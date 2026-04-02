"""
Aether Agent Layer — Stopping Policy
Defines when LOOP and controllers should stop, sleep, or pause.
Implements the required stopping rules for the agent layer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from agent_controller.runtime.loop_runtime import LoopState, StopReason

logger = logging.getLogger("aether.planning.stopping")


@dataclass
class StoppingConfig:
    max_budget_usd: float = 50.0
    max_actions_per_cycle: int = 100
    max_consecutive_no_ops: int = 5
    max_conflict_attempts: int = 3
    min_marginal_value: float = 0.05
    max_stale_seconds: float = 3600.0


class StoppingPolicy:
    """
    Evaluates whether LOOP or a controller should stop.
    Can be used as a LOOP stop hook or called directly by controllers.
    """

    def __init__(self, config: StoppingConfig | None = None):
        self.config = config or StoppingConfig()
        self._marginal_values: list[float] = []

    def evaluate(self, state: LoopState) -> Optional[StopReason]:
        """
        Check all stopping conditions. Returns a StopReason if the loop
        should stop, or None if it should continue.
        """
        if state.budget_spent >= self.config.max_budget_usd:
            return StopReason.BUDGET_CEILING

        if state.total_actions_taken >= self.config.max_actions_per_cycle:
            return StopReason.POLICY_CEILING

        if state.consecutive_no_ops >= self.config.max_consecutive_no_ops:
            return StopReason.NO_PRODUCTIVE_ACTION

        if state.conflict_attempts >= self.config.max_conflict_attempts:
            return StopReason.UNRESOLVED_CONFLICT

        if self._is_diminishing():
            return StopReason.DIMINISHING_VALUE

        return None

    def record_value(self, value: float) -> None:
        """Record the marginal value of the last action for trend analysis."""
        self._marginal_values.append(value)

    def _is_diminishing(self) -> bool:
        """Check if recent actions are yielding diminishing returns."""
        if len(self._marginal_values) < 5:
            return False
        recent = self._marginal_values[-5:]
        return all(v < self.config.min_marginal_value for v in recent)

    def as_loop_hook(self):
        """Return this policy as a LOOP stop hook function."""
        return self.evaluate
