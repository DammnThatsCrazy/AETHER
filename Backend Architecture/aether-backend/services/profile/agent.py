"""Agent Profile360 full composer.

Returns a complete, tenant-scoped Profile360 shape for an autonomous agent,
composing identity, ownership, authorization, capabilities, delegation,
subagent graph, task history, decision history, tool usage, resource usage,
x402 flows, economic state, trust, risk, temporal, outcomes, and graph.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from repositories.repos import (
    AgentConfigRepository,
    AgentEconomicIdentityRepository,
    AgentExecutionRepository,
    BehaviorProfileRepository,
    DelegationRepository,
    PaymentIntentRepository,
    SettlementEventRepository,
)
from shared.common.common import utc_now


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _top(counter: Counter[str], limit: int = 10) -> list[dict[str, Any]]:
    return [{"id": key, "count": count} for key, count in counter.most_common(limit) if key]


class AgentProfile360Composer:
    """Composes a full Profile360 shape for an autonomous agent.

    Each section is built from normalized repository records so API routes can
    expose the full profile or any individual section directly.
    """

    def __init__(
        self,
        agent_configs: Optional[AgentConfigRepository] = None,
        executions: Optional[AgentExecutionRepository] = None,
        delegations: Optional[DelegationRepository] = None,
        payment_intents: Optional[PaymentIntentRepository] = None,
        settlements: Optional[SettlementEventRepository] = None,
        economic_identities: Optional[AgentEconomicIdentityRepository] = None,
        behavior_profiles: Optional[BehaviorProfileRepository] = None,
    ) -> None:
        self._agent_configs = agent_configs or AgentConfigRepository()
        self._executions = executions or AgentExecutionRepository()
        self._delegations = delegations or DelegationRepository()
        self._payment_intents = payment_intents or PaymentIntentRepository()
        self._settlements = settlements or SettlementEventRepository()
        self._economic_identities = economic_identities or AgentEconomicIdentityRepository()
        self._behavior_profiles = behavior_profiles or BehaviorProfileRepository()

    async def compose(self, agent_id: str, tenant_id: str, limit: int = 100) -> dict[str, Any]:
        """Return the full Profile360 shape for the given agent scoped to tenant."""
        # Fetch all data sources
        agent_config = await self._agent_configs.find_by_id(agent_id)
        executions = await self._executions.list_for_agent(agent_id, tenant_id, limit=limit)
        active_delegations = await self._delegations.active_for(agent_id, tenant_id)

        # Subagents: delegations where this agent is the grantor
        subagent_delegations = await self._delegations.find_many(
            filters={"grantor_entity_id": agent_id, "tenant_id": tenant_id},
            limit=limit,
        )

        intents = await self._payment_intents.list_for_agent(agent_id, tenant_id, limit=limit)
        settlements = await self._settlements.list_for_agent(agent_id, tenant_id, limit=limit)
        economic_identity = await self._economic_identities.find_for_agent(agent_id, tenant_id)
        behavior = await self._behavior_profiles.find_by_id(agent_id)

        # Ownership guard: only expose config if it belongs to this tenant
        if agent_config and agent_config.get("tenant_id") != tenant_id:
            agent_config = None

        # ── Computed counters ──────────────────────────────────────────────
        tool_counts: Counter[str] = Counter()
        resource_counts: Counter[str] = Counter()
        task_statuses: Counter[str] = Counter(e.get("status", "") for e in executions)

        for e in executions:
            # Tool usage from policy_log hints (best-effort)
            for tool in (e.get("policy_log") or {}).get("tools_used", []):
                tool_counts[str(tool)] += 1
            for resource in (e.get("policy_log") or {}).get("resources", []):
                resource_counts[str(resource)] += 1

        provider_counts: Counter[str] = Counter(i.get("provider", "") for i in intents)
        capability_counts: Counter[str] = Counter(i.get("capability_requested", "") for i in intents)
        protocol_counts: Counter[str] = Counter(i.get("protocol", "") for i in intents)

        spend_by_currency: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for intent in intents:
            currency = intent.get("currency") or "UNKNOWN"
            if intent.get("settlement_status") in {"settled", "paid", "success"}:
                spend_by_currency[currency] += _decimal(intent.get("amount"))

        settled_count = sum(1 for s in settlements if s.get("status") in {"settled", "paid", "success"})
        failed_count = sum(1 for s in settlements if s.get("status") in {"failed", "timeout"})
        total_settlements = len(settlements)
        reliability = settled_count / total_settlements if total_settlements else None

        # Risk score from behavior profile if available
        risk_score = (behavior or {}).get("risk_score", 0.0)
        anomaly_flags = (behavior or {}).get("anomaly_flags", [])

        # ── Timeline ──────────────────────────────────────────────────────
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

        # ── Graph ─────────────────────────────────────────────────────────
        nodes = [{"id": agent_id, "type": "Agent"}]
        edges: list[dict[str, Any]] = []

        for i in intents:
            if i.get("intent_id"):
                nodes.append({"id": i["intent_id"], "type": "PaymentIntent"})
                edges.append({"from": agent_id, "to": i["intent_id"], "type": "PAYS_FOR"})

        for s in settlements:
            if s.get("settlement_event_id"):
                nodes.append({"id": s["settlement_event_id"], "type": "SettlementEvent"})
            if s.get("intent_id") and s.get("settlement_event_id"):
                edges.append({"from": s["intent_id"], "to": s["settlement_event_id"], "type": "SETTLED_AS"})

        for d in subagent_delegations:
            grantee = d.get("grantee_entity_id")
            if grantee:
                nodes.append({"id": grantee, "type": "Subagent"})
                edges.append({"from": agent_id, "to": grantee, "type": "DELEGATES_TO"})

        return {
            "agent_id": agent_id,
            "tenant_id": tenant_id,
            "identity": {
                "agent_id": agent_id,
                "tenant_id": tenant_id,
                "model": (agent_config or {}).get("model"),
                "status": (agent_config or {}).get("status"),
                "registered_at": (agent_config or {}).get("created_at"),
                "name": (agent_config or {}).get("name"),
            },
            "ownership": {
                "owner_entity_id": (agent_config or {}).get("owner_entity_id"),
                "tenant_id": tenant_id,
                "policy_version": (agent_config or {}).get("policy_version"),
            },
            "authorization": {
                "risk_tolerance": (agent_config or {}).get("risk_tolerance", "medium"),
                "constraints": (agent_config or {}).get("constraints", {}),
            },
            "capabilities": {
                "tools": (agent_config or {}).get("tools", []),
                "top_capabilities": _top(capability_counts),
                "top_protocols": _top(protocol_counts),
            },
            "delegation": {
                "active_delegations": active_delegations,
                "active_delegation_count": len(active_delegations),
            },
            "subagent_graph": {
                "subagent_delegations": subagent_delegations,
                "subagent_count": len(subagent_delegations),
            },
            "task_history": {
                "execution_count": len(executions),
                "status_counts": dict(task_statuses),
                "recent_executions": executions[:10],
            },
            "decision_history": {
                "behavior_profile": behavior or {},
                "automation_ratio": (behavior or {}).get("automation_ratio", 0.0),
                "decision_latency_ms": (behavior or {}).get("decision_latency_ms", 0),
                "top_patterns": (behavior or {}).get("top_patterns", []),
            },
            "tool_usage": {
                "top_tools": _top(tool_counts),
            },
            "resource_usage": {
                "top_resources": _top(resource_counts),
                "top_providers": _top(provider_counts),
            },
            "x402_flows": {
                "payment_intent_count": len(intents),
                "settlement_event_count": len(settlements),
                "top_providers": _top(provider_counts),
                "top_capabilities": _top(capability_counts),
                "spend_by_currency": {k: str(v) for k, v in spend_by_currency.items()},
                "recent_intents": intents[:10],
                "recent_settlements": settlements[:10],
            },
            "economic_state": {
                "economic_identity": economic_identity or {},
                "spend_by_currency": {k: str(v) for k, v in spend_by_currency.items()},
                "provider_ecosystem": _top(provider_counts),
            },
            "trust": {
                "successful_settlements": settled_count,
                "failed_settlements": failed_count,
                "settlement_reliability": reliability,
                "provider_preference_stability": _top(provider_counts, limit=3),
            },
            "risk": {
                "risk_score": risk_score,
                "anomaly_flags": anomaly_flags,
                "risk_tolerance": (agent_config or {}).get("risk_tolerance", "medium"),
            },
            "temporal": {
                "timeline": timeline,
                "first_seen_at": timeline[-1]["timestamp"] if timeline else None,
                "last_seen_at": timeline[0]["timestamp"] if timeline else None,
            },
            "outcomes": {
                "execution_count": len(executions),
                "failed_count": sum(1 for e in executions if e.get("status") in {"failed", "error"}),
                "succeeded_count": sum(1 for e in executions if e.get("status") in {"completed", "success"}),
            },
            "graph": {
                "nodes": nodes,
                "edges": edges,
            },
            "computed_at": utc_now().isoformat(),
        }
