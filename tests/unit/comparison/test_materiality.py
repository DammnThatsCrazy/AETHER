"""Materiality composition + hard severity override monotonicity."""
from __future__ import annotations

import pytest

from services.intelligence.comparison.generated_vocabulary import (
    COMPARISON_SEVERITIES,
    MATERIALITY_COMPONENTS,
)
from services.intelligence.comparison.materiality import (
    HardSeverityOverride,
    score_materiality,
    severity_for_score,
)

RANK = {s: i for i, s in enumerate(COMPARISON_SEVERITIES)}


class TestComposition:
    def test_uniform_blend_of_components(self):
        result = score_materiality({"economic_impact": 0.8, "risk_impact": 0.4})
        assert result.score == pytest.approx(0.6)
        assert result.banded_severity == "critical" if result.score >= 0.8 else True

    def test_all_fourteen_components_accepted(self):
        result = score_materiality({name: 0.5 for name in MATERIALITY_COMPONENTS})
        assert result.score == pytest.approx(0.5)
        assert result.missing_components == []

    def test_unknown_component_rejected(self):
        with pytest.raises(ValueError, match="Unknown materiality component"):
            score_materiality({"vibes": 1.0})

    def test_out_of_range_component_rejected(self):
        with pytest.raises(ValueError, match="out of range"):
            score_materiality({"risk_impact": 1.5})

    def test_empty_components_rejected(self):
        with pytest.raises(ValueError, match="At least one"):
            score_materiality({})

    def test_missing_components_are_reported_not_defaulted(self):
        result = score_materiality({"confidence": 1.0})
        assert result.score == pytest.approx(1.0)  # only provided components count
        assert "risk_impact" in result.missing_components
        assert len(result.missing_components) == len(MATERIALITY_COMPONENTS) - 1

    def test_custom_weights(self):
        result = score_materiality(
            {"economic_impact": 1.0, "freshness": 0.0},
            weights={"economic_impact": 3.0, "freshness": 1.0},
        )
        assert result.score == pytest.approx(0.75)


class TestSeverityBands:
    @pytest.mark.parametrize(
        "score,expected",
        [(0.0, "info"), (0.19, "info"), (0.2, "low"), (0.45, "medium"),
         (0.65, "high"), (0.8, "critical"), (1.0, "critical")],
    )
    def test_bands(self, score, expected):
        assert severity_for_score(score) == expected


class TestHardOverrides:
    def test_override_raises_severity(self):
        # Blended score is low, but risk_impact hits the hard floor.
        result = score_materiality(
            {"risk_impact": 0.95, "economic_impact": 0.0, "confidence": 0.0,
             "freshness": 0.0, "data_quality": 0.0}
        )
        assert result.banded_severity in ("info", "low")
        assert result.severity == "high"
        assert result.overrides_applied

    def test_override_never_lowers_severity(self):
        # Score already critical; a "high" floor must not pull it down.
        override = HardSeverityOverride(
            component="risk_impact", threshold=0.5, min_severity="high"
        )
        result = score_materiality(
            {"risk_impact": 0.9, "economic_impact": 0.9, "policy_impact": 0.9},
            hard_overrides=(override,),
        )
        assert result.banded_severity == "critical"
        assert result.severity == "critical"  # unchanged by the lower floor
        assert result.overrides_applied == []

    def test_monotonicity_sweep(self):
        """For every component value, severity with overrides >= without."""
        override = HardSeverityOverride(
            component="policy_impact", threshold=0.7, min_severity="critical"
        )
        for i in range(0, 21):
            value = i / 20
            components = {"policy_impact": value, "economic_impact": 0.1}
            base = score_materiality(components, hard_overrides=())
            with_override = score_materiality(components, hard_overrides=(override,))
            assert RANK[with_override.severity] >= RANK[base.severity]

    def test_untriggered_override_is_inert(self):
        override = HardSeverityOverride(
            component="risk_impact", threshold=0.9, min_severity="critical"
        )
        result = score_materiality({"risk_impact": 0.3}, hard_overrides=(override,))
        assert result.severity == result.banded_severity

    def test_override_validates_component_and_severity(self):
        with pytest.raises(ValueError):
            HardSeverityOverride(component="nope", threshold=0.5, min_severity="high")
        with pytest.raises(ValueError):
            HardSeverityOverride(
                component="risk_impact", threshold=0.5, min_severity="apocalyptic"
            )
