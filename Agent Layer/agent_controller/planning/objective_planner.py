"""
Aether Agent Layer — Objective Planner
Creates execution plans for objectives by decomposing goals into
routable plan steps assigned to domain controllers and teams.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from models.objectives import (
    Objective,
    ObjectiveType,
    Plan,
    PlanStep,
    Severity,
    StepStatus,
)

logger = logging.getLogger("aether.planning.planner")


# Default domain routing: objective type -> controller assignments
_DEFAULT_ROUTES: dict[ObjectiveType, list[str]] = {
    ObjectiveType.DISCOVERY: ["intake", "discovery", "verification", "commit"],
    ObjectiveType.ENRICHMENT: ["intake", "enrichment", "verification", "commit"],
    ObjectiveType.VERIFICATION: ["intake", "verification"],
    ObjectiveType.MAINTENANCE: ["intake", "discovery", "enrichment", "verification", "commit"],
    ObjectiveType.RECOVERY: ["recovery"],
    ObjectiveType.RECONCILIATION: ["intake", "enrichment", "verification", "commit"],
}


class ObjectivePlanner:
    """
    Decomposes an objective into a Plan with ordered PlanSteps.
    Each step is assigned to a domain controller and optionally a team.
    """

    def __init__(self, custom_routes: dict[ObjectiveType, list[str]] | None = None):
        self._routes = custom_routes or _DEFAULT_ROUTES

    def create_plan(self, objective: Objective) -> Plan:
        """Generate a plan from an objective's type and goal definition."""
        route = self._routes.get(objective.objective_type, ["intake"])
        steps = []

        for i, controller_name in enumerate(route):
            step = PlanStep(
                plan_id="",  # filled when attached
                required_domain=controller_name,
                assigned_controller=controller_name,
                verification_requirements=self._verification_for(controller_name),
                retry_policy=self._retry_policy_for(objective.severity),
            )
            steps.append(step)

        plan = Plan(
            objective_id=objective.objective_id,
            steps=steps,
            estimated_cost=self._estimate_cost(objective, steps),
            created_by="objective_planner",
        )
        # Fix: set plan_id on steps
        for step in plan.steps:
            step.plan_id = plan.plan_id

        # Build dependency chain: each step depends on the previous
        plan.dependencies = {}
        for i in range(1, len(steps)):
            plan.dependencies[steps[i].step_id] = [steps[i - 1].step_id]

        logger.info(
            f"Plan created: {plan.plan_id[:8]}... "
            f"steps={len(steps)} for objective {objective.objective_id[:8]}..."
        )
        return plan

    def _verification_for(self, controller: str) -> list[str]:
        if controller == "verification":
            return ["evidence_sufficiency", "provenance", "schema", "consistency"]
        if controller == "commit":
            return ["pre_commit_verification"]
        return []

    def _retry_policy_for(self, severity: Severity) -> dict[str, Any]:
        if severity.value <= Severity.HIGH.value:
            return {"max_retries": 5, "backoff_seconds": 15}
        return {"max_retries": 3, "backoff_seconds": 30}

    def _estimate_cost(self, objective: Objective, steps: list[PlanStep]) -> float:
        """Simple cost estimation based on step count and severity."""
        base = len(steps) * 0.10
        severity_mult = {0: 2.0, 1: 1.5, 2: 1.0, 3: 0.5, 4: 0.2}
        return base * severity_mult.get(objective.severity.value, 1.0)
