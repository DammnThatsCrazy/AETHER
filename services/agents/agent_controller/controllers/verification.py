"""
Aether Agent Layer — Verification Controller
Handles evidence sufficiency, provenance checks, schema checks,
consistency checks, quality scoring, and policy verification.
"""

from __future__ import annotations

import logging
from typing import Any

from models.evidence import (
    VerificationDecision,
    VerificationResult,
)
from models.objectives import PlanStep

logger = logging.getLogger("aether.controllers.verification")


class VerificationController:
    """
    Runs verification checks on candidate facts and evidence.
    Determines whether facts meet quality and provenance standards
    before they can be staged as mutations.
    """

    def __init__(self):
        self._teams: dict[str, Any] = {}
        self._results: list[VerificationResult] = []
        self._checks = [
            "evidence_sufficiency",
            "provenance",
            "schema_conformance",
            "consistency",
            "quality_score",
        ]

    def register_team(self, team_name: str, team: Any) -> None:
        self._teams[team_name] = team

    def handle_step(self, step: PlanStep, objective_id: str) -> dict[str, Any]:
        """Execute a verification step on candidate facts."""
        fact_ids = step.input_schema.get("fact_ids", [])
        entity_id = step.input_schema.get("entity_id", "")

        # Run all checks
        passed = []
        failed = []
        for check in self._checks:
            if self._run_check(check, fact_ids):
                passed.append(check)
            else:
                failed.append(check)

        score = len(passed) / len(self._checks) if self._checks else 0.0
        decision = self._decide(score, failed)

        result = VerificationResult(
            objective_id=objective_id,
            entity_id=entity_id,
            fact_ids=fact_ids,
            checks_run=list(self._checks),
            passed_checks=passed,
            failed_checks=failed,
            score=score,
            decision=decision,
        )
        self._results.append(result)

        logger.info(
            f"Verification: {decision.value} (score={score:.2f}) "
            f"for objective {objective_id[:8]}..."
        )
        return {
            "action": "verified",
            "verification_id": result.verification_id,
            "decision": decision.value,
            "score": score,
            "passed": passed,
            "failed": failed,
        }

    def _run_check(self, check_name: str, fact_ids: list[str]) -> bool:
        """Run a single verification check. Production: real check logic."""
        # Placeholder — all checks pass by default in dev
        return True

    def _decide(self, score: float, failed: list[str]) -> VerificationDecision:
        if score >= 0.8 and not failed:
            return VerificationDecision.PASSED
        if score >= 0.6:
            return VerificationDecision.NEEDS_REVIEW
        if failed:
            return VerificationDecision.FAILED
        return VerificationDecision.INCONCLUSIVE

    def get_results(self, objective_id: str) -> list[VerificationResult]:
        return [r for r in self._results if r.objective_id == objective_id]

    def health(self) -> dict[str, Any]:
        return {
            "controller": "verification",
            "status": "active",
            "teams": list(self._teams.keys()),
            "total_verifications": len(self._results),
            "checks_available": self._checks,
        }
