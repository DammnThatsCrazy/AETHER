"""
Aether Agent Layer — Objective Events
Event bus for internal agent layer events. Controllers and runtimes
publish events here; BOLT, TRIGGER, and the CLI dashboard subscribe.

This does NOT replace Kafka for external event streaming —
it is the internal agent-layer event channel only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger("aether.shared.events")


class EventType(str, Enum):
    OBJECTIVE_CREATED = "objective.created"
    OBJECTIVE_ACTIVATED = "objective.activated"
    OBJECTIVE_COMPLETED = "objective.completed"
    OBJECTIVE_FAILED = "objective.failed"
    OBJECTIVE_BLOCKED = "objective.blocked"
    OBJECTIVE_REVIEW = "objective.awaiting_review"
    PLAN_CREATED = "plan.created"
    PLAN_COMPLETED = "plan.completed"
    PLAN_FAILED = "plan.failed"
    STEP_STARTED = "step.started"
    STEP_COMPLETED = "step.completed"
    STEP_FAILED = "step.failed"
    MUTATION_STAGED = "mutation.staged"
    MUTATION_APPROVED = "mutation.approved"
    MUTATION_REJECTED = "mutation.rejected"
    MUTATION_COMMITTED = "mutation.committed"
    BATCH_CREATED = "batch.created"
    BATCH_APPROVED = "batch.approved"
    BATCH_REJECTED = "batch.rejected"
    CHECKPOINT_SAVED = "checkpoint.saved"
    BRIEF_CREATED = "brief.created"
    CONTROLLER_ALERT = "controller.alert"
    TRIGGER_FIRED = "trigger.fired"
    LOOP_STOPPED = "loop.stopped"
    RECOVERY_STARTED = "recovery.started"


@dataclass
class AgentEvent:
    event_type: EventType
    source: str = ""
    objective_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class EventBus:
    """Simple synchronous event bus for internal agent layer events."""

    def __init__(self):
        self._subscribers: dict[EventType, list[Callable[[AgentEvent], None]]] = {}
        self._history: list[AgentEvent] = []
        self._max_history: int = 1000

    def subscribe(
        self, event_type: EventType, callback: Callable[[AgentEvent], None]
    ) -> None:
        self._subscribers.setdefault(event_type, []).append(callback)

    def subscribe_all(self, callback: Callable[[AgentEvent], None]) -> None:
        """Subscribe to all event types."""
        for et in EventType:
            self.subscribe(et, callback)

    def publish(self, event: AgentEvent) -> None:
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        callbacks = self._subscribers.get(event.event_type, [])
        for cb in callbacks:
            try:
                cb(event)
            except Exception:
                logger.exception(f"Event handler error for {event.event_type.value}")

    def recent_events(self, limit: int = 50) -> list[AgentEvent]:
        return list(reversed(self._history[-limit:]))

    def events_for_objective(self, objective_id: str) -> list[AgentEvent]:
        return [e for e in self._history if e.objective_id == objective_id]
