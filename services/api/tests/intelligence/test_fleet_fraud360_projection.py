"""Fleet hypotheses projected into Fraud360: canonical subject, conservative states."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from intelligence.fraud360.contracts import EpistemicStatus, FraudHypothesisState
from intelligence.fraud360.store import FraudHypothesisRepository
from intelligence.fraud_networks.fleet_fraud360 import (
    fraud360_hypothesis_id, project_fleet_hypothesis,
)
from intelligence.fraud_networks.fleet_hypothesis import (
    AgentObservation, apply_review, build_fleet_hypothesis,
)

pytestmark = pytest.mark.asyncio

ROOT = "orch"


class _Reader:
    def __init__(self, tenant, canonical_ids=("agent-entity-1",), truncated=False):
        self.rows = [
            {"tenant_id": tenant, "agent_id": ROOT, "canonical_agent_entity_id": c}
            for c in canonical_ids
        ]
        self.truncated = truncated

    async def actor_identity(self, tenant_id, agent_id):
        return SimpleNamespace(rows=self.rows, truncated=self.truncated, scope_mismatch=False)


def _fleet(tenant, *, n=8, principal=True):
    members = [f"w{i}" for i in range(n)]
    obs = {
        m: AgentObservation(
            agent_ref=m, spawned_at=f"2026-10-22T10:00:{i:02d}Z", tool_sequence=["scan"],
            endpoint_hosts={"rpc.shared.example"}, target_refs={"wallet:0xabc"},
        )
        for i, m in enumerate(members)
    }
    return build_fleet_hypothesis(
        tenant_id=tenant, root_agent_ref=ROOT, member_refs=[ROOT, *members], observations=obs,
        principal_entity_ids=["person-1"] if principal else None,
    )


async def test_projects_onto_the_canonical_agent_not_the_source_ref():
    tenant = "t-proj-1"
    fleet = _fleet(tenant)
    out = await project_fleet_hypothesis(fleet, agent_identity_reader=_Reader(tenant))
    assert out["status"] == "projected" and out["state"] == "under_evaluation"
    stored = await FraudHypothesisRepository().get(tenant, fraud360_hypothesis_id(tenant, ROOT))
    assert stored.subject_kind == "agent" and stored.subject_id == "agent-entity-1"
    assert stored.claim_state is EpistemicStatus.ATTRIBUTED
    assert stored.matched_pattern_ids == ["agent_abuse"]
    assert {r.type for r in stored.evidence_refs} == {"relationship", "event"}
    assert all(r.uri.startswith("store://fleet_hypotheses/") for r in stored.evidence_refs)


async def test_no_principal_means_inferred_claim():
    tenant = "t-proj-2"
    await project_fleet_hypothesis(_fleet(tenant, principal=False), agent_identity_reader=_Reader(tenant))
    stored = await FraudHypothesisRepository().get(tenant, fraud360_hypothesis_id(tenant, ROOT))
    assert stored.claim_state is EpistemicStatus.INFERRED


@pytest.mark.parametrize("reader_kwargs", [
    {"canonical_ids": ()},
    {"canonical_ids": ("a", "b")},
    {"truncated": True},
])
async def test_unresolved_or_ambiguous_identity_writes_nothing(reader_kwargs):
    tenant = "t-proj-3"
    out = await project_fleet_hypothesis(
        _fleet(tenant), agent_identity_reader=_Reader(tenant, **reader_kwargs)
    )
    assert out["status"] == "unresolved_agent_identity"
    assert await FraudHypothesisRepository().get(tenant, fraud360_hypothesis_id(tenant, ROOT)) is None


async def test_reviewer_confirm_reaches_investigating_never_confirmed():
    tenant = "t-proj-4"
    reader = _Reader(tenant)
    fleet = _fleet(tenant)
    await project_fleet_hypothesis(fleet, agent_identity_reader=reader)
    reviewed = apply_review(
        fleet, reviewer_id="analyst", decision="confirm", reason="delegation and targets match",
    )
    out = await project_fleet_hypothesis(reviewed, agent_identity_reader=reader)
    assert out["state"] == "investigating"
    stored = await FraudHypothesisRepository().get(tenant, fraud360_hypothesis_id(tenant, ROOT))
    assert stored.state is FraudHypothesisState.INVESTIGATING
    assert stored.state is not FraudHypothesisState.CONFIRMED


async def test_reviewer_reject_is_grounded_in_the_review_record():
    tenant = "t-proj-5"
    reader = _Reader(tenant)
    fleet = _fleet(tenant, n=2, principal=False)  # candidate: needs a step through evaluation
    assert fleet["status"] == "unconfirmed"
    await project_fleet_hypothesis(fleet, agent_identity_reader=reader)
    rejected = apply_review(
        fleet, reviewer_id="analyst", decision="reject", reason="shared RPC provider only",
    )
    out = await project_fleet_hypothesis(rejected, agent_identity_reader=reader)
    assert out["status"] == "projected" and out["state"] == "rejected"


async def test_analyst_moved_record_is_left_alone():
    tenant = "t-proj-6"
    reader = _Reader(tenant)
    fleet = _fleet(tenant)
    await project_fleet_hypothesis(fleet, agent_identity_reader=reader)
    repo = FraudHypothesisRepository()
    hid = fraud360_hypothesis_id(tenant, ROOT)
    await repo.update_state(tenant, hid, FraudHypothesisState.SUPPORTED)
    await repo.update_state(tenant, hid, FraudHypothesisState.INCONCLUSIVE)
    reviewed = apply_review(fleet, reviewer_id="a", decision="confirm", reason="verified with owner")
    out = await project_fleet_hypothesis(reviewed, agent_identity_reader=reader)
    assert out["status"] == "state_diverged" and out["state"] == "inconclusive"
    assert (await repo.get(tenant, hid)).state is FraudHypothesisState.INCONCLUSIVE


async def test_projection_is_idempotent():
    tenant = "t-proj-7"
    reader = _Reader(tenant)
    fleet = _fleet(tenant)
    a = await project_fleet_hypothesis(fleet, agent_identity_reader=reader)
    b = await project_fleet_hypothesis(fleet, agent_identity_reader=reader)
    assert a == b
    assert len(await FraudHypothesisRepository().list(tenant)) == 1
