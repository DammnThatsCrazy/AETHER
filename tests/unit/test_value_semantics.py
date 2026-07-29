"""PR4 — canonical value semantics: safe rollups, unknown != 0, and the
Profile360 financials() USD-first fix (no cross-currency scalar summation).

These run under the root pytest suite (part of `make ci-check`), importing the
backend value service + aggregator via an isolated sys.path insert.
"""
from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
_PREFIXES = ("config", "services", "shared", "middleware", "dependencies", "repositories")


@contextmanager
def backend_module_path():
    original = list(sys.path)
    for prefix in _PREFIXES:
        for name in list(sys.modules):
            if name == prefix or name.startswith(f"{prefix}."):
                sys.modules.pop(name, None)
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original
        for prefix in _PREFIXES:
            for name in list(sys.modules):
                if name == prefix or name.startswith(f"{prefix}."):
                    sys.modules.pop(name, None)


@pytest.fixture()
def value_mod(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    with backend_module_path():
        module = importlib.import_module("services.value")
        price_sources = importlib.import_module("services.value.price_sources")
        from decimal import Decimal

        rates = {
            "ETH": (Decimal("3000"), "test_market", "fresh", "high"),
            "USDC": (Decimal("1.000"), "test_peg", "fresh", "high"),
        }
        price_sources.clear_price_providers()
        price_sources.register_price_provider(rates.get)
        yield module
        price_sources.clear_price_providers()


# --------------------------------------------------------------------------- #
# value_of — normalization
# --------------------------------------------------------------------------- #
def test_usd_is_a_fiat_identity(value_mod):
    v = value_mod.value_of({"amount": "100", "asset_id": "USD"})
    assert v["valuation"]["usd_value"] == "100"
    assert v["valuation"]["valuation_method"] == "fiat_identity"
    assert v["status"]["include_in_rollups"] is True


def test_provider_reported_usd_is_used(value_mod):
    v = value_mod.value_of({"amount": "3.2", "asset_id": "ETH", "value_usd": "8000"})
    assert v["valuation"]["usd_value"] == "8000"
    assert v["valuation"]["valuation_method"] == "provider_reported"


def test_unpriced_asset_is_none_never_zero(value_mod):
    v = value_mod.value_of({"amount": "500", "asset_id": "SOMETOKEN"})
    assert v["valuation"]["usd_value"] is None          # NOT "0"
    assert v["status"]["include_in_rollups"] is False
    assert v["status"]["exclusion_reason"] == "unpriced"


def test_amounts_are_decimal_strings_not_floats(value_mod):
    v = value_mod.value_of({"amount": 100.5, "asset_id": "USD"})
    assert isinstance(v["native"]["amount"], str)
    assert isinstance(v["valuation"]["usd_value"], str)


# --------------------------------------------------------------------------- #
# safe_rollup — never a mixed-currency scalar; unknown != 0
# --------------------------------------------------------------------------- #
def test_single_currency_rollup_is_complete(value_mod):
    r = value_mod.safe_rollup([
        {"amount": "10", "asset_id": "USD"},
        {"amount": "5", "asset_id": "USD"},
    ])
    assert r["total_usd"] == "15"
    assert r["native_currency"] == "USD"
    assert r["native_total"] == "15"
    assert r["rollup_status"] == "complete"
    assert r["unpriced_count"] == 0


def test_mixed_currencies_are_not_scalar_summed(value_mod):
    # UNKNOWNTOK has no price source -> unpriced; USD is priced.
    r = value_mod.safe_rollup([
        {"amount": "100", "asset_id": "USD"},
        {"amount": "3", "asset_id": "UNKNOWNTOK"},   # unpriced
    ])
    # No single native scalar across two currencies.
    assert r["native_total"] is None
    assert r["native_currency"] is None
    # USD total reflects ONLY the priced (USD) subset — never the token added in.
    assert r["total_usd"] == "100"
    assert r["rollup_status"] == "partial"
    assert r["unpriced_count"] == 1
    assert set(r["by_native_currency"]) == {"USD", "UNKNOWNTOK"}
    assert r["by_native_currency"]["UNKNOWNTOK"]["usd_value"] is None


def test_priced_assets_convert_to_usd_first(value_mod):
    # ETH (market fixture) + USDC (peg-aware) + USD (identity) all price to USD.
    r = value_mod.safe_rollup([
        {"amount": "1", "asset_id": "ETH"},     # 1 * 3000
        {"amount": "50", "asset_id": "USDC"},   # 50 * 1.000 (peg-verified)
        {"amount": "100", "asset_id": "USD"},   # identity
    ])
    from decimal import Decimal
    assert Decimal(r["total_usd"]) == Decimal("3150")
    assert r["rollup_status"] == "complete"
    assert r["unpriced_count"] == 0
    # Still no single mixed-currency native scalar.
    assert r["native_total"] is None


def test_all_unpriced_yields_unavailable_not_zero(value_mod):
    r = value_mod.safe_rollup([{"amount": "3", "asset_id": "UNKNOWNTOK"}])
    assert r["total_usd"] is None      # NOT "0"
    assert r["rollup_status"] == "unavailable"


# --------------------------------------------------------------------------- #
# Profile360 financials() — the release blocker
# --------------------------------------------------------------------------- #
@pytest.fixture()
def agg(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    with backend_module_path():
        repos = importlib.import_module("repositories.repos")
        repos.reset_in_memory_stores()
        mod = importlib.import_module("services.profile.aggregator")
        yield mod.Profile360Aggregator()
        repos.reset_in_memory_stores()


def _run(coro):
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_financials_never_sums_mixed_currencies(agg):
    class _Repo:
        def __init__(self, rows): self._rows = rows
        async def find_many(self, **kw): return list(self._rows)
        async def list_for_entity(self, *a, **k): return list(self._rows)

    agg._transfers = _Repo([  # type: ignore[attr-defined]
        {"id": "t1", "transfer_id": "t1", "tenant_id": "t-a", "from_entity_id": "x",
         "to_entity_id": "user-1", "amount": "100", "asset_id": "USD"},
        {"id": "t2", "transfer_id": "t2", "tenant_id": "t-a", "from_entity_id": "x",
         "to_entity_id": "user-1", "amount": "3", "asset_id": "UNKNOWNTOK"},  # unpriced
    ])
    out = _run(agg.financials("user-1", "t-a"))
    s = out["summary"]
    # Legacy scalar is None because currencies are mixed (blocker fixed).
    assert s["inflow_total"] is None
    # USD-first value reflects only the priced USD leg — the unpriced token is
    # never coerced into the total.
    assert s["inflow_usd"] == "100"
    assert s["unpriced_count"] >= 1
    assert s["rollup_status"] == "partial"
    assert set(s["by_native_currency"]) == {"USD", "UNKNOWNTOK"}
