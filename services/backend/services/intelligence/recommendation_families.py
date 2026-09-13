"""Recommendation family strategies for graph-native OODA generation."""
from __future__ import annotations

import uuid
from abc import ABC
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from services.intelligence.decision_models import (
    CandidateAction,
    Recommendation,
    RecommendationEvidence,
)
from services.intelligence.scoring import RecommendationScoreInput, RecommendationScorer


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class GovernancePolicyGate:
    """Tenant policy gate preserving human approval for critical/high-impact actions."""

    def evaluate(self, action: CandidateAction, confidence_overall: float) -> tuple[str, list[str], float]:
        flags: list[str] = []
        penalty = 0.0
        approval = action.requires_approval_level
        if action.expected_value and action.expected_value >= 500:
            approval = "elevated"
            flags.append("economic_value_review")
            penalty += 0.04
        if "irreversible" in action.policy_flags or "critical" in action.policy_flags:
            approval = "critical"
            flags.append("human_approval_required")
            penalty += 0.10
        if confidence_overall < 0.45:
            flags.append("low_confidence_explanation_required")
            penalty += 0.05
        return approval, flags, min(penalty, 1.0)


@dataclass(frozen=True)
class FamilyDetection:
    matched: bool
    suppression_reasons: tuple[str, ...] = ()


class BaseRecommendationFamily(ABC):
    """Strategy contract for graph-native recommendation families."""

    family_key: str = "base"
    default_action_key: str = "open_investigation"
    default_label: str = "Open investigation workflow"
    default_expected_outcome: str = "Improve measurable outcome."
    default_downside_risk: str = "Analyst time may be spent on a low-impact loop."
    required_approval_level: str = "standard"
    policy_flags: tuple[str, ...] = ("explanation_required",)
    signal_probability_key: str = "probability"
    signal_value_key: str = "expected_value_usd"
    threshold: float = 0.55

    def __init__(self) -> None:
        self.scorer = RecommendationScorer()
        self.policy_gate = GovernancePolicyGate()

    def detect(self, signals: dict[str, Any], graph_context: dict[str, Any] | None = None, profile_context: dict[str, Any] | None = None) -> FamilyDetection:
        probability = float(signals.get(self.signal_probability_key, signals.get("probability", 0.0)))
        blocked = signals.get(f"{self.family_key}_policy_blocked") or signals.get("policy_blocked")
        if blocked:
            return FamilyDetection(False, ("policy_blocked",))
        if probability < self.threshold:
            return FamilyDetection(False, ("below_family_threshold",))
        return FamilyDetection(True)

    def score(self, signals: dict[str, Any], graph_context: dict[str, Any] | None = None, profile_context: dict[str, Any] | None = None):
        probability = float(signals.get(self.signal_probability_key, signals.get("probability", self.threshold)))
        expected_value = float(signals.get(self.signal_value_key, signals.get("expected_value_usd", 0.0)))
        graph_relevance = float(signals.get("graph_relevance_score", (graph_context or {}).get("relevance_score", 0.6)))
        attribution = float(signals.get("attribution_confidence", 0.55))
        anomaly = float(signals.get("anomaly_score", 0.0))
        trust = float(signals.get("trust_score", 0.75))
        risk_penalty = max(anomaly * 0.35, (1.0 - trust) * 0.5)
        return self.scorer.score(RecommendationScoreInput(
            deterministic_rule_score=0.82 if probability >= self.threshold else 0.45,
            ml_probability_score=probability,
            graph_relevance_score=graph_relevance,
            attribution_confidence=attribution,
            economic_expected_value=expected_value,
            risk_penalty=risk_penalty,
            freshness_penalty=float(signals.get("freshness_penalty", 0.05)),
            governance_policy_penalty=0.0,
            model_version=str(signals.get("model_version", f"{self.family_key}-v1")),
        ))

    def generate_candidate_actions(self, confidence, signals: dict[str, Any]) -> list[CandidateAction]:
        expected_value = signals.get(self.signal_value_key, signals.get("expected_value_usd"))
        if expected_value is not None:
            expected_value = round(float(expected_value), 2)
        return [
            CandidateAction(
                action_key=self.default_action_key,
                action_type="integration_ready" if self.family_key != "retention" else "manual_or_system_triggered",
                label=self.default_label,
                description=f"Review graph evidence and execute the governed {self.family_key} workflow only after required approval.",
                system="aether",
                integration=str(signals.get("preferred_integration", "workflow_placeholder")),
                expected_outcome=self.default_expected_outcome,
                expected_value=expected_value,
                currency="USD" if expected_value is not None else None,
                downside_risk=self.default_downside_risk,
                confidence=confidence,
                requires_approval_level=self.required_approval_level,  # type: ignore[arg-type]
                policy_flags=list(self.policy_flags),
            ),
            CandidateAction(
                action_key="open_investigation",
                action_type="manual",
                label="Open investigation workflow",
                description="Inspect evidence, graph context, prior outcomes, and governance flags before action.",
                system="aether",
                expected_outcome="Increase decision quality before operational execution.",
                expected_value=round(float(expected_value or 0.0) * 0.2, 2) if expected_value is not None else None,
                currency="USD" if expected_value is not None else None,
                downside_risk="Slower time to action.",
                confidence=confidence,
                requires_approval_level="none",
                policy_flags=["explanation_required"],
            ),
        ]

    def build_evidence(self, tenant_id: str, entity_id: str, signals: dict[str, Any], graph_context: dict[str, Any] | None = None, profile_context: dict[str, Any] | None = None) -> list[RecommendationEvidence]:
        probability = float(signals.get(self.signal_probability_key, signals.get("probability", self.threshold)))
        graph_relevance = float(signals.get("graph_relevance_score", (graph_context or {}).get("relevance_score", 0.6)))
        return [
            RecommendationEvidence(evidence_id=str(uuid.uuid4()), source_type="profile_signal", source_id=f"profile360:{entity_id}", summary=f"{self.family_key} signal probability {probability:.0%}.", weight=0.30, tenant_id=tenant_id),
            RecommendationEvidence(evidence_id=str(uuid.uuid4()), source_type="edge", source_id=f"graph:{entity_id}", summary=f"Graph relevance score {graph_relevance:.0%} from deterministic traversal rules.", weight=0.25, tenant_id=tenant_id),
            RecommendationEvidence(evidence_id=str(uuid.uuid4()), source_type="policy", source_id=f"policy:{self.family_key}", summary="Governance policy evaluated approval level, policy flags, and suppression reasons.", weight=0.20, tenant_id=tenant_id),
        ]

    def apply_governance(self, action: CandidateAction, confidence_overall: float) -> tuple[str, list[str], float]:
        return self.policy_gate.evaluate(action, confidence_overall)

    def emit(self, tenant_id: str, entity_id: str, signals: dict[str, Any], graph_context: dict[str, Any] | None = None, profile_context: dict[str, Any] | None = None) -> Recommendation:
        confidence = self.score(signals, graph_context, profile_context)
        candidates = self.scorer.rank_actions(self.generate_candidate_actions(confidence, signals))
        approval, flags, _penalty = self.apply_governance(candidates[0], confidence.overall)
        detection = self.detect(signals, graph_context, profile_context)
        policy_flags = sorted(set(flags + candidates[0].policy_flags + list(detection.suppression_reasons)))
        return Recommendation(
            recommendation_id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            entity_id=entity_id,
            recommendation_type=self.family_key,
            recommended_action=candidates[0],
            candidate_actions=candidates,
            confidence=confidence,
            expected_outcome=candidates[0].expected_outcome or self.default_expected_outcome,
            expected_value=candidates[0].expected_value,
            downside_risk=candidates[0].downside_risk,
            evidence=self.build_evidence(tenant_id, entity_id, signals, graph_context, profile_context),
            graph_snapshot_id=str(signals.get("graph_snapshot_id", "")) or None,
            computed_at=now_iso(),
            required_approval_level=approval,  # type: ignore[arg-type]
            policy_governance_flags=policy_flags,
            status="generated" if detection.matched else "suppressed",
        )


class RetentionRecommendationFamily(BaseRecommendationFamily):
    family_key = "retention"
    default_action_key = "human_review_retention_offer"
    default_label = "Review retention offer"
    default_expected_outcome = "Reduce churn risk and recover projected value."
    default_downside_risk = "Over-contact risk if consent, frequency, or recency policies are not satisfied."
    policy_flags = ("consent_required", "frequency_cap_required")
    signal_probability_key = "churn_probability"
    signal_value_key = "retention_expected_value_usd"

    def _with_retention_value(self, signals: dict[str, Any]) -> dict[str, Any]:
        if "retention_expected_value_usd" not in signals:
            ltv = float(signals.get("ltv_predicted_usd", 420.0))
            return {**signals, "retention_expected_value_usd": ltv * 0.18}
        return signals

    def score(self, signals, graph_context=None, profile_context=None):
        return super().score(self._with_retention_value(signals), graph_context, profile_context)

    def generate_candidate_actions(self, confidence, signals: dict[str, Any]) -> list[CandidateAction]:
        return super().generate_candidate_actions(confidence, self._with_retention_value(signals))


class ExpansionRecommendationFamily(BaseRecommendationFamily):
    family_key = "expansion"
    default_action_key = "route_expansion_signal"
    default_label = "Route expansion signal"
    default_expected_outcome = "Identify high-fit expansion opportunities for account teams."
    policy_flags = ("sales_review_required",)
    signal_probability_key = "expansion_probability"


class FraudReviewRecommendationFamily(BaseRecommendationFamily):
    family_key = "fraud_review"
    default_action_key = "open_fraud_cluster_review"
    default_label = "Open fraud cluster review"
    default_expected_outcome = "Reduce fraud loss while preserving analyst review."
    required_approval_level = "elevated"
    policy_flags = ("fraud_review_required", "human_approval_required")
    signal_probability_key = "fraud_probability"


class AttributionOptimizationRecommendationFamily(BaseRecommendationFamily):
    family_key = "attribution_optimization"
    default_action_key = "review_attribution_path"
    default_label = "Review attribution path"
    default_expected_outcome = "Reduce campaign waste by reallocating spend only after review."
    policy_flags = ("campaign_review_required",)
    signal_probability_key = "attribution_waste_probability"


class JourneyOptimizationRecommendationFamily(BaseRecommendationFamily):
    family_key = "journey_optimization"
    default_action_key = "optimize_journey_step"
    default_label = "Optimize journey step"
    default_expected_outcome = "Improve conversion through governed journey tuning."
    policy_flags = ("journey_review_required",)
    signal_probability_key = "journey_dropoff_probability"


class AgentGovernanceRecommendationFamily(BaseRecommendationFamily):
    family_key = "agent_governance"
    default_action_key = "review_agent_policy"
    default_label = "Review agent policy"
    default_expected_outcome = "Prevent unsafe autonomous agent behavior."
    required_approval_level = "critical"
    policy_flags = ("agent_policy_review", "human_approval_required", "critical")
    signal_probability_key = "agent_risk_probability"


class RewardsOptimizationRecommendationFamily(BaseRecommendationFamily):
    family_key = "rewards_optimization"
    default_action_key = "review_reward_trigger"
    default_label = "Review reward trigger"
    default_expected_outcome = "Improve reward efficiency with auditable approval."
    policy_flags = ("reward_policy_review",)
    signal_probability_key = "reward_optimization_probability"


class OperationalFailureRecommendationFamily(BaseRecommendationFamily):
    family_key = "operational_failure"
    default_action_key = "open_operational_failure_review"
    default_label = "Open operational failure review"
    default_expected_outcome = "Resolve repeated operational failure patterns."
    required_approval_level = "elevated"
    policy_flags = ("ops_review_required",)
    signal_probability_key = "operational_failure_probability"


class RecommendationFamilyRegistry:
    """Ordered registry that selects the strongest matching family."""

    def __init__(self, families: list[BaseRecommendationFamily] | None = None) -> None:
        self._families = families or [
            RetentionRecommendationFamily(),
            ExpansionRecommendationFamily(),
            FraudReviewRecommendationFamily(),
            AttributionOptimizationRecommendationFamily(),
            JourneyOptimizationRecommendationFamily(),
            AgentGovernanceRecommendationFamily(),
            RewardsOptimizationRecommendationFamily(),
            OperationalFailureRecommendationFamily(),
        ]

    @property
    def families(self) -> list[BaseRecommendationFamily]:
        return list(self._families)

    def get(self, family_key: str) -> BaseRecommendationFamily | None:
        return next((family for family in self._families if family.family_key == family_key), None)

    def detect(self, signals: dict[str, Any], graph_context: dict[str, Any] | None = None, profile_context: dict[str, Any] | None = None) -> BaseRecommendationFamily:
        requested = signals.get("recommendation_family") or signals.get("recommendation_type")
        if requested and (family := self.get(str(requested))):
            return family
        matches = [family for family in self._families if family.detect(signals, graph_context, profile_context).matched]
        if matches:
            return max(matches, key=lambda family: family.score(signals, graph_context, profile_context).overall)
        return self.get("retention") or self._families[0]
