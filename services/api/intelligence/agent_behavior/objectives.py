"""Objectives, goal mutation, constraints, resources and state (WO-040–WO-044).

All of it is reconstructed from agent facts. Declared things (an objective's
goal, a budget) stay ``declared``; things Aether watched happen stay
``observed``; anything Aether could not see is explicitly ``not_observed``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable, Optional

from intelligence.agent_behavior import contracts as c
from intelligence.agent_behavior.facts import AgentFact

# --- objectives (WO-040) -------------------------------------------------------

LIFECYCLE = ("created", "active", "blocked", "completed", "failed", "abandoned", "superseded")
TERMINAL = frozenset({"completed", "failed", "abandoned", "superseded"})
_TRANSITIONS = {
    "agent_objective_created": "created",
    "agent_objective_started": "active",
    "agent_objective_completed": "completed",
    "agent_objective_failed": "failed",
    "agent_objective_abandoned": "abandoned",
}
_ALLOWED = {
    None: {"created", "active"},
    "created": {"active", "blocked", "completed", "failed", "abandoned", "superseded"},
    "active": {"blocked", "completed", "failed", "abandoned", "superseded"},
    "blocked": {"active", "completed", "failed", "abandoned", "superseded"},
}
_BLOCKING = frozenset({"deny", "denied", "block", "blocked"})


@dataclass
class Objective:
    objective_id: str
    basis: str
    owner_actor: dict[str, Any]
    executing_actors: list[str] = field(default_factory=list)
    parent_objective: Optional[str] = None
    type: Optional[str] = None
    declared_goal: Optional[str] = None
    status: str = "created"
    constraints: list[dict[str, Any]] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    priority: Optional[int] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    evidence: list[str] = field(default_factory=list)
    mutations: list[dict[str, Any]] = field(default_factory=list)
    anomalies: list[dict[str, Any]] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


def _transition(obj: Objective, to: str, fact: AgentFact) -> None:
    if obj.status in TERMINAL or to not in _ALLOWED.get(obj.status, set()):
        obj.anomalies.append({"event_id": fact.event_id, "from": obj.status, "attempted": to,
                              "reason": "transition_not_allowed"})
        return
    obj.history.append({"from": obj.status, "to": to, "event_id": fact.event_id, "at": fact.occurred_at})
    obj.status = to
    if to == "active" and not obj.started_at:
        obj.started_at = fact.occurred_at
    if to in TERMINAL:
        obj.completed_at = fact.occurred_at


def _list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if v not in (None, "")]
    return [str(value)] if value not in (None, "") else []


def reconstruct_objectives(facts: Iterable[AgentFact]) -> dict[str, Objective]:
    """Objectives by id. Tasks with no declared objective become derived
    objectives keyed ``task:<ref>`` so downstream work always has an anchor."""
    facts = list(facts)
    out: dict[str, Objective] = {}
    for f in facts:
        oid = f.objective_ref
        if not oid:
            continue
        obj = out.get(oid)
        if obj is None:
            owner = f.attr("ownerActorId", "owner_actor_id")
            obj = out[oid] = Objective(
                objective_id=oid, basis=c.DECLARED,
                owner_actor=(c.declared(owner, [f.event_id]) if owner
                             else c.unknown("no objective owner declared")).to_dict(),
                status="created" if f.event_type == "agent_objective_created" else "active",
            )
            if f.event_type != "agent_objective_created":
                obj.started_at = f.occurred_at
                obj.anomalies.append({"event_id": f.event_id, "reason": "objective_seen_before_creation"})
        obj.evidence.append(f.event_id)
        if f.agent_ref and f.agent_ref not in obj.executing_actors:
            obj.executing_actors.append(f.agent_ref)
        if f.event_type == "agent_objective_created":
            obj.parent_objective = f.parent_objective_ref or obj.parent_objective
            obj.type = f.attr("objectiveType", "objective_type") or obj.type
            obj.declared_goal = f.attr("goal", "declaredGoal") or obj.declared_goal
            obj.success_criteria = _list(f.attr("successCriteria", "success_criteria")) or obj.success_criteria
            obj.priority = f.attr("priority") if isinstance(f.attr("priority"), int) else obj.priority
            for item in _list(f.attr("constraints")):
                obj.constraints.append({"constraint": item, "basis": c.DECLARED, "evidence": [f.event_id]})
        elif f.event_type == "agent_objective_modified":
            record_mutation(obj, f)
        elif f.event_type in _TRANSITIONS and _TRANSITIONS[f.event_type] != "created":
            _transition(obj, _TRANSITIONS[f.event_type], f)
        elif ((f.event_type in {"agent_policy_evaluated", "agent_authorization_denied"})
              and (f.policy_decision in _BLOCKING or f.event_type == "agent_authorization_denied")):
            _transition(obj, "blocked", f)
        elif f.event_type == "agent_authorization_granted" and obj.status == "blocked":
            _transition(obj, "active", f)
    for f in facts:
        if f.objective_ref or not f.task_ref:
            continue
        oid = f"task:{f.task_ref}"
        obj = out.setdefault(oid, Objective(
            objective_id=oid, basis=c.DERIVED,
            owner_actor=c.unknown("derived from a task; no objective declared").to_dict(), status="active",
            started_at=f.occurred_at,
        ))
        obj.evidence.append(f.event_id)
        if f.agent_ref and f.agent_ref not in obj.executing_actors:
            obj.executing_actors.append(f.agent_ref)
        if f.event_type in {"agent_task_completed", "agent_task_failed"} and obj.status not in TERMINAL:
            _transition(obj, "completed" if f.event_type == "agent_task_completed" else "failed", f)
    return out


# --- goal mutation and precedence (WO-041) ------------------------------------

_MUTABLE = ("goal", "constraints", "successCriteria", "priority", "deadline")


def record_mutation(obj: Objective, fact: AgentFact) -> None:
    changes = fact.attr("changes") if isinstance(fact.attr("changes"), dict) else {
        k: fact.attributes[k] for k in _MUTABLE if k in fact.attributes
    }
    if not changes:
        obj.anomalies.append({"event_id": fact.event_id, "reason": "modification_without_changes"})
        return
    obj.mutations.append({
        "event_id": fact.event_id, "at": fact.occurred_at, "fields": sorted(changes),
        "modified_by": fact.attr("modifiedBy", "modified_by") or fact.agent_ref,
        "modified_by_basis": c.DECLARED if fact.attr("modifiedBy", "modified_by") else c.OBSERVED,
        "previous_goal": obj.declared_goal if "goal" in changes else None,
        "new_goal": changes.get("goal"),
    })
    if "goal" in changes:
        obj.declared_goal = changes["goal"]
    if "successCriteria" in changes:
        obj.success_criteria = _list(changes["successCriteria"])
    if isinstance(changes.get("priority"), int):
        obj.priority = changes["priority"]


def objective_precedence(objectives: Iterable[Objective], human_actors: Iterable[str] = ()) -> list[dict[str, Any]]:
    """Order concurrently active objectives.

    Rule, highest first: explicit declared priority; human-owned before
    agent-owned; parent before child; earlier start. The applied rule is
    reported for every pair-deciding step so the order is explainable.
    """
    humans = set(human_actors)
    active = [o for o in objectives if o.status in {"created", "active", "blocked"}]
    ids = {o.objective_id for o in active}

    def key(o: Objective):
        owner = o.owner_actor.get("value")
        return (
            -(o.priority if isinstance(o.priority, int) else -10**6),
            0 if owner in humans else 1,
            1 if o.parent_objective in ids else 0,
            o.started_at or "~",
            o.objective_id,
        )

    ranked = sorted(active, key=key)
    return [{
        "objective_id": o.objective_id, "rank": i + 1, "priority": o.priority,
        "human_owned": o.owner_actor.get("value") in humans,
        "rule": "declared_priority" if isinstance(o.priority, int) else
                "human_owner" if o.owner_actor.get("value") in humans else
                "parent_before_child" if o.parent_objective not in ids else "earliest_start",
    } for i, o in enumerate(ranked)]


# --- constraints (WO-042) --------------------------------------------------------

CONSTRAINT_KINDS = ("policy", "authority", "budget", "time", "allowlist", "declared")


def constraints_for(facts: Iterable[AgentFact], *, decision_ref: Optional[str] = None,
                    objective: Optional[Objective] = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for f in facts:
        if decision_ref and f.decision_ref not in (None, decision_ref):
            continue
        if f.event_type == "agent_policy_evaluated":
            denied = (f.policy_decision or "").lower() in _BLOCKING
            out.append({
                "kind": "policy", "ref": f"{f.policy_id}@{f.policy_version}" if f.policy_version else f.policy_id,
                "status": "violated" if denied else "satisfied", "decision": f.policy_decision,
                "reason_codes": list(f.policy_reason_codes), "applies_to": f.candidate_ref or f.action_type,
                "basis": c.OBSERVED, "evidence": [f.event_id],
            })
        elif f.event_type in {"agent_authorization_denied", "agent_authorization_granted"}:
            out.append({
                "kind": "authority", "ref": f.authorization_ref,
                "status": "violated" if f.event_type.endswith("denied") else "satisfied",
                "applies_to": f.candidate_ref or f.action_type, "basis": c.OBSERVED, "evidence": [f.event_id],
            })
    if objective:
        for item in objective.constraints:
            out.append({"kind": "declared", "ref": item["constraint"], "status": "unknown",
                        "basis": c.DECLARED, "evidence": item["evidence"]})
    return out


# --- resources (WO-043) -----------------------------------------------------------

def resource_envelope(facts: Iterable[AgentFact], agent_ref: str,
                      grants: Iterable[dict[str, Any]] = ()) -> dict[str, Any]:
    facts = [f for f in facts if f.agent_ref == agent_ref]
    budget_facts = [f for f in facts if f.attr("budget", "budgetAmount") is not None]
    tools_used = sorted({f.tool_name for f in facts if f.tool_name})
    declared_tools = sorted({t for f in facts for t in _list(f.attr("availableTools", "toolsAvailable"))})
    spent = sum((f.amount for f in facts if f.amount is not None and f.event_type in
                 {"agent_transaction_initiated", "agent_transaction_settled"}), Decimal(0))
    deadline = next((f.attr("deadline") for f in facts if f.attr("deadline")), None)
    grants = [g for g in grants if g.get("grantee_entity_id") == agent_ref]
    return {
        "budget": (c.declared(str(budget_facts[-1].attr("budget", "budgetAmount")), [budget_facts[-1].event_id])
                   if budget_facts else c.not_observed("no budget reported")).to_dict(),
        "observed_spend": str(spent),
        "tools_available": (c.declared(declared_tools, [f.event_id for f in facts if f.attr("availableTools", "toolsAvailable")])
                            if declared_tools else c.not_observed("tool inventory not reported")).to_dict(),
        "tools_used": (c.observed(tools_used, [f.event_id for f in facts if f.tool_name]) if tools_used
                       else c.unknown("no tool use observed")).to_dict(),
        "time_limit": (c.declared(deadline, [next(f.event_id for f in facts if f.attr("deadline"))])
                       if deadline else c.not_observed("no deadline reported")).to_dict(),
        "permissions": [{"grant_id": g.get("delegation_id"), "scope": g.get("scope"), "basis": c.RESOLVED}
                        for g in grants],
    }


# --- environment and observed state (WO-044) ----------------------------------

def state_at(facts: Iterable[AgentFact], agent_ref: str, at: str,
             environment_records: Iterable[dict[str, Any]] = ()) -> dict[str, Any]:
    """What the agent had observed by ``at`` versus what independent records
    say the environment was. Agent reports never populate the environment side."""
    seen = [f for f in facts if f.agent_ref == agent_ref and f.occurred_at <= at]
    observed_state = {
        "information": [{"source": f.information_source_ref, "event_id": f.event_id}
                        for f in seen if f.event_type in {"agent_information_retrieved", "agent_source_consulted"}],
        "context": [f.event_id for f in seen if f.event_type == "agent_context_received"],
        "quotes": [{"amount": str(f.amount) if f.amount is not None else None, "currency": f.currency,
                    "object": f.object_ref, "event_id": f.event_id}
                   for f in seen if f.event_type in {"agent_quote_received", "agent_price_evaluated"}],
        "tool_results": [{"tool": f.tool_name, "status": f.status, "event_id": f.event_id}
                         for f in seen if f.tool_name and f.status in {"succeeded", "failed"}],
        "basis": c.OBSERVED,
    }
    env = [r for r in environment_records if str(r.get("at") or "") <= at]
    return {
        "at": at,
        "observed_state": observed_state,
        "environment_state": ({"records": env, "basis": c.RESOLVED} if env else
                              c.not_observed("no independent environment record for this time").to_dict()),
    }
