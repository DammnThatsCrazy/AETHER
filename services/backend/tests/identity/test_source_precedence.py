"""Tests for the Source Precedence Engine (prompt §3.4)."""
from __future__ import annotations

import os
import sys

# Make backend packages importable when this suite is run in isolation.
_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from services.identity.source_precedence import (  # noqa: E402
    PRECEDENCE_MATRIX,
    Source,
    precedence_for,
    resolve_conflict,
)

_REQUIRED_KEYS = {
    "authoritative_source",
    "fallback_sources",
    "timestamp_priority",
    "identity_priority",
    "conflict_rule",
    "manual_review_threshold",
    "tenant_override_allowed",
    "audit_required",
}


# ── Matrix shape ────────────────────────────────────────────────────────────────

def test_every_field_declares_required_keys():
    assert PRECEDENCE_MATRIX  # non-empty
    for field, entry in PRECEDENCE_MATRIX.items():
        missing = _REQUIRED_KEYS - set(entry)
        assert not missing, f"{field} missing keys: {missing}"
        # Authoritative source is a recognised Source.
        assert entry["authoritative_source"] in {s.value for s in Source}


def test_precedence_for_returns_copy():
    a = precedence_for("revenue")
    a["fallback_sources"].append("tampered")
    b = precedence_for("revenue")
    assert "tampered" not in b["fallback_sources"]


def test_precedence_for_unknown_field_is_fail_closed():
    p = precedence_for("does_not_exist")
    assert p["conflict_rule"] == "manual_review"
    assert p["manual_review_threshold"] == 1.0
    assert p["tenant_override_allowed"] is False
    assert p["audit_required"] is True
    assert p.get("unknown_field") is True


def test_financial_fields_never_authoritative_to_sdk():
    # Money-bearing facts must not treat the client SDK as source of truth.
    for field in ("revenue", "financial_value", "payment_customer_linkage"):
        assert precedence_for(field)["authoritative_source"] != Source.SDK.value


# ── resolve_conflict: authoritative selection ───────────────────────────────────

def test_picks_authoritative_over_fallback():
    result = resolve_conflict(
        "revenue",
        [
            {"source": "provider_webhook", "value": "90.00", "confidence": 0.99},
            {"source": "authenticated_webhook", "value": "100.00", "confidence": 0.95},
        ],
    )
    assert result["resolved"] is True
    assert result["value"] == "100.00"
    assert result["source"] == Source.AUTHENTICATED_WEBHOOK.value
    assert result["used_fallback"] is False


def test_falls_back_when_authoritative_absent():
    result = resolve_conflict(
        "revenue",
        [{"source": "provider_webhook", "value": "90.00", "confidence": 0.95}],
    )
    assert result["resolved"] is True
    assert result["value"] == "90.00"
    assert result["used_fallback"] is True


def test_source_may_be_enum_member():
    result = resolve_conflict(
        "identity",
        [{"source": Source.OPERATOR_ACTION, "value": "entity_1", "confidence": 1.0}],
    )
    assert result["resolved"] is True
    assert result["value"] == "entity_1"


# ── resolve_conflict: fail-closed conflicts ─────────────────────────────────────

def test_two_authoritative_sources_disagree_is_conflict():
    result = resolve_conflict(
        "financial_value",
        [
            {"source": "authenticated_webhook", "value": "100.00", "confidence": 0.99},
            {"source": "authenticated_webhook", "value": "250.00", "confidence": 0.99},
        ],
    )
    assert result["resolved"] is False
    assert result["conflict"] is True
    assert result["requires_manual_review"] is True
    assert result["reason"] == "authoritative_sources_disagree"
    assert result["audit_required"] is True


def test_authoritative_agreement_resolves():
    result = resolve_conflict(
        "financial_value",
        [
            {"source": "authenticated_webhook", "value": "100.00", "confidence": 0.99},
            {"source": "authenticated_webhook", "value": "100.00", "confidence": 0.99},
        ],
    )
    assert result["resolved"] is True
    assert result["value"] == "100.00"
    assert result["tie_break"] == "authoritative_agreement"


def test_insufficient_confidence_is_conflict():
    # revenue requires >= 0.90 confidence to accept without review.
    result = resolve_conflict(
        "revenue",
        [{"source": "authenticated_webhook", "value": "100.00", "confidence": 0.50}],
    )
    assert result["resolved"] is False
    assert result["reason"] == "insufficient_confidence"
    assert result["requires_manual_review"] is True


def test_no_candidates_is_conflict():
    result = resolve_conflict("revenue", [])
    assert result["resolved"] is False
    assert result["reason"] == "no_candidates"


def test_unknown_source_for_unknown_field_is_conflict():
    result = resolve_conflict(
        "totally_unknown_field",
        [{"source": "sdk", "value": "x", "confidence": 1.0}],
    )
    assert result["resolved"] is False
    assert result["reason"] == "unknown_source"


# ── resolve_conflict: timestamp tie-break (attribution-style fields) ────────────

def test_latest_timestamp_breaks_tie_for_campaign():
    result = resolve_conflict(
        "campaign_linkage",
        [
            {"source": "sdk", "value": "google", "confidence": 1.0,
             "timestamp": "2026-01-01T00:00:00Z"},
            {"source": "sdk", "value": "meta", "confidence": 1.0,
             "timestamp": "2026-02-01T00:00:00Z"},
        ],
    )
    assert result["resolved"] is True
    assert result["value"] == "meta"
    assert result["tie_break"] == "latest_timestamp"


def test_timestamp_tie_break_not_applied_to_authoritative_wins_fields():
    # revenue uses authoritative_wins — timestamps must NOT silently decide it.
    result = resolve_conflict(
        "revenue",
        [
            {"source": "authenticated_webhook", "value": "100.00", "confidence": 0.99,
             "timestamp": "2026-01-01T00:00:00Z"},
            {"source": "authenticated_webhook", "value": "250.00", "confidence": 0.99,
             "timestamp": "2026-02-01T00:00:00Z"},
        ],
    )
    assert result["resolved"] is False
    assert result["reason"] == "authoritative_sources_disagree"
