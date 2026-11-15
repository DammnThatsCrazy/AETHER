"""OpenAI Agents: agent runtime (traces) and tool bridge (function-call spans).

Input is a tracing export batch, ``{"data": [...]}``, whose items are
``{"object": "trace", ...}`` or ``{"object": "trace.span", ...}`` with
``span_data.type`` (``function``, ``agent``, ``generation``, ``handoff``, …).
The tenant forwards it from its own trace processor. Only traces and function
spans become observations: a trace is the agent's task (a claim), and a
function span is the call where the agent touched a system. MCP tool calls are
function spans too.

A correlation token in the trace's metadata applies to every span of that
trace in the batch, so a tool call joins to its task exactly. Provider object
IDs in a function's input or output (a Shopify GID, a Stripe ``pi_`` ID) bind
the call to the system-of-record object when the tenant has that account bound.
"""

from __future__ import annotations

from typing import Any, Mapping

from actions.agent_correlation.mappers._common import (
    MapperContext,
    MappingError,
    find_object_refs,
    find_tokens,
    opt_str,
    parse_time,
)
from shared.integration_contracts.correlation import CorrelationObservation

FAMILY = "openai"
MAX_ITEMS = 500


def map_export(ctx: MapperContext, record: Mapping[str, Any]) -> list[CorrelationObservation]:
    items = record.get("data")
    if not isinstance(items, list) or not items:
        raise MappingError("data must be a non-empty list of trace and span objects")
    if len(items) > MAX_ITEMS:
        raise MappingError(f"at most {MAX_ITEMS} items per export batch")

    traces: dict[str, Mapping[str, Any]] = {}
    spans: list[Mapping[str, Any]] = []
    for item in items:
        if not isinstance(item, Mapping):
            raise MappingError("every item must be an object")
        kind = item.get("object")
        if kind == "trace":
            traces[str(item.get("id") or "")] = item
        elif kind == "trace.span":
            spans.append(item)
    traces.pop("", None)

    trace_tokens = {tid: find_tokens(t.get("metadata")) for tid, t in traces.items()}
    first_span_time: dict[str, Any] = {}
    for span in spans:
        tid = str(span.get("trace_id") or "")
        started = span.get("started_at")
        if tid and started and (tid not in first_span_time or str(started) < str(first_span_time[tid])):
            first_span_time[tid] = started

    out: list[CorrelationObservation] = []
    for tid, trace in traces.items():
        when = trace.get("started_at") or first_span_time.get(tid)
        if not when:
            continue  # a trace with no time and no spans in this batch cannot be placed
        actors = []
        if opt_str(trace.get("group_id")):
            actors.append(f"openai_group:{trace['group_id']}")
        out.append(CorrelationObservation(
            tenant_id=ctx.tenant_id,
            observation_id=f"openai:trace:{tid}",
            source_role="agent_runtime",
            provider_family=FAMILY,
            occurred_at=parse_time(when, field_name="started_at"),
            correlation_tokens=trace_tokens.get(tid, ()),
            actor_refs=tuple(actors),
            infrastructure_refs=(f"openai_trace:{tid}",),
        ))

    for span in spans:
        data = span.get("span_data")
        if not isinstance(data, Mapping) or data.get("type") != "function":
            continue
        span_id = opt_str(span.get("id"))
        span_trace = opt_str(span.get("trace_id"))
        if not span_id or not span_trace:
            raise MappingError("function spans need id and trace_id")
        tokens = tuple(dict.fromkeys(
            trace_tokens.get(span_trace, ()) + find_tokens(data.get("input"), data.get("output"))
        ))[:8]
        out.append(CorrelationObservation(
            tenant_id=ctx.tenant_id,
            observation_id=f"openai:span:{span_id}",
            source_role="tool_bridge",
            provider_family=FAMILY,
            occurred_at=parse_time(span.get("ended_at") or span.get("started_at"), field_name="started_at"),
            object_refs=find_object_refs(ctx, data.get("input"), data.get("output")),
            correlation_tokens=tokens,
            infrastructure_refs=(f"openai_trace:{span_trace}",),
        ))
    if not out:
        raise MappingError("the batch holds no placeable trace or function span")
    return out


KINDS = {"export": ("agent_runtime", map_export)}
ROLES = frozenset({"agent_runtime", "tool_bridge"})
