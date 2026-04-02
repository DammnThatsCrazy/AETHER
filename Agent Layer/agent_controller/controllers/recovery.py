"""
Aether Agent Layer — Recovery Controller
Handles retry/fallback, compensation, rollback orchestration,
stale objective repair, and checkpoint restoration.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from models.objectives import Objective, ObjectiveStatus, PlanStep
from agent_controller.runtime.checkpointing import CheckpointStore

logger = logging.getLogger("aether.controllers.recovery")


class RecoveryController:
    """
    Manages recovery operations: retry failed objectives, restore
    from checkpoints, compensate for failed mutations, and repair
    stale objectives.
    """

    def __init__(self, checkpoint_store: CheckpointStore, objective_runtime: Any = None):
        self.checkpoints = checkpoint_store
        self.objective_runtime = objective_runtime
        self._recovery_log: list[dict[str, Any]] = []

    def handle_step(self, step: PlanStep, objective_id: str) -> dict[str, Any]:
        """Execute a recovery step."""
        recovery_type = step.input_schema.get("recovery_type", "retry")

        if recovery_type == "retry":
            return self._handle_retry(objective_id)
        elif recovery_type == "checkpoint_restore":
            return self._handle_checkpoint_restore(objective_id)
        elif recovery_type == "compensation":
            return self._handle_compensation(objective_id, step)
        elif recovery_type == "stale_repair":
            return self._handle_stale_repair(objective_id)
        else:
            return {"action": "unknown_recovery_type", "type": recovery_type}

    def _handle_retry(self, objective_id: str) -> dict[str, Any]:
        self._log_recovery(objective_id, "retry", "Retrying objective")
        return {"action": "retry_initiated", "objective_id": objective_id}

    def _handle_checkpoint_restore(self, objective_id: str) -> dict[str, Any]:
        checkpoint = self.checkpoints.latest(objective_id)
        if checkpoint is None:
            return {"action": "no_checkpoint_found", "objective_id": objective_id}

        self._log_recovery(
            objective_id, "checkpoint_restore",
            f"Restoring from checkpoint {checkpoint.checkpoint_id[:8]}..."
        )
        return {
            "action": "checkpoint_restored",
            "checkpoint_id": checkpoint.checkpoint_id,
            "completed_steps": checkpoint.completed_steps,
            "open_steps": checkpoint.open_steps,
        }

    def _handle_compensation(self, objective_id: str, step: PlanStep) -> dict[str, Any]:
        compensation_actions = step.compensation_policy
        self._log_recovery(objective_id, "compensation", str(compensation_actions))
        return {"action": "compensation_applied", "policy": compensation_actions}

    def _handle_stale_repair(self, objective_id: str) -> dict[str, Any]:
        self._log_recovery(objective_id, "stale_repair", "Repairing stale objective")
        return {"action": "stale_repair_initiated", "objective_id": objective_id}

    def _log_recovery(self, objective_id: str, recovery_type: str, detail: str) -> None:
        entry = {
            "objective_id": objective_id,
            "recovery_type": recovery_type,
            "detail": detail,
        }
        self._recovery_log.append(entry)
        logger.info(f"Recovery [{recovery_type}]: {detail}")

    def health(self) -> dict[str, Any]:
        return {
            "controller": "recovery",
            "status": "active",
            "recoveries_performed": len(self._recovery_log),
        }
