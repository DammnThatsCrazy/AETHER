"""Capability, competency, behavior features and the AgentBehaviorModel (WO-070–WO-083).

The model is a rebuildable projection (ADR-AB-002): the same facts and
version always give the same model. Each feature carries its sample size,
basis and a confidence envelope; features with too little evidence say so
instead of returning a number. The observability envelope lists what Aether
cannot see for this agent, so absence is never read as behavior.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from decimal import Decimal
from typing import Any, Iterable, Optional

from intelligence.agent_behavior import contracts as c
from intelligence.agent_behavior.activity import (
    failure_resolution, information_inputs, memory_lifecycle, tool_entities,
)
from intelligence.agent_behavior.decisions import project_decisions
from intelligence.agent_behavior.facts import AgentFact, watermark
from intelligence.agent_behavior.taxonomy import DOTTED_TO_CANONICAL

MODEL = "agent_behavior_model"
VERSION = "1"
MIN_SAMPLE = 5
_Z = 1.96

# --- confidence (WO-080) ------------------------------------------------------------


def wilson(successes: int, n: int) -> tuple[Optional[float], Optional[float]]:
    if n <= 0:
        return None, None
    p = successes / n
    denom = 1 + _Z * _Z / n
    centre = p + _Z * _Z / (2 * n)
    spread = _Z * math.sqrt(p * (1 - p) / n + _Z * _Z / (4 * n * n))
    return round((centre - spread) / denom, 4), round((centre + spread) / denom, 4)


def confidence_envelope(successes: int, n: int, *, method: str = "wilson_95",
                        evidence: Iterable[str] = ()) -> dict[str, Any]:
    """A rate with its uncertainty. Below MIN_SAMPLE the value is withheld."""
    low, high = wilson(successes, n)
    enough = n >= MIN_SAMPLE
    reason = None if enough else f"fewer than {MIN_SAMPLE} observations (n={n})"
    return {
        "value": round(successes / n, 4) if n and enough else None,
        "n": n,
        "interval": [low, high] if n else None,
        "method": method,
        "calibration": "uncalibrated",
        "sufficiency": "sufficient" if enough else "insufficient_evidence",
        "basis": c.DERIVED if enough else c.UNKNOWN,
        "evidence": list(evidence)[:25],
        **({"reason": reason} if reason else {}),
    }


# --- observability (WO-081) -------------------------------------------------------------

def observability_envelope(facts: list[AgentFact]) -> dict[str, Any]:
    families: dict[str, set[str]] = defaultdict(set)
    for dotted, (etype, _) in DOTTED_TO_CANONICAL.items():
        families[dotted.split(".")[1]].add(etype)
    seen_types = {f.event_type for f in facts}
    observed = sorted(fam for fam, types in families.items() if types & seen_types)
    blind = sorted(set(families) - set(observed))
    validated = sum(1 for f in facts if f.deployment_id)
    return {
        "observed_families": observed,
        "not_observed_families": blind,
        "coverage": round(len(observed) / len(families), 4) if families else 0.0,
        "validated_source_share": round(validated / len(facts), 4) if facts else None,
        "always_unobservable": ["chain_of_thought", "unreported_tools", "off_platform_actions",
                                "funding_outside_telemetry"],
        "statement": c.not_observed(
            "Absence of a family means Aether did not receive it, not that the agent did not do it"
        ).to_dict() if blind else None,
    }


# --- capability and competency (WO-070, WO-071) ---------------------------------------

def capabilities(facts: list[AgentFact]) -> list[dict[str, Any]]:
    caps: dict[str, dict[str, Any]] = {}

    def add(name: str, basis: str, ev: str) -> None:
        cap = caps.setdefault(name, {"capability": name, "declared": [], "demonstrated": [], "revoked": []})
        cap[basis].append(ev)

    for f in facts:
        if f.event_type == "agent_capability_granted":
            add(f.attr("capability") or f.action_type or "unspecified", "declared", f.event_id)
        elif f.event_type == "agent_capability_revoked":
            add(f.attr("capability") or f.action_type or "unspecified", "revoked", f.event_id)
        declared_tools = f.attr("availableTools", "toolsAvailable")
        for tool in declared_tools if isinstance(declared_tools, list) else []:
            add(f"tool:{tool}", "declared", f.event_id)
        if f.tool_name and f.status == "succeeded":
            add(f"tool:{f.tool_name}", "demonstrated", f.event_id)
        if f.event_type in {"agent_execution_succeeded", "agent_transaction_settled"} and f.action_type:
            add(f"action:{f.action_type}", "demonstrated", f.event_id)
    out = []
    for name, cap in sorted(caps.items()):
        status = ("revoked" if cap["revoked"] and cap["revoked"][-1] > max(cap["declared"] + [""])
                  else "demonstrated" if cap["demonstrated"] else "declared_only")
        out.append({"capability": name, "status": status,
                    "basis": c.OBSERVED if cap["demonstrated"] else c.DECLARED,
                    "evidence": (cap["demonstrated"] or cap["declared"] or cap["revoked"])[:10]})
    return out


def competencies(facts: list[AgentFact]) -> list[dict[str, Any]]:
    tally: dict[str, list[tuple[bool, str]]] = defaultdict(list)
    for f in facts:
        if f.tool_name and f.status in {"succeeded", "failed"}:
            tally[f"tool:{f.tool_name}"].append((f.status == "succeeded", f.event_id))
        if f.event_type in {"agent_execution_succeeded", "agent_execution_failed"}:
            tally[f"action:{f.action_type or 'unspecified'}"].append(
                (f.event_type.endswith("succeeded"), f.event_id))
    return [{"capability": k, "success": confidence_envelope(sum(ok for ok, _ in v), len(v),
                                                              evidence=[e for _, e in v])}
            for k, v in sorted(tally.items())]


# --- features (WO-072, WO-074, WO-075) ---------------------------------------------------

def _rate(num: int, den: int, evidence: Iterable[str] = ()) -> dict[str, Any]:
    if den == 0:
        return {**c.not_applicable("no opportunities to measure").to_dict(), "n": 0}
    return confidence_envelope(num, den, evidence=evidence)


def behavior_features(facts: list[AgentFact], decisions: list[dict[str, Any]]) -> dict[str, Any]:
    tool_calls = [f for f in facts if f.tool_name and f.event_type.startswith("agent_tool_")]
    with_result = [f for f in tool_calls if f.status in {"succeeded", "failed"}]
    fr = failure_resolution(facts)
    failures = sum(len(e["failures"]) for e in fr)
    spawns = [f for f in facts if f.event_type == "agent_subagent_spawned"]
    dispositions = Counter(d["disposition"]["disposition"] for d in decisions)
    n_dec = len(decisions)
    cand_counts = [len(d["candidates"]["candidates"]) for d in decisions if d["candidates"]["candidates"]]
    rejects = sum(1 for d in decisions for x in d["candidates"]["candidates"] if x["rejected"])
    considered = sum(len(d["candidates"]["candidates"]) for d in decisions)
    latencies = [f.latency_ms for f in tool_calls if f.latency_ms is not None]
    authz = [f for f in facts if f.event_type in {"agent_authorization_granted", "agent_authorization_denied"}
             or f.event_type == "agent_policy_evaluated"]
    denied = [f for f in authz if f.event_type == "agent_authorization_denied"
              or (f.policy_decision or "").lower() in {"deny", "denied", "block", "blocked"}]
    info = information_inputs(facts)
    mem = memory_lifecycle(facts)

    # exploration vs exploitation (WO-075): first-time tool/candidate choices
    seen_tools: set[str] = set()
    novel = 0
    for f in tool_calls:
        if f.tool_name not in seen_tools:
            novel += 1
            seen_tools.add(f.tool_name)
    switches_after_failure = sum(1 for e in fr for s in e["switches"])
    retries = sum(len(e["retries"]) for e in fr)

    # uncertainty behavior (WO-074): what the agent does when its candidate
    # set is incomplete or it reports uncertainty.
    uncertain = [d for d in decisions if d["candidates"]["completeness"] != "complete"]
    reported_uncertain = [f for f in facts if f.attr("uncertainty", "confidence") is not None]
    info_before_select = sum(1 for d in decisions if any(
        f.decision_ref == d["decision_id"] and f.event_type in {"agent_information_retrieved", "agent_source_consulted"}
        for f in facts))

    return {
        "tool_success_rate": _rate(sum(f.status == "succeeded" for f in with_result), len(with_result),
                                   [f.event_id for f in with_result]),
        "tool_diversity": {"distinct_tools": len(seen_tools), "calls": len(tool_calls), "basis": c.DERIVED},
        "latency_ms_median": (sorted(latencies)[len(latencies) // 2] if latencies else None),
        "failure_resolution_rate": _rate(sum(e["resolved"] for e in fr), len(fr)),
        "retry_per_failure": round(retries / failures, 4) if failures else None,
        "switch_per_failure": round(switches_after_failure / failures, 4) if failures else None,
        "delegation_fanout": {"spawned": len(spawns),
                              "distinct_children": len({f.child_agent_ref for f in spawns}), "basis": c.OBSERVED},
        "decisions": n_dec,
        "candidates_per_decision": round(sum(cand_counts) / len(cand_counts), 4) if cand_counts else None,
        "candidate_rejection_rate": _rate(rejects, considered),
        "disposition_mix": dict(sorted(dispositions.items())),
        "escalation_rate": _rate(dispositions.get("escalated", 0), n_dec),
        "constrained_non_action_rate": _rate(dispositions.get("constrained_non_action", 0), n_dec),
        "authority_denial_rate": _rate(len(denied), len(authz), [f.event_id for f in denied]),
        "information_inputs_per_decision": round(info["inputs"] / n_dec, 4) if n_dec else None,
        "memory_reuse": {"items": len(mem), "retrievals": sum(m["retrievals"] for m in mem),
                         "stale_use": sum(1 for m in mem for a in m["anomalies"] if "after" in a["reason"])},
        "exploration": {
            "novel_tool_share": _rate(novel, len(tool_calls)),
            "switch_after_failure": switches_after_failure,
            "retry_after_failure": retries,
            "tendency": (None if len(tool_calls) < MIN_SAMPLE else
                         "exploratory" if novel / len(tool_calls) > 0.5 else "exploitative"),
        },
        "uncertainty": {
            "decisions_with_incomplete_candidates": len(uncertain),
            "escalated_when_incomplete": sum(1 for d in uncertain if d["disposition"]["disposition"] == "escalated"),
            "abstained_when_incomplete": sum(1 for d in uncertain if d["disposition"]["disposition"] in {"abstained", "deferred"}),
            "decisions_with_information_lookup": info_before_select,
            "self_reported_uncertainty": c.declared(len(reported_uncertain), [f.event_id for f in reported_uncertain])
                                         .to_dict() if reported_uncertain else
                                         c.not_observed("agent does not report its uncertainty").to_dict(),
        },
    }


# --- preference inference (WO-083) --------------------------------------------------

def infer_preferences(facts: list[AgentFact], decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Preferences only from decisions whose OpportunityEnvelope allows it
    (ADR-AB-004). Candidate attributes come from candidate_considered facts."""
    attrs: dict[tuple[str, str], dict[str, Any]] = {}
    for f in facts:
        if f.event_type == "agent_candidate_considered" and f.decision_ref and f.object_ref:
            attrs[(f.decision_ref, f.object_ref)] = {"price": f.amount, "vendor": f.attr("vendor")}
    cheapest_hits, cheapest_n, vendor_hits = 0, 0, Counter()
    ev: list[str] = []
    eligible = 0
    for d in decisions:
        if d["opportunity"]["preference_inference"] != "allowed":
            continue
        chosen = d["selected_action"].get("value") or {}
        pick = chosen.get("candidate") if isinstance(chosen, dict) else None
        scope = d["opportunity"]["preference_scope"]
        if not pick or pick not in scope:
            continue
        eligible += 1
        ev.extend(d["selected_action"]["evidence"])
        prices = {cand: attrs.get((d["decision_id"], cand), {}).get("price") for cand in scope}
        if all(isinstance(p, Decimal) for p in prices.values()):
            cheapest_n += 1
            cheapest_hits += prices[pick] == min(prices.values())
        vendor = attrs.get((d["decision_id"], pick), {}).get("vendor")
        if vendor:
            vendor_hits[vendor] += 1
    out = []
    if cheapest_n:
        env = confidence_envelope(cheapest_hits, cheapest_n, evidence=ev)
        out.append({"preference": "lowest_price", "rate": env, "basis": c.INFERRED if env["value"] is not None else c.UNKNOWN,
                    "scope": "observed_permitted_alternatives_only"})
    for vendor, hits in vendor_hits.most_common(3):
        env = confidence_envelope(hits, eligible, evidence=ev)
        out.append({"preference": f"vendor:{vendor}", "rate": env,
                    "basis": c.INFERRED if env["value"] is not None else c.UNKNOWN,
                    "scope": "observed_permitted_alternatives_only"})
    return out


# --- AgentBehaviorModel (WO-082) ------------------------------------------------------

def build_behavior_model(facts: Iterable[AgentFact], agent_ref: str, *,
                         identity: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """The rebuildable behavior model for one agent."""
    all_facts = sorted(facts, key=lambda f: (f.occurred_at, f.event_id))
    mine = [f for f in all_facts if f.agent_ref == agent_ref]
    decisions = [d for d in project_decisions(mine)["decisions"]
                 if d["decision_actor"].get("value") == agent_ref]
    features = behavior_features(mine, decisions)
    tools = tool_entities(mine)
    top_tools = sorted(tools, key=lambda t: (-t["invocations"], t["tool"]))[:5]
    dispositions = features["disposition_mix"]
    usual = max(dispositions, key=dispositions.get) if dispositions else None
    observability = observability_envelope(mine)
    return {
        "agent_ref": agent_ref,
        "model": c.ModelVersion(MODEL, VERSION, watermark(mine), len(mine)).to_dict(),
        "identity": identity,
        "what_it_usually_does": {
            "top_tools": [{"tool": t["tool"], "invocations": t["invocations"],
                           "success_rate": t["success_rate"]} for t in top_tools],
            "usual_disposition": usual,
            "basis": c.DERIVED if mine else c.UNKNOWN,
        },
        "capabilities": capabilities(mine),
        "competencies": competencies(mine),
        "features": features,
        "failure_resolution": failure_resolution(mine),
        "preferences": infer_preferences(mine, decisions),
        "observability": observability,
        "evidence": {"facts": len(mine), "decisions": len(decisions),
                     "first": mine[0].occurred_at if mine else None,
                     "last": mine[-1].occurred_at if mine else None},
        "what_aether_cannot_see": observability["not_observed_families"] + observability["always_unobservable"],
    }
