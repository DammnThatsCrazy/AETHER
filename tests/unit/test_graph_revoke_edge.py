"""Tests for GraphClient.revoke_edge — soft revoke of graph edges (in-memory).

Runs against the in-memory backend (AETHER_ENV=local). Covers:
- revoke_edge sets revoked/revoked_at/revoke_reason on the matching edge
- revoking a non-existent edge is a safe no-op (returns 0)
- idempotent double-revoke preserves the original revoked_at
- revoked edges are filtered out of get_edges/get_neighbors by default
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

os.environ.setdefault("AETHER_ENV", "local")

from shared.graph.graph import Edge, EdgeType, GraphClient, Vertex  # noqa: E402


def _v(vid: str, vtype: str = "User", tenant_id: str = "tenant_a") -> Vertex:
    return Vertex(
        vertex_type=vtype,
        vertex_id=vid,
        properties={"tenant_id": tenant_id},
        created_at="2024-01-01T00:00:00+00:00",
    )


def _e(
    from_id: str,
    to_id: str,
    etype: str,
    tenant_id: str = "tenant_a",
) -> Edge:
    return Edge(
        edge_type=etype,
        from_vertex_id=from_id,
        to_vertex_id=to_id,
        properties={"tenant_id": tenant_id},
        created_at="2024-01-01T00:00:00+00:00",
    )


async def _client(*vertices: Vertex, edges: list[Edge] | None = None) -> GraphClient:
    client = GraphClient()
    await client.connect()
    assert client.mode == "in-memory"
    for v in vertices:
        await client.add_vertex(v)
    for e in (edges or []):
        await client.add_edge(e)
    return client


@pytest.mark.asyncio
async def test_revoke_edge_sets_revocation_properties() -> None:
    """revoke_edge stamps revoked/revoked_at/revoke_reason on the matching edge."""
    client = await _client(
        _v("u1", "User"),
        _v("a1", "Agent"),
        edges=[_e("u1", "a1", EdgeType.DELEGATES)],
    )

    count = await client.revoke_edge(
        "u1", "a1", EdgeType.DELEGATES, reason="fragment_split"
    )
    assert count == 1

    # Edge is not deleted — it's still present when include_revoked=True.
    edges = await client.get_edges("u1", direction="out", include_revoked=True)
    assert len(edges) == 1
    props = edges[0].properties
    assert props["revoked"] is True
    assert props["revoke_reason"] == "fragment_split"
    assert isinstance(props["revoked_at"], str) and props["revoked_at"]


@pytest.mark.asyncio
async def test_revoke_nonexistent_edge_is_noop() -> None:
    """Revoking an edge that does not exist returns 0 and does not raise."""
    client = await _client(
        _v("u1", "User"),
        _v("a1", "Agent"),
        edges=[_e("u1", "a1", EdgeType.DELEGATES)],
    )

    # Wrong endpoints / wrong type — nothing matches.
    assert await client.revoke_edge("u1", "a1", EdgeType.NOTIFIES, reason="x") == 0
    assert await client.revoke_edge("u1", "missing", EdgeType.DELEGATES, reason="x") == 0
    assert await client.revoke_edge("nope", "a1", EdgeType.DELEGATES, reason="x") == 0

    # The real edge is untouched.
    edges = await client.get_edges("u1", direction="out")
    assert len(edges) == 1
    assert "revoked" not in edges[0].properties


@pytest.mark.asyncio
async def test_revoke_edge_is_idempotent() -> None:
    """Double-revoke is a safe success and preserves the original revoked_at."""
    client = await _client(
        _v("u1", "User"),
        _v("a1", "Agent"),
        edges=[_e("u1", "a1", EdgeType.DELEGATES)],
    )

    assert await client.revoke_edge("u1", "a1", EdgeType.DELEGATES, reason="first") == 1
    first = (await client.get_edges("u1", direction="out", include_revoked=True))[0]
    original_revoked_at = first.properties["revoked_at"]

    # Re-revoke: still succeeds, still counts the matching edge, but does not
    # overwrite the original revocation metadata.
    assert await client.revoke_edge("u1", "a1", EdgeType.DELEGATES, reason="second") == 1
    again = (await client.get_edges("u1", direction="out", include_revoked=True))[0]
    assert again.properties["revoked"] is True
    assert again.properties["revoked_at"] == original_revoked_at
    assert again.properties["revoke_reason"] == "first"


@pytest.mark.asyncio
async def test_revoked_edges_filtered_by_default() -> None:
    """Revoked edges are excluded from get_edges/get_neighbors unless asked for."""
    client = await _client(
        _v("u1", "User"),
        _v("a1", "Agent"),
        _v("a2", "Agent"),
        edges=[
            _e("u1", "a1", EdgeType.DELEGATES),
            _e("u1", "a2", EdgeType.DELEGATES),
        ],
    )

    await client.revoke_edge("u1", "a1", EdgeType.DELEGATES, reason="split")

    # Default: the revoked edge is filtered out.
    default_edges = await client.get_edges("u1", direction="out")
    assert {e.to_vertex_id for e in default_edges} == {"a2"}

    default_neighbors = await client.get_neighbors("u1", direction="out")
    assert {v.vertex_id for v in default_neighbors} == {"a2"}

    # include_revoked=True brings it back.
    all_edges = await client.get_edges("u1", direction="out", include_revoked=True)
    assert {e.to_vertex_id for e in all_edges} == {"a1", "a2"}

    all_neighbors = await client.get_neighbors(
        "u1", direction="out", include_revoked=True
    )
    assert {v.vertex_id for v in all_neighbors} == {"a1", "a2"}


@pytest.mark.asyncio
async def test_revoke_edge_is_tenant_scoped() -> None:
    """A tenant_id filter only revokes edges carrying that tenant."""
    client = await _client(
        _v("u1", "User"),
        _v("a1", "Agent"),
        edges=[
            _e("u1", "a1", EdgeType.DELEGATES, tenant_id="tenant_a"),
            _e("u1", "a1", EdgeType.DELEGATES, tenant_id="tenant_b"),
        ],
    )

    # Only tenant_a's edge is revoked.
    assert (
        await client.revoke_edge(
            "u1", "a1", EdgeType.DELEGATES, reason="split", tenant_id="tenant_a"
        )
        == 1
    )

    remaining = await client.get_edges("u1", direction="out")
    assert len(remaining) == 1
    assert remaining[0].properties["tenant_id"] == "tenant_b"

    revoked = await client.get_edges("u1", direction="out", include_revoked=True)
    revoked_a = [e for e in revoked if e.properties.get("revoked")]
    assert len(revoked_a) == 1
    assert revoked_a[0].properties["tenant_id"] == "tenant_a"
