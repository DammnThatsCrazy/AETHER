"""
Aether Shared — Governed Trust Vector

This module turns the single composite trust scalar into a governed,
multi-dimension VECTOR. It exists so that:

  1. Trust is expressed as named, independently interpretable dimensions —
     each carrying its OWN evidence coverage — instead of one opaque scalar.
  2. The weights that fold dimensions into a composite are VERSIONED
     (``WEIGHTS_VERSION``), so any change to weights or thresholds is
     traceable in the output.
  3. Different decisions get DIFFERENT composites. A single universal
     composite silently applies one policy to every question. Instead we
     expose several named, separately-weighted derivations (base,
     reward-eligibility, agent-delegation, ...), each documenting which
     dimensions it trusts and how much.

Nothing here is a new ML model. Dimensions are derived from the same existing
model outputs the composite already consumed; this module only governs how
they are named, disclosed, and combined.

Orientation convention
-----------------------
Every dimension ``value`` is stored in its NATURAL orientation on [0, 1]:

  * identity_assurance      higher = identity is more assured        (trust +)
  * transaction_integrity   higher = transactions are cleaner        (trust +)
  * behavioral_reliability  higher = behavior is more reliable       (trust +)
  * automation_likelihood   higher = MORE likely automated/bot       (trust -)
  * source_coverage         higher = more evidence sources present   (trust +)
  * evidence_recency        higher = evidence is fresher             (trust +)

``automation_likelihood`` is the one trust-INVERTED dimension: a composite
that penalizes automation consumes ``(1 - value)``. Which composites do that
is a per-use-case policy choice, not a global one — an agent-delegation
composite deliberately does NOT penalize automation, because being automated
is expected of an agent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

# ═══════════════════════════════════════════════════════════════════════════
# VERSIONING
# ═══════════════════════════════════════════════════════════════════════════

# Bump this whenever ANY weight map or threshold in this module changes, so the
# provenance of a produced score/vector is traceable. It is stamped onto every
# TrustScore / TrustVector output.
WEIGHTS_VERSION = "2026.08.0"


# ═══════════════════════════════════════════════════════════════════════════
# DIMENSIONS
# ═══════════════════════════════════════════════════════════════════════════

# Canonical, ordered dimension names. Order is stable for serialization.
TRUST_DIMENSIONS: tuple[str, ...] = (
    "identity_assurance",
    "transaction_integrity",
    "behavioral_reliability",
    "automation_likelihood",
    "source_coverage",
    "evidence_recency",
)

# Dimensions whose natural orientation is trust-NEGATIVE. A composite that
# wants a trust-positive contribution from these must use ``(1 - value)``.
INVERTED_DIMENSIONS: frozenset[str] = frozenset({"automation_likelihood"})

# Coverage vocabulary for a single dimension's backing evidence.
COVERAGE_COMPLETE = "complete"
COVERAGE_PARTIAL = "partial"
COVERAGE_MISSING = "missing"

# Priors used when a dimension has NO backing evidence. Absence is never read
# as a trust-positive: automation is treated as genuinely unknown (0.5), and
# recency is treated as stale/low, mirroring ``ABSENT_EVIDENCE_PRIOR``.
ABSENT_AUTOMATION_PRIOR = 0.5
ABSENT_RECENCY_PRIOR = 0.1

# Linear-decay window for turning an evidence age (days) into a recency score.
RECENCY_WINDOW_DAYS = 30.0


def recency_from_age_days(age_days: float, window_days: float = RECENCY_WINDOW_DAYS) -> float:
    """Map an evidence age in days to a [0, 1] recency score (1 = fresh)."""
    if window_days <= 0:
        return 0.0
    return max(0.0, min(1.0, 1.0 - (age_days / window_days)))


@dataclass(frozen=True)
class TrustDimension:
    """One named trust axis with its own value and evidence coverage."""

    name: str
    value: float               # 0.0 – 1.0, in the dimension's natural orientation
    coverage: str = COVERAGE_MISSING  # complete | partial | missing
    observed: bool = False     # True when backed by at least one real signal

    def to_dict(self) -> dict:
        return {
            "value": round(self.value, 4),
            "coverage": self.coverage,
            "observed": self.observed,
            "inverted": self.name in INVERTED_DIMENSIONS,
        }


# ═══════════════════════════════════════════════════════════════════════════
# USE-CASE COMPOSITE WEIGHTINGS  (each is a distinct, documented policy)
# ═══════════════════════════════════════════════════════════════════════════

# Base composite — backward-compatible with the legacy scalar. It intentionally
# uses ONLY the three legacy axes so the historical composite value is exactly
# reproduced, now derived from the vector instead of ad-hoc arithmetic.
BASE_COMPOSITE_WEIGHTS: dict[str, float] = {
    "transaction_integrity": 0.40,
    "identity_assurance": 0.35,
    "behavioral_reliability": 0.25,
}

# Reward eligibility — humans earning rewards. Identity assurance and clean
# transactions dominate, automation is PENALIZED (bots farming rewards), and
# stale/thin evidence is discounted via coverage + recency.
REWARD_ELIGIBILITY_WEIGHTS: dict[str, float] = {
    "identity_assurance": 0.30,
    "transaction_integrity": 0.25,
    "automation_likelihood": 0.20,   # inverted -> penalizes bots
    "behavioral_reliability": 0.10,
    "source_coverage": 0.10,
    "evidence_recency": 0.05,
}

# Agent delegation — granting an agent authority to act. Automation is EXPECTED
# (weight 0, not penalized); what matters is transactional integrity, reliable
# behavior, breadth of corroborating sources, and freshness of that evidence.
AGENT_DELEGATION_WEIGHTS: dict[str, float] = {
    "transaction_integrity": 0.30,
    "behavioral_reliability": 0.25,
    "identity_assurance": 0.15,
    "source_coverage": 0.15,
    "evidence_recency": 0.15,
    # automation_likelihood deliberately omitted (weight 0.0).
}

# Registry of named composites -> weight map, for traceability/governance.
COMPOSITE_WEIGHTINGS: dict[str, dict[str, float]] = {
    "trust.composite": BASE_COMPOSITE_WEIGHTS,
    "reward_eligibility_trust": REWARD_ELIGIBILITY_WEIGHTS,
    "agent_delegation_trust": AGENT_DELEGATION_WEIGHTS,
}


# ═══════════════════════════════════════════════════════════════════════════
# TRUST VECTOR
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class TrustVector:
    """A governed multi-dimension trust vector.

    Holds one :class:`TrustDimension` per canonical axis. Composites are
    DERIVED from these dimensions via named, versioned weight maps — the
    scalar is a view over the vector, never an independent number.
    """

    identity_assurance: TrustDimension
    transaction_integrity: TrustDimension
    behavioral_reliability: TrustDimension
    automation_likelihood: TrustDimension
    source_coverage: TrustDimension
    evidence_recency: TrustDimension
    weights_version: str = WEIGHTS_VERSION

    def dimensions(self) -> dict[str, TrustDimension]:
        return {name: getattr(self, name) for name in TRUST_DIMENSIONS}

    def _contribution(self, name: str) -> float:
        dim = getattr(self, name)
        return (1.0 - dim.value) if name in INVERTED_DIMENSIONS else dim.value

    def composite(self, weights: Mapping[str, float]) -> float:
        """Fold the vector into a single [0, 1] scalar under ``weights``.

        Weights are normalized so the result stays in [0, 1] regardless of how
        the map is authored (only the listed dimensions contribute).
        """
        total_w = sum(weights.values())
        if total_w <= 0:
            return 0.0
        acc = sum(w * self._contribution(name) for name, w in weights.items())
        return max(0.0, min(1.0, acc / total_w))

    def composite_coverage(self, weights: Mapping[str, float]) -> float:
        """Fraction of a composite's weight that is backed by observed evidence.

        This is the composite-level evidence disclosure: a high-looking score
        drawn mostly from unobserved priors is surfaced as low coverage.
        """
        total_w = sum(weights.values())
        if total_w <= 0:
            return 0.0
        observed_w = sum(
            w for name, w in weights.items() if getattr(self, name).observed
        )
        return round(observed_w / total_w, 4)

    def named_composite(self, name: str) -> dict:
        """Compute a registered composite by name, with its coverage."""
        weights = COMPOSITE_WEIGHTINGS[name]
        return {
            "value": round(self.composite(weights), 4),
            "evidence_backed_weight": self.composite_coverage(weights),
            "weights": dict(weights),
        }

    def to_dict(self) -> dict:
        return {
            "weights_version": self.weights_version,
            "dimensions": {
                name: dim.to_dict() for name, dim in self.dimensions().items()
            },
            "inverted_dimensions": sorted(INVERTED_DIMENSIONS),
        }


# ═══════════════════════════════════════════════════════════════════════════
# NAMED USE-CASE COMPOSITES  (separately-named derivations, distinct weights)
# ═══════════════════════════════════════════════════════════════════════════

def base_composite(vector: TrustVector) -> float:
    """Legacy-compatible composite (3 axes). Derived from the vector."""
    return vector.composite(BASE_COMPOSITE_WEIGHTS)


def reward_eligibility_trust(vector: TrustVector) -> float:
    """Trust for reward eligibility — penalizes automation, values identity."""
    return vector.composite(REWARD_ELIGIBILITY_WEIGHTS)


def agent_delegation_trust(vector: TrustVector) -> float:
    """Trust for delegating authority to an agent — automation not penalized."""
    return vector.composite(AGENT_DELEGATION_WEIGHTS)


def use_case_composites(vector: TrustVector) -> dict:
    """All non-base named composites with values + evidence-backed coverage."""
    return {
        "reward_eligibility_trust": vector.named_composite("reward_eligibility_trust"),
        "agent_delegation_trust": vector.named_composite("agent_delegation_trust"),
    }
