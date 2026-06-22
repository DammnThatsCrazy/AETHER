"""Algorithmic attribution models — Markov chain removal-effect model.

The MarkovAttributionModel trains on historical journey data from
silver_campaign_touchpoint_facts. It uses removal-effect attribution:
for each channel C, compare conversion probability with all channels
vs. conversion probability without C. The removal effect is the credit
assigned to C.

Minimum data gate: if fewer than 1000 converting journeys are available,
the model falls back to PositionBasedModel and logs the reason. This
prevents garbage-in-garbage-out attribution on sparse datasets.

The existing DataDrivenModel (Shapley heuristic) is aliased here as
``shapley_heuristic`` for backwards compatibility while exposing its true
nature to callers who request by name.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Optional

from services.attribution.models import (
    AttributionModel,
    AttributionResult,
    PositionBasedModel,
    Touchpoint,
)

logger = logging.getLogger("aether.measurement.algorithmic_attribution")

_MIN_CONVERTING_JOURNEYS = 1000
_ABSORBING_CONVERTED = "__converted__"
_ABSORBING_NULL = "__null__"
_START_STATE = "__start__"


class MarkovAttributionModel(AttributionModel):
    """Markov-chain removal-effect attribution.

    Training:
      - Accepts journey path lists: sequences of channel names ending in
        either ``__converted__`` or ``__null__`` (non-converting).
      - Builds a transition matrix from observed state transitions.
      - Computes steady-state conversion probability from the full matrix.
      - For each channel C, removes C from the matrix (routes its outbound
        transitions to null) and recomputes conversion probability.
      - Removal effect = base_prob - prob_without_C.
      - Weights are normalized so sum = 1.0.

    At inference time (``attribute()``):
      - Uses the trained removal effects as per-channel credit weights.
      - Channels not seen during training get weight 0 (absorbed by
        ``unattributed_credit``).
      - Falls back to PositionBasedModel if not trained or insufficient data.
    """

    name = "markov"

    def __init__(self) -> None:
        self._trained = False
        self._removal_effects: dict[str, float] = {}
        self._training_journey_count = 0
        self._fallback = PositionBasedModel()

    # ── Training API ────────────────────────────────────────────────────────

    def train(
        self,
        converting_journeys: list[list[str]],
        null_journeys: list[list[str]],
    ) -> None:
        """Train the Markov model on journey path data.

        Args:
            converting_journeys: Lists of channel sequences that ended in conversion.
            null_journeys: Lists of channel sequences that did NOT convert.
        """
        n_converting = len(converting_journeys)
        if n_converting < _MIN_CONVERTING_JOURNEYS:
            logger.warning(
                "MarkovAttributionModel: insufficient data for training "
                "(converting_journeys=%d < threshold=%d). "
                "Model will fall back to position_based at inference time.",
                n_converting, _MIN_CONVERTING_JOURNEYS,
            )
            self._trained = False
            return

        transition_counts = self._build_transition_counts(
            converting_journeys, null_journeys,
        )
        transition_matrix = self._normalize_transitions(transition_counts)
        base_prob = self._conversion_probability(transition_matrix)

        removal_effects: dict[str, float] = {}
        all_channels = {
            state for state in transition_matrix
            if state not in (_START_STATE, _ABSORBING_CONVERTED, _ABSORBING_NULL)
        }

        for channel in all_channels:
            reduced = self._remove_channel(transition_matrix, channel)
            prob_without = self._conversion_probability(reduced)
            removal_effects[channel] = max(0.0, base_prob - prob_without)

        total = sum(removal_effects.values())
        if total > 0:
            self._removal_effects = {ch: v / total for ch, v in removal_effects.items()}
        else:
            self._removal_effects = {ch: 1.0 / len(all_channels) for ch in all_channels} if all_channels else {}

        self._trained = True
        self._training_journey_count = n_converting
        logger.info(
            "MarkovAttributionModel trained: channels=%d converting_journeys=%d base_conversion_prob=%.4f",
            len(all_channels), n_converting, base_prob,
        )

    # ── Inference API ───────────────────────────────────────────────────────

    async def attribute(self, touchpoints: list[Touchpoint]) -> AttributionResult:
        if not self._trained:
            logger.debug(
                "MarkovAttributionModel not trained — falling back to position_based"
            )
            return await self._fallback.attribute(touchpoints)

        if not touchpoints:
            return AttributionResult(touchpoints=[], credits={}, model=self.name)

        channel_weights: dict[int, float] = {}
        unmatched: list[int] = []

        for i, tp in enumerate(touchpoints):
            weight = self._removal_effects.get(tp.channel)
            if weight is not None:
                channel_weights[i] = weight
            else:
                unmatched.append(i)

        if not channel_weights:
            # None of the observed channels have training data — fall back
            return await self._fallback.attribute(touchpoints)

        total = sum(channel_weights.values())
        if total == 0:
            return await self._fallback.attribute(touchpoints)

        weights = [channel_weights.get(i, 0.0) / total for i in range(len(touchpoints))]
        return self._build_result(touchpoints, weights)

    # ── Internal helpers ────────────────────────────────────────────────────

    @staticmethod
    def _build_transition_counts(
        converting: list[list[str]],
        null: list[list[str]],
    ) -> dict[str, dict[str, float]]:
        counts: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

        for journey in converting:
            path = [_START_STATE] + journey + [_ABSORBING_CONVERTED]
            for from_state, to_state in zip(path, path[1:]):
                counts[from_state][to_state] += 1.0

        for journey in null:
            path = [_START_STATE] + journey + [_ABSORBING_NULL]
            for from_state, to_state in zip(path, path[1:]):
                counts[from_state][to_state] += 1.0

        return dict(counts)

    @staticmethod
    def _normalize_transitions(
        counts: dict[str, dict[str, float]],
    ) -> dict[str, dict[str, float]]:
        matrix: dict[str, dict[str, float]] = {}
        for state, targets in counts.items():
            total = sum(targets.values())
            if total > 0:
                matrix[state] = {t: v / total for t, v in targets.items()}
            else:
                matrix[state] = dict(targets)
        return matrix

    @staticmethod
    def _remove_channel(
        matrix: dict[str, dict[str, float]],
        channel: str,
    ) -> dict[str, dict[str, float]]:
        """Return a copy of the matrix with `channel` absorbed into null."""
        reduced: dict[str, dict[str, float]] = {}
        for state, targets in matrix.items():
            if state == channel:
                # This state's outbound transitions all go to null
                reduced[state] = {_ABSORBING_NULL: 1.0}
            else:
                new_targets: dict[str, float] = {}
                null_extra = 0.0
                for t, prob in targets.items():
                    if t == channel:
                        null_extra += prob
                    else:
                        new_targets[t] = prob
                if null_extra > 0:
                    new_targets[_ABSORBING_NULL] = new_targets.get(_ABSORBING_NULL, 0.0) + null_extra
                reduced[state] = new_targets
        return reduced

    @staticmethod
    def _conversion_probability(matrix: dict[str, dict[str, float]]) -> float:
        """Estimate conversion probability via Monte Carlo simulation (1000 paths)."""
        if _START_STATE not in matrix:
            return 0.0

        import random
        rng = random.Random(42)  # deterministic for reproducibility
        n_simulations = 1000
        converted = 0

        for _ in range(n_simulations):
            state = _START_STATE
            steps = 0
            while state not in (_ABSORBING_CONVERTED, _ABSORBING_NULL) and steps < 50:
                targets = matrix.get(state)
                if not targets:
                    break
                states = list(targets.keys())
                probs = list(targets.values())
                total = sum(probs)
                if total <= 0:
                    break
                r = rng.random() * total
                cumulative = 0.0
                for s, p in zip(states, probs):
                    cumulative += p
                    if r <= cumulative:
                        state = s
                        break
                else:
                    state = states[-1]
                steps += 1
            if state == _ABSORBING_CONVERTED:
                converted += 1

        return converted / n_simulations


# ── Alias for backwards compatibility ─────────────────────────────────────────

class ShapleyHeuristicModel(AttributionModel):
    """Renamed alias for the existing DataDrivenModel.

    Exposes the model under the honest name ``shapley_heuristic`` while the
    legacy name ``data_driven`` remains registered via DataDrivenModel for
    backwards compatibility.
    """

    name = "shapley_heuristic"

    def __init__(self) -> None:
        from services.attribution.models import DataDrivenModel
        self._inner = DataDrivenModel()

    async def attribute(self, touchpoints: list[Touchpoint]) -> AttributionResult:
        result = await self._inner.attribute(touchpoints)
        # Re-stamp the model name so credits reference the honest name
        result = AttributionResult(
            touchpoints=result.touchpoints,
            credits={k: v for k, v in result.credits.items()},
            model=self.name,
        )
        return result


# ── Register in AttributionResolver ───────────────────────────────────────────

def register_algorithmic_models(resolver: Any) -> None:
    """Register MarkovAttributionModel and ShapleyHeuristicModel with a resolver."""
    resolver._models["markov"] = MarkovAttributionModel()
    resolver._models["shapley_heuristic"] = ShapleyHeuristicModel()
    logger.info("Algorithmic attribution models registered: markov, shapley_heuristic")
