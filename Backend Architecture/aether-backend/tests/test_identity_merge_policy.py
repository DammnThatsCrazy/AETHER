"""Tests for the identity merge policy engine."""
from __future__ import annotations

import pytest

from services.identity.merge_policy import (
    MergePolicyContext,
    evaluate,
    evaluate_operator_merge,
)
from services.identity.models import (
    ConfidenceTier,
    IdentitySignalType,
    MergeDecision,
    REASON_CROSS_TENANT_BLOCKED,
    REASON_MANUAL_OPERATOR_MERGE,
    REASON_NEW_ENTITY,
    REASON_CONFLICTING_ALIAS,
)

TENANT = "tenant_a"


def _ctx(**kwargs) -> MergePolicyContext:
    defaults = dict(
        tenant_id=TENANT,
        source_tenant_id=TENANT,
        matching_signal_types=[],
        consent_snapshot=None,
        revoked_signal_types=[],
        has_conflict=False,
        existing_entity_ids=[],
        actor_type="system",
        actor_id="",
        auto_link_deterministic=True,
        auto_link_strong=True,
        require_consent_for_sensitive=True,
    )
    defaults.update(kwargs)
    return MergePolicyContext(**defaults)


# ── Cross-tenant blocking ──────────────────────────────────────────────────────

def test_cross_tenant_blocked():
    ctx = _ctx(source_tenant_id="tenant_b", matching_signal_types=[IdentitySignalType.USER_ID])
    result = evaluate(ctx)
    assert result.decision == MergeDecision.BLOCKED
    assert REASON_CROSS_TENANT_BLOCKED in result.reason_codes


# ── Create for new entities ────────────────────────────────────────────────────

def test_no_existing_entities_creates():
    ctx = _ctx(
        matching_signal_types=[IdentitySignalType.USER_ID],
        existing_entity_ids=[],
    )
    result = evaluate(ctx)
    assert result.decision == MergeDecision.CREATE
    assert REASON_NEW_ENTITY in result.reason_codes


# ── Deterministic merge ────────────────────────────────────────────────────────

def test_deterministic_single_entity_merges():
    ctx = _ctx(
        matching_signal_types=[IdentitySignalType.USER_ID],
        existing_entity_ids=["entity_1"],
    )
    result = evaluate(ctx)
    assert result.decision == MergeDecision.MERGE
    assert result.confidence_tier == ConfidenceTier.DETERMINISTIC
    assert result.merge_target_entity_id == "entity_1"


def test_deterministic_multiple_entities_candidate():
    ctx = _ctx(
        matching_signal_types=[IdentitySignalType.USER_ID],
        existing_entity_ids=["entity_1", "entity_2"],
    )
    result = evaluate(ctx)
    assert result.decision == MergeDecision.CANDIDATE


def test_deterministic_auto_link_disabled_becomes_candidate():
    ctx = _ctx(
        matching_signal_types=[IdentitySignalType.USER_ID],
        existing_entity_ids=["entity_1"],
        auto_link_deterministic=False,
    )
    result = evaluate(ctx)
    assert result.decision == MergeDecision.CANDIDATE


# ── Strong link ────────────────────────────────────────────────────────────────

def test_strong_single_entity_links():
    ctx = _ctx(
        matching_signal_types=[IdentitySignalType.EMAIL_HASH],
        consent_snapshot={"purposes": {"analytics": True}},
        existing_entity_ids=["entity_1"],
    )
    result = evaluate(ctx)
    assert result.decision == MergeDecision.LINK
    assert result.confidence_tier == ConfidenceTier.STRONG


def test_strong_auto_link_disabled_becomes_candidate():
    ctx = _ctx(
        matching_signal_types=[IdentitySignalType.EMAIL_HASH],
        consent_snapshot={"purposes": {"analytics": True}},
        existing_entity_ids=["entity_1"],
        auto_link_strong=False,
    )
    result = evaluate(ctx)
    assert result.decision == MergeDecision.CANDIDATE


# ── Probable candidate ─────────────────────────────────────────────────────────

def test_probable_becomes_candidate():
    ctx = _ctx(
        matching_signal_types=[IdentitySignalType.ANONYMOUS_ID],
        existing_entity_ids=["entity_1"],
    )
    result = evaluate(ctx)
    assert result.decision == MergeDecision.CANDIDATE
    assert result.confidence_tier == ConfidenceTier.PROBABLE


# ── Weak reject ───────────────────────────────────────────────────────────────

def test_weak_rejects():
    ctx = _ctx(
        matching_signal_types=[IdentitySignalType.SESSION_ID],
        existing_entity_ids=["entity_1"],
    )
    result = evaluate(ctx)
    assert result.decision == MergeDecision.REJECT


# ── Conflict → candidate ──────────────────────────────────────────────────────

def test_conflict_becomes_candidate():
    ctx = _ctx(
        matching_signal_types=[IdentitySignalType.USER_ID],
        existing_entity_ids=["entity_1", "entity_2"],
        has_conflict=True,
    )
    result = evaluate(ctx)
    assert result.decision == MergeDecision.CANDIDATE
    assert REASON_CONFLICTING_ALIAS in result.reason_codes
    assert result.conflict_type == "conflicting_strong_alias"


# ── Blocked by consent / fingerprint ──────────────────────────────────────────

def test_fingerprint_only_blocked_by_policy():
    ctx = _ctx(
        matching_signal_types=[IdentitySignalType.DEVICE_FINGERPRINT],
        existing_entity_ids=["entity_1"],
    )
    result = evaluate(ctx)
    assert result.decision == MergeDecision.BLOCKED


def test_email_without_consent_blocked():
    ctx = _ctx(
        matching_signal_types=[IdentitySignalType.EMAIL_HASH],
        consent_snapshot=None,
        existing_entity_ids=["entity_1"],
    )
    result = evaluate(ctx)
    assert result.decision == MergeDecision.BLOCKED


# ── Operator merge ─────────────────────────────────────────────────────────────

def test_operator_merge_always_merges():
    result = evaluate_operator_merge(
        tenant_id=TENANT,
        primary_entity_id="entity_1",
        secondary_entity_id="entity_2",
        actor_id="operator_x",
        actor_type="operator",
    )
    assert result.decision == MergeDecision.MERGE
    assert result.confidence == 1.0
    assert result.confidence_tier == ConfidenceTier.DETERMINISTIC
    assert REASON_MANUAL_OPERATOR_MERGE in result.reason_codes


def test_operator_merge_missing_entity_rejects():
    result = evaluate_operator_merge(
        tenant_id=TENANT,
        primary_entity_id="",
        secondary_entity_id="entity_2",
        actor_id="operator_x",
    )
    assert result.decision == MergeDecision.REJECT


# ── All decisions produce reason codes ────────────────────────────────────────

def test_all_decisions_have_reason_codes():
    cases = [
        _ctx(source_tenant_id="other"),
        _ctx(matching_signal_types=[IdentitySignalType.DEVICE_FINGERPRINT], existing_entity_ids=["e1"]),
        _ctx(matching_signal_types=[IdentitySignalType.USER_ID], existing_entity_ids=[]),
        _ctx(matching_signal_types=[IdentitySignalType.USER_ID], existing_entity_ids=["e1"]),
        _ctx(matching_signal_types=[IdentitySignalType.SESSION_ID], existing_entity_ids=["e1"]),
    ]
    for ctx in cases:
        result = evaluate(ctx)
        assert result.reason_codes, f"No reason codes for decision {result.decision}"
