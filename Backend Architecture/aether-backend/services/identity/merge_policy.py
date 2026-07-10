"""Merge policy engine for identity resolution decisions.

Every call to ``evaluate`` produces an explicit MergeDecision, a confidence
score, a tier, and a list of reason codes. No graph mutation happens here —
the policy only makes decisions. The resolver executes them.

Policy rules (in priority order):
1. Cross-tenant → BLOCKED
2. Consent blocks sensitive link → BLOCKED
3. Fingerprint-only → BLOCKED
4. DETERMINISTIC + no conflict → LINK / MERGE
5. STRONG + no conflict → LINK / MERGE (if policy allows auto-link)
6. PROBABLE → CANDIDATE
7. WEAK → REJECT (or CANDIDATE with strict=False)
8. Conflicting strong aliases → CONFLICT (creates conflict record)
9. Revoked alias → BLOCKED
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .confidence import score_signals
from .models import (
    ConfidenceTier,
    IdentitySignalType,
    MergeDecision,
    REASON_CROSS_TENANT_BLOCKED,
    REASON_FINGERPRINT_ONLY_BLOCKED,
    REASON_CONSENT_BLOCKS_LINK,
    REASON_CONFLICTING_ALIAS,
    REASON_INSUFFICIENT_EVIDENCE,
    REASON_MANUAL_OPERATOR_MERGE,
    REASON_NEW_ENTITY,
)


# External agent telemetry signals are observational context, never identity
# evidence: a deployment / platform / channel binding identifies where agent
# software runs, not a human. Signals with these names are excluded before
# any signal-strength evaluation, so they can never contribute to a merge.
NON_MERGE_ELIGIBLE_SIGNAL_NAMES: frozenset[str] = frozenset({
    "deployment_id",
    "agent_id",
    "external_platform",
    "external_channel_id",
    "external_workspace_id",
})

REASON_NON_MERGE_ELIGIBLE_SIGNAL = "non_merge_eligible_signal_excluded"


def _filter_merge_eligible(signal_types: list) -> list:
    """Drop signals whose name is on the non-merge-eligible denylist.

    Compares by string value so both IdentitySignalType members and raw
    string signal names are covered.
    """
    return [
        st for st in signal_types
        if str(getattr(st, "value", st)) not in NON_MERGE_ELIGIBLE_SIGNAL_NAMES
    ]


@dataclass
class MergePolicyContext:
    """All inputs the policy engine needs to make a decision."""
    tenant_id: str
    source_tenant_id: str                    # tenant from the incoming event
    matching_signal_types: list[IdentitySignalType]
    consent_snapshot: Optional[dict]
    revoked_signal_types: list[IdentitySignalType] = field(default_factory=list)
    has_conflict: bool = False               # conflicting strong aliases found?
    existing_entity_ids: list[str] = field(default_factory=list)
    actor_type: str = "system"              # "system" | "operator" | "admin"
    actor_id: str = ""
    # policy knobs
    auto_link_deterministic: bool = True
    auto_link_strong: bool = True
    require_consent_for_sensitive: bool = True


@dataclass
class MergePolicyResult:
    decision: MergeDecision
    confidence: float
    confidence_tier: ConfidenceTier
    reason_codes: list[str]
    merge_target_entity_id: Optional[str] = None  # ID to merge into, if known
    conflict_type: Optional[str] = None


def evaluate(ctx: MergePolicyContext) -> MergePolicyResult:
    """
    Apply merge policy and return an explicit decision.

    This function is pure (no I/O). The resolver calls it, then acts on
    the result.
    """

    # ── 1. Cross-tenant block ─────────────────────────────────────────────
    if ctx.source_tenant_id != ctx.tenant_id:
        return MergePolicyResult(
            decision=MergeDecision.BLOCKED,
            confidence=0.0,
            confidence_tier=ConfidenceTier.BLOCKED,
            reason_codes=[REASON_CROSS_TENANT_BLOCKED],
        )

    # ── 1b. Non-merge-eligible signal guard ──────────────────────────────
    # Deployment / agent / external-platform signals never count as identity
    # evidence — filter them out before any strength evaluation.
    matching_signal_types = _filter_merge_eligible(ctx.matching_signal_types)
    revoked_signal_types = _filter_merge_eligible(ctx.revoked_signal_types)
    excluded_signals = len(matching_signal_types) != len(ctx.matching_signal_types)

    # ── 2 & 3. Score signals (handles consent + fingerprint blocking) ─────
    score, tier, reason_codes = score_signals(
        matching_signal_types=matching_signal_types,
        consent_snapshot=ctx.consent_snapshot,
        source_tenant_id=ctx.source_tenant_id,
        target_tenant_id=ctx.tenant_id,
        revoked_types=revoked_signal_types,
    )
    if excluded_signals and REASON_NON_MERGE_ELIGIBLE_SIGNAL not in reason_codes:
        reason_codes = reason_codes + [REASON_NON_MERGE_ELIGIBLE_SIGNAL]

    if tier == ConfidenceTier.BLOCKED:
        return MergePolicyResult(
            decision=MergeDecision.BLOCKED,
            confidence=score,
            confidence_tier=tier,
            reason_codes=reason_codes,
        )

    # ── No existing entities → CREATE ─────────────────────────────────────
    if not ctx.existing_entity_ids:
        return MergePolicyResult(
            decision=MergeDecision.CREATE,
            confidence=score,
            confidence_tier=tier,
            reason_codes=reason_codes + [REASON_NEW_ENTITY],
        )

    # ── 8. Conflicting strong aliases → CANDIDATE + flag conflict ─────────
    if ctx.has_conflict:
        return MergePolicyResult(
            decision=MergeDecision.CANDIDATE,
            confidence=score,
            confidence_tier=tier,
            reason_codes=reason_codes + [REASON_CONFLICTING_ALIAS],
            conflict_type="conflicting_strong_alias",
        )

    # ── 4. DETERMINISTIC + auto-link allowed ─────────────────────────────
    if tier == ConfidenceTier.DETERMINISTIC and ctx.auto_link_deterministic:
        target = ctx.existing_entity_ids[0] if len(ctx.existing_entity_ids) == 1 else None
        decision = MergeDecision.MERGE if target else MergeDecision.CANDIDATE
        return MergePolicyResult(
            decision=decision,
            confidence=score,
            confidence_tier=tier,
            reason_codes=reason_codes,
            merge_target_entity_id=target,
        )

    if tier == ConfidenceTier.DETERMINISTIC:
        # Deterministic but auto-link is disabled → queue for review
        return MergePolicyResult(
            decision=MergeDecision.CANDIDATE,
            confidence=score,
            confidence_tier=tier,
            reason_codes=reason_codes,
        )

    # ── 5. STRONG + auto-link allowed ────────────────────────────────────
    if tier == ConfidenceTier.STRONG and ctx.auto_link_strong:
        target = ctx.existing_entity_ids[0] if len(ctx.existing_entity_ids) == 1 else None
        decision = MergeDecision.LINK if target else MergeDecision.CANDIDATE
        return MergePolicyResult(
            decision=decision,
            confidence=score,
            confidence_tier=tier,
            reason_codes=reason_codes,
            merge_target_entity_id=target,
        )

    if tier == ConfidenceTier.STRONG:
        return MergePolicyResult(
            decision=MergeDecision.CANDIDATE,
            confidence=score,
            confidence_tier=tier,
            reason_codes=reason_codes,
        )

    # ── 6. PROBABLE → CANDIDATE ──────────────────────────────────────────
    if tier == ConfidenceTier.PROBABLE:
        return MergePolicyResult(
            decision=MergeDecision.CANDIDATE,
            confidence=score,
            confidence_tier=tier,
            reason_codes=reason_codes,
        )

    # ── 7. WEAK → REJECT ─────────────────────────────────────────────────
    return MergePolicyResult(
        decision=MergeDecision.REJECT,
        confidence=score,
        confidence_tier=tier,
        reason_codes=reason_codes + [REASON_INSUFFICIENT_EVIDENCE],
    )


def evaluate_operator_merge(
    tenant_id: str,
    primary_entity_id: str,
    secondary_entity_id: str,
    actor_id: str,
    actor_type: str = "operator",
    reason: str = "",
) -> MergePolicyResult:
    """Policy for an explicit operator-initiated merge."""
    if not primary_entity_id or not secondary_entity_id:
        return MergePolicyResult(
            decision=MergeDecision.REJECT,
            confidence=0.0,
            confidence_tier=ConfidenceTier.BLOCKED,
            reason_codes=[REASON_INSUFFICIENT_EVIDENCE],
        )
    return MergePolicyResult(
        decision=MergeDecision.MERGE,
        confidence=1.0,
        confidence_tier=ConfidenceTier.DETERMINISTIC,
        reason_codes=[REASON_MANUAL_OPERATOR_MERGE],
        merge_target_entity_id=primary_entity_id,
    )
