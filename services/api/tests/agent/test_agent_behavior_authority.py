"""Authority boundaries, responsibility roles and influence semantics (WO-020–WO-023)."""
from __future__ import annotations

import pytest

from actions.delegation.authority_boundary import INSIDE, OUTSIDE, UNKNOWN, ObservedAction, check_action
from ingestion.silver.projectors.agent_execution_projector import AgentExecutionProjector
from intelligence.agent_behavior.facts import normalize_rows
from intelligence.agent_behavior.responsibility import (
    CIRCUMSTANTIAL_CAP, ROLES, InfluenceEdge, decompose, infer_influence, observed_influence,
)

T = "tenant-auth"
GRANT = {
    "delegation_id": "del-1", "grantor_entity_id": "person-1", "grantee_entity_id": "agent-1",
    "starts_at": "2026-10-01T00:00:00Z", "ends_at": "2026-11-01T00:00:00Z",
    "scope": {"actions": ["purchase"], "resources": ["merchant:*"], "max_amount": "100.00",
              "daily_limit": "150.00", "merchant_allowlist": ["shop-1", "shop-2"],
              "asset_allowlist": ["USD"], "human_approval_threshold": "80.00"},
}


def act(eid="a1", amount="20.00", at="2026-10-22T10:00:00Z", **kw):
    base = dict(event_id=eid, actor_ref="agent-1", action="purchase", occurred_at=at,
                resource="merchant:shop-1", amount=amount, merchant="shop-1", asset="USD")
    base.update(kw)
    return ObservedAction(**base)


def test_inside_boundary_explains_that_it_is_not_an_authorization_decision():
    r = check_action(act(), [GRANT])
    assert r.status == INSIDE and r.grant_id == "del-1"
    assert "daily_limit_checked_against_observed_spend_only" in r.notes
    assert "not an authorization decision" in r.to_dict()["note"]


@pytest.mark.parametrize("kwargs,reason", [
    ({"amount": "120.00"}, "max_transaction_exceeded"),
    ({"merchant": "shop-9"}, "merchant_not_allowlisted"),
    ({"asset": "BTC"}, "asset_not_allowlisted"),
    ({"action": "transfer_asset"}, "action_not_in_scope"),
    ({"resource": "wallet:abc"}, "resource_not_in_scope"),
    ({"at": "2026-12-01T00:00:00Z"}, "grant_not_active_at_action_time"),
    ({"amount": "90.00"}, "human_approval_required_not_observed"),
])
def test_outside_boundary_names_the_violation(kwargs, reason):
    r = check_action(act(**kwargs), [GRANT])
    assert r.status == OUTSIDE and reason in r.reasons


def test_human_approval_and_daily_limit():
    approved = check_action(act(amount="90.00", human_approval_ref="appr-1"), [GRANT])
    assert approved.status == INSIDE and approved.requires_human_approval and approved.human_approval_observed
    earlier = [act("p1", "70.00", "2026-10-22T08:00:00Z"), act("p2", "60.00", "2026-10-22T09:00:00Z"),
               act("p0", "99.00", "2026-10-21T09:00:00Z")]
    r = check_action(act(amount="30.00"), [GRANT], earlier)
    assert r.status == OUTSIDE and r.reasons == ["daily_limit_exceeded"]


def test_no_grant_is_unknown_not_outside():
    assert check_action(act(), []).status == UNKNOWN
    assert check_action(act(at="not-a-time"), [GRANT]).status == UNKNOWN


def _facts(*events):
    rows = []
    for i, (etype, agent, props) in enumerate(events):
        rows.extend(AgentExecutionProjector().project({
            "messageId": f"r-{i:03d}", "type": etype, "tenantId": T,
            "timestamp": f"2026-10-22T10:00:{i:02d}Z", "properties": {"agentId": agent, **props},
        }).rows)
    return normalize_rows(rows, T)


def test_roles_are_independent_and_never_copied():
    facts = _facts(
        ("agent_objective_created", "orch", {"objectiveId": "o1", "ownerActorId": "person-1"}),
        ("agent_subagent_spawned", "orch", {"parentAgentId": "orch", "childAgentId": "buyer"}),
        ("agent_action_selected", "buyer", {"decisionId": "d1", "objectiveId": "o1", "recommendedBy": "advisor"}),
        ("agent_authorization_granted", "buyer", {"decisionId": "d1", "approverActorId": "person-2"}),
        ("agent_transaction_initiated", "buyer", {"decisionId": "d1", "objectiveId": "o1", "amount": "40"}),
    )
    action = facts[-1]
    roles = decompose(action, facts, influence=observed_influence(facts))
    assert set(roles) == set(ROLES)
    assert roles["execution_actor"]["value"] == "buyer"
    assert roles["decision_actor"]["value"] == "buyer"
    assert roles["instruction_source"]["value"] == "orch"
    assert roles["initiating_actor"] == {**roles["initiating_actor"], "value": "orch", "basis": "derived"}
    assert roles["authorization_actor"]["value"] == "person-2"
    assert roles["authorization_actor"]["basis"] == "declared"
    assert roles["objective_owner"]["value"] == "person-1"
    assert roles["funding_actor"]["epistemic_status"] == "unavailable"
    assert roles["beneficiary_actor"]["value"] is None and roles["beneficiary_actor"]["basis"] == "unknown"
    assert roles["influencing_actor"]["value"] in {"orch", "advisor"}


def test_grant_backed_authorization_and_ambiguity():
    facts = _facts(("agent_transaction_initiated", "agent-1", {"amount": "5"}))
    roles = decompose(facts[0], facts, grants=[GRANT])
    assert roles["authorization_actor"]["value"] == "person-1"
    assert roles["authorization_actor"]["epistemic_status"] == "resolved"
    two = [GRANT, {**GRANT, "delegation_id": "del-2", "grantor_entity_id": "person-3"}]
    assert decompose(facts[0], facts, grants=two)["authorization_actor"]["basis"] == "unknown"
    assert decompose(facts[0], facts)["instruction_source"]["basis"] == "unknown"


def test_influence_edges_and_guardrail():
    facts = _facts(
        ("agent_subagent_spawned", "orch", {"parentAgentId": "orch", "childAgentId": "w"}),
        ("agent_policy_evaluated", "w", {"policyId": "spend", "decision": "deny"}),
    )
    edges = {(e.source, e.relation): e for e in observed_influence(facts)}
    assert edges[("orch", "instructed")].state == "observed"
    assert edges[("policy:spend", "blocked")].target == "w"
    weak = infer_influence("x", "y", {"shared_egress": ["e1"], "shared_tools": ["e2"], "similar_behavior": ["e3"],
                                      "timing_correlation": ["e4"], "overlapping_targets": ["e5"]})
    assert weak.confidence <= CIRCUMSTANTIAL_CAP and weak.implies_control is False
    assert weak.competing_explanations
    with pytest.raises(ValueError):
        InfluenceEdge("x", "y", "influenced", "inferred", ("e",), implies_control=True)
    with pytest.raises(ValueError):
        InfluenceEdge("x", "y", "instructed", "observed", ())
