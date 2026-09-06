"""Risk360 materiality / finding-candidate hook (Phase 5).

Materiality precedes finding creation; risk does not auto-create findings
(RISK_FRAUD_360.md §7). This module is the "materiality / finding-candidate"
hook the Risk360 pipeline calls: it maps an evidence-backed
:class:`~services.risk360.contracts.RiskAssessment`'s risk outcome / confidence
/ vector coverage / exposure magnitude onto the comparison plane's
:func:`services.intelligence.comparison.materiality.score_materiality`
components (``risk_impact``, ``economic_impact``, ``policy_impact``,
``data_quality``, ``confidence``), returning a comparison
:class:`~services.intelligence.comparison.materiality.MaterialityResult`.

Honesty contract
----------------

* Returns ``None`` when there is nothing evidence-backed to score — an empty
  assessment (no value-bearing component and no valued exposure) is NOT scored
  as a low-severity finding; it simply has no materiality yet.
* Component scores are derived from what the assessment actually records
  (outcome, usd exposure, coverage, confidence). Missing components are left
  missing and reported by ``score_materiality`` — never silently defaulted.
* The outcome → impact maps below are severity-band semantics for the
  materiality plane, NOT decision thresholds (those live in the RiskPolicy's
  canonical ``DecisionPolicy``). They translate the policy *disposition* into a
  0–1 materiality component so downstream finding ladders can compare apples to
  apples.

Phase 6 pushes real findings through the comparison disposition ladder; this
hook only produces the scoring candidate.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Mapping, Optional

from shared.computation.policies import PolicyOutcome
from shared.measurement.value_states import requires_value

from .contracts import ExposureAssessment, RiskAssessment

# Reused lazily so module import never requires the comparison plane.
from services.intelligence.comparison.materiality import (  # noqa: E402
    MaterialityResult,
    score_materiality,
)

# USD-denominated magnitude cap for the economic_impact component: exposure at
# or above this saturates the component at 1.0 (a monotone, documented heuristic
# — the exact magnitude map is intentionally simple and testable).
_ECONOMIC_IMPACT_CAP_USD = Decimal("1000000")

# Policy disposition → 0–1 materiality-component semantics. These are NOT
# decision thresholds (policies own those); they rank how material a given
# disposition is for the materiality/finding plane.
_OUTCOME_RISK_IMPACT: Mapping[PolicyOutcome, float] = {
    PolicyOutcome.ALLOW: 0.1,
    PolicyOutcome.IGNORE: 0.1,
    PolicyOutcome.MERGE: 0.3,
    PolicyOutcome.REVIEW: 0.5,
    PolicyOutcome.INTERVENE: 0.85,
    PolicyOutcome.BLOCK: 0.9,
    PolicyOutcome.REJECT: 0.9,
}

# Same dispositions mapped for the comparison plane's policy_impact component.
_OUTCOME_POLICY_IMPACT: Mapping[PolicyOutcome, float] = {
    PolicyOutcome.ALLOW: 0.1,
    PolicyOutcome.IGNORE: 0.1,
    PolicyOutcome.MERGE: 0.3,
    PolicyOutcome.REVIEW: 0.55,
    PolicyOutcome.INTERVENE: 0.9,
    PolicyOutcome.BLOCK: 0.9,
    PolicyOutcome.REJECT: 0.9,
}


def _economic_impact_for_usd(usd_value: Optional[Decimal]) -> Optional[float]:
    """Monotone 0–1 economic-impact magnitude from a USD exposure value.

    ``None`` (unpriced exposure) returns ``None`` — no fabricated figure. A real
    value maps linearly up to the documented cap.
    """
    if usd_value is None:
        return None
    raw = Decimal(usd_value)
    if raw <= 0:
        return 0.0
    ratio = raw / _ECONOMIC_IMPACT_CAP_USD
    return 1.0 if ratio >= 1 else float(ratio)


def _coverage_quality(assessment: RiskAssessment) -> Optional[float]:
    """0–1 data-quality-from-coverage over the assessment's recorded vector.

    Returns ``None`` when the vector records no component (nothing to score).
    A fully value-bearing vector reads as good data quality; an assessment that
    records mostly non-value-bearing states (producers ran but produced no
    usable numbers) reads as degraded coverage.
    """
    components = assessment.vector.components
    if not components:
        return None
    recorded = len(components)
    scored = sum(
        1 for c in components if requires_value(c.state) and c.score is not None
    )
    return scored / recorded


def materiality_for_assessment(
    assessment: RiskAssessment,
    *,
    outcome: Optional[PolicyOutcome] = None,
    exposure: Optional[ExposureAssessment] = None,
) -> Optional[MaterialityResult]:
    """Score the assessment's materiality, or return ``None`` honestly.

    ``outcome`` is the policy disposition the assessment projected under
    (RiskAssessment does not store it — the pipeline holds it during step (c)
    and passes it here). ``exposure`` defaults to ``assessment.exposure``.

    Components:
    * ``risk_impact`` — from the policy ``outcome`` severity disposition.
    * ``policy_impact`` — from the same disposition.
    * ``economic_impact`` — from the exposure USD magnitude when present.
    * ``data_quality`` — from vector value-coverage.
    * ``confidence`` — from the assessment confidence when evidence-backed.

    Returns ``None`` when nothing is evidence-backed (no value-bearing
    component and no valued exposure) — such an assessment is not materiality-
    scored at all.
    """
    effective_exposure = exposure if exposure is not None else assessment.exposure
    exposure_usd = (
        effective_exposure.economic_value.usd_value
        if effective_exposure is not None
        and effective_exposure.economic_value is not None
        else None
    )

    components: dict[str, float] = {}
    has_evidence = False
    for component in assessment.vector.components:
        if requires_value(component.state) and component.score is not None:
            has_evidence = True
            break
    if exposure_usd is not None:
        has_evidence = True

    if not has_evidence:
        return None

    if outcome is not None and outcome in _OUTCOME_RISK_IMPACT:
        components["risk_impact"] = _OUTCOME_RISK_IMPACT[outcome]
        components["policy_impact"] = _OUTCOME_POLICY_IMPACT[outcome]

    economic_impact = _economic_impact_for_usd(exposure_usd)
    if economic_impact is not None:
        components["economic_impact"] = economic_impact

    coverage = _coverage_quality(assessment)
    if coverage is not None:
        components["data_quality"] = coverage

    if assessment.confidence is not None:
        components["confidence"] = assessment.confidence

    if not components:
        return None
    return score_materiality(components)


__all__ = [
    "materiality_for_assessment",
]
