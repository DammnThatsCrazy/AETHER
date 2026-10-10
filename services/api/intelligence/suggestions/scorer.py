"""Priority scoring for the Suggestion entity.

The priority_score is a weighted sum of signal dimensions minus a
reversibility penalty. The computed float maps to a SuggestionPriority
bucket, with class-level hard overrides for security and reliability.
"""

from __future__ import annotations

from typing import Optional

from .models import SuggestionClass, SuggestionCreate, SuggestionPriority

# ---------------------------------------------------------------------------
# Weights (must sum to 1.0 before risk/reversibility adjustment)
# ---------------------------------------------------------------------------

WEIGHT_IMPACT           = 0.30
WEIGHT_CONFIDENCE       = 0.20
WEIGHT_URGENCY          = 0.20
WEIGHT_EVIDENCE_QUALITY = 0.15
WEIGHT_TENANT_VALUE     = 0.15

# Reversibility penalty multiplied against risk_score
REVERSIBILITY_PENALTY: dict[Optional[bool], float] = {
    True:  0.20,
    False: 0.40,
    None:  0.30,
}

# Priority score thresholds
P0_THRESHOLD = 0.90
P1_THRESHOLD = 0.75
P2_THRESHOLD = 0.50
P3_THRESHOLD = 0.25

# Classes that always force at least P1 priority
HIGH_RISK_CLASSES: frozenset[SuggestionClass] = frozenset({
    SuggestionClass.SECURITY,
    SuggestionClass.RELIABILITY,
    SuggestionClass.IDENTITY,
    SuggestionClass.GRAPH_HEALTH,
    SuggestionClass.GOVERNANCE,
})

# Class minimum floor priorities
CLASS_FLOOR: dict[SuggestionClass, SuggestionPriority] = {
    SuggestionClass.SECURITY:     SuggestionPriority.P1,
    SuggestionClass.RELIABILITY:  SuggestionPriority.P1,
    SuggestionClass.IDENTITY:     SuggestionPriority.P2,
    SuggestionClass.GRAPH_HEALTH: SuggestionPriority.P2,
    SuggestionClass.GOVERNANCE:   SuggestionPriority.P2,
}

_PRIORITY_ORDER = [
    SuggestionPriority.P0,
    SuggestionPriority.P1,
    SuggestionPriority.P2,
    SuggestionPriority.P3,
    SuggestionPriority.INFO,
]


def _higher_priority(a: SuggestionPriority, b: SuggestionPriority) -> SuggestionPriority:
    """Return the higher-urgency of two priorities (P0 > P1 > P2 > P3 > info)."""
    return a if _PRIORITY_ORDER.index(a) <= _PRIORITY_ORDER.index(b) else b


def compute_priority_score(
    impact: float,
    confidence: float,
    urgency: float,
    evidence_quality: float,
    tenant_value: float,
    risk: Optional[float],
    reversible: Optional[bool],
) -> float:
    """Compute a [0.0, 1.0] priority score."""
    penalty = REVERSIBILITY_PENALTY.get(reversible, 0.30)
    raw = (
        impact           * WEIGHT_IMPACT
        + confidence     * WEIGHT_CONFIDENCE
        + urgency        * WEIGHT_URGENCY
        + evidence_quality * WEIGHT_EVIDENCE_QUALITY
        + tenant_value   * WEIGHT_TENANT_VALUE
        - (risk or 0.0)  * penalty
    )
    return max(0.0, min(1.0, raw))


def map_to_priority(
    score: float,
    suggestion_class: SuggestionClass,
    risk_score: Optional[float],
) -> SuggestionPriority:
    """Map a priority_score to a SuggestionPriority, applying class floors."""
    if score >= P0_THRESHOLD:
        raw_priority = SuggestionPriority.P0
    elif score >= P1_THRESHOLD:
        raw_priority = SuggestionPriority.P1
    elif score >= P2_THRESHOLD:
        raw_priority = SuggestionPriority.P2
    elif score >= P3_THRESHOLD:
        raw_priority = SuggestionPriority.P3
    else:
        raw_priority = SuggestionPriority.INFO

    # Apply class floor — never demote below the class minimum
    floor = CLASS_FLOOR.get(suggestion_class)
    if floor is not None:
        raw_priority = _higher_priority(raw_priority, floor)

    # High risk_score forces at least P1
    if risk_score is not None and risk_score >= 0.8 and _PRIORITY_ORDER.index(raw_priority) > 1:
        raw_priority = SuggestionPriority.P1

    return raw_priority


def compute_scores(create: SuggestionCreate) -> dict:
    """Compute all derived scores from a SuggestionCreate.

    Returns a dict of derived field overrides ready to merge into the
    Suggestion constructor kwargs.
    """
    impact    = create.impact_score    if create.impact_score    is not None else create.confidence_score
    urgency   = create.urgency_score   if create.urgency_score   is not None else 0.5
    ev_qual   = 0.7  # default evidence quality unless overridden
    tv        = 0.5  # default tenant value unless overridden
    risk      = create.risk_score
    reversible = create.reversible

    priority_score = compute_priority_score(
        impact=impact,
        confidence=create.confidence_score,
        urgency=urgency,
        evidence_quality=ev_qual,
        tenant_value=tv,
        risk=risk,
        reversible=reversible,
    )
    priority = map_to_priority(priority_score, create.suggestion_class, risk)

    return {
        "impact_score":          impact,
        "urgency_score":         urgency,
        "evidence_quality_score": ev_qual,
        "tenant_value_score":    tv,
        "reversibility_score":   (1.0 - REVERSIBILITY_PENALTY.get(reversible, 0.30)),
        "priority_score":        priority_score,
        "priority":              priority,
    }
