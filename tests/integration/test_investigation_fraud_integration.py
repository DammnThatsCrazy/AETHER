"""Integration tests — investigations linked to fraud networks and flow traces."""

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


async def _create_investigation(inv_routes, tenant_id: str = "t1") -> str:
    from services.investigation.routes import CreateCaseRequest
    from services.operational_intelligence.models import EntityRef
    producer = FakeProducer()
    case = await inv_routes.create_case(
        CreateCaseRequest(
            tenantId=tenant_id,
            title="Fraud investigation",
            subjects=[EntityRef(kind="user", id="e1")],
            createdBy="analyst-1",
        ),
        FakeRequest(tenant_id),
        producer=producer,
    )
    return case.id


async def _create_fraud_network(fn_routes, tenant_id: str = "t1") -> str:
    graph = FakeGraph()
    producer = FakeProducer()
    resp = await fn_routes.build_network(
        fn_routes.FraudNetworkBuildRequest(
            tenant_id=tenant_id,
            anchor_entity_ids=["e1"],
            network_type="mule_network",
            label="Test network",
        ),
        FakeRequest(tenant_id),
        graph=graph,
        producer=producer,
    )
    return resp["id"]


async def _create_flow_trace(ft_routes, tenant_id: str = "t1") -> str:
    graph = FakeGraph()
    producer = FakeProducer()
    resp = await ft_routes.create_trace(
        ft_routes.FlowTraceRequest(
            tenant_id=tenant_id,
            anchor_entity_id="e1",
            direction="downstream",
            max_hops=3,
        ),
        FakeRequest(tenant_id),
        graph=graph,
        producer=producer,
    )
    return resp["id"]


@pytest.mark.asyncio
async def test_attach_fraud_network_to_case() -> None:
    from repositories.repos import reset_in_memory_stores
    from services.investigation import routes as inv_routes
    from services.fraud_networks import routes as fn_routes

    reset_in_memory_stores()
    prev_fn = _enable_flag(fn_routes, "fraud_networks_enabled", True)
    try:
        case_id = await _create_investigation(inv_routes)
        network_id = await _create_fraud_network(fn_routes)

        producer = FakeProducer()
        updated_case = await inv_routes.attach_fraud_network(
            case_id,
            inv_routes.AttachFraudNetworkRequest(
                tenantId="t1",
                network_id=network_id,
            ),
            FakeRequest(),
            producer=producer,
        )
        assert updated_case.id == case_id
        assert updated_case.graphStateId == network_id
    finally:
        _restore_flag(fn_routes, "fraud_networks_enabled", prev_fn)


@pytest.mark.asyncio
async def test_attach_flow_trace_to_case() -> None:
    from repositories.repos import reset_in_memory_stores
    from services.investigation import routes as inv_routes
    from services.flow_trace import routes as ft_routes

    reset_in_memory_stores()
    prev_ft = _enable_flag(ft_routes, "flow_trace_enabled", True)
    try:
        case_id = await _create_investigation(inv_routes)
        trace_id = await _create_flow_trace(ft_routes)

        producer = FakeProducer()
        updated_case = await inv_routes.attach_flow_trace(
            case_id,
            inv_routes.AttachFlowTraceRequest(
                tenantId="t1",
                trace_id=trace_id,
            ),
            FakeRequest(),
            producer=producer,
        )
        assert updated_case.id == case_id
        assert len(updated_case.evidence) > 0
    finally:
        _restore_flag(ft_routes, "flow_trace_enabled", prev_ft)


@pytest.mark.asyncio
async def test_get_fraud_summary_for_case() -> None:
    from repositories.repos import reset_in_memory_stores
    from services.investigation import routes as inv_routes
    from services.fraud_networks import routes as fn_routes

    reset_in_memory_stores()
    prev_fn = _enable_flag(fn_routes, "fraud_networks_enabled", True)
    try:
        case_id = await _create_investigation(inv_routes)
        network_id = await _create_fraud_network(fn_routes)

        producer = FakeProducer()
        await inv_routes.attach_fraud_network(
            case_id,
            inv_routes.AttachFraudNetworkRequest(tenantId="t1", network_id=network_id),
            FakeRequest(),
            producer=producer,
        )

        summary = await inv_routes.get_fraud_summary(case_id, FakeRequest(), tenantId="t1")
        assert summary["case_id"] == case_id
        assert summary.get("fraud_network") is not None
    finally:
        _restore_flag(fn_routes, "fraud_networks_enabled", prev_fn)


@pytest.mark.asyncio
async def test_get_full_report_for_case() -> None:
    from repositories.repos import reset_in_memory_stores
    from services.investigation import routes as inv_routes

    reset_in_memory_stores()
    case_id = await _create_investigation(inv_routes)

    report = await inv_routes.get_report(case_id, FakeRequest(), tenantId="t1")
    assert report["case"]["id"] == case_id
    assert "subjects" in report
    assert "timeline" in report or "evidence" in report


@pytest.mark.asyncio
async def test_export_case_bundle() -> None:
    from repositories.repos import reset_in_memory_stores
    from services.investigation import routes as inv_routes

    reset_in_memory_stores()
    case_id = await _create_investigation(inv_routes)

    bundle = await inv_routes.export_case(case_id, FakeRequest(), tenantId="t1")
    assert bundle["case"]["id"] == case_id
    assert "case" in bundle
