"""Durable card-linked → graph projection outbox.

Replaces the previous best-effort ``_project_to_graph`` (which swallowed every
graph failure) with a durable, reconcilable outbox:

  * the durable card-linked FLOW store remains the single source of truth;
  * each newly-created flow enqueues idempotent projection rows (one catalog
    row per (tenant, program) + one flow row per (tenant, flow)) into the
    ``card_linked_graph_outbox`` durable store;
  * a worker drains queued/retry-due rows through the canonical
    :class:`~shared.graph.mutation_gateway.GraphMutationGateway` — we add NO
    new direct graph writer, so the graph write-path freeze gate stays green —
    with bounded retry, exponential backoff and dead-lettering (reusing the
    shared :class:`~shared.outbox.GenericOutboxWorker`);
  * :meth:`CardLinkedGraphProjectionOutbox.reconcile` compares the flow store
    against the outbox and surfaces drift (never-enqueued flows, dead-letters,
    pending rows) with health metrics;
  * :meth:`CardLinkedGraphProjectionOutbox.repair` is the operator replay entry
    point: it re-enqueues missing projections and resets dead-lettered rows for
    another drain.

Everything is tenant-scoped: rows are keyed ``{tenant_id}:{kind}:{id}`` and every
read filters on ``tenant_id`` so one tenant can never drain or reconcile another.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from shared.logger.logger import get_logger, metrics
from shared.outbox import (
    GenericOutboxWorker,
    STATUS_DEAD_LETTERED,
    STATUS_FAILED,
    STATUS_PERSISTED,
    STATUS_PROCESSING,
    STATUS_QUEUED,
)
from shared.store import get_store

logger = get_logger("aether.card_linked.graph_outbox")

OUTBOX_STORE_NAME = "card_linked_graph_outbox"

KIND_FLOW = "flow"
KIND_CATALOG = "catalog"

_PENDING_STATUSES = (STATUS_QUEUED, STATUS_FAILED, STATUS_PROCESSING)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def should_project(record: dict[str, Any]) -> bool:
    """A flow projects to the graph unless it is a benchmark-only observation.

    Mirrors the honesty rule in ``graph_projector.build_flow_mutations`` so the
    reconciler's notion of "should have a projection" matches what the sink
    would actually write.
    """
    return (
        record.get("basis") != "benchmark_only"
        and record.get("reconciliation_state") != "benchmark_only"
    )


class CardLinkedGraphOutboxRepository:
    """``get_store``-backed outbox table.

    Reuses the card-linked package's durable substrate (the same
    ``shared.store`` abstraction the five flow/benchmark/health/recon/audit
    stores use — Redis in prod, in-memory locally) and exposes the
    :class:`~shared.outbox.GenericOutboxWorker` repo contract
    (``find_many`` / ``insert``) plus enqueue/list helpers. No new Alembic
    table is required — this is the same durability model as its sibling
    stores.
    """

    def __init__(self) -> None:
        self._store = get_store(OUTBOX_STORE_NAME)

    async def enqueue(self, row: dict) -> tuple[dict, str]:
        """Idempotent enqueue keyed on ``outbox_id``.

        Returns ``(row, "enqueued" | "duplicate")``. A duplicate is a
        structural no-op so replays/retries never double-project.
        """
        outbox_id = row["outbox_id"]
        existing = await self._store.get(outbox_id)
        if existing is not None:
            return existing, "duplicate"
        await self._store.set(outbox_id, row)
        metrics.increment(
            "card_linked_graph_outbox_enqueued_total",
            labels={"kind": row.get("kind", KIND_FLOW)},
        )
        return row, "enqueued"

    # ── GenericOutboxWorker repo contract ────────────────────────────────────

    async def find_many(
        self,
        *,
        filters: Optional[dict] = None,
        limit: int = 100,
        sort_by: str = "created_at",
        sort_order: str = "asc",
        offset: int = 0,
    ) -> list[dict]:
        rows = await self._store.find(**(filters or {}))
        rows.sort(key=lambda r: r.get(sort_by) or "", reverse=(sort_order == "desc"))
        return rows[offset : offset + limit]

    async def insert(self, row_id: str, data: dict) -> dict:
        await self._store.set(row_id, data)
        return data

    # ── convenience reads (tenant-scoped) ────────────────────────────────────

    async def get(self, outbox_id: str) -> Optional[dict]:
        return await self._store.get(outbox_id)

    async def list_for_tenant(self, tenant_id: str, limit: int = 100_000) -> list[dict]:
        rows = await self._store.find(tenant_id=tenant_id)
        rows.sort(key=lambda r: r.get("created_at") or "")
        return rows[:limit]


class CardLinkedGraphProjectionOutbox:
    """Enqueue + reconcile + repair facade over the outbox repository."""

    def __init__(self, repo: Optional[CardLinkedGraphOutboxRepository] = None) -> None:
        self._repo = repo or CardLinkedGraphOutboxRepository()

    @property
    def repo(self) -> CardLinkedGraphOutboxRepository:
        return self._repo

    @staticmethod
    def _flow_outbox_id(tenant_id: str, flow_id: str) -> str:
        return f"{tenant_id}:{KIND_FLOW}:{flow_id}"

    @staticmethod
    def _catalog_outbox_id(tenant_id: str, slug: str) -> str:
        return f"{tenant_id}:{KIND_CATALOG}:{slug}"

    def _new_row(
        self,
        tenant_id: str,
        outbox_id: str,
        kind: str,
        payload: dict,
        *,
        flow_id: Optional[str] = None,
        program_slug: Optional[str] = None,
    ) -> dict:
        ts = _now_iso()
        return {
            "id": outbox_id,
            "outbox_id": outbox_id,
            "tenant_id": tenant_id,
            "kind": kind,
            "status": STATUS_QUEUED,
            "attempts": 0,
            "flow_id": flow_id,
            "program_slug": program_slug,
            "payload": payload,
            "next_attempt_at": None,
            "last_error": None,
            "created_at": ts,
            "updated_at": ts,
        }

    async def enqueue_projection(self, tenant_id: str, record: dict) -> list[str]:
        """Durably enqueue the projection rows for one created flow.

        Benchmark-only flows are never projected. The catalog row is enqueued
        once per (tenant, program) — the durable dedup replaces the old
        process-local ``_projected_programs`` cache. Returns the outbox ids
        newly enqueued (duplicates are skipped).
        """
        if not should_project(record):
            return []
        enqueued: list[str] = []
        slug = record.get("card_program_id")
        if slug:
            cid = self._catalog_outbox_id(tenant_id, slug)
            _, disp = await self._repo.enqueue(
                self._new_row(
                    tenant_id, cid, KIND_CATALOG,
                    {"program_slug": slug}, program_slug=slug,
                )
            )
            if disp == "enqueued":
                enqueued.append(cid)
        flow_id = record["id"]
        fid = self._flow_outbox_id(tenant_id, flow_id)
        _, disp = await self._repo.enqueue(
            self._new_row(
                tenant_id, fid, KIND_FLOW,
                {"record": dict(record)}, flow_id=flow_id, program_slug=slug,
            )
        )
        if disp == "enqueued":
            enqueued.append(fid)
        return enqueued

    # ── reconciliation + repair ──────────────────────────────────────────────

    async def _projectable_flows(self, tenant_id: str) -> list[dict]:
        from services.card_linked_payments.repositories import (
            get_card_linked_repositories,
        )

        flows = await get_card_linked_repositories().flows.list_for_tenant(
            tenant_id, limit=100_000
        )
        return [f for f in flows if should_project(f)]

    async def reconcile(self, tenant_id: str) -> dict:
        """Drift report between the flow store (truth) and the outbox/graph.

        Emits health/drift metrics and returns counts an operator can act on.
        """
        projectable = await self._projectable_flows(tenant_id)
        rows = await self._repo.list_for_tenant(tenant_id)
        flow_rows = {r.get("flow_id"): r for r in rows if r.get("kind") == KIND_FLOW}

        missing = [f for f in projectable if f["id"] not in flow_rows]
        dead = [r for r in rows if r.get("status") == STATUS_DEAD_LETTERED]
        pending = [r for r in rows if r.get("status") in _PENDING_STATUSES]
        persisted = [r for r in rows if r.get("status") == STATUS_PERSISTED]
        drift = len(missing) + len(dead)

        metrics.gauge(
            "card_linked_graph_projection_drift", float(drift),
            labels={"tenant_id": tenant_id},
        )
        metrics.gauge(
            "card_linked_graph_outbox_pending", float(len(pending)),
            labels={"tenant_id": tenant_id},
        )
        metrics.gauge(
            "card_linked_graph_outbox_dead_lettered", float(len(dead)),
            labels={"tenant_id": tenant_id},
        )
        return {
            "tenant_id": tenant_id,
            "projectable_flows": len(projectable),
            "outbox_rows": len(rows),
            "persisted": len(persisted),
            "pending": len(pending),
            "dead_lettered": len(dead),
            "missing_projection": len(missing),
            "missing_flow_ids": sorted(f["id"] for f in missing),
            "drift": drift,
            "healthy": drift == 0,
        }

    async def repair(
        self,
        tenant_id: str,
        *,
        enqueue_missing: bool = True,
        replay_dead_letters: bool = True,
    ) -> dict:
        """Operator repair/replay entry point.

        Re-enqueues never-projected flows and resets dead-lettered rows back to
        ``queued`` (attempts cleared) so the next worker drain reprocesses them.
        Idempotent: re-enqueue is a no-op for rows that already exist.
        """
        re_enqueued = 0
        replayed = 0
        if enqueue_missing:
            projectable = await self._projectable_flows(tenant_id)
            rows = await self._repo.list_for_tenant(tenant_id)
            have = {r.get("flow_id") for r in rows if r.get("kind") == KIND_FLOW}
            for flow in projectable:
                if flow["id"] not in have:
                    new_ids = await self.enqueue_projection(tenant_id, flow)
                    if new_ids:
                        re_enqueued += 1
        if replay_dead_letters:
            rows = await self._repo.list_for_tenant(tenant_id)
            for row in rows:
                if row.get("status") == STATUS_DEAD_LETTERED:
                    revived = {
                        **row,
                        "status": STATUS_QUEUED,
                        "attempts": 0,
                        "next_attempt_at": None,
                        "last_error": None,
                        "updated_at": _now_iso(),
                    }
                    await self._repo.insert(row["outbox_id"], revived)
                    replayed += 1
        metrics.increment(
            "card_linked_graph_outbox_repaired_total",
            value=re_enqueued + replayed,
            labels={"tenant_id": tenant_id},
        )
        return {
            "tenant_id": tenant_id,
            "re_enqueued_missing": re_enqueued,
            "replayed_dead_letters": replayed,
        }


class CardLinkedGraphOutboxWorker:
    """Drains the card-linked graph outbox through the canonical mutation
    gateway. The projection sink is the only card-linked-specific logic; retry
    backoff, dead-lettering and status transitions come from the shared worker.
    """

    def __init__(
        self,
        repo: Optional[CardLinkedGraphOutboxRepository] = None,
        graph_client: Any = None,
        *,
        max_attempts: int = 5,
    ) -> None:
        self._repo = repo or CardLinkedGraphOutboxRepository()
        self._graph = graph_client
        self._worker = GenericOutboxWorker(
            repo=self._repo,
            sink=self._project,
            name="card_linked_graph_outbox",
            max_attempts=max_attempts,
            backoff_base_s=1.0,
            backoff_cap_s=300.0,
            success_status=STATUS_PERSISTED,
        )

    def _client(self) -> Any:
        if self._graph is None:
            from dependencies.providers import get_graph

            self._graph = get_graph()
        return self._graph

    async def _project(self, row: dict) -> None:
        """One outbox row → catalog or flow graph mutations, all through the
        GraphMutationGateway. Raising signals a failed attempt (retried)."""
        from shared.graph.mutation_gateway import GraphMutationGateway
        from shared.graph.mutation_intents import edge_intent, vertex_intent

        from services.card_linked_payments.graph_projector import (
            build_catalog_mutations,
            build_flow_mutations,
        )

        kind = row.get("kind", KIND_FLOW)
        tenant_id = str(row.get("tenant_id", ""))
        payload = row.get("payload") or {}
        gateway = GraphMutationGateway(graph_client=self._client())

        if kind == KIND_CATALOG:
            from services.payment_catalog.catalog import PAYMENTSCAN_CARD_PROGRAMS

            slug = payload.get("program_slug")
            entity = next(
                (e for e in PAYMENTSCAN_CARD_PROGRAMS if e.slug == slug), None
            )
            if entity is None:
                return  # unknown program → nothing to project (terminal success)
            vertices, edges = build_catalog_mutations(
                tenant_id,
                {
                    "slug": entity.slug,
                    "display_name": entity.display_name,
                    "source": entity.source,
                    "status": entity.status,
                },
            )
        else:
            record = payload.get("record") or {}
            vertices, edges = build_flow_mutations(record)

        for vertex in vertices:
            await gateway.apply(
                vertex_intent(
                    vertex, operation="node_versioned",
                    tenant_id=tenant_id, actor_id="card_linked_ingestion",
                )
            )
        for edge in edges:
            await gateway.apply(
                edge_intent(
                    edge, operation="edge_created",
                    tenant_id=tenant_id, actor_id="card_linked_ingestion",
                )
            )

    async def drain_once(
        self, tenant_id: Optional[str] = None, limit: int = 100
    ) -> dict:
        """Process one bounded batch. Pass ``tenant_id`` to stay tenant-scoped."""
        return await self._worker.drain_once(tenant_id=tenant_id, limit=limit)

    def build_coro(self):
        """Zero-arg coroutine factory for supervisor wiring."""
        return self._worker.build_coro()
