"""The replay-parity digest must actually see the graph.

`current_graph_digest` filtered vertices on `properties["tenant_id"]` while
every vertex producer writes `tenantId`. The filter therefore matched nothing a
real producer had written, and the digest over a populated graph was
byte-identical to the digest over an empty one — so any parity check built on
it was vacuously green for its entire life.

This is the regression guard. It fails if the digest ever stops seeing
canonically-written vertices again.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")

from shared.graph.graph import GraphClient, Vertex  # noqa: E402
from shared.graph.mutation_gateway import current_graph_digest  # noqa: E402

CREATED = "2024-01-01T00:00:00+00:00"


async def _client(tenant_property: str, count: int = 3) -> GraphClient:
    client = GraphClient()
    await client.connect()
    for i in range(count):
        await client.add_vertex(
            Vertex(vertex_id=f"v{i}", vertex_type="User",
                   properties={tenant_property: "t1", "createdAt": CREATED})
        )
    return client


async def _empty_digest() -> str:
    client = GraphClient()
    await client.connect()
    return await current_graph_digest(client, tenant_id="t1", scope="all")


async def test_digest_sees_vertices_written_the_canonical_way():
    """`tenantId` is what silver_graph_projector writes — the common case."""
    digest = await current_graph_digest(await _client("tenantId"), tenant_id="t1", scope="all")
    assert digest != await _empty_digest(), (
        "digest over a populated graph equals the digest over an empty one — "
        "the tenant filter is matching nothing, which makes every parity check "
        "built on it vacuously green"
    )


async def test_digest_sees_vertices_written_the_legacy_way():
    """`tenant_id` rows predate the canonical spelling and must still count."""
    digest = await current_graph_digest(await _client("tenant_id"), tenant_id="t1", scope="all")
    assert digest != await _empty_digest()


async def test_digest_is_spelling_independent():
    """Both spellings describe the same graph, so they must digest the same."""
    camel = await current_graph_digest(await _client("tenantId"), tenant_id="t1", scope="all")
    snake = await current_graph_digest(await _client("tenant_id"), tenant_id="t1", scope="all")
    assert camel == snake


async def test_digest_excludes_other_tenants():
    client = GraphClient()
    await client.connect()
    await client.add_vertex(
        Vertex(vertex_id="mine", vertex_type="User",
               properties={"tenantId": "t1", "createdAt": CREATED})
    )
    with_only_mine = await current_graph_digest(client, tenant_id="t1", scope="all")
    await client.add_vertex(
        Vertex(vertex_id="theirs", vertex_type="User",
               properties={"tenantId": "t2", "createdAt": CREATED})
    )
    assert await current_graph_digest(client, tenant_id="t1", scope="all") == with_only_mine
