"""Risk360 risk-policy registry — declarative typed registry (Phase 5).

There is NO policy registry or storage in the tree; the canonical
:class:`shared.computation.policies.DecisionPolicy` is the decision core and
this module is the Risk360 **risk policy registry** that references it by its
id fields only. Each :class:`RiskPolicy` is one frozen row of the registry:

* ``policy_id`` / ``policy_version`` — the canonical ``DecisionPolicy`` ids this
  row projects through;
* ``dimension_weights`` — positive weights over the registered Risk360
  dimensions (``RISK_DIMENSION_KEYS``) used to aggregate a per-dimension
  :class:`~services.risk360.contracts.RiskVector` into one 0–1 aggregate score.
  Weights are **not** thresholds; a dimension that has no value-bearing
  component simply contributes nothing to the aggregate (it is never coerced to
  a fabricated zero contribution).
* ``policy`` — the canonical aggregate ``DecisionPolicy`` whose threshold bands
  map the 0–1 aggregate risk score to a ``PolicyOutcome``.

Thresholds live ONLY here (in the ``DecisionPolicy`` rows) — never as module
constants in the pipeline. There is no universal meaning for an overall risk
score, so the same ``RiskVector`` projects differently under different risk
policies (payment_authorization vs promotion_eligibility vs agent_execution);
the registry is seeded with one default ``risk360.standard`` row.

Registry style mirrors :mod:`services.risk360.dimensions` exactly: frozen
dataclass rows + module-level seed + a lookup that raises ``KeyError`` listing
the registered ids — a misspelled policy id can never silently evaluate.
"""

from __future__ import annotations

from typing import Final, Mapping, Optional

from shared.computation.policies import (
    DecisionPolicy,
    DecisionThreshold,
    PolicyOutcome,
)
from shared.measurement.value_states import requires_value

from .contracts import RiskVector
from .dimensions import RISK_DIMENSION_KEYS

DEFAULT_POLICY_ID: Final[str] = "risk360.standard"


class RiskPolicyRow:
    """Marker base kept for symmetry with dimension rows (unused today)."""


# We need a frozen dataclass row that also validates in __post_init__.
from dataclasses import dataclass  # noqa: E402  (kept local for readability)


@dataclass(frozen=True)
class RiskPolicy:
    """One frozen row of the risk policy registry.

    ``dimension_weights`` keys must be registered Risk360 dimensions
    (``RISK_DIMENSION_KEYS``) and every weight must be strictly positive.
    ``policy`` is the canonical aggregate ``DecisionPolicy`` whose ``decide``
    maps the 0–1 aggregate score to a ``PolicyOutcome``. An aggregate over no
    value-bearing dimensions is ``None`` and fails closed to the policy's
    configured default (REVIEW when ``fail_closed``), never a made-up number.
    """

    policy_id: str
    policy_version: str
    display_name: str
    #: Positive weights over registered risk dimensions. Missing dimensions
    #: contribute nothing to the aggregate (never a fabricated zero).
    dimension_weights: Mapping[str, float]
    #: Canonical aggregate decision policy (thresholds live here, only here).
    policy: DecisionPolicy

    def __post_init__(self) -> None:
        unregistered = sorted(set(self.dimension_weights) - set(RISK_DIMENSION_KEYS))
        if unregistered:
            raise ValueError(
                f"policy {self.policy_id!r} weights reference unregistered risk "
                f"dimensions {unregistered} — weights keys must be ⊆ "
                f"RISK_DIMENSION_KEYS"
            )
        non_positive = sorted(
            {d for d, w in self.dimension_weights.items() if w <= 0}
        )
        if non_positive:
            raise ValueError(
                f"policy {self.policy_id!r} weights must be positive; "
                f"non-positive: {non_positive}"
            )

    def aggregate_score(self, vector: RiskVector) -> Optional[float]:
        """Aggregate value-bearing components into one 0–1 score, or None.

        A dimension with no value-bearing (``observed``/``estimated``) component
        contributes **nothing** — it is never coerced to a zero that would drag
        the aggregate toward ALLOW. When no dimension contributes a score the
        aggregate is ``None`` and ``decide(None)`` fails closed.
        """
        scores: dict[str, float] = {}
        for component in vector.components:
            if not requires_value(component.state) or component.score is None:
                continue
            scores[component.dimension] = component.score
        return weighted_aggregate_score(self.dimension_weights, scores)

    def decide(self, vector: RiskVector) -> tuple[Optional[float], PolicyOutcome]:
        """Project ``vector`` through this policy: ``(aggregate, outcome)``."""
        aggregate = self.aggregate_score(vector)
        return aggregate, self.policy.decide(aggregate)


def weighted_aggregate_score(
    weights: Mapping[str, float],
    scores: Mapping[str, float],
) -> Optional[float]:
    """Weight-normalized aggregate over the *scored* dimensions only.

    ``scores`` maps a risk dimension to its 0–1 score. Dimensions absent from
    ``scores`` (no value-bearing component) contribute nothing to either the
    numerator or the denominator — an unobserved dimension never drags the
    aggregate toward ``0``. Returns ``None`` when no scored dimension has a
    weight, so the caller can fail closed instead of inventing a number.
    """
    numerator = 0.0
    denominator = 0.0
    for dimension, weight in weights.items():
        score = scores.get(dimension)
        if score is None:
            continue
        numerator += weight * float(score)
        denominator += weight
    if denominator <= 0:
        return None
    aggregate = numerator / denominator
    if aggregate < 0.0:
        return 0.0
    if aggregate > 1.0:
        return 1.0
    return aggregate


# ── Registry seed (typed rows, per the Risk360/Fraud360 scoping decision) ──

# Threshold bands for the default standard policy. An aggregate below the ALLOW
# upper bound is ALLOW; REVIEW in the middle band; BLOCK at/above the lower
# bound of the last band. ``None`` (no scored dimension) fails closed to REVIEW.
_STANDARD_THRESHOLDS: Final[tuple[DecisionThreshold, ...]] = (
    DecisionThreshold(upper=0.25, outcome=PolicyOutcome.ALLOW),
    DecisionThreshold(lower=0.25, upper=0.65, outcome=PolicyOutcome.REVIEW),
    DecisionThreshold(lower=0.65, outcome=PolicyOutcome.BLOCK),
)

_DEFAULT_POLICY = DecisionPolicy(
    policy_id=DEFAULT_POLICY_ID,
    policy_version="1",
    display_name="Risk360 standard assessment policy",
    thresholds=list(_STANDARD_THRESHOLDS),
    default_outcome=PolicyOutcome.REVIEW,
    owner="risk",
    fail_closed=True,
)

# Weights favor the high-severity fraud/identity/payment dimensions but keep
# every registered dimension positively weighted; a dimension only enters the
# aggregate when it actually carries a value-bearing component.
_STANDARD_WEIGHTS: Final[Mapping[str, float]] = {
    "identity": 2.0,
    "authentication": 2.0,
    "fraud": 2.0,
    "economic": 1.5,
    "payment": 1.5,
    "transaction": 1.5,
    "behavioral": 1.2,
    "relationship": 1.2,
    "security": 1.1,
    "infrastructure": 1.0,
    "geographic": 1.0,
    "temporal": 1.0,
    "communication": 1.0,
    "campaign": 1.0,
    "agentic": 1.0,
    "execution": 1.0,
    "counterparty": 1.0,
    "population": 1.0,
    "operational": 1.0,
    "compliance": 1.0,
    "reputation": 1.0,
    "exposure": 0.5,
    "data_quality": 0.5,
    "model_uncertainty": 0.5,
}


#: Seeded registry rows in declaration order.
RISK_POLICIES: Final[tuple[RiskPolicy, ...]] = (
    RiskPolicy(
        policy_id=DEFAULT_POLICY_ID,
        policy_version="1",
        display_name="Risk360 standard assessment policy",
        dimension_weights=_STANDARD_WEIGHTS,
        policy=_DEFAULT_POLICY,
    ),
)

#: Canonical registered policy-id set.
RISK_POLICY_IDS: Final[frozenset[str]] = frozenset(p.policy_id for p in RISK_POLICIES)

_BY_ID: Final[dict[str, RiskPolicy]] = {p.policy_id: p for p in RISK_POLICIES}


def policy(policy_id: str) -> RiskPolicy:
    """Look up a :class:`RiskPolicy` row by its canonical ``policy_id``.

    Raises ``KeyError`` listing the registered ids for an unknown policy id so a
    misspelled policy can never silently project as the default.
    """
    try:
        return _BY_ID[policy_id]
    except KeyError:
        raise KeyError(
            f"Unknown risk policy {policy_id!r}. Registered policy ids: "
            f"{sorted(RISK_POLICY_IDS)}"
        ) from None


__all__ = [
    "DEFAULT_POLICY_ID",
    "RISK_POLICIES",
    "RISK_POLICY_IDS",
    "RiskPolicy",
    "policy",
    "weighted_aggregate_score",
]
