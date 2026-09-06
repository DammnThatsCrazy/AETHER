"""Risk360 dimension registry — declarative typed registry (Phase 3).

Seeded from the canonical 24-dimension set of
``docs/source-of-truth/RISK_FRAUD_360.md`` §4 (Risk architecture). Each
:class:`RiskDimension` is one frozen row of the registry: a stable ``key``, a
human ``label``, a ``description`` of what the dimension measures, and the
honest ``default_state`` a dimension carries when no observation has fed it.

The registry is a **declarative typed Python registry** (frozen dataclass rows
+ frozenset of keys), per the Risk360/Fraud360 convergence-program scoping
decision — not a new JSON vocabulary. It is promotable to a shared JSON
registry later if a frontend needs a typed union.

Dimension state semantics (``ValueState``)
------------------------------------------

Dimension state follows the canonical measurement-plane authority
:class:`shared.measurement.value_states.ValueState`. The governing invariant:
**a dimension that was not observed is NEVER coerced to a fabricated zero.**
The SoT §4 absence vocabulary (``missing`` / ``unknown`` / ``unavailable`` /
``not_applicable`` / ``suppressed``) is legal and maps onto ``ValueState`` as
follows:

* ``missing`` / ``unknown`` — no observation has fed the dimension. This is
  every seeded dimension's ``default_state``: ``ValueState.MISSING_INPUTS``
  ("could not run; no knowledge"). A ``RiskVector`` that lacks a component for
  the dimension reports this state (see
  :meth:`services.risk360.contracts.RiskVector.component_for`) and never a
  ``0``.
* ``not_applicable`` — ``ValueState.NOT_APPLICABLE`` when the dimension does not
  apply to a subject kind (e.g. ``campaign`` for a device-only subject). A
  producer switches the component to this state explicitly.
* ``unavailable`` / ``suppressed`` — withheld by consent/policy. The number is
  still never invented: these are carried on the claim as
  ``EpistemicStatus.UNAVAILABLE``, and the component stays a non-value-bearing
  ``ValueState`` with ``score=None``.

``requires_value(state)`` (``shared.measurement.value_states``) is the shared
predicate: only ``observed`` / ``estimated`` may carry a real ``score``; every
other state requires ``score=None``. The contracts enforce this on every
``RiskComponent``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from shared.measurement.value_states import ValueState


@dataclass(frozen=True)
class RiskDimension:
    """One frozen row of the risk dimension registry.

    ``default_state`` is the honest state a dimension carries when no
    observation has fed it — ``ValueState.MISSING_INPUTS`` for every seeded
    dimension, which is non-value-bearing (never a fabricated zero). Producers
    upgrade a component to ``observed``/``estimated`` only when data genuinely
    supports a score, and to ``not_applicable`` when the dimension does not
    apply to the subject kind.
    """

    key: str
    label: str
    description: str
    default_state: ValueState = ValueState.MISSING_INPUTS


# Seeded in the canonical order of RISK_FRAUD_360.md §4.
RISK_DIMENSIONS: Final[tuple[RiskDimension, ...]] = (
    RiskDimension(
        key="identity",
        label="Identity",
        description=(
            "Truth and provenance of the subject's identity/account linkage — "
            "who the subject is and how firmly that is established."
        ),
    ),
    RiskDimension(
        key="authentication",
        label="Authentication",
        description=(
            "Strength and integrity of how the subject/actor authenticates as "
            "who or what they claim to be."
        ),
    ),
    RiskDimension(
        key="behavioral",
        label="Behavioral",
        description=(
            "Conduct patterns and whether recent behavior is consistent with or "
            "divergent from the subject's baseline."
        ),
    ),
    RiskDimension(
        key="relationship",
        label="Relationship",
        description=(
            "The subject's graph relationships and their integrity — weighted "
            "links, affiliations, and anomalous connection structure."
        ),
    ),
    RiskDimension(
        key="economic",
        label="Economic",
        description=(
            "Economic/financial facts: flows, positions, exposure, value "
            "normalization, and standing in the economic plane."
        ),
    ),
    RiskDimension(
        key="transaction",
        label="Transaction",
        description=(
            "Individual transactions and their risk-relevant properties — "
            "amount, cadence, counterparty, and anomaly signals."
        ),
    ),
    RiskDimension(
        key="payment",
        label="Payment",
        description=(
            "Payment method/rail risk, reversal and dispute behavior, and authorization outcomes."
        ),
    ),
    RiskDimension(
        key="geographic",
        label="Geographic",
        description=(
            "Location, IP/geo enrichment, and consistency or anomaly of "
            "geographic signals across the subject's activity."
        ),
    ),
    RiskDimension(
        key="temporal",
        label="Temporal",
        description=(
            "Timing, recency, and time-pattern signals — bursts, gaps, "
            "known-then vs known-now alignment."
        ),
    ),
    RiskDimension(
        key="communication",
        label="Communication",
        description=(
            "Communication channels and messaging patterns relevant to "
            "deception/abuse or legitimacy."
        ),
    ),
    RiskDimension(
        key="campaign",
        label="Campaign",
        description=(
            "Marketing/campaign activity — attribution, eligibility, and incentive-abuse exposure."
        ),
    ),
    RiskDimension(
        key="agentic",
        label="Agentic",
        description=(
            "Autonomous agent activity and delegation integrity — what agents "
            "act for, under what authorization."
        ),
    ),
    RiskDimension(
        key="execution",
        label="Execution",
        description=(
            "Execution and fulfillment of promises, orders, and deliveries — "
            "did the subject deliver what was committed."
        ),
    ),
    RiskDimension(
        key="infrastructure",
        label="Infrastructure",
        description=(
            "Device/infrastructure/network fingerprints, hygiene, and proxy/automation indicators."
        ),
    ),
    RiskDimension(
        key="counterparty",
        label="Counterparty",
        description=(
            "Risk posed by the counterparty/peer the subject interacts with, "
            "carried onto the subject's assessment."
        ),
    ),
    RiskDimension(
        key="population",
        label="Population",
        description=(
            "Cohort/population-level context — membership, contagion, and "
            "whether the subject sits inside a suspicious population."
        ),
    ),
    RiskDimension(
        key="operational",
        label="Operational",
        description=(
            "Operational-process health and anomalies that affect or signal risk for the subject."
        ),
    ),
    RiskDimension(
        key="security",
        label="Security",
        description=(
            "Security posture, compromise indicators, and vulnerabilities relevant to the subject."
        ),
    ),
    RiskDimension(
        key="compliance",
        label="Compliance",
        description=("Regulatory/licensing/KYC-style obligation standing for the subject."),
    ),
    RiskDimension(
        key="reputation",
        label="Reputation",
        description=(
            "Reputational standing and trust signals about the subject from "
            "canonical trust/reputation authorities."
        ),
    ),
    RiskDimension(
        key="fraud",
        label="Fraud",
        description=(
            "Deception/abuse indicators about the subject — distinct from the "
            "fraud360 synthesis, which consumes full assessments."
        ),
    ),
    RiskDimension(
        key="exposure",
        label="Exposure",
        description=(
            "What value/assets/outcomes are at stake for the subject and how "
            "much — the quantity side of 'risk of what'."
        ),
    ),
    RiskDimension(
        key="data_quality",
        label="Data quality",
        description=(
            "Quality, completeness, and freshness of the data feeding the "
            "assessment for this dimension."
        ),
    ),
    RiskDimension(
        key="model_uncertainty",
        label="Model uncertainty",
        description=(
            "Uncertainty and confidence limits of the models behind the "
            "assessment — how much the assessment should be trusted."
        ),
    ),
)

# Canonical 24-dimension key set (RISK_FRAUD_360.md §4).
RISK_DIMENSION_KEYS: Final[frozenset[str]] = frozenset(d.key for d in RISK_DIMENSIONS)

_BY_KEY: Final[dict[str, RiskDimension]] = {d.key: d for d in RISK_DIMENSIONS}


def dimension(key: str) -> RiskDimension:
    """Look up a :class:`RiskDimension` row by its canonical ``key``.

    Raises ``KeyError`` for an unregistered key so a misspelled dimension can
    never silently evaluate as an observed zero.
    """
    try:
        return _BY_KEY[key]
    except KeyError:
        raise KeyError(
            f"Unknown risk dimension {key!r}. Registered keys: {sorted(RISK_DIMENSION_KEYS)}"
        ) from None


__all__ = [
    "RiskDimension",
    "RISK_DIMENSIONS",
    "RISK_DIMENSION_KEYS",
    "dimension",
]
