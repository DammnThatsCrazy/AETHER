"""Agent Profile360 economic telemetry composer.

This module is additive to the existing ProfileComposer. It derives normalized,
frontend-friendly sections from repositories and graph-compatible records without
hardcoding a UI view or duplicating authoritative event data.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from repositories.repos import (
    AgentEconomicIdentityRepository,
    AgentExecutionRepository,
    BehaviorProfileRepository,
    DelegationRepository,
    PaymentIntentRepository,
    SettlementEventRepository,
)
from shared.common.common import utc_now


def _decimal(value: Any) -> Optional[Decimal]:
    """Parse a value into a Decimal, or None when absent/unparseable.

    Unknown is never coerced to 0: an invalid/absent amount returns None so a
    caller can skip it and no aggregate fabricates a zero. A parseable ``"0"``
    (an explicit zero) still returns ``Decimal("0")``.
    """
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _top(counter: Counter[str], limit: int = 10) -> list[dict[str, Any]]:
    return [{"id": key, "count": count} for key, count in counter.most_common(limit) if key]


class AgentProfile360EconomicComposer:
    """Composes graph-derived economic, delegation, trust, and temporal slices.

    The return shape is intentionally sectioned by future Profile360 surfaces:
    identity, behavioral, economic, communication, delegation, trust, temporal,
    and graph. Each section is built from normalized records so API routes can
    expose it directly or merge it into the broader ProfileComposer response.
    """

    def __init__(
        self,
        payment_intents: Optional[PaymentIntentRepository] = None,
        settlements: Optional[SettlementEventRepository] = None,
        economic_identities: Optional[AgentEconomicIdentityRepository] = None,
        executions: Optional[AgentExecutionRepository] = None,
        delegations: Optional[DelegationRepository] = None,
        behavior_profiles: Optional[BehaviorProfileRepository] = None,
    ) -> None:
        self._payment_intents = payment_intents or PaymentIntentRepository()
        self._settlements = settlements or SettlementEventRepository()
        self._economic_identities = economic_identities or AgentEconomicIdentityRepository()
        self._executions = executions or AgentExecutionRepository()
        self._delegations = delegations or DelegationRepository()
        self._behavior_profiles = behavior_profiles or BehaviorProfileRepository()

    async def compose(self, agent_id: str, tenant_id: str, limit: int = 100) -> dict[str, Any]:
        intents = await self._payment_intents.list_for_agent(agent_id, tenant_id, limit=limit)
        settlements = await self._settlements.list_for_agent(agent_id, tenant_id, limit=limit)
        economic_identity = await self._economic_identities.find_for_agent(agent_id, tenant_id)
        executions = await self._executions.list_for_agent(agent_id, tenant_id, limit=limit)
        active_delegations = await self._delegations.active_for(agent_id, tenant_id)
        behavior = await self._behavior_profiles.find_by_id(agent_id)

        provider_counts = Counter(i.get("provider", "") for i in intents)
        protocol_counts = Counter(i.get("protocol", "") for i in intents)
        capability_counts = Counter(i.get("capability_requested", "") for i in intents)
        endpoint_counts = Counter(i.get("endpoint", "") for i in intents)
        status_counts = Counter(i.get("settlement_status", "") for i in intents)
        settlement_status_counts = Counter(s.get("status", "") for s in settlements)

        spend_by_currency: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        abandoned_by_currency: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for intent in intents:
            currency = intent.get("currency") or "UNKNOWN"
            amount = _decimal(intent.get("amount"))
            if amount is None:
                # Unknown/unparseable amount: contributes nothing — never a
                # fabricated zero in a spend/abandoned rollup.
                continue
            if intent.get("settlement_status") in {"settled", "paid", "success"}:
                spend_by_currency[currency] += amount
            if intent.get("settlement_status") == "abandoned" or intent.get("abandoned_reason"):
                abandoned_by_currency[currency] += amount

        settled_count = sum(1 for s in settlements if s.get("status") in {"settled", "paid", "success"})
        failed_count = sum(1 for s in settlements if s.get("status") in {"failed", "timeout"})
        total_settlements = len(settlements)
        reliability = settled_count / total_settlements if total_settlements else None

        timeline = sorted(
            [
                {
                    "id": i.get("intent_id"),
                    "type": "payment_intent",
                    "timestamp": i.get("occurred_at"),
                    "status": i.get("settlement_status"),
                    "provider": i.get("provider"),
                    "capability": i.get("capability_requested"),
                    "amount": i.get("amount"),
                    "currency": i.get("currency"),
                }
                for i in intents
            ]
            + [
                {
                    "id": s.get("settlement_event_id"),
                    "type": "settlement_event",
                    "timestamp": s.get("occurred_at"),
                    "status": s.get("status"),
                    "provider": s.get("provider"),
                    "amount": s.get("amount"),
                    "currency": s.get("currency"),
                }
                for s in settlements
            ],
            key=lambda row: row.get("timestamp") or "",
            reverse=True,
        )[:limit]

        return {
            "agent_id": agent_id,
            "tenant_id": tenant_id,
            "identity": {
                "economic_identity": economic_identity or {},
                "protocol_affinity": _top(protocol_counts),
                "provider_ecosystem": _top(provider_counts),
            },
            "behavioral": {
                "execution_count": len(executions),
                "behavior_profile": behavior or {},
                "repeated_capabilities": _top(capability_counts),
            },
            "economic": {
                "payment_intent_count": len(intents),
                "settlement_event_count": len(settlements),
                "spend_by_currency": {k: str(v) for k, v in spend_by_currency.items()},
                "abandoned_value_by_currency": {k: str(v) for k, v in abandoned_by_currency.items()},
                "status_counts": dict(status_counts),
                "top_providers": _top(provider_counts),
                "top_capabilities": _top(capability_counts),
            },
            "communication": {
                "endpoints": _top(endpoint_counts),
                "protocols": _top(protocol_counts),
            },
            "delegation": {
                "active_delegations": active_delegations,
                "delegation_count": len(active_delegations),
            },
            "trust": {
                "successful_settlements": settled_count,
                "failed_settlements": failed_count,
                "settlement_reliability": reliability,
                "settlement_status_counts": dict(settlement_status_counts),
                "provider_preference_stability": _top(provider_counts, limit=3),
            },
            "temporal": {
                "timeline": timeline,
                "first_seen_at": timeline[-1]["timestamp"] if timeline else None,
                "last_seen_at": timeline[0]["timestamp"] if timeline else None,
            },
            "graph": {
                "nodes": [
                    {"id": agent_id, "type": "Agent"},
                    *[
                        {"id": i.get("intent_id"), "type": "PaymentIntent"}
                        for i in intents if i.get("intent_id")
                    ],
                    *[
                        {"id": s.get("settlement_event_id"), "type": "SettlementEvent"}
                        for s in settlements if s.get("settlement_event_id")
                    ],
                ],
                "edges": [
                    {"from": agent_id, "to": i.get("intent_id"), "type": "PAYS_FOR"}
                    for i in intents if i.get("intent_id")
                ] + [
                    {"from": s.get("intent_id"), "to": s.get("settlement_event_id"), "type": "SETTLED_AS"}
                    for s in settlements if s.get("intent_id") and s.get("settlement_event_id")
                ],
            },
            "computed_at": utc_now().isoformat(),
        }
