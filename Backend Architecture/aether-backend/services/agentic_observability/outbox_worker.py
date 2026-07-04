"""Agentic graph outbox worker.

Processes durable graph mutations produced by the canonical agentic ingestion
pipeline. The worker is observation-only: it projects already accepted facts into
Aether's graph and never calls external providers or executes provider actions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from repositories.agentic_observability_repos import AgenticProjectionOutboxRepository
from shared.graph.graph import Edge, GraphClient, Vertex
from shared.logger.logger import get_logger

logger = get_logger("aether.agentic_observability.outbox_worker")

_TERMINAL_STATUSES = {"completed", "dead_lettered"}
_RETRYABLE_STATUSES = {"queued", "failed"}
_MAX_ATTEMPTS = 5


@dataclass(frozen=True)
class AgenticOutboxWorkerResult:
    scanned: int = 0
    completed: int = 0
    failed: int = 0
    dead_lettered: int = 0
    skipped: int = 0


class AgenticGraphOutboxWorker:
    """Project queued agentic graph mutations through the shared graph client."""

    def __init__(
        self,
        *,
        outbox_repo: AgenticProjectionOutboxRepository | None = None,
        graph_client: GraphClient | None = None,
        max_attempts: int = _MAX_ATTEMPTS,
    ) -> None:
        self.outbox_repo = outbox_repo or AgenticProjectionOutboxRepository()
        self.graph_client = graph_client or GraphClient()
        self.max_attempts = max_attempts

    async def process_batch(self, *, tenant_id: str, limit: int = 100) -> AgenticOutboxWorkerResult:
        """Process queued/failed graph outbox records for one tenant.

        The tenant is mandatory so worker invocations cannot accidentally scan or
        mutate another tenant's graph records.
        """
        if not tenant_id:
            raise ValueError("tenant_id is required for agentic graph outbox processing")

        queued = await self.outbox_repo.find_many(
            {"tenant_id": tenant_id, "mutation_domain": "graph", "status": "queued"},
            limit=limit,
            sort_by="created_at",
            sort_order="asc",
        )
        remaining = max(0, limit - len(queued))
        failed = []
        if remaining:
            failed = await self.outbox_repo.find_many(
                {"tenant_id": tenant_id, "mutation_domain": "graph", "status": "failed"},
                limit=remaining,
                sort_by="updated_at",
                sort_order="asc",
            )
        records = queued + failed

        counts = {"scanned": len(records), "completed": 0, "failed": 0, "dead_lettered": 0, "skipped": 0}
        for record in records:
            status = record.get("status")
            if status in _TERMINAL_STATUSES or status not in _RETRYABLE_STATUSES:
                counts["skipped"] += 1
                continue
            if record.get("tenant_id") != tenant_id:
                counts["skipped"] += 1
                logger.warning(
                    "agentic_outbox_worker_cross_tenant_skip",
                    extra={"tenant_id": tenant_id, "outbox_id": record.get("outbox_id")},
                )
                continue

            try:
                await self._project_record(record)
            except Exception as exc:  # durable failure state; do not swallow
                attempts = int(record.get("attempt_count") or 0) + 1
                now = datetime.now(timezone.utc)
                update: dict[str, Any] = {
                    "attempt_count": attempts,
                    "last_attempt_at": now.isoformat(),
                    "last_error_code": exc.__class__.__name__,
                    "last_error_message": str(exc)[:500],
                }
                if attempts >= self.max_attempts:
                    update.update({"status": "dead_lettered", "dead_lettered_at": now.isoformat()})
                    counts["dead_lettered"] += 1
                else:
                    delay = min(300, 2 ** attempts)
                    update.update({"status": "failed", "next_attempt_at": (now + timedelta(seconds=delay)).isoformat()})
                    counts["failed"] += 1
                await self.outbox_repo.update(record["outbox_id"], update)
                logger.exception(
                    "agentic_graph_outbox_projection_failed",
                    extra={
                        "tenant_id": tenant_id,
                        "outbox_id": record.get("outbox_id"),
                        "source_event_id": record.get("source_event_id"),
                        "attempt_count": attempts,
                    },
                )
                continue

            now = datetime.now(timezone.utc).isoformat()
            await self.outbox_repo.update(
                record["outbox_id"],
                {
                    "status": "completed",
                    "attempt_count": int(record.get("attempt_count") or 0) + 1,
                    "last_attempt_at": now,
                    "completed_at": now,
                    "last_error_code": None,
                    "last_error_message": None,
                },
            )
            counts["completed"] += 1

        return AgenticOutboxWorkerResult(**counts)

    async def _project_record(self, record: dict[str, Any]) -> None:
        payload = record.get("payload") or {}
        if not isinstance(payload, dict):
            raise ValueError("outbox payload must be an object")
        kind = payload.get("kind")
        if kind == "vertex":
            vertex = Vertex(
                vertex_type=str(payload["vertex_type"]),
                vertex_id=str(payload["vertex_id"]),
                properties=dict(payload.get("properties") or {}),
            )
            await self.graph_client.upsert_vertex(vertex)
            return
        if kind == "edge":
            edge = Edge(
                edge_type=str(payload["edge_type"]),
                from_vertex_id=str(payload["from_vertex_id"]),
                to_vertex_id=str(payload["to_vertex_id"]),
                properties=dict(payload.get("properties") or {}),
            )
            await self.graph_client.add_edge(edge)
            return
        raise ValueError(f"unsupported graph outbox mutation kind: {kind!r}")


async def _run_cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Process tenant-scoped agentic graph outbox records")
    parser.add_argument("--tenant-id", required=True, help="Tenant scope to process")
    parser.add_argument("--limit", type=int, default=100, help="Maximum outbox rows to process")
    args = parser.parse_args()

    result = await AgenticGraphOutboxWorker().process_batch(tenant_id=args.tenant_id, limit=args.limit)
    print(result)


if __name__ == "__main__":
    import asyncio

    asyncio.run(_run_cli())
