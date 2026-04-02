"""
Aether Agent Layer — Governance Controller
Top-level authority over the agent layer. Enforces policy, budget ceilings,
kill switch, audit invariants, approval governance, conflict arbitration,
and autonomy boundaries.

Hierarchy: Governance -> KIRA -> Domain Controllers -> Teams -> Workers
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("aether.governance")


@dataclass
class GovernancePolicy:
    """Top-level policy governing the agent layer."""
    max_daily_budget_usd: float = 50.0
    max_hourly_budget_usd: float = 5.0
    max_concurrent_objectives: int = 20
    max_actions_per_cycle: int = 100
    require_human_approval: bool = True  # vNext: always True
    allow_autonomous_maintenance: bool = True
    maintenance_policy_scope: str = "low_risk_only"
    kill_switch_engaged: bool = False
    allowed_mutation_classes: list[int] = field(default_factory=lambda: [1, 2, 3, 4, 5])
    auto_approve_classes: list[int] = field(default_factory=list)  # vNext: empty (all need approval)


class GovernanceController:
    """
    Top-level governance authority. All controllers and runtimes must
    respect governance decisions. Governance can:
    - Engage/release the kill switch
    - Set/modify budget ceilings
    - Approve or reject policy changes
    - Arbitrate conflicts between controllers
    - Enforce audit invariants
    """

    def __init__(self, policy: GovernancePolicy | None = None):
        self.policy = policy or GovernancePolicy()
        self._budget_spent_daily: float = 0.0
        self._budget_spent_hourly: float = 0.0
        self._active_objective_count: int = 0
        self._audit_log: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Kill switch
    # ------------------------------------------------------------------

    def engage_kill_switch(self, reason: str = "") -> None:
        self.policy.kill_switch_engaged = True
        self._audit("kill_switch_engaged", {"reason": reason})
        logger.critical(f"GOVERNANCE: Kill switch engaged — {reason}")

    def release_kill_switch(self, operator: str = "") -> None:
        self.policy.kill_switch_engaged = False
        self._audit("kill_switch_released", {"operator": operator})
        logger.warning(f"GOVERNANCE: Kill switch released by {operator}")

    @property
    def is_halted(self) -> bool:
        return self.policy.kill_switch_engaged

    # ------------------------------------------------------------------
    # Budget enforcement
    # ------------------------------------------------------------------

    def check_budget(self, estimated_cost: float = 0.0) -> bool:
        """Returns True if the action is within budget."""
        if self._budget_spent_hourly + estimated_cost > self.policy.max_hourly_budget_usd:
            logger.warning("GOVERNANCE: Hourly budget ceiling reached")
            return False
        if self._budget_spent_daily + estimated_cost > self.policy.max_daily_budget_usd:
            logger.warning("GOVERNANCE: Daily budget ceiling reached")
            return False
        return True

    def record_spend(self, amount: float) -> None:
        self._budget_spent_hourly += amount
        self._budget_spent_daily += amount

    def reset_hourly_budget(self) -> None:
        self._budget_spent_hourly = 0.0

    def reset_daily_budget(self) -> None:
        self._budget_spent_daily = 0.0
        self._budget_spent_hourly = 0.0

    # ------------------------------------------------------------------
    # Objective admission
    # ------------------------------------------------------------------

    def can_admit_objective(self) -> bool:
        if self.is_halted:
            return False
        if self._active_objective_count >= self.policy.max_concurrent_objectives:
            logger.warning("GOVERNANCE: Objective concurrency ceiling reached")
            return False
        return True

    def track_objective_started(self) -> None:
        self._active_objective_count += 1

    def track_objective_ended(self) -> None:
        self._active_objective_count = max(0, self._active_objective_count - 1)

    # ------------------------------------------------------------------
    # Approval governance
    # ------------------------------------------------------------------

    def requires_human_approval(self, mutation_class: int) -> bool:
        """In vNext, all classes require human approval."""
        if not self.policy.require_human_approval:
            return mutation_class not in self.policy.auto_approve_classes
        return True

    # ------------------------------------------------------------------
    # Conflict arbitration
    # ------------------------------------------------------------------

    def arbitrate_conflict(
        self,
        controller_a: str,
        controller_b: str,
        conflict_description: str,
    ) -> dict[str, str]:
        """Log and arbitrate a conflict between controllers."""
        decision = {
            "controllers": f"{controller_a} vs {controller_b}",
            "conflict": conflict_description,
            "resolution": "escalate_to_operator",
        }
        self._audit("conflict_arbitration", decision)
        logger.info(f"GOVERNANCE: Conflict arbitrated — {decision}")
        return decision

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------

    def _audit(self, action: str, details: dict[str, Any]) -> None:
        self._audit_log.append({"action": action, "details": details})

    @property
    def audit_trail(self) -> list[dict[str, Any]]:
        return list(self._audit_log)

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        return {
            "controller": "governance",
            "status": "halted" if self.is_halted else "active",
            "kill_switch": self.is_halted,
            "budget_daily_spent": self._budget_spent_daily,
            "budget_daily_limit": self.policy.max_daily_budget_usd,
            "active_objectives": self._active_objective_count,
            "max_objectives": self.policy.max_concurrent_objectives,
        }
