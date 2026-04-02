"""
Aether Agent Layer — LOOP Runtime
LOOP is NOT a controller. LOOP is a runtime behavior shared across KIRA
and domain controllers.

LOOP is aggressive from day one — it continues existing objectives, reopens
unresolved ones, creates low-risk maintenance objectives when policy allows,
revisits stale graph areas, and sleeps only when no productive next action exists.

LOOP stopping rules:
- policy ceiling reached
- budget ceiling reached
- waiting for human approval is the correct next step
- unresolved conflict after allowed attempts
- no productive next action exists
- success criteria reached
- diminishing value / low marginal information gain
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger("aether.runtime.loop")


class LoopAction(str, Enum):
    CONTINUE = "continue"
    REOPEN = "reopen"
    CREATE_MAINTENANCE = "create_maintenance"
    REVISIT_STALE = "revisit_stale"
    SLEEP = "sleep"
    PAUSE = "pause"
    STOP = "stop"


class StopReason(str, Enum):
    POLICY_CEILING = "policy_ceiling"
    BUDGET_CEILING = "budget_ceiling"
    AWAITING_HUMAN = "awaiting_human"
    UNRESOLVED_CONFLICT = "unresolved_conflict"
    NO_PRODUCTIVE_ACTION = "no_productive_action"
    SUCCESS_REACHED = "success_reached"
    DIMINISHING_VALUE = "diminishing_value"
    KILL_SWITCH = "kill_switch"


@dataclass
class LoopState:
    """Tracks the current state of a LOOP iteration."""
    iteration: int = 0
    total_actions_taken: int = 0
    budget_spent: float = 0.0
    budget_limit: float = 0.0
    policy_ceiling: int = 100
    consecutive_no_ops: int = 0
    max_consecutive_no_ops: int = 5
    conflict_attempts: int = 0
    max_conflict_attempts: int = 3
    last_action: Optional[LoopAction] = None
    stop_reason: Optional[StopReason] = None
    is_stopped: bool = False


class LoopRuntime:
    """
    Shared LOOP behavior that controllers invoke to decide whether to
    continue, sleep, or stop. LOOP does not bypass Governance, KIRA,
    verification, or staged review.
    """

    def __init__(
        self,
        budget_limit: float = 50.0,
        policy_ceiling: int = 100,
        max_consecutive_no_ops: int = 5,
        max_conflict_attempts: int = 3,
    ):
        self.state = LoopState(
            budget_limit=budget_limit,
            policy_ceiling=policy_ceiling,
            max_consecutive_no_ops=max_consecutive_no_ops,
            max_conflict_attempts=max_conflict_attempts,
        )
        self._should_stop_hooks: list[Callable[[LoopState], Optional[StopReason]]] = []

    def register_stop_hook(self, hook: Callable[[LoopState], Optional[StopReason]]) -> None:
        """Register an external stopping condition check."""
        self._should_stop_hooks.append(hook)

    def should_continue(self) -> bool:
        """
        Evaluate all stopping rules. Returns True if LOOP should continue,
        False if it should stop.
        """
        if self.state.is_stopped:
            return False

        # Budget ceiling
        if self.state.budget_limit > 0 and self.state.budget_spent >= self.state.budget_limit:
            self._stop(StopReason.BUDGET_CEILING)
            return False

        # Policy ceiling
        if self.state.total_actions_taken >= self.state.policy_ceiling:
            self._stop(StopReason.POLICY_CEILING)
            return False

        # No productive action
        if self.state.consecutive_no_ops >= self.state.max_consecutive_no_ops:
            self._stop(StopReason.NO_PRODUCTIVE_ACTION)
            return False

        # Unresolved conflicts
        if self.state.conflict_attempts >= self.state.max_conflict_attempts:
            self._stop(StopReason.UNRESOLVED_CONFLICT)
            return False

        # External hooks
        for hook in self._should_stop_hooks:
            reason = hook(self.state)
            if reason is not None:
                self._stop(reason)
                return False

        return True

    def record_action(self, action: LoopAction, cost: float = 0.0) -> None:
        """Record that LOOP took an action."""
        self.state.iteration += 1
        self.state.total_actions_taken += 1
        self.state.budget_spent += cost
        self.state.last_action = action

        if action == LoopAction.SLEEP:
            self.state.consecutive_no_ops += 1
        else:
            self.state.consecutive_no_ops = 0

        logger.info(
            f"LOOP iteration={self.state.iteration} action={action.value} "
            f"budget={self.state.budget_spent:.2f}/{self.state.budget_limit:.2f}"
        )

    def record_conflict(self) -> None:
        self.state.conflict_attempts += 1

    def record_no_op(self) -> None:
        self.state.consecutive_no_ops += 1

    def _stop(self, reason: StopReason) -> None:
        self.state.is_stopped = True
        self.state.stop_reason = reason
        logger.info(f"LOOP stopped: {reason.value}")

    def reset(self) -> None:
        """Reset for a new LOOP cycle (e.g., after operator restart)."""
        self.state = LoopState(
            budget_limit=self.state.budget_limit,
            policy_ceiling=self.state.policy_ceiling,
            max_consecutive_no_ops=self.state.max_consecutive_no_ops,
            max_conflict_attempts=self.state.max_conflict_attempts,
        )

    def summary(self) -> dict[str, Any]:
        return {
            "iteration": self.state.iteration,
            "actions_taken": self.state.total_actions_taken,
            "budget_spent": self.state.budget_spent,
            "budget_limit": self.state.budget_limit,
            "is_stopped": self.state.is_stopped,
            "stop_reason": self.state.stop_reason.value if self.state.stop_reason else None,
            "consecutive_no_ops": self.state.consecutive_no_ops,
            "last_action": self.state.last_action.value if self.state.last_action else None,
        }
