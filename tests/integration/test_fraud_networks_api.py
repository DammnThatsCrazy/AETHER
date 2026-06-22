"""Integration tests for fraud_networks routes — in-memory backend."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT.parent / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND_ROOT))
pytest.importorskip("fastapi")

import os
os.environ.setdefault("AETHER_ENV", "local")


class FakeTenant:
    def __init__(self, tenant_id: str = "t1"):
        self.tenant_id = tenant_id

    def require_permission(self, perm: str) -> None:
        return None


class FakeRequest:
    def __init__(self, tenant_id: str = "t1"):
        self.state = MagicMock()
        self.state.tenant = FakeTenant(tenant_id)


class BlockingTenant:
    def __init__(self, tenant_id: str = "t1"):
        self.tenant_id = tenant_id

    def require_permission(self, perm: str) -> None:
        from shared.common.common import ForbiddenError
        raise ForbiddenError(f"Missing permission: {perm}")


class BlockingRequest:
    def __init__(self, tenant_id: str = "t1"):
        self.state = MagicMock()
        self.state.tenant = BlockingTenant(tenant_id)


class FakeGraph:
    def __init__(self):
        self.vertices: list = []
        self.edges: list = []

    async def upsert_vertex(self, vertex):
        self.vertices.append(vertex)

    async def add_edge(self, edge):
        self.edges.append(edge)

    async def get_neighbors(self, *args, **kwargs):
        return []


class FakeProducer:
    def __init__(self):
        self.events: list = []

    async def publish(self, event):
        self.events.append(event)


def _enable_flag(routes_module, flag_name: str, value: bool) -> bool:
    cfg = routes_module.settings.fraud_intelligence
    previous = getattr(cfg, flag_name)
    object.__setattr__(cfg, flag_name, value)
    return previous


def _restore_flag(routes_module, flag_name: str, value: bool) -> None:
    cfg = routes_module.settings.fraud_intelligence
    object.__setattr__(cfg, flag_name, value)


@pytest.mark.asyncio
async def test_build_network_happy_path() -> None:
    from repositories.repos import reset_in_memory_stores, TransferRepository
    from services.fraud_networks import routes

    reset_in_memory_stores()
    prev = _enable_flag(routes, "fraud_networks_enabled", True)
    transfer_repo = TransferRepository()
    await transfer_repo.insert("tx1", {
        "id": "tx1", "from_entity_id": "e1", "to_entity_id": "e2",
        "amount": "500", "tenant_id": "t1",
    })
    await transfer_repo.insert("tx2", {
        "id": "tx2", "from_entity_id": "e2", "to_entity_id": "e1",
        "amount": "450", "tenant_id": "t1",
    })

    graph = FakeGraph()
    producer = FakeProducer()
    try:
        body = routes.FraudNetworkBuildRequest(
            tenant_id="t1",
            anchor_entity_ids=["e1", "e2"],
            network_type="mule_network",
            label="Test Circular",
        )
        resp = await routes.build_network(body, FakeRequest(), graph=graph, producer=producer)
        assert resp["tenant_id"] == "t1"
        assert resp["status"] in ("active", "detected")
        assert resp["member_count"] >= 0
        assert resp["risk_score"] >= 0.0
        assert "id" in resp
    finally:
        _restore_flag(routes, "fraud_networks_enabled", prev)


@pytest.mark.asyncio
async def test_list_networks_returns_only_tenant_networks() -> None:
    from repositories.repos import reset_in_memory_stores
    from services.fraud_networks import routes

    reset_in_memory_stores()
    prev = _enable_flag(routes, "fraud_networks_enabled", True)
    graph = FakeGraph()
    producer = FakeProducer()
    try:
        body_t1 = routes.FraudNetworkBuildRequest(
            tenant_id="t1",
            anchor_entity_ids=["eA"],
            network_type="mule_network",
            label="Mule ring T1",
        )
        body_t2 = routes.FraudNetworkBuildRequest(
            tenant_id="t2",
            anchor_entity_ids=["eA"],
            network_type="mule_network",
            label="Mule ring T2",
        )
        await routes.build_network(body_t1, FakeRequest("t1"), graph=graph, producer=producer)
        await routes.build_network(body_t2, FakeRequest("t2"), graph=graph, producer=producer)

        list_resp = await routes.list_networks(FakeRequest("t1"), tenant_id="t1", status=None, limit=50)
        networks = list_resp["data"]
        assert len(networks) == 1
        assert all(n["tenant_id"] == "t1" for n in networks)
    finally:
        _restore_flag(routes, "fraud_networks_enabled", prev)


@pytest.mark.asyncio
async def test_get_network_by_id() -> None:
    from repositories.repos import reset_in_memory_stores
    from services.fraud_networks import routes

    reset_in_memory_stores()
    prev = _enable_flag(routes, "fraud_networks_enabled", True)
    graph = FakeGraph()
    producer = FakeProducer()
    try:
        body = routes.FraudNetworkBuildRequest(
            tenant_id="t1",
            anchor_entity_ids=["eB"],
            network_type="unknown",
            label="Device ring",
        )
        resp = await routes.build_network(body, FakeRequest(), graph=graph, producer=producer)
        network_id = resp["id"]

        get_resp = await routes.get_network(network_id, FakeRequest(), tenant_id="t1")
        assert get_resp["id"] == network_id
    finally:
        _restore_flag(routes, "fraud_networks_enabled", prev)


@pytest.mark.asyncio
async def test_get_network_wrong_tenant_raises_404() -> None:
    from repositories.repos import reset_in_memory_stores
    from services.fraud_networks import routes
    from shared.common.common import NotFoundError

    reset_in_memory_stores()
    prev = _enable_flag(routes, "fraud_networks_enabled", True)
    graph = FakeGraph()
    producer = FakeProducer()
    try:
        body = routes.FraudNetworkBuildRequest(
            tenant_id="t1",
            anchor_entity_ids=["eC"],
            network_type="mule_network",
            label="T1 network",
        )
        resp = await routes.build_network(body, FakeRequest("t1"), graph=graph, producer=producer)
        network_id = resp["id"]
        with pytest.raises(NotFoundError):
            await routes.get_network(network_id, FakeRequest("t2"), tenant_id="t2")
    finally:
        _restore_flag(routes, "fraud_networks_enabled", prev)


@pytest.mark.asyncio
async def test_get_network_graph_returns_cytoscape_payload() -> None:
    from repositories.repos import reset_in_memory_stores
    from services.fraud_networks import routes

    reset_in_memory_stores()
    prev = _enable_flag(routes, "fraud_networks_enabled", True)
    graph = FakeGraph()
    producer = FakeProducer()
    try:
        body = routes.FraudNetworkBuildRequest(
            tenant_id="t1",
            anchor_entity_ids=["eD", "eE"],
            network_type="mule_network",
            label="Graph test",
        )
        resp = await routes.build_network(body, FakeRequest(), graph=graph, producer=producer)
        network_id = resp["id"]

        graph_resp = await routes.get_network_graph(network_id, FakeRequest(), tenant_id="t1")
        assert "nodes" in graph_resp
        assert "edges" in graph_resp
        assert isinstance(graph_resp["nodes"], list)
    finally:
        _restore_flag(routes, "fraud_networks_enabled", prev)


@pytest.mark.asyncio
async def test_get_network_members() -> None:
    from repositories.repos import reset_in_memory_stores
    from services.fraud_networks import routes

    reset_in_memory_stores()
    prev = _enable_flag(routes, "fraud_networks_enabled", True)
    graph = FakeGraph()
    producer = FakeProducer()
    try:
        body = routes.FraudNetworkBuildRequest(
            tenant_id="t1",
            anchor_entity_ids=["eF", "eG"],
            network_type="mule_network",
            label="Members test",
        )
        resp = await routes.build_network(body, FakeRequest(), graph=graph, producer=producer)
        network_id = resp["id"]

        members_resp = await routes.get_members(network_id, FakeRequest(), tenant_id="t1")
        assert isinstance(members_resp["data"], list)
        assert len(members_resp["data"]) >= 0
    finally:
        _restore_flag(routes, "fraud_networks_enabled", prev)


@pytest.mark.asyncio
async def test_refresh_network() -> None:
    from repositories.repos import reset_in_memory_stores
    from services.fraud_networks import routes

    reset_in_memory_stores()
    prev = _enable_flag(routes, "fraud_networks_enabled", True)
    graph = FakeGraph()
    producer = FakeProducer()
    try:
        body = routes.FraudNetworkBuildRequest(
            tenant_id="t1",
            anchor_entity_ids=["eH"],
            network_type="mule_network",
            label="Refresh test",
        )
        resp = await routes.build_network(body, FakeRequest(), graph=graph, producer=producer)
        network_id = resp["id"]
        initial_events = len(producer.events)

        refresh_resp = await routes.refresh_network(
            network_id, FakeRequest(), tenant_id="t1", producer=producer
        )
        assert refresh_resp["id"] == network_id
        assert len(producer.events) > initial_events
    finally:
        _restore_flag(routes, "fraud_networks_enabled", prev)


@pytest.mark.asyncio
async def test_escalate_network() -> None:
    from repositories.repos import reset_in_memory_stores
    from services.fraud_networks import routes

    reset_in_memory_stores()
    prev = _enable_flag(routes, "fraud_networks_enabled", True)
    graph = FakeGraph()
    producer = FakeProducer()
    try:
        body = routes.FraudNetworkBuildRequest(
            tenant_id="t1",
            anchor_entity_ids=["eI"],
            network_type="mule_network",
            label="Escalate test",
        )
        resp = await routes.build_network(body, FakeRequest(), graph=graph, producer=producer)
        network_id = resp["id"]

        escalate_resp = await routes.escalate_network(
            network_id,
            routes.NetworkStatusUpdateRequest(tenant_id="t1"),
            FakeRequest(),
            producer=producer,
        )
        assert escalate_resp["status"] == "escalated"
    finally:
        _restore_flag(routes, "fraud_networks_enabled", prev)


@pytest.mark.asyncio
async def test_suppress_network() -> None:
    from repositories.repos import reset_in_memory_stores
    from services.fraud_networks import routes

    reset_in_memory_stores()
    prev = _enable_flag(routes, "fraud_networks_enabled", True)
    graph = FakeGraph()
    producer = FakeProducer()
    try:
        body = routes.FraudNetworkBuildRequest(
            tenant_id="t1",
            anchor_entity_ids=["eJ"],
            network_type="mule_network",
            label="Suppress test",
        )
        resp = await routes.build_network(body, FakeRequest(), graph=graph, producer=producer)
        network_id = resp["id"]

        suppress_resp = await routes.suppress_network(
            network_id,
            routes.NetworkStatusUpdateRequest(tenant_id="t1", reason="false positive"),
            FakeRequest(),
            producer=producer,
        )
        assert suppress_resp["status"] == "suppressed"
    finally:
        _restore_flag(routes, "fraud_networks_enabled", prev)


@pytest.mark.asyncio
async def test_missing_permission_raises_forbidden() -> None:
    from repositories.repos import reset_in_memory_stores
    from services.fraud_networks import routes
    from shared.common.common import ForbiddenError

    reset_in_memory_stores()
    prev = _enable_flag(routes, "fraud_networks_enabled", True)
    try:
        body = routes.FraudNetworkBuildRequest(
            tenant_id="t1",
            anchor_entity_ids=["eK"],
            network_type="mule_network",
            label="Forbidden test",
        )
        with pytest.raises(ForbiddenError):
            await routes.build_network(
                body, BlockingRequest(), graph=FakeGraph(), producer=FakeProducer()
            )
    finally:
        _restore_flag(routes, "fraud_networks_enabled", prev)


@pytest.mark.asyncio
async def test_feature_disabled_raises_404() -> None:
    from repositories.repos import reset_in_memory_stores
    from services.fraud_networks import routes
    from shared.common.common import NotFoundError

    reset_in_memory_stores()
    prev = _enable_flag(routes, "fraud_networks_enabled", False)
    try:
        body = routes.FraudNetworkBuildRequest(
            tenant_id="t1",
            anchor_entity_ids=["eL"],
            network_type="mule_network",
            label="Disabled test",
        )
        with pytest.raises(NotFoundError):
            await routes.build_network(
                body, FakeRequest(), graph=FakeGraph(), producer=FakeProducer()
            )
    finally:
        _restore_flag(routes, "fraud_networks_enabled", prev)
