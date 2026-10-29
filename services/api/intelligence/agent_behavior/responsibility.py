"""Responsibility decomposition and influence semantics (WO-022, WO-023).

Roles are filled independently from evidence (ADR-AB-005). A role nobody
reported stays ``unknown``; it is never copied from another role, so "the
agent executed it" never becomes "the agent decided, authorized, funded and
benefited from it".

Influence edges carry a state (observed / declared / inferred). Inferred
influence built only from circumstantial signals (shared egress, shared tools,
similar behavior) is capped and can never assert control.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from intelligence.agent_behavior import contracts as c
from intelligence.agent_behavior.facts import AgentFact

ROLES = (
    "objective_owner", "initiating_actor", "instruction_source", "decision_actor",
    "execution_actor", "authorization_actor", "funding_actor", "beneficiary_actor",
    "influencing_actor",
)
INFLUENCE_RELATIONS = ("instructed", "recommended", "influenced", "blocked", "verified", "authorized")
INFLUENCE_STATES = ("observed", "declared", "inferred")
CIRCUMSTANTIAL_SIGNALS = frozenset({
    "shared_egress", "shared_endpoint", "shared_tools", "similar_behavior",
    "timing_correlation", "overlapping_targets",
})
CIRCUMSTANTIAL_CAP = 0.55


def _spawn_parents(facts: list[AgentFact]) -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    for f in facts:
        if f.event_type == "agent_subagent_spawned" and f.child_agent_ref:
            out.setdefault(f.child_agent_ref, (f.parent_agent_ref or f.agent_ref or "", f.event_id))
        elif f.event_type == "agent_delegated_task" and f.delegated_to_ref:
            out.setdefault(f.delegated_to_ref, (f.agent_ref or "", f.event_id))
    return out


def _root(agent: str, parents: dict[str, tuple[str, str]]) -> tuple[str, list[str]]:
    seen, chain = {agent}, []
    while agent in parents:
        parent, ev = parents[agent]
        if not parent or parent in seen:
            break
        seen.add(parent)
        chain.append(ev)
        agent = parent
    return agent, chain


def decompose(
    action: AgentFact,
    facts: Iterable[AgentFact],
    *,
    grants: Iterable[dict[str, Any]] = (),
    influence: Iterable["InfluenceEdge"] = (),
) -> dict[str, dict[str, Any]]:
    """All nine roles for one observed action, each evidence-qualified."""
    facts = [f for f in facts if f.tenant_id == action.tenant_id]
    grants = list(grants)
    parents = _spawn_parents(facts)
    roles: dict[str, c.Claim] = {}
    agent = action.agent_ref

    roles["execution_actor"] = (c.observed(agent, [action.event_id]) if agent
                                else c.unknown("action fact carries no agent reference"))

    selected = [f for f in facts if f.event_type == "agent_action_selected" and action.decision_ref
                and f.decision_ref == action.decision_ref]
    roles["decision_actor"] = (c.observed(selected[0].agent_ref, [selected[0].event_id]) if selected
                               and selected[0].agent_ref else
                               c.unknown("no action selection observed for this decision"))

    if agent and agent in parents:
        parent, ev = parents[agent]
        roles["instruction_source"] = c.observed(parent, [ev])
        root, chain = _root(agent, parents)
        roles["initiating_actor"] = c.derived(root, chain, reason="root of the observed spawn/delegation chain")
    else:
        roles["instruction_source"] = c.unknown("no delegation or spawn into this agent observed")
        roles["initiating_actor"] = c.unknown("no lineage observed above this agent")

    auth = [f for f in facts if f.event_type == "agent_authorization_granted"
            and (f.authorization_ref and f.authorization_ref == action.authorization_ref
                 or f.decision_ref and f.decision_ref == action.decision_ref)]
    approver = auth[0].attr("approverActorId", "approver_actor_id") if auth else None
    if approver:
        roles["authorization_actor"] = c.declared(approver, [auth[0].event_id])
    else:
        initiator = roles["initiating_actor"].value or agent
        grantors = sorted({g.get("grantor_entity_id") for g in grants
                           if g.get("grantee_entity_id") in {agent, initiator} and g.get("grantor_entity_id")})
        roles["authorization_actor"] = (
            c.Claim(grantors[0], c.RESOLVED, reason="grantor of a recorded delegation; grants authority, not intent")
            if len(grantors) == 1 else
            c.unknown("no authorization observed" if not grantors else "several possible grantors")
        )

    owners = [f for f in facts if f.event_type == "agent_objective_created" and action.objective_ref
              and f.objective_ref == action.objective_ref and f.attr("ownerActorId", "owner_actor_id")]
    roles["objective_owner"] = (c.declared(owners[0].attr("ownerActorId", "owner_actor_id"), [owners[0].event_id])
                                if owners else c.unknown("no objective owner declared"))

    funder = action.attr("fundingActorId", "funding_actor_id")
    roles["funding_actor"] = (c.declared(funder, [action.event_id]) if funder else
                              c.not_observed("funding source is outside agent telemetry")
                              if action.amount is not None else c.not_applicable("action moves no value"))
    roles["beneficiary_actor"] = (c.declared(action.principal_id, [action.event_id]) if action.principal_id
                                  else c.unknown("no beneficiary declared"))

    infl = [e for e in influence if e.target == agent and e.relation in {"instructed", "recommended", "influenced"}]
    if infl:
        strongest = max(infl, key=lambda e: (e.state != "inferred", e.confidence))
        roles["influencing_actor"] = c.Claim(
            strongest.source, c.INFERRED if strongest.state == "inferred" else c.OBSERVED if strongest.state == "observed" else c.DECLARED,
            tuple(strongest.evidence), confidence=strongest.confidence if strongest.state == "inferred" else None,
        )
    else:
        roles["influencing_actor"] = c.unknown("no influence observed")
    return {role: roles[role].to_dict() for role in ROLES}


@dataclass(frozen=True)
class InfluenceEdge:
    source: str
    target: str
    relation: str
    state: str
    evidence: tuple[str, ...]
    confidence: float = 1.0
    signals: tuple[str, ...] = ()
    implies_control: bool = False
    competing_explanations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.relation not in INFLUENCE_RELATIONS:
            raise ValueError(f"unknown relation {self.relation!r}")
        if self.state not in INFLUENCE_STATES:
            raise ValueError(f"unknown state {self.state!r}")
        if self.state == "inferred" and self.implies_control:
            raise ValueError("inferred influence can never imply control")
        if not self.evidence and self.state != "inferred":
            raise ValueError("observed/declared influence must cite evidence")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source, "target": self.target, "relation": self.relation,
            "state": self.state, "epistemic_status": c.BASIS_TO_EPISTEMIC[self.state].value,
            "evidence": list(self.evidence), "confidence": round(self.confidence, 4),
            "signals": list(self.signals), "implies_control": self.implies_control,
            "competing_explanations": list(self.competing_explanations),
        }


def observed_influence(facts: Iterable[AgentFact]) -> list[InfluenceEdge]:
    """Influence edges that rest on direct evidence."""
    edges: dict[tuple[str, str, str], InfluenceEdge] = {}

    def add(source: Optional[str], target: Optional[str], relation: str, state: str, ev: str) -> None:
        if source and target and source != target:
            edges.setdefault((source, target, relation), InfluenceEdge(source, target, relation, state, (ev,)))

    for f in facts:
        if f.event_type == "agent_subagent_spawned":
            add(f.parent_agent_ref or f.agent_ref, f.child_agent_ref, "instructed", "observed", f.event_id)
        elif f.event_type == "agent_delegated_task":
            add(f.agent_ref, f.delegated_to_ref, "instructed", "observed", f.event_id)
        elif f.event_type == "agent_authorization_granted":
            add(f.attr("approverActorId", "approver_actor_id"), f.agent_ref, "authorized", "declared", f.event_id)
        elif f.event_type in {"agent_policy_evaluated", "agent_authorization_denied"} and \
                (f.policy_decision in {"deny", "denied", "block", "blocked"} or f.event_type == "agent_authorization_denied"):
            add(f"policy:{f.policy_id}" if f.policy_id else "policy:unidentified", f.agent_ref, "blocked", "observed", f.event_id)
        elif f.event_type == "agent_action_selected" and f.attr("recommendedBy", "recommended_by"):
            add(f.attr("recommendedBy", "recommended_by"), f.agent_ref, "recommended", "declared", f.event_id)
        elif f.event_type in {"agent_execution_succeeded"} and f.attr("verifiedBy", "verified_by"):
            add(f.attr("verifiedBy", "verified_by"), f.agent_ref, "verified", "declared", f.event_id)
    return list(edges.values())


def infer_influence(
    source: str, target: str, signals: dict[str, Iterable[str]], *, base_confidence: float = 0.3,
) -> InfluenceEdge:
    """An inferred ``influenced`` edge from correlation signals.

    Circumstantial-only support is capped at :data:`CIRCUMSTANTIAL_CAP` and the
    edge never implies control (WO-023 guardrail).
    """
    names = tuple(sorted(k for k, v in signals.items() if list(v)))
    evidence = tuple(sorted({e for v in signals.values() for e in v}))
    confidence = min(0.95, base_confidence + 0.1 * len(names))
    if set(names) <= CIRCUMSTANTIAL_SIGNALS:
        confidence = min(confidence, CIRCUMSTANTIAL_CAP)
    return InfluenceEdge(
        source, target, "influenced", "inferred", evidence, confidence=confidence, signals=names,
        implies_control=False,
        competing_explanations=("shared_third_party_infrastructure", "common_vendor_template",
                                "independent_actors_with_similar_goals"),
    )
