"""Objectives, constraints, resources, state and DecisionEnvelopes (WO-040–WO-052)."""
from __future__ import annotations

import pytest

from ingestion.silver.projectors.agent_execution_projector import AgentExecutionProjector
from intelligence.agent_behavior.decisions import (
    ClosedEnvelopeError, append_reference, build_envelope, group_decisions, mutate_closed,
    project_decisions, update_envelope,
)
from intelligence.agent_behavior.facts import normalize_rows
from intelligence.agent_behavior.objectives import (
    constraints_for, objective_precedence, reconstruct_objectives, resource_envelope, state_at,
)

T = "tenant-dec"


def facts(*events, start=0):
    rows = []
    for i, (etype, agent, props) in enumerate(events, start=start):
        rows.extend(AgentExecutionProjector().project({
            "messageId": f"d-{i:03d}", "type": etype, "tenantId": T,
            "timestamp": f"2026-10-22T10:{i // 60:02d}:{i % 60:02d}Z",
            "properties": {"agentId": agent, **props},
        }).rows)
    return normalize_rows(rows, T)


def test_objective_lifecycle_mutation_and_anomalies():
    fs = facts(
        ("agent_objective_created", "a", {"objectiveId": "o1", "ownerActorId": "person-1", "goal": "buy laptop",
                                          "constraints": ["max 1000 USD"], "priority": 2}),
        ("agent_objective_started", "a", {"objectiveId": "o1"}),
        ("agent_policy_evaluated", "a", {"objectiveId": "o1", "policyId": "p", "decision": "deny"}),
        ("agent_authorization_granted", "a", {"objectiveId": "o1"}),
        ("agent_objective_modified", "a", {"objectiveId": "o1", "goal": "buy refurbished laptop", "modifiedBy": "person-1"}),
        ("agent_objective_completed", "a", {"objectiveId": "o1"}),
        ("agent_objective_started", "a", {"objectiveId": "o1"}),
    )
    o = reconstruct_objectives(fs)["o1"]
    assert [h["to"] for h in o.history] == ["active", "blocked", "active", "completed"]
    assert o.status == "completed" and o.owner_actor["value"] == "person-1"
    assert o.declared_goal == "buy refurbished laptop"
    assert o.mutations[0]["previous_goal"] == "buy laptop" and o.mutations[0]["modified_by_basis"] == "declared"
    assert o.anomalies[-1]["reason"] == "transition_not_allowed"
    assert o.constraints[0]["basis"] == "declared"


def test_task_without_objective_gets_a_derived_anchor_and_precedence_is_explained():
    fs = facts(
        ("agent_task_started", "a", {"taskId": "t1"}),
        ("agent_objective_created", "a", {"objectiveId": "hi", "ownerActorId": "person-1"}),
        ("agent_objective_created", "a", {"objectiveId": "p9", "priority": 9}),
        ("agent_objective_created", "b", {"objectiveId": "child", "parentObjectiveId": "hi"}),
    )
    objs = reconstruct_objectives(fs)
    assert objs["task:t1"].basis == "derived" and objs["task:t1"].owner_actor["basis"] == "unknown"
    order = objective_precedence(objs.values(), human_actors={"person-1"})
    assert [o["objective_id"] for o in order][:2] == ["p9", "hi"]
    assert order[0]["rule"] == "declared_priority" and order[1]["rule"] == "human_owner"


def test_constraints_resources_and_state():
    fs = facts(
        ("agent_objective_created", "a", {"objectiveId": "o", "budget": "500", "availableTools": ["search", "buy"],
                                          "deadline": "2026-10-23T00:00:00Z"}),
        ("agent_information_retrieved", "a", {"sourceRef": "web:reviews"}),
        ("agent_quote_received", "a", {"amount": "420.00", "currency": "USD", "candidateId": "sku-9"}),
        ("agent_policy_evaluated", "a", {"policyId": "spend", "policyVersion": "3", "decision": "allow"}),
        ("agent_transaction_initiated", "a", {"amount": "420.00", "currency": "USD"}),
    )
    cons = constraints_for(fs)
    assert cons == [{**cons[0], "kind": "policy", "ref": "spend@3", "status": "satisfied"}]
    env = resource_envelope(fs, "a", grants=[{"delegation_id": "g", "grantee_entity_id": "a", "scope": {}}])
    assert env["budget"]["value"] == "500" and env["budget"]["basis"] == "declared"
    assert env["tools_available"]["value"] == ["buy", "search"]
    assert env["observed_spend"] == "420.00" and env["permissions"][0]["basis"] == "resolved"
    st = state_at(fs, "a", fs[2].occurred_at)
    assert st["observed_state"]["quotes"][0]["amount"] == "420.00"
    assert st["environment_state"]["epistemic_status"] == "unavailable"
    st2 = state_at(fs, "a", fs[2].occurred_at, environment_records=[{"at": "2026-10-22T09:00:00Z", "price": "410"}])
    assert st2["environment_state"]["basis"] == "resolved"


def _shopping(decision="d1", deny=False, extra=()):
    events = [
        ("agent_decision_started", "buyer", {"decisionId": decision, "objectiveId": "o"}),
        ("agent_candidate_considered", "buyer", {"decisionId": decision, "candidateId": "sku-1"}),
        ("agent_candidate_considered", "buyer", {"decisionId": decision, "candidateId": "sku-2"}),
        ("agent_candidate_rejected", "buyer", {"decisionId": decision, "candidateId": "sku-2", "reason": "price"}),
    ]
    if deny:
        events.append(("agent_policy_evaluated", "buyer", {"decisionId": decision, "policyId": "spend", "decision": "deny"}))
    else:
        events += [
            ("agent_action_selected", "buyer", {"decisionId": decision, "candidateId": "sku-1", "actionType": "purchase"}),
            ("agent_transaction_initiated", "buyer", {"decisionId": decision, "amount": "10"}),
        ]
    events += list(extra)
    return facts(*events)


def test_envelope_reconstructs_selection_with_evidence():
    fs = _shopping(extra=[("agent_decision_completed", "buyer", {"decisionId": "d1", "candidateSetComplete": True,
                                                                  "outcome": "purchased"})])
    env = build_envelope("d1", group_decisions(fs)["d1"], fs)
    assert env.status == "closed" and env.closed_reason == "outcome_observed"
    assert env.decision_actor["value"] == "buyer" and env.decision_actor["basis"] == "observed"
    assert env.selected_action["value"] == {"action": "purchase", "candidate": "sku-1"}
    assert env.candidates["completeness"] == "complete"
    rejected = {c["candidate"]: c for c in env.candidates["candidates"]}["sku-2"]["rejected"]
    assert rejected["value"] == "price"
    assert env.opportunity["preference_inference"] == "allowed"
    assert env.disposition["disposition"] == "selected_action"
    assert env.outcome["value"] == "purchased"
    assert set(env.evidence) == {f.event_id for f in fs}
    assert "candidate_set" not in env.missing


def test_constrained_non_action_blocks_preference_inference():
    fs = _shopping(deny=True)
    env = build_envelope("d1", group_decisions(fs)["d1"], fs)
    assert env.disposition["disposition"] == "constrained_non_action"
    assert env.opportunity["permitted"] == [] and env.opportunity["preference_inference"] == "not_applicable"
    assert env.status == "closed"
    assert "selected_action" in env.missing and "execution" in env.missing


def test_envelope_is_immutable_after_closure_and_superseded_on_change():
    fs = _shopping(extra=[("agent_decision_completed", "buyer", {"decisionId": "d1"})])
    env = build_envelope("d1", group_decisions(fs)["d1"], fs)
    with pytest.raises(ClosedEnvelopeError):
        mutate_closed(env, status="open")
    annotated = append_reference(env, "review", "rev-1", "2026-10-23T00:00:00Z")
    assert annotated.references[-1]["ref"] == "rev-1" and annotated.content_hash == env.content_hash
    late = fs + facts(("agent_candidate_considered", "buyer", {"decisionId": "d1", "candidateId": "sku-3"}), start=50)
    rebuilt = build_envelope("d1", group_decisions(late)["d1"], late)
    sup = update_envelope(annotated, rebuilt)
    assert sup.version == 2 and sup.supersedes == "d1@v1" and sup.references == annotated.references
    assert update_envelope(env, env) is env


def test_open_envelope_times_out_and_projector_is_deterministic():
    fs = facts(("agent_decision_started", "a", {"decisionId": "slow"}),
               ("agent_candidate_considered", "a", {"decisionId": "slow", "candidateId": "x"}))
    open_env = build_envelope("slow", group_decisions(fs)["slow"], fs)
    assert open_env.status == "open" and open_env.closed_at is None
    late = build_envelope("slow", group_decisions(fs)["slow"], fs, now="2026-10-25T00:00:00Z")
    assert late.status == "closed" and late.closed_reason == "timeout"
    a = project_decisions(fs)
    b = project_decisions(list(reversed(fs)))
    assert a == b and a["model"]["input_count"] == 2


def test_derived_decision_window_without_decision_ref():
    fs = facts(("agent_tool_invocation_observed", "w", {"taskId": "t", "toolName": "search", "status": "succeeded",
                                                         "objectType": "product", "objectId": "p1"}),
               ("agent_task_completed", "w", {"taskId": "t", "outcome": "completed"}))
    [(did, group)] = group_decisions(fs).items()
    assert did == "derived:w:t"
    env = build_envelope(did, group, fs)
    assert env.decision_actor["basis"] == "derived"
    assert env.candidates["candidates"][0]["discovered_by"]["basis"] == "derived"
    assert env.objective["value"] == "task:t"
