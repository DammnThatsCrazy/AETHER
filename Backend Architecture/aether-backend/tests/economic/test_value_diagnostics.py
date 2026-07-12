"""Tests for the Kyber financial-diagnostics helpers (§4.19).

Exercises services.economic.value_diagnostics against real value dicts produced
by services.value (value_of / safe_rollup). Core invariants under test:
  - the diagnostic surfaces WHY values are unpriced / excluded;
  - an absent USD total / value stays None and is NEVER coerced to 0.
"""
from __future__ import annotations

from services.economic.value_diagnostics import diagnose_rollup, value_status
from services.value.rollups import safe_rollup
from services.value.valuation import value_of


# --------------------------------------------------------------- diagnose_rollup
def test_diagnose_rollup_surfaces_unpriced_and_excluded():
    # ETH priced+included, UNKNOWNTOK unpriced, testnet BTC priced-but-excluded.
    rollup = safe_rollup([
        {"amount": "1", "currency": "ETH"},                    # 3000, included
        {"amount": "5", "currency": "UNKNOWNTOK"},             # unpriced
        {"amount": "2", "currency": "BTC", "testnet": True},   # priced, excluded
    ])
    d = diagnose_rollup(rollup)

    assert d["valuation_status"] == "partial"
    assert d["total_usd"] == "3000"          # priced total preserved verbatim
    assert d["has_trusted_total"] is True
    assert d["is_complete"] is False

    assert d["unpriced_count"] == 1
    assert d["excluded_count"] == 1
    assert d["priced_currencies"] == ["ETH"]
    assert "UNKNOWNTOK" in d["unpriced_currencies"]
    assert "BTC" in d["unpriced_currencies"]

    # Why-excluded narrative surfaces both unpriced and ownership exclusion.
    assert any("unpriced" in w for w in d["why_excluded"])
    assert any("excluded by ownership" in w for w in d["why_excluded"])
    # Why-included narrative names the priced currency + trusted total.
    assert any("ETH" in w for w in d["why_included"])
    assert any("trusted USD total" in w for w in d["why_included"])

    assert 0.0 < d["completeness"]["ratio"] < 1.0
    assert d["completeness"]["total_records"] == 3
    assert d["completeness"]["priced_records"] == 1


def test_diagnose_rollup_all_unpriced_total_is_none_never_zero():
    rollup = safe_rollup([{"amount": "10", "currency": "UNKNOWNTOK"}])
    d = diagnose_rollup(rollup)

    assert d["total_usd"] is None            # unpriced -> None, never 0
    assert d["total_usd"] != 0
    assert d["has_trusted_total"] is False
    assert d["valuation_status"] == "unavailable"
    assert d["unpriced_count"] == 1
    assert any("unpriced" in w for w in d["why_excluded"])


def test_diagnose_empty_rollup_completeness_ratio_is_none_not_zero():
    d = diagnose_rollup({})
    assert d["total_usd"] is None
    assert d["completeness"]["total_records"] == 0
    # Nothing to divide => ratio None (an absence), never coerced to 0.
    assert d["completeness"]["ratio"] is None
    assert d["valuation_status"] == "unavailable"
    assert d["currency_count"] == 0


def test_diagnose_rollup_conflict_state_and_count():
    d = diagnose_rollup({
        "total_usd": None,
        "rollup_status": "conflicted",
        "by_native_currency": {},
        "unpriced_count": 0,
        "stale_count": 3,
        "excluded_count": 0,
    })
    assert d["valuation_status"] == "conflicted"
    assert d["conflict_count"] == 1
    assert d["reconciliation_state"] == "conflict"
    assert d["stale_count"] == 3
    assert any("conflict" in w for w in d["why_excluded"])
    assert any("stale" in w for w in d["why_excluded"])
    assert d["total_usd"] is None            # preserved, never 0


def test_diagnose_rollup_honors_explicit_reconciliation_state():
    d = diagnose_rollup({
        "total_usd": "42.00",
        "rollup_status": "complete",
        "by_native_currency": {"USD": {"amount": "42.00", "usd_value": "42.00", "count": 1, "priced": True}},
        "unpriced_count": 0,
        "stale_count": 0,
        "excluded_count": 0,
        "reconciliation_state": "matched",
    })
    assert d["reconciliation_state"] == "matched"
    assert d["is_complete"] is True
    assert d["completeness"]["ratio"] == 1.0
    assert d["why_excluded"] == []


# ------------------------------------------------------------------ value_status
def test_value_status_unpriced_surfaces_reason_and_none_usd():
    v = value_of({"amount": "5", "currency": "UNKNOWNTOK"})
    s = value_status(v)

    assert s["valuation_status"] == "unpriced"
    assert s["is_priced"] is False
    assert s["usd_value"] is None            # unpriced -> None, never 0
    assert s["usd_value"] != 0
    assert s["include_in_rollups"] is False
    assert s["exclusion_reason"] == "unpriced"
    assert "unpriced" in s["why_excluded"]
    assert s["native_currency"] == "UNKNOWNTOK"


def test_value_status_excluded_value_surfaces_exclusion_reason():
    v = value_of({"amount": "2", "currency": "ETH", "testnet": True})
    s = value_status(v)

    assert s["is_priced"] is True            # ETH is priced...
    assert s["usd_value"] == "6000"
    assert s["include_in_rollups"] is False  # ...but excluded from owned rollup
    assert s["exclusion_reason"] == "testnet_excluded"
    assert "testnet_excluded" in s["why_excluded"]


def test_value_status_priced_value_surfaces_price_source_and_inclusion():
    v = value_of({"amount": "1", "currency": "ETH"})
    s = value_status(v)

    assert s["valuation_status"] == "priced"
    assert s["is_priced"] is True
    assert s["usd_value"] == "3000"
    assert s["include_in_rollups"] is True
    assert s["valuation_method"] == "market_price"
    assert s["price_source"] == "market_reference"
    assert s["priced_at"] is not None
    assert s["is_stale"] is False
    assert any("priced via" in w for w in s["why_included"])
    assert "included in trusted USD rollup" in s["why_included"]


def test_value_status_full_envelope_ownership_and_reconciliation():
    av = {
        "native": {"amount": "100", "currency": "USDC"},
        "valuation": {
            "usd_value": "100.00",
            "freshness": "recent",
            "confidence": "high",
            "valuation_method": "stablecoin_peg_verified",
            "conversion_source": "peg_snapshot",
            "priced_at": "2026-07-12T00:00:00Z",
        },
        "ownership": {"relationship": "owned", "confidence": "high"},
        "status": {"include_in_rollups": True, "reconciliation_state": "matched"},
    }
    s = value_status(av)

    assert s["ownership_relationship"] == "owned"
    assert s["ownership_confidence"] == "high"
    assert s["reconciliation_state"] == "matched"
    assert s["price_source"] == "peg_snapshot"
    assert s["priced_at"] == "2026-07-12T00:00:00Z"
    assert s["confidence"] == "high"
    assert s["valuation_status"] == "priced"
    assert s["is_stale"] is False


def test_value_status_stale_freshness_flagged():
    av = {
        "native": {"amount": "1", "currency": "ETH"},
        "valuation": {"usd_value": "3000", "freshness": "stale", "confidence": "low"},
        "status": {"include_in_rollups": False, "exclusion_reason": "stale_price"},
    }
    s = value_status(av)
    assert s["valuation_status"] == "stale"
    assert s["is_stale"] is True
    assert "stale_price" in s["why_excluded"]


def test_value_status_never_coerces_absent_fields_to_zero():
    s = value_status({
        "valuation": {"usd_value": None},
        "native": {"amount": None, "currency": None},
    })
    assert s["usd_value"] is None
    assert s["usd_value"] != 0
    assert s["native_amount"] is None
    assert s["is_priced"] is False
    # Absent ownership / reconciliation stay None, not fabricated defaults.
    assert s["ownership_relationship"] is None
    assert s["reconciliation_state"] is None
