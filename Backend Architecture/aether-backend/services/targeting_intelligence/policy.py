"""Conflict-precedence engine — strictest safe rule always wins.

Resolution order (earlier beats later, without exception):

1. hard_consent_block          — consent absent/revoked for the purpose
2. regulatory_policy_block     — regulatory or tenant policy block
3. fraud_risk_exclusion        — fraud-risk signal on the cluster
4. tenant_manual_exclusion     — explicit tenant exclusion/suppression rule
5. holdout_control             — holdout membership
6. inclusion                   — include rule
7. similarity_reference_inclusion — reference-cluster similarity inclusion

Every resolution emits an auditable PolicyDecision referenced from
eligibility snapshots via policyDecisionIds.
"""

from __future__ import annotations

from typing import Any, Optional

from services.targeting_intelligence.models import (
    ClusterTargetingRule,
    PolicyDecision,
    TargetingConflictResolution,
)


class ClusterSignals:
    """Safety signals for one cluster, gathered by the caller."""

    def __init__(
        self,
        *,
        consent_blocked: bool = False,
        regulatory_blocked: bool = False,
        fraud_risk: bool = False,
    ) -> None:
        self.consent_blocked = consent_blocked
        self.regulatory_blocked = regulatory_blocked
        self.fraud_risk = fraud_risk


def resolve_cluster(
    tenant_id: str,
    cluster_id: str,
    rules: list[ClusterTargetingRule],
    signals: Optional[ClusterSignals] = None,
) -> PolicyDecision:
    """Resolve all rules touching one cluster to a single safe outcome."""
    signals = signals or ClusterSignals()
    cluster_rules = [r for r in rules if r.clusterId == cluster_id]
    rule_types = {r.ruleType for r in cluster_rules}

    inputs: dict[str, Any] = {
        "ruleTypes": sorted(rule_types),
        "consentBlocked": signals.consent_blocked,
        "regulatoryBlocked": signals.regulatory_blocked,
        "fraudRisk": signals.fraud_risk,
    }

    resolution: TargetingConflictResolution
    rule_applied: str
    if signals.consent_blocked:
        resolution, rule_applied = "hard_consent_block", "consent_signal"
    elif signals.regulatory_blocked:
        resolution, rule_applied = "regulatory_policy_block", "regulatory_signal"
    elif signals.fraud_risk:
        resolution, rule_applied = "fraud_risk_exclusion", "fraud_signal"
    elif "exclude" in rule_types or "suppress" in rule_types:
        resolution, rule_applied = "tenant_manual_exclusion", "exclude_rule"
    elif "holdout" in rule_types:
        resolution, rule_applied = "holdout_control", "holdout_rule"
    elif "include" in rule_types:
        resolution, rule_applied = "inclusion", "include_rule"
    elif "reference" in rule_types:
        resolution, rule_applied = "similarity_reference_inclusion", "reference_rule"
    else:
        # No rule and no blocking signal: not eligible by default (safe).
        resolution, rule_applied = "tenant_manual_exclusion", "default_not_targeted"
        inputs["default"] = True

    return PolicyDecision(
        tenantId=tenant_id,
        clusterId=cluster_id,
        resolution=resolution,
        ruleApplied=rule_applied,
        inputsSummary=inputs,
    )


ELIGIBLE_RESOLUTIONS: frozenset[str] = frozenset(
    {"inclusion", "similarity_reference_inclusion"}
)


def is_eligible(decision: PolicyDecision) -> bool:
    return decision.resolution in ELIGIBLE_RESOLUTIONS


def is_holdout(decision: PolicyDecision) -> bool:
    return decision.resolution == "holdout_control"
