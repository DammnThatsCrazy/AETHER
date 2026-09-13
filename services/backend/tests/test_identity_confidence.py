"""Tests for identity confidence scoring — tiers, reason codes, consent, blocking."""
from __future__ import annotations

import pytest

from services.identity.confidence import (
    CONSENT_REQUIRED_SIGNALS,
    score_signals,
    signal_weight,
)
from services.identity.models import (
    ConfidenceTier,
    IdentitySignalType,
    REASON_CONSENT_ALLOWS_LINK,
    REASON_CONSENT_BLOCKS_LINK,
    REASON_CROSS_TENANT_BLOCKED,
    REASON_FINGERPRINT_ONLY_BLOCKED,
    REASON_REVOKED_ALIAS,
    REASON_SAME_USER_ID,
    REASON_SAME_EMAIL_HASH,
    REASON_INSUFFICIENT_EVIDENCE,
)

TENANT = "tenant_a"


def _score(types, consent=None, revoked=None, target=None):
    return score_signals(
        matching_signal_types=list(types),
        consent_snapshot=consent,
        source_tenant_id=TENANT,
        target_tenant_id=target or TENANT,
        revoked_types=list(revoked or []),
    )


# ── Cross-tenant blocking ──────────────────────────────────────────────────────

def test_cross_tenant_blocks():
    score, tier, codes = score_signals(
        [IdentitySignalType.USER_ID],
        consent_snapshot={"purposes": {"analytics": True}},
        source_tenant_id="tenant_a",
        target_tenant_id="tenant_b",
    )
    assert tier == ConfidenceTier.BLOCKED
    assert score == 0.0
    assert REASON_CROSS_TENANT_BLOCKED in codes


# ── Fingerprint-only blocking ──────────────────────────────────────────────────

def test_fingerprint_only_blocked():
    score, tier, codes = _score([IdentitySignalType.DEVICE_FINGERPRINT])
    assert tier == ConfidenceTier.BLOCKED
    assert REASON_FINGERPRINT_ONLY_BLOCKED in codes


def test_fingerprint_plus_user_id_not_blocked():
    score, tier, codes = _score(
        [IdentitySignalType.DEVICE_FINGERPRINT, IdentitySignalType.USER_ID]
    )
    assert tier == ConfidenceTier.DETERMINISTIC
    assert REASON_FINGERPRINT_ONLY_BLOCKED not in codes


# ── Consent gating ─────────────────────────────────────────────────────────────

def test_email_without_consent_blocked():
    score, tier, codes = _score([IdentitySignalType.EMAIL_HASH], consent=None)
    assert tier == ConfidenceTier.BLOCKED
    assert REASON_CONSENT_BLOCKS_LINK in codes


def test_email_with_consent_scored():
    score, tier, codes = _score(
        [IdentitySignalType.EMAIL_HASH],
        consent={"purposes": {"analytics": True}},
    )
    assert tier in (ConfidenceTier.STRONG, ConfidenceTier.DETERMINISTIC)
    assert REASON_CONSENT_ALLOWS_LINK in codes


def test_phone_without_consent_blocked():
    score, tier, codes = _score([IdentitySignalType.PHONE_HASH], consent=None)
    assert tier == ConfidenceTier.BLOCKED


def test_consent_denied_flag_blocks():
    score, tier, codes = _score(
        [IdentitySignalType.EMAIL_HASH],
        consent={"denied": True},
    )
    assert tier == ConfidenceTier.BLOCKED


def test_mixed_sensitive_nonsensitive_without_consent():
    # user_id alone should still score (not consent-gated)
    score, tier, codes = _score(
        [IdentitySignalType.USER_ID, IdentitySignalType.EMAIL_HASH],
        consent=None,
    )
    # email_hash is removed, user_id remains → DETERMINISTIC
    assert tier == ConfidenceTier.DETERMINISTIC


# ── Revoked alias ──────────────────────────────────────────────────────────────

def test_revoked_only_signal_blocked():
    score, tier, codes = _score(
        [IdentitySignalType.USER_ID],
        revoked=[IdentitySignalType.USER_ID],
    )
    assert tier == ConfidenceTier.BLOCKED
    assert REASON_REVOKED_ALIAS in codes


def test_revoked_plus_other_signal_not_blocked():
    score, tier, codes = _score(
        [IdentitySignalType.USER_ID, IdentitySignalType.EXTERNAL_ID],
        revoked=[IdentitySignalType.USER_ID],
    )
    # user_id revoked but external_id remains → still scored
    assert tier != ConfidenceTier.BLOCKED


# ── Tier assignment ────────────────────────────────────────────────────────────

def test_user_id_deterministic():
    score, tier, codes = _score([IdentitySignalType.USER_ID])
    assert tier == ConfidenceTier.DETERMINISTIC
    assert score == 1.0


def test_external_id_deterministic():
    score, tier, codes = _score([IdentitySignalType.EXTERNAL_ID])
    assert tier == ConfidenceTier.DETERMINISTIC


def test_wallet_sig_verified_deterministic():
    score, tier, codes = _score([IdentitySignalType.WALLET_SIGNATURE_VERIFIED])
    assert tier == ConfidenceTier.DETERMINISTIC


def test_anonymous_id_probable():
    score, tier, codes = _score([IdentitySignalType.ANONYMOUS_ID])
    assert tier == ConfidenceTier.PROBABLE


def test_session_id_weak():
    score, tier, codes = _score([IdentitySignalType.SESSION_ID])
    assert tier == ConfidenceTier.WEAK


def test_empty_signals_blocked():
    score, tier, codes = _score([])
    assert tier == ConfidenceTier.BLOCKED
    assert REASON_INSUFFICIENT_EVIDENCE in codes


# ── Score computation ──────────────────────────────────────────────────────────

def test_multiple_signals_boost_score():
    score1, _, _ = _score([IdentitySignalType.ANONYMOUS_ID])
    score2, _, _ = _score([IdentitySignalType.ANONYMOUS_ID, IdentitySignalType.SESSION_ID])
    assert score2 > score1


def test_score_capped_at_1():
    types = list(IdentitySignalType)
    score, _, _ = _score(types, consent={"purposes": {"analytics": True}})
    assert score <= 1.0


# ── Signal weights ─────────────────────────────────────────────────────────────

def test_user_id_weight_is_1():
    assert signal_weight(IdentitySignalType.USER_ID) == 1.0


def test_fingerprint_weight_is_lowest():
    fp_w = signal_weight(IdentitySignalType.DEVICE_FINGERPRINT)
    uid_w = signal_weight(IdentitySignalType.USER_ID)
    assert fp_w < uid_w


def test_consent_required_signals_set():
    assert IdentitySignalType.EMAIL_HASH in CONSENT_REQUIRED_SIGNALS
    assert IdentitySignalType.PHONE_HASH in CONSENT_REQUIRED_SIGNALS
    assert IdentitySignalType.DEVICE_FINGERPRINT in CONSENT_REQUIRED_SIGNALS
    assert IdentitySignalType.USER_ID not in CONSENT_REQUIRED_SIGNALS


# ── Reason codes present ───────────────────────────────────────────────────────

def test_reason_codes_present_for_user_id():
    _, _, codes = _score([IdentitySignalType.USER_ID])
    assert REASON_SAME_USER_ID in codes


def test_reason_codes_present_for_email_with_consent():
    _, _, codes = _score(
        [IdentitySignalType.EMAIL_HASH],
        consent={"purposes": {"analytics": True}},
    )
    assert REASON_SAME_EMAIL_HASH in codes
