"""Durable retry and operator recovery for agent graph projections."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
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

logger = get_logger("aether.agent_marketplace.projection")
OUTBOX_STORE_NAME = "agent_marketplace_graph_outbox"
_PROCESSING_STALE_SECONDS = 300


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mutation_payload(mutation: Any) -> dict[str, Any]:
    from shared.graph.graph import Edge, Vertex

    if isinstance(mutation, Vertex):
        return {
            "kind": "vertex",
            "vertex_type": mutation.vertex_type,
            "vertex_id": mutation.vertex_id,
            "properties": mutation.properties,
            "created_at": mutation.created_at,
        }
    if isinstance(mutation, Edge):
        return {
            "kind": "edge",
            "edge_type": mutation.edge_type,
            "from_vertex_id": mutation.from_vertex_id,
            "to_vertex_id": mutation.to_vertex_id,
            "properties": mutation.properties,
            "created_at": mutation.created_at,
        }
    raise TypeError(f"unsupported graph mutation: {type(mutation).__name__}")


def _mutation_key(payload: dict[str, Any]) -> str:
    if payload["kind"] == "vertex":
        identity = ["vertex", payload["vertex_type"], payload["vertex_id"]]
    else:
        identity = [
            "edge", payload["edge_type"], payload["from_vertex_id"],
            payload["to_vertex_id"],
        ]
    return json.dumps(identity, ensure_ascii=False, separators=(",", ":"))


def _processing_is_stale(value: Any) -> bool:
    if not value:
        return True
    try:
        instant = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - instant).total_seconds() >= _PROCESSING_STALE_SECONDS
    except ValueError:
        return True


def _encode_tenant_source_cursor(
    tenant_id: str, *, deployment_cursor: Optional[str], deployment_done: bool,
    silver_cursor: Optional[str], silver_done: bool,
) -> str:
    payload = json.dumps({
        "v": 1,
        "scope": "tenant_agent_sources",
        "tenant_id": tenant_id,
        "deployment_cursor": deployment_cursor,
        "deployment_done": deployment_done,
        "silver_cursor": silver_cursor,
        "silver_done": silver_done,
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_tenant_source_cursor(cursor: Optional[str], tenant_id: str) -> dict[str, Any]:
    if cursor is None:
        return {
            "deployment_cursor": None, "deployment_done": False,
            "silver_cursor": None, "silver_done": False,
        }
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid tenant source page cursor") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("v") != 1
        or payload.get("scope") != "tenant_agent_sources"
        or payload.get("tenant_id") != tenant_id
        or not isinstance(payload.get("deployment_done"), bool)
        or not isinstance(payload.get("silver_done"), bool)
        or payload.get("deployment_cursor") is not None
        and not isinstance(payload.get("deployment_cursor"), str)
        or payload.get("silver_cursor") is not None
        and not isinstance(payload.get("silver_cursor"), str)
    ):
        raise ValueError("tenant source page cursor does not match this tenant")
    return payload


class AgentMarketplaceGraphOutboxRepository:
    """Store-backed outbox; Redis/Dynamo are durable in deployed profiles."""

    def __init__(self) -> None:
        self._store = get_store(OUTBOX_STORE_NAME)

    @staticmethod
    def outbox_id(tenant_id: str, payload: dict[str, Any]) -> str:
        material = json.dumps(
            [tenant_id, _mutation_key(payload)], ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    async def enqueue(self, tenant_id: str, source_event_id: str, payload: dict[str, Any]) -> tuple[dict, bool]:
        outbox_id = self.outbox_id(tenant_id, payload)
        existing = await self._store.get(outbox_id)
        if existing is not None:
            return existing, False
        row = {
            "id": outbox_id,
            "outbox_id": outbox_id,
            "tenant_id": tenant_id,
            "source_event_id": source_event_id,
            "status": STATUS_QUEUED,
            "attempts": 0,
            "next_attempt_at": None,
            "last_error": None,
            "payload": payload,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        await self._store.set(outbox_id, row)
        metrics.increment("agent_marketplace_graph_outbox_enqueued_total")
        return row, True

    async def find_many(
        self, *, filters: Optional[dict] = None, limit: int = 100,
        sort_by: str = "created_at", sort_order: str = "asc", offset: int = 0,
    ) -> list[dict]:
        rows = await self._store.find(**(filters or {}))
        rows.sort(key=lambda row: row.get(sort_by) or "", reverse=(sort_order == "desc"))
        return rows[offset:offset + limit]

    async def insert(self, row_id: str, data: dict) -> dict:
        await self._store.set(row_id, data)
        return data

    async def get(self, row_id: str) -> Optional[dict]:
        return await self._store.get(row_id)

    async def list_for_tenant(self, tenant_id: str, limit: int = 100_000) -> list[dict]:
        rows = await self._store.find(tenant_id=tenant_id)
        rows.sort(key=lambda row: row.get("created_at") or "")
        return rows[:limit]

    async def list_for_tenant_page(
        self, tenant_id: str, *, limit: int, cursor: Optional[str] = None,
    ) -> tuple[list[dict], Optional[str], bool]:
        return await self._store.find_page(
            limit=limit, cursor=cursor, tenant_id=tenant_id,
        )


class AgentMarketplaceGraphProjectionOutbox:
    """Enqueue, reconcile, repair, and replay agent graph mutations."""

    def __init__(self, repo: AgentMarketplaceGraphOutboxRepository | None = None) -> None:
        self.repo = repo or AgentMarketplaceGraphOutboxRepository()

    async def enqueue_mutations(
        self, tenant_id: str, source_event_id: str, mutations: list[Any],
    ) -> dict[str, Any]:
        queued = 0
        duplicates = 0
        existing_statuses: list[str] = []
        for mutation in mutations:
            row, created = await self.repo.enqueue(
                tenant_id, source_event_id, _mutation_payload(mutation)
            )
            queued += int(created)
            duplicates += int(not created)
            if not created:
                existing_statuses.append(str(row.get("status") or "unknown"))
        if queued:
            projection_status = "queued"
        elif existing_statuses and all(status == STATUS_PERSISTED for status in existing_statuses):
            projection_status = "persisted"
        elif any(status in {STATUS_FAILED, STATUS_DEAD_LETTERED} for status in existing_statuses):
            projection_status = "partial"
        else:
            projection_status = "queued"
        return {
            "queued": queued,
            "duplicates": duplicates,
            "graph_projection_status": projection_status,
        }

    async def _expected_mutations(
        self, tenant_id: str, limit: int, *, cursor: Optional[str] = None,
    ) -> tuple[list[tuple[str, Any]], bool, Optional[str]]:
        from actions.agent.deployments import get_deployment_repository
        from actions.agent_marketplace.authority import AgentRunAuthorityResolver
        from actions.agent_marketplace.catalog import MarketplaceCatalogRepository
        from actions.agent_marketplace.lineage import build_marketplace_origin_mutations
        from config.settings import settings
        from dependencies.providers import get_cache
        from ingestion.silver.projectors.silver_graph_projector import (
            build_external_agent_run_mutations,
        )
        from repositories.repos import AnalyticsRepository

        expected: list[tuple[str, Any]] = []
        if tenant_id == "platform":
            from actions.agent_marketplace.lineage import (
                build_public_marketplace_listing_mutations,
            )

            rows, next_cursor, truncated = await MarketplaceCatalogRepository().list_projection_observations(
                limit=limit, cursor=cursor,
            )
            for row in rows:
                source_event_id = f"marketplace_catalog:{row.get('source_namespace')}:{row.get('observation_id') or row.get('id')}"
                expected.extend(
                    (source_event_id, mutation)
                    for mutation in build_public_marketplace_listing_mutations(row)
                )
            return expected, truncated, next_cursor

        cursor_state = _decode_tenant_source_cursor(cursor, tenant_id)
        deployments_done = bool(cursor_state["deployment_done"])
        silver_done = bool(cursor_state["silver_done"])
        deployment_cursor = cursor_state.get("deployment_cursor")
        silver_cursor = cursor_state.get("silver_cursor")

        deployments: list[dict[str, Any]] = []
        if not deployments_done:
            deployments, deployment_cursor, deployment_truncated = (
                await get_deployment_repository().list_page(
                    tenant_id, limit=limit, cursor=deployment_cursor,
                )
            )
            deployments_done = not deployment_truncated
        for deployment in deployments:
            if deployment.get("marketplace_origin"):
                for mutation in build_marketplace_origin_mutations(deployment):
                    expected.append((str(deployment.get("id") or ""), mutation))

        if settings.external_agent_telemetry.graph_enabled and not silver_done:
            rows, silver_cursor, silver_truncated = await AnalyticsRepository(
                get_cache()
            ).query_silver_page(
                "silver_agent_execution_facts", {"tenant_id": tenant_id},
                limit=limit, cursor=silver_cursor,
            )
            silver_done = not silver_truncated
            authority_resolver = AgentRunAuthorityResolver()
            for row in rows:
                authority_links = await authority_resolver.resolve(row)
                mutations = build_external_agent_run_mutations(row, authority_links)
                source_event_id = str(row.get("source_event_id") or "")
                if source_event_id:
                    expected.extend((source_event_id, mutation) for mutation in mutations)
        else:
            silver_done = True

        truncated = not deployments_done or not silver_done
        next_cursor = (
            _encode_tenant_source_cursor(
                tenant_id,
                deployment_cursor=deployment_cursor,
                deployment_done=deployments_done,
                silver_cursor=silver_cursor,
                silver_done=silver_done,
            )
            if truncated else None
        )
        return expected, truncated, next_cursor

    async def reconcile(
        self, tenant_id: str, *, limit: int = 500, cursor: Optional[str] = None,
        outbox_cursor: Optional[str] = None,
    ) -> dict[str, Any]:
        outbox_limit = min(limit * 10, 1_000)
        rows, outbox_next_cursor, outbox_truncated = await self.repo.list_for_tenant_page(
            tenant_id, limit=outbox_limit, cursor=outbox_cursor,
        )
        by_status = {
            status: sum(1 for row in rows if row.get("status") == status)
            for status in (STATUS_QUEUED, STATUS_PROCESSING, STATUS_FAILED, STATUS_DEAD_LETTERED, STATUS_PERSISTED)
        }
        expected, truncated, next_cursor = await self._expected_mutations(
            tenant_id, limit, cursor=cursor,
        )
        semaphore = asyncio.Semaphore(24)

        async def is_missing(mutation: Any) -> bool:
            outbox_id = self.repo.outbox_id(tenant_id, _mutation_payload(mutation))
            async with semaphore:
                return await self.repo.get(outbox_id) is None

        missing_flags = await asyncio.gather(*(is_missing(mutation) for _, mutation in expected))
        missing = [
            mutation for (_, mutation), is_absent in zip(expected, missing_flags)
            if is_absent
        ]
        stale_processing = sum(
            1 for row in rows
            if row.get("status") == STATUS_PROCESSING
            and _processing_is_stale(row.get("updated_at"))
        )
        return {
            "tenant_id": tenant_id,
            "outbox_rows": len(rows),
            "by_status": by_status,
            "stale_processing": stale_processing,
            "source_mutations_checked": len(expected),
            "missing_outbox_rows": len(missing),
            "missing_outbox_mutations": [
                self.repo.outbox_id(tenant_id, _mutation_payload(mutation))
                for mutation in missing[:50]
            ],
            "missing_truncated": len(missing) > 50,
            "source_scan_limit": limit,
            "source_scan_truncated": truncated,
            "source_next_cursor": next_cursor,
            "outbox_scan_limit": outbox_limit,
            "outbox_scan_truncated": outbox_truncated,
            "outbox_next_cursor": outbox_next_cursor,
            "scan_consistency": "best_effort_non_snapshot",
            "scan_pages_exhausted": not truncated and not outbox_truncated,
            "graph_state_checked": False,
        }

    async def repair(
        self, tenant_id: str, *, enqueue_missing: bool = True,
        replay_dead_letters: bool = True, replay_persisted: bool = False,
        limit: int = 500, cursor: Optional[str] = None,
        outbox_cursor: Optional[str] = None,
    ) -> dict[str, Any]:
        enqueued = 0
        source_truncated = False
        source_next_cursor = None
        outbox_truncated = False
        outbox_limit = min(limit * 10, 1_000)
        if enqueue_missing:
            expected, source_truncated, source_next_cursor = await self._expected_mutations(
                tenant_id, limit, cursor=cursor,
            )
            for source_event_id, mutation in expected:
                payload = _mutation_payload(mutation)
                if await self.repo.get(self.repo.outbox_id(tenant_id, payload)) is None:
                    _, created = await self.repo.enqueue(tenant_id, source_event_id, payload)
                    enqueued += int(created)

        reset = 0
        statuses = {STATUS_DEAD_LETTERED} if replay_dead_letters else set()
        if replay_persisted:
            statuses.add(STATUS_PERSISTED)
        recovery_rows, outbox_next_cursor, outbox_truncated = await self.repo.list_for_tenant_page(
            tenant_id, limit=outbox_limit, cursor=outbox_cursor,
        )
        for row in recovery_rows:
            status = row.get("status")
            recoverable = status in statuses or (
                status == STATUS_PROCESSING and _processing_is_stale(row.get("updated_at"))
            )
            if not recoverable:
                continue
            revived = {
                **row,
                "status": STATUS_QUEUED,
                "attempts": 0,
                "next_attempt_at": None,
                "last_error": None,
                "updated_at": _now_iso(),
            }
            await self.repo.insert(str(row["outbox_id"]), revived)
            reset += 1
        return {
            "tenant_id": tenant_id,
            "enqueued_missing": enqueued,
            "requeued_terminal": reset,
            "source_scan_performed": enqueue_missing,
            "source_scan_limit": limit,
            "source_scan_truncated": source_truncated,
            "source_next_cursor": source_next_cursor,
            "outbox_scan_limit": outbox_limit,
            "outbox_scan_truncated": outbox_truncated,
            "outbox_next_cursor": outbox_next_cursor,
            "scan_consistency": "best_effort_non_snapshot",
            "scan_pages_exhausted": (not enqueue_missing or not source_truncated)
            and not outbox_truncated,
        }


class AgentMarketplaceGraphOutboxWorker:
    """Replay serialized mutations through the canonical graph gateway."""

    def __init__(self, repo: AgentMarketplaceGraphOutboxRepository | None = None) -> None:
        self.repo = repo or AgentMarketplaceGraphOutboxRepository()
        self._worker = GenericOutboxWorker(
            repo=self.repo,
            sink=self._project,
            name=OUTBOX_STORE_NAME,
            max_attempts=8,
            backoff_base_s=1.0,
            backoff_cap_s=900.0,
        )

    async def _project(self, row: dict) -> None:
        from shared.graph.graph import Edge, Vertex
        from shared.graph.mutation_gateway import get_mutation_gateway
        from shared.graph.mutation_intents import edge_intent, vertex_intent

        payload = row.get("payload") or {}
        tenant_id = str(row.get("tenant_id") or "")
        gateway = get_mutation_gateway()
        if payload.get("kind") == "vertex":
            mutation = Vertex(
                vertex_type=payload["vertex_type"],
                vertex_id=payload["vertex_id"],
                properties=payload.get("properties") or {},
                created_at=payload.get("created_at") or _now_iso(),
            )
            outcome = await gateway.apply(vertex_intent(
                mutation, operation="node_versioned", tenant_id=tenant_id,
                actor_id="agent_marketplace_graph_outbox",
                source_event_id=str(row.get("source_event_id") or "") or None,
            ), mode_override="enforce")
            self._require_applied(outcome)
            return
        if payload.get("kind") == "edge":
            mutation = Edge(
                edge_type=payload["edge_type"],
                from_vertex_id=payload["from_vertex_id"],
                to_vertex_id=payload["to_vertex_id"],
                properties=payload.get("properties") or {},
                created_at=payload.get("created_at") or _now_iso(),
            )
            outcome = await gateway.apply(edge_intent(
                mutation, operation="edge_created", tenant_id=tenant_id,
                actor_id="agent_marketplace_graph_outbox",
                source_event_id=str(row.get("source_event_id") or "") or None,
            ), mode_override="enforce")
            self._require_applied(outcome)
            return
        raise ValueError("unknown agent graph mutation payload")

    @staticmethod
    def _require_applied(outcome: Any) -> None:
        """Keep blocked or incomplete writes retryable in the durable outbox."""
        if outcome.blocked:
            raise RuntimeError("graph mutation was blocked by the mutation gateway")
        if not outcome.applied and not outcome.deduplicated:
            raise RuntimeError("graph mutation was not applied")

    async def drain_once(self, tenant_id: Optional[str] = None, limit: int = 100) -> dict[str, Any]:
        return await self._worker.drain_once(tenant_id=tenant_id, limit=limit)

    def build_coro(self):
        return self._worker.build_coro()
