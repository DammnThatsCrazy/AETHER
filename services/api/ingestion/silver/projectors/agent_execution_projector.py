"""Silver projector for agent execution and evaluation events."""

from __future__ import annotations

from typing import Any

from shared.agent_lineage import vocabulary as lineage_vocab

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


_MAX_DELEGATION_DEPTH = 10_000
_CONTROL_MODES = frozenset(lineage_vocab.CONTROL_MODES)
_AUTHORITY_TYPES = frozenset(lineage_vocab.AUTHORITY_TYPES)

# High-cardinality lineage context blocks (observation-envelope v1.x). They may
# ride at the event top level or under ``context``; both snake_case (envelope
# wire) and camelCase (SDK wire) spellings are accepted.
_LINEAGE_BLOCKS = {
    "actor": ("actor_context", "actorContext"),
    "authority": ("authority_context", "authorityContext"),
    "execution": ("execution_context", "executionContext"),
    "protocol": ("protocol_context", "protocolContext"),
}


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part.capitalize() for part in rest)


def _lineage_block(event: dict[str, Any], context: dict[str, Any], block: str) -> dict[str, Any]:
    for holder in (event, context):
        for key in _LINEAGE_BLOCKS[block]:
            value = holder.get(key)
            if isinstance(value, dict):
                return value
    return {}


def _block_ref(block: dict[str, Any], name: str) -> str | None:
    return _source_reference(block.get(name) if name in block else block.get(_camel(name)))


def _bounded_depth(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 0 <= value <= _MAX_DELEGATION_DEPTH else None


def _control_mode(*candidates: Any) -> str:
    """First reported value that is in the vocabulary; otherwise ``UNKNOWN``.

    Control mode describes how authority flowed, never whether behaviour was
    legitimate, and an unrecognised value must not leak into Silver as a new
    category.
    """
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip() in _CONTROL_MODES:
            return candidate.strip()
    return "UNKNOWN"


def _authority_type(value: Any) -> str | None:
    """``None`` when no authority was reported; ``unknown`` when it is unrecognised."""
    ref = _source_reference(value)
    if ref is None:
        return None
    return ref if ref in _AUTHORITY_TYPES else "unknown"


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
    # Agent behavior taxonomy (WO-030). Dotted design names map onto these in
    # intelligence/agent_behavior/taxonomy.py.
    "agent_objective_created",
    "agent_objective_started",
    "agent_objective_modified",
    "agent_objective_completed",
    "agent_objective_failed",
    "agent_objective_abandoned",
    "agent_information_retrieved",
    "agent_source_consulted",
    "agent_context_received",
    "agent_decision_started",
    "agent_candidate_considered",
    "agent_candidate_rejected",
    "agent_action_selected",
    "agent_decision_completed",
    "agent_authorization_requested",
    "agent_authorization_granted",
    "agent_authorization_denied",
    "agent_tool_retried",
    "agent_tool_switched",
    "agent_terminated",
    "agent_task_returned",
    "agent_execution_started",
    "agent_execution_succeeded",
    "agent_execution_failed",
    "agent_execution_aborted",
    "agent_quote_received",
    "agent_price_evaluated",
    "agent_transaction_initiated",
    "agent_transaction_authorized",
    "agent_transaction_settled",
    "agent_transaction_failed",
    "agent_message_generated",
    "agent_memory_created",
    "agent_memory_retrieved",
    "agent_memory_updated",
    "agent_memory_invalidated",
    "agent_memory_expired",
})


def _bounded_int(value: Any) -> int | None:
    """Non-negative integer source measurement, or None."""
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if 0 <= number <= 10**9 else None


def _decimal_text(value: Any) -> str | None:
    """Keep a source amount as a decimal string; never coerce through float."""
    if isinstance(value, bool) or value is None:
        return None
    text = str(value).strip()
    if not text or len(text) > 64:
        return None
    try:
        from decimal import Decimal, InvalidOperation
        Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return text


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
        actor_ctx = _lineage_block(event, context, "actor")
        authority_ctx = _lineage_block(event, context, "authority")
        execution_ctx = _lineage_block(event, context, "execution")
        protocol_ctx = _lineage_block(event, context, "protocol")
        # A real run reference only. A trace correlates observations; it is not
        # a run, so it is never promoted into source_run_id / canonical_run_id.
        run_ref = _source_reference(
            p.get("runId") or p.get("run_id")
        ) or _block_ref(execution_ctx, "source_run_id")
        trace_ref = _source_reference(
            correlation.get("traceId") or correlation.get("trace_id")
        ) or _block_ref(execution_ctx, "trace_id")
        task_ref = _source_reference(
            p.get("taskId") or p.get("task_id")
        ) or _block_ref(execution_ctx, "task_id")
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
        # Source-reported principal. ``beneficiaryActorId`` is a claim about who
        # benefits, not a resolved principal: it is stored only as a reported
        # reference and canonical_principal_entity_id stays NULL here (canonical
        # resolution owns that column and never copies the claim).
        beneficiary_claim = _source_reference(
            context.get("beneficiaryActorId") or context.get("beneficiary_actor_id")
        )
        reported_principal_ref = (
            _block_ref(actor_ctx, "reported_principal_ref")
            or _block_ref(actor_ctx, "principal")
            or beneficiary_claim
        )
        authority_type = _authority_type(
            authority_ctx.get("authority_type", authority_ctx.get("authorityType"))
        )
        authority_ref = _block_ref(authority_ctx, "authority_ref")
        if not authority_ref and authority_type == "mandate":
            authority_ref = _block_ref(authority_ctx, "mandate_ref")
        elif not authority_ref and authority_type == "approval":
            authority_ref = _block_ref(authority_ctx, "approval_ref")
        validated_agent_ref = _source_reference(
            deployment.get("agentId") or deployment.get("agent_id")
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
            # Legacy correlation columns, kept for existing readers: ``run_id``
            # still falls back to the trace id and says so in
            # ``run_correlation_source``. Canonical lineage must use
            # ``source_run_id`` / ``canonical_run_id`` below instead.
            "run_id": run_ref or trace_ref,
            "run_correlation_source": "run_id" if run_ref else (
                "trace_id" if trace_ref else None
            ),
            "trace_id": trace_ref,
            "span_id": _source_reference(
                correlation.get("spanId") or correlation.get("span_id")
            ) or _block_ref(execution_ctx, "span_id"),
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
            ) or _block_ref(execution_ctx, "parent_run_id"),
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
            "principal_id": beneficiary_claim,
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
            "protocol_version": _block_ref(protocol_ctx, "protocol_version")
            or p.get("protocolVersion"),
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
            # Agent behavior references (WO-033). Source-reported references
            # only; behavior projectors decide what they mean.
            "objective_ref": _source_reference(p.get("objectiveId") or p.get("objective_id")),
            "parent_objective_ref": _source_reference(
                p.get("parentObjectiveId") or p.get("parent_objective_id")
            ),
            "candidate_ref": _source_reference(p.get("candidateId") or p.get("candidate_id")),
            "previous_tool_name": _source_reference(
                p.get("fromToolName") or p.get("previousToolName") or p.get("from_tool_name")
            ),
            "attempt": _bounded_int(p.get("attempt")),
            "latency_ms": _bounded_int(p.get("latencyMs") or p.get("latency_ms")),
            "memory_ref": _source_reference(p.get("memoryId") or p.get("memory_id")),
            "information_source_ref": _source_reference(
                p.get("sourceRef") or p.get("source_ref") or p.get("sourceId")
            ),
            "authorization_ref": _source_reference(
                p.get("authorizationId") or p.get("authorization_id")
            ),
            "amount": _decimal_text(p.get("amount")),
            "currency": _source_reference(p.get("currency")),
            # --- High-cardinality lineage (work order AO-3). Source values are
            # stored as reported and never overwritten; every *canonical_* /
            # *_entity_id resolution output below stays NULL until the lineage
            # resolver fills it.
            "source_run_id": run_ref,
            "canonical_run_id": None,
            "root_run_id": _source_reference(p.get("rootRunId") or p.get("root_run_id"))
            or _block_ref(execution_ctx, "root_run_id"),
            "agent_definition_id": validated_agent_ref
            or _source_reference(p.get("agentDefinitionId") or p.get("agent_definition_id"))
            or _block_ref(execution_ctx, "agent_definition_id"),
            "agent_instance_id": _source_reference(
                p.get("agentInstanceId") or p.get("agent_instance_id")
                or p.get("instanceId") or p.get("instance_id")
            ) or _block_ref(execution_ctx, "agent_instance_id"),
            "parent_agent_entity_id": None,
            "root_agent_entity_id": None,
            "reported_principal_ref": reported_principal_ref,
            "reported_principal_namespace": _block_ref(
                actor_ctx, "reported_principal_namespace"
            ),
            "canonical_principal_entity_id": None,
            "principal_resolution_status": "unresolved" if reported_principal_ref else None,
            # Actor roles are producer-reported entity references. They are kept
            # distinct (never collapsed into actor_id) and are NOT evidence of
            # principal attribution; that is decided by canonical resolution.
            "initiator_entity_id": _block_ref(actor_ctx, "initiator"),
            "executor_entity_id": _block_ref(actor_ctx, "executor"),
            "operator_entity_id": _block_ref(actor_ctx, "operator"),
            "beneficiary_entity_id": _block_ref(actor_ctx, "beneficiary"),
            "control_mode": _control_mode(
                execution_ctx.get("control_mode", execution_ctx.get("controlMode")),
                p.get("controlMode"), p.get("control_mode"),
            ),
            "authority_type": authority_type,
            "authority_ref": authority_ref,
            "delegation_depth": _bounded_depth(next(
                (
                    holder[key]
                    for holder, key in (
                        (execution_ctx, "delegation_depth"),
                        (execution_ctx, "delegationDepth"),
                        (p, "delegationDepth"),
                        (p, "delegation_depth"),
                    )
                    if holder.get(key) is not None
                ),
                None,
            )),
            "protocol": _block_ref(protocol_ctx, "protocol")
            or _source_reference(p.get("protocol")),
            "external_effect_ref": _source_reference(
                p.get("externalEffectRef") or p.get("external_effect_ref")
            ) or _block_ref(execution_ctx, "external_effect_ref"),
            # Derived by Aether, never accepted from the producer: a deployment
            # the registry validated is deployment_verified, everything else is
            # the producer's own report.
            "execution_verification_state": (
                "deployment_verified" if deployment else "source_reported"
            ),
            "parent_span_id": _source_reference(
                correlation.get("parentSpanId") or correlation.get("parent_span_id")
            ) or _block_ref(execution_ctx, "parent_span_id"),
        })
        return ProjectionResult(table="silver_agent_execution_facts", rows=[row])
