"""Agent identity, continuity and resolution claims (WO-011, WO-012, WO-013).

An agent is a specialization of the canonical actor model, not a parallel
identity system:

* :func:`agent_identity` classifies how well Aether knows an agent
  (``known_agent`` / ``probable_agent`` / ``unknown_automated_actor`` /
  ``unknown_actor``) without asserting a vendor, model or runtime it did not
  observe.
* :func:`agent_continuity` separates the logical agent from configuration
  versions and runtime instances, and records declared continuity relations
  (clone, fork, migration, restore, ...) only from evidence.
* :func:`agent_identity_claims` and :func:`continuity_hypotheses` hand the
  existing identity authority source-identity claims and review items. Agent
  identifiers stay non-merge-eligible (``merge_policy.NON_MERGE_ELIGIBLE_SIGNAL_NAMES``);
  an inferred continuity is a hypothesis for review, never a fact.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from identity.identity.actor_ref import ActorRef, actor_ref, agent_namespace
from identity.identity.merge_policy import NON_MERGE_ELIGIBLE_SIGNAL_NAMES

KNOWN_AGENT = "known_agent"
PROBABLE_AGENT = "probable_agent"
UNKNOWN_AUTOMATED_ACTOR = "unknown_automated_actor"
UNKNOWN_ACTOR = "unknown_actor"
RECOGNITION_STATES = (KNOWN_AGENT, PROBABLE_AGENT, UNKNOWN_AUTOMATED_ACTOR, UNKNOWN_ACTOR)

CONTINUITY_RELATIONS = (
    "clone", "fork", "migration", "restore", "checkpoint", "replacement",
    "continuation", "merge", "terminated",
)
AGENT_CLASSES = ("orchestrator", "worker", "assistant", "autonomous", "unknown")
PERSISTENCE = ("ephemeral", "session", "persistent", "unknown")

# Facts that only an automated actor emits. Their presence without a usable
# agent reference still tells us "something automated acted".
_AUTOMATION_EVENTS = frozenset({
    "agent_tool_invocation_observed", "agent_tool_called", "agent_subagent_spawned",
    "agent_task_started", "agent_decision_started", "agent_action_selected",
})


@dataclass(frozen=True)
class AgentIdentity:
    agent_id: str
    actor: ActorRef
    recognition: str
    agent_class: str
    persistence: str
    owner_actor_id: Optional[str]
    operator_actor_id: Optional[str]
    parent_agent_id: Optional[str]
    model_family: Optional[str]
    runtime: Optional[str]
    framework: Optional[str]
    first_seen: Optional[str]
    last_seen: Optional[str]
    status: str
    confidence: float
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "actor": self.actor.to_dict(),
            "recognition": self.recognition,
            "agent_class": self.agent_class,
            "persistence": self.persistence,
            "owner_actor_id": self.owner_actor_id,
            "operator_actor_id": self.operator_actor_id,
            "parent_agent_id": self.parent_agent_id,
            "model_family": self.model_family,
            "runtime": self.runtime,
            "framework": self.framework,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "status": self.status,
            "confidence": self.confidence,
            "provenance": self.provenance,
        }


def _first(facts: list[Any], getter) -> Optional[str]:
    for f in facts:
        value = getter(f)
        if value:
            return str(value)
    return None


def agent_identity(
    *,
    tenant_id: str,
    agent_ref: Optional[str],
    facts: Iterable[Any],
    canonical_agent_entity_id: Optional[str] = None,
    owner_entity_id: Optional[str] = None,
) -> AgentIdentity:
    """Classify one agent from its normalized facts (``AgentFact``)."""
    facts = list(facts)
    mine = [f for f in facts if f.tenant_id == tenant_id and (agent_ref is None or f.agent_ref == agent_ref)]
    deployment = _first(mine, lambda f: f.deployment_id)
    automated = any(f.event_type in _AUTOMATION_EVENTS for f in mine)
    if agent_ref and (canonical_agent_entity_id or deployment):
        recognition, confidence = KNOWN_AGENT, 0.95 if canonical_agent_entity_id else 0.85
    elif agent_ref:
        recognition, confidence = PROBABLE_AGENT, 0.6
    elif automated:
        recognition, confidence = UNKNOWN_AUTOMATED_ACTOR, 0.5
    else:
        recognition, confidence = UNKNOWN_ACTOR, 0.0

    value = agent_ref or "unidentified"
    if canonical_agent_entity_id:
        actor = actor_ref(tenant_id, "agent", canonical_agent_entity_id, namespace="canonical",
                          basis="resolved", resolved_entity_id=canonical_agent_entity_id)
    else:
        actor = actor_ref(tenant_id, "agent" if agent_ref else "unknown", value,
                          namespace=agent_namespace(deployment),
                          basis="observed" if agent_ref else "unknown")

    # A parent is only known from a spawn fact naming this agent as the child.
    spawned_by = next((f.parent_agent_ref for f in facts
                       if f.tenant_id == tenant_id and f.event_type == "agent_subagent_spawned"
                       and f.child_agent_ref == agent_ref and f.parent_agent_ref), None)
    spawns_children = any(f.event_type == "agent_subagent_spawned" and f.parent_agent_ref == agent_ref
                          for f in facts if f.tenant_id == tenant_id)
    agent_class = "orchestrator" if spawns_children else ("worker" if spawned_by else "unknown")
    terminated = any(f.event_type == "agent_terminated" for f in mine)
    runs = {f.run_id for f in mine if f.run_id}
    persistence = "ephemeral" if spawned_by and len(runs) <= 1 else ("persistent" if len(runs) > 1 else "unknown")
    times = sorted(f.occurred_at for f in mine if f.occurred_at)
    model = _first(mine, lambda f: f.model_id)
    return AgentIdentity(
        agent_id=actor.actor_id,
        actor=actor,
        recognition=recognition,
        agent_class=agent_class,
        persistence=persistence,
        owner_actor_id=owner_entity_id,
        operator_actor_id=None,
        parent_agent_id=spawned_by,
        # Reported model identifiers are kept as source claims; we never
        # derive a family or vendor we did not observe (non-goal of WO-011).
        model_family=model,
        runtime=_first(mine, lambda f: f.attr("runtime")),
        framework=_first(mine, lambda f: f.attr("framework")),
        first_seen=times[0] if times else None,
        last_seen=times[-1] if times else None,
        status="terminated" if terminated else ("active" if mine else "unobserved"),
        confidence=confidence,
        provenance={
            "deployment_id": deployment,
            "source_event_count": len(mine),
            "evidence": [f.event_id for f in mine[:25]],
            "model_basis": "source_reported" if model else "not_observed",
        },
    )


# --- continuity (WO-012) -----------------------------------------------------

def _config_fingerprint(fact: Any) -> Optional[str]:
    parts = [fact.model_id, fact.attr("runtime"), fact.attr("framework"),
             fact.attr("configVersion", "config_version")]
    if not any(parts):
        return None
    return hashlib.sha256("|".join(str(p or "") for p in parts).encode()).hexdigest()[:16]


def agent_continuity(*, tenant_id: str, agent_ref: str, facts: Iterable[Any]) -> dict[str, Any]:
    """Logical agent -> configuration versions -> runtime instances -> sessions -> actions."""
    mine = [f for f in facts if f.tenant_id == tenant_id and f.agent_ref == agent_ref]
    configs: list[dict[str, Any]] = []
    current: Optional[str] = None
    for f in mine:
        fp = _config_fingerprint(f)
        if fp and fp != current:
            configs.append({
                "version": len(configs) + 1,
                "fingerprint": fp,
                "model_id": f.model_id,
                "runtime": f.attr("runtime"),
                "framework": f.attr("framework"),
                "first_seen": f.occurred_at,
                "evidence": f.event_id,
                "basis": "observed",
            })
            current = fp
    instances: dict[str, dict[str, Any]] = {}
    for f in mine:
        if not f.run_id:
            continue
        inst = instances.setdefault(f.run_id, {
            "run_id": f.run_id, "first_seen": f.occurred_at, "last_seen": f.occurred_at,
            "sessions": set(), "action_count": 0, "configuration_version": len(configs) or None,
        })
        inst["last_seen"] = f.occurred_at
        if f.task_ref:
            inst["sessions"].add(f.task_ref)
        inst["action_count"] += 1
    relations = []
    for f in mine:
        relation = f.attr("continuityRelation", "continuity_relation")
        if f.event_type == "agent_terminated":
            relations.append({"relation": "terminated", "from": agent_ref, "to": None,
                              "basis": "observed", "evidence": f.event_id, "at": f.occurred_at})
        elif relation in CONTINUITY_RELATIONS:
            relations.append({"relation": relation, "from": f.attr("fromAgentId", "from_agent_id"),
                              "to": agent_ref, "basis": "declared", "evidence": f.event_id,
                              "at": f.occurred_at})
    return {
        "logical_agent": agent_ref,
        "configuration_versions": configs,
        "model_changed": len({c["model_id"] for c in configs if c["model_id"]}) > 1,
        "runtime_changed": len({c["runtime"] for c in configs if c["runtime"]}) > 1,
        "runtime_instances": [
            {**i, "sessions": sorted(i["sessions"])} for i in instances.values()
        ],
        "relations": relations,
    }


def classify_relationship(a: dict[str, Any], b: dict[str, Any]) -> str:
    """Relationship between two agents' continuity records.

    Returns one of: same_agent_new_model, same_agent_new_runtime, cloned,
    restored_checkpoint, child_agent, unrelated. Only declared or observed
    relations are used; similarity alone never makes two agents "the same".
    """
    for rel in b.get("relations", []):
        if rel["from"] == a["logical_agent"]:
            if rel["relation"] in {"clone", "fork"}:
                return "cloned"
            if rel["relation"] in {"restore", "checkpoint"}:
                return "restored_checkpoint"
            if rel["relation"] in {"migration", "continuation", "replacement"}:
                return "continued"
    if b.get("parent_agent_id") == a["logical_agent"]:
        return "child_agent"
    if a["logical_agent"] == b["logical_agent"]:
        if a.get("model_changed") or b.get("model_changed"):
            return "same_agent_new_model"
        if a.get("runtime_changed") or b.get("runtime_changed"):
            return "same_agent_new_runtime"
        return "same_agent"
    return "unrelated"


# --- identity-resolution integration (WO-013) --------------------------------

def agent_identity_claims(tenant_id: str, facts: Iterable[Any]) -> list[dict[str, Any]]:
    """Source-identity claims for the existing resolver.

    One claim per (namespace, agent ref). ``merge_eligible`` is always False:
    an agent identifier never merges people (merge-policy denylist).
    """
    assert "agent_id" in NON_MERGE_ELIGIBLE_SIGNAL_NAMES
    claims: dict[tuple[str, str], dict[str, Any]] = {}
    for f in facts:
        if f.tenant_id != tenant_id or not f.agent_ref:
            continue
        ns = agent_namespace(f.deployment_id)
        claim = claims.setdefault((ns, f.agent_ref), {
            "tenant_id": tenant_id,
            "identifier_type": "agent_id",
            "identifier_value": f.agent_ref,
            "source_namespace": ns,
            "trust_class": "SOURCE_REFERENCE" if f.deployment_id else "SOURCE_ASSERTED",
            "merge_eligible": False,
            "evidence": [],
        })
        if len(claim["evidence"]) < 25:
            claim["evidence"].append(f.event_id)
    return list(claims.values())


def continuity_hypotheses(tenant_id: str, facts: Iterable[Any]) -> list[dict[str, Any]]:
    """Ambiguous continuity becomes a review item with competing hypotheses.

    Trigger: the same agent ref reported from two different deployments
    namespaces, or a declared relation whose source agent was never observed.
    """
    facts = [f for f in facts if f.tenant_id == tenant_id and f.agent_ref]
    by_ref: dict[str, dict[str, list[str]]] = {}
    for f in facts:
        by_ref.setdefault(f.agent_ref, {}).setdefault(agent_namespace(f.deployment_id), []).append(f.event_id)
    known = {f.agent_ref for f in facts}
    out = []
    for ref, spaces in sorted(by_ref.items()):
        if len(spaces) > 1:
            out.append({
                "subject": ref,
                "review_state": "needs_review",
                "basis": "inferred",
                "question": "Are these one logical agent?",
                "namespaces": sorted(spaces),
                "hypotheses": [
                    {"id": "same_logical_agent", "evidence": sorted(e for ev in spaces.values() for e in ev)[:25]},
                    {"id": "identifier_collision_across_deployments", "evidence": []},
                ],
                "fact_status": "not_a_fact_until_reviewed",
            })
    for f in facts:
        source = f.attr("fromAgentId", "from_agent_id")
        if source and source not in known and f.attr("continuityRelation", "continuity_relation"):
            out.append({
                "subject": f.agent_ref,
                "review_state": "needs_review",
                "basis": "declared",
                "question": f"Declared {f.attr('continuityRelation', 'continuity_relation')} from an agent never observed",
                "hypotheses": [
                    {"id": "declared_relation_true", "evidence": [f.event_id]},
                    {"id": "source_agent_outside_observation", "evidence": []},
                ],
                "fact_status": "not_a_fact_until_reviewed",
            })
    return out
