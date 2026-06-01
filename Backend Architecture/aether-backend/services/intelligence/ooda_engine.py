"""Graph-native OODA recommendation generation inside the intelligence service."""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

from services.intelligence.decision_models import (
    CandidateAction,
    DataFreshness,
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


class GraphNativeRecommendationEngine:
    def __init__(self) -> None:
        self.scorer = RecommendationScorer()
        self.policy_gate = GovernancePolicyGate()

    def _snapshot_id(self, tenant_id: str, entity_id: str, payload: dict[str, Any]) -> str:
        digest = hashlib.sha256(f"{tenant_id}:{entity_id}:{payload}".encode()).hexdigest()[:16]
        return f"graph-snapshot-{digest}"

    def generate_for_entity(self, tenant_id: str, entity_id: str, signals: dict[str, Any] | None = None) -> Recommendation:
        signals = signals or {}
        churn = float(signals.get("churn_probability", 0.62))
        ltv = float(signals.get("ltv_predicted_usd", 420.0))
        anomaly = float(signals.get("anomaly_score", 0.18))
        attribution = float(signals.get("attribution_confidence", 0.72))
        graph_relevance = float(signals.get("graph_relevance_score", 0.66))
        trust = float(signals.get("trust_score", 0.82))
        freshness_penalty = float(signals.get("freshness_penalty", 0.05))

        rule_score = 0.80 if churn >= 0.55 and ltv >= 100 else 0.48
        risk_penalty = max(anomaly * 0.35, (1.0 - trust) * 0.5)

        base = RecommendationScoreInput(
            deterministic_rule_score=rule_score,
            ml_probability_score=churn,
            graph_relevance_score=graph_relevance,
            attribution_confidence=attribution,
            economic_expected_value=ltv * 0.18,
            risk_penalty=risk_penalty,
            freshness_penalty=freshness_penalty,
            governance_policy_penalty=0.0,
            model_version=str(signals.get("model_version", "ooda-v1")),
        )
        confidence = self.scorer.score(base)

        candidates = [
            CandidateAction(
                action_key="human_review_retention_offer",
                action_type="manual_or_system_triggered",
                label="Review retention offer",
                description="Create a consent-compliant retention touch with human approval before execution.",
                system="aether",
                integration=str(signals.get("preferred_integration", "notification_or_crm")),
                expected_outcome="Reduce churn risk and recover projected value.",
                expected_value=round(ltv * 0.18, 2),
                currency="USD",
                downside_risk="Over-contact risk if consent, frequency, or recency policies are not satisfied.",
                confidence=confidence,
                requires_approval_level="standard",
                policy_flags=["consent_required", "frequency_cap_required"],
            ),
            CandidateAction(
                action_key="open_investigation",
                action_type="manual",
                label="Open investigation workflow",
                description="Ask an analyst to inspect graph evidence, attribution path, and risk signals.",
                system="aether",
                expected_outcome="Clarify ambiguous graph state before action.",
                expected_value=round(ltv * 0.04, 2),
                currency="USD",
                downside_risk="Slower time to action.",
                confidence=confidence,
                requires_approval_level="none",
                policy_flags=["explanation_required"],
            ),
        ]
        ranked = self.scorer.rank_actions(candidates)
        approval, flags, gov_penalty = self.policy_gate.evaluate(ranked[0], confidence.overall)
        if gov_penalty:
            confidence = self.scorer.score(RecommendationScoreInput(**{**base.__dict__, "governance_policy_penalty": gov_penalty}))

        evidence = [
            RecommendationEvidence(evidence_id=str(uuid.uuid4()), source_type="ml_prediction", source_id=f"churn:{entity_id}", summary=f"Churn model probability {churn:.0%}.", weight=0.30, tenant_id=tenant_id),
            RecommendationEvidence(evidence_id=str(uuid.uuid4()), source_type="profile_signal", source_id=f"profile360:{entity_id}", summary=f"Predicted LTV ${ltv:,.2f} with trust score {trust:.0%}.", weight=0.25, tenant_id=tenant_id),
            RecommendationEvidence(evidence_id=str(uuid.uuid4()), source_type="attribution_path", source_id=f"attribution:{entity_id}", summary=f"Attribution confidence {attribution:.0%} for the current journey path.", weight=0.20, tenant_id=tenant_id),
            RecommendationEvidence(evidence_id=str(uuid.uuid4()), source_type="edge", source_id=f"graph:{entity_id}", summary=f"Graph relevance score {graph_relevance:.0%} from relationship traversal.", weight=0.15, tenant_id=tenant_id),
        ]

        return Recommendation(
            recommendation_id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            entity_id=entity_id,
            recommendation_type="retention",
            recommended_action=ranked[0],
            candidate_actions=ranked,
            confidence=confidence,
            expected_outcome=ranked[0].expected_outcome or "Improve measurable outcome.",
            expected_value=ranked[0].expected_value,
            downside_risk=ranked[0].downside_risk,
            evidence=evidence,
            graph_snapshot_id=self._snapshot_id(tenant_id, entity_id, signals),
            computed_at=now_iso(),
            required_approval_level=approval,
            policy_governance_flags=sorted(set(flags + ranked[0].policy_flags)),
            data_freshness=DataFreshness(status="stale" if freshness_penalty >= 0.25 else "fresh", max_age_seconds=int(signals.get("max_age_seconds", 3600))),
        )
