"""Integration tests for flow_trace routes — in-memory backend."""

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
async def test_create_trace_happy_path() -> None:
    from repositories.repos import reset_in_memory_stores, TransferRepository
    from services.flow_trace import routes

    reset_in_memory_stores()
    prev = _enable_flag(routes, "flow_trace_enabled", True)
    repo = TransferRepository()
    await repo.insert("tx1", {
        "id": "tx1", "from_entity_id": "e1", "to_entity_id": "e2",
        "amount": "500", "tenant_id": "t1",
    })
    graph = FakeGraph()
    producer = FakeProducer()
    try:
        body = routes.FlowTraceRequest(
            tenant_id="t1",
            anchor_entity_id="e1",
            direction="downstream",
            max_hops=3,
        )
        resp = await routes.create_trace(body, FakeRequest(), graph=graph, producer=producer)
        assert resp["tenant_id"] == "t1"
        assert resp["anchor_entity_id"] == "e1"
        assert isinstance(resp["path_count"], int)
    finally:
        _restore_flag(routes, "flow_trace_enabled", prev)


@pytest.mark.asyncio
async def test_trace_identifies_sinks() -> None:
    from repositories.repos import reset_in_memory_stores, TransferRepository
    from services.flow_trace import routes

    reset_in_memory_stores()
    prev = _enable_flag(routes, "flow_trace_enabled", True)
    repo = TransferRepository()
    for i, (frm, to) in enumerate([("anchor", "e2"), ("anchor", "e3")]):
        await repo.insert(f"tx{i}", {
            "id": f"tx{i}", "from_entity_id": frm, "to_entity_id": to,
            "amount": "200", "tenant_id": "t1",
        })
    graph = FakeGraph()
    producer = FakeProducer()
    try:
        body = routes.FlowTraceRequest(
            tenant_id="t1",
            anchor_entity_id="anchor",
            direction="downstream",
            max_hops=3,
        )
        resp = await routes.create_trace(body, FakeRequest(), graph=graph, producer=producer)
        assert len(resp["sink_nodes"]) >= 1
        assert "e2" in resp["sink_nodes"] or "e3" in resp["sink_nodes"]
    finally:
        _restore_flag(routes, "flow_trace_enabled", prev)


@pytest.mark.asyncio
async def test_trace_detects_cycles() -> None:
    from repositories.repos import reset_in_memory_stores, TransferRepository
    from services.flow_trace import routes

    reset_in_memory_stores()
    prev = _enable_flag(routes, "flow_trace_enabled", True)
    repo = TransferRepository()
    for tx_id, frm, to in [("tx1", "e1", "e2"), ("tx2", "e2", "e3"), ("tx3", "e3", "e1")]:
        await repo.insert(tx_id, {
            "id": tx_id, "from_entity_id": frm, "to_entity_id": to,
            "amount": "100", "tenant_id": "t1",
        })
    graph = FakeGraph()
    producer = FakeProducer()
    try:
        body = routes.FlowTraceRequest(
            tenant_id="t1",
            anchor_entity_id="e1",
            direction="downstream",
            max_hops=6,
        )
        resp = await routes.create_trace(body, FakeRequest(), graph=graph, producer=producer)
        assert resp["cycle_detected"] is True
    finally:
        _restore_flag(routes, "flow_trace_enabled", prev)


@pytest.mark.asyncio
async def test_tenant_isolation_in_trace() -> None:
    from repositories.repos import reset_in_memory_stores, TransferRepository
    from services.flow_trace import routes

    reset_in_memory_stores()
    prev = _enable_flag(routes, "flow_trace_enabled", True)
    repo = TransferRepository()
    await repo.insert("tx1", {
        "id": "tx1", "from_entity_id": "anchor", "to_entity_id": "eX",
        "amount": "100", "tenant_id": "t1",
    })
    graph = FakeGraph()
    producer = FakeProducer()
    try:
        body = routes.FlowTraceRequest(
            tenant_id="t2",
            anchor_entity_id="anchor",
            direction="downstream",
            max_hops=3,
        )
        resp = await routes.create_trace(body, FakeRequest("t2"), graph=graph, producer=producer)
        assert "eX" not in resp["sink_nodes"]
    finally:
        _restore_flag(routes, "flow_trace_enabled", prev)


@pytest.mark.asyncio
async def test_get_trace_by_id() -> None:
    from repositories.repos import reset_in_memory_stores
    from services.flow_trace import routes

    reset_in_memory_stores()
    prev = _enable_flag(routes, "flow_trace_enabled", True)
    graph = FakeGraph()
    producer = FakeProducer()
    try:
        body = routes.FlowTraceRequest(
            tenant_id="t1",
            anchor_entity_id="anchor2",
            direction="both",
            max_hops=2,
        )
        resp = await routes.create_trace(body, FakeRequest(), graph=graph, producer=producer)
        trace_id = resp["id"]

        get_resp = await routes.get_trace(trace_id, FakeRequest(), tenant_id="t1")
        assert get_resp["id"] == trace_id
    finally:
        _restore_flag(routes, "flow_trace_enabled", prev)


@pytest.mark.asyncio
async def test_get_trace_wrong_tenant_raises_404() -> None:
    from repositories.repos import reset_in_memory_stores
    from services.flow_trace import routes
    from shared.common.common import NotFoundError

    reset_in_memory_stores()
    prev = _enable_flag(routes, "flow_trace_enabled", True)
    graph = FakeGraph()
    producer = FakeProducer()
    try:
        body = routes.FlowTraceRequest(
            tenant_id="t1",
            anchor_entity_id="anchor3",
            direction="downstream",
            max_hops=2,
        )
        resp = await routes.create_trace(body, FakeRequest("t1"), graph=graph, producer=producer)
        trace_id = resp["id"]
        with pytest.raises(NotFoundError):
            await routes.get_trace(trace_id, FakeRequest("t2"), tenant_id="t2")
    finally:
        _restore_flag(routes, "flow_trace_enabled", prev)


@pytest.mark.asyncio
async def test_list_traces_tenant_scoped() -> None:
    from repositories.repos import reset_in_memory_stores
    from services.flow_trace import routes

    reset_in_memory_stores()
    prev = _enable_flag(routes, "flow_trace_enabled", True)
    graph = FakeGraph()
    producer = FakeProducer()
    try:
        body_t1 = routes.FlowTraceRequest(
            tenant_id="t1",
            anchor_entity_id="anchorL",
            direction="downstream",
            max_hops=2,
        )
        body_t2 = routes.FlowTraceRequest(
            tenant_id="t2",
            anchor_entity_id="anchorL",
            direction="downstream",
            max_hops=2,
        )
        await routes.create_trace(body_t1, FakeRequest("t1"), graph=graph, producer=producer)
        await routes.create_trace(body_t2, FakeRequest("t2"), graph=graph, producer=producer)

        list_resp = await routes.list_traces(FakeRequest("t1"), tenant_id="t1", limit=50)
        traces = list_resp["data"]
        assert len(traces) == 1
        assert all(t["tenant_id"] == "t1" for t in traces)
    finally:
        _restore_flag(routes, "flow_trace_enabled", prev)


@pytest.mark.asyncio
async def test_feature_disabled_raises_404() -> None:
    from repositories.repos import reset_in_memory_stores
    from services.flow_trace import routes
    from shared.common.common import NotFoundError

    reset_in_memory_stores()
    prev = _enable_flag(routes, "flow_trace_enabled", False)
    try:
        body = routes.FlowTraceRequest(
            tenant_id="t1",
            anchor_entity_id="any",
            direction="downstream",
            max_hops=2,
        )
        with pytest.raises(NotFoundError):
            await routes.create_trace(body, FakeRequest(), graph=FakeGraph(), producer=FakeProducer())
    finally:
        _restore_flag(routes, "flow_trace_enabled", prev)


@pytest.mark.asyncio
async def test_depth_bounds_respected() -> None:
    from repositories.repos import reset_in_memory_stores, TransferRepository
    from services.flow_trace import routes

    reset_in_memory_stores()
    prev = _enable_flag(routes, "flow_trace_enabled", True)
    repo = TransferRepository()
    for i in range(1, 6):
        await repo.insert(f"txD{i}", {
            "id": f"txD{i}", "from_entity_id": f"d{i}", "to_entity_id": f"d{i+1}",
            "amount": "100", "tenant_id": "t1",
        })
    graph = FakeGraph()
    producer = FakeProducer()
    try:
        body = routes.FlowTraceRequest(
            tenant_id="t1",
            anchor_entity_id="d1",
            direction="downstream",
            max_hops=2,
        )
        resp = await routes.create_trace(body, FakeRequest(), graph=graph, producer=producer)
        assert "d6" not in resp["sink_nodes"]
        assert "d6" not in resp["source_nodes"]
        assert "d6" not in resp["aggregation_points"]
    finally:
        _restore_flag(routes, "flow_trace_enabled", prev)
