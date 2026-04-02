"""
Aether Agent Layer — Intake Controller
Handles objective intake: dedupe, normalization, admission control,
severity classification, and routing into KIRA.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from models.objectives import Objective, ObjectiveStatus, Severity, PlanStep

logger = logging.getLogger("aether.controllers.intake")


class IntakeController:
    """
    First-contact controller for new objectives. Normalizes input,
    deduplicates against existing objectives, classifies severity,
    and routes admitted objectives to KIRA for planning.
    """

    def __init__(self, objective_runtime: Any):
        self.objective_runtime = objective_runtime
        self._seen_goals: set[str] = set()

    def handle_step(self, step: PlanStep, objective_id: str) -> dict[str, Any]:
        """Process an intake step for an objective."""
        obj = self.objective_runtime.get_objective(objective_id)
        if obj is None:
            raise ValueError(f"Objective {objective_id} not found")

        # Normalize goal definition
        normalized_goal = self._normalize(obj.goal_definition)

        # Dedupe check
        if self._is_duplicate(normalized_goal):
            return {
                "action": "dedupe_rejected",
                "reason": "Duplicate objective detected",
            }

        self._seen_goals.add(normalized_goal)

        # Classify severity if not set
        if obj.severity == Severity.MEDIUM:
            obj.severity = self._classify_severity(obj)

        return {
            "action": "admitted",
            "normalized_goal": normalized_goal,
            "severity": obj.severity.name,
        }

    def _normalize(self, goal: str) -> str:
        return goal.strip().lower()

    def _is_duplicate(self, normalized_goal: str) -> bool:
        return normalized_goal in self._seen_goals

    def _classify_severity(self, obj: Objective) -> Severity:
        """Simple keyword-based severity classification."""
        goal_lower = obj.goal_definition.lower()
        if any(kw in goal_lower for kw in ["critical", "urgent", "security", "breach"]):
            return Severity.CRITICAL
        if any(kw in goal_lower for kw in ["important", "high-priority", "compliance"]):
            return Severity.HIGH
        if any(kw in goal_lower for kw in ["maintenance", "cleanup", "stale"]):
            return Severity.LOW
        return Severity.MEDIUM

    def health(self) -> dict[str, Any]:
        return {
            "controller": "intake",
            "status": "active",
            "known_goals": len(self._seen_goals),
        }
