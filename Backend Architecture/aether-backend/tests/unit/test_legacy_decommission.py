"""Legacy per-provider decommission helper tests (WS7) — Team F.

``retire_connector_type`` marks a legacy connector per-provider as
decommissioned. It must be:

* idempotent — a repeat call is a stable ``already_retired`` no-op that
  preserves the original ``retired_at`` timestamp;
* auditable — the retirement is recorded in the in-memory ledger and readable
  via ``is_retired``;
* per-provider, never core-first — only ``shopify`` is eligible (the six new
  providers ship no legacy connector); any other type returns a typed
  ``not_eligible`` result and no other connector type is ever touched;
* typed, never raising — an unknown type returns a typed ``unknown`` result
  rather than a silent no-op or an exception.
"""
from __future__ import annotations

import pytest

from services.integrations.connectors import registry as registry_mod
from services.integrations.connectors.adapters import ALL_CONNECTORS
from services.integrations.connectors.base import BaseConnector
from services.integrations.connectors.registry import (
    CONNECTORS,
    DECOMMISSIONABLE_CONNECTOR_TYPES,
    RetireResult,
    is_retired,
    retire_connector_type,
)


def _state() -> dict[str, BaseConnector]:
    """A fresh registry state built from ALL_CONNECTORS (never the shared
    module global), so each test starts from a clean, un-retired registry."""
    return {c.connector_type: c() for c in ALL_CONNECTORS}


@pytest.fixture(autouse=True)
def _reset_ledger():
    """The in-memory retirement ledger is module-global; clear it between
    tests so idempotency assertions are deterministic."""
    registry_mod._RETIRED_AT.clear()
    yield


def _assert_retired_shape(result: RetireResult, connector_type: str) -> None:
    assert result.ok is True
    assert result.connector_type == connector_type
    assert result.status == "retired"
    assert result.retired_at is not None  # ISO timestamp recorded
    assert ":" in result.retired_at  # ISO-8601 shape


# ── Happy path ──────────────────────────────────────────────────────────────


def test_retire_shopify_marks_decommissioned():
    result = retire_connector_type(_state(), "shopify")
    _assert_retired_shape(result, "shopify")
    assert is_retired("shopify") is True


def test_retire_records_audit_timestamp():
    state = _state()
    result = retire_connector_type(state, "shopify")
    ledger = registry_mod._RETIRED_AT
    assert ledger["shopify"] == result.retired_at


def test_retire_does_not_mutate_registry_state():
    state = _state()
    retire_connector_type(state, "shopify")
    # The decommission marks the type; it never removes or replaces the entry
    # in the registry state (per-provider mark, not a destructive removal).
    assert "shopify" in state
    assert state["shopify"] is not None
    assert list(state) == [c.connector_type for c in ALL_CONNECTORS]


# ── Idempotency ─────────────────────────────────────────────────────────────


def test_retire_shopify_is_idempotent_and_preserves_timestamp():
    state = _state()
    first = retire_connector_type(state, "shopify")
    second = retire_connector_type(state, "shopify")
    assert second.ok is True
    assert second.status == "already_retired"
    assert second.retired_at == first.retired_at
    assert registry_mod._RETIRED_AT["shopify"] == first.retired_at


def test_retire_shopify_repeat_does_not_re_touch():
    state = _state()
    retire_connector_type(state, "shopify")
    before = dict(registry_mod._RETIRED_AT)
    retire_connector_type(state, "shopify")
    assert registry_mod._RETIRED_AT == before


# ── Unknown type → typed NOT_FOUND-style result (no silent no-op, no raise) ─


def test_retire_unknown_type_returns_not_found_style_result():
    result = retire_connector_type(_state(), "no_such_connector")
    assert result.ok is False
    assert result.status == "unknown"
    assert result.connector_type == "no_such_connector"
    assert result.retired_at is None
    assert "no_such_connector" in result.detail
    assert is_retired("no_such_connector") is False


def test_retire_unknown_type_never_raises():
    # Typed result instead of an exception for a missing type.
    result = retire_connector_type(_state(), "does_not_exist")
    assert isinstance(result, RetireResult)
    assert result.status == "unknown"


# ── Non-eligible type → typed not_eligible result (never core-first) ────────


def test_retire_shopify_is_the_only_eligible_type():
    assert DECOMMISSIONABLE_CONNECTOR_TYPES == frozenset({"shopify"})


@pytest.mark.parametrize("connector_type", ["slack", "stripe", "hubspot", "dune", "jira"])
def test_retire_non_eligible_type_returns_not_eligible(connector_type: str):
    result = retire_connector_type(_state(), connector_type)
    assert result.ok is False
    assert result.status == "not_eligible"
    assert result.connector_type == connector_type
    assert result.retired_at is None
    assert is_retired(connector_type) is False


def test_retire_core_connectors_never_touched():
    state = _state()
    for connector_type in ["slack", "stripe", "webhook"]:
        result = retire_connector_type(state, connector_type)
        assert result.status == "not_eligible"
    # The ledger is empty — no core connector was ever retired.
    assert registry_mod._RETIRED_AT == {}


def test_retire_shopify_does_not_touch_other_types():
    state = _state()
    retire_connector_type(state, "shopify")
    assert is_retired("shopify") is True
    # Every other registered connector is untouched (not retired, still present).
    assert set(registry_mod._RETIRED_AT) == {"shopify"}
    for connector_type in CONNECTORS:
        if connector_type == "shopify":
            continue
        assert is_retired(connector_type) is False
        assert connector_type in state


# ── HTTP route (Team C) ─────────────────────────────────────────────────────
# ``POST /v1/admin/kyber/provider-connections/decommission/{connector_type}``
# is an operator-gated Kyber surface wired to the same process-local retirement
# ledger. These tests drive the handler directly, monkeypatching the operator
# gate and the settings-backed flag gate, so the handler logic is exercised
# without HTTP/tenant plumbing (same pattern as ``test_legacy_ssrf.py``).

from services.provider_runtime import routes as runtime_routes  # noqa: E402
from shared.common.common import BadRequestError, NotFoundError  # noqa: E402


class _FakeRequest:
    """Minimal request stand-in — the operator gate is monkeypatched, so the
    handler never touches ``request.state``."""


def _operator_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime_routes, "_require_operator", lambda request: None)


def _flag_gate(monkeypatch: pytest.MonkeyPatch, available: bool) -> None:
    monkeypatch.setattr(
        runtime_routes, "_legacy_decommission_available", lambda: available
    )


@pytest.mark.asyncio
async def test_route_flag_off_is_a_real_gate_not_a_noop(monkeypatch) -> None:
    """DECISION 3 / H-2: with the follow-on flag off the route is inert — the
    handler fails closed even for a valid connector."""
    _operator_passes(monkeypatch)
    _flag_gate(monkeypatch, False)
    with pytest.raises(NotFoundError) as excinfo:
        await runtime_routes.decommission_legacy_connector("shopify", _FakeRequest())
    # NotFoundError appends " not found" (same as the WS6 migration gate).
    assert excinfo.value.message == "legacy decommission is not enabled not found"


@pytest.mark.asyncio
async def test_route_unknown_connector_type_is_a_404(monkeypatch) -> None:
    """An unknown type surfaces as a typed 404 (never a silent no-op, never a 500)."""
    _operator_passes(monkeypatch)
    _flag_gate(monkeypatch, True)
    with pytest.raises(NotFoundError) as excinfo:
        await runtime_routes.decommission_legacy_connector(
            "no_such_connector", _FakeRequest()
        )
    assert "no_such_connector" in excinfo.value.message


@pytest.mark.asyncio
async def test_route_not_eligible_connector_is_a_400(monkeypatch) -> None:
    """A native-only provider (registered but outside the decommissionable set)
    is a 400 — decommission is per-provider, never core-first."""
    _operator_passes(monkeypatch)
    _flag_gate(monkeypatch, True)
    with pytest.raises(BadRequestError) as excinfo:
        await runtime_routes.decommission_legacy_connector("slack", _FakeRequest())
    assert "no legacy connector to decommission" in excinfo.value.message


@pytest.mark.asyncio
async def test_route_shopify_retire_returns_api_response(monkeypatch) -> None:
    """The one decommissionable connector retires to an APIResponse-shaped dict."""
    _operator_passes(monkeypatch)
    _flag_gate(monkeypatch, True)
    body = await runtime_routes.decommission_legacy_connector("shopify", _FakeRequest())
    assert body["status"] == "success"
    data = body["data"]
    assert data["ok"] is True
    assert data["status"] == "retired"
    assert data["connector_type"] == "shopify"
    assert data["retired_at"]


@pytest.mark.asyncio
async def test_route_shopify_repeat_retire_is_idempotent(monkeypatch) -> None:
    """A repeat retire is a stable ``already_retired`` no-op preserving the
    original timestamp."""
    _operator_passes(monkeypatch)
    _flag_gate(monkeypatch, True)
    first = await runtime_routes.decommission_legacy_connector("shopify", _FakeRequest())
    second = await runtime_routes.decommission_legacy_connector(
        "shopify", _FakeRequest()
    )
    assert first["data"]["status"] == "retired"
    assert second["data"]["status"] == "already_retired"
    assert second["data"]["retired_at"] == first["data"]["retired_at"]
    assert is_retired("shopify") is True
