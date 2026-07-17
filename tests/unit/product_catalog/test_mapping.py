"""Mapping precedence resolver — precedence order, tie-breaks, determinism."""
from __future__ import annotations

from services.product_catalog.mapping import (
    PRECEDENCE_ORDER,
    UNMAPPED,
    resolve_for_match,
    resolve_mapping,
)
from services.product_catalog.models import MappingRule


def _rule(rule_id: str, precedence: str, confidence: float = 1.0, **kwargs) -> MappingRule:
    return MappingRule(
        tenant_id="t1",
        rule_id=rule_id,
        match_kind=kwargs.pop("match_kind", "event_name"),
        match_value=kwargs.pop("match_value", "order_completed"),
        precedence_class=precedence,
        confidence=confidence,
        **kwargs,
    )


class TestPrecedence:
    def test_precedence_order_is_the_documented_ladder(self):
        assert PRECEDENCE_ORDER == (
            "explicit_instrumentation",
            "tenant_catalog",
            "verified_framework",
            "reviewed_discovery",
            "inferred",
            "unmapped",
        )

    def test_explicit_instrumentation_beats_everything(self):
        rules = [
            _rule("r-inferred", "inferred", confidence=1.0),
            _rule("r-explicit", "explicit_instrumentation", confidence=0.5),
            _rule("r-tenant", "tenant_catalog", confidence=1.0),
        ]
        result = resolve_mapping(rules)
        assert result.rule_id == "r-explicit"
        assert result.mapping_source == "explicit_instrumentation"
        assert result.mapping_confidence == 0.5

    def test_each_class_beats_the_next_weaker_one(self):
        ladder = [c for c in PRECEDENCE_ORDER if c != "unmapped"]
        for stronger, weaker in zip(ladder, ladder[1:]):
            result = resolve_mapping([
                _rule("r-weak", weaker, confidence=1.0),
                _rule("r-strong", stronger, confidence=0.1),
            ])
            assert result.rule_id == "r-strong", (stronger, weaker)

    def test_confidence_breaks_ties_within_a_class(self):
        result = resolve_mapping([
            _rule("r-low", "inferred", confidence=0.4),
            _rule("r-high", "inferred", confidence=0.9),
        ])
        assert result.rule_id == "r-high"
        assert result.mapping_confidence == 0.9

    def test_rule_id_breaks_full_ties_deterministically(self):
        a = _rule("rule-a", "tenant_catalog", confidence=0.7)
        b = _rule("rule-b", "tenant_catalog", confidence=0.7)
        assert resolve_mapping([b, a]).rule_id == "rule-a"
        assert resolve_mapping([a, b]).rule_id == "rule-a"

    def test_shadowed_rules_are_recorded_in_order(self):
        result = resolve_mapping([
            _rule("r1", "inferred", confidence=0.3),
            _rule("r2", "explicit_instrumentation"),
            _rule("r3", "reviewed_discovery"),
        ])
        assert result.rule_id == "r2"
        assert result.shadowed_rule_ids == ["r3", "r1"]


class TestUnmapped:
    def test_no_candidates_resolves_to_unmapped(self):
        result = resolve_mapping([])
        assert result == UNMAPPED
        assert result.mapping_source == "unmapped"
        assert result.mapping_confidence == 0.0
        assert result.mapping_version is None
        assert result.rule_id is None

    def test_unmapped_class_rules_never_win(self):
        result = resolve_mapping([_rule("r-un", "unmapped", confidence=1.0)])
        assert result.mapping_source == "unmapped"
        assert result.rule_id is None


class TestResolveForMatch:
    def test_filters_by_match_kind_and_value(self):
        rules = [
            _rule("r-route", "tenant_catalog", match_kind="route", match_value="/checkout"),
            _rule("r-event", "inferred", match_kind="event_name", match_value="order_completed"),
        ]
        result = resolve_for_match(rules, "event_name", "order_completed")
        assert result.rule_id == "r-event"
        assert resolve_for_match(rules, "route", "/nope") == UNMAPPED

    def test_resolution_carries_targets_and_version(self):
        rule = _rule(
            "r-t", "verified_framework", confidence=0.8,
            target_feature_id="feat-1", target_surface_id="surf-1",
            target_control_id="ctl-1", version=3,
        )
        result = resolve_mapping([rule])
        assert result.target_feature_id == "feat-1"
        assert result.target_surface_id == "surf-1"
        assert result.target_control_id == "ctl-1"
        assert result.mapping_version == 3
