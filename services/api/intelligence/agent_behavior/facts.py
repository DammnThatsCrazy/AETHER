"""Provider-independent agent facts (WO-033).

Behavior projectors read :class:`AgentFact`, never provider payloads or raw
Silver rows. A fact is built from a ``silver_agent_execution_facts`` row: typed
columns win, and a small allow-list of camelCase payload keys fills columns
for rows written before the WO-033 migration. Nothing here infers meaning;
every field is what the source reported, kept as a reference.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Optional

_REF_MAX = 256

# column -> payload fallbacks (camelCase first, then snake_case)
_PAYLOAD_FALLBACK: dict[str, tuple[str, ...]] = {
    "objective_ref": ("objectiveId", "objective_id"),
    "parent_objective_ref": ("parentObjectiveId", "parent_objective_id"),
    "candidate_ref": ("candidateId", "candidate_id"),
    "previous_tool_name": ("fromToolName", "previousToolName"),
    "memory_ref": ("memoryId", "memory_id"),
    "information_source_ref": ("sourceRef", "sourceId", "source_ref"),
    "authorization_ref": ("authorizationId", "authorization_id"),
    "currency": ("currency",),
}


def _ref(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > _REF_MAX or any(ord(c) < 32 or ord(c) == 127 for c in text):
        return None
    return text


def _int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _decimal(value: Any) -> Optional[Decimal]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    return str(value or "")


@dataclass(frozen=True)
class AgentFact:
    event_id: str
    event_type: str
    tenant_id: str
    agent_ref: Optional[str]
    occurred_at: str
    deployment_id: Optional[str] = None
    run_id: Optional[str] = None
    task_ref: Optional[str] = None
    objective_ref: Optional[str] = None
    parent_objective_ref: Optional[str] = None
    decision_ref: Optional[str] = None
    candidate_ref: Optional[str] = None
    action_ref: Optional[str] = None
    action_type: Optional[str] = None
    tool_name: Optional[str] = None
    previous_tool_name: Optional[str] = None
    server_url: Optional[str] = None
    status: Optional[str] = None
    outcome: Optional[str] = None
    attempt: Optional[int] = None
    latency_ms: Optional[int] = None
    policy_id: Optional[str] = None
    policy_version: Optional[str] = None
    policy_decision: Optional[str] = None
    policy_reason_codes: tuple[str, ...] = ()
    authorization_ref: Optional[str] = None
    delegation_id: Optional[str] = None
    delegated_to_ref: Optional[str] = None
    parent_agent_ref: Optional[str] = None
    child_agent_ref: Optional[str] = None
    root_agent_ref: Optional[str] = None
    principal_id: Optional[str] = None
    resource_ref: Optional[str] = None
    object_type: Optional[str] = None
    object_id: Optional[str] = None
    memory_ref: Optional[str] = None
    information_source_ref: Optional[str] = None
    amount: Optional[Decimal] = None
    currency: Optional[str] = None
    model_id: Optional[str] = None
    human_override: bool = False
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def object_ref(self) -> Optional[str]:
        if self.object_type and self.object_id:
            return f"{self.object_type}:{self.object_id}"
        return self.candidate_ref

    def attr(self, *keys: str) -> Any:
        for key in keys:
            if key in self.attributes and self.attributes[key] not in (None, ""):
                return self.attributes[key]
        return None


def fact_from_row(row: dict[str, Any]) -> AgentFact:
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}

    def col(name: str) -> Any:
        value = row.get(name)
        if value in (None, "") and name in _PAYLOAD_FALLBACK:
            for key in _PAYLOAD_FALLBACK[name]:
                if payload.get(key) not in (None, ""):
                    return payload[key]
        return value

    codes = row.get("policy_reason_codes") or []
    return AgentFact(
        event_id=str(row.get("source_event_id") or ""),
        event_type=str(row.get("source_event_type") or row.get("event_name") or ""),
        tenant_id=str(row.get("tenant_id") or ""),
        agent_ref=_ref(row.get("agent_id")),
        occurred_at=_iso(row.get("occurred_at")),
        deployment_id=_ref(row.get("deployment_id")),
        run_id=_ref(row.get("run_id")),
        task_ref=_ref(row.get("task_ref") or row.get("task_id")),
        objective_ref=_ref(col("objective_ref")),
        parent_objective_ref=_ref(col("parent_objective_ref")),
        decision_ref=_ref(row.get("decision_ref") or payload.get("decisionId")),
        candidate_ref=_ref(col("candidate_ref")),
        action_ref=_ref(row.get("action_ref")),
        action_type=_ref(row.get("action_type")),
        tool_name=_ref(row.get("tool_name")),
        previous_tool_name=_ref(col("previous_tool_name")),
        server_url=_ref(row.get("server_url")),
        status=_ref(row.get("status")),
        outcome=_ref(row.get("outcome")),
        attempt=_int(row.get("attempt") if row.get("attempt") is not None else payload.get("attempt")),
        latency_ms=_int(row.get("latency_ms") if row.get("latency_ms") is not None else payload.get("latencyMs")),
        policy_id=_ref(row.get("policy_id")),
        policy_version=_ref(row.get("policy_version")),
        policy_decision=_ref(row.get("policy_decision")),
        policy_reason_codes=tuple(c for c in codes if isinstance(c, str)),
        authorization_ref=_ref(col("authorization_ref")),
        delegation_id=_ref(row.get("delegation_id")),
        delegated_to_ref=_ref(row.get("delegated_to_ref")),
        parent_agent_ref=_ref(row.get("parent_agent_ref")),
        child_agent_ref=_ref(row.get("child_agent_ref")),
        root_agent_ref=_ref(row.get("root_agent_ref")),
        principal_id=_ref(row.get("principal_id")),
        resource_ref=_ref(row.get("resource_ref")),
        object_type=_ref(row.get("object_type")),
        object_id=_ref(row.get("object_id")),
        memory_ref=_ref(col("memory_ref")),
        information_source_ref=_ref(col("information_source_ref")),
        amount=_decimal(row.get("amount") if row.get("amount") is not None else payload.get("amount")),
        currency=_ref(col("currency")),
        model_id=_ref(row.get("model_id")),
        human_override=bool(row.get("human_override")),
        attributes=dict(payload),
    )


def normalize_rows(rows: Iterable[dict[str, Any]], tenant_id: str) -> list[AgentFact]:
    """Tenant-filtered facts in deterministic occurrence order."""
    facts = [fact_from_row(r) for r in rows if r.get("tenant_id") == tenant_id]
    facts = [f for f in facts if f.event_id and f.event_type]
    seen: set[str] = set()
    unique: list[AgentFact] = []
    for f in sorted(facts, key=lambda f: (f.occurred_at, f.event_id)):
        if f.event_id in seen:
            continue
        seen.add(f.event_id)
        unique.append(f)
    return unique


def watermark(facts: Iterable[AgentFact]) -> Optional[str]:
    last = None
    for f in facts:
        key = f"{f.occurred_at}|{f.event_id}"
        last = key if last is None or key > last else last
    return last
