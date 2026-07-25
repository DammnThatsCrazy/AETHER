"""Tenant-scoped graph reads must not truncate a tenant's own rows.

Every `get_all_vertices(limit=N)`-then-filter-by-tenant call site applies the
cap to the WHOLE graph before the tenant predicate runs. A tenant whose
vertices sort past that cap therefore receives a partial page or none at all —
and it reads as "you have no data", not as an error.

The pre-existing isolation suite cannot catch this: it uses `limit=1000`
against a 4-vertex fixture, so the cap never binds. These tests seed more
foreign vertices than the cap on purpose.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")

from shared.graph.graph import GraphClient, Vertex, tenant_of  # noqa: E402

CAP = 50
FOREIGN = 60
MINE = 5


async def _seeded() -> GraphClient:
    """A graph where the caller's tenant sorts entirely past the cap."""
    client = GraphClient()
    await client.connect()
    for i in range(FOREIGN):
        await client.add_vertex(
            Vertex(vertex_id=f"foreign-{i}", vertex_type="User",
                   properties={"tenantId": "other-tenant"})
        )
    for i in range(MINE):
        await client.add_vertex(
            Vertex(vertex_id=f"mine-{i}", vertex_type="User",
                   properties={"tenantId": "my-tenant"})
        )
    return client


async def test_legacy_scan_then_filter_loses_the_tenants_rows():
    """Documents the bug the scoped read exists to remove.

    If this ever starts passing with a full result, the global read has changed
    semantics and the scoped read may no longer be necessary — investigate
    rather than deleting the test.
    """
    client = await _seeded()
    page = await client.get_all_vertices(limit=CAP)
    survived = [v for v in page if tenant_of(v.properties) == "my-tenant"]
    assert len(survived) < MINE, (
        "the global page unexpectedly contained the tenant's rows; this test's "
        "premise (tenant sorts past the cap) no longer holds"
    )


async def test_scoped_read_returns_every_row_for_the_tenant():
    client = await _seeded()
    scoped = await client.get_vertices_for_tenant("my-tenant", limit=CAP)
    assert len(scoped) == MINE
    assert {v.vertex_id for v in scoped} == {f"mine-{i}" for i in range(MINE)}


async def test_scoped_read_never_returns_another_tenants_rows():
    client = await _seeded()
    scoped = await client.get_vertices_for_tenant("my-tenant", limit=CAP)
    assert all(tenant_of(v.properties) == "my-tenant" for v in scoped)


async def test_scoped_read_applies_the_cap_to_the_tenants_own_rows():
    """The cap must bound the tenant's rows, not a global page."""
    client = GraphClient()
    await client.connect()
    for i in range(20):
        await client.add_vertex(
            Vertex(vertex_id=f"mine-{i}", vertex_type="User",
                   properties={"tenantId": "my-tenant"})
        )
    assert len(await client.get_vertices_for_tenant("my-tenant", limit=7)) == 7


async def test_missing_tenant_id_returns_nothing_not_everything():
    """A scoped read that cannot name its tenant must not widen."""
    client = await _seeded()
    assert await client.get_vertices_for_tenant("", limit=CAP) == []


async def test_tenant_of_reads_both_spellings():
    """Vertex producers write `tenantId`; edge producers write `tenant_id`."""
    assert tenant_of({"tenantId": "t1"}) == "t1"
    assert tenant_of({"tenant_id": "t1"}) == "t1"
    assert tenant_of({}) is None
    assert tenant_of(None) is None
    # An empty value is absence, not a wildcard.
    assert tenant_of({"tenantId": ""}) is None


async def test_vertex_type_filter_composes_with_tenant_scope():
    client = GraphClient()
    await client.connect()
    for i in range(5):
        await client.add_vertex(
            Vertex(vertex_id=f"u{i}", vertex_type="User", properties={"tenantId": "t"})
        )
    for i in range(5):
        await client.add_vertex(
            Vertex(vertex_id=f"w{i}", vertex_type="Wallet", properties={"tenantId": "t"})
        )
    wallets = await client.get_vertices_for_tenant("t", limit=100, vertex_type="Wallet")
    assert len(wallets) == 5
    assert all(v.vertex_type == "Wallet" for v in wallets)
