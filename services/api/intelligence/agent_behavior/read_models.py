"""Agent360 / Profile360 behavior read models and query capabilities
(WO-110–WO-115), plus communication, override and human-agent coupling
(WO-130–WO-132).

Read models are backend-owned (INV-007): the frontend renders these
structures and does not recompute behavior. Every section says where it
stands -- ``available``, ``partial`` or ``unavailable`` -- and why.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Callable, Iterable, Optional

from intelligence.agent_behavior import contracts as c
from intelligence.agent_behavior.activity import agent_journey
from intelligence.agent_behavior.decisions import project_decisions
from intelligence.agent_behavior.dynamics import (
    counterfactual_without_constraint, decision_attribution, influence_graph,
)
from intelligence.agent_behavior.facts import AgentFact, fact_order
from intelligence.agent_behavior.model import build_behavior_model
from intelligence.agent_behavior.responsibility import decompose
from intelligence.agent_behavior.taxonomy import COMMUNICATION_EVENTS

READ_MODEL_VERSION = "1"


def _section(state: str, data: Any, reason: Optional[str] = None) -> dict[str, Any]:
    out = {"state": state, "data": data}
    if reason:
        out["reason"] = reason
    return out


def _ts(value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None


# --- Agent360 (WO-110, WO-111, WO-112) -----------------------------------------------

_AUTHORIZATION_STATUS = {
    "agent_authorization_requested": "requested",
    "agent_authorization_granted": "granted",
    "agent_authorization_denied": "denied",
}


def _instant(value: str) -> Any:
    from shared.temporal.instant import MIN_INSTANT, coerce_utc_lenient

    # Silver timestamps mix whole and fractional seconds, so strings do not sort
    # chronologically; compare parsed UTC instants (unparseable sorts first).
    return coerce_utc_lenient(value) or MIN_INSTANT


def _approval_timeline(facts: Iterable[AgentFact]) -> dict[str, list[tuple[Any, str, str]]]:
    """``authorization_ref -> [(instant, event_id, status)]`` in time order."""
    timeline: dict[str, list[tuple[Any, str, str]]] = {}
    for f in facts:
        status = _AUTHORIZATION_STATUS.get(f.event_type)
        if status and f.authorization_ref:
            timeline.setdefault(f.authorization_ref, []).append((_instant(f.occurred_at), f.event_id, status))
    for entries in timeline.values():
        entries.sort()
    return timeline


def _granted_approval_ref(f: AgentFact, timeline: dict[str, list[tuple[Any, str, str]]]) -> Optional[str]:
    """The action's authorization reference only when that authorization's latest
    status at the action's time is ``granted``. The same id is used for requested,
    granted and denied, so the reference alone is not evidence of approval."""
    ref = f.authorization_ref
    if not ref:
        return None
    at = _instant(f.occurred_at)
    at_or_before = [e for e in timeline.get(ref, []) if e[0] <= at]
    return ref if at_or_before and at_or_before[-1][2] == "granted" else None


def _observed_action(f: AgentFact, approval_ref: Optional[str] = None):
    from actions.delegation.authority_boundary import ObservedAction

    return ObservedAction(
        event_id=f.event_id, actor_ref=f.agent_ref or "", occurred_at=f.occurred_at,
        action=f.action_type or ("purchase" if f.event_type.startswith("agent_transaction_") else f.event_type),
        resource=f.resource_ref, amount=str(f.amount) if f.amount is not None else None,
        merchant=f.attr("merchant", "merchantId"), protocol=f.attr("protocol"), asset=f.currency,
        human_approval_ref=approval_ref,
    )


# Lifecycle phases of one economic action, least to most final. A failed or
# aborted phase ranks lowest so a completed phase represents the action.
_PHASE_RANK = {
    "agent_transaction_failed": 0, "agent_execution_failed": 0, "agent_execution_aborted": 0,
    "agent_transaction_initiated": 1, "agent_execution_started": 1,
    "agent_transaction_authorized": 2,
    "agent_execution_succeeded": 3, "agent_transaction_settled": 4,
}


def _economic_key(f: AgentFact) -> Optional[tuple[str, str]]:
    """Explicit source correlation for one economic action across its phases.

    A reported action id correlates phases on its own. An object reference names a
    target (a product can be bought twice), so it correlates only together with
    the same decision or task. Nothing is inferred from amount or timing, so
    uncorrelated events stay distinct.
    """
    if f.action_ref:
        return (f.agent_ref or "", f"action:{f.action_ref}")
    scope = f.decision_ref or (f"task:{f.task_ref}" if f.task_ref else None)
    if f.object_type and f.object_id and scope:
        return (f.agent_ref or "", f"object:{f.object_type}:{f.object_id}|{scope}")
    return None


# References decompose() reads from an action, plus the currency value totals
# need; a correlated action keeps any reported on an earlier phase when its most
# final phase omits them.
_ATTRIBUTION_REFS = ("decision_ref", "objective_ref", "authorization_ref", "currency")


def distinct_actions(actions: list[AgentFact]) -> list[AgentFact]:
    """One representative per correlated action: its most final phase, carrying
    attribution references reported only on earlier phases.

    Shared with Value 360's agent activity reader so a purchase reported as
    initiated -> authorized -> settled is attributed once, not per phase."""
    import dataclasses

    groups: dict[Any, list[AgentFact]] = {}
    for f in actions:
        groups.setdefault(_economic_key(f) or ("event", f.event_id), []).append(f)
    chosen = []
    for group in groups.values():
        ordered = sorted(group, key=fact_order)
        best = max(group, key=lambda f: (_PHASE_RANK.get(f.event_type, 1), f.occurred_at, f.event_id))
        missing = {name: next((getattr(f, name) for f in ordered if getattr(f, name)), None)
                   for name in _ATTRIBUTION_REFS if not getattr(best, name)}
        missing = {k: v for k, v in missing.items() if v}
        chosen.append(dataclasses.replace(best, **missing) if missing else best)
    return sorted(chosen, key=fact_order)


def _prior_spends(actions: list[AgentFact], observed: list[Any], index: int) -> list[Any]:
    """Earlier spends for the boundary check, counting each correlated action once
    and never the current action's own earlier phases."""
    current = _economic_key(actions[index])
    latest: dict[Any, Any] = {}
    for f, o in zip(actions[:index], observed[:index]):
        key = _economic_key(f)
        if key is not None and key == current:
            continue
        latest[key or ("event", f.event_id)] = o
    return list(latest.values())


def _governance(facts: list[AgentFact], agent_ref: str, model: dict[str, Any],
                grants: list[dict[str, Any]],
                queued_reviews: Optional[list[dict[str, Any]]] = None) -> dict[str, dict[str, Any]]:
    """Identity, authority, Value, Risk, Trust and market sections from their
    owning domains (WO-013, WO-020, WO-092–WO-094, WO-144, WO-161). This module
    only composes; each owner decides its own meaning."""
    from actions.delegation.authority_boundary import check_action
    from identity.identity.agent_identity import (
        agent_continuity, agent_identity, agent_identity_claims, continuity_hypotheses,
    )
    from intelligence.agent_behavior.population import adversarial_signals, market_compatibility
    from intelligence.risk360.agent_behavior_signals import (
        signals_from_adversarial, signals_from_authority_checks, signals_from_behavior_model,
    )
    from intelligence.risk360.agent_trust import reputation_profile, trust_profile
    from value.attribution.agent_behavior_value import attribute

    tenant = facts[0].tenant_id if facts else ""
    mine = [f for f in facts if f.agent_ref == agent_ref]
    actions = [f for f in mine if f.amount is not None and (
        f.event_type.startswith("agent_transaction_") or f.event_type.startswith("agent_execution_"))]
    approvals = _approval_timeline(facts)
    observed = [_observed_action(f, _granted_approval_ref(f, approvals)) for f in actions]
    checks = [check_action(a, grants, _prior_spends(actions, observed, i)).to_dict() | {"event_id": a.event_id}
              for i, a in enumerate(observed)]
    value = attribute(
        [{"event_id": f.event_id, "amount": str(f.amount), "currency": f.currency,
          "roles": decompose(f, facts, grants=grants)} for f in distinct_actions(actions)],
        agent_refs={f.agent_ref for f in facts if f.agent_ref},
    )
    adversarial = adversarial_signals(mine, checks)
    signals = (signals_from_behavior_model(tenant, model) + signals_from_authority_checks(tenant, agent_ref, checks)
               + signals_from_adversarial(tenant, agent_ref, adversarial)) if tenant else []
    claims = [cl for cl in agent_identity_claims(tenant, facts) if cl["identifier_value"] == agent_ref]
    return {
        "identity": _section("available", {
            "agent": agent_identity(tenant_id=tenant, agent_ref=agent_ref, facts=facts).to_dict(),
            "continuity": agent_continuity(tenant_id=tenant, agent_ref=agent_ref, facts=facts),
            "resolver_claims": claims,
            "review_items": [h for h in continuity_hypotheses(tenant, facts) if h["subject"] == agent_ref],
            "queued_reviews": [r for r in (queued_reviews or []) if r.get("status") == "open"],
            # A reviewer's judgement, not an Aether resolution: nothing is merged,
            # bound or relinked, and the agent refs stay source-reported.
            "continuity_decisions": [
                {"review_id": r.get("id"), "decision": (r.get("decision") or {}).get("decision") or r.get("status"),
                 "decided_by": (r.get("decision") or {}).get("decided_by"),
                 "decided_at": (r.get("decision") or {}).get("decided_at"),
                 "basis": "reviewer_asserted", "merge_performed": False,
                 "source_identity_ids": sorted({str(i) for i in (r.get("candidate_source_identity_ids") or [])}
                                               | {str(r.get("identify_source_identity_id"))}),
                 "claim": ("reviewer judged the deployments report one logical agent"
                           if r.get("status") == "confirmed"
                           else "reviewer judged the deployments report distinct agents")}
                for r in (queued_reviews or []) if r.get("status") in {"confirmed", "rejected"}
            ],
        }) if mine else _section("unavailable", None, "no facts for this agent"),
        "authority": _section("available" if checks else "unavailable", checks,
                              None if checks else "no value-moving actions observed"),
        "value": _section("available" if actions else "unavailable", value,
                          None if actions else "no value-moving actions observed"),
        "risk": _section("available", {
            "signals": [sig.model_dump(mode="json") for sig in signals],
            "adversarial": adversarial,
            "note": "Risk signals for the Risk360 pipeline; not findings.",
        }),
        "trust": _section("available" if mine else "unavailable", {
            "trust": trust_profile(model, checks), "reputation": reputation_profile(agent_ref, []),
        }),
        "market": _section("available" if mine else "unavailable", market_compatibility(mine)),
    }


def agent360_behavior(facts: list[AgentFact], agent_ref: str, *, identity: Optional[dict[str, Any]] = None,
                      handoffs: Iterable[dict[str, Any]] = (), truncated: bool = False,
                      grants: Iterable[dict[str, Any]] = (),
                      queued_reviews: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    model = build_behavior_model(facts, agent_ref, identity=identity)
    governance = _governance(facts, agent_ref, model, list(grants), queued_reviews)
    decisions = [d for d in project_decisions([f for f in facts if f.agent_ref == agent_ref])["decisions"]
                 if d["decision_actor"].get("value") == agent_ref]
    partial = "partial" if truncated else "available"
    have = bool(model["evidence"]["facts"])
    return {
        "agent_ref": agent_ref,
        "read_model_version": READ_MODEL_VERSION,
        "model": model["model"],
        "source_truncated": truncated,
        "sections": {
            "identity": (_section("available", identity) if identity else governance["identity"]),
            "behavior": _section(partial if have else "unavailable", {
                "what_it_usually_does": model["what_it_usually_does"],
                "features": model["features"],
                "capabilities": model["capabilities"],
                "competencies": model["competencies"],
                "preferences": model["preferences"],
                "failure_resolution": model["failure_resolution"],
            }, None if have else "no facts for this agent"),
            "decisions": _section(partial if decisions else "unavailable", [{
                "decision_id": d["decision_id"], "status": d["status"],
                "disposition": d["disposition"]["disposition"],
                "objective": d["objective"].get("value"), "opened_at": d["opened_at"],
                "missing": d["missing"], "evidence": list(d["evidence"])[:25],
            } for d in decisions], None if decisions else "no decisions reconstructed"),
            "journey": _section(partial if have else "unavailable",
                                agent_journey(facts, agent_ref, handoffs=handoffs) if have else None),
            "influence": _section(partial if have else "unavailable", influence_graph(facts) if have else None),
            "authority": governance["authority"],
            "value": governance["value"],
            "risk": governance["risk"],
            "trust": governance["trust"],
            "market": governance["market"],
            "observability": _section("available", {
                **model["observability"], "what_aether_cannot_see": model["what_aether_cannot_see"],
            }),
        },
    }


def decision_detail(facts: list[AgentFact], decision_id: str, *,
                    grants: Iterable[dict[str, Any]] = ()) -> Optional[dict[str, Any]]:
    decisions = {d["decision_id"]: d for d in project_decisions(facts)["decisions"]}
    env = decisions.get(decision_id)
    if env is None:
        return None
    actor = env["decision_actor"].get("value")
    model = build_behavior_model(facts, actor) if actor else None
    action_fact = next((f for f in reversed(facts) if f.event_id in set(env["evidence"])
                        and (f.amount is not None or f.event_type == "agent_action_selected")), None)
    return {
        "envelope": env,
        "attribution": decision_attribution(env, facts),
        "responsibility": decompose(action_fact, facts, grants=grants) if action_fact else None,
        "counterfactual": counterfactual_without_constraint(env, facts, model["preferences"] if model else []),
    }


# --- Profile360 human-agent reconciliation (WO-113) -----------------------------------

def profile360_agents(human_entity_id: str, facts: list[AgentFact],
                      grants: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Agents acting for a person, without merging identities.

    An agent is linked only by a recorded grant from this person or a declared
    beneficiary on the agent's own facts."""
    granted = sorted({g["grantee_entity_id"] for g in grants
                      if g.get("grantor_entity_id") == human_entity_id and g.get("grantee_entity_id")})
    declared = sorted({f.agent_ref for f in facts if f.principal_id == human_entity_id and f.agent_ref})
    agents = []
    for ref in sorted(set(granted) | set(declared)):
        model = build_behavior_model(facts, ref)
        agents.append({
            "agent_ref": ref,
            "link_basis": "recorded_grant" if ref in granted else "declared_beneficiary",
            "usual_disposition": model["what_it_usually_does"]["usual_disposition"],
            "decisions": model["evidence"]["decisions"],
        })
    human_direct = sum(1 for f in facts if f.agent_ref is None and f.principal_id == human_entity_id)
    return {
        "human_entity_id": human_entity_id,
        "agents": agents,
        "identity_merge": "not_performed",
        "agent_mediated_actions": sum(1 for f in facts if f.agent_ref in {a["agent_ref"] for a in agents}),
        "human_direct_actions_observed": human_direct,
        "coupling": human_agent_coupling(human_entity_id, facts, [a["agent_ref"] for a in agents]),
    }


# --- communication, override, coupling (WO-130, WO-131, WO-132) --------------------------

def communications(facts: Iterable[AgentFact], agent_ref: str) -> dict[str, Any]:
    msgs = [f for f in facts if f.agent_ref == agent_ref and f.event_type in COMMUNICATION_EVENTS]
    counts: dict[str, int] = defaultdict(int)
    threads = set()
    for f in msgs:
        counts[f.event_type] += 1
        if f.attr("threadId", "thread_id"):
            threads.add(f.attr("threadId", "thread_id"))
    return {"agent_ref": agent_ref, "by_type": dict(sorted(counts.items())), "threads": len(threads),
            "content": "not_stored", "evidence": [f.event_id for f in msgs][:25]}


def human_overrides(facts: Iterable[AgentFact]) -> list[dict[str, Any]]:
    facts = list(facts)
    out = []
    for f in facts:
        if not (f.event_type == "agent_human_override_observed" or f.human_override):
            continue
        after = next((g for g in facts if g.agent_ref == f.agent_ref and g.occurred_at > f.occurred_at
                      and (g.outcome or g.event_type.endswith(("_succeeded", "_failed")))), None)
        out.append({
            "event_id": f.event_id, "agent_ref": f.agent_ref, "decision": f.decision_ref,
            "overridden_by": c.declared(f.attr("overriddenBy", "overridden_by"), [f.event_id]).to_dict()
            if f.attr("overriddenBy", "overridden_by") else c.unknown("overriding human not reported").to_dict(),
            "override_kind": f.attr("overrideKind", "override_kind") or "unspecified",
            "outcome_after": (after.outcome or after.event_type) if after else None,
            "outcome_evidence": [after.event_id] if after else [],
        })
    return out


def human_agent_coupling(human_entity_id: str, facts: Iterable[AgentFact], agents: Iterable[str]) -> dict[str, Any]:
    agents = set(agents)
    facts = [f for f in facts if f.agent_ref in agents]
    requested = {f.authorization_ref or f.decision_ref: f for f in facts
                 if f.event_type == "agent_authorization_requested" and (f.authorization_ref or f.decision_ref)}
    latencies = []
    for f in facts:
        key = f.authorization_ref or f.decision_ref
        if f.event_type in {"agent_authorization_granted", "agent_authorization_denied"} and key in requested:
            a, b = _ts(requested[key].occurred_at), _ts(f.occurred_at)
            if a and b:
                latencies.append((b - a).total_seconds())
    escalations = sum(1 for f in facts if f.event_type == "agent_escalated_to_human")
    overrides = len(human_overrides(facts))
    decisions = len({f.decision_ref for f in facts if f.decision_ref})
    return {
        "human_entity_id": human_entity_id,
        "agents": sorted(agents),
        "approval_requests": len(requested),
        "approval_latency_seconds_median": sorted(latencies)[len(latencies) // 2] if latencies else None,
        "escalations": escalations,
        "overrides": overrides,
        "override_rate": round(overrides / decisions, 4) if decisions else None,
        "basis": c.DERIVED,
    }


# --- query orchestration capabilities (WO-115) --------------------------------------------

#: Closed read-capability list for Noesis / Access Kit. Each maps to one owner
#: function; there is no free-form behavioral query.
QUERY_CAPABILITIES: dict[str, dict[str, Any]] = {
    "agent_behavior.summary": {"returns": "Agent360 behavior read model", "args": ["agent_ref"]},
    "agent_behavior.decision": {"returns": "DecisionEnvelope + attribution + responsibility", "args": ["decision_id"]},
    "agent_behavior.lineage": {"returns": "spawn lineage tree", "args": ["root_agent_ref"]},
    "agent_behavior.human_agents": {"returns": "Profile360 agent reconciliation", "args": ["human_entity_id"]},
}


def run_capability(name: str, facts: list[AgentFact], args: dict[str, Any],
                   grants: Iterable[dict[str, Any]] = ()) -> Any:
    handlers: dict[str, Callable[[], Any]] = {
        "agent_behavior.summary": lambda: agent360_behavior(facts, args["agent_ref"]),
        "agent_behavior.decision": lambda: decision_detail(facts, args["decision_id"], grants=grants),
        "agent_behavior.human_agents": lambda: profile360_agents(args["human_entity_id"], facts, grants),
    }
    if name not in QUERY_CAPABILITIES:
        raise ValueError(f"unknown capability {name!r}")
    if name not in handlers:
        raise ValueError(f"{name} is served by its owning route")
    missing = [a for a in QUERY_CAPABILITIES[name]["args"] if not args.get(a)]
    if missing:
        raise ValueError(f"missing {', '.join(missing)}")
    return handlers[name]()
