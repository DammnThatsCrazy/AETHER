"""
Aether Agent Layer — Replanner
Handles plan failures by generating revised plans, reassigning steps,
or escalating to KIRA for cross-controller coordination.
"""

from __future__ import annotations

import logging
from typing import Optional

from models.objectives import (
    Objective,
    Plan,
    PlanStatus,
    PlanStep,
    StepStatus,
)

logger = logging.getLogger("aether.planning.replanner")


class Replanner:
    """
    Generates a revised plan when the current plan fails or gets blocked.
    Preserves completed steps and rebuilds from the failure point.
    """

    def __init__(self, max_replan_attempts: int = 3):
        self.max_replan_attempts = max_replan_attempts

    def needs_replan(self, plan: Plan) -> bool:
        """Check if a plan needs replanning."""
        if plan.status == PlanStatus.FAILED:
            return True
        if plan.failed_steps and plan.status == PlanStatus.ACTIVE:
            return True
        return False

    def replan(self, objective: Objective, current_plan: Plan) -> Optional[Plan]:
        """
        Create a new plan version preserving completed work.
        Returns None if max replan attempts exceeded.
        """
        if current_plan.version >= self.max_replan_attempts:
            logger.warning(
                f"Max replan attempts ({self.max_replan_attempts}) reached "
                f"for objective {objective.objective_id[:8]}..."
            )
            return None

        # Supersede the current plan
        current_plan.supersede()

        # Build new plan from incomplete/failed steps
        new_steps = []
        for step in current_plan.steps:
            if step.status == StepStatus.COMPLETED:
                continue  # preserve completed work
            # Reset failed/blocked steps
            new_step = PlanStep(
                plan_id="",
                required_domain=step.required_domain,
                assigned_controller=step.assigned_controller,
                assigned_team=step.assigned_team,
                input_schema=step.input_schema,
                expected_output_schema=step.expected_output_schema,
                verification_requirements=step.verification_requirements,
                retry_policy=step.retry_policy,
                compensation_policy=step.compensation_policy,
                status=StepStatus.PENDING,
            )
            new_steps.append(new_step)

        new_plan = Plan(
            objective_id=objective.objective_id,
            version=current_plan.version + 1,
            steps=new_steps,
            estimated_cost=current_plan.estimated_cost * 0.7,  # reduced scope
            created_by="replanner",
        )
        for step in new_plan.steps:
            step.plan_id = new_plan.plan_id

        # Rebuild dependencies
        new_plan.dependencies = {}
        for i in range(1, len(new_steps)):
            new_plan.dependencies[new_steps[i].step_id] = [new_steps[i - 1].step_id]

        logger.info(
            f"Replan created: {new_plan.plan_id[:8]}... "
            f"v{new_plan.version} steps={len(new_steps)} "
            f"for objective {objective.objective_id[:8]}..."
        )
        return new_plan
