"""Silver projector for agent execution and evaluation events."""

from __future__ import annotations

from typing import Any
from .base import BaseProjector, ProjectionResult

_AGENT_TYPES = frozenset({
    "agent_task_started",
    "agent_task_completed",
    "agent_task_failed",
    "agent_step_observed",
    "agent_tool_call_observed",
    "agent_handoff_observed",
    "agent_evaluation_observed",
    "agent_cost_observed",
    "agent_grounding_observed",
    "agent_guardrail_observed",
    "agent_human_override_observed",
    "agentic_session_started",
    "agentic_session_completed",
    "agentic_session_abandoned",
    # Observed agent execution types (family "agent", silverProjection
    # "agent_execution_facts" per event-registry.json) routed through the
    # canonical spine. Types projecting to a DIFFERENT table (e.g.
    # agent_budget_observed → agent_cost_facts) are intentionally excluded.
    "a2h_interaction",
    "agent_activity_observed",
    "agent_attachment_observed",
    "agent_attachment_parsed_observed",
    "agent_authorized",
    "agent_capability_granted",
    "agent_capability_revoked",
    "agent_deauthorized",
    "agent_decision",
    "agent_delegated_task",
    "agent_disconnect_observed",
    "agent_email_address_observed",
    "agent_escalated_to_human",
    "agent_handoff",
    "agent_inbox_observed",
    "agent_mcp_connection_observed",
    "agent_message_received_observed",
    "agent_message_sent_observed",
    "agent_notification_observed",
    "agent_outcome_recorded",
    "agent_performance_snapshot_observed",
    "agent_permission_observed",
    "agent_policy_evaluated",
    "agent_portfolio_snapshot_observed",
    "agent_position_observed",
    "agent_registered",
    "agent_reply_observed",
    "agent_resource_requested",
    "agent_risk_signal_observed",
    "agent_strategy_observed",
    "agent_subagent_spawned",
    "agent_task",
    "agent_task_created",
    "agent_task_decomposed",
    "agent_thread_observed",
    "agent_tool_called",
    "agent_tool_invocation_observed",
    "agent_tool_observed",
    "agent_trade_fill_observed",
    "agent_trade_intent_observed",
    "agent_trade_order_observed",
    "agent_trade_rejection_observed",
    "agent_updated",
    "agentic_account_connected_observed",
    "agentic_account_disconnected_observed",
    "agentic_account_observed",
})


class AgentExecutionProjector(BaseProjector):
    handles = _AGENT_TYPES

    def project(self, event: dict[str, Any]) -> ProjectionResult | None:
        if event.get("type") not in self.handles:
            return None
        p = self._props(event)
        row = self._base_row(event)
        row.update({
            "event_name": event.get("type"),
            "agent_id": p.get("agentId") or p.get("workerId"),
            "task_id": p.get("taskId") or p.get("sessionId"),
            "model_id": p.get("modelId") or p.get("model"),
            "prompt_tokens": p.get("promptTokens"),
            "completion_tokens": p.get("completionTokens"),
            "cost_usd": p.get("costUsd") or p.get("cost"),
            "status": p.get("status"),
            "outcome": p.get("outcome") or p.get("status"),
            "grounding_sources": p.get("groundingSources"),
            "human_override": bool(p.get("humanOverride")),
            # Observed MCP / tool / risk / object context (drives bounded graph
            # emission in SilverGraphProjector._emit_agent_execution).
            "tool_name": p.get("toolName"),
            "server_name": p.get("serverName"),
            "server_url": p.get("serverUrl"),
            "protocol_version": p.get("protocolVersion"),
            "risk_level": p.get("riskLevel"),
            "reason_codes": p.get("reasonCodes"),
            "provider": p.get("provider"),
            "object_type": p.get("objectType"),
            "object_id": p.get("objectId"),
            # Financial observation context (external-account trade / portfolio
            # observations). Amounts are decimal strings, kept queryable as
            # first-class silver columns rather than only in the Bronze payload.
            "symbol": p.get("symbol"),
            "side": p.get("side"),
            "quantity": p.get("quantity"),
            "total_value": p.get("totalValue"),
            "external_order_id": p.get("externalOrderId"),
            "account_kind": p.get("accountKind"),
        })
        return ProjectionResult(table="silver_agent_execution_facts", rows=[row])
