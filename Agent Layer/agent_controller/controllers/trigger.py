"""
Aether Agent Layer — TRIGGER Controller
Scheduling + wake engine. Single unified scheduler architecture.

TRIGGER supports:
- Cron/scheduled wakeups
- Graph-state change wakeups
- Provider/webhook wakeups
- Queue/backlog condition wakeups
- Stale-entity wakeups
- Failed-objective retry wakeups
- Operator/manual wakeups
- Missed-fire handling
- Orphan cleanup
- Clear fire routing to the correct objective/controller context
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from shared.events.objective_events import AgentEvent, EventBus, EventType

logger = logging.getLogger("aether.controllers.trigger")


class TriggerType(str, Enum):
    CRON = "cron"
    GRAPH_STATE = "graph_state"
    WEBHOOK = "webhook"
    QUEUE_CONDITION = "queue_condition"
    STALE_ENTITY = "stale_entity"
    FAILED_RETRY = "failed_retry"
    OPERATOR_MANUAL = "operator_manual"


class TriggerStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    FIRED = "fired"
    MISSED = "missed"
    ORPHANED = "orphaned"
    EXPIRED = "expired"


@dataclass
class TriggerRecord:
    trigger_id: str = ""
    trigger_type: TriggerType = TriggerType.CRON
    target_controller: str = ""
    target_objective_id: str = ""
    schedule: str = ""  # cron expression or interval
    condition: dict[str, Any] = field(default_factory=dict)
    status: TriggerStatus = TriggerStatus.ACTIVE
    last_fired_at: Optional[float] = None
    fire_count: int = 0
    max_fires: int = 0  # 0 = unlimited
    created_at: float = field(default_factory=time.time)
    callback: Optional[Callable[[], None]] = field(default=None, repr=False)


class TriggerController:
    """
    TRIGGER — unified scheduling and wake engine.
    One scheduler architecture, no fragmented schedulers.
    """

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self._triggers: dict[str, TriggerRecord] = {}
        self._missed_fires: list[dict[str, Any]] = []
        self._next_id: int = 1

    def handle_step(self, step: Any, objective_id: str) -> dict[str, Any]:
        """TRIGGER steps handle scheduling operations."""
        return {"action": "trigger_evaluated", "objective_id": objective_id}

    # ------------------------------------------------------------------
    # Trigger registration
    # ------------------------------------------------------------------

    def register_trigger(
        self,
        trigger_type: TriggerType,
        target_controller: str,
        target_objective_id: str = "",
        schedule: str = "",
        condition: dict[str, Any] | None = None,
        max_fires: int = 0,
        callback: Callable[[], None] | None = None,
    ) -> str:
        trigger_id = f"TRG-{self._next_id:04d}"
        self._next_id += 1
        record = TriggerRecord(
            trigger_id=trigger_id,
            trigger_type=trigger_type,
            target_controller=target_controller,
            target_objective_id=target_objective_id,
            schedule=schedule,
            condition=condition or {},
            max_fires=max_fires,
            callback=callback,
        )
        self._triggers[trigger_id] = record
        logger.info(
            f"TRIGGER: Registered {trigger_id} "
            f"type={trigger_type.value} target={target_controller}"
        )
        return trigger_id

    # ------------------------------------------------------------------
    # Fire triggers
    # ------------------------------------------------------------------

    def fire_trigger(self, trigger_id: str) -> bool:
        """Fire a trigger and route to its target."""
        trigger = self._triggers.get(trigger_id)
        if trigger is None:
            logger.error(f"TRIGGER: Unknown trigger {trigger_id}")
            return False

        if trigger.status != TriggerStatus.ACTIVE:
            logger.warning(f"TRIGGER: {trigger_id} not active (status={trigger.status.value})")
            return False

        # Check max fires
        if trigger.max_fires > 0 and trigger.fire_count >= trigger.max_fires:
            trigger.status = TriggerStatus.EXPIRED
            return False

        trigger.last_fired_at = time.time()
        trigger.fire_count += 1
        trigger.status = TriggerStatus.FIRED

        # Execute callback if present
        if trigger.callback:
            try:
                trigger.callback()
            except Exception as e:
                logger.error(f"TRIGGER: Callback failed for {trigger_id}: {e}")

        # Re-arm for recurring triggers
        if trigger.max_fires == 0 or trigger.fire_count < trigger.max_fires:
            trigger.status = TriggerStatus.ACTIVE

        self.event_bus.publish(AgentEvent(
            event_type=EventType.TRIGGER_FIRED,
            source="trigger",
            objective_id=trigger.target_objective_id,
            payload={
                "trigger_id": trigger_id,
                "type": trigger.trigger_type.value,
                "target": trigger.target_controller,
            },
        ))

        logger.info(f"TRIGGER: Fired {trigger_id} (count={trigger.fire_count})")
        return True

    def evaluate_conditions(self, context: dict[str, Any]) -> list[str]:
        """Evaluate all condition-based triggers against current context."""
        fired = []
        for trigger_id, trigger in self._triggers.items():
            if trigger.status != TriggerStatus.ACTIVE:
                continue
            if trigger.trigger_type in (
                TriggerType.GRAPH_STATE,
                TriggerType.QUEUE_CONDITION,
                TriggerType.STALE_ENTITY,
            ):
                if self._check_condition(trigger.condition, context):
                    if self.fire_trigger(trigger_id):
                        fired.append(trigger_id)
        return fired

    def _check_condition(self, condition: dict[str, Any], context: dict[str, Any]) -> bool:
        """Simple condition matching. Production: real predicate engine."""
        for key, expected in condition.items():
            if context.get(key) != expected:
                return False
        return True

    # ------------------------------------------------------------------
    # Missed-fire handling
    # ------------------------------------------------------------------

    def record_missed_fire(self, trigger_id: str, reason: str) -> None:
        trigger = self._triggers.get(trigger_id)
        if trigger:
            trigger.status = TriggerStatus.MISSED
        self._missed_fires.append({
            "trigger_id": trigger_id,
            "reason": reason,
            "timestamp": time.time(),
        })
        logger.warning(f"TRIGGER: Missed fire {trigger_id} — {reason}")

    # ------------------------------------------------------------------
    # Orphan cleanup
    # ------------------------------------------------------------------

    def cleanup_orphans(self, stale_threshold_seconds: float = 86400) -> list[str]:
        """Mark triggers as orphaned if they haven't fired recently."""
        now = time.time()
        orphaned = []
        for trigger_id, trigger in self._triggers.items():
            if trigger.status != TriggerStatus.ACTIVE:
                continue
            age = now - trigger.created_at
            if age > stale_threshold_seconds and trigger.fire_count == 0:
                trigger.status = TriggerStatus.ORPHANED
                orphaned.append(trigger_id)
        if orphaned:
            logger.info(f"TRIGGER: Cleaned up {len(orphaned)} orphaned triggers")
        return orphaned

    # ------------------------------------------------------------------
    # Pause / resume
    # ------------------------------------------------------------------

    def pause_trigger(self, trigger_id: str) -> None:
        trigger = self._triggers.get(trigger_id)
        if trigger:
            trigger.status = TriggerStatus.PAUSED

    def resume_trigger(self, trigger_id: str) -> None:
        trigger = self._triggers.get(trigger_id)
        if trigger:
            trigger.status = TriggerStatus.ACTIVE

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def list_triggers(self, status: TriggerStatus | None = None) -> list[TriggerRecord]:
        if status:
            return [t for t in self._triggers.values() if t.status == status]
        return list(self._triggers.values())

    def health(self) -> dict[str, Any]:
        active = sum(1 for t in self._triggers.values() if t.status == TriggerStatus.ACTIVE)
        return {
            "controller": "trigger",
            "status": "active",
            "total_triggers": len(self._triggers),
            "active_triggers": active,
            "missed_fires": len(self._missed_fires),
        }
