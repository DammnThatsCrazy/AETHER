"""Canonical agent event taxonomy and runtime adapters (WO-030, WO-031).

The work orders name events in a dotted design vocabulary
(``agent.tool.invoked``). The event registry is snake_case and is the only
event namespace (ADR-AB-010). :data:`DOTTED_TO_CANONICAL` maps each design
name onto a registry type plus, where one registry type covers several design
events, the ``status`` it carries.

Adapters own acquire / validate / map / normalize / emit for one runtime
class. They translate a runtime's native record into canonical ``/v1/batch``
events and never infer behavior (INV-001, ADR-AB-001): a failed MCP call is
reported as a failed tool call, not as "the agent adapted".
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Optional

# design name -> (registry type, status carried in properties.status or None)
DOTTED_TO_CANONICAL: dict[str, tuple[str, Optional[str]]] = {
    # Objective
    "agent.objective.created": ("agent_objective_created", None),
    "agent.objective.started": ("agent_objective_started", None),
    "agent.objective.modified": ("agent_objective_modified", None),
    "agent.objective.completed": ("agent_objective_completed", None),
    "agent.objective.failed": ("agent_objective_failed", None),
    "agent.objective.abandoned": ("agent_objective_abandoned", None),
    # Information
    "agent.information.retrieved": ("agent_information_retrieved", None),
    "agent.source.consulted": ("agent_source_consulted", None),
    "agent.context.received": ("agent_context_received", None),
    # Decision
    "agent.decision.started": ("agent_decision_started", None),
    "agent.candidate.considered": ("agent_candidate_considered", None),
    "agent.candidate.rejected": ("agent_candidate_rejected", None),
    "agent.action.selected": ("agent_action_selected", None),
    "agent.decision.completed": ("agent_decision_completed", None),
    # Authority
    "agent.authorization.requested": ("agent_authorization_requested", None),
    "agent.authorization.granted": ("agent_authorization_granted", None),
    "agent.authorization.denied": ("agent_authorization_denied", None),
    "agent.authority.checked": ("agent_policy_evaluated", None),
    # Tools
    "agent.tool.invoked": ("agent_tool_invocation_observed", "invoked"),
    "agent.tool.succeeded": ("agent_tool_invocation_observed", "succeeded"),
    "agent.tool.failed": ("agent_tool_invocation_observed", "failed"),
    "agent.tool.retried": ("agent_tool_retried", None),
    "agent.tool.switched": ("agent_tool_switched", None),
    # Delegation
    "agent.task.delegated": ("agent_delegated_task", None),
    "agent.spawned": ("agent_subagent_spawned", None),
    "agent.terminated": ("agent_terminated", None),
    "agent.task.returned": ("agent_task_returned", None),
    # Execution
    "agent.execution.started": ("agent_execution_started", None),
    "agent.execution.succeeded": ("agent_execution_succeeded", None),
    "agent.execution.failed": ("agent_execution_failed", None),
    "agent.execution.aborted": ("agent_execution_aborted", None),
    # Economic
    "agent.quote.received": ("agent_quote_received", None),
    "agent.price.evaluated": ("agent_price_evaluated", None),
    "agent.transaction.initiated": ("agent_transaction_initiated", None),
    "agent.transaction.authorized": ("agent_transaction_authorized", None),
    "agent.transaction.settled": ("agent_transaction_settled", None),
    "agent.transaction.failed": ("agent_transaction_failed", None),
    # Communication
    "agent.message.received": ("agent_message_received_observed", None),
    "agent.message.generated": ("agent_message_generated", None),
    "agent.message.sent": ("agent_message_sent_observed", None),
    "agent.message.replied": ("agent_reply_observed", None),
    # Memory
    "agent.memory.created": ("agent_memory_created", None),
    "agent.memory.retrieved": ("agent_memory_retrieved", None),
    "agent.memory.updated": ("agent_memory_updated", None),
    "agent.memory.invalidated": ("agent_memory_invalidated", None),
    "agent.memory.expired": ("agent_memory_expired", None),
}

FAMILIES: dict[str, tuple[str, ...]] = {}
for _name in DOTTED_TO_CANONICAL:
    FAMILIES.setdefault(_name.split(".")[1], ())
    FAMILIES[_name.split(".")[1]] += (_name,)

OBJECTIVE_EVENTS = frozenset(t for d, (t, _) in DOTTED_TO_CANONICAL.items() if d.startswith("agent.objective."))
DECISION_EVENTS = frozenset({
    "agent_decision_started", "agent_candidate_considered", "agent_candidate_rejected",
    "agent_action_selected", "agent_decision_completed", "agent_decision",
})
AUTHORITY_EVENTS = frozenset({
    "agent_authorization_requested", "agent_authorization_granted",
    "agent_authorization_denied", "agent_policy_evaluated",
})
TOOL_EVENTS = frozenset({
    "agent_tool_invocation_observed", "agent_tool_called", "agent_tool_observed",
    "agent_tool_retried", "agent_tool_switched",
})
EXECUTION_EVENTS = frozenset({
    "agent_execution_started", "agent_execution_succeeded",
    "agent_execution_failed", "agent_execution_aborted",
})
ECONOMIC_EVENTS = frozenset(t for d, (t, _) in DOTTED_TO_CANONICAL.items()
                            if d.split(".")[1] in {"quote", "price", "transaction"})
INFORMATION_EVENTS = frozenset({
    "agent_information_retrieved", "agent_source_consulted", "agent_context_received",
})
MEMORY_EVENTS = frozenset(t for d, (t, _) in DOTTED_TO_CANONICAL.items() if d.startswith("agent.memory."))
COMMUNICATION_EVENTS = frozenset({
    "agent_message_received_observed", "agent_message_generated",
    "agent_message_sent_observed", "agent_reply_observed",
})
DELEGATION_EVENTS = frozenset({
    "agent_delegated_task", "agent_subagent_spawned", "agent_terminated", "agent_task_returned",
    "agent_handoff",
})
TASK_EVENTS = frozenset({
    "agent_task_started", "agent_task_completed", "agent_task_failed", "agent_outcome_recorded",
    "agent_task_created",
})


def canonical_event(dotted: str) -> tuple[str, Optional[str]]:
    try:
        return DOTTED_TO_CANONICAL[dotted]
    except KeyError:
        raise ValueError(f"unknown agent design event {dotted!r}") from None


# --- adapters ---------------------------------------------------------------

ADAPTER_CLASSES: tuple[str, ...] = (
    "generic_runtime", "mcp", "model_gateway", "browser_automation",
    "custom_orchestrator", "wallet_payment", "commerce", "communication",
)

# Keys never carried into canonical properties, whatever the runtime sends.
# Ingestion scrubs sensitive keys again; content keys are dropped here so an
# adapter never forwards prompt/response/message bodies (INV-006, WO-032).
_DROP_KEYS = frozenset({
    "prompt", "completion", "response", "content", "messages", "body", "text",
    "reasoning", "thoughts", "chain_of_thought", "chainOfThought", "arguments_raw",
})


class AdapterError(ValueError):
    """A runtime record the adapter cannot map. Callers reject, never guess."""


@dataclass(frozen=True)
class CanonicalEvent:
    type: str
    message_id: str
    timestamp: str
    properties: dict[str, Any]

    def to_batch_event(self) -> dict[str, Any]:
        return {"type": self.type, "messageId": self.message_id,
                "timestamp": self.timestamp, "properties": self.properties}


def _message_id(adapter: str, source_id: str, canonical_type: str) -> str:
    material = json.dumps([adapter, source_id, canonical_type], separators=(",", ":"))
    return "abi_" + hashlib.sha256(material.encode()).hexdigest()[:32]


def _clean_props(props: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in props.items() if k not in _DROP_KEYS and v is not None}


def _require(record: dict[str, Any], *keys: str) -> None:
    missing = [k for k in keys if record.get(k) in (None, "")]
    if missing:
        raise AdapterError(f"missing {', '.join(missing)}")


def _emit(adapter: str, record: dict[str, Any], dotted: str, props: dict[str, Any]) -> CanonicalEvent:
    canonical_type, status = canonical_event(dotted)
    props = _clean_props(props)
    if status and "status" not in props:
        props["status"] = status
    return CanonicalEvent(
        type=canonical_type,
        message_id=_message_id(adapter, str(record["id"]), canonical_type),
        timestamp=str(record["timestamp"]),
        properties=props,
    )


def _generic(record: dict[str, Any]) -> list[CanonicalEvent]:
    """A runtime that already speaks the design vocabulary."""
    _require(record, "id", "timestamp", "event", "agentId")
    props = dict(record.get("properties") or {})
    props["agentId"] = record["agentId"]
    return [_emit("generic_runtime", record, str(record["event"]), props)]


def _mcp(record: dict[str, Any]) -> list[CanonicalEvent]:
    """MCP ``tools/call`` request/response pairs."""
    _require(record, "id", "timestamp", "agentId", "method")
    if record["method"] != "tools/call":
        raise AdapterError(f"unsupported MCP method {record['method']!r}")
    params = record.get("params") or {}
    tool = params.get("name")
    if not tool:
        raise AdapterError("tools/call without a tool name")
    props = {
        "agentId": record["agentId"], "toolName": tool,
        "serverName": record.get("serverName"), "serverUrl": record.get("serverUrl"),
        "runId": record.get("runId"), "decisionId": record.get("decisionId"),
        "latencyMs": record.get("latencyMs"), "attempt": record.get("attempt"),
    }
    if "error" in record and record["error"]:
        err = record["error"] if isinstance(record["error"], dict) else {}
        props["errorCode"] = err.get("code")
        return [_emit("mcp", record, "agent.tool.failed", props)]
    if "result" in record:
        props["isError"] = bool((record.get("result") or {}).get("isError"))
        dotted = "agent.tool.failed" if props["isError"] else "agent.tool.succeeded"
        return [_emit("mcp", record, dotted, props)]
    return [_emit("mcp", record, "agent.tool.invoked", props)]


def _model_gateway(record: dict[str, Any]) -> list[CanonicalEvent]:
    """A model call is an information retrieval by the agent; tokens and cost
    are measurements, prompt and completion text are never forwarded."""
    _require(record, "id", "timestamp", "agentId", "model")
    return [_emit("model_gateway", record, "agent.information.retrieved", {
        "agentId": record["agentId"], "sourceRef": f"model:{record['model']}",
        "modelId": record["model"], "promptTokens": record.get("promptTokens"),
        "completionTokens": record.get("completionTokens"),
        "latencyMs": record.get("latencyMs"), "runId": record.get("runId"),
        "status": "failed" if record.get("error") else "succeeded",
    })]


def _browser(record: dict[str, Any]) -> list[CanonicalEvent]:
    _require(record, "id", "timestamp", "agentId", "action")
    status = record.get("status") or "succeeded"
    dotted = "agent.tool.failed" if status == "failed" else "agent.tool.succeeded"
    return [_emit("browser_automation", record, dotted, {
        "agentId": record["agentId"], "toolName": f"browser.{record['action']}",
        "objectType": "url" if record.get("url") else None, "objectId": record.get("url"),
        "latencyMs": record.get("latencyMs"), "runId": record.get("runId"),
    })]


_WALLET_STATES = {
    "quoted": "agent.quote.received",
    "initiated": "agent.transaction.initiated",
    "authorized": "agent.transaction.authorized",
    "settled": "agent.transaction.settled",
    "failed": "agent.transaction.failed",
}


def _wallet(record: dict[str, Any]) -> list[CanonicalEvent]:
    _require(record, "id", "timestamp", "agentId", "state")
    dotted = _WALLET_STATES.get(str(record["state"]))
    if not dotted:
        raise AdapterError(f"unsupported wallet state {record['state']!r}")
    return [_emit("wallet_payment", record, dotted, {
        "agentId": record["agentId"], "amount": record.get("amount"),
        "currency": record.get("currency"), "objectType": "wallet" if record.get("wallet") else None,
        "objectId": record.get("wallet"), "resourceRef": record.get("protocol"),
        "authorizationId": record.get("authorizationId"), "runId": record.get("runId"),
        "decisionId": record.get("decisionId"),
    })]


ADAPTERS: dict[str, Callable[[dict[str, Any]], list[CanonicalEvent]]] = {
    "generic_runtime": _generic,
    "custom_orchestrator": _generic,
    "commerce": _generic,
    "communication": _generic,
    "mcp": _mcp,
    "model_gateway": _model_gateway,
    "browser_automation": _browser,
    "wallet_payment": _wallet,
}


def map_runtime_record(adapter_class: str, record: dict[str, Any]) -> list[dict[str, Any]]:
    """Map one native runtime record to canonical ``/v1/batch`` events."""
    if adapter_class not in ADAPTERS:
        raise AdapterError(f"unknown adapter class {adapter_class!r}")
    return [e.to_batch_event() for e in ADAPTERS[adapter_class](record)]
