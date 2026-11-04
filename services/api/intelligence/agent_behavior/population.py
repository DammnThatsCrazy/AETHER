"""Population, market, strategic and adversarial agent intelligence (WO-140–WO-161).

Built on single-agent truth (Gate F): every group here is a hypothesis over
per-agent evidence. Similar behavior forms a *syndicate* (a behavioral
grouping), never a claim of common control; that stays with the reviewed fleet
hypothesis in Risk.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Any, Iterable, Optional

from intelligence.agent_behavior import contracts as c
from intelligence.agent_behavior.facts import AgentFact

_FEATURE_KEYS = ("tool_success_rate", "candidate_rejection_rate", "escalation_rate",
                 "constrained_non_action_rate", "authority_denial_rate")


def _ts(value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None


def _vector(model: dict[str, Any]) -> Optional[list[float]]:
    feats = model["features"]
    values = [feats.get(k, {}).get("value") if isinstance(feats.get(k), dict) else None for k in _FEATURE_KEYS]
    tools = model["what_it_usually_does"]["top_tools"]
    if all(v is None for v in values) and not tools:
        return None
    return [v if v is not None else 0.0 for v in values]


def _cos(a: list[float], b: list[float]) -> float:
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    if not na or not nb:
        return 1.0 if na == nb else 0.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


# --- syndicates (WO-140) ----------------------------------------------------------------

def behavioral_syndicates(models: Iterable[dict[str, Any]], *, threshold: float = 0.95,
                          min_size: int = 3) -> list[dict[str, Any]]:
    models = [m for m in models if _vector(m) is not None]
    tools = {m["agent_ref"]: {t["tool"] for t in m["what_it_usually_does"]["top_tools"]} for m in models}
    vec = {m["agent_ref"]: _vector(m) for m in models}
    parent = {m["agent_ref"]: m["agent_ref"] for m in models}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    refs = sorted(vec)
    for i, a in enumerate(refs):
        for b in refs[i + 1:]:
            jacc = len(tools[a] & tools[b]) / len(tools[a] | tools[b]) if tools[a] | tools[b] else 0.0
            if _cos(vec[a], vec[b]) >= threshold and jacc >= 0.5:
                parent[find(a)] = find(b)
    groups: dict[str, list[str]] = defaultdict(list)
    for r in refs:
        groups[find(r)].append(r)
    return [{
        "syndicate_id": "syn_" + "_".join(sorted(g))[:48],
        "members": sorted(g),
        "shared_tools": sorted(set.intersection(*(tools[m] for m in g))),
        "basis": c.INFERRED,
        "claim": "behavioral_similarity",
        "implies_common_control": False,
    } for g in groups.values() if len(g) >= min_size]


# --- swarm (WO-141) ------------------------------------------------------------------

def swarm_episodes(facts: Iterable[AgentFact], *, window_seconds: int = 300,
                   min_agents: int = 5) -> list[dict[str, Any]]:
    """Many distinct agents acting on the same target with the same tool inside
    a short window."""
    buckets: dict[tuple[str, str], list[AgentFact]] = defaultdict(list)
    for f in facts:
        if f.tool_name and f.object_ref and f.agent_ref:
            buckets[(f.tool_name, f.object_ref)].append(f)
    out = []
    for (tool, target), fs in sorted(buckets.items()):
        fs = sorted((f for f in fs if _ts(f.occurred_at)), key=lambda f: (f.occurred_at, f.event_id))
        best: Optional[tuple[int, int]] = None
        lo = 0
        for hi in range(len(fs)):
            while (_ts(fs[hi].occurred_at) - _ts(fs[lo].occurred_at)).total_seconds() > window_seconds:
                lo += 1
            size = len({f.agent_ref for f in fs[lo:hi + 1]})
            if best is None or size > len({f.agent_ref for f in fs[best[0]:best[1] + 1]}):
                best = (lo, hi)
        if best is None:
            continue
        span = fs[best[0]:best[1] + 1]
        agents = sorted({f.agent_ref for f in span})
        if len(agents) >= min_agents:
            out.append({"tool": tool, "target": target, "agents": agents, "size": len(agents),
                        "start": span[0].occurred_at, "end": span[-1].occurred_at,
                        "basis": c.DERIVED, "evidence": [f.event_id for f in span][:25]})
    return out


# --- contagion (WO-142) -----------------------------------------------------------------

def contagion(facts: Iterable[AgentFact], behavior: str) -> dict[str, Any]:
    """Did adoption of ``behavior`` (a tool name) follow instruction edges?

    An adopter whose instructing parent adopted earlier is a ``linked``
    adoption. The share of linked adoptions is a derived indicator, not proof
    of transmission."""
    facts = list(facts)
    parents = {f.child_agent_ref: f.agent_ref for f in facts
               if f.event_type == "agent_subagent_spawned" and f.child_agent_ref}
    parents.update({f.delegated_to_ref: f.agent_ref for f in facts
                    if f.event_type == "agent_delegated_task" and f.delegated_to_ref})
    first: dict[str, AgentFact] = {}
    for f in sorted(facts, key=lambda f: (f.occurred_at, f.event_id)):
        if f.tool_name == behavior and f.agent_ref and f.agent_ref not in first:
            first[f.agent_ref] = f
    linked = [a for a, f in first.items() if parents.get(a) in first
              and first[parents[a]].occurred_at <= f.occurred_at]
    with_parent = [a for a in first if a in parents]
    return {
        "behavior": behavior, "adopters": len(first), "adopters_with_parent": len(with_parent),
        "linked_adoptions": sorted(linked),
        "linked_share": round(len(linked) / len(with_parent), 4) if with_parent else None,
        "basis": c.DERIVED, "note": "temporal ordering along instruction edges; not proof of transmission",
    }


# --- demand graph and market compatibility (WO-143, WO-144) ------------------------------

def demand_graph(facts: Iterable[AgentFact]) -> dict[str, Any]:
    edges: dict[tuple[str, str, str], dict[str, Any]] = {}
    for f in facts:
        target = f.object_ref or f.resource_ref
        if not f.agent_ref or not target:
            continue
        kind = ("transacted" if f.event_type.startswith("agent_transaction_") else
                "quoted" if f.event_type in {"agent_quote_received", "agent_price_evaluated"} else
                "considered" if f.event_type in {"agent_candidate_considered", "agent_action_selected"} else
                "queried" if f.tool_name else None)
        if not kind:
            continue
        e = edges.setdefault((f.agent_ref, target, kind), {"agent": f.agent_ref, "target": target, "kind": kind,
                                                           "count": 0, "amounts": defaultdict(Decimal)})
        e["count"] += 1
        if f.amount is not None and f.currency:
            e["amounts"][f.currency] += f.amount
    return {"edges": [{**e, "amounts": {k: str(v) for k, v in sorted(e["amounts"].items())}}
                      for _, e in sorted(edges.items())],
            "targets_by_demand": Counter(t for (_, t, _) in edges).most_common(10)}


def market_compatibility(facts: Iterable[AgentFact]) -> list[dict[str, Any]]:
    """Per merchant/resource: how well agents can transact there."""
    per: dict[str, dict[str, Any]] = {}
    for f in facts:
        target = f.resource_ref or (f.object_ref if f.event_type.startswith("agent_transaction_") else None)
        if not target:
            continue
        p = per.setdefault(target, {"target": target, "attempts": 0, "succeeded": 0, "failed": 0,
                                    "denied": 0, "agents": set(), "failure_reasons": Counter()})
        p["agents"].add(f.agent_ref)
        if f.event_type in {"agent_transaction_initiated", "agent_execution_started"}:
            p["attempts"] += 1
        elif f.event_type in {"agent_transaction_settled", "agent_execution_succeeded"}:
            p["succeeded"] += 1
        elif f.event_type in {"agent_transaction_failed", "agent_execution_failed"}:
            p["failed"] += 1
            p["failure_reasons"][f.attr("errorCode", "reason") or "unspecified"] += 1
        elif f.event_type == "agent_authorization_denied" or (f.policy_decision or "").lower() == "deny":
            p["denied"] += 1
    out = []
    for p in sorted(per.values(), key=lambda p: p["target"]):
        done = p["succeeded"] + p["failed"]
        out.append({**p, "agents": sorted(a for a in p["agents"] if a),
                    "failure_reasons": dict(p["failure_reasons"]),
                    "agent_success_rate": round(p["succeeded"] / done, 4) if done else None,
                    "basis": c.DERIVED})
    return out


# --- strategic episodes and negotiation (WO-150, WO-151) ---------------------------------

def strategic_episodes(facts: Iterable[AgentFact], *, gap_seconds: int = 900) -> list[dict[str, Any]]:
    """Interactions of two or more agents around one object, split by idle gaps."""
    by_obj: dict[str, list[AgentFact]] = defaultdict(list)
    for f in facts:
        if f.object_ref and f.agent_ref and (f.amount is not None or f.event_type.startswith("agent_message")
                                               or f.event_type in {"agent_quote_received", "agent_price_evaluated"}):
            by_obj[f.object_ref].append(f)
    out = []
    for obj, fs in sorted(by_obj.items()):
        fs.sort(key=lambda f: (f.occurred_at, f.event_id))
        current: list[AgentFact] = []
        for f in fs + [None]:
            gap = (f is None or (current and _ts(f.occurred_at) and _ts(current[-1].occurred_at) and
                                 (_ts(f.occurred_at) - _ts(current[-1].occurred_at)).total_seconds() > gap_seconds))
            if gap and current:
                actors = sorted({x.agent_ref for x in current})
                if len(actors) >= 2:
                    out.append({"object": obj, "actors": actors, "moves": len(current),
                                "start": current[0].occurred_at, "end": current[-1].occurred_at,
                                "negotiation": negotiation(current), "basis": c.DERIVED,
                                "evidence": [x.event_id for x in current][:25]})
                current = []
            if f is not None:
                current.append(f)
    return out


def negotiation(moves: list[AgentFact]) -> dict[str, Any]:
    priced = [(m.agent_ref, m.amount, m.event_id) for m in moves if m.amount is not None]
    if len(priced) < 2:
        return {"status": "not_applicable", "reason": "fewer than two priced moves"}
    by_actor: dict[str, list[Decimal]] = defaultdict(list)
    for actor, amount, _ in priced:
        by_actor[actor].append(amount)
    concessions = {a: str(v[0] - v[-1]) for a, v in by_actor.items() if len(v) > 1}
    closed = any(m.event_type in {"agent_transaction_initiated", "agent_transaction_settled"} for m in moves)
    return {"rounds": len(priced), "opening": str(priced[0][1]), "final": str(priced[-1][1]),
            "concessions": concessions, "agreed": closed, "basis": c.DERIVED,
            "evidence": [e for _, _, e in priced][:25]}


# --- identity discontinuity and adversarial signals (WO-160, WO-161) ----------------------

def identity_discontinuity(baseline: dict[str, Any], recent: dict[str, Any],
                           declared_changes: Iterable[dict[str, Any]] = ()) -> dict[str, Any]:
    va, vb = _vector(baseline), _vector(recent)
    if va is None or vb is None:
        return {"status": "insufficient_evidence"}
    tools_a = {t["tool"] for t in baseline["what_it_usually_does"]["top_tools"]}
    tools_b = {t["tool"] for t in recent["what_it_usually_does"]["top_tools"]}
    overlap = len(tools_a & tools_b) / len(tools_a | tools_b) if tools_a | tools_b else 1.0
    distance = 1 - _cos(va, vb)
    explained = list(declared_changes)
    if distance < 0.2 and overlap >= 0.5:
        return {"status": "continuous", "distance": round(distance, 4), "tool_overlap": round(overlap, 4)}
    status = "explained_change" if explained else "discontinuity_suspected"
    return {"status": status, "distance": round(distance, 4), "tool_overlap": round(overlap, 4),
            "declared_changes": explained, "basis": c.INFERRED,
            "confidence": None if explained else round(min(0.8, 0.4 + distance), 4),
            "competing_explanations": ["new configuration not reported", "different workload",
                                       "credential or identifier reuse by another agent"],
            "evidence": recent["features"].get("tool_success_rate", {}).get("evidence", [])[:10]}


def adversarial_signals(facts: Iterable[AgentFact], authority_checks: Iterable[dict[str, Any]] = (),
                        *, probe_threshold: int = 3) -> list[dict[str, Any]]:
    facts = sorted(facts, key=lambda f: (f.occurred_at, f.event_id))
    out = []
    guard = [f for f in facts if f.event_type == "agent_guardrail_observed"]
    if guard:
        out.append({"kind": "guardrail_triggered", "basis": c.OBSERVED, "evidence": [f.event_id for f in guard][:25]})
    denials = [f for f in facts if f.event_type == "agent_authorization_denied"
               or (f.policy_decision or "").lower() in {"deny", "denied", "block", "blocked"}]
    if len(denials) >= probe_threshold:
        out.append({"kind": "authority_probing", "basis": c.INFERRED, "confidence": round(min(0.8, 0.2 * len(denials)), 4),
                    "evidence": [f.event_id for f in denials][:25],
                    "competing_explanations": ["misconfigured policy", "legitimate retries"]})
    untrusted = [f for f in facts if f.event_type == "agent_context_received"
                 and str(f.attr("trust") or f.attr("sourceTrust") or "") in {"untrusted", "external"}]
    for ctx in untrusted:
        follow = [d for d in denials if d.agent_ref == ctx.agent_ref and d.occurred_at >= ctx.occurred_at]
        if follow:
            out.append({"kind": "injection_suspected", "basis": c.INFERRED, "confidence": 0.5,
                        "evidence": [ctx.event_id, follow[0].event_id],
                        "competing_explanations": ["coincidental policy denial"]})
    outside = [chk for chk in authority_checks if chk.get("status") == "outside"]
    if outside:
        out.append({"kind": "authority_boundary_exceeded", "basis": c.OBSERVED,
                    "evidence": [e for chk in outside for e in chk.get("evidence", [])][:25]})
    return out
