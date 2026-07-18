"""
Agentic Graph Outbox Worker.

Scans queued/failed outbox rows for a tenant, projects them through
the graph client, and marks them persisted or dead-lettered.

Built on shared.outbox.GenericOutboxWorker — the graph projection sink is
the only agentic-specific logic. Statuses (queued/processing/persisted/
failed/dead_lettered), the agentic_projection_outbox table, retry backoff
(min(300, 2**attempts) seconds) and the public API are unchanged.

INVARIANT: Worker only projects graph mutations derived from observations.
           It never executes external provider actions.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
from typing import Any

from repositories.agentic_observability_repos import AgenticProjectionOutboxRepository
from shared.graph.graph import Edge, Vertex
from shared.logger.logger import get_logger
from shared.outbox import GenericOutboxWorker, STATUS_PERSISTED

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
        self._worker = GenericOutboxWorker(
            repo=outbox_repo,
            sink=self._project,
            name="agentic_graph_outbox",
            max_attempts=max_attempts,
            backoff_base_s=1.0,
            backoff_cap_s=_MAX_BACKOFF_SECONDS,
            success_status=STATUS_PERSISTED,
        )

    async def _project(self, row: dict) -> None:
        """Graph projection sink: one outbox row → one vertex/edge write.

        Routed through the canonical mutation gateway; tenant flows from the
        outbox row (which is drained per tenant) or the projected properties.
        """
        from shared.graph.mutation_gateway import GraphMutationGateway
        from shared.graph.mutation_intents import edge_intent, vertex_intent

        outbox_id = str(row.get("outbox_id") or row.get("id", ""))
        mutation_type = row.get("mutation_type", "vertex")
        payload = row.get("payload", {}) or {}
        props = payload.get("properties", {}) or {}
        tenant_id = str(row.get("tenant_id") or props.get("tenant_id", ""))
        gateway = GraphMutationGateway(graph_client=self._graph)

        if mutation_type == "vertex":
            v = Vertex(
                vertex_type=payload.get("vertex_type", "AgentObservation"),
                vertex_id=payload.get("vertex_id", outbox_id),
                properties=props,
            )
            await gateway.apply(vertex_intent(
                v, operation="node_created", tenant_id=tenant_id,
                actor_id="agentic_graph_outbox",
            ))
        else:
            e = Edge(
                edge_type=payload.get("edge_type", "observed"),
                from_vertex_id=payload.get("from_vertex_id", ""),
                to_vertex_id=payload.get("to_vertex_id", ""),
                properties=props,
            )
            await gateway.apply(edge_intent(
                e, operation="edge_created", tenant_id=tenant_id,
                actor_id="agentic_graph_outbox",
            ))

    async def process_batch(
        self, tenant_id: str, limit: int = 100
    ) -> AgenticOutboxWorkerResult:
        summary = await self._worker.drain_once(tenant_id=tenant_id, limit=limit)
        return AgenticOutboxWorkerResult(
            tenant_id=tenant_id,
            processed=int(summary.get("processed", 0)),
            persisted=int(summary.get("succeeded", 0)),
            failed=int(summary.get("failed", 0)),
            dead_lettered=int(summary.get("dead_lettered", 0)),
            errors=list(summary.get("errors", [])),
        )


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
