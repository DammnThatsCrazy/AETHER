"""Silver projector for agent execution and evaluation events."""

from __future__ import annotations

from typing import Any
from .base import BaseProjector, ProjectionResult

_SOURCE_REF_MAX_LENGTH = 256
_ECONOMIC_CORRELATION_EVENT_TYPES = frozenset({
    "agent_task_started",
    "agent_task_completed",
    "agent_task_failed",
    "agent_outcome_recorded",
})


def _source_reference(value: Any) -> str | None:
    """Keep external correlation references bounded and printable."""
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > _SOURCE_REF_MAX_LENGTH
        or any(ord(char) < 32 or ord(char) == 127 for char in normalized)
    ):
        return None
    return normalized


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
        context = event.get("context") or {}
        # This marker is added after deployment registry validation in the
        # ingestion decision. SDK-supplied agentDeployment data is not trusted
        # as a canonical agent/deployment join.
        deployment = event.get("validated_agent_deployment") or {}
        correlation = context.get("correlation") or {}
        event_name = str(event.get("type") or "")
        row = self._base_row(event)
        run_ref = _source_reference(p.get("runId") or p.get("run_id"))
        trace_ref = _source_reference(
            correlation.get("traceId") or correlation.get("trace_id")
        )
        task_ref = _source_reference(p.get("taskId") or p.get("task_id"))
        outcome_ref = _source_reference(p.get("outcomeId") or p.get("outcome_id"))
        # These are caller-reported record references for later exact lookup.
        # They do not make the SDK authoritative for payment state or value.
        payment_intent_ref = None
        settlement_event_ref = None
        if event_name in _ECONOMIC_CORRELATION_EVENT_TYPES:
            payment_intent_ref = _source_reference(
                p.get("paymentIntentId") or p.get("payment_intent_id")
            )
            settlement_event_ref = _source_reference(
                p.get("settlementEventId") or p.get("settlement_event_id")
            )
        if not outcome_ref and event_name in {
            "agent_task_completed", "agent_task_failed", "agent_outcome_recorded",
        }:
            # Every accepted event already has a stable source_event_id. Use it
            # as the source outcome reference when a producer omits outcomeId.
            outcome_ref = _source_reference(row.get("source_event_id"))
        spawn_parent_ref = _source_reference(
            p.get("parentAgentId") or p.get("parent_agent_id")
        )
        spawn_child_ref = _source_reference(
            p.get("childAgentId") or p.get("child_agent_id")
        )
        event_status = {
            "agent_task_started": "started",
            "agent_task_completed": "completed",
            "agent_task_failed": "failed",
        }.get(event_name)
        row.update({
            "event_name": event_name,
            # Registry-backed identity takes precedence over event properties
            # when an accepted event has validated deployment context.
            "agent_id": deployment.get("agentId") or deployment.get("agent_id") or p.get("agentId") or p.get("workerId"),
            "deployment_id": deployment.get("deploymentId") or deployment.get("deployment_id"),
            "run_id": run_ref or trace_ref,
            "run_correlation_source": "run_id" if run_ref else (
                "trace_id" if trace_ref else None
            ),
            "trace_id": trace_ref,
            "span_id": _source_reference(
                correlation.get("spanId") or correlation.get("span_id")
            ),
            "correlation_id": _source_reference(
                correlation.get("correlationId") or correlation.get("correlation_id")
            ),
            "causation_id": _source_reference(
                correlation.get("causationId") or correlation.get("causation_id")
            ),
            "delegation_id": _source_reference(
                p.get("delegationId") or p.get("delegation_id")
                or context.get("delegationId") or context.get("delegation_id")
            ),
            "delegated_to_ref": _source_reference(
                p.get("delegatedToAgentId") or p.get("delegated_to_agent_id")
                or p.get("targetAgentId") or p.get("target_agent_id")
                or (spawn_child_ref if event_name == "agent_subagent_spawned" else None)
            ),
            # Sub-agent spawn lineage. Source-reported references only; the
            # lineage reader treats them as claims until deployments resolve.
            "parent_agent_ref": spawn_parent_ref,
            "child_agent_ref": spawn_child_ref,
            "root_agent_ref": _source_reference(
                p.get("rootAgentId") or p.get("root_agent_id")
            ),
            "parent_run_id": _source_reference(
                p.get("parentRunId") or p.get("parent_run_id")
            ),
            # A delegation target is namespaced independently from the actor.
            # Authority resolution must not infer this from the actor provider.
            "delegated_to_namespace": _source_reference(
                p.get("delegatedToNamespace") or p.get("delegated_to_namespace")
            ),
            "action_ref": _source_reference(
                p.get("actionId") or p.get("action_id")
            ),
            "action_type": _source_reference(
                p.get("actionType") or p.get("action_type") or p.get("action")
            ),
            # An explicit source resource reference may be compared with
            # canonical delegation scope. Do not synthesize it from object
            # type/id: those source fields can have different semantics.
            "resource_ref": _source_reference(
                p.get("resourceRef") or p.get("resource_ref")
            ),
            "trigger_ref": _source_reference(
                p.get("triggerId") or p.get("trigger_id")
            ),
            "trigger_type": _source_reference(
                p.get("triggerType") or p.get("trigger_type")
            ),
            "decision_ref": _source_reference(
                p.get("decisionId") or p.get("decision_id")
            ),
            "policy_id": _source_reference(p.get("policyId") or p.get("policy_id")),
            "policy_version": _source_reference(
                p.get("policyVersion") or p.get("policy_version")
            ),
            "policy_decision": _source_reference(
                p.get("decision") or p.get("policyDecision") or p.get("policy_decision")
            ),
            "policy_reason_codes": [
                item[:128] for item in (p.get("reasonCodes") or p.get("policyReasonCodes") or [])
                if isinstance(item, str) and item.strip() and len(item) <= 256
                and not any(ord(char) < 32 or ord(char) == 127 for char in item)
            ][:32],
            "principal_id": _source_reference(
                context.get("beneficiaryActorId") or context.get("beneficiary_actor_id")
            ),
            "task_id": task_ref or _source_reference(
                p.get("sessionId") or p.get("session_id")
            ),
            "task_ref": task_ref,
            "outcome_ref": outcome_ref,
            "payment_intent_ref": payment_intent_ref,
            "settlement_event_ref": settlement_event_ref,
            "model_id": p.get("modelId") or p.get("model"),
            "prompt_tokens": p.get("promptTokens"),
            "completion_tokens": p.get("completionTokens"),
            "cost_usd": p.get("costUsd") or p.get("cost"),
            "status": _source_reference(p.get("status")) or event_status,
            "outcome": _source_reference(p.get("outcome") or p.get("status")) or (
                event_status if event_status in {"completed", "failed"} else None
            ),
            "grounding_sources": p.get("groundingSources"),
            "human_override": bool(p.get("humanOverride")),
            # Observed MCP / tool / risk / object context (drives bounded graph
            # emission in SilverGraphProjector._emit_agent_execution).
            "tool_name": _source_reference(p.get("toolName") or p.get("tool_name")),
            "resource_uri": p.get("resourceUri") or p.get("resource_uri"),
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
