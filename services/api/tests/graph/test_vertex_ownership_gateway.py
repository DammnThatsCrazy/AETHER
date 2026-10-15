"""Graph vertex writes keep their owner through the mutation gateway.

The backends refuse an owner change (see ``test_postgres_graph_backend``); the
gateway applies the same rule before any ledger write and keeps tenant writers
off ``platform`` / ``public`` reference vertices.
"""

from __future__ import annotations

import os
import uuid

os.environ.setdefault("AETHER_ENV", "local")

import pytest  # noqa: E402

from repositories import graph_mutation_ledger as ledger  # noqa: E402
from shared.graph.graph import (  # noqa: E402
    GraphClient,
    Vertex,
    VertexOwnershipError,
    VertexType,
    _InMemoryGraphBackend,
)
from shared.graph.mutation_gateway import GraphMutationGateway  # noqa: E402
from shared.graph.mutation_intents import vertex_intent  # noqa: E402


def _graph() -> GraphClient:
    client = GraphClient()
    client._backend = _InMemoryGraphBackend()  # noqa: SLF001
    return client


def _vertex(vid: str, tenant: str | None, **props) -> Vertex:
    if tenant is not None:
        props = {"tenantId": tenant, "tenant_id": tenant, **props}
    return Vertex(vertex_type=VertexType.ASSET, vertex_id=vid, properties=props)


async def _write(gateway, vertex: Vertex, tenant: str, mode: str = "off") -> None:
    await gateway.apply(
        vertex_intent(vertex, operation="node_versioned", tenant_id=tenant, actor_id="test"),
        mode_override=mode,
    )


@pytest.mark.parametrize("mode", ["off", "shadow", "enforce"])
async def test_tenant_writer_cannot_touch_platform_vertices(mode):
    ledger.reset_graph_ledger_memory()
    graph = _graph()
    gateway = GraphMutationGateway(graph_client=graph)
    vid = f"asset:{uuid.uuid4().hex[:8]}"
    await _write(gateway, _vertex(vid, "platform", symbol="USDC"), "platform", mode)

    for vertex in (
        _vertex(vid, "tenant-a", symbol="EVIL"),   # take it over
        _vertex(vid, "platform", symbol="EVIL"),   # rewrite it as platform
    ):
        with pytest.raises(VertexOwnershipError):
            await _write(gateway, vertex, "tenant-a", mode)
    with pytest.raises(VertexOwnershipError):  # nor create a new platform vertex
        await _write(gateway, _vertex(f"{vid}-new", "public"), "tenant-a", mode)

    assert (await graph.get_vertex(vid)).properties["symbol"] == "USDC"
    assert await graph.get_vertex(f"{vid}-new") is None
    await _write(gateway, _vertex(vid, "platform", symbol="USDC.e"), "platform", mode)
    assert (await graph.get_vertex(vid)).properties["symbol"] == "USDC.e"


async def test_rejected_cross_tenant_write_leaves_no_ledger_record():
    ledger.reset_graph_ledger_memory()
    graph = _graph()
    gateway = GraphMutationGateway(graph_client=graph)
    vid = f"user:{uuid.uuid4().hex[:8]}"
    await _write(gateway, _vertex(vid, "tenant-a", secret="a"), "tenant-a", "enforce")
    before = len(ledger._MEM_LEDGER)  # noqa: SLF001

    with pytest.raises(VertexOwnershipError):
        await _write(gateway, _vertex(vid, "tenant-b", secret="b"), "tenant-b", "enforce")
    with pytest.raises(VertexOwnershipError):
        await _write(gateway, Vertex(
            vertex_type=VertexType.USER, vertex_id=vid,
            properties={"tenantId": "tenant-b", "tenant_id": "tenant-a", "secret": "b"},
        ), "tenant-a", "enforce")

    assert len(ledger._MEM_LEDGER) == before  # noqa: SLF001
    assert (await graph.get_vertex(vid)).properties["secret"] == "a"


def test_card_catalog_vertices_are_platform_and_flows_only_link_to_them():
    from value.card_linked_payments.graph_projector import (
        build_catalog_mutations,
        build_flow_mutations,
    )

    vertices, edges = build_catalog_mutations({
        "slug": "redotpay", "issuer_id": "issuer-1", "payment_network": "visa",
    })
    assert {v.vertex_id for v in vertices} == {
        "card_program:redotpay", "card_issuer:issuer-1", "payment_network:visa",
    }
    assert {v.properties["tenant_id"] for v in vertices} == {"platform"}
    assert {e.properties["tenant_id"] for e in edges} == {"platform"}

    vertices, edges = build_flow_mutations({
        "id": "flow-1", "tenant_id": "tenant-a", "basis": "observed",
        "card_program_id": "redotpay", "user_id": "u-1",
    })
    assert [v.vertex_id for v in vertices] == ["card_linked_flow:flow-1"]
    assert any(e.to_vertex_id == "card_program:redotpay" for e in edges)


def test_interop_topology_links_to_platform_chain_vertices_without_writing_them():
    from graph.interop.graph_mutations import build_topology_mutations

    vertices, edges = build_topology_mutations(
        {"provider_id": "wormhole"},
        [{"gateway_id": "gw-1", "native_chain_id": "eip155:1"}],
        [],
    )
    assert not any(v.vertex_id.startswith("chain:") for v in vertices)
    assert any(e.to_vertex_id == "chain:eip155:1" for e in edges)


def test_staged_rollback_drops_only_the_committing_tenants_vertex():
    from actions.agent.mutation_commit import _owned_vertex_drop

    gremlin = _owned_vertex_drop("tenant-a", "v-1")
    assert gremlin.startswith("g.V('v-1')")
    assert "has('tenantId', 'tenant-a')" in gremlin
    assert "has('tenant_id', 'tenant-a')" in gremlin
    assert gremlin.endswith(".drop()")
