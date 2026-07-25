"""Ledger-driven projector for the Kyber Graph.

The graph is a *projection*, not a second source of truth. Its input is the
append-only ``graph_mutation_ledger``, and everything about this module follows
from that:

**Per tenant.** ``GraphMutationLedgerRepository.list_records`` reads one
tenant's ledger, and offsets are stored per ``(projection, tenant)``. That is
not an accident of the read API — it is what keeps one tenant's poison row from
stalling the fleet. :meth:`KyberGraphProjector.project_all` isolates each tenant
so a failure is recorded against that tenant and the rest still advance.

**At least once, never at most once.** The offset advances only after a batch is
fully applied. A crash mid-batch therefore re-processes rows, which is safe
because :class:`~services.kyber.graph.repository.KyberGraphStore` upserts on
natural keys. The inverse — advancing first — would skip rows on a crash, and a
projection with a silent hole reads as "nothing happened there" forever.

**Topology and references only.** For each ledger row the projector upserts the
``Tenant`` node, its ``TenantGraph``, the ``GraphDomain`` the mutation touched,
and the ``OWNS_GRAPH`` / ``CONTAINS_DOMAIN`` edges between them. The row's
``payload`` is deliberately never read. Copying payload contents into node
properties would turn this table into a second, unscoped copy of tenant data —
the exact boundary violation the Kyber Graph exists to avoid — and it would do
so invisibly, because the resulting rows would look like ordinary topology.

**Freshness is reported, not assumed.** Lag is measured from the newest consumed
row's ``recorded_at``, and a failing tenant keeps its ``last_error`` and
``consecutive_failures`` on its offset row. A projection that is silently 6
hours behind is worse than one that is visibly down: the first still answers
questions.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime
from typing import Any, Callable, Coroutine, Optional

from repositories.graph_mutation_ledger import GraphMutationLedgerRepository
from services.kyber.graph.contracts import KyberGraphEdge, KyberGraphNode
from services.kyber.graph.repository import KyberGraphStore, kyber_graph_store
from shared.common.common import parse_iso, utc_now
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.kyber.graph.projector")

#: Offset row key. Changing this restarts the projection from zero, which is
#: safe (upserts converge) but re-reads every tenant's ledger.
PROJECTION_NAME = "kyber_graph"

#: ``list_records`` has no "since offset" parameter, so resumption is done by
#: over-fetching from the head of the tenant's ledger and dropping rows at or
#: below the stored offset. ``ledger_offset`` is a global BIGSERIAL, so the
#: window needed to reach `limit` fresh rows grows with the ledger; this ceiling
#: bounds the read. See ``fetch_window_exhausted`` in the result: when the
#: window fills with already-consumed rows the batch makes no progress and says
#: so rather than reporting a quiet success.
_MAX_LEDGER_FETCH = 20_000

_DEFAULT_INTERVAL_SECONDS = 60
_MIN_INTERVAL_SECONDS = 5


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning(f"kyber graph projector: {name}={raw!r} is not an int; using {default}")
        return default


def interval_seconds() -> int:
    """How often the supervised worker projects."""
    return max(
        _MIN_INTERVAL_SECONDS,
        _env_int("KYBER_GRAPH_PROJECTOR_INTERVAL_S", _DEFAULT_INTERVAL_SECONDS),
    )


class KyberGraphProjector:
    """Consumes the graph mutation ledger into Kyber Graph topology.

    Both the store and the ledger repository are injectable so the projector can
    be driven against fakes; the clock is injectable so lag and timestamps are
    assertable without sleeping.
    """

    def __init__(
        self,
        *,
        store: Optional[KyberGraphStore] = None,
        ledger: Optional[GraphMutationLedgerRepository] = None,
        clock: Optional[Callable[[], datetime]] = None,
        environment: Optional[str] = None,
    ) -> None:
        self.store = store or kyber_graph_store
        self.ledger = ledger or GraphMutationLedgerRepository()
        self._clock = clock or utc_now
        # Every projected node carries an environment: PostgreSQL treats NULLs
        # as distinct in a unique index, so an environment-less node would not
        # be deduped by ux_kyber_graph_nodes_key.
        self.environment = environment or os.getenv("AETHER_ENV", "local")

    # ── Clock ────────────────────────────────────────────────────────────────

    def _now(self) -> datetime:
        return self._clock()

    # ── One tenant ───────────────────────────────────────────────────────────

    async def project_tenant(self, tenant_id: str, *, limit: int = 500) -> dict[str, Any]:
        """Project one tenant's unconsumed ledger rows.

        Resumes from the durable offset and advances it only after the whole
        batch applied. On failure the offset is left where it was and the error
        is recorded on the offset row, so the next run re-processes the same
        range instead of skipping it.
        """
        offset = await self.store.offset_for(PROJECTION_NAME, tenant_id)
        start = int(offset.last_offset or 0)

        try:
            fetched = await self._fetch(tenant_id, start, limit)
            fresh = [row for row in fetched if _row_offset(row) > start]
            fresh.sort(key=_row_offset)
            fresh = fresh[:limit]
            projected = await self._apply(tenant_id, fresh)
        except Exception as exc:  # noqa: BLE001 - a bad tenant must not stall the fleet
            metrics.increment(
                "kyber_graph_projection_failures_total",
                labels={"projection": PROJECTION_NAME},
            )
            failed = offset.model_copy(
                update={
                    # last_offset is deliberately untouched: at-least-once.
                    "last_run_at": self._now().isoformat(),
                    "last_error": f"{type(exc).__name__}: {exc}"[:1000],
                    "consecutive_failures": int(offset.consecutive_failures or 0) + 1,
                }
            )
            await self.store.save_offset(failed)
            logger.error(f"kyber graph projection failed for tenant={tenant_id}: {exc}")
            return {
                "projection": PROJECTION_NAME,
                "tenant_id": tenant_id,
                "ok": False,
                "rows_processed": 0,
                "nodes_upserted": 0,
                "edges_upserted": 0,
                "from_offset": start,
                "last_offset": start,
                "lag_seconds": None,
                "error": failed.last_error,
                "consecutive_failures": failed.consecutive_failures,
                "fetch_window_exhausted": False,
            }

        highest = max([_row_offset(row) for row in fresh], default=start)
        advanced = offset.model_copy(
            update={
                "last_offset": max(start, highest),
                "last_run_at": self._now().isoformat(),
                "last_error": None,
                "consecutive_failures": 0,
            }
        )
        await self.store.save_offset(advanced)

        lag = self._emit_lag(fresh)
        # A full read window containing nothing new means the resume window
        # (see _MAX_LEDGER_FETCH) could not reach unconsumed rows. Nothing
        # failed, but no progress was made either, and a caller must be able to
        # tell that apart from "caught up".
        window_exhausted = not fresh and len(fetched) >= _MAX_LEDGER_FETCH
        result = {
            "projection": PROJECTION_NAME,
            "tenant_id": tenant_id,
            "ok": True,
            "rows_processed": len(fresh),
            "nodes_upserted": projected["nodes"],
            "edges_upserted": projected["edges"],
            "rows_without_domain": projected["rows_without_domain"],
            "from_offset": start,
            "last_offset": advanced.last_offset,
            "lag_seconds": lag,
            "error": None,
            "consecutive_failures": 0,
            "fetch_window_exhausted": window_exhausted,
        }
        if result["rows_processed"]:
            logger.info(
                f"kyber graph projection tenant={tenant_id} rows={len(fresh)} "
                f"nodes={projected['nodes']} edges={projected['edges']} "
                f"offset={start}->{advanced.last_offset}"
            )
        return result

    async def _fetch(self, tenant_id: str, start: int, limit: int) -> list[dict[str, Any]]:
        """Read the next ``limit`` unconsumed rows of the tenant's ledger.

        ``since_offset`` pushes the resume point into the query, so the window
        is ``limit`` rows regardless of how long the ledger has grown. The
        client-side ``_MAX_LEDGER_FETCH`` ceiling stays as a backstop for a
        ledger implementation that ignores the argument: if one ever does, the
        batch reports ``fetch_window_exhausted`` instead of quietly making no
        progress forever.
        """
        window = min(max(limit, 1), _MAX_LEDGER_FETCH)
        return await self.ledger.list_records(
            tenant_id, aggregate_id=None, limit=window, since_offset=start
        )

    async def _apply(
        self, tenant_id: str, rows: list[dict[str, Any]]
    ) -> dict[str, int]:
        """Upsert the topology implied by ``rows``.

        Rows are collapsed to distinct nodes and edges first — a 500-row batch
        touching one tenant implies one ``Tenant`` node, not 500 writes — keeping
        the newest provenance for each key so the batch's own ordering cannot
        regress ``source_offset``.
        """
        nodes: dict[str, KyberGraphNode] = {}
        edges: dict[str, KyberGraphEdge] = {}
        rows_without_domain = 0

        for row in rows:
            row_offset = _row_offset(row)
            event_id = row.get("source_event_id") or row.get("mutation_id")
            # NOTE: row["payload"] is never read. The graph stores references
            # into tenant data, never the data.
            tenant_key = f"tenant:{tenant_id}"
            graph_key = f"tenant_graph:{tenant_id}"

            _keep_node(
                nodes,
                KyberGraphNode(
                    node_key=tenant_key,
                    node_type="Tenant",
                    environment=self.environment,
                    tenant_id=tenant_id,
                    display_name=tenant_id,
                    properties={"derived_from": "graph_mutation_ledger"},
                    source_event_id=event_id,
                    source_offset=row_offset,
                ),
            )
            _keep_node(
                nodes,
                KyberGraphNode(
                    node_key=graph_key,
                    node_type="TenantGraph",
                    environment=self.environment,
                    tenant_id=tenant_id,
                    display_name=f"{tenant_id} graph",
                    properties={"derived_from": "graph_mutation_ledger"},
                    source_event_id=event_id,
                    source_offset=row_offset,
                ),
            )
            _keep_edge(
                edges,
                KyberGraphEdge(
                    source_node_key=tenant_key,
                    target_node_key=graph_key,
                    relationship_type="OWNS_GRAPH",
                    environment=self.environment,
                    tenant_id=tenant_id,
                    source_event_id=event_id,
                    source_offset=row_offset,
                ),
            )

            domain = row.get("aggregate_type")
            if not domain:
                # An unclassified mutation is counted, not guessed at: inventing
                # a domain would put a node in the graph that no contract backs.
                rows_without_domain += 1
                continue
            domain_key = f"graph_domain:{tenant_id}:{domain}"
            _keep_node(
                nodes,
                KyberGraphNode(
                    node_key=domain_key,
                    node_type="GraphDomain",
                    environment=self.environment,
                    tenant_id=tenant_id,
                    display_name=str(domain),
                    properties={
                        "aggregate_type": str(domain),
                        "derived_from": "graph_mutation_ledger",
                    },
                    source_event_id=event_id,
                    source_offset=row_offset,
                ),
            )
            _keep_edge(
                edges,
                KyberGraphEdge(
                    source_node_key=graph_key,
                    target_node_key=domain_key,
                    relationship_type="CONTAINS_DOMAIN",
                    environment=self.environment,
                    tenant_id=tenant_id,
                    source_event_id=event_id,
                    source_offset=row_offset,
                ),
            )

        for node in nodes.values():
            await self.store.upsert_node(node)
        for edge in edges.values():
            await self.store.upsert_edge(edge)

        return {
            "nodes": len(nodes),
            "edges": len(edges),
            "rows_without_domain": rows_without_domain,
        }

    def _emit_lag(self, rows: list[dict[str, Any]]) -> Optional[float]:
        """Projection lag from the newest consumed row, in seconds."""
        newest: Optional[datetime] = None
        for row in rows:
            recorded = row.get("recorded_at")
            if not recorded:
                continue
            try:
                parsed = parse_iso(str(recorded))
            except (TypeError, ValueError):
                continue
            if parsed is not None and (newest is None or parsed > newest):
                newest = parsed
        if newest is None:
            return None
        lag = max(0.0, (self._now() - newest).total_seconds())
        metrics.gauge(
            "kyber_graph_projection_lag_seconds",
            lag,
            labels={"projection": PROJECTION_NAME},
        )
        return lag

    # ── The fleet ────────────────────────────────────────────────────────────

    async def project_all(
        self, *, tenant_ids: Optional[list[str]] = None
    ) -> dict[str, Any]:
        """Project every known tenant, isolating failures per tenant.

        When ``tenant_ids`` is omitted the roster is derived from tenants this
        projection already knows: existing offset rows plus ``Tenant`` nodes. A
        tenant that has never been projected and is not passed in is reported as
        a ``missing_inputs`` gap — the ledger read is per tenant, so a roster is
        a genuine input this module does not own and must not fabricate.
        """
        targets = list(tenant_ids) if tenant_ids is not None else await self._known_tenants()
        results: list[dict[str, Any]] = []
        for tenant_id in targets:
            try:
                results.append(await self.project_tenant(tenant_id))
            except Exception as exc:  # noqa: BLE001 - isolate one tenant's failure
                metrics.increment(
                    "kyber_graph_projection_failures_total",
                    labels={"projection": PROJECTION_NAME},
                )
                logger.error(f"kyber graph projection crashed for tenant={tenant_id}: {exc}")
                results.append(
                    {
                        "projection": PROJECTION_NAME,
                        "tenant_id": tenant_id,
                        "ok": False,
                        "rows_processed": 0,
                        "nodes_upserted": 0,
                        "edges_upserted": 0,
                        "error": f"{type(exc).__name__}: {exc}"[:1000],
                    }
                )

        missing: list[str] = []
        if not targets:
            missing.append("tenant_ids")
        return {
            "projection": PROJECTION_NAME,
            "environment": self.environment,
            "tenants": len(targets),
            "ok_tenants": sum(1 for r in results if r.get("ok")),
            "failed_tenants": sum(1 for r in results if not r.get("ok")),
            "rows_processed": sum(int(r.get("rows_processed") or 0) for r in results),
            "nodes_upserted": sum(int(r.get("nodes_upserted") or 0) for r in results),
            "edges_upserted": sum(int(r.get("edges_upserted") or 0) for r in results),
            "missing_inputs": missing,
            "results": results,
            "computed_at": self._now().isoformat(),
        }

    async def _known_tenants(self) -> list[str]:
        """Tenants this projection has seen: offset rows plus ``Tenant`` nodes."""
        known: set[str] = set()
        for offset in await self.store.list_offsets(PROJECTION_NAME):
            if offset.tenant_id:
                known.add(offset.tenant_id)
        for node in await self.store.find_nodes(
            node_type="Tenant", environment=self.environment, limit=1000
        ):
            if node.tenant_id:
                known.add(node.tenant_id)
        return sorted(known)


#: Process-wide projector.
kyber_graph_projector = KyberGraphProjector()


class KyberGraphProjectorWorker:
    """Long-running projection loop for a supervised runtime role."""

    def __init__(self, projector: Optional[KyberGraphProjector] = None) -> None:
        self.projector = projector or kyber_graph_projector
        self._running = False

    async def run_forever(self) -> None:
        self._running = True
        logger.info("kyber graph projector worker started")
        while self._running:
            try:
                await self.projector.project_all()
            except asyncio.CancelledError:  # pragma: no cover - shutdown path
                raise
            except Exception as exc:  # noqa: BLE001 - the loop must survive
                logger.error(f"kyber graph projection sweep failed: {exc}")
                metrics.increment(
                    "kyber_graph_projection_failures_total",
                    labels={"projection": PROJECTION_NAME},
                )
            await asyncio.sleep(interval_seconds())

    def stop(self) -> None:  # pragma: no cover - shutdown path
        self._running = False


def build_kyber_graph_projector_coro() -> Coroutine:
    """Zero-arg factory: a fresh supervised Kyber Graph projection coroutine.

    Same shape as ``services.kyber.retention.build_kyber_retention_coro`` so the
    runtime supervisor registers it as an ordinary ``WorkerSpec`` factory
    without a special case.
    """
    return KyberGraphProjectorWorker().run_forever()


def _row_offset(row: dict[str, Any]) -> int:
    """A ledger row's position, defaulting to 0 when the backend omits it."""
    try:
        return int(row.get("ledger_offset") or 0)
    except (TypeError, ValueError):
        return 0


def _keep_node(acc: dict[str, KyberGraphNode], node: KyberGraphNode) -> None:
    """Keep the newest provenance for a node key inside one batch."""
    current = acc.get(node.node_key)
    if current is None or (node.source_offset or 0) >= (current.source_offset or 0):
        acc[node.node_key] = node


def _keep_edge(acc: dict[str, KyberGraphEdge], edge: KyberGraphEdge) -> None:
    """Keep the newest provenance for an edge key inside one batch."""
    current = acc.get(edge.idempotency_key)
    if current is None or (edge.source_offset or 0) >= (current.source_offset or 0):
        acc[edge.idempotency_key] = edge


__all__ = [
    "PROJECTION_NAME",
    "KyberGraphProjector",
    "KyberGraphProjectorWorker",
    "build_kyber_graph_projector_coro",
    "interval_seconds",
    "kyber_graph_projector",
]
