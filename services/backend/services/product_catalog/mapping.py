"""Mapping precedence resolver — pure, deterministic, no I/O.

Given the candidate MappingRules that match one piece of raw instrumentation,
pick the winning rule by precedence class, then confidence, then rule_id.
The output records mapping_source / mapping_confidence / mapping_version so
every downstream row can explain exactly why it maps where it maps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from services.product_catalog.models import MappingRule

# Strongest → weakest. An explicit instrumentation annotation always beats a
# tenant-curated catalog rule, which beats a verified framework default, which
# beats a human-reviewed discovery, which beats a pure inference. `unmapped`
# is the terminal fallback and never wins against any real rule.
PRECEDENCE_ORDER: tuple[str, ...] = (
    "explicit_instrumentation",
    "tenant_catalog",
    "verified_framework",
    "reviewed_discovery",
    "inferred",
    "unmapped",
)

_PRECEDENCE_RANK: dict[str, int] = {name: i for i, name in enumerate(PRECEDENCE_ORDER)}


@dataclass(frozen=True)
class MappingResolution:
    """Resolved mapping for one piece of instrumentation."""

    mapping_source: str                      # winning precedence class (or 'unmapped')
    mapping_confidence: float                # winner's confidence (0.0 when unmapped)
    mapping_version: Optional[int]           # winner's rule version (None when unmapped)
    rule_id: Optional[str] = None
    target_feature_id: Optional[str] = None
    target_surface_id: Optional[str] = None
    target_control_id: Optional[str] = None
    # Losing candidates' rule_ids, in deterministic order (for explainability).
    shadowed_rule_ids: list[str] = field(default_factory=list)


UNMAPPED = MappingResolution(
    mapping_source="unmapped",
    mapping_confidence=0.0,
    mapping_version=None,
)


def _sort_key(rule: MappingRule) -> tuple[int, float, str]:
    # Precedence rank ascending (strongest first), confidence descending,
    # rule_id ascending — a total, deterministic order.
    return (_PRECEDENCE_RANK[rule.precedence_class], -rule.confidence, rule.rule_id)


def resolve_mapping(candidates: Sequence[MappingRule]) -> MappingResolution:
    """Pick the winning rule among candidates for ONE instrumentation match.

    Callers pre-filter candidates to those whose (match_kind, match_value)
    actually match the instrumentation being resolved; this function only
    arbitrates precedence. Empty input resolves to UNMAPPED.
    """
    real = [r for r in candidates if r.precedence_class != "unmapped"]
    if not real:
        return UNMAPPED
    ordered = sorted(real, key=_sort_key)
    winner = ordered[0]
    return MappingResolution(
        mapping_source=winner.precedence_class,
        mapping_confidence=winner.confidence,
        mapping_version=winner.version,
        rule_id=winner.rule_id,
        target_feature_id=winner.target_feature_id,
        target_surface_id=winner.target_surface_id,
        target_control_id=winner.target_control_id,
        shadowed_rule_ids=[r.rule_id for r in ordered[1:]],
    )


def resolve_for_match(
    rules: Sequence[MappingRule],
    match_kind: str,
    match_value: str,
) -> MappingResolution:
    """Filter rules to those matching (match_kind, match_value), then resolve."""
    candidates = [
        r for r in rules
        if r.match_kind == match_kind and r.match_value == match_value
    ]
    return resolve_mapping(candidates)
