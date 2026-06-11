"""
Aether Service — Agent Economic Views

Per-agent budget usage, delegation policy views, and treasury runway.
Consumed by Profile360 and the commerce analytics surface.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from repositories.repos import (
    AgentEconomicIdentityRepository,
    DelegationRepository,
    PaymentIntentRepository,
    SettlementEventRepository,
)
from shared.common.common import utc_now
from shared.logger.logger import get_logger

logger = get_logger("aether.service.agent.economic")


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except InvalidOperation:
        return Decimal("0")


class AgentEconomicViews:
    """Aggregates per-agent economic data from repositories.

    All queries are tenant-scoped; no cross-tenant data is ever returned.
    """

    def __init__(
        self,
        payment_intents: Optional[PaymentIntentRepository] = None,
        settlements: Optional[SettlementEventRepository] = None,
        delegations: Optional[DelegationRepository] = None,
        identities: Optional[AgentEconomicIdentityRepository] = None,
    ) -> None:
        self._intents = payment_intents or PaymentIntentRepository()
        self._settlements = settlements or SettlementEventRepository()
        self._delegations = delegations or DelegationRepository()
        self._identities = identities or AgentEconomicIdentityRepository()

    async def budget_view(
        self,
        agent_id: str,
        tenant_id: str,
        limit: int = 500,
    ) -> dict[str, Any]:
        """Return current budget usage and burn rate for an agent.

        Derives spend from settlement records (authoritative) rather than
        intent status to avoid double-counting pending intents.
        """
        intents = await self._intents.list_for_agent(agent_id, tenant_id, limit=limit)
        settlements = await self._settlements.list_for_agent(agent_id, tenant_id, limit=limit)

        # Terminal settled statuses — all represent completed spend
        settled_statuses = {"settled", "paid", "success", "access_granted"}

        spend_by_currency: dict[str, Decimal] = {}
        for s in settlements:
            if s.get("status") in settled_statuses:
                currency = s.get("currency") or "UNKNOWN"
                spend_by_currency[currency] = (
                    spend_by_currency.get(currency, Decimal("0"))
                    + _decimal(s.get("amount"))
                )

        pending_count = sum(
            1 for i in intents
            if i.get("settlement_status") in {"pending", "submitted", "authorized"}
        )
        failed_count = sum(
            1 for s in settlements
            if s.get("status") in {"failed", "timeout"}
        )
        total_settled = sum(
            1 for s in settlements
            if s.get("status") in settled_statuses
        )

        # Economic identity holds pre-computed recurring spend and preferences
        identity = await self._identities.find_for_agent(agent_id, tenant_id)
        recurring_spend = (identity or {}).get("recurring_spend", {})

        return {
            "agent_id": agent_id,
            "tenant_id": tenant_id,
            "spend_by_currency": {k: str(v) for k, v in spend_by_currency.items()},
            "recurring_spend": recurring_spend,
            "intent_count": len(intents),
            "pending_intent_count": pending_count,
            "settled_count": total_settled,
            "failed_count": failed_count,
            "settlement_success_rate": (
                round(total_settled / len(settlements), 4) if settlements else None
            ),
            "computed_at": utc_now().isoformat(),
        }

    async def delegation_policy_view(
        self,
        agent_id: str,
        tenant_id: str,
    ) -> dict[str, Any]:
        """Return active delegations granted to and by this agent.

        Combines explicit delegation grants (from DelegationRepository) with
        subagent spawns (recorded by AgentLifecycleMapper as delegation rows).
        """
        # Delegations where this agent is the grantee (it acts on behalf of someone)
        received = await self._delegations.active_for(agent_id, tenant_id)

        # Delegations where this agent is the grantor (it delegated to others)
        granted = await self._delegations.find_many(
            filters={"grantor_entity_id": agent_id, "tenant_id": tenant_id},
            limit=200,
        )
        now_iso = utc_now().isoformat()
        active_granted = [
            d for d in granted
            if not d.get("revoked_at")
            and (not d.get("ends_at") or d["ends_at"] > now_iso)
        ]

        # Subagents: delegations granted to others with source=agent_subagent_spawned
        subagents = [
            d for d in active_granted
            if (d.get("metadata") or {}).get("source") == "agent_subagent_spawned"
        ]

        return {
            "agent_id": agent_id,
            "tenant_id": tenant_id,
            "received_delegation_count": len(received),
            "received_delegations": received,
            "granted_delegation_count": len(active_granted),
            "subagent_count": len(subagents),
            "subagents": [
                {
                    "agent_id": d.get("grantee_entity_id"),
                    "delegation_id": d.get("delegation_id"),
                    "scope": d.get("scope", {}),
                    "starts_at": d.get("starts_at"),
                }
                for d in subagents
            ],
            "computed_at": utc_now().isoformat(),
        }

    async def full_economic_profile(
        self,
        agent_id: str,
        tenant_id: str,
        limit: int = 500,
    ) -> dict[str, Any]:
        """Merge budget + delegation views into a single economic profile response."""
        budget = await self.budget_view(agent_id, tenant_id, limit=limit)
        delegation = await self.delegation_policy_view(agent_id, tenant_id)
        identity = await self._identities.find_for_agent(agent_id, tenant_id)

        return {
            "agent_id": agent_id,
            "tenant_id": tenant_id,
            "budget": budget,
            "delegation_policy": delegation,
            "economic_identity": identity,
            "computed_at": utc_now().isoformat(),
        }
