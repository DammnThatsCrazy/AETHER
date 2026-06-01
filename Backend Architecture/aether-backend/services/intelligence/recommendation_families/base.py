"""Base contracts for graph-native recommendation families."""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
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


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class RecommendationGenerationContext:
    tenant_id: str
    entity_id: str | None = None
    population_id: str | None = None
    signals: dict[str, Any] = field(default_factory=dict)
    profile_context: dict[str, Any] = field(default_factory=dict)
    graph_context: dict[str, Any] = field(default_factory=dict)
    attribution_context: dict[str, Any] = field(default_factory=dict)
    economic_context: dict[str, Any] = field(default_factory=dict)
    ml_context: dict[str, Any] = field(default_factory=dict)
    governance_context: dict[str, Any] = field(default_factory=dict)
    computed_at: str = field(default_factory=now_iso)

    def value(self, key: str, default: Any = None) -> Any:
        for source in (
            self.signals,
            self.profile_context,
            self.graph_context,
            self.attribution_context,
            self.economic_context,
            self.ml_context,
            self.governance_context,
        ):
            if key in source:
                return source[key]
        return default

    @classmethod
    def from_signals(
        cls,
        tenant_id: str,
        entity_id: str | None = None,
        signals: dict[str, Any] | None = None,
        population_id: str | None = None,
    ) -> "RecommendationGenerationContext":
        """Build a context from a flat signal dict.

        Shared by the OODA engine façade and ``BaseRecommendationFamily.emit``
        so ad-hoc callers and the registry assemble an identical context shape,
        including any nested ``*_context`` sub-dictionaries passed inside
        ``signals``. Keeping one builder avoids the two paths drifting apart.
        """
        signals = dict(signals or {})
        return cls(
            tenant_id=tenant_id,
            entity_id=entity_id,
            population_id=population_id or signals.get("population_id"),
            signals=signals,
            profile_context=dict(signals.get("profile_context", {})),
            graph_context=dict(signals.get("graph_context", {})),
            attribution_context=dict(signals.get("attribution_context", {})),
            economic_context=dict(signals.get("economic_context", {})),
            ml_context=dict(signals.get("ml_context", {})),
            governance_context=dict(signals.get("governance_context", {})),
        )


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


class BaseRecommendationFamily:
    family_key = "base"
    family_label = "Base"
    primary_signal = "probability"
    detection_signal_keys: tuple[str, ...] = ()
    detect_threshold = 0.55
    default_expected_outcome = "Improve measurable outcome."
    default_downside_risk = "Analyst time may be spent on a low-impact loop."
    default_policy_flags: tuple[str, ...] = ("explanation_required",)
    default_approval_level = "standard"

    def __init__(self) -> None:
        self.scorer = RecommendationScorer()
        self.policy_gate = GovernancePolicyGate()

    def detect(self, context: RecommendationGenerationContext) -> bool:
        explicit = context.value("recommendation_family") or context.value("recommendation_type")
        if explicit == self.family_key:
            return True
        if context.value(f"{self.family_key}_policy_blocked") or context.value("policy_blocked"):
            return False
        signal_keys = self.detection_signal_keys or (self.primary_signal,)
        return any(_num(context.value(key), 0.0) >= self.detect_threshold for key in signal_keys)

    def score(self, context: RecommendationGenerationContext):
        probability = _num(context.value(self.primary_signal), self.detect_threshold)
        graph_relevance = _num(context.value("graph_relevance_score"), 0.60)
        attribution = _num(context.value("attribution_confidence"), 0.55)
        expected_value = self.expected_value(context)
        anomaly = _num(context.value("anomaly_score"), 0.0)
        trust = _num(context.value("trust_score"), 0.75)
        risk_penalty = max(anomaly * 0.35, (1.0 - trust) * 0.5)
        return self.scorer.score(RecommendationScoreInput(
            deterministic_rule_score=0.82 if probability >= self.detect_threshold else 0.45,
            ml_probability_score=max(0.0, min(1.0, probability)),
            graph_relevance_score=max(0.0, min(1.0, graph_relevance)),
            attribution_confidence=max(0.0, min(1.0, attribution)),
            economic_expected_value=expected_value or 0.0,
            risk_penalty=max(0.0, min(1.0, risk_penalty)),
            freshness_penalty=max(0.0, min(1.0, _num(context.value("freshness_penalty"), 0.05))),
            governance_policy_penalty=0.0,
            model_version=str(context.value("model_version", f"{self.family_key}-v1")),
        ))

    def expected_value(self, context: RecommendationGenerationContext) -> float | None:
        value = context.value("economic_expected_value", context.value("expected_value_usd"))
        return round(_num(value), 2) if value is not None else None

    def action_specs(self, context: RecommendationGenerationContext) -> list[dict[str, Any]]:
        return [{"key": "open_investigation", "label": "Open investigation", "approval": "none", "flags": ["explanation_required"]}]

    def generate_candidate_actions(self, context: RecommendationGenerationContext) -> list[CandidateAction]:
        confidence = self.score(context)
        expected_value = self.expected_value(context)
        actions: list[CandidateAction] = []
        for spec in self.action_specs(context):
            action_value = spec.get("expected_value", expected_value)
            if action_value is not None:
                action_value = round(_num(action_value), 2)
            actions.append(CandidateAction(
                action_key=str(spec["key"]),
                action_type=str(spec.get("type", "manual")),
                label=str(spec["label"]),
                description=spec.get("description") or f"Review {self.family_label.lower()} recommendation evidence before action.",
                system=str(spec.get("system", "aether")),
                integration=spec.get("integration"),
                expected_outcome=spec.get("expected_outcome") or self.default_expected_outcome,
                expected_value=action_value,
                currency="USD" if action_value is not None else None,
                downside_risk=spec.get("downside_risk") or self.default_downside_risk,
                confidence=confidence,
                requires_approval_level=spec.get("approval", self.default_approval_level),
                policy_flags=list(spec.get("flags", self.default_policy_flags)),
            ))
        return self.scorer.rank_actions(actions)

    def build_evidence(self, context: RecommendationGenerationContext) -> list[RecommendationEvidence]:
        evidence = [
            RecommendationEvidence(
                evidence_id=str(uuid.uuid4()),
                source_type="profile_signal",
                source_id=f"profile360:{context.entity_id or context.population_id}",
                summary=f"{self.family_label} signal {self.primary_signal}={_num(context.value(self.primary_signal), 0.0):.2f}.",
                weight=0.30,
                tenant_id=context.tenant_id,
            ),
            RecommendationEvidence(
                evidence_id=str(uuid.uuid4()),
                source_type="edge",
                source_id=f"graph:{context.entity_id or context.population_id}",
                summary=f"Graph relevance score {_num(context.value('graph_relevance_score'), 0.60):.0%} from graph-native context.",
                weight=0.25,
                tenant_id=context.tenant_id,
            ),
            RecommendationEvidence(
                evidence_id=str(uuid.uuid4()),
                source_type="policy",
                source_id=f"policy:{self.family_key}",
                summary="Governance policy evaluated approval level, policy flags, and human-in-the-loop requirements.",
                weight=0.20,
                tenant_id=context.tenant_id,
            ),
        ]
        if context.attribution_context or context.value("attribution_confidence") is not None:
            evidence.append(RecommendationEvidence(
                evidence_id=str(uuid.uuid4()),
                source_type="attribution_path",
                source_id=f"attribution:{context.entity_id or context.population_id}",
                summary=f"Attribution confidence {_num(context.value('attribution_confidence'), 0.55):.0%} for the related path.",
                weight=0.15,
                tenant_id=context.tenant_id,
            ))
        return evidence

    def graph_snapshot_id(self, context: RecommendationGenerationContext) -> str:
        digest = hashlib.sha256(f"{context.tenant_id}:{context.entity_id}:{context.population_id}:{self.family_key}:{context.signals}".encode()).hexdigest()[:16]
        return f"graph-snapshot-{digest}"

    def emit(
        self,
        tenant_id: str,
        entity_id: str | None = None,
        signals: dict[str, Any] | None = None,
        population_id: str | None = None,
    ) -> Recommendation:
        """Build a context from raw signals and generate a recommendation.

        Convenience entry point so callers can produce a recommendation without
        assembling a :class:`RecommendationGenerationContext` by hand. Equivalent
        to ``self.generate(RecommendationGenerationContext.from_signals(...))``.
        """
        context = RecommendationGenerationContext.from_signals(
            tenant_id, entity_id, signals, population_id
        )
        return self.generate(context)

    def generate(self, context: RecommendationGenerationContext) -> Recommendation:
        confidence = self.score(context)
        candidates = self.generate_candidate_actions(context)
        approval, flags, gov_penalty = self.policy_gate.evaluate(candidates[0], confidence.overall)
        if gov_penalty:
            confidence = self.scorer.score(RecommendationScoreInput(
                deterministic_rule_score=confidence.deterministic_rule_score,
                ml_probability_score=confidence.ml_probability_score or 0.0,
                graph_relevance_score=confidence.graph_relevance_score or 0.0,
                attribution_confidence=confidence.attribution_confidence or 0.0,
                economic_expected_value=confidence.economic_expected_value or 0.0,
                risk_penalty=confidence.risk_penalty,
                freshness_penalty=confidence.freshness_penalty,
                governance_policy_penalty=gov_penalty,
                model_version=confidence.model_version,
            ))
            candidates = [action.model_copy(update={"confidence": confidence}) for action in candidates]
        policy_flags = sorted(set(flags + candidates[0].policy_flags + list(self.default_policy_flags)))
        return Recommendation(
            recommendation_id=str(uuid.uuid4()),
            tenant_id=context.tenant_id,
            entity_id=context.entity_id,
            population_id=context.population_id,
            recommendation_type=self.family_key,
            recommended_action=candidates[0],
            candidate_actions=candidates,
            confidence=confidence,
            expected_outcome=candidates[0].expected_outcome or self.default_expected_outcome,
            expected_value=candidates[0].expected_value,
            downside_risk=candidates[0].downside_risk,
            evidence=self.build_evidence(context),
            graph_snapshot_id=self.graph_snapshot_id(context),
            computed_at=context.computed_at,
            required_approval_level=approval,
            policy_governance_flags=policy_flags,
            data_freshness=DataFreshness(
                status="stale" if _num(context.value("freshness_penalty"), 0.05) >= 0.25 else "fresh",
                max_age_seconds=int(_num(context.value("max_age_seconds"), 3600)),
            ),
        )
