"""Recommendation family registration + suggestion adapter mapping."""

from __future__ import annotations

import dataclasses
import os

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from config.settings import settings  # noqa: E402
from services.intelligence.recommendation_families.ai_outcome_efficiency import (  # noqa: E402
    AIOutcomeEfficiencyRecommendationFamily,
)
from services.intelligence.recommendation_families.base import (  # noqa: E402
    RecommendationGenerationContext,
)
from services.intelligence.recommendation_families.registry import (  # noqa: E402
    RecommendationFamilyRegistry,
)
from services.suggestions.adapters.ai_efficiency_adapter import (  # noqa: E402
    create_suggestion_from_ai_efficiency_finding,
    create_suggestions_from_findings,
)
from services.suggestions.models import SuggestionClass, SuggestionSource  # noqa: E402


def _finding(**overrides):
    base = {
        "detector": "retry_waste",
        "tenant_id": "t-fam",
        "severity": "high",
        "title": "Retry waste on prov/model",
        "description": "3 of 5 invocations were retried.",
        "evidence_refs": ["inv-1", "inv-2", "inv-3"],
        "estimated_monthly_waste": {"USD": 60.0},
        "candidate_action": "Investigate the failure/retry causes.",
    }
    base.update(overrides)
    return base


def _context(findings):
    return RecommendationGenerationContext.from_signals(
        "t-fam", entity_id="entity-1",
        signals={"ai_efficiency_findings": findings},
    )


@pytest.fixture()
def recommendations_on(monkeypatch):
    patched = dataclasses.replace(
        settings.ai_economics, enabled=True, recommendations_enabled=True,
    )
    monkeypatch.setattr(settings, "ai_economics", patched)


@pytest.fixture()
def recommendations_off(monkeypatch):
    patched = dataclasses.replace(
        settings.ai_economics, enabled=True, recommendations_enabled=False,
    )
    monkeypatch.setattr(settings, "ai_economics", patched)


class TestRecommendationFamily:
    def test_family_registered(self):
        registry = RecommendationFamilyRegistry()
        family = registry.get("ai_outcome_efficiency")
        assert family is not None
        assert isinstance(family, AIOutcomeEfficiencyRecommendationFamily)

    def test_detect_false_when_flag_off(self, recommendations_off):
        family = AIOutcomeEfficiencyRecommendationFamily()
        assert family.detect(_context([_finding()])) is False

    def test_detect_true_with_findings_when_enabled(self, recommendations_on):
        family = AIOutcomeEfficiencyRecommendationFamily()
        assert family.detect(_context([_finding()])) is True
        assert family.detect(_context([])) is False

    def test_generate_maps_findings_to_evidence_and_actions(self, recommendations_on):
        family = AIOutcomeEfficiencyRecommendationFamily()
        findings = [
            _finding(),
            _finding(detector="cache_opportunity", severity="medium",
                     title="Low cache utilization", evidence_refs=["inv-9"]),
        ]
        recommendation = family.generate(_context(findings))
        assert recommendation.recommendation_type == "ai_outcome_efficiency"
        evidence_ids = {e.source_id for e in recommendation.evidence}
        assert "ai_efficiency:retry_waste" in evidence_ids
        assert "ai_efficiency:cache_opportunity" in evidence_ids
        action_keys = {a.action_key for a in recommendation.candidate_actions}
        assert "review_retry_waste" in action_keys
        assert "review_cache_opportunity" in action_keys
        # USD-only waste estimates sum into expected value (60 + 60)
        assert recommendation.expected_value == pytest.approx(120.0)
        assert recommendation.required_approval_level in ("standard", "elevated", "critical")


class TestSuggestionAdapter:
    def test_maps_finding_with_existing_enums(self):
        suggestion = create_suggestion_from_ai_efficiency_finding(_finding())
        assert suggestion is not None
        assert suggestion.source == SuggestionSource.RULE
        assert suggestion.suggestion_class == SuggestionClass.AGENT_OPERATIONS
        assert suggestion.tenant_id == "t-fam"
        assert suggestion.subject.kind == "tenant"
        assert suggestion.confidence_score == pytest.approx(0.90)
        assert len(suggestion.evidence) == 3
        assert suggestion.source_ref["id"].startswith("ai_eff:retry_waste:")

    def test_source_ref_stable_for_same_finding(self):
        first = create_suggestion_from_ai_efficiency_finding(_finding())
        second = create_suggestion_from_ai_efficiency_finding(_finding())
        assert first is not None and second is not None
        assert first.source_ref["id"] == second.source_ref["id"]

    def test_malformed_finding_returns_none(self):
        assert create_suggestion_from_ai_efficiency_finding({}) is None
        assert create_suggestion_from_ai_efficiency_finding({"detector": "x"}) is None

    def test_batch_mapping_drops_bad_entries(self):
        suggestions = create_suggestions_from_findings([
            _finding(), {}, _finding(detector="cache_opportunity"),
        ])
        assert len(suggestions) == 2

    def test_unquantified_waste_summary(self):
        suggestion = create_suggestion_from_ai_efficiency_finding(
            _finding(estimated_monthly_waste=None)
        )
        assert suggestion is not None
        assert "unquantified" in suggestion.summary
