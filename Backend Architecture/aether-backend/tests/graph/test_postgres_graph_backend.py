"""Contract parity: ``_PostgresGraphBackend`` vs ``_InMemoryGraphBackend`` (#4).

The staging / production-lean profiles declare ``graph: postgres`` but ran no
implementation until ``_PostgresGraphBackend`` landed. These tests pin its
observable behaviour to the in-memory backend — the parity reference — by
running the SAME assertions against BOTH backends. The postgres parametrisation
skips unless a database is reachable (``GRAPH_TEST_DATABASE_URL`` or
``DATABASE_URL``); the in-memory parametrisation always runs, so the contract
itself is exercised even with no database.

Isolation without truncation: the postgres backend shares one database across
the whole test session (and, under ``-n auto``, across parallel xdist workers),
so every test operates inside its OWN namespace — a unique tenant and a unique
id prefix — and asserts only about that namespace. No test truncates or reads
global state, so concurrent tests never touch each other's rows regardless of
how xdist distributes them.

Run the postgres half locally with, e.g.::

    GRAPH_TEST_DATABASE_URL=postgresql://aether:aether@localhost:5432/aether_graph_test \\
        python -m pytest tests/graph/test_postgres_graph_backend.py
"""

from __future__ import annotations

import os
import uuid

import pytest

from shared.graph.graph import (
    Edge,
    EdgeType,
    Vertex,
    VertexType,
    _InMemoryGraphBackend,
    _PostgresGraphBackend,
)

try:  # asyncpg is present in the backend runtime; guard so collection never fails.
    import asyncpg
except ImportError:  # pragma: no cover - asyncpg always installed in CI
    asyncpg = None  # type: ignore[assignment]

PG_URL = os.getenv("GRAPH_TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
BACKENDS = ["inmem", "pg"]


async def _open(kind: str):
    """Return ``(backend, pool)``; ``pool`` is None for in-memory.

    Never truncates — isolation is by per-test namespace (see :class:`_NS`) so
    the shared postgres database is safe under parallel xdist workers. Skips
    (never fails) when no database is reachable.
    """
    if kind == "pg":
        if asyncpg is None or not PG_URL:
            pytest.skip("no asyncpg / GRAPH_TEST_DATABASE_URL / DATABASE_URL")
        try:
            pool = await asyncpg.create_pool(PG_URL, min_size=1, max_size=4)
        except Exception as exc:  # pragma: no cover - environment-dependent
            pytest.skip(f"postgres unavailable: {exc}")
        backend = _PostgresGraphBackend(pool)
        await backend.ensure_schema()
        return backend, pool
    return _InMemoryGraphBackend(), None


class _NS:
    """A unique per-test namespace: its own tenants and its own id prefix."""

    def __init__(self) -> None:
        token = uuid.uuid4().hex[:12]
        self.tenant = f"tnt_{token}"
        self.other = f"oth_{token}"
        self._token = token

    def vid(self, name: str) -> str:
        return f"{self._token}_{name}"

    def props(self, tenant: str | None = None, **extra) -> dict:
        """Both tenant spellings, as every canonical graph write carries them."""
        t = self.tenant if tenant is None else tenant
        return {"tenantId": t, "tenant_id": t, **extra}

    def edge(self, source: str, target: str, *, tenant: str | None = None, **props) -> Edge:
        return Edge(
            edge_type=EdgeType.SEMANTIC_RELATES_TO,
            from_vertex_id=self.vid(source),
            to_vertex_id=self.vid(target),
            properties=self.props(tenant, **props),
        )

    def vertex(
        self, name: str, *, tenant: str | None = None, vtype: str = VertexType.ENTITY, **props
    ) -> Vertex:
        return Vertex(vertex_type=vtype, vertex_id=self.vid(name), properties=self.props(tenant, **props))


# ── vertices ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("kind", BACKENDS)
async def test_add_and_get_vertex_roundtrips(kind):
    backend, pool = await _open(kind)
    ns = _NS()
    try:
        vid = await backend.add_vertex(ns.vertex("v1", summary="hi"))
        assert vid == ns.vid("v1")
        got = await backend.get_vertex(ns.vid("v1"))
        assert got is not None
        assert got.vertex_id == ns.vid("v1")
        assert got.vertex_type == VertexType.ENTITY
        assert got.properties.get("summary") == "hi"
        assert got.properties.get("tenantId") == ns.tenant
        # Missing vertex is None on both backends.
        assert await backend.get_vertex(ns.vid("nope")) is None
    finally:
        if pool is not None:
            await pool.close()


@pytest.mark.parametrize("kind", BACKENDS)
async def test_add_vertex_is_last_write_wins(kind):
    backend, pool = await _open(kind)
    ns = _NS()
    try:
        await backend.add_vertex(ns.vertex("v1", summary="first", extra="keep_me"))
        # add_vertex overwrites the whole row (like ``_vertices[id] = vertex``).
        await backend.add_vertex(ns.vertex("v1", summary="second"))
        got = await backend.get_vertex(ns.vid("v1"))
        assert got.properties.get("summary") == "second"
        assert "extra" not in got.properties  # fully replaced, not merged
    finally:
        if pool is not None:
            await pool.close()


@pytest.mark.parametrize("kind", BACKENDS)
async def test_upsert_vertex_merges_properties(kind):
    backend, pool = await _open(kind)
    ns = _NS()
    try:
        await backend.add_vertex(ns.vertex("v1", a="1", b="2"))
        # upsert merges: new keys added, overlapping keys overwritten, others kept.
        await backend.upsert_vertex(ns.vertex("v1", b="9", c="3"))
        got = await backend.get_vertex(ns.vid("v1"))
        assert got.properties.get("a") == "1"  # preserved
        assert got.properties.get("b") == "9"  # overwritten
        assert got.properties.get("c") == "3"  # added
        # upsert on a brand-new id inserts.
        await backend.upsert_vertex(ns.vertex("v2", z="z"))
        assert (await backend.get_vertex(ns.vid("v2"))).properties.get("z") == "z"
    finally:
        if pool is not None:
            await pool.close()


@pytest.mark.parametrize("kind", BACKENDS)
async def test_get_vertices_for_tenant_is_scoped_and_capped(kind):
    backend, pool = await _open(kind)
    ns = _NS()
    try:
        await backend.add_vertex(ns.vertex("a"))
        await backend.add_vertex(ns.vertex("b", vtype=VertexType.CAMPAIGN))
        await backend.add_vertex(ns.vertex("c", tenant=ns.other))
        ours = await backend.get_vertices_for_tenant(ns.tenant, limit=100)
        assert {v.vertex_id for v in ours} == {ns.vid("a"), ns.vid("b")}  # never other's "c"
        # vertex_type predicate is pushed into the query.
        entities = await backend.get_vertices_for_tenant(
            ns.tenant, limit=100, vertex_type=VertexType.ENTITY
        )
        assert {v.vertex_id for v in entities} == {ns.vid("a")}
        # The cap applies to THIS tenant's rows.
        assert len(await backend.get_vertices_for_tenant(ns.tenant, limit=1)) == 1
    finally:
        if pool is not None:
            await pool.close()


# ── edges ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("kind", BACKENDS)
async def test_add_and_get_edges_directional(kind):
    backend, pool = await _open(kind)
    ns = _NS()
    try:
        await backend.add_edge(ns.edge("s", "t"))
        out = await backend.get_edges(ns.vid("s"), edge_type=EdgeType.SEMANTIC_RELATES_TO)
        assert [(e.from_vertex_id, e.to_vertex_id) for e in out] == [(ns.vid("s"), ns.vid("t"))]
        # "in" from the target's perspective sees the same edge.
        inc = await backend.get_edges(
            ns.vid("t"), edge_type=EdgeType.SEMANTIC_RELATES_TO, direction="in"
        )
        assert [(e.from_vertex_id, e.to_vertex_id) for e in inc] == [(ns.vid("s"), ns.vid("t"))]
        # "both" from an endpoint includes it once.
        both = await backend.get_edges(ns.vid("s"), direction="both")
        assert len(both) == 1
        # An unrelated edge_type filter excludes it.
        assert await backend.get_edges(ns.vid("s"), edge_type=EdgeType.OWNS) == []
    finally:
        if pool is not None:
            await pool.close()


@pytest.mark.parametrize("kind", BACKENDS)
async def test_edges_are_append_only(kind):
    backend, pool = await _open(kind)
    ns = _NS()
    try:
        # The same (from, to, type) pair may carry several edges (replica race);
        # the store appends rather than deduping.
        await backend.add_edge(ns.edge("s", "t", idempotency_key="k1"))
        await backend.add_edge(ns.edge("s", "t", idempotency_key="k1"))
        out = await backend.get_edges(ns.vid("s"))
        assert len(out) == 2
    finally:
        if pool is not None:
            await pool.close()


@pytest.mark.parametrize("kind", BACKENDS)
async def test_revoke_edge_soft_marks_and_is_idempotent(kind):
    backend, pool = await _open(kind)
    ns = _NS()
    try:
        await backend.add_edge(ns.edge("s", "t"))
        s, t = ns.vid("s"), ns.vid("t")
        # Revoke returns the count of matching edges.
        assert await backend.revoke_edge(s, t, EdgeType.SEMANTIC_RELATES_TO, "gone") == 1
        # A revoked edge is excluded from the default read...
        assert await backend.get_edges(s) == []
        # ...but visible with include_revoked, with the revoke folded into props.
        revoked = await backend.get_edges(s, include_revoked=True)
        assert len(revoked) == 1
        assert revoked[0].properties.get("revoked") is True
        assert revoked[0].properties.get("revoke_reason") == "gone"
        first_revoked_at = revoked[0].properties.get("revoked_at")
        assert first_revoked_at
        # Re-revoking is idempotent: still counts, preserves the original stamp.
        assert await backend.revoke_edge(s, t, EdgeType.SEMANTIC_RELATES_TO, "again") == 1
        again = await backend.get_edges(s, include_revoked=True)
        assert again[0].properties.get("revoked_at") == first_revoked_at
        # Revoking a non-existent edge is a safe no-op.
        assert await backend.revoke_edge(ns.vid("x"), ns.vid("y"), EdgeType.SEMANTIC_RELATES_TO, "n") == 0
    finally:
        if pool is not None:
            await pool.close()


@pytest.mark.parametrize("kind", BACKENDS)
async def test_revoke_edge_is_tenant_scoped(kind):
    backend, pool = await _open(kind)
    ns = _NS()
    try:
        await backend.add_edge(ns.edge("s", "t"))
        s, t = ns.vid("s"), ns.vid("t")
        # A revoke naming a DIFFERENT tenant matches nothing (fail-closed).
        assert await backend.revoke_edge(
            s, t, EdgeType.SEMANTIC_RELATES_TO, "x", tenant_id=ns.other
        ) == 0
        assert len(await backend.get_edges(s)) == 1  # still live
        # The owning tenant revokes it.
        assert await backend.revoke_edge(
            s, t, EdgeType.SEMANTIC_RELATES_TO, "x", tenant_id=ns.tenant
        ) == 1
        assert await backend.get_edges(s) == []
    finally:
        if pool is not None:
            await pool.close()


@pytest.mark.parametrize("kind", BACKENDS)
async def test_get_neighbors_requires_neighbor_vertex(kind):
    backend, pool = await _open(kind)
    ns = _NS()
    try:
        await backend.add_edge(ns.edge("s", "t"))
        # No vertices exist yet: a neighbour is only returned when its vertex does.
        assert await backend.get_neighbors(ns.vid("s")) == []
        await backend.add_vertex(ns.vertex("t"))
        nbrs = await backend.get_neighbors(ns.vid("s"))
        assert [v.vertex_id for v in nbrs] == [ns.vid("t")]
        # A revoked edge yields no neighbour.
        await backend.revoke_edge(ns.vid("s"), ns.vid("t"), EdgeType.SEMANTIC_RELATES_TO, "gone")
        assert await backend.get_neighbors(ns.vid("s")) == []
    finally:
        if pool is not None:
            await pool.close()


# ── tenant erasure / orphan deletion ─────────────────────────────────────────


@pytest.mark.parametrize("kind", BACKENDS)
async def test_delete_tenant_data_scoped(kind):
    backend, pool = await _open(kind)
    ns = _NS()
    try:
        await backend.add_vertex(ns.vertex("a"))
        await backend.add_vertex(ns.vertex("b"))
        await backend.add_edge(ns.edge("a", "b"))
        await backend.add_vertex(ns.vertex("c", tenant=ns.other))
        await backend.add_edge(ns.edge("c", "c", tenant=ns.other))
        removed = await backend.delete_tenant_data(ns.tenant)
        # 2 vertices + 1 edge for this tenant.
        assert removed == 3
        assert await backend.get_vertex(ns.vid("a")) is None
        assert await backend.get_edges(ns.vid("a"), include_revoked=True) == []
        # The other tenant is untouched.
        assert await backend.get_vertex(ns.vid("c")) is not None
        assert len(await backend.get_edges(ns.vid("c"), include_revoked=True)) == 1
    finally:
        if pool is not None:
            await pool.close()


@pytest.mark.parametrize("kind", BACKENDS)
async def test_delete_vertex_if_orphaned_guards(kind):
    backend, pool = await _open(kind)
    ns = _NS()
    try:
        v = ns.vid("v")
        # tenant_mismatch / ownership_changed / not_found.
        await backend.add_vertex(
            Vertex(
                vertex_type=VertexType.ENTITY,
                vertex_id=v,
                properties={"tenant_id": ns.tenant, "import_commit_id": "c1"},
            )
        )
        assert await backend.delete_vertex_if_orphaned(ns.vid("missing"), ns.tenant, "c1") == (
            False,
            "not_found",
        )
        assert await backend.delete_vertex_if_orphaned(v, ns.other, "c1") == (
            False,
            "tenant_mismatch",
        )
        assert await backend.delete_vertex_if_orphaned(v, ns.tenant, "c2") == (
            False,
            "ownership_changed",
        )
        # An active (non-revoked) incident edge blocks deletion.
        await backend.add_edge(
            Edge(
                edge_type=EdgeType.SEMANTIC_RELATES_TO,
                from_vertex_id=v,
                to_vertex_id=ns.vid("w"),
                properties={"tenant_id": ns.tenant, "import_commit_id": "c1"},
            )
        )
        assert await backend.delete_vertex_if_orphaned(v, ns.tenant, "c1") == (
            False,
            "active_reference",
        )
        # Revoke the incident edge → the vertex is now orphaned and deletable.
        await backend.revoke_edge(v, ns.vid("w"), EdgeType.SEMANTIC_RELATES_TO, "gone")
        assert await backend.delete_vertex_if_orphaned(v, ns.tenant, "c1") == (True, "deleted")
        assert await backend.get_vertex(v) is None
    finally:
        if pool is not None:
            await pool.close()


# ── health / query ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("kind", BACKENDS)
async def test_ping_and_query(kind):
    backend, pool = await _open(kind)
    try:
        assert await backend.ping() is True
        # ``query`` is a no-op on non-gremlin backends (Neptune error-path parity).
        assert await backend.query("g.V().count()") == []
    finally:
        if pool is not None:
            await pool.close()
