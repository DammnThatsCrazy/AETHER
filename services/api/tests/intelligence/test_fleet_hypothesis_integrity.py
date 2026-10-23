"""Fleet hypothesis integrity: review validity, atomic writes, evidence scope, truncation."""
from __future__ import annotations

import asyncio

import pytest

from actions.agent.lineage import (
    ACTIVITY_FACT_LIMIT, SPAWN_FACT_LIMIT, build_lineage_tree, edge_event_refs,
    read_lineage_facts, source_is_truncated,
)
from intelligence.fraud_networks import fleet_routes
from intelligence.fraud_networks.fleet_hypothesis import (
    STATUS_CONFIRMED, STATUS_NEEDS_REVIEW, AgentObservation, FleetHypothesisRepository,
    build_fleet_hypothesis, evidence_fingerprint,
)
from repositories.repos import reset_in_memory_stores

T = "tenant-integrity"
ROOT = "orch"


@pytest.fixture(autouse=True)
def _clean():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


def _hyp(*, principals=None, root=ROOT, n=6):
    members = [f"w{i:02d}" for i in range(n)]
    obs = {
        m: AgentObservation(
            agent_ref=m, spawned_at=f"2026-10-22T10:00:{i:02d}Z",
            tool_sequence=["scan", "quote"], endpoint_hosts={"rpc.shared.example"},
        )
        for i, m in enumerate(members)
    }
    return build_fleet_hypothesis(
        tenant_id=T, root_agent_ref=root, member_refs=[root, *members], observations=obs,
        principal_entity_ids=principals,
    )


async def _confirm(repo, hypothesis, reviewer="analyst-1"):
    return await repo.review(
        T, hypothesis["hypothesis_id"], reviewer_id=reviewer, decision="confirm",
        reason="delegation matches the case file",
    )


# ── A review is valid only for the evidence it was made on ───────────────────

@pytest.mark.asyncio
async def test_rebuild_with_the_same_evidence_keeps_the_review():
    repo = FleetHypothesisRepository()
    await repo.save(_hyp(principals=["person-a"]))
    await _confirm(repo, _hyp(principals=["person-a"]))
    again = await repo.save(_hyp(principals=["person-a"]))
    assert again["status"] == STATUS_CONFIRMED
    assert [h["decision"] for h in again["review_history"]] == ["confirm"]


@pytest.mark.asyncio
async def test_changed_principal_supersedes_the_review_instead_of_inheriting_it():
    repo = FleetHypothesisRepository()
    await repo.save(_hyp(principals=["person-a"]))
    await _confirm(repo, _hyp(principals=["person-a"]))

    # Principal A's delegation lapsed and B now holds it: the reviewer saw A only.
    rebuilt = await repo.save(_hyp(principals=["person-b"]))
    assert rebuilt["status"] != STATUS_CONFIRMED
    assert rebuilt["status"] == STATUS_NEEDS_REVIEW
    assert rebuilt["person_link"]["principal_entity_ids"] == ["person-b"]
    assert "reviewed_fingerprint" not in rebuilt
    assert [h["decision"] for h in rebuilt["review_history"]] == ["confirm", "superseded"]
    assert rebuilt["review_history"][-1]["previous_status"] == STATUS_CONFIRMED

    # Losing the principal altogether must not leave a confirmed record with no person.
    lost = await repo.save(_hyp(principals=None))
    assert lost["status"] != STATUS_CONFIRMED and lost["person_link"] is None


def test_fingerprint_ignores_fleet_membership_drift_but_not_evidence_or_principals():
    base = _hyp(principals=["person-a"], n=6)
    assert evidence_fingerprint(base) == evidence_fingerprint(_hyp(principals=["person-a"], n=9))
    assert evidence_fingerprint(base) != evidence_fingerprint(_hyp(principals=["person-b"], n=6))
    assert evidence_fingerprint(base) != evidence_fingerprint(_hyp(principals=None, n=6))


# ── created_at is the hypothesis's, not the last write's ─────────────────────

@pytest.mark.asyncio
async def test_created_at_survives_rebuilds_and_reviews():
    repo = FleetHypothesisRepository()
    first = await repo.save(_hyp(principals=["person-a"]))
    created = first["created_at"]
    await asyncio.sleep(0.01)
    rebuilt = await repo.save(_hyp(principals=["person-a"]))
    reviewed = await _confirm(repo, rebuilt)
    stored = await repo.get(T, first["hypothesis_id"])
    assert rebuilt["created_at"] == reviewed["created_at"] == stored["created_at"] == created
    assert stored["updated_at"] > created


# ── Concurrent writers cannot overwrite one another ──────────────────────────

@pytest.mark.asyncio
async def test_concurrent_reviews_are_both_kept_in_commit_order(monkeypatch):
    repo = FleetHypothesisRepository()
    h = await repo.save(_hyp(principals=["person-a"]))

    real_get = repo.get

    async def slow_get(tenant_id, hid):
        row = await real_get(tenant_id, hid)
        await asyncio.sleep(0)  # let the other reviewer read the same revision
        return row

    monkeypatch.setattr(repo, "get", slow_get)
    first, second = await asyncio.gather(
        repo.review(T, h["hypothesis_id"], reviewer_id="r1", decision="confirm",
                    reason="first reviewer, evidence checked"),
        repo.review(T, h["hypothesis_id"], reviewer_id="r2", decision="reject",
                    reason="second reviewer, disagrees strongly"),
    )
    stored = await real_get(T, h["hypothesis_id"])
    assert {e["reviewer_id"] for e in stored["review_history"]} == {"r1", "r2"}
    assert len(stored["review_history"]) == 2, "neither review may erase the other"
    # The later commit saw the earlier one's status, so the trail is coherent.
    assert stored["review_history"][1]["previous_status"] == (
        STATUS_CONFIRMED if stored["review_history"][0]["decision"] == "confirm"
        else "rejected_by_reviewer"
    )
    assert stored["revision"] == h["revision"] + 2
    assert first is not None and second is not None


@pytest.mark.asyncio
async def test_a_rebuild_racing_a_review_does_not_erase_it(monkeypatch):
    repo = FleetHypothesisRepository()
    h = await repo.save(_hyp(principals=["person-a"]))
    real_get = repo.get

    async def slow_get(tenant_id, hid):
        row = await real_get(tenant_id, hid)
        await asyncio.sleep(0)
        return row

    monkeypatch.setattr(repo, "get", slow_get)
    await asyncio.gather(
        repo.save(_hyp(principals=["person-a"])),
        repo.review(T, h["hypothesis_id"], reviewer_id="r1", decision="confirm",
                    reason="reviewer decision during a rebuild"),
    )
    stored = await real_get(T, h["hypothesis_id"])
    assert stored["status"] == STATUS_CONFIRMED
    assert [e["decision"] for e in stored["review_history"]] == ["confirm"]


@pytest.mark.asyncio
async def test_first_write_race_never_replaces_the_winner():
    repo = FleetHypothesisRepository()
    h = _hyp(principals=["person-a"])
    first, second = await asyncio.gather(repo.save(dict(h)), repo.save(dict(h)))
    stored = await repo.get(T, h["hypothesis_id"])
    assert stored["revision"] == 2 and {first["revision"], second["revision"]} == {1, 2}
    assert await repo.insert_if_absent(h["hypothesis_id"], dict(h), T) is False


@pytest.mark.asyncio
async def test_replace_if_matches_refuses_stale_and_foreign_writes():
    repo = FleetHypothesisRepository()
    h = await repo.save(_hyp(principals=["person-a"]))
    stale = dict(h, revision=99, status="x")
    assert await repo.replace_if_matches(h["hypothesis_id"], stale, T, {"revision": 0}) is False
    assert (await repo.get(T, h["hypothesis_id"]))["status"] != "x"
    foreign = dict(h, tenant_id="other")
    assert await repo.replace_if_matches(h["hypothesis_id"], foreign, "other", {"revision": 1}) is False
    assert await repo.review(T, "missing:id", reviewer_id="r", decision="confirm",
                             reason="no such hypothesis here") is None


# ── Only canonical humans become the person link ─────────────────────────────

@pytest.mark.asyncio
async def test_only_active_canonical_humans_are_principals():
    from identity.identity.models import EntityType
    from identity.identity.repository import IdentityResolutionRepository

    ids = IdentityResolutionRepository()
    await ids.create_subject(T, "person-1")
    await ids.create_subject(T, "agent-9", EntityType.DEVICE)
    await ids.create_subject(T, "person-old")
    await ids.create_subject(T, "person-new")
    await ids.mark_subject_merged_by_canonical_id(T, "person-old", "person-new")
    await ids.create_subject(T, "human-merged-into-device")
    await ids.mark_subject_merged_by_canonical_id(T, "human-merged-into-device", "agent-9")
    await ids.create_subject("other-tenant", "person-elsewhere")

    humans = await fleet_routes._human_principals(
        T,
        {"person-1", "agent-9", "org-acme", "person-old", "person-new", "person-elsewhere",
         "never-seen", "human-merged-into-device"},
    )
    # Unresolved, non-human and other-tenant ids are not people. A merged-away id
    # is the person it merged into, recorded once under the surviving id.
    assert humans == ["person-1", "person-new"]


@pytest.mark.asyncio
async def test_principal_lookup_failure_excludes_rather_than_guesses(monkeypatch):
    from identity.identity.repository import IdentityResolutionRepository

    async def boom(self, tenant_id, canonical_entity_id, max_hops=10):
        raise RuntimeError("identity store down")

    monkeypatch.setattr(IdentityResolutionRepository, "resolve_surviving_canonical_entity_id", boom)
    assert await fleet_routes._human_principals(T, {"person-1"}) == []


# ── Evidence references come from the traversed lineage ──────────────────────

def _spawn(parent, child, event_id, at, root=None):
    return {
        "tenant_id": T, "source_event_type": "agent_subagent_spawned",
        "parent_agent_ref": parent, "child_agent_ref": child, "agent_id": parent,
        "source_event_id": event_id, "occurred_at": at, "root_agent_ref": root,
    }


def test_evidence_refs_cite_only_edges_inside_the_selected_tree():
    rows = [
        # Two fleets, neither row sets root_agent_ref.
        _spawn("orch", "a1", "evt-orch-1", "2026-10-22T10:00:01Z"),
        _spawn("a1", "a2", "evt-orch-2", "2026-10-22T10:00:02Z"),
        _spawn("other", "b1", "evt-other-1", "2026-10-22T10:00:03Z"),
        _spawn("other", "b2", "evt-other-2", "2026-10-22T10:00:04Z"),
    ]
    tree = build_lineage_tree(tenant_id=T, root_agent_ref="orch", spawn_rows=rows)["tree"]
    assert sorted(edge_event_refs(tree)) == ["evt-orch-1", "evt-orch-2"]
    assert edge_event_refs(tree, limit=1) and len(edge_event_refs(tree, limit=1)) == 1


# ── Bounded reads say when they were cut ─────────────────────────────────────

class _Analytics:
    def __init__(self, spawn_rows, activity_per_agent=0):
        self._spawn = spawn_rows
        self._activity = activity_per_agent
        self.limits = []

    async def query_silver(self, table, filters, limit=100):
        self.limits.append(limit)
        if "source_event_type" in filters:
            return list(self._spawn[:limit])
        return [
            {"tenant_id": T, "agent_id": filters["agent_id"], "occurred_at": f"2026-10-22T11:{i // 60:02d}:{i % 60:02d}Z",
             "run_id": f"r{i}"}
            for i in range(min(self._activity, limit))
        ]


@pytest.mark.asyncio
async def test_spawn_fact_truncation_is_reported_not_presented_as_empty():
    # Newest-first: the requested root's edges are older than 1,000 unrelated ones.
    noise = [_spawn(f"n{i}", f"c{i}", f"evt-n{i}", "2026-10-22T12:00:00Z") for i in range(SPAWN_FACT_LIMIT)]
    old_root = [_spawn("orch", "a1", "evt-old", "2026-10-01T00:00:00Z")]
    facts = await read_lineage_facts(
        _Analytics(noise + old_root), tenant_id=T, root_agent_ref="orch"
    )
    shape = facts["shape"]
    assert shape["totals"]["agent_count"] == 1  # the edge was evicted by the cap
    assert shape["source_truncation"]["spawn_facts"] is True
    assert source_is_truncated(shape)


@pytest.mark.asyncio
async def test_activity_truncation_names_the_agents_whose_rollup_is_partial():
    rows = [_spawn("orch", "a1", "evt-1", "2026-10-22T10:00:00Z")]
    facts = await read_lineage_facts(
        _Analytics(rows, activity_per_agent=ACTIVITY_FACT_LIMIT + 50),
        tenant_id=T, root_agent_ref="orch",
    )
    cut = facts["shape"]["source_truncation"]
    assert cut["spawn_facts"] is False
    assert set(cut["activity_truncated_agents"]) == {"orch", "a1"}
    assert facts["shape"]["totals"]["event_count"] == 2 * ACTIVITY_FACT_LIMIT
    assert source_is_truncated(facts["shape"])


@pytest.mark.asyncio
async def test_complete_reads_are_not_marked_truncated():
    rows = [_spawn("orch", "a1", "evt-1", "2026-10-22T10:00:00Z")]
    facts = await read_lineage_facts(
        _Analytics(rows, activity_per_agent=3), tenant_id=T, root_agent_ref="orch"
    )
    assert not source_is_truncated(facts["shape"])
    assert facts["shape"]["source_truncation"]["activity_truncated_agents"] == []
