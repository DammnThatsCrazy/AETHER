"""Interop topology links gateways only to chain vertices the asset registry owns.

``chain:`` vertices are platform-owned and seeded by the asset registry; the
interop projector never writes one. A gateway whose chain is not in the graph
gets no ``CONNECTS_CHAIN`` edge (so nothing dangles, and Neptune never sees an
``addE`` to a missing vertex); the skip is counted. Runs on the in-memory
backend and, with ``GRAPH_TEST_DATABASE_URL`` / ``DATABASE_URL``, on Postgres.
"""

from __future__ import annotations

import os
import random
import uuid

os.environ.setdefault("AETHER_ENV", "local")

import pytest  # noqa: E402

import dependencies.providers as providers  # noqa: E402
from graph.interop import scan_worker  # noqa: E402
from shared.graph.graph import (  # noqa: E402
    EdgeType,
    GraphClient,
    Vertex,
    VertexType,
    _InMemoryGraphBackend,
    _PostgresGraphBackend,
)

try:
    import asyncpg
except ImportError:  # pragma: no cover
    asyncpg = None  # type: ignore[assignment]

PG_URL = os.getenv("GRAPH_TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
SEEDED_CHAIN = "chain:eip155:8453"


@pytest.fixture(params=["inmem", "pg"])
async def graph(request, monkeypatch):
    client = GraphClient()
    pool = None
    if request.param == "pg":
        if asyncpg is None or not PG_URL:
            pytest.skip("GRAPH_TEST_DATABASE_URL not set")
        try:
            pool = await asyncpg.create_pool(PG_URL, min_size=1, max_size=2)
        except Exception as exc:  # pragma: no cover - environment-dependent
            pytest.skip(f"postgres unavailable: {exc}")
        backend = _PostgresGraphBackend(pool)
        await backend.ensure_schema()
        client._backend = backend  # noqa: SLF001
    else:
        client._backend = _InMemoryGraphBackend()  # noqa: SLF001
    monkeypatch.setattr(providers, "get_graph", lambda: client)
    try:
        yield client
    finally:
        if pool is not None:
            await pool.close()


async def test_gateway_links_only_to_registry_chain_vertices(graph, monkeypatch):
    counted: list[str] = []
    monkeypatch.setattr(
        scan_worker.metrics, "increment",
        lambda name, *a, **k: counted.append(name),
    )
    await graph.add_vertex(Vertex(
        vertex_type=VertexType.CHAIN, vertex_id=SEEDED_CHAIN,
        properties={"tenantId": "platform", "tenant_id": "platform", "chain_id": "eip155:8453"},
    ))
    token = uuid.uuid4().hex[:8]
    unseeded = str(900_000_000 + random.randrange(1_000_000))
    observations = [
        {"endpoint_ref": {"gateway_id": f"gw-base-{token}", "network_id": "base-mainnet",
                          "native_chain_id": "8453"}},
        {"endpoint_ref": {"gateway_id": f"gw-other-{token}", "network_id": "other",
                          "native_chain_id": unseeded}},
    ]

    result = await scan_worker.InteropGraphProjector(enabled=True).project(
        "public", observations, [], provider={"provider_id": f"provider-{token}"},
    )

    assert result.graph_projection_status == "persisted"
    linked = await graph.get_edges(
        f"interop_gateway:gw-base-{token}", EdgeType.CONNECTS_CHAIN, "out",
    )
    assert [e.to_vertex_id for e in linked] == [SEEDED_CHAIN]
    assert await graph.get_edges(
        f"interop_gateway:gw-other-{token}", EdgeType.CONNECTS_CHAIN, "out",
    ) == []
    assert await graph.get_vertex(f"chain:eip155:{unseeded}") is None
    assert await graph.get_vertex(f"chain:{unseeded}") is None
    assert (await graph.get_vertex(SEEDED_CHAIN)).properties["tenant_id"] == "platform"
    assert counted.count("interop_chain_link_skipped") == 1
