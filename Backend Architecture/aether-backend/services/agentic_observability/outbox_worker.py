"""
Agentic Graph Outbox Worker.

Scans queued/failed outbox rows for a tenant, projects them through
the graph client, and marks them persisted or dead-lettered.

INVARIANT: Worker only projects graph mutations derived from observations.
           It never executes external provider actions.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from repositories.agentic_observability_repos import AgenticProjectionOutboxRepository
from shared.graph.graph import Edge, Vertex
from shared.logger.logger import get_logger

logger = get_logger("aether.agentic_observability.outbox_worker")

_MAX_BACKOFF_SECONDS = 300


@dataclass
class AgenticOutboxWorkerResult:
    tenant_id: str
    processed: int = 0
    persisted: int = 0
    failed: int = 0
    dead_lettered: int = 0
    errors: list[str] = field(default_factory=list)


class AgenticGraphOutboxWorker:
    def __init__(
        self,
        outbox_repo: AgenticProjectionOutboxRepository,
        graph_client: Any,
        max_attempts: int = 5,
    ) -> None:
        self._outbox = outbox_repo
        self._graph = graph_client
        self._max_attempts = max_attempts

    async def process_batch(
        self, tenant_id: str, limit: int = 100
    ) -> AgenticOutboxWorkerResult:
        result = AgenticOutboxWorkerResult(tenant_id=tenant_id)

        queued = await self._outbox.find_many(
            filters={"tenant_id": tenant_id, "status": "queued"}, limit=limit
        )
        failed = await self._outbox.find_many(
            filters={"tenant_id": tenant_id, "status": "failed"}, limit=limit
        )
        now = datetime.now(timezone.utc)
        # Only retry failed rows whose next_attempt_at window has elapsed.
        eligible_failed = [
            r for r in failed
            if not r.get("next_attempt_at")
            or datetime.fromisoformat(r["next_attempt_at"].replace("Z", "+00:00")) <= now
        ]
        rows = queued + eligible_failed

        for row in rows:
            result.processed += 1
            outbox_id = row.get("outbox_id") or row.get("id", "")
            attempts = int(row.get("attempts", 0))
            mutation_type = row.get("mutation_type", "vertex")
            payload = row.get("payload", {})

            if attempts >= self._max_attempts:
                await self._mark(outbox_id, row, "dead_lettered", attempts)
                result.dead_lettered += 1
                continue

            try:
                if mutation_type == "vertex":
                    v = Vertex(
                        vertex_type=payload.get("vertex_type", "AgentObservation"),
                        vertex_id=payload.get("vertex_id", outbox_id),
                        properties=payload.get("properties", {}),
                    )
                    await self._graph.add_vertex(v)
                else:
                    e = Edge(
                        edge_type=payload.get("edge_type", "observed"),
                        from_vertex_id=payload.get("from_vertex_id", ""),
                        to_vertex_id=payload.get("to_vertex_id", ""),
                        properties=payload.get("properties", {}),
                    )
                    await self._graph.add_edge(e)

                await self._mark(outbox_id, row, "persisted", attempts + 1)
                result.persisted += 1

            except Exception as exc:
                backoff = min(_MAX_BACKOFF_SECONDS, 2 ** attempts)
                logger.warning(
                    "outbox projection failed",
                    extra={
                        "outbox_id": outbox_id,
                        "attempts": attempts,
                        "backoff_s": backoff,
                        "error": str(exc),
                    },
                )
                from shared.common.common import utc_now
                next_attempt = (
                    datetime.now(timezone.utc).replace(microsecond=0).isoformat()
                    .replace("+00:00", "Z")
                )
                # Compute next_attempt_at so the worker skips this row until the window elapses.
                import datetime as _dt
                next_ts = (
                    datetime.now(timezone.utc) + _dt.timedelta(seconds=backoff)
                ).isoformat().replace("+00:00", "Z")
                await self._mark(outbox_id, {**row, "next_attempt_at": next_ts}, "failed", attempts + 1)
                result.failed += 1
                result.errors.append(f"{outbox_id}:{type(exc).__name__}")

        return result

    async def _mark(self, outbox_id: str, row: dict[str, Any], status: str, attempts: int) -> None:
        from shared.common.common import utc_now
        try:
            updated = {**row, "status": status, "attempts": attempts, "updated_at": utc_now().isoformat()}
            await self._outbox.insert(outbox_id, updated)
        except Exception as exc:
            logger.warning("outbox mark failed", extra={"outbox_id": outbox_id, "error": str(exc)})


async def _run(tenant_id: str, limit: int) -> None:
    from repositories.agentic_observability_repos import AgenticProjectionOutboxRepository
    outbox = AgenticProjectionOutboxRepository()
    try:
        from dependencies.providers import get_graph
        graph = get_graph()
    except Exception:
        from shared.graph.graph import GraphClient
        graph = GraphClient()
    worker = AgenticGraphOutboxWorker(outbox, graph)
    result = await worker.process_batch(tenant_id, limit=limit)
    print(
        f"[outbox] processed={result.processed} persisted={result.persisted} "
        f"failed={result.failed} dead_lettered={result.dead_lettered}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process agentic graph outbox")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    asyncio.run(_run(args.tenant_id, args.limit))
