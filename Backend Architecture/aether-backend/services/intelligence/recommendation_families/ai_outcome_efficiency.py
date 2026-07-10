"""AI Outcome Efficiency recommendation family.

Maps deterministic AI efficiency detector findings (retry_waste,
model_overqualification, deterministic_replacement_candidate,
cache_opportunity, failed_workflow_concentration) into governed
recommendations. Proposals only — the family never changes production
models, prompts, or routing.

Only active when ``settings.ai_economics.recommendations_enabled`` is True.
"""

from __future__ import annotations

import uuid
from typing import Any

from services.intelligence.decision_models import RecommendationEvidence
from services.intelligence.recommendation_families.base import (
    BaseRecommendationFamily,
    RecommendationGenerationContext,
    _num,
)

_DETECTOR_ACTIONS: dict[str, dict[str, str]] = {
    "retry_waste": {
        "key": "review_retry_waste",
        "label": "Review retry waste",
        "description": "Inspect retried AI invocations and fix the retry root cause.",
    },
    "model_overqualification": {
        "key": "evaluate_cheaper_model",
        "label": "Evaluate cheaper model",
        "description": "Run an offline evaluation of the flagged task on the cheaper card before any routing change.",
    },
    "deterministic_replacement_candidate": {
        "key": "review_deterministic_replacement",
        "label": "Review deterministic replacement",
        "description": "Assess replacing a repeated, perfect-quality invocation with a cached or deterministic path.",
    },
    "cache_opportunity": {
        "key": "review_cache_opportunity",
        "label": "Review prompt caching opportunity",
        "description": "Assess enabling prompt caching for repeated input prefixes.",
    },
    "failed_workflow_concentration": {
        "key": "investigate_failed_workflows",
        "label": "Investigate failing AI workflows",
        "description": "Investigate workflows/tasks with concentrated failures that still incur cost.",
    },
}

_SEVERITY_SCORE = {"high": 0.9, "medium": 0.7, "low": 0.55}


class AIOutcomeEfficiencyRecommendationFamily(BaseRecommendationFamily):
    family_key = "ai_outcome_efficiency"
    family_label = "AI outcome efficiency"
    primary_signal = "ai_efficiency_score"
    detection_signal_keys = (
        "ai_efficiency_score",
        "ai_retry_waste_share",
        "ai_unknown_cost_share",
        "ai_failed_workflow_rate",
    )
    detect_threshold = 0.25
    default_expected_outcome = (
        "Reduce AI spend waste while preserving outcome quality — via governed, "
        "human-approved changes only."
    )
    default_downside_risk = (
        "A cheaper model or cached path may degrade quality if migrated without evaluation."
    )
    default_policy_flags = ("explanation_required", "ai_efficiency_review_required")

    @staticmethod
    def _findings(context: RecommendationGenerationContext) -> list[dict[str, Any]]:
        findings = context.value("ai_efficiency_findings") or []
        return [f for f in findings if isinstance(f, dict)]

    def detect(self, context: RecommendationGenerationContext) -> bool:
        from config.settings import settings
        if not settings.ai_economics.recommendations_enabled:
            return False
        if self._findings(context):
            return True
        return super().detect(context)

    def score(self, context: RecommendationGenerationContext):
        findings = self._findings(context)
        if findings and context.value(self.primary_signal) is None:
            peak = max(_SEVERITY_SCORE.get(f.get("severity", "low"), 0.55) for f in findings)
            context.signals.setdefault(self.primary_signal, peak)
        return super().score(context)

    def expected_value(self, context: RecommendationGenerationContext) -> float | None:
        explicit = context.value("economic_expected_value", context.value("expected_value_usd"))
        if explicit is not None:
            return round(_num(explicit), 2)
        # Sum only USD-denominated waste estimates — never mix currencies.
        total = 0.0
        seen = False
        for finding in self._findings(context):
            waste = finding.get("estimated_monthly_waste") or {}
            if "USD" in waste:
                total += _num(waste["USD"])
                seen = True
        return round(total, 2) if seen else None

    def action_specs(self, context: RecommendationGenerationContext) -> list[dict[str, Any]]:
        specs: list[dict[str, Any]] = []
        seen_detectors: set[str] = set()
        for finding in self._findings(context):
            detector = str(finding.get("detector", ""))
            action = _DETECTOR_ACTIONS.get(detector)
            if action is None or detector in seen_detectors:
                continue
            seen_detectors.add(detector)
            specs.append({
                "key": action["key"],
                "label": action["label"],
                "description": action["description"],
                "type": "manual",
                "approval": "standard",
                "flags": list(self.default_policy_flags),
                "expected_outcome": finding.get("candidate_action"),
            })
        if not specs:
            specs.append({
                "key": "review_ai_efficiency",
                "label": "Review AI efficiency findings",
                "approval": "standard",
                "flags": list(self.default_policy_flags),
            })
        return specs

    def build_evidence(self, context: RecommendationGenerationContext) -> list[RecommendationEvidence]:
        evidence = super().build_evidence(context)
        for finding in self._findings(context):
            detector = str(finding.get("detector", "unknown"))
            refs = finding.get("evidence_refs") or []
            summary = str(finding.get("title") or f"AI efficiency finding: {detector}")
            if refs:
                summary = f"{summary} ({len(refs)} invocation(s) as evidence)."
            evidence.append(RecommendationEvidence(
                evidence_id=str(uuid.uuid4()),
                source_type="economic_state",
                source_id=f"ai_efficiency:{detector}",
                summary=summary[:500],
                weight=0.25,
                tenant_id=context.tenant_id,
            ))
        return evidence
