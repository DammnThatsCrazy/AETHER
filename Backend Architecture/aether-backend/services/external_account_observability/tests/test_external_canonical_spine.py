"""
External account observability → canonical durable spine (PR 1).

Covers three guarantees under ``AETHER_ENV=local`` (in-memory stores):

(a) Money fields are decimal-safe: a decimal STRING round-trips as a string and
    a binary ``float`` is REJECTED at pydantic model construction.
(b) With the canonical-spine flag ON, ``observe_trade_order`` /
    ``observe_portfolio_snapshot`` write exactly ONE ``bronze_sdk_events`` row +
    ONE ``event_outbox`` row (single transaction) AND still insert the legacy
    ``obs_*`` record the Kyber read routes depend on.
(c) With the flag OFF (default), no bronze/outbox row is written and the
    response shape is unchanged.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
os.environ.setdefault("AETHER_ENV", "local")

import asyncio

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError

from repositories.repos import _IN_MEMORY_STORES, reset_in_memory_stores


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class _Tenant:
    tenant_id = "tenant-a"

    def require_permission(self, perm: str) -> None:
        return None


def _client() -> TestClient:
    from services.external_account_observability.routes import router

    app = FastAPI()

    @app.middleware("http")
    async def _tenant_mw(request: Request, call_next):
        request.state.tenant = _Tenant()
        return await call_next(request)

    app.include_router(router)
    return TestClient(app)


def _bronze() -> dict:
    return _IN_MEMORY_STORES.get("bronze_sdk_events", {})


def _outbox() -> dict:
    return _IN_MEMORY_STORES.get("event_outbox", {})


def setup_function() -> None:
    reset_in_memory_stores()


# ---------------------------------------------------------------------------
# (a) Decimal-safe money — model construction
# ---------------------------------------------------------------------------

def test_decimal_string_quantity_round_trips_as_string():
    from services.external_account_observability.brokerage_models import TradeOrderObservedRecord

    rec = TradeOrderObservedRecord(symbol="AAPL", quantity="1.5", tenant_id="tenant-a")
    assert rec.quantity == "1.5"
    assert isinstance(rec.quantity, str)
    # Int coerces to a canonical decimal string, never a binary float.
    rec_int = TradeOrderObservedRecord(symbol="AAPL", quantity=3, tenant_id="tenant-a")
    assert rec_int.quantity == "3"


def test_decimal_string_total_value_round_trips_as_string():
    from services.external_account_observability.brokerage_models import PortfolioSnapshotObservedRecord

    rec = PortfolioSnapshotObservedRecord(total_value="1000.50", tenant_id="tenant-a")
    assert rec.total_value == "1000.50"
    assert isinstance(rec.total_value, str)


def test_binary_float_quantity_rejected_at_construction():
    from services.external_account_observability.brokerage_models import TradeOrderObservedRecord

    with pytest.raises(ValidationError):
        TradeOrderObservedRecord(symbol="AAPL", quantity=1.1, tenant_id="tenant-a")


def test_binary_float_total_value_rejected_at_construction():
    from services.external_account_observability.brokerage_models import PortfolioSnapshotObservedRecord

    with pytest.raises(ValidationError):
        PortfolioSnapshotObservedRecord(total_value=1000.5, tenant_id="tenant-a")


def test_binary_float_budget_rejected_at_construction():
    from services.external_account_observability.budget_models import AgentBudgetObservedRecord

    with pytest.raises(ValidationError):
        AgentBudgetObservedRecord(total_budget=1.1, tenant_id="tenant-a")

    ok = AgentBudgetObservedRecord(total_budget="500.00", tenant_id="tenant-a")
    assert ok.total_budget == "500.00"


def test_request_model_rejects_binary_float_quantity():
    """A route request with a binary float quantity is rejected (HTTP 422)."""
    resp = _client().post(
        "/v1/observability/external-accounts/order-observations",
        json={"tenant_id": "tenant-a", "symbol": "AAPL", "quantity": 1.1},
    )
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# (b) Flag ON — exactly 1 bronze + 1 outbox row, legacy obs_* still written
# ---------------------------------------------------------------------------

def test_order_flag_on_writes_bronze_outbox_and_legacy(monkeypatch):
    monkeypatch.setattr(
        "services.external_account_observability.routes._use_canonical_spine",
        lambda tenant_id: True,
    )
    resp = _client().post(
        "/v1/observability/external-accounts/order-observations",
        json={
            "tenant_id": "tenant-a",
            "agent_id": "agent-1",
            "symbol": "AAPL",
            "side": "buy",
            "quantity": "2.5",
            "status": "filled",
            "external_order_id": "ext-order-1",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    obs_id = body["observation_id"]

    # Exactly one Bronze row + one outbox row (single transaction).
    assert len(_bronze()) == 1, _bronze()
    assert len(_outbox()) == 1, _outbox()
    assert body["graph_mutations_queued"] == 1

    # Legacy obs_trade_observations record still inserted (Kyber read compat),
    # with the quantity preserved as a decimal string.
    from services.external_account_observability.routes import TradeObservationRepository

    legacy = _run(TradeObservationRepository().find_by_id(obs_id))
    assert legacy is not None
    assert legacy["quantity"] == "2.5"


def test_portfolio_flag_on_writes_bronze_outbox_and_legacy(monkeypatch):
    monkeypatch.setattr(
        "services.external_account_observability.routes._use_canonical_spine",
        lambda tenant_id: True,
    )
    resp = _client().post(
        "/v1/observability/external-accounts/portfolio-snapshots",
        json={"tenant_id": "tenant-a", "total_value": "1000.00"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    obs_id = body["observation_id"]

    assert len(_bronze()) == 1, _bronze()
    assert len(_outbox()) == 1, _outbox()
    assert body["graph_mutations_queued"] == 1

    from services.external_account_observability.routes import PortfolioSnapshotRepository

    legacy = _run(PortfolioSnapshotRepository().find_by_id(obs_id))
    assert legacy is not None
    assert legacy["total_value"] == "1000.00"


# ---------------------------------------------------------------------------
# (c) Flag OFF — no bronze/outbox rows, response shape unchanged
# ---------------------------------------------------------------------------

def test_order_flag_off_no_spine_write(monkeypatch):
    monkeypatch.setattr(
        "services.external_account_observability.routes._use_canonical_spine",
        lambda tenant_id: False,
    )
    resp = _client().post(
        "/v1/observability/external-accounts/order-observations",
        json={
            "tenant_id": "tenant-a",
            "agent_id": "agent-1",
            "symbol": "AAPL",
            "quantity": "2.5",
            "external_order_id": "ext-order-1",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()

    # No canonical-spine write on the legacy path.
    assert len(_bronze()) == 0, _bronze()
    assert len(_outbox()) == 0, _outbox()

    # Response shape unchanged (ExtAccountResponse).
    assert set(body.keys()) == {
        "observation_id", "received_at", "graph_mutations_queued", "tenant_id",
    }
    assert body["tenant_id"] == "tenant-a"

    # Legacy obs_trade_observations record still written.
    from services.external_account_observability.routes import TradeObservationRepository

    legacy = _run(TradeObservationRepository().find_by_id(body["observation_id"]))
    assert legacy is not None


def test_portfolio_flag_off_no_spine_write(monkeypatch):
    monkeypatch.setattr(
        "services.external_account_observability.routes._use_canonical_spine",
        lambda tenant_id: False,
    )
    resp = _client().post(
        "/v1/observability/external-accounts/portfolio-snapshots",
        json={"tenant_id": "tenant-a", "total_value": "1000.00"},
    )
    assert resp.status_code == 201, resp.text
    assert len(_bronze()) == 0, _bronze()
    assert len(_outbox()) == 0, _outbox()
