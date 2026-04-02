"""
Aether Agent Layer — BOLT Controller
Continuity + briefing + internal operator signal runtime.

BOLT owns:
- Objective continuity across sessions/process restarts
- Checkpoint records
- Brief records
- Internal operator summaries
- Handoff state
- Run history
- Session restore coordination
- Internal feed/timeline generation
- Internal board/status generation

BOLT must support:
- CLI-first operational surface
- ASCII dashboard rendering
- Dashboard/admin supervisory surface
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from agent_controller.runtime.checkpointing import CheckpointRecord, CheckpointStore
from agent_controller.runtime.briefing import (
    BriefAudience,
    BriefRecord,
    BriefingStore,
    BriefType,
)
from shared.events.objective_events import AgentEvent, EventBus, EventType

logger = logging.getLogger("aether.controllers.bolt")


class BoltController:
    """
    BOLT — continuity and briefing controller.
    Manages checkpoints, briefs, run history, and the internal
    operator-facing information surface.
    """

    def __init__(
        self,
        checkpoint_store: CheckpointStore,
        briefing_store: BriefingStore,
        event_bus: EventBus,
    ):
        self.checkpoints = checkpoint_store
        self.briefings = briefing_store
        self.event_bus = event_bus
        self._run_history: list[dict[str, Any]] = []
        self._handoff_state: dict[str, Any] = {}
        self._session_id: str = ""

        # Subscribe to key events for timeline
        self.event_bus.subscribe_all(self._on_event)

    def handle_step(self, step: Any, objective_id: str) -> dict[str, Any]:
        """BOLT steps handle continuity and briefing operations."""
        return {"action": "bolt_checkpoint", "objective_id": objective_id}

    # ------------------------------------------------------------------
    # Checkpointing
    # ------------------------------------------------------------------

    def create_checkpoint(
        self,
        objective_id: str,
        plan_id: str = "",
        open_steps: list[str] | None = None,
        completed_steps: list[str] | None = None,
        blocked_steps: list[str] | None = None,
        budget_spent: float = 0.0,
        summary: str = "",
    ) -> CheckpointRecord:
        cp = self.checkpoints.create_checkpoint(
            objective_id=objective_id,
            plan_id=plan_id,
            open_steps=open_steps,
            completed_steps=completed_steps,
            blocked_steps=blocked_steps,
            budget_spent=budget_spent,
            summary=summary,
        )
        self.event_bus.publish(AgentEvent(
            event_type=EventType.CHECKPOINT_SAVED,
            source="bolt",
            objective_id=objective_id,
            payload={"checkpoint_id": cp.checkpoint_id},
        ))
        return cp

    def restore_session(self) -> dict[str, Any]:
        """Restore the last known state for all active objectives."""
        latest = self.checkpoints.all_latest()
        restored = []
        for cp in latest:
            restored.append({
                "objective_id": cp.objective_id,
                "plan_id": cp.plan_id,
                "completed": len(cp.completed_steps),
                "open": len(cp.open_steps),
                "blocked": len(cp.blocked_steps),
            })
        self.briefings.create_brief(
            brief_type=BriefType.SESSION_RESTORE,
            summary=f"Session restored with {len(restored)} active objectives",
            details={"objectives": restored},
        )
        logger.info(f"BOLT: Session restored — {len(restored)} objectives")
        return {"restored_objectives": restored}

    # ------------------------------------------------------------------
    # Briefing
    # ------------------------------------------------------------------

    def create_brief(
        self,
        brief_type: BriefType,
        summary: str,
        objective_id: str = "",
        audience: BriefAudience = BriefAudience.OPERATOR,
        details: dict[str, Any] | None = None,
    ) -> BriefRecord:
        brief = self.briefings.create_brief(
            brief_type=brief_type,
            summary=summary,
            objective_id=objective_id,
            audience=audience,
            details=details,
        )
        self.event_bus.publish(AgentEvent(
            event_type=EventType.BRIEF_CREATED,
            source="bolt",
            objective_id=objective_id,
            payload={"brief_id": brief.brief_id, "type": brief_type.value},
        ))
        return brief

    def operator_summary(self) -> dict[str, Any]:
        """Generate a current operator summary."""
        recent_briefs = self.briefings.recent(10)
        alerts = self.briefings.alerts()
        return {
            "recent_briefs": [
                {"type": b.brief_type.value, "summary": b.summary}
                for b in recent_briefs
            ],
            "active_alerts": len(alerts),
            "run_history_count": len(self._run_history),
            "handoff_state": self._handoff_state,
        }

    # ------------------------------------------------------------------
    # Run history
    # ------------------------------------------------------------------

    def record_run(self, run_data: dict[str, Any]) -> None:
        run_data["timestamp"] = datetime.now(timezone.utc).isoformat()
        self._run_history.append(run_data)

    def set_handoff_state(self, state: dict[str, Any]) -> None:
        self._handoff_state = state

    @property
    def run_history(self) -> list[dict[str, Any]]:
        return list(self._run_history)

    # ------------------------------------------------------------------
    # Event handler
    # ------------------------------------------------------------------

    def _on_event(self, event: AgentEvent) -> None:
        """Record timeline events for the internal feed."""
        # Events are already stored in event_bus history
        pass

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        return {
            "controller": "bolt",
            "status": "active",
            "total_checkpoints": len(self.checkpoints.all_latest()),
            "total_briefs": self.briefings.total_count,
            "run_history": len(self._run_history),
        }
