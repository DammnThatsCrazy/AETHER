"""Security tests: identity resolution must enforce strict tenant isolation.

No cross-tenant identity signals may be merged, linked, or returned.
"""
from __future__ import annotations

import pytest

from services.identity.confidence import score_signals
from services.identity.merge_policy import MergePolicyContext, evaluate
from services.identity.models import (
    ConfidenceTier,
    IdentitySignalType,
    MergeDecision,
    REASON_CROSS_TENANT_BLOCKED,
)

TENANT_A = "tenant_alpha"
TENANT_B = "tenant_beta"
DETERMINISTIC_SIGNALS = [IdentitySignalType.USER_ID]


# ── Cross-tenant scoring always blocked ───────────────────────────────────────

def test_score_cross_tenant_always_blocked():
    score, tier, codes = score_signals(
        matching_signal_types=DETERMINISTIC_SIGNALS,
        consent_snapshot={"purposes": {"analytics": True}},
        source_tenant_id=TENANT_A,
        target_tenant_id=TENANT_B,
    )
    assert tier == ConfidenceTier.BLOCKED
    assert score == 0.0
    assert REASON_CROSS_TENANT_BLOCKED in codes


def test_score_cross_tenant_blocked_regardless_of_consent():
    for consent in [None, {}, {"purposes": {"analytics": True, "identity": True}}]:
        score, tier, codes = score_signals(
            matching_signal_types=DETERMINISTIC_SIGNALS,
            consent_snapshot=consent,
            source_tenant_id=TENANT_A,
            target_tenant_id=TENANT_B,
        )
        assert tier == ConfidenceTier.BLOCKED, f"Should be blocked for consent={consent}"


def test_score_cross_tenant_blocked_for_all_signal_types():
    for signal_type in IdentitySignalType:
        score, tier, codes = score_signals(
            matching_signal_types=[signal_type],
            consent_snapshot={"purposes": {"analytics": True}},
            source_tenant_id=TENANT_A,
            target_tenant_id=TENANT_B,
        )
        assert tier == ConfidenceTier.BLOCKED, f"{signal_type} should be blocked cross-tenant"
        assert REASON_CROSS_TENANT_BLOCKED in codes


# ── Cross-tenant policy evaluation always blocked ─────────────────────────────

def test_policy_cross_tenant_always_blocked():
    ctx = MergePolicyContext(
        tenant_id=TENANT_A,
        source_tenant_id=TENANT_B,
        matching_signal_types=DETERMINISTIC_SIGNALS,
        consent_snapshot={"purposes": {"analytics": True}},
    )
    result = evaluate(ctx)
    assert result.decision == MergeDecision.BLOCKED
    assert REASON_CROSS_TENANT_BLOCKED in result.reason_codes


def test_policy_cross_tenant_blocked_with_strong_signal():
    ctx = MergePolicyContext(
        tenant_id=TENANT_A,
        source_tenant_id=TENANT_B,
        matching_signal_types=[
            IdentitySignalType.USER_ID,
            IdentitySignalType.EMAIL_HASH,
            IdentitySignalType.EXTERNAL_ID,
        ],
        consent_snapshot={"purposes": {"analytics": True, "identity": True}},
    )
    result = evaluate(ctx)
    assert result.decision == MergeDecision.BLOCKED


# ── Same-tenant operations succeed ───────────────────────────────────────────

def test_same_tenant_deterministic_succeeds():
    ctx = MergePolicyContext(
        tenant_id=TENANT_A,
        source_tenant_id=TENANT_A,
        matching_signal_types=DETERMINISTIC_SIGNALS,
        consent_snapshot=None,
        existing_entity_ids=["entity_001"],
    )
    result = evaluate(ctx)
    assert result.decision != MergeDecision.BLOCKED


def test_same_tenant_score_not_blocked():
    score, tier, codes = score_signals(
        matching_signal_types=DETERMINISTIC_SIGNALS,
        consent_snapshot=None,
        source_tenant_id=TENANT_A,
        target_tenant_id=TENANT_A,
    )
    assert tier != ConfidenceTier.BLOCKED
    assert REASON_CROSS_TENANT_BLOCKED not in codes


# ── Fingerprint alone never creates a hard link ───────────────────────────────

def test_fingerprint_alone_blocked():
    score, tier, codes = score_signals(
        matching_signal_types=[IdentitySignalType.DEVICE_FINGERPRINT],
        consent_snapshot={"purposes": {"analytics": True}},
        source_tenant_id=TENANT_A,
        target_tenant_id=TENANT_A,
    )
    assert tier == ConfidenceTier.BLOCKED


def test_fingerprint_alone_policy_blocked():
    ctx = MergePolicyContext(
        tenant_id=TENANT_A,
        source_tenant_id=TENANT_A,
        matching_signal_types=[IdentitySignalType.DEVICE_FINGERPRINT],
        consent_snapshot={"purposes": {"analytics": True}},
        existing_entity_ids=["entity_001"],
    )
    result = evaluate(ctx)
    assert result.decision == MergeDecision.BLOCKED


# ── Consent-gated signals blocked without consent ─────────────────────────────

SENSITIVE_SIGNALS = [
    IdentitySignalType.EMAIL_HASH,
    IdentitySignalType.PHONE_HASH,
    IdentitySignalType.DEVICE_FINGERPRINT,
    IdentitySignalType.BROWSER_ID,
    IdentitySignalType.MOBILE_INSTALL_ID,
    IdentitySignalType.INSTALLATION_ID,
]


def test_sensitive_signals_blocked_without_consent():
    for sig in SENSITIVE_SIGNALS:
        score, tier, _ = score_signals(
            matching_signal_types=[sig],
            consent_snapshot=None,
            source_tenant_id=TENANT_A,
            target_tenant_id=TENANT_A,
        )
        assert tier == ConfidenceTier.BLOCKED, f"{sig} should require consent"
