"""
Aether Backend — Attribution Models

Multi-touch attribution modeling for cross-platform reward eligibility.
Supports multiple industry-standard attribution models.

Design:
    - All models implement the ``AttributionModel`` ABC.
    - ``attribute()`` receives an ordered list of ``Touchpoint`` objects and
      returns an ``AttributionResult`` whose weights always sum to 1.0.
    - Models are stateless and side-effect-free — safe to share across
      requests.

Integration:
    Used by ``services.attribution.resolver.AttributionResolver`` which
    collects touchpoints from the user journey, selects a model, and
    returns the attribution result.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import combinations
from typing import Any

from shared.logger.logger import get_logger

logger = get_logger("aether.attribution.models")


# ========================================================================
# DATA MODELS
# ========================================================================

@dataclass
class Touchpoint:
    """A single interaction in a user journey."""

    channel: str
    source: str
    campaign: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    event_type: str = "pageview"
    properties: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "source": self.source,
            "campaign": self.campaign,
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type,
            "properties": self.properties,
        }


@dataclass
class TouchpointCredit:
    """A touchpoint paired with its attributed credit weight."""

    touchpoint: Touchpoint
    weight: float

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.touchpoint.to_dict(),
            "weight": round(self.weight, 6),
        }


@dataclass
class AttributionResult:
    """Complete output of an attribution model run."""

    credits: list[TouchpointCredit]
    model_used: str
    total_credit: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "credits": [c.to_dict() for c in self.credits],
            "model_used": self.model_used,
            "total_credit": round(self.total_credit, 6),
        }


# ========================================================================
# BASE CLASS
# ========================================================================

class AttributionModel(ABC):
    """Base class for all attribution models."""

    name: str

    def _build_result(
        self,
        touchpoints: list[Touchpoint],
        weights: list[float],
    ) -> AttributionResult:
        """Helper to pair touchpoints with weights and normalise."""
        total = sum(weights) or 1.0
        normalised = [w / total for w in weights]
        credits = [
            TouchpointCredit(touchpoint=tp, weight=w)
            for tp, w in zip(touchpoints, normalised)
        ]
        return AttributionResult(
            credits=credits,
            model_used=self.name,
            total_credit=round(sum(normalised), 6),
        )

    @abstractmethod
    async def attribute(self, touchpoints: list[Touchpoint]) -> AttributionResult:
        """Run the attribution model and return weighted credits."""
        ...


# ========================================================================
# CONCRETE MODELS
# ========================================================================

class FirstTouchModel(AttributionModel):
    """100 % credit to the first touchpoint in the journey."""

    name = "first_touch"

    async def attribute(self, touchpoints: list[Touchpoint]) -> AttributionResult:
        weights = [0.0] * len(touchpoints)
        weights[0] = 1.0
        return self._build_result(touchpoints, weights)


class LastTouchModel(AttributionModel):
    """100 % credit to the last touchpoint in the journey."""

    name = "last_touch"

    async def attribute(self, touchpoints: list[Touchpoint]) -> AttributionResult:
        weights = [0.0] * len(touchpoints)
        weights[-1] = 1.0
        return self._build_result(touchpoints, weights)


class LinearModel(AttributionModel):
    """Equal credit distributed across all touchpoints."""

    name = "linear"

    async def attribute(self, touchpoints: list[Touchpoint]) -> AttributionResult:
        n = len(touchpoints)
        weights = [1.0 / n] * n
        return self._build_result(touchpoints, weights)


class TimeDecayModel(AttributionModel):
    """
    Exponential decay favouring more-recent touchpoints.

    The weight of a touchpoint is ``2^(-t / half_life)`` where *t* is the
    time elapsed between that touchpoint and the last touchpoint.
    """

    name = "time_decay"

    def __init__(self, half_life_hours: float = 168.0) -> None:
        self.half_life_hours = half_life_hours

    async def attribute(self, touchpoints: list[Touchpoint]) -> AttributionResult:
        last_ts = touchpoints[-1].timestamp
        weights: list[float] = []
        for tp in touchpoints:
            hours_before = max(
                (last_ts - tp.timestamp).total_seconds() / 3600.0,
                0.0,
            )
            weights.append(math.pow(2.0, -hours_before / self.half_life_hours))
        return self._build_result(touchpoints, weights)


class PositionBasedModel(AttributionModel):
    """
    U-shaped (position-based) attribution:
    40 % to the first touchpoint, 40 % to the last, and 20 % split
    equally among the middle touchpoints.
    """

    name = "position_based"

    def __init__(
        self,
        first_weight: float = 0.40,
        last_weight: float = 0.40,
    ) -> None:
        self.first_weight = first_weight
        self.last_weight = last_weight

    async def attribute(self, touchpoints: list[Touchpoint]) -> AttributionResult:
        n = len(touchpoints)
        if n == 1:
            return self._build_result(touchpoints, [1.0])
        if n == 2:
            return self._build_result(touchpoints, [self.first_weight, self.last_weight])

        middle_total = 1.0 - self.first_weight - self.last_weight
        middle_each = middle_total / (n - 2)
        weights = [self.first_weight] + [middle_each] * (n - 2) + [self.last_weight]
        return self._build_result(touchpoints, weights)


class DataDrivenModel(AttributionModel):
    """
    Shapley-value approximation using marginal contribution analysis.

    For each touchpoint, estimates its marginal contribution by comparing
    conversion probability with and without that touchpoint across all
    possible coalitions (capped for performance).

    Note:
        In production this would use historical conversion data.  This
        implementation uses a heuristic conversion-probability function
        that considers coalition size and channel diversity.
    """

    name = "data_driven"

    def __init__(self, max_coalition_size: int = 10) -> None:
        self.max_coalition_size = max_coalition_size

    async def attribute(self, touchpoints: list[Touchpoint]) -> AttributionResult:
        n = len(touchpoints)
        if n == 1:
            return self._build_result(touchpoints, [1.0])

        # Limit combinatorial explosion for large journeys
        effective = touchpoints[-self.max_coalition_size:] if n > self.max_coalition_size else touchpoints

        shapley_values = self._compute_shapley(effective)
        return self._build_result(effective, shapley_values)

    # -- private ----------------------------------------------------------

    def _compute_shapley(self, touchpoints: list[Touchpoint]) -> list[float]:
        """Approximate Shapley values via marginal contributions."""
        n = len(touchpoints)
        values = [0.0] * n
        indices = list(range(n))

        for i in indices:
            marginal_sum = 0.0
            coalition_count = 0
            # Iterate over all subsets that do NOT include i
            for size in range(0, n):
                for subset in combinations([j for j in indices if j != i], size):
                    v_without = self._coalition_value(touchpoints, list(subset))
                    v_with = self._coalition_value(touchpoints, list(subset) + [i])
                    marginal_sum += v_with - v_without
                    coalition_count += 1

            values[i] = marginal_sum / max(coalition_count, 1)

        return values

    @staticmethod
    def _coalition_value(touchpoints: list[Touchpoint], indices: list[int]) -> float:
        """
        Heuristic conversion probability for a coalition of touchpoints.

        Factors in coalition size (more touches = higher probability) and
        channel diversity (more unique channels = higher value).
        """
        if not indices:
            return 0.0
        channels = {touchpoints[i].channel for i in indices}
        size_factor = 1.0 - math.exp(-0.5 * len(indices))
        diversity_factor = len(channels) / max(len(indices), 1)
        return size_factor * (0.6 + 0.4 * diversity_factor)


# ========================================================================
# PROFILE 360 — ACTOR-WEIGHTED + EXPOSURE-AWARE MODELS (additive)
# ========================================================================
#
# These two models extend the existing registry to support the Profile 360
# spec: human-vs-agent credit splitting and impression-aware credit when
# touchpoints carry exposure metadata in their `properties` block.
#
# Hints read from Touchpoint.properties:
#   - actor_type: "human" | "agent"        (ActorWeightedModel)
#   - is_impression: bool                  (ExposureAwareModel)
#   - viewable_dwell_ms: int               (ExposureAwareModel)
# Touchpoints lacking these hints fall back to the model's default behavior.

class ActorWeightedModel(AttributionModel):
    """U-shaped distribution that further splits each touchpoint's weight
    between human and agent actors.

    A touchpoint with `properties.actor_type == "agent"` is multiplied by
    `agent_weight`; "human" is multiplied by `human_weight`. Weights are
    re-normalized at the end so the result still sums to 1.0.
    """

    name = "actor_weighted"

    def __init__(
        self,
        human_weight: float = 0.7,
        agent_weight: float = 0.3,
        first_weight: float = 0.40,
        last_weight: float = 0.40,
    ) -> None:
        self.human_weight = human_weight
        self.agent_weight = agent_weight
        self.first_weight = first_weight
        self.last_weight = last_weight

    def _actor_factor(self, tp: Touchpoint) -> float:
        actor_type = (tp.properties or {}).get("actor_type")
        if actor_type == "agent":
            return self.agent_weight
        if actor_type == "human":
            return self.human_weight
        return 1.0  # unknown actor — neutral

    async def attribute(self, touchpoints: list[Touchpoint]) -> AttributionResult:
        n = len(touchpoints)
        if n == 1:
            base = [1.0]
        elif n == 2:
            base = [self.first_weight, self.last_weight]
        else:
            middle_total = 1.0 - self.first_weight - self.last_weight
            middle_each = middle_total / (n - 2)
            base = [self.first_weight] + [middle_each] * (n - 2) + [self.last_weight]
        weighted = [b * self._actor_factor(tp) for b, tp in zip(base, touchpoints)]
        return self._build_result(touchpoints, weighted)


class ExposureAwareModel(AttributionModel):
    """U-shaped attribution that includes viewable impressions alongside clicks.

    Impressions (touchpoints with `is_impression=True`) only contribute when
    `viewable_dwell_ms >= dwell_threshold_ms`. Eligible impressions get
    `impression_weight` of a click's credit; clicks keep their full weight.
    """

    name = "exposure_aware"

    def __init__(
        self,
        first_weight: float = 0.40,
        last_weight: float = 0.40,
        impression_weight: float = 0.5,
        dwell_threshold_ms: int = 1000,
    ) -> None:
        self.first_weight = first_weight
        self.last_weight = last_weight
        self.impression_weight = impression_weight
        self.dwell_threshold_ms = dwell_threshold_ms

    def _eligible(self, tp: Touchpoint) -> bool:
        props = tp.properties or {}
        if not props.get("is_impression"):
            return True  # clicks always eligible
        return int(props.get("viewable_dwell_ms", 0)) >= self.dwell_threshold_ms

    def _impression_multiplier(self, tp: Touchpoint) -> float:
        if (tp.properties or {}).get("is_impression"):
            return self.impression_weight
        return 1.0

    async def attribute(self, touchpoints: list[Touchpoint]) -> AttributionResult:
        eligible = [tp for tp in touchpoints if self._eligible(tp)]
        if not eligible:
            return await LastTouchModel().attribute(touchpoints)

        n = len(eligible)
        if n == 1:
            base = [1.0]
        elif n == 2:
            base = [self.first_weight, self.last_weight]
        else:
            middle_total = 1.0 - self.first_weight - self.last_weight
            middle_each = middle_total / (n - 2)
            base = [self.first_weight] + [middle_each] * (n - 2) + [self.last_weight]
        weighted = [b * self._impression_multiplier(tp) for b, tp in zip(base, eligible)]
        return self._build_result(eligible, weighted)
