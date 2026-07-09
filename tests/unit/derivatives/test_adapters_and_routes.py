"""Simulator determinism, conformance suite behavior (including catching a
deliberately broken adapter), reconciliation, and route gates."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from services.derivatives.adapters.base import DerivativesAdapter
from services.derivatives.adapters.conformance import run_conformance
from services.derivatives.adapters.simulator import SimulatorAdapter
from services.derivatives.reconciliation import DerivativesReconciliation

TENANT = "t-deriv-a"
OTHER_TENANT = "t-deriv-b"

_FLAGS_ON = SimpleNamespace(
    runtime_enabled=True, adapters_enabled=True, streams_enabled=True,
    reconciliation_enabled=True, pnl_enabled=True, graph_enabled=True,
    profile360_enabled=True, api_enabled=True, noesis_enabled=True, kyber_enabled=True,
)
_FLAGS_OFF = SimpleNamespace(
    runtime_enabled=False, adapters_enabled=False, streams_enabled=False,
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


def _build_app(tenant_id: str) -> TestClient:
    from services.derivatives.routes import router

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
    assert client.get("/v1/derivatives/venues").status_code == 404


def test_account_link_and_observation_intake(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "derivatives", _FLAGS_ON)
    client = _build_app(TENANT)

    linked = client.post("/v1/derivatives/accounts/link", json={
        "venue_id": "venue:simulated",
        "external_account_ref": "acct-xyz",
    })
    assert linked.status_code == 201, linked.text
    assert linked.json()["authority_type"] == "read_only"
    replay = client.post("/v1/derivatives/accounts/link", json={
        "venue_id": "venue:simulated",
        "external_account_ref": "acct-xyz",
    })
    assert replay.json()["inserted"] is False

    fill = client.post("/v1/derivatives/observations", json={
        "event_name": "derivatives_fill_observed",
        "payload": {
            "fill_id": "f-100", "trading_account_id": "acct-xyz",
            "canonical_market_id": "sim:btc-perp", "side": "buy",
            "price": "60000", "quantity": "0.5", "executed_at": "2026-07-08T12:00:00Z",
        },
    })
    assert fill.status_code == 201, fill.text

    listed = client.get("/v1/derivatives/fills")
    assert listed.json()["count"] == 1

    other = _build_app(OTHER_TENANT).get("/v1/derivatives/fills")
    assert other.json()["count"] == 0  # tenant isolation


def test_unknown_and_non_ingestable_events_rejected(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "derivatives", _FLAGS_ON)
    client = _build_app(TENANT)
    unknown = client.post("/v1/derivatives/observations", json={
        "event_name": "derivatives_teleport_observed", "payload": {"order_id": "x"},
    })
    assert unknown.status_code == 422
    registry_only = client.post("/v1/derivatives/observations", json={
        "event_name": "derivatives_venue_registered", "payload": {"order_id": "x"},
    })
    assert registry_only.status_code == 422


def test_execution_claims_rejected(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "derivatives", _FLAGS_ON)
    client = _build_app(TENANT)
    response = client.post("/v1/derivatives/observations", json={
        "event_name": "derivatives_fill_observed",
        "payload": {"fill_id": "f-2", "execution_by_aether": True},
    })
    assert response.status_code == 422
