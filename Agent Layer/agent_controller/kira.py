"""
Aether Agent Layer — KIRA Controller
Top orchestration controller across all domain controllers.
KIRA is an orchestrator, NOT a full-access worker.

KIRA must:
- Coordinate across domain controllers
- Synthesize objective execution
- Supervise controller progress
- Route plan steps
- Request verification
- Trigger recovery or replanning
- Prepare staged mutation packages for approval
- Communicate final internal outcomes

KIRA must NOT:
- Directly act like a normal worker
- Directly mutate canonical graph state
- Bypass review workflows
- Replace domain controller responsibilities
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from models.objectives import (
    Objective,
    ObjectiveStatus,
    Plan,
    PlanStep,
    StepStatus,
)
from agent_controller.governance import GovernanceController
from agent_controller.runtime.objective_runtime import ObjectiveRuntime
from agent_controller.runtime.loop_runtime import LoopRuntime, LoopAction
from agent_controller.planning.objective_planner import ObjectivePlanner
from agent_controller.planning.replanner import Replanner
from agent_controller.planning.routing_policy import RoutingPolicy
from shared.events.objective_events import AgentEvent, EventBus, EventType

logger = logging.getLogger("aether.kira")


class KiraController:
    """
    KIRA — top orchestration controller. Sits under Governance and
    coordinates all domain controllers through the plan/step execution model.
    """

    def __init__(
        self,
        governance: GovernanceController,
        objective_runtime: ObjectiveRuntime,
        event_bus: EventBus,
        loop: LoopRuntime | None = None,
    ):
        self.governance = governance
        self.objective_runtime = objective_runtime
        self.event_bus = event_bus
        self.loop = loop or LoopRuntime()
        self.planner = ObjectivePlanner()
        self.replanner = Replanner()
        self.routing = RoutingPolicy()
        self._domain_controllers: dict[str, Any] = {}

    def register_controller(self, name: str, controller: Any) -> None:
        """Register a domain controller for step routing."""
        self._domain_controllers[name] = controller
        logger.info(f"KIRA: Registered domain controller '{name}'")

    # ------------------------------------------------------------------
    # Objective orchestration
    # ------------------------------------------------------------------

    def admit_objective(self, objective: Objective) -> bool:
        """Admit an objective through governance checks and begin planning."""
        if self.governance.is_halted:
            logger.warning("KIRA: Governance halt — rejecting objective")
            return False

        if not self.governance.can_admit_objective():
            logger.warning("KIRA: Objective ceiling reached — rejecting")
            return False

        # Plan the objective
        plan = self.planner.create_plan(objective)
        self.objective_runtime.attach_plan(objective.objective_id, plan)
        objective.activate()
        plan.activate()
        self.governance.track_objective_started()

        self.event_bus.publish(AgentEvent(
            event_type=EventType.OBJECTIVE_ACTIVATED,
            source="kira",
            objective_id=objective.objective_id,
        ))

        logger.info(
            f"KIRA: Objective {objective.objective_id[:8]}... admitted "
            f"with plan {plan.plan_id[:8]}..."
        )
        return True

    def execute_next_step(self, objective_id: str) -> Optional[dict[str, Any]]:
        """
        Find the next ready step in an objective's plan and route it
        to the appropriate domain controller.
        """
        plan = self.objective_runtime.get_active_plan(objective_id)
        if plan is None:
            return None

        # Find next executable step (respecting dependencies)
        next_step = self._find_next_step(plan)
        if next_step is None:
            # Check if plan is complete
            if all(s.status == StepStatus.COMPLETED for s in plan.steps):
                plan.complete()
                obj = self.objective_runtime.get_objective(objective_id)
                if obj:
                    obj.send_to_review()
                self.event_bus.publish(AgentEvent(
                    event_type=EventType.PLAN_COMPLETED,
                    source="kira",
                    objective_id=objective_id,
                ))
                return {"status": "plan_complete", "objective_id": objective_id}
            return None

        # Route to domain controller
        decision = self.routing.route_step(next_step)
        controller = self._domain_controllers.get(decision.controller)
        if controller is None:
            logger.error(f"KIRA: No controller '{decision.controller}' registered")
            next_step.fail(f"No controller: {decision.controller}")
            return {"status": "routing_failed", "step_id": next_step.step_id}

        next_step.assigned_controller = decision.controller
        next_step.assigned_team = decision.team
        next_step.start()

        self.event_bus.publish(AgentEvent(
            event_type=EventType.STEP_STARTED,
            source="kira",
            objective_id=objective_id,
            payload={"step_id": next_step.step_id, "controller": decision.controller},
        ))

        # Delegate execution to the domain controller
        try:
            result = controller.handle_step(next_step, objective_id)
            next_step.complete(result)
            self.event_bus.publish(AgentEvent(
                event_type=EventType.STEP_COMPLETED,
                source="kira",
                objective_id=objective_id,
                payload={"step_id": next_step.step_id},
            ))
            return {"status": "step_completed", "step_id": next_step.step_id, "result": result}
        except Exception as e:
            logger.error(f"KIRA: Step {next_step.step_id[:8]}... failed: {e}")
            next_step.fail(str(e))
            self.event_bus.publish(AgentEvent(
                event_type=EventType.STEP_FAILED,
                source="kira",
                objective_id=objective_id,
                payload={"step_id": next_step.step_id, "error": str(e)},
            ))
            return {"status": "step_failed", "step_id": next_step.step_id, "error": str(e)}

    def check_replan(self, objective_id: str) -> bool:
        """Check if an objective needs replanning and trigger if so."""
        plan = self.objective_runtime.get_active_plan(objective_id)
        obj = self.objective_runtime.get_objective(objective_id)
        if plan is None or obj is None:
            return False

        if self.replanner.needs_replan(plan):
            new_plan = self.replanner.replan(obj, plan)
            if new_plan is None:
                obj.fail("Max replan attempts exceeded")
                self.governance.track_objective_ended()
                self.event_bus.publish(AgentEvent(
                    event_type=EventType.OBJECTIVE_FAILED,
                    source="kira",
                    objective_id=objective_id,
                ))
                return False
            self.objective_runtime.attach_plan(objective_id, new_plan)
            new_plan.activate()
            logger.info(f"KIRA: Replanned objective {objective_id[:8]}...")
            return True
        return False

    def complete_objective(self, objective_id: str) -> None:
        """Mark an objective as completed after review approval."""
        obj = self.objective_runtime.get_objective(objective_id)
        if obj:
            obj.complete()
            self.governance.track_objective_ended()
            self.event_bus.publish(AgentEvent(
                event_type=EventType.OBJECTIVE_COMPLETED,
                source="kira",
                objective_id=objective_id,
            ))
            logger.info(f"KIRA: Objective {objective_id[:8]}... completed")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _find_next_step(self, plan: Plan) -> Optional[PlanStep]:
        """Find the next step whose dependencies are all completed."""
        for step in plan.steps:
            if step.status != StepStatus.PENDING:
                continue
            deps = plan.dependencies.get(step.step_id, [])
            all_deps_done = all(
                any(s.step_id == dep_id and s.status == StepStatus.COMPLETED for s in plan.steps)
                for dep_id in deps
            )
            if all_deps_done:
                return step
        return None

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        return {
            "controller": "kira",
            "status": "halted" if self.governance.is_halted else "active",
            "active_objectives": self.objective_runtime.active_count,
            "blocked_objectives": self.objective_runtime.blocked_count,
            "awaiting_review": self.objective_runtime.awaiting_review_count,
            "domain_controllers": list(self._domain_controllers.keys()),
            "loop_state": self.loop.summary(),
        }
