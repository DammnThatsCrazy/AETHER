"""§32: agent execution events share canonical lineage refs (no per-event dialects)."""

from __future__ import annotations

import json
from pathlib import Path

REGISTRY = json.loads(
    (Path(__file__).parents[2] / "packages/shared/contracts/event-registry.json").read_text("utf-8")
)
EVENTS = {e["type"]: e for e in REGISTRY["events"]}

LINEAGE_EVENTS = (
    "agent_subagent_spawned", "agent_delegated_task", "agent_task_started",
    "agent_task_completed", "agent_task_failed", "agent_tool_invocation_observed",
    "agent_policy_evaluated", "agent_handoff",
)
SPAWN_EVENTS = ("agent_subagent_spawned", "agent_delegated_task", "agent_handoff")
COMMON = (
    "context.actor_context", "context.authority_context", "context.execution_context",
    "context.protocol_context", "properties.runId", "properties.parentRunId",
    "properties.rootRunId", "properties.agentDefinitionId", "properties.agentInstanceId",
    "properties.controlMode", "properties.delegationDepth",
)
SPAWN = ("properties.parentAgentId", "properties.childAgentId", "properties.rootAgentId")
# Ad-hoc dialects the work order forbids each event from inventing.
DIALECT_FIELDS = ("properties.workerId", "properties.agentRef", "properties.controller", "properties.parentAgent")
CLAIM_CLASSES = {"SOURCE_ASSERTED", "SOURCE_REFERENCE"}


def _fields(event: str) -> dict:
    return EVENTS[event]["fieldTrust"]["fields"]


def test_every_lineage_event_shares_the_common_refs():
    for event in LINEAGE_EVENTS:
        fields = _fields(event)
        for path in COMMON:
            assert path in fields, f"{event} missing {path}"


def test_spawn_delegation_handoff_share_parent_child_root_refs():
    for event in SPAWN_EVENTS:
        for path in SPAWN:
            assert path in _fields(event), f"{event} missing {path}"


def test_lineage_refs_are_claims_never_resolved_trust_classes():
    # Canonical run / agent entity / principal are resolved by Aether; a source
    # can only assert or reference them.
    for event in LINEAGE_EVENTS:
        fields = _fields(event)
        for path in (*COMMON, *(SPAWN if event in SPAWN_EVENTS else ())):
            assert fields[path]["trustClass"] in CLAIM_CLASSES, (event, path)


def test_events_do_not_invent_their_own_lineage_dialect():
    for event in LINEAGE_EVENTS:
        assert not set(DIALECT_FIELDS) & set(_fields(event)), event
