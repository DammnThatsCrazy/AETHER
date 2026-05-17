"""
Aether Service — Policy Engine
Evaluates price/budget/asset/network policies and produces a PolicyDecision.
Day-1 posture: approval_required=True for every spend class.
"""

from __future__ import annotations

from typing import Optional

from shared.logger.logger import get_logger

from .commerce_models import (
    BudgetPolicy,
    PolicyDecision,
    PolicyOutcome,
    ProtectedResource,
)
from .commerce_store import get_commerce_store

logger = get_logger("aether.service.x402.policies")

# Day-1 GA: mandatory approval on all spend classes.
DEFAULT_APPROVAL_REQUIRED_ALL = True


class PolicyEngine:
    """Evaluates policies for a challenge and returns a decision."""

    def __init__(self) -> None:
        self._store = get_commerce_store()
        self._approval_required_all = DEFAULT_APPROVAL_REQUIRED_ALL

    def set_mandatory_approval(self, enabled: bool) -> None:
        """Admin-only toggle. Day-1 GA locks this True."""
        self._approval_required_all = enabled

    async def evaluate(
        self,
        tenant_id: str,
        challenge_id: str,
        resource: ProtectedResource,
        requester_id: str,
        amount_usd: float,
        asset_symbol: str,
        chain: str,
    ) -> PolicyDecision:
        """Run all policies and produce a decision."""
        active_rules: list[str] = []
        rationale_parts: list[str] = []

        # 1. Asset/network compatibility
        if resource.accepted_assets and asset_symbol not in resource.accepted_assets:
            decision = PolicyDecision(
                tenant_id=tenant_id,
                challenge_id=challenge_id,
                outcome=PolicyOutcome.DENY,
                active_rules=["asset_compatibility"],
                denial_reason=f"Asset {asset_symbol} not accepted by resource",
                requires_approval=False,
                rationale=f"Resource {resource.resource_id} accepts {resource.accepted_assets}",
            )
            await self._store.put_policy_decision(decision)
            return decision

        if resource.accepted_chains and chain not in resource.accepted_chains:
            decision = PolicyDecision(
                tenant_id=tenant_id,
                challenge_id=challenge_id,
                outcome=PolicyOutcome.DENY,
                active_rules=["chain_compatibility"],
                denial_reason=f"Chain {chain} not accepted by resource",
                requires_approval=False,
                rationale=f"Resource {resource.resource_id} accepts {resource.accepted_chains}",
            )
            await self._store.put_policy_decision(decision)
            return decision

        active_rules.append("asset_compatibility")
        active_rules.append("chain_compatibility")

        # 2. Budget policy — per-transaction cap enforced if a policy exists for this requester
        budget_policy = await self._store.get_budget_policy(tenant_id, requester_id)
        if budget_policy is not None and budget_policy.per_transaction_cap_usd > 0:
            if amount_usd > budget_policy.per_transaction_cap_usd:
                decision = PolicyDecision(
                    tenant_id=tenant_id,
                    challenge_id=challenge_id,
                    outcome=PolicyOutcome.DENY,
                    active_rules=["budget_per_transaction_cap"],
                    denial_reason=(
                        f"Amount ${amount_usd:.2f} exceeds per-transaction cap "
                        f"${budget_policy.per_transaction_cap_usd:.2f} for {requester_id}"
                    ),
                    requires_approval=False,
                    rationale=f"Budget policy {budget_policy.policy_id} active for {requester_id}",
                )
                await self._store.put_policy_decision(decision)
                return decision
            active_rules.append("budget_per_transaction_cap")

        # 3. Price sanity
        if amount_usd != resource.price_usd:
            rationale_parts.append(
                f"amount_mismatch: challenge=${amount_usd} vs resource=${resource.price_usd}"
            )
            active_rules.append("price_sanity")

        # 4. Mandatory approval posture (Day-1 GA)
        requires_approval = (
            self._approval_required_all or resource.approval_required
        )
        if requires_approval:
            active_rules.append("mandatory_approval_all_spend_classes")
            rationale_parts.append(
                "Day-1 GA: approval required for all spend classes"
            )

        rationale = " | ".join(rationale_parts) if rationale_parts else "policies cleared"

        decision = PolicyDecision(
            tenant_id=tenant_id,
            challenge_id=challenge_id,
            outcome=(
                PolicyOutcome.REQUIRE_APPROVAL
                if requires_approval
                else PolicyOutcome.ALLOW
            ),
            active_rules=active_rules,
            denial_reason=None,
            requires_approval=requires_approval,
            rationale=rationale,
        )
        await self._store.put_policy_decision(decision)
        logger.info(
            f"policy evaluated: challenge={challenge_id} outcome={decision.outcome} "
            f"rules={active_rules}"
        )
        return decision

    async def simulate(
        self,
        tenant_id: str,
        resource: ProtectedResource,
        requester_id: str,
        amount_usd: float,
        asset_symbol: str,
        chain: str,
    ) -> PolicyDecision:
        """Dry-run evaluation — does not persist."""
        # Temporarily redirect put_policy_decision to a no-op
        saved_put = self._store.put_policy_decision

        async def _noop(d):
            return d

        self._store.put_policy_decision = _noop  # type: ignore
        try:
            return await self.evaluate(
                tenant_id,
                "sim_" + requester_id,
                resource,
                requester_id,
                amount_usd,
                asset_symbol,
                chain,
            )
        finally:
            self._store.put_policy_decision = saved_put  # type: ignore


_engine: Optional[PolicyEngine] = None


def get_policy_engine() -> PolicyEngine:
    global _engine
    if _engine is None:
        _engine = PolicyEngine()
    return _engine
