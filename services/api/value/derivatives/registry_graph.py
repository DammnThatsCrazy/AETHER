"""Project the derivatives venue and market registry into the graph as ``platform``.

Tenant account and position projections only link to ``market_venue:`` and
``derivative_market:`` vertices; this is the only writer of those vertices. It
reads every registry row and writes the vertex when it is missing or differs,
so it is safe to re-run after registry rows are added::

    DATABASE_URL=... python -m value.derivatives.registry_graph
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional

from repositories.derivatives_repos import MarketRepo, VenueRepo
from shared.graph.graph import Vertex
from value.derivatives.graph_mutations import build_market_vertex, build_venue_vertex

PLATFORM = "platform"
_PAGE = 500


async def _rows(repo: Any, order_by: str) -> list[dict]:
    rows: list[dict] = []
    while True:
        page = await repo.find_many(limit=_PAGE, offset=len(rows), order_by=order_by, descending=False)
        rows.extend(page)
        if len(page) < _PAGE:
            return rows


async def _project(gateway: Any, graph: Any, rows: list[dict], build: Callable[[dict], Vertex]) -> int:
    from shared.graph.mutation_intents import vertex_intent

    written = 0
    for row in rows:
        vertex = build(row)
        existing = await graph.get_vertex(vertex.vertex_id)
        if existing is not None and existing.properties == vertex.properties:
            continue
        await gateway.apply(vertex_intent(
            vertex, operation="node_versioned", tenant_id=PLATFORM,
            actor_kind="service", actor_id="derivatives_registry",
        ))
        written += 1
    return written


async def project_registry(graph_client: Optional[Any] = None) -> dict[str, int]:
    """Write the registry's venue and market vertices; returns how many were written."""
    from shared.graph.graph import get_graph_client
    from shared.graph.mutation_gateway import GraphMutationGateway

    graph = graph_client or get_graph_client()
    gateway = GraphMutationGateway(graph_client=graph)
    return {
        "venues": await _project(gateway, graph, await _rows(VenueRepo(), "venue_id"), build_venue_vertex),
        "markets": await _project(
            gateway, graph, await _rows(MarketRepo(), "canonical_market_id"), build_market_vertex,
        ),
    }


def main() -> int:
    from shared.graph.graph import get_graph_client

    async def _run() -> dict[str, int]:
        graph = get_graph_client()
        await graph.connect()
        try:
            return await project_registry(graph)
        finally:
            await graph.close()

    written = asyncio.run(_run())
    print(f"derivatives registry vertices written: {written['venues']} venues, {written['markets']} markets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
