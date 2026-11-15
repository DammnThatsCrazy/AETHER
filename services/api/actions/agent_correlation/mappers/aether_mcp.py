"""Aether MCP: the first-party channel any agent platform reports through.

Agents on platforms without a public telemetry API (a Grok bot through a Team
Bot custom MCP server, an OpenAI Agent Builder workflow, a Claude or Cursor
agent) connect to Aether's MCP endpoint and call its tools. Each call becomes
an observation:

* ``task_registered`` — the agent declares a task and receives a token. A
  claim (``agent_runtime``); the principal it names is never treated as proof.
* ``tool_call_reported`` — the agent reports a call it made to another system
  (``tool_bridge``). Provider object IDs in its input or output bind it to the
  system-of-record object; a signature nonce lets an edge observer attest it.
* ``outcome_reported`` — the agent reports what came of the task.

``agent_platform`` names the platform (``xai_grok``, ``openai``, ``anthropic``,
``cursor``, ``custom``…) and becomes the observation's provider family.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from actions.agent_correlation.mappers._common import (
    MapperContext,
    MappingError,
    find_object_refs,
    find_tokens,
    opt_str,
    parse_time,
    require,
)
from shared.integration_contracts.correlation import CorrelationObservation, SignedRequestRef

_PLATFORM_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
_REF_RE = re.compile(r"^[A-Za-z0-9._:@/-]{1,128}$")


def _platform(record: Mapping[str, Any]) -> str:
    platform = str(require(record, "agent_platform"))
    if not _PLATFORM_RE.fullmatch(platform):
        raise MappingError("agent_platform must be a short lowercase token")
    return platform


def _ref(record: Mapping[str, Any], key: str) -> str:
    value = str(require(record, key))
    if not _REF_RE.fullmatch(value):
        raise MappingError(f"{key} has unsupported characters")
    return value


def _token(record: Mapping[str, Any]) -> tuple[str, ...]:
    tokens = find_tokens(require(record, "correlation_token"))
    if not tokens:
        raise MappingError("correlation_token is not an Aether correlation token")
    return tokens[:1]


def map_task_registered(ctx: MapperContext, record: Mapping[str, Any]) -> list[CorrelationObservation]:
    platform = _platform(record)
    task_ref = _ref(record, "task_ref")
    actors = []
    if opt_str(record.get("agent_ref")):
        actors.append(f"agent:{platform}:{_ref(record, 'agent_ref')}")
    return [CorrelationObservation(
        tenant_id=ctx.tenant_id,
        observation_id=f"aether_mcp:task:{task_ref}",
        source_role="agent_runtime",
        provider_family=platform,
        occurred_at=parse_time(record.get("registered_at"), field_name="registered_at"),
        correlation_tokens=_token(record),
        actor_refs=tuple(actors),
    )]


def map_tool_call_reported(ctx: MapperContext, record: Mapping[str, Any]) -> list[CorrelationObservation]:
    platform = _platform(record)
    call_id = _ref(record, "call_id")
    nonce = opt_str(record.get("signature_nonce"))
    return [CorrelationObservation(
        tenant_id=ctx.tenant_id,
        observation_id=f"aether_mcp:tool_call:{platform}:{call_id}",
        source_role="tool_bridge",
        provider_family=platform,
        occurred_at=parse_time(record.get("occurred_at"), field_name="occurred_at"),
        object_refs=find_object_refs(ctx, record.get("input"), record.get("output")),
        correlation_tokens=_token(record),
        # The agent's own report of its signature: an edge observer's verified
        # check of the same nonce is what attests it.
        signed_request=SignedRequestRef(request_id=f"sig_nonce:{nonce}", signature_verified=False) if nonce else None,
    )]


def map_outcome_reported(ctx: MapperContext, record: Mapping[str, Any]) -> list[CorrelationObservation]:
    platform = _platform(record)
    outcome_id = _ref(record, "outcome_id")
    return [CorrelationObservation(
        tenant_id=ctx.tenant_id,
        observation_id=f"aether_mcp:outcome:{platform}:{outcome_id}",
        source_role="agent_runtime",
        provider_family=platform,
        occurred_at=parse_time(record.get("occurred_at"), field_name="occurred_at"),
        object_refs=find_object_refs(ctx, record.get("summary"), record.get("evidence")),
        correlation_tokens=_token(record),
    )]


KINDS = {
    "task_registered": ("agent_runtime", map_task_registered),
    "tool_call_reported": ("tool_bridge", map_tool_call_reported),
    "outcome_reported": ("agent_runtime", map_outcome_reported),
}
