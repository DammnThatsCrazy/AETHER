"""Fleet hypotheses: graded evidence, competing explanations, reviewer-gated status."""
from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest

from intelligence.fraud_networks.fleet_hypothesis import (
    CIRCUMSTANTIAL_CAP, DELEGATION_CAP, STATUS_CONFIRMED, STATUS_NEEDS_REVIEW,
    STATUS_REJECTED, STATUS_UNCONFIRMED, AgentObservation, FleetHypothesisRepository,
    ReviewError, apply_review, build_fleet_hypothesis, hypothesis_id,
    observations_from_rows,
)

T = "tenant-a"
ROOT = "orch"


def _fleet(n=12, *, shared_host=True, same_tools=True, shared_target=True, burst=True):
    members = [f"w{i:02d}" for i in range(n)]
    obs = {}
    for i, m in enumerate(members):
        obs[m] = AgentObservation(
            agent_ref=m,
            spawned_at=f"2026-10-22T10:00:{i:02d}Z" if burst else f"2026-10-22T1{i % 9}:00:00Z",
            tool_sequence=["wallet_scan", "swap_quote"] if same_tools else [f"tool{i}"],
            endpoint_hosts={"rpc.shared.example"} if shared_host else {f"h{i}.example"},
            target_refs={"wallet:0xabc"} if shared_target else {f"wallet:0x{i}"},
        )
    return members, obs


def _build(members, obs, **kw):
    return build_fleet_hypothesis(
        tenant_id=T, root_agent_ref=ROOT, member_refs=[ROOT, *members], observations=obs, **kw
    )


def test_small_fleet_is_not_a_hypothesis():
    members, obs = _fleet(1)
    assert _build(members, obs) is None


def test_circumstantial_evidence_never_exceeds_cap_and_is_never_confirmed():
    members, obs = _fleet(20)
    h = _build(members, obs)
    kinds = {e["type"] for e in h["evidence"]}
    assert {"spawn_burst", "shared_endpoint", "identical_tool_sequence", "overlapping_targets"} <= kinds
    assert h["confidence"] <= CIRCUMSTANTIAL_CAP
    assert h["status"] in (STATUS_NEEDS_REVIEW, STATUS_UNCONFIRMED)
    assert h["person_link"] is None
    ids = {c["id"] for c in h["competing_explanations"]}
    assert {"shared_third_party_infrastructure", "same_vendor_template",
            "no_human_principal_observed"} <= ids
    assert all(e["basis"] in ("observed", "inferred") for e in h["evidence"])


def test_shared_infrastructure_alone_stays_weak():
    members, obs = _fleet(10, same_tools=False, shared_target=False, burst=False)
    h = _build(members, obs)
    assert h["confidence"] < 0.5
    assert {e["type"] for e in h["evidence"]} == {"observed_spawn_tree", "shared_endpoint"}


def test_principal_delegation_links_a_person_but_keeps_victim_explanation():
    members, obs = _fleet(12)
    h = _build(members, obs, principal_entity_ids=["person-1"])
    assert h["person_link"]["principal_entity_ids"] == ["person-1"]
    assert h["person_link"]["claim"] == "authority_granted"
    assert CIRCUMSTANTIAL_CAP < h["confidence"] <= DELEGATION_CAP
    assert "principal_is_not_the_actor" in {c["id"] for c in h["competing_explanations"]}
    assert h["status"] == STATUS_NEEDS_REVIEW


def test_small_benign_fleet_is_kept_as_context_not_queued():
    members, obs = _fleet(2, same_tools=False, shared_host=False, shared_target=False)
    h = _build(members, obs, principal_entity_ids=["person-1"])
    assert h["status"] == STATUS_UNCONFIRMED and h["priority"] == "low"
    flagged = _build(members, obs, principal_entity_ids=["person-1"], risk_flagged_refs={"w00"})
    assert flagged["status"] == STATUS_NEEDS_REVIEW and flagged["priority"] == "high"


def test_risk_flag_raises_priority_not_confidence():
    members, obs = _fleet(12)
    plain = _build(members, obs)
    flagged = _build(members, obs, risk_flagged_refs={"w03", "unrelated"})
    assert flagged["confidence"] == plain["confidence"]
    assert flagged["priority"] == "high" and plain["priority"] == "normal"
    assert flagged["risk_context"]["flagged_agent_refs"] == ["w03"]


def test_review_is_the_only_path_to_confirmed_and_needs_a_person_and_reason():
    members, obs = _fleet(12)
    no_person = _build(members, obs)
    with pytest.raises(ReviewError):
        apply_review(no_person, reviewer_id="analyst", decision="confirm", reason="looks right to me")
    with pytest.raises(ReviewError):
        apply_review(no_person, reviewer_id="analyst", decision="reject", reason="short")
    with pytest.raises(ReviewError):
        apply_review(no_person, reviewer_id="", decision="reject", reason="not enough evidence here")
    rejected = apply_review(
        no_person, reviewer_id="analyst", decision="reject", reason="shared RPC provider only"
    )
    assert rejected["status"] == STATUS_REJECTED
    assert rejected["review_history"][0]["previous_status"] == no_person["status"]

    with_person = _build(members, obs, principal_entity_ids=["person-1"])
    confirmed = apply_review(
        with_person, reviewer_id="analyst", decision="confirm", reason="delegation plus swaps match"
    )
    assert confirmed["status"] == STATUS_CONFIRMED
    assert confirmed["confidence"] == with_person["confidence"], "review must not rewrite evidence"


def test_observations_fold_rows_tenant_scoped():
    rows = [
        {"tenant_id": T, "event_name": "agent_subagent_spawned", "agent_id": ROOT,
         "child_agent_ref": "w00", "occurred_at": "2026-10-22T10:00:00Z", "source_event_id": "s1"},
        {"tenant_id": T, "event_name": "agent_tool_invocation_observed", "agent_id": "w00",
         "tool_name": "wallet_scan", "server_url": "https://RPC.shared.example/v1",
         "object_type": "wallet", "object_id": "0xabc", "occurred_at": "2026-10-22T10:01:00Z"},
        {"tenant_id": "other", "event_name": "agent_tool_invocation_observed", "agent_id": "w00",
         "tool_name": "leak", "occurred_at": "2026-10-22T10:02:00Z"},
    ]
    obs = observations_from_rows(rows, T, ["w00"])["w00"]
    assert obs.spawned_at == "2026-10-22T10:00:00Z"
    assert obs.tool_sequence == ["wallet_scan"]
    assert obs.endpoint_hosts == {"rpc.shared.example"}
    assert obs.target_refs == {"wallet:0xabc"}


@pytest.mark.asyncio
async def test_repository_is_tenant_scoped_and_keeps_reviewed_status():
    repo = FleetHypothesisRepository()
    tenant = "tenant-repo-" + "x"
    members, obs = _fleet(6)
    h = build_fleet_hypothesis(
        tenant_id=tenant, root_agent_ref=ROOT, member_refs=[ROOT, *members], observations=obs,
        principal_entity_ids=["person-1"],
    )
    saved = await repo.save(h)
    reviewed = apply_review(saved, reviewer_id="a", decision="confirm", reason="verified with the owner")
    await repo.insert_tenant_scoped(reviewed["hypothesis_id"], reviewed, tenant)
    resaved = await repo.save(h)  # a rebuild must not silently undo the review
    assert resaved["status"] == STATUS_CONFIRMED
    assert len(resaved["review_history"]) == 1
    assert await repo.get("other-tenant", h["hypothesis_id"]) is None
    assert hypothesis_id(tenant, ROOT) == h["hypothesis_id"]
