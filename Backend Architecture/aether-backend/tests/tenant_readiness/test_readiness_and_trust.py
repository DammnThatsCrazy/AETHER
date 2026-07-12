"""Tests for Tenant Launch Readiness (§3.13), Trust States (§3.14),
Quota states (§3.17), and generic-webhook default (§3.18).
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("AETHER_ENV", "local")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest

from repositories.repos import reset_in_memory_stores
from services.tenant_readiness.quota import (
    GENERIC_WEBHOOK_ENABLED_BY_DEFAULT,
    QUOTA_EXCEEDED,
    QUOTA_NEAR_LIMIT,
    QUOTA_OK,
    generic_webhook_disabled,
    generic_webhook_enabled,
    quota_state,
)
from services.tenant_readiness.service import (
    LAUNCH_READINESS_CHECKS,
    STATUS_FAILED,
    STATUS_NOT_APPLICABLE,
    STATUS_PASSED,
    STATUS_PENDING,
    TenantLaunchReadiness,
)
from services.tenant_readiness.trust_states import (
    TRUST_STATES,
    TrustState,
    derive_trust_states,
    is_trust_state,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _clean():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


def _all_passed_signals() -> dict:
    return {name: True for name in LAUNCH_READINESS_CHECKS}


# ── Launch readiness checklist ────────────────────────────────────────────────

async def test_all_checks_passed_is_ready():
    svc = TenantLaunchReadiness()
    result = svc.evaluate("tenant-a", _all_passed_signals())

    assert result["ready"] is True
    assert result["blocking"] == []
    assert len(result["checks"]) == len(LAUNCH_READINESS_CHECKS)
    assert {c["name"] for c in result["checks"]} == set(LAUNCH_READINESS_CHECKS)
    assert all(c["status"] == STATUS_PASSED for c in result["checks"])
    # Canonical order preserved.
    assert [c["name"] for c in result["checks"]] == list(LAUNCH_READINESS_CHECKS)


async def test_missing_signal_is_pending_and_blocks():
    svc = TenantLaunchReadiness()
    result = svc.evaluate("tenant-a", {})  # no signals at all

    assert result["ready"] is False
    assert set(result["blocking"]) == set(LAUNCH_READINESS_CHECKS)
    assert all(c["status"] == STATUS_PENDING for c in result["checks"])


async def test_failed_check_blocks_readiness():
    signals = _all_passed_signals()
    signals["dsr_delete_verified"] = False
    result = TenantLaunchReadiness().evaluate("tenant-a", signals)

    assert result["ready"] is False
    assert result["blocking"] == ["dsr_delete_verified"]
    failed = next(c for c in result["checks"] if c["name"] == "dsr_delete_verified")
    assert failed["status"] == STATUS_FAILED


async def test_not_applicable_does_not_block():
    signals = _all_passed_signals()
    signals["connector_signature_verified"] = STATUS_NOT_APPLICABLE
    result = TenantLaunchReadiness().evaluate("tenant-a", signals)

    assert result["ready"] is True
    assert result["blocking"] == []
    na = next(c for c in result["checks"] if c["name"] == "connector_signature_verified")
    assert na["status"] == STATUS_NOT_APPLICABLE


async def test_evidence_is_passed_through():
    signals = _all_passed_signals()
    signals["events_received"] = {"status": STATUS_PASSED, "evidence": {"count": 42}}
    result = TenantLaunchReadiness().evaluate("tenant-a", signals)

    events = next(c for c in result["checks"] if c["name"] == "events_received")
    assert events["status"] == STATUS_PASSED
    assert events["evidence"] == {"count": 42}
    # Checks without evidence do not carry an evidence key.
    plain = next(c for c in result["checks"] if c["name"] == "tenant_created")
    assert "evidence" not in plain


async def test_invalid_status_raises():
    signals = _all_passed_signals()
    signals["tenant_created"] = "bogus"
    with pytest.raises(ValueError):
        TenantLaunchReadiness().evaluate("tenant-a", signals)


async def test_generic_webhook_disabled_gate():
    # The §3.13 generic_webhook_disabled gate passes when the webhook is off.
    from services.tenant_readiness.quota import generic_webhook_disabled as gwd

    signals = _all_passed_signals()
    signals["generic_webhook_disabled"] = gwd({})  # default off -> True -> passed
    result = TenantLaunchReadiness().evaluate("tenant-a", signals)
    assert result["ready"] is True

    # If a tenant force-enabled the generic webhook, the gate fails.
    signals["generic_webhook_disabled"] = gwd({"generic_webhook_approved": True})
    result = TenantLaunchReadiness().evaluate("tenant-a", signals)
    assert result["ready"] is False
    assert "generic_webhook_disabled" in result["blocking"]


# ── record / get persistence + tenant isolation ──────────────────────────────

async def test_record_and_get_roundtrip():
    svc = TenantLaunchReadiness()
    stored = await svc.record("tenant-a", _all_passed_signals())
    assert stored["ready"] is True
    assert stored["tenant_id"] == "tenant-a"

    fetched = await svc.get("tenant-a")
    assert fetched is not None
    assert fetched["ready"] is True
    assert len(fetched["checks"]) == len(LAUNCH_READINESS_CHECKS)


async def test_get_is_tenant_isolated():
    svc = TenantLaunchReadiness()
    await svc.record("tenant-a", _all_passed_signals())
    # Another tenant has recorded nothing.
    assert await svc.get("tenant-b") is None


# ── Quota states (§3.17) ─────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "usage,limit,expected",
    [
        (0, 100, QUOTA_OK),
        (50, 100, QUOTA_OK),
        (89, 100, QUOTA_OK),
        (90, 100, QUOTA_NEAR_LIMIT),   # exactly 90% -> near
        (95, 100, QUOTA_NEAR_LIMIT),
        (99, 100, QUOTA_NEAR_LIMIT),
        (100, 100, QUOTA_EXCEEDED),    # at limit -> exceeded
        (150, 100, QUOTA_EXCEEDED),
        (5, 0, QUOTA_OK),              # no limit configured -> ok
    ],
)
async def test_quota_thresholds(usage, limit, expected):
    assert quota_state(usage, limit) == expected


# ── Generic webhook default (§3.18) ──────────────────────────────────────────

async def test_generic_webhook_default_off():
    assert GENERIC_WEBHOOK_ENABLED_BY_DEFAULT is False
    assert generic_webhook_enabled({}) is False
    assert generic_webhook_enabled(None) is False
    # Non-strict-True values must NOT enable it.
    assert generic_webhook_enabled({"generic_webhook_approved": "true"}) is False
    assert generic_webhook_enabled({"generic_webhook_approved": 1}) is False
    # Only an explicit True enables it.
    assert generic_webhook_enabled({"generic_webhook_approved": True}) is True
    assert generic_webhook_disabled({}) is True
    assert generic_webhook_disabled({"generic_webhook_approved": True}) is False


# ── Trust states (§3.14) ─────────────────────────────────────────────────────

async def test_derive_trust_states_from_semantic_signals():
    signals = {
        "event_count": 0,                    # no_data
        "consent_present": False,            # consent_missing
        "identity_status": "pending",        # identity_pending
        "connector_signature_valid": False,  # connector_signature_failed
        "generic_webhook_enabled": False,    # webhook_disabled
        "usage": 100,
        "limit": 100,                        # quota_exceeded
        "financial_value_status": "partial",  # financial_values_partial
    }
    states = derive_trust_states(signals)

    for expected in (
        TrustState.NO_DATA,
        TrustState.CONSENT_MISSING,
        TrustState.IDENTITY_PENDING,
        TrustState.CONNECTOR_SIGNATURE_FAILED,
        TrustState.WEBHOOK_DISABLED,
        TrustState.QUOTA_EXCEEDED,
        TrustState.FINANCIAL_VALUES_PARTIAL,
    ):
        assert expected in states

    # Only valid trust states, returned in canonical order, de-duplicated.
    assert all(is_trust_state(s) for s in states)
    assert states == [s for s in TRUST_STATES if s in set(states)]
    assert len(states) == len(set(states))


async def test_derive_trust_states_from_explicit_flags():
    states = derive_trust_states(
        {"replay_in_progress": True, "dsr_in_progress": True, "attribution_conflict": True}
    )
    assert TrustState.REPLAY_IN_PROGRESS in states
    assert TrustState.DSR_IN_PROGRESS in states
    assert TrustState.ATTRIBUTION_CONFLICT in states


async def test_derive_trust_states_quota_near_limit():
    states = derive_trust_states({"usage": 92, "limit": 100})
    assert TrustState.QUOTA_NEAR_LIMIT in states
    assert TrustState.QUOTA_EXCEEDED not in states


async def test_derive_trust_states_empty_is_empty():
    # No signals -> no fabricated trust states.
    assert derive_trust_states({}) == []
