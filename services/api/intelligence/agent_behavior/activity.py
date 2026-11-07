"""Agent journeys, tools, information inputs and memory (WO-060–WO-063, WO-073).

Every structure here is rebuilt from facts. Tool results carry status and
latency only; information and memory are references, never content.
"""
from __future__ import annotations

from collections import defaultdict
from statistics import median
from typing import Any, Iterable, Optional

from intelligence.agent_behavior import contracts as c
from intelligence.agent_behavior.facts import AgentFact
from intelligence.agent_behavior.taxonomy import (
    DECISION_EVENTS, EXECUTION_EVENTS, INFORMATION_EVENTS, MEMORY_EVENTS, OBJECTIVE_EVENTS, TASK_EVENTS,
)

_TOOL_CALLS = frozenset({"agent_tool_invocation_observed", "agent_tool_called", "agent_tool_observed"})


def _step_kind(f: AgentFact) -> str:
    t = f.event_type
    if t in OBJECTIVE_EVENTS:
        return "objective"
    if t in DECISION_EVENTS:
        return "decision"
    if t in _TOOL_CALLS or t in {"agent_tool_retried", "agent_tool_switched"}:
        return "tool"
    if t in INFORMATION_EVENTS:
        return "information"
    if t in MEMORY_EVENTS:
        return "memory"
    if t in {"agent_subagent_spawned", "agent_delegated_task", "agent_task_returned", "agent_handoff"}:
        return "delegation"
    if t in EXECUTION_EVENTS or t.startswith("agent_transaction_"):
        return "execution"
    if t in {"agent_policy_evaluated"} or t.startswith("agent_authorization_"):
        return "authority"
    if t in TASK_EVENTS:
        return "task"
    return "other"


# --- AgentJourney (WO-060) -----------------------------------------------------

def agent_journey(facts: Iterable[AgentFact], root_agent: str, *,
                  handoffs: Iterable[dict[str, Any]] = ()) -> dict[str, Any]:
    """The run tree under ``root_agent`` as one ordered journey.

    The human journey is joined only by an explicit ``journeyId`` reported on
    the root's facts that matches a recorded handoff; otherwise the join stays
    ``unknown`` (no timing or session guesswork).
    """
    facts = list(facts)
    children: dict[str, list[str]] = defaultdict(list)
    for f in facts:
        if f.event_type == "agent_subagent_spawned" and f.child_agent_ref and f.agent_ref:
            if f.child_agent_ref not in children[f.agent_ref]:
                children[f.agent_ref].append(f.child_agent_ref)
    members, depth, stack = [], {root_agent: 0}, [root_agent]
    while stack:
        ref = stack.pop(0)
        if ref in members:
            continue
        members.append(ref)
        for kid in children.get(ref, []):
            if kid not in depth:
                depth[kid] = depth[ref] + 1
                stack.append(kid)
    mine = [f for f in facts if f.agent_ref in depth]
    steps = [{"seq": i + 1, "at": f.occurred_at, "agent": f.agent_ref, "depth": depth[f.agent_ref],
              "kind": _step_kind(f), "event_type": f.event_type, "event_id": f.event_id,
              "status": f.status or f.outcome, "tool": f.tool_name, "decision": f.decision_ref}
             for i, f in enumerate(mine)]
    root_journeys = {f.attr("journeyId", "journey_id") for f in mine if f.agent_ref == root_agent} - {None}
    matched = [h for h in handoffs if h.get("journey_id") in root_journeys]
    if matched:
        join = c.observed({"journey_id": matched[0]["journey_id"], "link_basis": matched[0].get("link_basis")},
                          [f.event_id for f in mine if f.attr("journeyId", "journey_id") == matched[0]["journey_id"]][:5])
    elif root_journeys:
        join = c.declared({"journey_id": sorted(root_journeys)[0]},
                          [f.event_id for f in mine if f.attr("journeyId", "journey_id")][:5],
                          reason="journey reported by the agent; no recorded handoff matches")
    else:
        join = c.unknown("no journey reference on the root agent's facts")
    outcome = next((s for s in reversed(steps) if s["agent"] == root_agent and s["kind"] == "task"
                    and s["event_type"] in {"agent_task_completed", "agent_task_failed"}), None)
    return {
        "root_agent": root_agent,
        "agents": [{"agent": m, "depth": depth[m]} for m in members],
        "steps": steps,
        "human_journey": join.to_dict(),
        "outcome": (c.observed(outcome["status"], [outcome["event_id"]]) if outcome
                    else c.unknown("root agent outcome not observed")).to_dict(),
        "span": {"start": steps[0]["at"] if steps else None, "end": steps[-1]["at"] if steps else None},
    }


# --- tools (WO-061) and failure resolution (WO-073) -------------------------------

def _pct(values: list[int], q: float) -> Optional[int]:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


def tool_invocations(facts: Iterable[AgentFact]) -> list[dict[str, Any]]:
    return [{
        "invocation_id": f.event_id, "agent": f.agent_ref, "tool": f.tool_name, "server": f.server_url,
        "status": f.status or "unknown", "attempt": f.attempt, "latency_ms": f.latency_ms,
        "decision": f.decision_ref, "task": f.task_ref, "at": f.occurred_at,
    } for f in facts if f.event_type in _TOOL_CALLS and f.tool_name]


def tool_entities(facts: Iterable[AgentFact]) -> list[dict[str, Any]]:
    by_tool: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for inv in tool_invocations(facts):
        by_tool[inv["tool"]].append(inv)
    out = []
    for tool, invs in sorted(by_tool.items()):
        done = [i for i in invs if i["status"] in {"succeeded", "failed"}]
        ok = sum(1 for i in done if i["status"] == "succeeded")
        lat = [i["latency_ms"] for i in invs if i["latency_ms"] is not None]
        out.append({
            "tool": tool,
            "servers": sorted({i["server"] for i in invs if i["server"]}),
            "agents": sorted({i["agent"] for i in invs if i["agent"]}),
            "invocations": len(invs),
            "with_result": len(done),
            "success_rate": round(ok / len(done), 4) if done else None,
            "success_rate_basis": c.DERIVED if done else c.UNKNOWN,
            "latency_p50_ms": int(median(lat)) if lat else None,
            "latency_p95_ms": _pct(lat, 0.95),
            "first_seen": min(i["at"] for i in invs), "last_seen": max(i["at"] for i in invs),
        })
    return out


def failure_resolution(facts: Iterable[AgentFact]) -> list[dict[str, Any]]:
    """Per (agent, task): failures, retries, switches and whether it resolved.

    Explicit ``agent_tool_retried`` / ``agent_tool_switched`` facts are observed;
    otherwise retry/switch is derived from the ordered tool results.
    """
    seqs: dict[tuple[str, str], list[AgentFact]] = defaultdict(list)
    for f in facts:
        if f.agent_ref and (f.event_type in _TOOL_CALLS | {"agent_tool_retried", "agent_tool_switched"}):
            seqs[(f.agent_ref, f.task_ref or f.run_id or "-")].append(f)
    episodes = []
    for (agent, task), seq in sorted(seqs.items()):
        failures, retries, switches = [], [], []
        last_failed: Optional[AgentFact] = None
        resolved_by = None
        for f in seq:
            if f.event_type == "agent_tool_retried":
                retries.append({"tool": f.tool_name, "event_id": f.event_id, "basis": c.OBSERVED})
                continue
            if f.event_type == "agent_tool_switched":
                switches.append({"from_tool": f.previous_tool_name, "to_tool": f.tool_name,
                                 "event_id": f.event_id, "basis": c.OBSERVED})
                continue
            if last_failed is not None and f.status in {"invoked", "succeeded", "failed"}:
                explicit = {r["event_id"] for r in retries} | {s["event_id"] for s in switches}
                if f.tool_name == last_failed.tool_name and not explicit & {f.event_id}:
                    retries.append({"tool": f.tool_name, "event_id": f.event_id, "basis": c.DERIVED})
                elif f.tool_name != last_failed.tool_name:
                    switches.append({"from_tool": last_failed.tool_name, "to_tool": f.tool_name,
                                     "event_id": f.event_id, "basis": c.DERIVED})
            if f.status == "failed":
                failures.append({"tool": f.tool_name, "event_id": f.event_id})
                last_failed = f
            elif f.status == "succeeded":
                if last_failed is not None and resolved_by is None:
                    resolved_by = f
                last_failed = None
        if not failures:
            continue
        episodes.append({
            "agent": agent, "task": task, "failures": failures, "retries": retries, "switches": switches,
            "resolved": resolved_by is not None,
            "resolution": ({"tool": resolved_by.tool_name, "event_id": resolved_by.event_id,
                            "strategy": "switch" if resolved_by.tool_name != failures[-1]["tool"] else "retry"}
                           if resolved_by else None),
            "basis": c.DERIVED,
        })
    return episodes


# --- information inputs (WO-062) ---------------------------------------------------

def information_inputs(facts: Iterable[AgentFact]) -> dict[str, Any]:
    facts = list(facts)
    inputs = [f for f in facts if f.event_type in INFORMATION_EVENTS]
    by_source: dict[str, dict[str, Any]] = {}
    for f in inputs:
        src = f.information_source_ref or "unidentified"
        s = by_source.setdefault(src, {"source": src, "uses": 0, "agents": set(), "decisions": set(),
                                       "first_seen": f.occurred_at, "evidence": []})
        s["uses"] += 1
        s["agents"].add(f.agent_ref)
        if f.decision_ref:
            s["decisions"].add(f.decision_ref)
        if len(s["evidence"]) < 10:
            s["evidence"].append(f.event_id)
    failed_decisions = {f.decision_ref for f in facts if f.decision_ref and
                        (f.status == "failed" or f.event_type in {"agent_execution_failed", "agent_transaction_failed"})}
    out = []
    for s in sorted(by_source.values(), key=lambda s: s["source"]):
        decisions = sorted(d for d in s["decisions"] if d)
        out.append({
            "source": s["source"], "uses": s["uses"], "agents": sorted(a for a in s["agents"] if a),
            "decisions": decisions,
            "decisions_with_failure": sorted(set(decisions) & failed_decisions),
            "failure_association": c.derived(
                round(len(set(decisions) & failed_decisions) / len(decisions), 4), s["evidence"],
                reason="co-occurrence only; not a causal claim").to_dict() if decisions else
                c.unknown("source not linked to any decision").to_dict(),
            "first_seen": s["first_seen"],
        })
    unattributed = sum(1 for f in inputs if not f.decision_ref)
    return {"sources": out, "inputs": len(inputs), "inputs_without_decision": unattributed}


# --- memory lifecycle (WO-063) ---------------------------------------------------------

_MEM_STATE = {
    "agent_memory_created": "created", "agent_memory_retrieved": "retrieved",
    "agent_memory_updated": "updated", "agent_memory_invalidated": "invalidated",
    "agent_memory_expired": "expired",
}


def memory_lifecycle(facts: Iterable[AgentFact]) -> list[dict[str, Any]]:
    items: dict[str, dict[str, Any]] = {}
    for f in facts:
        if f.event_type not in _MEM_STATE or not f.memory_ref:
            continue
        m = items.setdefault(f.memory_ref, {
            "memory_ref": f.memory_ref, "agent": f.agent_ref, "state": None, "created_at": None,
            "retrievals": 0, "updates": 0, "ended_at": None, "anomalies": [], "evidence": [],
        })
        state = _MEM_STATE[f.event_type]
        m["evidence"].append(f.event_id)
        if m["state"] is None and state != "created":
            m["anomalies"].append({"event_id": f.event_id, "reason": "used_before_creation_observed"})
        if m["state"] in {"invalidated", "expired"} and state in {"retrieved", "updated"}:
            m["anomalies"].append({"event_id": f.event_id, "reason": f"{state}_after_{m['state']}"})
        if state == "created":
            m["created_at"] = m["created_at"] or f.occurred_at
        elif state == "retrieved":
            m["retrievals"] += 1
        elif state == "updated":
            m["updates"] += 1
        else:
            m["ended_at"] = f.occurred_at
        if not (m["state"] in {"invalidated", "expired"} and state in {"retrieved", "updated"}):
            m["state"] = state
    return sorted(items.values(), key=lambda m: m["memory_ref"])
