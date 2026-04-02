"""
Aether Agent Layer — Objective Runtime
Manages the lifecycle of objectives: creation, tracking, state transitions,
and persistence of objective state across the controller hierarchy.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from models.objectives import (
    Objective,
    ObjectiveStatus,
    ObjectiveType,
    Plan,
    Severity,
)

logger = logging.getLogger("aether.runtime.objective")


class ObjectiveRuntime:
    """
    Central objective store and lifecycle manager.
    All controllers interact with objectives through this runtime.
    """

    def __init__(self):
        self._objectives: dict[str, Objective] = {}
        self._plans: dict[str, Plan] = {}

    # ------------------------------------------------------------------
    # Objective CRUD
    # ------------------------------------------------------------------

    def create_objective(
        self,
        objective_type: ObjectiveType,
        goal_definition: str,
        source: str = "",
        target_entity_ids: list[str] | None = None,
        severity: Severity = Severity.MEDIUM,
        priority: int = 2,
        policy_scope: str = "default",
        budget_limit: float = 0.0,
        deadline: Optional[datetime] = None,
        opened_by: str = "",
    ) -> Objective:
        obj = Objective(
            objective_type=objective_type,
            source=source,
            target_entity_ids=target_entity_ids or [],
            goal_definition=goal_definition,
            severity=severity,
            priority=priority,
            policy_scope=policy_scope,
            budget_limit=budget_limit,
            deadline=deadline,
            opened_by=opened_by,
        )
        self._objectives[obj.objective_id] = obj
        logger.info(
            f"Objective created: {obj.objective_id[:8]}... "
            f"type={obj.objective_type.value} severity={obj.severity.name}"
        )
        return obj

    def get_objective(self, objective_id: str) -> Optional[Objective]:
        return self._objectives.get(objective_id)

    def list_objectives(
        self,
        status: ObjectiveStatus | None = None,
        objective_type: ObjectiveType | None = None,
    ) -> list[Objective]:
        results = list(self._objectives.values())
        if status is not None:
            results = [o for o in results if o.status == status]
        if objective_type is not None:
            results = [o for o in results if o.objective_type == objective_type]
        return results

    # ------------------------------------------------------------------
    # Plan management
    # ------------------------------------------------------------------

    def attach_plan(self, objective_id: str, plan: Plan) -> None:
        obj = self._objectives.get(objective_id)
        if obj is None:
            raise ValueError(f"Objective {objective_id} not found")
        plan.objective_id = objective_id
        self._plans[plan.plan_id] = plan
        obj.current_plan_id = plan.plan_id
        logger.info(f"Plan {plan.plan_id[:8]}... attached to objective {objective_id[:8]}...")

    def get_plan(self, plan_id: str) -> Optional[Plan]:
        return self._plans.get(plan_id)

    def get_active_plan(self, objective_id: str) -> Optional[Plan]:
        obj = self._objectives.get(objective_id)
        if obj is None or obj.current_plan_id is None:
            return None
        return self._plans.get(obj.current_plan_id)

    # ------------------------------------------------------------------
    # Status transitions
    # ------------------------------------------------------------------

    def transition(self, objective_id: str, new_status: ObjectiveStatus) -> None:
        obj = self._objectives.get(objective_id)
        if obj is None:
            raise ValueError(f"Objective {objective_id} not found")
        old_status = obj.status
        obj.status = new_status
        logger.info(
            f"Objective {objective_id[:8]}... "
            f"{old_status.value} -> {new_status.value}"
        )

    # ------------------------------------------------------------------
    # Queries for LOOP and controllers
    # ------------------------------------------------------------------

    @property
    def active_count(self) -> int:
        return sum(1 for o in self._objectives.values() if o.status == ObjectiveStatus.ACTIVE)

    @property
    def blocked_count(self) -> int:
        return sum(1 for o in self._objectives.values() if o.status == ObjectiveStatus.BLOCKED)

    @property
    def awaiting_review_count(self) -> int:
        return sum(
            1 for o in self._objectives.values()
            if o.status == ObjectiveStatus.AWAITING_REVIEW
        )

    def stale_objectives(self, stale_threshold_seconds: float = 3600) -> list[Objective]:
        """Return objectives that have been active but not updated recently."""
        now = datetime.now(timezone.utc)
        stale = []
        for obj in self._objectives.values():
            if obj.status in (ObjectiveStatus.ACTIVE, ObjectiveStatus.BLOCKED):
                age = (now - obj.opened_at).total_seconds()
                if age > stale_threshold_seconds:
                    stale.append(obj)
        return stale

    def sleeping_objectives(self) -> list[Objective]:
        return [o for o in self._objectives.values() if o.status == ObjectiveStatus.SLEEPING]
