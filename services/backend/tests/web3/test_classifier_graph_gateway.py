from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest

from config.settings import settings
from repositories.graph_mutation_ledger import (
    GraphMutationLedgerRepository,
    reset_graph_ledger_memory,
)
from shared.graph.mutation_gateway import GraphMutationGateway
from services.web3 import classifier, routes


TENANT = "tenant-web3-gateway"
OBSERVATION = {
    "observation_type": "contract_call",
    "chain_id": "1",
    "tx_hash": "0xABC",
    "from_address": "0xWallet",
    "to_address": "0xContract",
    "protocol_id": "proto-1",
    "app_id": "app-1",
    "domain": "example.test",
    "provenance": {"source": "fixture-provider"},
}


class RecordingGraph:
    def __init__(self) -> None:
        self.vertices = {}
        self.edges = []

    async def upsert_vertex(self, vertex):
        self.vertices[vertex.vertex_id] = vertex
        return vertex.vertex_id

    async def add_vertex(self, vertex):
        self.vertices[vertex.vertex_id] = vertex
        return vertex.vertex_id

    async def add_edge(self, edge):
        self.edges.append(edge)


def _registries():
    return (object(), object(), object(), object())


@pytest.fixture(autouse=True)
def reset_ledger():
    reset_graph_ledger_memory()
    yield
    reset_graph_ledger_memory()


@pytest.fixture
def enforce_gateway(monkeypatch):
    monkeypatch.setattr(
        settings,
        "temporal_observatory",
        dataclasses.replace(
            settings.temporal_observatory, mutation_gateway_mode="enforce"
        ),
    )


@pytest.mark.asyncio
async def test_observation_builder_awaits_gateway_and_carries_tenant_provenance(monkeypatch):
    async def classify_contract(*_args):
        return {"completeness": "protocol_mapped", "protocol_id": "proto-1"}

    async def attribute_domain(*_args):
        return {"app_id": "app-1", "verified": True, "protocol_ids": ["proto-1"]}

    monkeypatch.setattr(classifier, "classify_contract", classify_contract)
    monkeypatch.setattr(classifier, "attribute_domain", attribute_domain)

    graph = RecordingGraph()
    actual_gateway = GraphMutationGateway(graph_client=graph)
    applied = []

    class CapturingGateway:
        async def apply(self, intent):
            applied.append(intent)
            return await actual_gateway.apply(intent)

    monkeypatch.setattr(classifier, "GraphMutationGateway", lambda **_kwargs: CapturingGateway())
    result = await classifier.build_graph_from_observation(
        dict(OBSERVATION), graph, *_registries(), tenant_id=TENANT,
    )

    assert result == {"vertices_created": 6, "edges_created": 5}
    assert len(graph.vertices) == 6
    assert len(graph.edges) == 5
    assert len(applied) == 11
    assert {intent.tenant_id for intent in applied} == {TENANT}
    assert {intent.source_event_id for intent in applied} == {"web3:1:0xabc"}
    assert all(vertex.properties["tenantId"] == TENANT for vertex in graph.vertices.values())
    assert all(edge.properties["tenant_id"] == TENANT for edge in graph.edges)
    assert all(edge.properties["provenance"] == "web3:fixture-provider" for edge in graph.edges)
    assert all(edge.properties["source_event_id"] == "web3:1:0xabc" for edge in graph.edges)
    assert all(edge.properties["idempotency_key"] for edge in graph.edges)


@pytest.mark.asyncio
async def test_tenant_scopes_web3_vertex_ids(monkeypatch):
    async def classify_contract(*_args):
        return {"completeness": "raw_observed", "protocol_id": ""}

    monkeypatch.setattr(classifier, "classify_contract", classify_contract)
    graph = RecordingGraph()
    observation = {**OBSERVATION, "protocol_id": "", "app_id": "", "domain": ""}

    await classifier.build_graph_from_observation(
        dict(observation), graph, *_registries(), tenant_id="tenant-a",
    )
    await classifier.build_graph_from_observation(
        dict(observation), graph, *_registries(), tenant_id="tenant-b",
    )

    assert "tenant-a:wallet:0xwallet" in graph.vertices
    assert "tenant-b:wallet:0xwallet" in graph.vertices
    assert len(graph.vertices) == 6
    assert {edge.properties["tenant_id"] for edge in graph.edges} == {"tenant-a", "tenant-b"}
    assert len({edge.from_vertex_id for edge in graph.edges}) == 2


@pytest.mark.asyncio
async def test_observation_builder_rejects_missing_tenant_before_writing():
    graph = RecordingGraph()
    with pytest.raises(ValueError, match="tenant_id is required"):
        await classifier.build_graph_from_observation(
            dict(OBSERVATION), graph, *_registries(), tenant_id="",
        )
    assert graph.vertices == {}
    assert graph.edges == []


@pytest.mark.asyncio
async def test_observation_builder_recovers_after_partial_gateway_failure(enforce_gateway, monkeypatch):
    async def classify_contract(*_args):
        return {"completeness": "raw_observed", "protocol_id": ""}

    monkeypatch.setattr(classifier, "classify_contract", classify_contract)
    observation = {
        **OBSERVATION,
        "protocol_id": "",
        "app_id": "",
        "domain": "",
    }
    graph = RecordingGraph()
    actual_gateway = GraphMutationGateway(graph_client=graph)
    state = {"calls": 0, "failed": False}

    class FailOnceGateway:
        async def apply(self, intent):
            state["calls"] += 1
            # The first two vertex writes succeed; fail before the first edge
            # reaches the gateway, then replay the same source transaction.
            if state["calls"] == 3 and not state["failed"]:
                state["failed"] = True
                raise RuntimeError("injected gateway outage before edge apply")
            return await actual_gateway.apply(intent)

    flaky = FailOnceGateway()
    monkeypatch.setattr(classifier, "GraphMutationGateway", lambda **_kwargs: flaky)
    with pytest.raises(RuntimeError, match="injected gateway outage"):
        await classifier.build_graph_from_observation(
            dict(observation), graph, *_registries(), tenant_id=TENANT,
        )

    assert len(graph.vertices) == 2
    assert graph.edges == []

    result = await classifier.build_graph_from_observation(
        dict(observation), graph, *_registries(), tenant_id=TENANT,
    )
    assert result == {"vertices_created": 3, "edges_created": 1}
    assert len(graph.vertices) == 3
    assert len(graph.edges) == 1
    assert graph.edges[0].properties["source_event_id"] == "web3:1:0xabc"


@pytest.mark.asyncio
async def test_replaying_same_transaction_adds_no_new_ledger_versions(enforce_gateway, monkeypatch):
    async def classify_contract(*_args):
        return {"completeness": "raw_observed", "protocol_id": ""}

    monkeypatch.setattr(classifier, "classify_contract", classify_contract)
    graph = RecordingGraph()
    gateway = GraphMutationGateway(graph_client=graph)
    monkeypatch.setattr(classifier, "GraphMutationGateway", lambda **_kwargs: gateway)
    observation = {
        **OBSERVATION,
        "protocol_id": "",
        "app_id": "",
        "domain": "",
    }
    ledger = GraphMutationLedgerRepository()

    await classifier.build_graph_from_observation(
        dict(observation), graph, *_registries(), tenant_id=TENANT,
    )
    first_rows = await ledger.list_records(TENANT)
    await classifier.build_graph_from_observation(
        dict(observation), graph, *_registries(), tenant_id=TENANT,
    )
    second_rows = await ledger.list_records(TENANT)

    assert len(first_rows) == 4
    assert len(second_rows) == len(first_rows)
    assert len(graph.vertices) == 3
    assert len(graph.edges) == 1


@pytest.mark.asyncio
async def test_migration_detector_awaits_tenant_scoped_gateway(monkeypatch):
    class ContractRegistry:
        async def list_by_protocol(self, _protocol_id):
            return [{"chain_id": "1", "status": "active", "address": "0xold", "deployed_by": "0xdeployer"}]

        async def get_by_address(self, _chain_id, _address):
            return {"deployed_by": "0xDeployer"}

    class ProtocolRegistry:
        async def get_by_protocol_id(self, _protocol_id):
            return {"protocol_id": "proto-1"}

    graph = RecordingGraph()
    actual_gateway = GraphMutationGateway(graph_client=graph)
    applied = []

    class CapturingGateway:
        async def apply(self, intent):
            applied.append(intent)
            return await actual_gateway.apply(intent)

    monkeypatch.setattr(classifier, "GraphMutationGateway", lambda **_kwargs: CapturingGateway())
    result = await classifier.detect_migration(
        "proto-1", "0xNEW", "1", ContractRegistry(), ProtocolRegistry(), graph,
        tenant_id=TENANT,
    )

    assert result and result["from_contract"] == "0xold"
    assert len(graph.edges) == 1
    assert applied[0].tenant_id == TENANT
    assert applied[0].source_event_id is None
    assert graph.edges[0].properties["tenant_id"] == TENANT
    assert graph.edges[0].properties["provenance"] == "web3:migration_detector"


class FakeRequest:
    def __init__(self, body, tenant_id=TENANT):
        self._body = body
        self.state = SimpleNamespace(tenant_id=tenant_id)

    async def json(self):
        return self._body


@pytest.mark.asyncio
async def test_observation_routes_forward_authenticated_tenant(monkeypatch):
    seen_tenants = []
    seen_migration_tenants = []

    async def record(body, tenant_id):
        body["observation_id"] = "record-generated-id"
        return body

    async def build(*_args, tenant_id):
        seen_tenants.append(tenant_id)
        return {"vertices_created": 0, "edges_created": 0}

    async def detect(*_args, tenant_id):
        seen_migration_tenants.append(tenant_id)
        return {"migration_type": "redeploy"}

    async def record_migration(_result, _tenant_id):
        return {}

    monkeypatch.setattr(routes.observation_repo, "record", record)
    monkeypatch.setattr(routes, "build_graph_from_observation", build)
    monkeypatch.setattr(routes, "detect_migration", detect)
    monkeypatch.setattr(routes.migration_reg, "record_migration", record_migration)
    monkeypatch.setattr("shared.graph.graph.GraphClient", lambda: RecordingGraph())

    await routes.classify_observation_endpoint(FakeRequest({"build_graph": True}))

    monkeypatch.setattr(routes, "require_permission", lambda *_args: None)
    await routes.ingest_observations_batch(FakeRequest({"build_graph": True, "observations": [{}]}))
    await routes.detect_migration_endpoint(FakeRequest({
        "protocol_id": "proto-1", "address": "0xnew", "chain_id": "1",
    }))
    assert seen_tenants == [TENANT, TENANT]
    assert seen_migration_tenants == [TENANT]
