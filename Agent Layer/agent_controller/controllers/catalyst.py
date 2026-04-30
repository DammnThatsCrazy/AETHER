"""
Aether Agent Layer — Catalyst Controller
Scheduling + wake engine. Single unified scheduler architecture.

Catalyst supports:
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

logger = logging.getLogger("aether.controllers.catalyst")


class CatalystType(str, Enum):
    CRON = "cron"
    GRAPH_STATE = "graph_state"
    WEBHOOK = "webhook"
    QUEUE_CONDITION = "queue_condition"
    STALE_ENTITY = "stale_entity"
    FAILED_RETRY = "failed_retry"
    OPERATOR_MANUAL = "operator_manual"


class CatalystStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    FIRED = "fired"
    MISSED = "missed"
    ORPHANED = "orphaned"
    EXPIRED = "expired"


@dataclass
class CatalystRecord:
    catalyst_id: str = ""
    catalyst_type: CatalystType = CatalystType.CRON
    target_controller: str = ""
    target_objective_id: str = ""
    schedule: str = ""  # cron expression or interval
    condition: dict[str, Any] = field(default_factory=dict)
    status: CatalystStatus = CatalystStatus.ACTIVE
    last_fired_at: Optional[float] = None
    fire_count: int = 0
    max_fires: int = 0  # 0 = unlimited
    created_at: float = field(default_factory=time.time)
    callback: Optional[Callable[[], None]] = field(default=None, repr=False)


class CatalystController:
    """
    Catalyst — unified scheduling and wake engine.
    One scheduler architecture, no fragmented schedulers.
    """

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self._catalysts: dict[str, CatalystRecord] = {}
        self._missed_fires: list[dict[str, Any]] = []
        self._next_id: int = 1

    def handle_step(self, step: Any, objective_id: str) -> dict[str, Any]:
        """Catalyst steps handle scheduling operations."""
        return {"action": "catalyst_evaluated", "objective_id": objective_id}

    # ------------------------------------------------------------------
    # Catalyst registration
    # ------------------------------------------------------------------

    def register_catalyst(
        self,
        catalyst_type: CatalystType,
        target_controller: str,
        target_objective_id: str = "",
        schedule: str = "",
        condition: dict[str, Any] | None = None,
        max_fires: int = 0,
        callback: Callable[[], None] | None = None,
    ) -> str:
        catalyst_id = f"CAT-{self._next_id:04d}"
        self._next_id += 1
        record = CatalystRecord(
            catalyst_id=catalyst_id,
            catalyst_type=catalyst_type,
            target_controller=target_controller,
            target_objective_id=target_objective_id,
            schedule=schedule,
            condition=condition or {},
            max_fires=max_fires,
            callback=callback,
        )
        self._catalysts[catalyst_id] = record
        logger.info(
            f"Catalyst: Registered {catalyst_id} "
            f"type={catalyst_type.value} target={target_controller}"
        )
        return catalyst_id

    # ------------------------------------------------------------------
    # Fire catalysts
    # ------------------------------------------------------------------

    def fire_catalyst(self, catalyst_id: str) -> bool:
        """Fire a catalyst and route to its target."""
        catalyst = self._catalysts.get(catalyst_id)
        if catalyst is None:
            logger.error(f"Catalyst: Unknown catalyst {catalyst_id}")
            return False

        if catalyst.status != CatalystStatus.ACTIVE:
            logger.warning(f"Catalyst: {catalyst_id} not active (status={catalyst.status.value})")
            return False

        # Check max fires
        if catalyst.max_fires > 0 and catalyst.fire_count >= catalyst.max_fires:
            catalyst.status = CatalystStatus.EXPIRED
            return False

        catalyst.last_fired_at = time.time()
        catalyst.fire_count += 1
        catalyst.status = CatalystStatus.FIRED

        # Execute callback if present
        if catalyst.callback:
            try:
                catalyst.callback()
            except Exception as e:
                logger.error(f"Catalyst: Callback failed for {catalyst_id}: {e}")

        # Re-arm for recurring catalysts
        if catalyst.max_fires == 0 or catalyst.fire_count < catalyst.max_fires:
            catalyst.status = CatalystStatus.ACTIVE

        self.event_bus.publish(AgentEvent(
            event_type=EventType.CATALYST_FIRED,
            source="catalyst",
            objective_id=catalyst.target_objective_id,
            payload={
                "catalyst_id": catalyst_id,
                "type": catalyst.catalyst_type.value,
                "target": catalyst.target_controller,
            },
        ))

        logger.info(f"Catalyst: Fired {catalyst_id} (count={catalyst.fire_count})")
        return True

    def evaluate_conditions(self, context: dict[str, Any]) -> list[str]:
        """Evaluate all condition-based catalysts against current context."""
        fired = []
        for catalyst_id, catalyst in self._catalysts.items():
            if catalyst.status != CatalystStatus.ACTIVE:
                continue
            if catalyst.catalyst_type in (
                CatalystType.GRAPH_STATE,
                CatalystType.QUEUE_CONDITION,
                CatalystType.STALE_ENTITY,
            ):
                if self._check_condition(catalyst.condition, context):
                    if self.fire_catalyst(catalyst_id):
                        fired.append(catalyst_id)
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

    def record_missed_fire(self, catalyst_id: str, reason: str) -> None:
        catalyst = self._catalysts.get(catalyst_id)
        if catalyst:
            catalyst.status = CatalystStatus.MISSED
        self._missed_fires.append({
            "catalyst_id": catalyst_id,
            "reason": reason,
            "timestamp": time.time(),
        })
        logger.warning(f"Catalyst: Missed fire {catalyst_id} — {reason}")

    # ------------------------------------------------------------------
    # Orphan cleanup
    # ------------------------------------------------------------------

    def cleanup_orphans(self, stale_threshold_seconds: float = 86400) -> list[str]:
        """Mark catalysts as orphaned if they haven't fired recently."""
        now = time.time()
        orphaned = []
        for catalyst_id, catalyst in self._catalysts.items():
            if catalyst.status != CatalystStatus.ACTIVE:
                continue
            age = now - catalyst.created_at
            if age > stale_threshold_seconds and catalyst.fire_count == 0:
                catalyst.status = CatalystStatus.ORPHANED
                orphaned.append(catalyst_id)
        if orphaned:
            logger.info(f"Catalyst: Cleaned up {len(orphaned)} orphaned catalysts")
        return orphaned

    # ------------------------------------------------------------------
    # Pause / resume
    # ------------------------------------------------------------------

    def pause_catalyst(self, catalyst_id: str) -> None:
        catalyst = self._catalysts.get(catalyst_id)
        if catalyst:
            catalyst.status = CatalystStatus.PAUSED

    def resume_catalyst(self, catalyst_id: str) -> None:
        catalyst = self._catalysts.get(catalyst_id)
        if catalyst:
            catalyst.status = CatalystStatus.ACTIVE

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def list_catalysts(self, status: CatalystStatus | None = None) -> list[CatalystRecord]:
        if status:
            return [c for c in self._catalysts.values() if c.status == status]
        return list(self._catalysts.values())

    def health(self) -> dict[str, Any]:
        active = sum(1 for c in self._catalysts.values() if c.status == CatalystStatus.ACTIVE)
        return {
            "controller": "catalyst",
            "status": "active",
            "total_catalysts": len(self._catalysts),
            "active_catalysts": active,
            "missed_fires": len(self._missed_fires),
        }
