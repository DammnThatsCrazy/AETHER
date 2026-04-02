"""
Aether Agent Layer — Internal Operations Service
Provides the operational surface for internal team operations.
This is the primary interface for operators interacting with the agent layer.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from models.objectives import Objective, ObjectiveStatus, ObjectiveType, Severity

logger = logging.getLogger("aether.services.internal_ops")


class InternalOpsService:
    """
    Operator-facing service for managing agent layer operations.
    Wraps the controller hierarchy for direct operational use.
    """

    def __init__(self, controller_hub: Any):
        self._hub = controller_hub

    def submit_objective(
        self,
        objective_type: str,
        goal: str,
        target_entities: list[str] | None = None,
        severity: str = "medium",
        priority: int = 2,
    ) -> dict[str, Any]:
        """Submit a new objective through the intake pipeline."""
        obj_type = ObjectiveType(objective_type)
        sev = Severity[severity.upper()]
        obj = self._hub.objective_runtime.create_objective(
            objective_type=obj_type,
            goal_definition=goal,
            target_entity_ids=target_entities or [],
            severity=sev,
            priority=priority,
            opened_by="operator",
        )
        return {"objective_id": obj.objective_id, "status": obj.status.value}

    def list_objectives(self, status: str | None = None) -> list[dict[str, Any]]:
        """List objectives with optional status filter."""
        s = ObjectiveStatus(status) if status else None
        objectives = self._hub.objective_runtime.list_objectives(status=s)
        return [
            {
                "objective_id": o.objective_id,
                "type": o.objective_type.value,
                "status": o.status.value,
                "severity": o.severity.name,
                "goal": o.goal_definition[:100],
            }
            for o in objectives
        ]

    def review_pending(self) -> list[dict[str, Any]]:
        """List all pending review batches."""
        batches = self._hub.review_runtime.open_batches()
        return [
            {
                "batch_id": b.review_batch_id,
                "objective_id": b.objective_id,
                "entities": b.entity_ids,
                "severity": b.severity,
                "mutations": len(b.staged_mutation_ids),
                "status": b.review_status.value,
            }
            for b in batches
        ]

    def approve_batch(self, batch_id: str, reviewer: str, notes: str = "") -> dict[str, str]:
        """Approve a review batch."""
        self._hub.review_runtime.approve_batch(batch_id, reviewer, notes)
        return {"batch_id": batch_id, "status": "approved"}

    def reject_batch(self, batch_id: str, reviewer: str, notes: str = "") -> dict[str, str]:
        """Reject a review batch."""
        self._hub.review_runtime.reject_batch(batch_id, reviewer, notes)
        return {"batch_id": batch_id, "status": "rejected"}

    def controller_health(self) -> dict[str, Any]:
        """Get health status of all controllers."""
        return self._hub.controller_health()

    def recent_timeline(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get recent timeline events."""
        events = self._hub.event_bus.recent_events(limit)
        return [
            {
                "type": e.event_type.value,
                "source": e.source,
                "objective_id": e.objective_id,
                "timestamp": e.timestamp.isoformat(),
                "payload": e.payload,
            }
            for e in events
        ]
