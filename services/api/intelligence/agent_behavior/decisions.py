"""Opportunities, dispositions and DecisionEnvelopes (WO-045, WO-046, WO-050–WO-052).

A DecisionEnvelope reconstructs one decision of an observed actor from
evidence (ADR-AB-003). It is not Aether's ``DecisionRecord``. It is open while
evidence may still arrive and closes on outcome, abandonment or timeout; after
closure it only accepts append-only references, and a correction produces a
superseding version.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional

from intelligence.agent_behavior import contracts as c
from intelligence.agent_behavior.facts import AgentFact, watermark
from intelligence.agent_behavior.objectives import constraints_for, reconstruct_objectives
from intelligence.agent_behavior.taxonomy import ECONOMIC_EVENTS, EXECUTION_EVENTS, TOOL_EVENTS

MODEL = "decision_envelope"
VERSION = "1"
DEFAULT_TIMEOUT = timedelta(hours=24)
_DENY = frozenset({"deny", "denied", "block", "blocked"})
_EXECUTION = EXECUTION_EVENTS | ECONOMIC_EVENTS - {"agent_quote_received", "agent_price_evaluated"}
_OUTCOME = frozenset({"agent_decision_completed", "agent_task_completed", "agent_task_failed",
                      "agent_outcome_recorded", "agent_execution_succeeded", "agent_execution_failed",
                      "agent_execution_aborted", "agent_transaction_settled", "agent_transaction_failed"})

DISPOSITIONS = ("selected_action", "constrained_non_action", "abstained", "deferred", "escalated",
                "failed_execution", "unknown")


def _ts(value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None


# --- grouping ---------------------------------------------------------------------

def group_decisions(facts: Iterable[AgentFact]) -> dict[str, list[AgentFact]]:
    """Facts per decision. Explicit ``decision_ref`` wins; otherwise a decision
    window is derived per (agent, task) and labelled ``derived:``."""
    groups: dict[str, list[AgentFact]] = {}
    for f in facts:
        if f.decision_ref:
            groups.setdefault(f.decision_ref, []).append(f)
    for f in facts:
        if f.decision_ref or not f.agent_ref or not f.task_ref:
            continue
        if f.event_type in TOOL_EVENTS | _EXECUTION | {"agent_policy_evaluated", "agent_action_selected",
                                                         "agent_candidate_considered", "agent_task_completed",
                                                         "agent_task_failed", "agent_escalated_to_human"}:
            groups.setdefault(f"derived:{f.agent_ref}:{f.task_ref}", []).append(f)
    return groups


# --- candidates and opportunity (WO-051, WO-045) -----------------------------------

def reconstruct_candidates(group: list[AgentFact]) -> dict[str, Any]:
    cands: dict[str, dict[str, Any]] = {}

    def entry(ref: str) -> dict[str, Any]:
        return cands.setdefault(ref, {"candidate": ref, "considered": None, "rejected": None,
                                      "selected": None, "discovered_by": None})

    for f in group:
        if f.event_type == "agent_candidate_considered" and f.object_ref:
            entry(f.object_ref)["considered"] = c.observed(True, [f.event_id]).to_dict()
        elif f.event_type == "agent_candidate_rejected" and f.object_ref:
            entry(f.object_ref)["rejected"] = c.observed(
                f.attr("reason", "rejectionReason") or "unspecified", [f.event_id]).to_dict()
        elif f.event_type == "agent_action_selected" and f.object_ref:
            entry(f.object_ref)["selected"] = c.observed(True, [f.event_id]).to_dict()
        elif f.event_type in TOOL_EVENTS and f.status in {"succeeded", None} and f.object_ref:
            e = entry(f.object_ref)
            if e["discovered_by"] is None:
                e["discovered_by"] = c.derived(f.tool_name or "tool", [f.event_id],
                                               reason="object returned by a tool call in this decision").to_dict()
    started = any(f.event_type == "agent_decision_started" for f in group)
    closed = any(f.event_type == "agent_decision_completed" for f in group)
    declared_complete = any(f.attr("candidateSetComplete", "candidate_set_complete") is True for f in group)
    completeness = ("complete" if started and closed and declared_complete else
                    "partial" if cands else "unknown")
    return {"candidates": list(cands.values()), "completeness": completeness}


def opportunity_envelope(group: list[AgentFact], candidates: dict[str, Any],
                         budget: Optional[str] = None) -> dict[str, Any]:
    available = [x["candidate"] for x in candidates["candidates"]]
    blocked: dict[str, list[str]] = {}
    decision_blocked: list[str] = []
    for f in group:
        deny = (f.event_type == "agent_authorization_denied"
                or (f.event_type == "agent_policy_evaluated" and (f.policy_decision or "").lower() in _DENY))
        if not deny:
            continue
        target = f.object_ref if f.object_ref in available else None
        if target:
            blocked.setdefault(target, []).append(f.event_id)
        else:
            decision_blocked.append(f.event_id)
    permitted = [] if decision_blocked else [a for a in available if a not in blocked]
    prefer_ok = candidates["completeness"] != "unknown" and len(permitted) >= 2
    return {
        "available": available,
        "permitted": permitted,
        "blocked": {k: v for k, v in blocked.items()} | ({"*": decision_blocked} if decision_blocked else {}),
        "budget": budget,
        "completeness": candidates["completeness"],
        # ADR-AB-004: preference only over observed, permitted alternatives.
        "preference_inference": "allowed" if prefer_ok else "not_applicable",
        "preference_scope": permitted if prefer_ok else [],
    }


# --- disposition (WO-046) ------------------------------------------------------------

def action_disposition(group: list[AgentFact], opportunity: dict[str, Any]) -> dict[str, Any]:
    types = {f.event_type for f in group}
    executed = [f for f in group if f.event_type in _EXECUTION]
    failed = [f for f in executed if f.event_type.endswith(("_failed", "_aborted"))]
    selected = [f for f in group if f.event_type == "agent_action_selected"]
    outcome = next((f.outcome for f in reversed(group) if f.outcome), None)
    if "agent_escalated_to_human" in types:
        kind, ev = "escalated", [f.event_id for f in group if f.event_type == "agent_escalated_to_human"]
    elif failed and len(failed) == len(executed):
        kind, ev = "failed_execution", [f.event_id for f in failed]
    elif executed or selected:
        kind, ev = "selected_action", [f.event_id for f in (selected or executed)]
    elif opportunity["blocked"]:
        kind, ev = "constrained_non_action", sorted({e for v in opportunity["blocked"].values() for e in v})
    elif outcome in {"abstained", "no_action"}:
        kind, ev = "abstained", [f.event_id for f in group if f.outcome == outcome]
    elif outcome in {"deferred", "postponed"}:
        kind, ev = "deferred", [f.event_id for f in group if f.outcome == outcome]
    else:
        return {"disposition": "unknown", **c.unknown("no selection, execution or constraint observed").to_dict()}
    basis = c.OBSERVED if kind in {"escalated", "failed_execution", "selected_action"} else c.DERIVED
    claim = c.Claim(kind, basis, tuple(ev))
    return {"disposition": kind, **claim.to_dict()}


# --- DecisionEnvelope (WO-050) ------------------------------------------------------

@dataclass(frozen=True)
class DecisionEnvelope:
    decision_id: str
    tenant_id: str
    version: int
    status: str  # open | closed
    closed_reason: Optional[str]
    decision_actor: dict[str, Any]
    objective: dict[str, Any]
    candidates: dict[str, Any]
    opportunity: dict[str, Any]
    constraints: list[dict[str, Any]]
    selected_action: dict[str, Any]
    execution: dict[str, Any]
    outcome: dict[str, Any]
    disposition: dict[str, Any]
    evidence: tuple[str, ...]
    missing: tuple[str, ...]
    opened_at: Optional[str]
    closed_at: Optional[str]
    references: tuple[dict[str, Any], ...] = ()
    supersedes: Optional[str] = None
    content_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        out = {k: (list(v) if isinstance(v, tuple) else v) for k, v in self.__dict__.items()}
        out["envelope_ref"] = f"{self.decision_id}@v{self.version}"
        return out


def _hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:24]


def build_envelope(decision_id: str, group: list[AgentFact], all_facts: list[AgentFact], *,
                   now: Optional[str] = None, timeout: timedelta = DEFAULT_TIMEOUT) -> DecisionEnvelope:
    group = sorted(group, key=lambda f: (f.occurred_at, f.event_id))
    tenant = group[0].tenant_id
    actors = [f.agent_ref for f in group if f.event_type == "agent_action_selected" and f.agent_ref] or \
             [f.agent_ref for f in group if f.agent_ref]
    actor_basis = c.OBSERVED if any(f.event_type == "agent_action_selected" for f in group) else c.DERIVED
    decision_actor = (c.Claim(actors[0], actor_basis, tuple(f.event_id for f in group if f.agent_ref == actors[0])[:10])
                      if actors else c.unknown("no actor on decision facts"))
    obj_ref = next((f.objective_ref for f in group if f.objective_ref), None)
    task_ref = next((f.task_ref for f in group if f.task_ref), None)
    objectives = reconstruct_objectives(all_facts)
    obj = objectives.get(obj_ref) if obj_ref else objectives.get(f"task:{task_ref}") if task_ref else None
    objective = (c.Claim(obj.objective_id, obj.basis if obj.basis != c.RESOLVED else c.DECLARED,
                         tuple(obj.evidence[:10])).to_dict() if obj else
                 c.unknown("no objective or task reference on this decision").to_dict())
    candidates = reconstruct_candidates(group)
    opportunity = opportunity_envelope(group, candidates)
    constraints = constraints_for(group, objective=obj)
    selected = [f for f in group if f.event_type == "agent_action_selected"]
    selected_action = (c.observed({"action": selected[-1].action_type, "candidate": selected[-1].object_ref},
                                  [selected[-1].event_id]) if selected
                       else c.unknown("no action selection observed")).to_dict()
    executed = [f for f in group if f.event_type in _EXECUTION]
    execution = (c.observed([{"type": f.event_type, "status": f.status, "amount": str(f.amount) if f.amount is not None else None}
                             for f in executed], [f.event_id for f in executed]) if executed
                 else c.unknown("no execution observed")).to_dict()
    outcomes = [f for f in group if f.event_type in _OUTCOME]
    outcome = (c.observed(outcomes[-1].outcome or outcomes[-1].status or outcomes[-1].event_type,
                          [outcomes[-1].event_id]) if outcomes else c.unknown("no outcome observed")).to_dict()
    disposition = action_disposition(group, opportunity)

    closed_reason = None
    if any(f.event_type in _OUTCOME for f in group) or disposition["disposition"] in {"constrained_non_action", "abstained"}:
        closed_reason = "outcome_observed"
    elif any(f.event_type == "agent_objective_abandoned" for f in group):
        closed_reason = "abandoned"
    elif now and _ts(group[-1].occurred_at) and _ts(now) and _ts(now) - _ts(group[-1].occurred_at) > timeout:
        closed_reason = "timeout"
    missing = tuple(name for name, claim in (
        ("decision_actor", decision_actor.to_dict()), ("objective", objective),
        ("selected_action", selected_action), ("execution", execution), ("outcome", outcome),
    ) if claim.get("basis") in c.ABSENT_BASES) + (("candidate_set",) if candidates["completeness"] != "complete" else ())
    payload = dict(decision_id=decision_id, tenant_id=tenant, version=1,
                   status="closed" if closed_reason else "open", closed_reason=closed_reason,
                   decision_actor=decision_actor.to_dict(), objective=objective, candidates=candidates,
                   opportunity=opportunity, constraints=constraints, selected_action=selected_action,
                   execution=execution, outcome=outcome, disposition=disposition,
                   evidence=tuple(f.event_id for f in group), missing=missing,
                   opened_at=group[0].occurred_at,
                   closed_at=group[-1].occurred_at if closed_reason in {"outcome_observed", "abandoned"} else now if closed_reason else None)
    return DecisionEnvelope(**payload, content_hash=_hash(payload))


class ClosedEnvelopeError(ValueError):
    """A closed envelope only accepts append-only references or supersession."""


def append_reference(env: DecisionEnvelope, kind: str, ref: str, at: str) -> DecisionEnvelope:
    if kind not in {"late_evidence", "review", "supersession", "annotation"}:
        raise ValueError(f"unknown reference kind {kind!r}")
    return replace(env, references=env.references + ({"kind": kind, "ref": ref, "at": at},))


def update_envelope(env: DecisionEnvelope, rebuilt: DecisionEnvelope) -> DecisionEnvelope:
    """Apply a rebuild. Open envelopes are replaced in place (same version);
    a closed envelope whose content changed is superseded by version+1."""
    if rebuilt.content_hash == env.content_hash:
        return env
    if env.status == "open":
        return replace(rebuilt, version=env.version, references=env.references)
    return replace(rebuilt, version=env.version + 1, supersedes=f"{env.decision_id}@v{env.version}",
                   references=env.references)


def mutate_closed(env: DecisionEnvelope, **changes: Any) -> DecisionEnvelope:
    if env.status == "closed":
        raise ClosedEnvelopeError("closed DecisionEnvelopes are immutable; supersede instead")
    return replace(env, **changes)


# --- projector (WO-052) -----------------------------------------------------------------

def project_decisions(facts: Iterable[AgentFact], *, now: Optional[str] = None) -> dict[str, Any]:
    facts = sorted(facts, key=lambda f: (f.occurred_at, f.event_id))
    envelopes = [build_envelope(did, group, facts, now=now)
                 for did, group in sorted(group_decisions(facts).items())]
    return {
        "model": c.ModelVersion(MODEL, VERSION, watermark(facts), len(facts)).to_dict(),
        "decisions": [e.to_dict() for e in envelopes],
    }
