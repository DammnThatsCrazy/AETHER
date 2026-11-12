"""Project fleet hypotheses into the Fraud360 hypothesis layer.

A fleet hypothesis answers "do these agents share a controlling operator?". Fraud360
already owns the lifecycle and no-silent-escalation rules for suspicion, so the fleet
result is mapped onto a ``FraudHypothesis`` instead of keeping a parallel record:

* The subject is the **canonical** Agent entity for the orchestrator. Source agent
  refs are claims by a deployment; if the canonical identity is unresolved or
  ambiguous nothing is written (same rule as the Risk360 agentic projection).
* ``claim_state`` is ``attributed`` when a canonical principal delegation backs a
  person link, otherwise ``inferred``. Never a factual state.
* Fleet status maps to the funnel: unconfirmed -> candidate, needs_review ->
  under_evaluation, reviewer-confirmed -> investigating, reviewer-rejected -> rejected.
  A reviewer confirming "common operator" is **not** confirmation of fraud, so the
  projection never reaches Fraud360 ``confirmed``; that needs separate factual evidence.
* Transitions go through ``FraudHypothesisStateMachine``. If an analyst has already moved
  the Fraud360 record somewhere the fleet status cannot legally reach, it is left alone
  and the result reports ``state_diverged``.
* Competing explanations stay on the fleet record, referenced from each evidence
  ``uri``; they are alternative readings, not contradictory evidence.
"""
from __future__ import annotations

import hashlib
from typing import Any, Optional

from graph.operational_intelligence.models import EvidenceRef
from intelligence.fraud360.contracts import (
    EpistemicStatus,
    FraudHypothesis,
    FraudHypothesisState,
    FraudHypothesisStateMachine,
    IllegalTransitionError,
)

PATTERN_ID = "agent_abuse"

_FUNNEL = (
    FraudHypothesisState.CANDIDATE,
    FraudHypothesisState.UNDER_EVALUATION,
    FraudHypothesisState.SUPPORTED,
    FraudHypothesisState.MATERIAL,
    FraudHypothesisState.INVESTIGATING,
)
_REJECTABLE = set(_FUNNEL[1:])

_STATUS_TARGET = {
    "unconfirmed": FraudHypothesisState.CANDIDATE,
    "needs_review": FraudHypothesisState.UNDER_EVALUATION,
    "confirmed_by_reviewer": FraudHypothesisState.INVESTIGATING,
    "rejected_by_reviewer": FraudHypothesisState.REJECTED,
}
_EVIDENCE_TYPE = {
    "observed_spawn_tree": "relationship",
    "canonical_principal_delegation": "relationship",
}


def fraud360_hypothesis_id(tenant_id: str, root_agent_ref: str) -> str:
    digest = hashlib.sha256(f"fleet\x00{tenant_id}\x00{root_agent_ref}".encode()).hexdigest()[:24]
    return f"fh_fleet_{digest}"


def _evidence_refs(fleet: dict[str, Any]) -> list[EvidenceRef]:
    refs: list[EvidenceRef] = []
    for item in fleet.get("evidence", []):
        kind = str(item.get("type"))
        refs.append(EvidenceRef(
            id=f"{fleet['hypothesis_id']}#{kind}",
            type=_EVIDENCE_TYPE.get(kind, "event"),
            source="fleet_hypothesis",
            observedAt=fleet.get("created_at"),
            confidence=min(max(float(item.get("strength", 0)), 0.0), 1.0),
            uri=f"store://fleet_hypotheses/{fleet['hypothesis_id']}#evidence/{kind}",
        ))
    return refs


def _review_ref(fleet: dict[str, Any]) -> Optional[EvidenceRef]:
    history = fleet.get("review_history") or []
    if not history:
        return None
    last = history[-1]
    return EvidenceRef(
        id=f"{fleet['hypothesis_id']}#review-{len(history)}",
        type="annotation",
        source="fleet_hypothesis_review",
        observedAt=last.get("reviewed_at"),
        uri=f"store://fleet_hypotheses/{fleet['hypothesis_id']}#review/{len(history)}",
    )


async def resolve_canonical_agent(
    tenant_id: str, source_agent_ref: str, reader: Optional[Any] = None
) -> Optional[str]:
    """The single canonical Agent entity for a source ref, or None (unresolved/ambiguous)."""
    if reader is None:
        from actions.agent.agent360_provider import RepositoryAgent360Source

        reader = RepositoryAgent360Source()
    read = await reader.actor_identity(tenant_id, source_agent_ref)
    if read.truncated or read.scope_mismatch:
        return None
    ids = {
        row["canonical_agent_entity_id"]
        for row in read.rows
        if isinstance(row, dict)
        and row.get("tenant_id") == tenant_id
        and row.get("agent_id") == source_agent_ref
        and isinstance(row.get("canonical_agent_entity_id"), str)
        and row.get("canonical_agent_entity_id")
    }
    return next(iter(ids)) if len(ids) == 1 else None


def _path(current: FraudHypothesisState, target: FraudHypothesisState) -> Optional[list[FraudHypothesisState]]:
    """Legal forward steps from ``current`` to ``target``, or None."""
    if current is target:
        return []
    if target is FraudHypothesisState.REJECTED:
        steps: list[FraudHypothesisState] = []
        if current is FraudHypothesisState.CANDIDATE:
            steps.append(FraudHypothesisState.UNDER_EVALUATION)
        elif current not in _REJECTABLE:
            return None
        return [*steps, target]
    if current in _FUNNEL and target in _FUNNEL and _FUNNEL.index(current) < _FUNNEL.index(target):
        return list(_FUNNEL[_FUNNEL.index(current) + 1: _FUNNEL.index(target) + 1])
    return None


async def project_fleet_hypothesis(
    fleet: dict[str, Any],
    *,
    agent_identity_reader: Optional[Any] = None,
    repo: Optional[Any] = None,
) -> dict[str, Any]:
    """Create or advance the Fraud360 record for a fleet hypothesis. Never raises on
    unresolvable identity; returns ``{"status": ..., "hypothesis_id": ...}``."""
    from intelligence.fraud360.store import FraudHypothesisRepository

    repo = repo or FraudHypothesisRepository()
    tenant_id = fleet["tenant_id"]
    canonical = await resolve_canonical_agent(tenant_id, fleet["root_agent_ref"], agent_identity_reader)
    if canonical is None:
        return {"status": "unresolved_agent_identity", "hypothesis_id": None}

    hypothesis_id = fraud360_hypothesis_id(tenant_id, fleet["root_agent_ref"])
    target = _STATUS_TARGET.get(str(fleet.get("status")), FraudHypothesisState.CANDIDATE)
    claim = EpistemicStatus.ATTRIBUTED if fleet.get("person_link") else EpistemicStatus.INFERRED
    refs = _evidence_refs(fleet)

    existing = await repo.get(tenant_id, hypothesis_id)
    if existing is None:
        await repo.create(tenant_id, FraudHypothesis(
            hypothesis_id=hypothesis_id,
            tenant_id=tenant_id,
            subject_kind="agent",
            subject_id=canonical,
            state=FraudHypothesisState.CANDIDATE,
            claim_state=claim,
            confidence=fleet.get("confidence"),
            matched_pattern_ids=[PATTERN_ID],
            evidence_refs=refs,
        ))
        current = FraudHypothesisState.CANDIDATE
    else:
        current = existing.state

    steps = _path(current, target)
    if steps is None:
        return {"status": "state_diverged", "hypothesis_id": hypothesis_id, "state": current.value}
    review = _review_ref(fleet)
    for step in steps:
        try:
            FraudHypothesisStateMachine.transition(
                current, step,
                evidence_refs=[review] if step is FraudHypothesisState.REJECTED and review else None,
                claim_state=claim,
            )
        except IllegalTransitionError:
            return {"status": "state_diverged", "hypothesis_id": hypothesis_id, "state": current.value}
        updated = await repo.update_state(
            tenant_id, hypothesis_id, step,
            evidence_refs=[review] if step is FraudHypothesisState.REJECTED and review else None,
        )
        if updated is None:
            return {"status": "unavailable", "hypothesis_id": hypothesis_id}
        current = step
    return {"status": "projected", "hypothesis_id": hypothesis_id, "state": current.value}
