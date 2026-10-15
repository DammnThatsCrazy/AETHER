"""Simulator determinism, conformance suite behavior (including catching a
deliberately broken adapter), reconciliation, and route gates."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from value.derivatives.adapters.base import DerivativesAdapter
from value.derivatives.adapters.conformance import run_conformance
from value.derivatives.adapters.simulator import SimulatorAdapter
from value.derivatives.runtime_reconciliation import DerivativesReconciliation

TENANT = "t-deriv-a"
OTHER_TENANT = "t-deriv-b"

_FLAGS_ON = SimpleNamespace(
    runtime_enabled=True, adapters_enabled=True,
    reconciliation_enabled=True, pnl_enabled=True, graph_enabled=True,
    profile360_enabled=True, api_enabled=True, noesis_enabled=True, kyber_enabled=True,
)
_FLAGS_OFF = SimpleNamespace(
    runtime_enabled=False, adapters_enabled=False,
    reconciliation_enabled=False, pnl_enabled=False, graph_enabled=False,
    profile360_enabled=False, api_enabled=False, noesis_enabled=False, kyber_enabled=False,
)


# ── Simulator + conformance ──────────────────────────────────────────────────

async def test_simulator_is_deterministic_per_seed():
    first, checkpoint = await SimulatorAdapter(seed=7).pull_events(None)
    second, _ = await SimulatorAdapter(seed=7).pull_events(None)
    different, _ = await SimulatorAdapter(seed=8).pull_events(None)
    assert first == second
    assert first != different
    assert checkpoint == {"cursor": len(first)}


async def test_simulator_passes_full_conformance():
    report = await run_conformance(SimulatorAdapter())
    failing = [c for c in report["checks"] if not c["passed"]]
    assert report["passed"], failing


async def test_conformance_catches_float_amounts_and_trade_authority():
    class BrokenAdapter(DerivativesAdapter):
        adapter_id = "broken"
        display_name = "Broken"

        def validate_config(self, config):  # accepts anything — violation
            return None

        async def test_connection(self):
            return {"ok": True}

        async def pull_events(self, checkpoint=None):
            return ([{
                "event_name": "derivatives_fill_observed",
                "payload": {"fill_id": "f1", "price": 100.5, "quantity": "1"},
                "execution_by_aether": False,
            }], {"cursor": 1})

    report = await run_conformance(BrokenAdapter())
    assert report["passed"] is False
    failed = {c["name"] for c in report["checks"] if not c["passed"]}
    assert "decimal_only_amounts" in failed
    assert "refuses_trade_authority" in failed


async def test_conformance_catches_execution_claims():
    class ExecutingAdapter(SimulatorAdapter):
        adapter_id = "executing"

        async def pull_events(self, checkpoint=None):
            events, cp = await super().pull_events(checkpoint)
            for event in events:
                event["execution_by_aether"] = True
            return events, cp

    report = await run_conformance(ExecutingAdapter())
    failed = {c["name"] for c in report["checks"] if not c["passed"]}
    assert "never_claims_execution" in failed


# ── Reconciliation ───────────────────────────────────────────────────────────

async def test_reconciliation_detects_position_variance():
    service = DerivativesReconciliation()
    result = await service.reconcile_account(
        TENANT, "acct-1",
        venue_snapshot={"size": Decimal("2"), "realized_pnl": Decimal("10")},
        projected={"size": Decimal("2"), "realized_pnl": Decimal("9")},
    )
    assert result["variance_count"] == 1
    names = [e["event_name"] for e in result["emitted_events"]]
    assert names[0] == "derivatives_reconciliation_run_completed"
    assert "derivatives_reconciliation_variance_detected" in names


async def test_reconciliation_matches_within_tolerance():
    service = DerivativesReconciliation()
    result = await service.reconcile_account(
        TENANT, "acct-2",
        venue_snapshot={"size": Decimal("2")},
        projected={"size": Decimal("2")},
    )
    assert result["variance_count"] == 0


# ── Routes ───────────────────────────────────────────────────────────────────

class _FakeTenant:
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self.is_platform_admin = False

    def require_permission(self, perm: str) -> None:
        return None


@pytest.fixture(autouse=True)
def _entitled_tenants(monkeypatch):
    """Grant ``derivatives.enabled`` to the test tenants via the billing authority.

    The entitlement check itself stays live: any other tenant is still denied.
    """
    from billing.billing.revops import TenantEntitlementRepository

    async def _list_for_tenant(self, tenant_id, limit=1000):
        if tenant_id in {TENANT, OTHER_TENANT}:
            return [{"tenant_id": tenant_id, "feature_key": "derivatives.enabled", "enabled": True}]
        return []

    monkeypatch.setattr(TenantEntitlementRepository, "list_for_tenant", _list_for_tenant)


def _build_app(tenant_id: str) -> TestClient:
    from value.derivatives.runtime_routes import router

    app = FastAPI()

    @app.exception_handler(PermissionError)
    async def _perm(request, exc):
        return JSONResponse(status_code=403, content={"error": str(exc)})

    app.include_router(router)

    @app.middleware("http")
    async def _inject(request: Request, call_next):
        request.state.tenant = _FakeTenant(tenant_id)
        return await call_next(request)

    return TestClient(app)


def test_flag_off_returns_404(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "derivatives", _FLAGS_OFF)
    client = _build_app(TENANT)
    assert client.get("/v1/derivatives/runtime/venues").status_code == 404


def test_account_link_and_observation_intake(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "derivatives", _FLAGS_ON)
    client = _build_app(TENANT)

    linked = client.post("/v1/derivatives/runtime/accounts/link", json={
        "venue_id": "venue:simulated",
        "external_account_ref": "acct-xyz",
    })
    assert linked.status_code == 201, linked.text
    assert linked.json()["authority_type"] == "read_only"
    replay = client.post("/v1/derivatives/runtime/accounts/link", json={
        "venue_id": "venue:simulated",
        "external_account_ref": "acct-xyz",
    })
    assert replay.json()["inserted"] is False

    fill = client.post("/v1/derivatives/runtime/observations", json={
        "event_name": "derivatives_fill_observed",
        "payload": {
            "fill_id": "f-100", "trading_account_id": "acct-xyz",
            "canonical_market_id": "sim:btc-perp", "side": "buy",
            "price": "60000", "quantity": "0.5", "executed_at": "2026-07-08T12:00:00Z",
        },
    })
    assert fill.status_code == 201, fill.text

    listed = client.get("/v1/derivatives/runtime/fills")
    assert listed.json()["count"] == 1

    other = _build_app(OTHER_TENANT).get("/v1/derivatives/runtime/fills")
    assert other.json()["count"] == 0  # tenant isolation


def test_unknown_and_non_ingestable_events_rejected(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "derivatives", _FLAGS_ON)
    client = _build_app(TENANT)
    unknown = client.post("/v1/derivatives/runtime/observations", json={
        "event_name": "derivatives_teleport_observed", "payload": {"order_id": "x"},
    })
    assert unknown.status_code == 422
    registry_only = client.post("/v1/derivatives/runtime/observations", json={
        "event_name": "derivatives_venue_registered", "payload": {"order_id": "x"},
    })
    assert registry_only.status_code == 422


def test_execution_claims_rejected(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "derivatives", _FLAGS_ON)
    client = _build_app(TENANT)
    response = client.post("/v1/derivatives/runtime/observations", json={
        "event_name": "derivatives_fill_observed",
        "payload": {"fill_id": "f-2", "execution_by_aether": True},
    })
    assert response.status_code == 422


def _order(client, order_id, event, status):
    return client.post("/v1/derivatives/runtime/observations", json={
        "event_name": event,
        "payload": {
            "order_id": order_id, "trading_account_id": "acct-xyz",
            "canonical_market_id": "sim:btc-perp", "order_status": status,
        },
    })


def test_order_observations_are_classified_against_what_is_held(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "derivatives", _FLAGS_ON)
    client = _build_app(TENANT)

    first = _order(client, "o-fsm", "derivatives_order_observed", "open")
    assert first.json()["transition"]["classification"] == "first_observation"

    advanced = _order(client, "o-fsm", "derivatives_order_updated_observed", "filled")
    assert advanced.json()["transition"]["classification"] == "advanced"

    # A late "open" after "filled" is stale evidence: stored, never a regression.
    stale = _order(client, "o-fsm", "derivatives_order_updated_observed", "open")
    assert stale.status_code == 201
    assert stale.json()["transition"] == {
        "classification": "stale", "status": "open", "held_status": "filled",
        "reason": "stale_out_of_order",
    }

    # Judged against the furthest status held, not the most recent row.
    again = _order(client, "o-fsm", "derivatives_order_updated_observed", "filled")
    assert again.json()["transition"]["classification"] == "duplicate"


def test_an_illegal_order_step_is_flagged_not_dropped(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "derivatives", _FLAGS_ON)
    client = _build_app(TENANT)
    _order(client, "o-ill", "derivatives_order_observed", "cancelled")
    odd = _order(client, "o-ill", "derivatives_order_rejected_observed", "rejected")
    assert odd.json()["transition"]["classification"] == "rejected_transition"
    assert odd.json()["inserted"] is True


def test_fills_carry_no_transition(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "derivatives", _FLAGS_ON)
    client = _build_app(TENANT)
    fill = client.post("/v1/derivatives/runtime/observations", json={
        "event_name": "derivatives_fill_observed",
        "payload": {"fill_id": "f-nt", "trading_account_id": "acct-xyz",
                    "canonical_market_id": "sim:btc-perp", "side": "buy",
                    "price": "1", "quantity": "1", "executed_at": "2026-07-08T12:00:00Z"},
    })
    assert "transition" not in fill.json()


def test_unentitled_tenant_is_denied(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "derivatives", _FLAGS_ON)
    client = _build_app("t-not-entitled")
    denied = client.post("/v1/derivatives/runtime/accounts/link", json={
        "venue_id": "venue:simulated",
        "external_account_ref": "acct-xyz",
    })
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "derivatives_not_entitled"


# ── Graph projection ─────────────────────────────────────────────────────────

@pytest.fixture
def graph(monkeypatch):
    """A fresh in-memory graph behind the routes' ``get_graph_client``."""
    from shared.graph import graph as graph_module

    client = graph_module.GraphClient()
    client._backend = graph_module._InMemoryGraphBackend()  # noqa: SLF001
    monkeypatch.setattr(graph_module, "get_graph_client", lambda: client)
    return client


async def _seed_platform(graph, vertex_id: str, vertex_type: str) -> None:
    from shared.graph.graph import Vertex

    await graph.add_vertex(Vertex(
        vertex_id=vertex_id, vertex_type=vertex_type,
        properties={"tenant_id": "platform", "label": "registry"},
    ))


def _edges(graph, edge_type: str) -> list:
    return [e for e in graph._backend._edges if e.edge_type == edge_type]  # noqa: SLF001


def _link(client, ref: str = "acct-graph"):
    return client.post("/v1/derivatives/runtime/accounts/link", json={
        "venue_id": "venue:simulated", "external_account_ref": ref,
    })


def _position(client, trading_account_id: str, position_id: str = "p-graph"):
    return client.post("/v1/derivatives/runtime/observations", json={
        "event_name": "derivatives_position_opened_observed",
        "payload": {
            "position_id": position_id, "trading_account_id": trading_account_id,
            "canonical_market_id": "sim:btc-perp", "side": "long", "status": "open",
            "size": "1",
        },
    })


async def test_account_link_never_writes_the_platform_venue(monkeypatch, graph):
    from config.settings import settings
    from shared.graph.graph import EdgeType

    monkeypatch.setattr(settings, "derivatives", _FLAGS_ON)
    linked = _link(_build_app(TENANT))
    assert linked.status_code == 201, linked.text

    account = await graph.get_vertex(f"trading_account:{linked.json()['trading_account_id']}")
    assert account.properties["tenant_id"] == TENANT
    assert await graph.get_vertex("market_venue:venue:simulated") is None
    assert _edges(graph, EdgeType.AUTHENTICATES) == []


async def test_account_link_links_the_registered_venue(monkeypatch, graph):
    from config.settings import settings
    from shared.graph.graph import EdgeType, VertexType

    monkeypatch.setattr(settings, "derivatives", _FLAGS_ON)
    await _seed_platform(graph, "market_venue:venue:simulated", VertexType.MARKET_VENUE)
    linked = _link(_build_app(TENANT))
    assert linked.status_code == 201, linked.text

    venue = await graph.get_vertex("market_venue:venue:simulated")
    assert venue.properties == {"tenant_id": "platform", "label": "registry"}
    [edge] = _edges(graph, EdgeType.AUTHENTICATES)
    assert edge.to_vertex_id == "market_venue:venue:simulated"
    assert edge.properties["tenant_id"] == TENANT


async def test_position_links_only_own_account_to_registered_market(monkeypatch, graph):
    from config.settings import settings
    from shared.graph.graph import EdgeType, VertexType

    monkeypatch.setattr(settings, "derivatives", _FLAGS_ON)
    client = _build_app(TENANT)
    account_id = _link(client).json()["trading_account_id"]

    # No registered market: the observation is stored, nothing is projected.
    assert _position(client, account_id).status_code == 201
    assert await graph.get_vertex("derivative_market:sim:btc-perp") is None
    assert _edges(graph, EdgeType.HOLDS_POSITION) == []

    await _seed_platform(graph, "derivative_market:sim:btc-perp", VertexType.MARKET)
    assert _position(client, account_id).status_code == 201
    [edge] = _edges(graph, EdgeType.HOLDS_POSITION)
    assert edge.from_vertex_id == f"trading_account:{account_id}"

    # Another tenant naming that account gets no edge from it.
    assert _position(_build_app(OTHER_TENANT), account_id, "p-other").status_code == 201
    assert len(_edges(graph, EdgeType.HOLDS_POSITION)) == 1
