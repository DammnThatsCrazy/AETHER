"""Durable retry and operator recovery for agent graph projections."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Optional

from shared.logger.logger import get_logger
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

    async def list_for_tenant(self, tenant_id: str, limit: int = 100_000) -> list[dict]:
        rows = await self._store.find(tenant_id=tenant_id)
        rows.sort(key=lambda row: row.get("created_at") or "")
        return rows[:limit]


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

    async def _expected_mutations(self, tenant_id: str, limit: int) -> tuple[list[tuple[str, Any]], bool]:
        from actions.agent.deployments import get_deployment_repository
        from actions.agent_marketplace.lineage import build_marketplace_origin_mutations
        from config.settings import settings
        from dependencies.providers import get_cache
        from ingestion.silver.projectors.silver_graph_projector import (
            build_external_agent_run_mutations,
        )
        from repositories.repos import AnalyticsRepository

        expected: list[tuple[str, Any]] = []
        deployments = (await get_deployment_repository().list(tenant_id))[:limit]
        truncated = len(deployments) >= limit
        for deployment in deployments:
            if deployment.get("marketplace_origin"):
                for mutation in build_marketplace_origin_mutations(deployment):
                    expected.append((str(deployment.get("id") or ""), mutation))

        if settings.external_agent_telemetry.graph_enabled:
            rows = await AnalyticsRepository(get_cache()).query_silver(
                "silver_agent_execution_facts", {"tenant_id": tenant_id}, limit=limit
            )
            truncated = truncated or len(rows) >= limit
            for row in rows:
                mutations = build_external_agent_run_mutations(row)
                source_event_id = str(row.get("source_event_id") or "")
                if source_event_id:
                    expected.extend((source_event_id, mutation) for mutation in mutations)
        return expected, truncated

    async def reconcile(self, tenant_id: str, *, limit: int = 500) -> dict[str, Any]:
        rows = await self.repo.list_for_tenant(tenant_id, limit=limit * 10)
        by_status = {
            status: sum(1 for row in rows if row.get("status") == status)
            for status in (STATUS_QUEUED, STATUS_PROCESSING, STATUS_FAILED, STATUS_DEAD_LETTERED, STATUS_PERSISTED)
        }
        expected, truncated = await self._expected_mutations(tenant_id, limit)
        have = {row.get("outbox_id") for row in rows}
        missing = [
            mutation for source_event_id, mutation in expected
            if self.repo.outbox_id(tenant_id, _mutation_payload(mutation)) not in have
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
            "graph_state_checked": False,
        }

    async def repair(
        self, tenant_id: str, *, enqueue_missing: bool = True,
        replay_dead_letters: bool = True, replay_persisted: bool = False,
        limit: int = 500,
    ) -> dict[str, Any]:
        enqueued = 0
        if enqueue_missing:
            expected, _ = await self._expected_mutations(tenant_id, limit)
            have = {
                row.get("outbox_id")
                for row in await self.repo.list_for_tenant(tenant_id, limit=limit * 10)
            }
            for source_event_id, mutation in expected:
                payload = _mutation_payload(mutation)
                if self.repo.outbox_id(tenant_id, payload) not in have:
                    _, created = await self.repo.enqueue(tenant_id, source_event_id, payload)
                    enqueued += int(created)

        reset = 0
        statuses = {STATUS_DEAD_LETTERED} if replay_dead_letters else set()
        if replay_persisted:
            statuses.add(STATUS_PERSISTED)
        for row in await self.repo.list_for_tenant(tenant_id, limit=limit * 10):
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
            "source_scan_limit": limit,
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
