"""Decision attribution, influence graph, snapshots, drift, adaptation and
counterfactuals (WO-090, WO-091, WO-100–WO-103).

Attribution reports evidence associated with a decision, never a cause.
Drift compares confidence intervals, not point estimates, so noise from small
samples is not reported as change. Counterfactuals are labelled hypothetical
and are only produced where the decision's alternatives were observed.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Iterable, Optional

from intelligence.agent_behavior import contracts as c
from intelligence.agent_behavior.facts import AgentFact
from intelligence.agent_behavior.model import confidence_envelope
from intelligence.agent_behavior.responsibility import InfluenceEdge, observed_influence

SNAPSHOT_VERSION = "1"
_RATE_FEATURES = ("tool_success_rate", "failure_resolution_rate", "candidate_rejection_rate",
                  "escalation_rate", "constrained_non_action_rate", "authority_denial_rate")


# --- decision attribution (WO-090) -------------------------------------------------------

def decision_attribution(envelope: dict[str, Any], facts: Iterable[AgentFact]) -> dict[str, Any]:
    did = envelope["decision_id"]
    group = [f for f in facts if f.event_id in set(envelope["evidence"])]
    selected_at = next((f.occurred_at for f in group if f.event_type == "agent_action_selected"), None)
    pick = (envelope["selected_action"].get("value") or {}).get("candidate") \
        if isinstance(envelope["selected_action"].get("value"), dict) else None
    factors: list[dict[str, Any]] = []
    for blocked, ev in envelope["opportunity"]["blocked"].items():
        factors.append({"factor": "constraint_removed_alternative", "detail": blocked,
                        "basis": c.OBSERVED, "evidence": ev})
    for f in group:
        if selected_at and f.occurred_at > selected_at:
            continue
        if f.event_type in {"agent_information_retrieved", "agent_source_consulted"}:
            factors.append({"factor": "information_consulted", "detail": f.information_source_ref,
                            "basis": c.OBSERVED, "evidence": [f.event_id]})
        if f.event_type == "agent_action_selected" and f.attr("recommendedBy", "recommended_by"):
            factors.append({"factor": "recommendation", "detail": f.attr("recommendedBy", "recommended_by"),
                            "basis": c.DECLARED, "evidence": [f.event_id]})
    prices = {f.object_ref: f.amount for f in group
              if f.event_type == "agent_candidate_considered" and f.amount is not None}
    permitted = envelope["opportunity"]["permitted"]
    if pick and pick in prices and len([p for p in permitted if p in prices]) >= 2:
        cheapest = min((prices[p] for p in permitted if p in prices))
        factors.append({"factor": "price_position",
                        "detail": "lowest_permitted_price" if prices[pick] == cheapest else "not_lowest_price",
                        "basis": c.DERIVED, "evidence": envelope["selected_action"]["evidence"]})
    return {
        "decision_id": did,
        "attribution_type": "evidence_association",
        "factors": factors,
        "note": "Factors present before the selection; association, not causation.",
        "unobservable": ["internal deliberation", "unreported context"],
    }


# --- influence graph (WO-091) ---------------------------------------------------------------

def influence_graph(facts: Iterable[AgentFact], inferred: Iterable[InfluenceEdge] = ()) -> dict[str, Any]:
    edges = observed_influence(facts) + list(inferred)
    nodes = sorted({e.source for e in edges} | {e.target for e in edges})
    adj: dict[str, set[str]] = {}
    for e in edges:
        if e.relation in {"instructed", "recommended", "influenced"}:
            adj.setdefault(e.source, set()).add(e.target)
    cycles = []
    for start in nodes:
        stack = [(start, [start])]
        while stack:
            node, path = stack.pop()
            for nxt in adj.get(node, ()):
                if nxt == start and len(path) > 1:
                    cyc = sorted(path)
                    if cyc not in cycles:
                        cycles.append(cyc)
                elif nxt not in path and len(path) < 8:
                    stack.append((nxt, path + [nxt]))
    return {
        "nodes": nodes,
        "edges": [e.to_dict() for e in sorted(edges, key=lambda e: (e.source, e.target, e.relation))],
        "by_state": {s: sum(1 for e in edges if e.state == s) for s in ("observed", "declared", "inferred")},
        "cycles": cycles,
    }


# --- snapshots and drift (WO-100, WO-101) ------------------------------------------------

def snapshot(model: dict[str, Any], window: tuple[str, str]) -> dict[str, Any]:
    feats = model["features"]
    return {
        "agent_ref": model["agent_ref"], "version": SNAPSHOT_VERSION, "window": list(window),
        "model": model["model"],
        "rates": {k: {"n": feats[k].get("n", 0), "value": feats[k].get("value"),
                      "interval": feats[k].get("interval"), "evidence": feats[k].get("evidence", [])}
                  for k in _RATE_FEATURES if isinstance(feats.get(k), dict)},
        "top_tools": [t["tool"] for t in model["what_it_usually_does"]["top_tools"]],
        "usual_disposition": model["what_it_usually_does"]["usual_disposition"],
    }


def delta(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k in _RATE_FEATURES:
        ra, rb = a["rates"].get(k), b["rates"].get(k)
        if not ra or not rb or ra["value"] is None or rb["value"] is None:
            out[k] = {"change": None, "reason": "insufficient evidence in one window"}
            continue
        out[k] = {"from": ra["value"], "to": rb["value"], "change": round(rb["value"] - ra["value"], 4),
                  "n": [ra["n"], rb["n"]],
                  "separated": ra["interval"][1] < rb["interval"][0] or rb["interval"][1] < ra["interval"][0]}
    return {"features": out,
            "tools_added": sorted(set(b["top_tools"]) - set(a["top_tools"])),
            "tools_dropped": sorted(set(a["top_tools"]) - set(b["top_tools"])),
            "disposition_changed": a["usual_disposition"] != b["usual_disposition"]}


def detect_drift(baseline: dict[str, Any], recent: dict[str, Any],
                 config_changes: Iterable[dict[str, Any]] = ()) -> dict[str, Any]:
    d = delta(baseline, recent)
    moved = [{"feature": k, **v, "evidence": recent["rates"][k]["evidence"][:10]}
             for k, v in d["features"].items() if v.get("separated")]
    changes = [cfg for cfg in config_changes
               if baseline["window"][1] <= (cfg.get("first_seen") or "") <= recent["window"][1]]
    if not moved:
        return {"status": "no_drift_detected", "dimensions": [], "delta": d,
                "note": "only interval-separated changes count as drift"}
    return {
        "status": "drift_detected",
        "dimensions": moved,
        "confidence": round(min(0.9, 0.5 + 0.1 * len(moved)), 4),
        "basis": c.INFERRED,
        "coincident_configuration_changes": changes,
        "explanation_note": "a coincident configuration change is a candidate explanation, not a proven cause",
        "delta": d,
    }


# --- outcome-linked adaptation (WO-102) ---------------------------------------------------

def adaptation(facts: Iterable[AgentFact], agent_ref: str) -> list[dict[str, Any]]:
    """Per tool: does the agent use it less after its first observed failure?"""
    calls = [f for f in facts if f.agent_ref == agent_ref and f.tool_name
             and f.event_type.startswith("agent_tool_") and f.status in {"succeeded", "failed", "invoked"}]
    out = []
    for tool in sorted({f.tool_name for f in calls}):
        first_fail = next((i for i, f in enumerate(calls) if f.tool_name == tool and f.status == "failed"), None)
        if first_fail is None:
            continue
        before, after = calls[:first_fail], calls[first_fail + 1:]
        if len(before) < 2 or len(after) < 2:
            out.append({"tool": tool, "adaptation": None, "reason": "too few calls around the first failure",
                        "evidence": [calls[first_fail].event_id]})
            continue
        share_before = sum(f.tool_name == tool for f in before) / len(before)
        share_after = sum(f.tool_name == tool for f in after) / len(after)
        out.append({
            "tool": tool, "share_before": round(share_before, 4), "share_after": round(share_after, 4),
            "adaptation": "reduced_use" if share_after < share_before - 0.1 else
                          "increased_use" if share_after > share_before + 0.1 else "unchanged",
            "basis": c.DERIVED, "evidence": [calls[first_fail].event_id],
        })
    return out


# --- counterfactual v0 (WO-103) ---------------------------------------------------------------

def counterfactual_without_constraint(envelope: dict[str, Any], facts: Iterable[AgentFact],
                                      preferences: Iterable[dict[str, Any]]) -> dict[str, Any]:
    blocked = [k for k in envelope["opportunity"]["blocked"] if k != "*"]
    if envelope["opportunity"]["blocked"].get("*"):
        blocked = list(envelope["opportunity"]["available"])
    if not blocked:
        return {"status": "not_applicable", "reason": "no constraint removed an observed alternative"}
    prices = {f.object_ref: f.amount for f in facts if f.event_id in set(envelope["evidence"])
              and f.amount is not None and f.object_ref}
    pref = next((p for p in preferences if p["preference"] == "lowest_price" and p["rate"]["value"] is not None), None)
    options = [b for b in blocked if b in prices]
    if pref and options:
        guess = min(options, key=lambda o: (prices[o], o))
        conf = pref["rate"]["interval"][0]
        return {"status": "hypothetical", "question": "What if the blocking constraint were absent?",
                "likely_choice": guess, "basis": c.INFERRED, "confidence": conf,
                "method": "observed lowest-price preference applied to the blocked alternatives",
                "label": "counterfactual — not observed", "evidence": envelope["evidence"][:10]}
    return {"status": "hypothetical", "question": "What if the blocking constraint were absent?",
            "likely_choice": None, "basis": c.UNKNOWN,
            "reason": "no reliable preference model for these alternatives",
            "label": "counterfactual — not observed", "options": sorted(blocked)}


def exact_sum(values: Iterable[Optional[Decimal]]) -> Decimal:
    return sum((v for v in values if v is not None), Decimal(0))
