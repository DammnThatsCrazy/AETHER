"""Lineage service over both stores: cursors, disclosure, rebuild, erasure, isolation."""
from __future__ import annotations

import base64
import json

import pytest

from actions.agent_lineage import synthetic as S
from actions.agent_lineage._common import UNATTRIBUTED, LineageQueryError
from actions.agent_lineage.repository import InMemoryLineageRepository, PostgresLineageRepository
from actions.agent_lineage.service import AgentLineageService, authority_from_delegation
from identity.profile.agent_lineage import compose_agent_activity
from tests.agent_lineage.conftest import migrated_pool
from shared.agent_lineage import vocabulary as V
from shared.agent_lineage.models import Disclosure, LineageSummary, Page

T = S.TENANT


class _MemorySignals:
    def __init__(self):
        self.rows = {}

    async def list_by_subject(self, tenant_id, kind, subject, limit=100):
        return [r for r in self.rows.values()
                if (r["tenant_id"], r["subject_kind"], r["subject_id"]) == (tenant_id, kind, subject)]

    async def upsert_scoped(self, tenant_id, signal_id, data):
        self.rows[signal_id] = {**data, "tenant_id": tenant_id, "signal_id": signal_id}

    async def delete_scoped(self, tenant_id, signal_id):
        return self.rows.pop(signal_id, None) is not None


def _service(repo, fixture):
    async def silver(tenant, cursor):
        facts = fixture.facts
        start = int(cursor or 0)
        page = [f for f in facts[start:start + 1000]]
        next_cursor = str(start + 1000) if start + 1000 < len(facts) else None
        return [dict(f) for f in page if f["tenant_id"] == tenant], next_cursor

    async def authority(tenant):
        return [a for a in fixture.authorities if a.tenant_id == tenant]

    async def bindings(tenant):
        return [b for b in fixture.bindings if b.tenant_id == tenant]

    async def aliases(tenant):
        return {}

    async def risk(tenant):
        return {}

    async def resources(tenant):
        return set()

    async def adjudications(tenant):
        return {}

    return AgentLineageService(
        repo, silver_reader=silver, authority_loader=authority, binding_loader=bindings, alias_loader=aliases, risk_loader=risk, resource_loader=resources, adjudication_loader=adjudications,
        signal_store=_MemorySignals(),
    )


@pytest.fixture(params=["memory", "postgres"])
async def repo(request):
    if request.param == "memory":
        yield InMemoryLineageRepository()
        return
    async with migrated_pool() as pool:
        yield PostgresLineageRepository(pool)


@pytest.fixture
def fixture():
    return S.build_fixture(1000)


async def test_paging_walks_every_row_exactly_once_and_stays_inside_budgets(repo, fixture):
    service = _service(repo, fixture)
    await service.reconcile(T)
    summary = await service.summary(T, S.LEGIT_HUMAN)
    total = sum(summary[k] for k in (
        "direct_agents", "indirect_agents", "probabilistic_agents", "unresolved_agents"))
    seen, cursor = [], None
    while True:
        page = await service.agents(T, S.LEGIT_HUMAN, cursor=cursor, page_size=97)
        Page(**page)
        assert len(page["items"]) <= 97
        seen.extend(r["agent_entity_id"] for r in page["items"])
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert len(seen) == len(set(seen)) == total


async def test_page_size_is_clamped_to_the_interactive_budget(repo, fixture):
    service = _service(repo, fixture)
    await service.reconcile(T)
    page = await service.agents(T, S.LEGIT_HUMAN, page_size=100_000)
    assert page["page_size"] == V.MAX_PAGE_SIZE and len(page["items"]) <= V.INTERACTIVE_MAX_NODES


async def test_cursor_cannot_be_replayed_against_another_scope(repo, fixture):
    service = _service(repo, fixture)
    await service.reconcile(T)
    page = await service.agents(T, S.LEGIT_HUMAN, page_size=2)
    with pytest.raises(LineageQueryError):
        await service.agents(T, S.MALICIOUS_HUMAN, cursor=page["next_cursor"])
    with pytest.raises(LineageQueryError):
        await service.agents("tenant-other", S.LEGIT_HUMAN, cursor=page["next_cursor"])
    with pytest.raises(LineageQueryError):
        await service.agents(T, S.LEGIT_HUMAN, cursor=page["next_cursor"], filters={"relationship": "direct"})
    forged = base64.urlsafe_b64encode(json.dumps({"v": 1, "s": "x", "k": ["a"]}).encode()).decode()
    with pytest.raises(LineageQueryError):
        await service.agents(T, S.LEGIT_HUMAN, cursor=forged)


async def test_filters_narrow_and_unknown_filters_fail_loudly(repo, fixture):
    service = _service(repo, fixture)
    await service.reconcile(T)
    direct = await service.agents(T, S.LEGIT_HUMAN, filters={"relationship": "direct"})
    assert [r["agent_entity_id"] for r in direct["items"]] == ["legit-orch"]
    crossed = await service.agents(T, S.MALICIOUS_HUMAN, filters={"authority_status": "out_of_scope"}, page_size=5)
    assert crossed["items"] and all(r["authority_resolution_status"] == "out_of_scope" for r in crossed["items"])
    flagged = await service.agents(T, S.MALICIOUS_HUMAN, filters={"risk": "flagged"}, page_size=5)
    assert flagged["items"] and all(r["risk_signal_count"] > 0 for r in flagged["items"])
    with pytest.raises(LineageQueryError):
        await service.agents(T, S.LEGIT_HUMAN, filters={"nope": 1})


async def test_drill_from_summary_to_one_agent_and_back_to_the_principal(repo, fixture):
    service = _service(repo, fixture)
    await service.reconcile(T)
    clusters = await service.clusters(T, S.MALICIOUS_HUMAN, page_size=5)
    cluster = clusters["items"][0]
    assert cluster["bases"] and cluster["member_count"] >= 5
    members = await service.agents(T, S.MALICIOUS_HUMAN, filters={"cluster_id": cluster["cluster_id"]}, page_size=3)
    agent = members["items"][0]["agent_entity_id"]
    detail = await service.agent_detail(T, agent)
    assert detail["node"]["agent_run_sample"] or detail["node"]["agent_run_count"] == 0
    assert detail["node"]["evidence_refs"]
    assert S.MALICIOUS_HUMAN in {row["principal_entity_id"] for row in detail["principals"]}
    root = detail["node"]["root_agent_id"]
    if agent != root:
        assert detail["ancestors"][-1]["agent_entity_id"] == root
    # The cluster page also hands over a usable cursor scope for its members.
    assert cluster["next_cursor"]


async def test_tree_collapses_branches_and_expands_one_level_at_a_time(repo, fixture):
    service = _service(repo, fixture)
    await service.reconcile(T)
    top = await service.tree(T, S.LEGIT_HUMAN)
    assert [n["agent_entity_id"] for n in top["items"]] == ["legit-orch"]
    node = top["items"][0]
    assert node["collapsed"] is True and node["descendant_count"] >= 500
    next_level = await service.tree(T, S.LEGIT_HUMAN, parent="legit-orch", page_size=3)
    assert len(next_level["items"]) == 3 and next_level["next_cursor"]


async def test_descendants_and_counts_agree(repo, fixture):
    service = _service(repo, fixture)
    await service.reconcile(T)
    counts = await service.agent_counts(T, "legit-orch")
    seen, cursor = set(), None
    while True:
        page = await service.descendants(T, "legit-orch", cursor=cursor, page_size=200)
        seen.update(n["agent_entity_id"] for n in page["items"])
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert len(seen) == counts["recursive_descendant_count"]


async def test_unknown_principal_and_agent_are_unknown_not_zero(repo, fixture):
    service = _service(repo, fixture)
    await service.reconcile(T)
    summary = await service.summary(T, "human:nobody")
    LineageSummary(**summary)
    assert summary["direct_agents"] is None and summary["disclosure"]["completeness"] == "unknown"
    counts = await service.agent_counts(T, "nobody")
    assert counts["recursive_descendant_count"] is None
    Disclosure(**counts["disclosure"])


async def test_tenants_are_isolated_on_read(repo, fixture):
    service = _service(repo, fixture)
    await service.reconcile(T)
    assert (await service.agents("tenant-other", S.LEGIT_HUMAN))["items"] == []
    assert (await service.summary("tenant-other", S.LEGIT_HUMAN))["direct_agents"] is None
    assert await repo.node("tenant-other", "legit-orch") is None


async def test_full_rebuild_is_stable_and_logs_real_restatements(repo, fixture):
    service = _service(repo, fixture)
    first = await service.reconcile(T)
    assert first["mode"] == "full"
    before = await service.summary(T, S.MALICIOUS_HUMAN)
    rebuilt = await service.reconcile(T, full=True)
    assert rebuilt["restatements"] == 0
    after = await service.summary(T, S.MALICIOUS_HUMAN)
    assert {k: v for k, v in after.items() if k != "disclosure"} == {
        k: v for k, v in before.items() if k != "disclosure"}

    # A correction: the human's grant is revoked. Every downstream row restates.
    record = fixture.authorities[[a.authority_ref for a in fixture.authorities].index("grant-h1-orch")]
    from dataclasses import replace

    fixture.authorities[fixture.authorities.index(record)] = replace(record, revoked_at=1.0, version=2)
    await service.reconcile(T)
    summary = await service.summary(T, S.MALICIOUS_HUMAN)
    assert summary["revoked_agents"] == summary["activity"]["agent_count"]
    restated = await service.restatements(T, S.MALICIOUS_HUMAN, page_size=5)
    assert restated["items"] and restated["items"][0]["after"]["relationship_status"] == "revoked"
    profile = await compose_agent_activity(_Reader(service), T, S.MALICIOUS_HUMAN)
    assert profile["counts"]["revoked_relationships"] == summary["revoked_agents"]


class _Reader:
    def __init__(self, service):
        self.service = service

    async def summary(self, tenant_id, principal):
        return await self.service.summary_model(tenant_id, principal)


async def test_a_fact_that_disappears_removes_rows_on_rebuild(repo, fixture):
    service = _service(repo, fixture)
    await service.reconcile(T)
    assert await repo.node(T, "impostor-0") is not None
    fixture.facts[:] = [f for f in fixture.facts if f.get("agent_id") != "impostor-0"]
    service._silver_reader = _service(repo, fixture)._silver_reader
    await service.reconcile(T, full=True)
    assert await repo.node(T, "impostor-0") is None
    assert await repo.rows_for_agent(T, "impostor-0") == []


async def test_erasure_removes_a_principal_and_is_idempotent(repo, fixture):
    service = _service(repo, fixture)
    await service.reconcile(T)
    first = await repo.erase_subject(T, {S.LEGIT_HUMAN})
    assert first["rows"] > 500 and first["summaries"] == 1
    assert (await service.summary(T, S.LEGIT_HUMAN))["direct_agents"] is None
    assert (await repo.erase_subject(T, {S.LEGIT_HUMAN}))["rows"] == 0
    # Another principal in the tenant is untouched.
    assert (await service.summary(T, S.MALICIOUS_HUMAN))["direct_agents"] == 1


async def test_profile360_reports_summary_only_with_disclosure(repo, fixture):
    service = _service(repo, fixture)
    await service.reconcile(T)
    section = await compose_agent_activity(_Reader(service), T, S.LEGIT_HUMAN)
    assert section["counts"]["directly_authorized_agents"] == 1
    assert section["counts"]["total_agents"] > 500
    assert section["counts"]["agent_outcomes"] is None
    assert "items" not in section and section["row_list_policy"] == "cursor_paginated_never_unbounded"


async def test_investigation_answers_the_operator_questions_in_bounded_reads(repo, fixture):
    service = _service(repo, fixture)
    await service.reconcile(T)
    view = await service.investigation(T, S.MALICIOUS_HUMAN)
    assert view["linkage"]["verified_links"] and view["linkage"]["inferred_links"]
    assert view["clusters"]["items"]
    assert view["spawn_acceleration"]["burst_at"] is not None
    assert view["common_tools"] and view["wallets"]
    assert view["authority_boundary_crossings"]["items"]
    assert view["verified_external_effects"] > 0
    for page in (view["active_agents"], view["revoked_agents"], view["unresolved_agents"]):
        assert len(page["items"]) <= 25


async def test_export_parts_cover_every_row_once_past_the_page_budget(repo):
    fixture = S.build_fixture(1000)
    service = _service(repo, fixture)
    await service.reconcile(T)
    summary = await service.summary(T, S.LEGIT_HUMAN)
    total = sum(summary[k] for k in ("direct_agents", "indirect_agents", "probabilistic_agents", "unresolved_agents"))
    seen, after, parts = [], None, 0
    while True:
        part = await service.export_part(T, S.LEGIT_HUMAN, after=after, part_rows=150)
        parts += 1
        seen.extend(row["agent_entity_id"] for row in part["rows"])
        assert all("evidence_digest" in row and "confidence" not in row for row in part["rows"])
        after = part["next_after"]
        if part["complete"]:
            break
    assert len(seen) == len(set(seen)) == total > V.MAX_PAGE_SIZE
    assert parts == 1 + (len(seen) - 1) // 150


async def test_export_part_stays_inside_the_artifact_cap():
    import json as _json

    from actions.agent_lineage.service import EXPORT_COLUMNS, EXPORT_PART_ROWS
    from repositories.artifacts import MAX_ARTIFACT_BYTES

    fixture = S.build_fixture(1000)
    service = _service(InMemoryLineageRepository(), fixture)
    await service.reconcile(T)
    part = await service.export_part(T, S.MALICIOUS_HUMAN, part_rows=200)
    per_row = len(_json.dumps(part["rows"])) / len(part["rows"])
    assert per_row * EXPORT_PART_ROWS < MAX_ARTIFACT_BYTES
    assert set(part["rows"][0]) == set(EXPORT_COLUMNS)


def test_only_a_grantors_own_grant_is_verified_authority():
    row = {"delegation_id": "d2", "tenant_id": T, "grantor_entity_id": "victim", "grantee_entity_id": "a"}
    assert authority_from_delegation(T, row).verified is False
    assert authority_from_delegation(T, {**row, "asserted_by_entity_id": "attacker"}).verified is False
    assert authority_from_delegation(T, {**row, "asserted_by_entity_id": "victim"}).verified is True


async def test_owner_registered_by_someone_else_is_only_declared(fixture):
    from actions.agent_lineage.service import _registered_owner_bindings
    from repositories.repos import AgentConfigRepository

    tenant = "tenant-owner-provenance"
    repo = AgentConfigRepository()
    await repo.register("forged", "victim", tenant, "m", asserted_by_entity_id="attacker")
    await repo.register("own", "owner", tenant, "m", asserted_by_entity_id="owner")
    found = {b.agent_entity_id: b.evidence_class for b in await _registered_owner_bindings(tenant)}
    assert found == {"forged": "TENANT_DECLARED", "own": "DETERMINISTIC_BINDING"}


async def test_erasure_scrubs_the_subject_from_records_about_others(repo):
    fixture = S.build_fixture(100)
    service = _service(repo, fixture)
    await service.reconcile(T)
    # conflict-* agents list both competing principals.
    assert (await repo.rows_for_agent(T, "conflict-0"))[0]["competing_principal_ids"]
    await repo.erase_subject(T, {"org:rival"})
    rows = await repo.rows_for_agent(T, "conflict-0")
    assert [r["principal_entity_id"] for r in rows] == ["org:vendor"]
    assert rows[0]["competing_principal_ids"] == ["org:vendor"]
    assert (await repo.node(T, "conflict-0"))["principal_entity_ids"] == ["org:vendor"]


def test_delegation_rows_map_to_authority_records():
    row = {"delegation_id": "d1", "tenant_id": T, "grantor_entity_id": "h", "grantee_entity_id": "a",
           "asserted_by_entity_id": "h",
           "scope": {"delegation_allowed": False, "maximum_delegation_depth": 2},
           "starts_at": "2026-01-01T00:00:00Z", "revoked_at": "2026-02-01T00:00:00Z"}
    record = authority_from_delegation(T, row)
    assert record.delegation_allowed is False and record.maximum_delegation_depth == 2
    assert record.revoked_at is not None and record.version == 2 and record.verified
    assert authority_from_delegation("other", row) is None
    assert UNATTRIBUTED == "unattributed"


async def _erasure_world(fixture, monkeypatch, holds=()):
    from actions.agent_lineage import service as svc
    from repositories.repos import AgentConfigRepository, DelegationRepository
    from shared.storage.lifecycle import StorageLifecycle

    async def active_hold(self, tenant, store, ref):
        return {"hold_id": "h1", "reason": "litigation"} if (store, ref) in holds else None

    monkeypatch.setattr(StorageLifecycle, "active_hold", active_hold)
    repo = InMemoryLineageRepository()
    service = _service(repo, fixture)
    await service.reconcile(T)
    svc.set_service(service)
    suffix = base64.urlsafe_b64encode(repr(holds).encode()).decode()[:12]
    world = {
        "service": service,
        "grant": f"grant-dsr-{suffix}", "other": f"grant-other-{suffix}", "agent": f"owned-{suffix}",
        "delegations": DelegationRepository(), "configs": AgentConfigRepository(),
    }
    await world["delegations"].grant(world["grant"], T, S.LEGIT_HUMAN, f"counterparty-{suffix}", {})
    await world["delegations"].grant(world["other"], T, S.MALICIOUS_HUMAN, "mal-orch", {})
    await world["configs"].register(world["agent"], S.LEGIT_HUMAN, T, "model-x")
    return world


def _subject():
    from governance.consent.erasure_planes import ErasureSubject

    return ErasureSubject(tenant_id=T, user_id="u", entity_ids=frozenset({S.LEGIT_HUMAN}))


async def test_the_dsr_plane_erases_lineage_and_the_inputs_that_would_rebuild_it(fixture, monkeypatch):
    from actions.agent_lineage import service as svc
    from actions.agent_lineage.repository import PrincipalBindingRepository
    from actions.agent_lineage.service import _registered_owner_bindings
    from governance.consent.erasure_planes import AGENT_LINEAGE_COMPONENT, erase_agent_lineage_plane
    from governance.dsr_propagation.models import DSR_COMPONENTS
    from intelligence.risk360.store import RiskSignalRepository

    assert AGENT_LINEAGE_COMPONENT in DSR_COMPONENTS
    world = await _erasure_world(fixture, monkeypatch)
    bindings = PrincipalBindingRepository()
    await bindings.insert("alb_dsr", {
        "id": "alb_dsr", "tenant_id": T, "kind": "agent", "principal_entity_id": S.LEGIT_HUMAN,
        "agent_entity_id": "legit-orch", "evidence_class": "TENANT_DECLARED",
    })
    signal_id = "rsk_fanout_dsr"
    await RiskSignalRepository().upsert_scoped(T, signal_id, {
        "subject_kind": "entity", "subject_id": S.LEGIT_HUMAN, "source": "agent_lineage_fanout.out_of_scope_execution_rate",
    })
    # The delegation store is the real authority source in production; the fixture's
    # loader stands in for it here, so drop what the plane deletes there.
    fixture.authorities[:] = [a for a in fixture.authorities if a.grantor_entity_id != S.LEGIT_HUMAN]
    try:
        receipts = await erase_agent_lineage_plane(_subject())
    finally:
        svc.set_service(None)
    service = world["service"]
    assert receipts[AGENT_LINEAGE_COMPONENT].records_impacted > 500
    assert await bindings.find_by_id("alb_dsr") is None
    assert await world["delegations"].find_by_id(world["grant"]) is None
    assert await world["delegations"].find_by_id(world["other"]) is not None
    assert (await service.summary(T, S.LEGIT_HUMAN))["direct_agents"] is None
    assert await RiskSignalRepository().get_scoped(T, signal_id) is None
    # The registered agent stays, but it can no longer rebuild an owner link.
    config = await world["configs"].find_by_id(world["agent"])
    assert config["owner_entity_id"] is None
    owners = await _registered_owner_bindings(T)
    assert S.LEGIT_HUMAN not in {binding.principal_entity_id for binding in owners}


async def test_a_hold_on_a_counterparty_stops_the_plane_before_anything_changes(fixture, monkeypatch):
    from actions.agent_lineage import service as svc
    from governance.consent.erasure_planes import AGENT_LINEAGE_COMPONENT, erase_agent_lineage_plane

    holds = (("delegations", "counterparty-held"),)
    world = await _erasure_world(fixture, monkeypatch, holds=holds)
    await world["delegations"].grant("grant-held", T, S.LEGIT_HUMAN, holds[0][1], {})
    try:
        receipts = await erase_agent_lineage_plane(_subject())
    finally:
        svc.set_service(None)
    assert receipts[AGENT_LINEAGE_COMPONENT].status == "skipped_legal_hold"
    assert await world["delegations"].find_by_id("grant-held") is not None
    assert (await world["configs"].find_by_id(world["agent"]))["owner_entity_id"] == S.LEGIT_HUMAN
    assert (await world["service"].summary(T, S.LEGIT_HUMAN))["direct_agents"] == 1
    await world["delegations"].delete("grant-held")


async def test_a_reconcile_racing_an_erasure_rebuilds_instead_of_rewriting_the_subject(repo, fixture):
    service = _service(repo, fixture)
    await service.reconcile(T)
    original = service._silver_reader
    raced = []

    async def racing(tenant, cursor):
        page = await original(tenant, cursor)
        if not raced:
            raced.append(True)
            # Another worker erases the subject and its evidence while this pass reads.
            await repo.erase_subject(T, {S.LEGIT_HUMAN})
            fixture.authorities[:] = [a for a in fixture.authorities if a.grantor_entity_id != S.LEGIT_HUMAN]
        return page

    service._silver_reader = racing
    await service.reconcile(T)
    assert raced
    rows = await service.agents(T, S.LEGIT_HUMAN, filters={"relationship": "direct"})
    assert rows["items"] == []


async def test_a_worker_with_an_older_fold_rebuilds_after_another_worker_erases(repo, fixture):
    worker = _service(repo, fixture)
    await worker.reconcile(T)
    other = _service(repo, fixture)
    await other.erase_subject(T, {S.LEGIT_HUMAN})
    fixture.authorities[:] = [a for a in fixture.authorities if a.grantor_entity_id != S.LEGIT_HUMAN]
    stats = await worker.reconcile(T)
    assert stats["mode"] == "full"
    assert (await worker.agents(T, S.LEGIT_HUMAN, filters={"relationship": "direct"}))["items"] == []


async def test_a_fact_budget_truncation_stays_disclosed_until_a_clean_rebuild(fixture, monkeypatch):
    from actions.agent_lineage import service as svc

    monkeypatch.setattr(svc, "MAX_FACTS_PER_RECONCILE", 1000)
    service = _service(InMemoryLineageRepository(), fixture)
    await service.reconcile(T)
    reason = "fact_budget:1000"
    assert reason in (await service.summary(T, S.LEGIT_HUMAN))["disclosure"]["truncation_reasons"]
    # An incremental pass reads nothing past the first page, so the data is still cut.
    monkeypatch.setattr(svc, "MAX_FACTS_PER_RECONCILE", 10_000_000)
    await service.reconcile(T)
    assert reason in (await service.summary(T, S.LEGIT_HUMAN))["disclosure"]["truncation_reasons"]
    await service.reconcile(T, full=True)
    assert reason not in (await service.summary(T, S.LEGIT_HUMAN))["disclosure"]["truncation_reasons"]


async def test_stored_risk_signals_reach_rows_and_a_failed_read_is_disclosed(fixture):
    service = _service(InMemoryLineageRepository(), fixture)
    flags = {"legit-orch": 2}

    async def risk(_tenant):
        return flags

    service._risk_loader = risk
    await service.reconcile(T)
    row = (await service.agents(T, S.LEGIT_HUMAN, filters={"relationship": "direct"}))["items"][0]
    assert row["risk_signal_count"] == 2

    # A cleared signal stops counting on the next pass, without a rebuild.
    flags.clear()
    await service.reconcile(T)
    row = (await service.agents(T, S.LEGIT_HUMAN, filters={"relationship": "direct"}))["items"][0]
    assert row["risk_signal_count"] == 0

    async def broken(_tenant):
        raise RuntimeError("store down")

    service._risk_loader = broken
    await service.reconcile(T)
    disclosure = (await service.summary(T, S.LEGIT_HUMAN))["disclosure"]
    assert "risk_signals_unavailable" in disclosure["truncation_reasons"]

    service._risk_loader = risk
    await service.reconcile(T)
    disclosure = (await service.summary(T, S.LEGIT_HUMAN))["disclosure"]
    assert "risk_signals_unavailable" not in disclosure["truncation_reasons"]


async def test_reconcile_publishes_behavioral_signals_and_withdraws_corrected_ones(fixture):
    from dataclasses import replace

    service = _service(InMemoryLineageRepository(), fixture)
    stats = await service.reconcile(T)
    assert stats["fanout_signals_published"] > 0
    rows = service._signal_store.rows
    assert rows and {r["subject_id"] for r in rows.values()} == {S.MALICIOUS_HUMAN}
    assert all(r["score"] is None for r in rows.values())

    # Remove the depth limit and the revoked branch: behavioral triggers should fall away.
    fixture.authorities[:] = [
        replace(a, maximum_delegation_depth=None, version=2) if a.authority_ref == "grant-h1-orch" else a
        for a in fixture.authorities if a.authority_ref != "grant-revoked-branch"
    ]
    fixture.facts[:] = [f for f in fixture.facts if f.get("policy_decision") != "denied"]
    await service.reconcile(T, full=True)
    assert not [r for r in rows.values() if r["source"].endswith("out_of_scope_execution_rate")]


async def test_signal_publish_failure_reports_unknown_and_keeps_the_projection(fixture):
    class _Broken(_MemorySignals):
        async def list_by_subject(self, *a, **k):
            raise RuntimeError("store down")

    service = _service(InMemoryLineageRepository(), fixture)
    service._signal_store = _Broken()
    stats = await service.reconcile(T)
    assert stats["fanout_signals_published"] is None
    assert (await service.summary(T, S.MALICIOUS_HUMAN))["direct_agents"] == 1


async def test_risk_relationship_kinds_are_populated_from_their_own_evidence(fixture):
    service = _service(InMemoryLineageRepository(), fixture)

    async def resources(_tenant):
        return {"wallet-3"}

    service._resource_loader = resources
    await service.reconcile(T)
    risk = await service.risk(T, S.MALICIOUS_HUMAN)
    kinds = risk["attribution_kinds"]
    assert kinds["delegated_by_risky_actor"] > 0
    assert kinds["interacted_with_risky_resource"] >= 1
    assert kinds["resembles_risky_behavior"] > 0
    assert kinds["confirmed_malicious"] is None
    assert risk["policy"]["calibrated"] is False
    assert 0 <= risk["signals"]["coordinated_execution_score"] <= 1
    assert 0 <= risk["signals"]["identity_churn"] <= 1
    # Likeness and churn are context: they do not appear as triggers.
    assert not {"resembles_risky_behavior", "identity_churn", "coordinated_execution_score"} & set(risk["triggered_signals"])
    # The clean fleet stays clean even with the new signals populated.
    legit = await service.risk(T, S.LEGIT_HUMAN)
    assert legit["assessment_level"] == "no_behavioral_indicators"
    assert legit["signals"]["identity_churn"] > 0.5
    assert legit["attribution_kinds"]["interacted_with_risky_resource"] == 0


def test_a_ref_bound_in_two_namespaces_resolves_by_the_facts_deployment():
    from actions.agent_lineage.service import AgentAliases, _apply_aliases

    aliases = AgentAliases(
        unique={"solo": "agent:solo"},
        scoped={("ns-a", "shared"): "agent:a", ("ns-b", "shared"): "agent:b", ("ns-a", "solo"): "agent:solo"},
        deployment_namespace={"dep-a": "ns-a", "dep-b": "ns-b"},
    )
    assert _apply_aliases({"agent_id": "shared", "deployment_id": "dep-a"}, aliases)["agent_id"] == "agent:a"
    assert _apply_aliases({"agent_id": "shared", "deployment_id": "dep-b"}, aliases)["agent_id"] == "agent:b"
    # With no namespace to go on it stays a source ref rather than merging two agents.
    assert _apply_aliases({"agent_id": "shared", "deployment_id": "dep-x"}, aliases)["agent_id"] == "shared"
    assert _apply_aliases({"agent_id": "solo"}, aliases)["agent_id"] == "agent:solo"
    delegated = _apply_aliases(
        {"agent_id": "x", "delegated_to_ref": "shared", "delegated_to_namespace": "ns-b", "deployment_id": "dep-a"},
        aliases,
    )
    assert delegated["delegated_to_ref"] == "agent:b"


async def test_the_sweep_enqueues_each_tenant_once_an_hour_and_rebuilds_daily(monkeypatch):
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from actions.agent_lineage import jobs as J
    from config import settings as settings_module

    calls = []

    class _Jobs:
        async def enqueue(self, tenant_id, job_type, payload, idempotency_key=None):
            calls.append((tenant_id, job_type, payload["full"], idempotency_key))

    async def tenants():
        return ["t1", "t2"]

    monkeypatch.setattr(settings_module, "settings", SimpleNamespace(
        external_agent_telemetry=SimpleNamespace(registry_enabled=True)))
    at = datetime(2026, 11, 6, J.FULL_REBUILD_HOUR_UTC, tzinfo=timezone.utc)
    assert await J.sweep_once(at, tenants=tenants, jobs=_Jobs()) == 2
    assert all(call[2] is True for call in calls)
    assert calls[0][3] == "agent_lineage:t1:2026110603"
    calls.clear()
    await J.sweep_once(at.replace(hour=4), tenants=tenants, jobs=_Jobs())
    assert all(call[2] is False for call in calls)
    monkeypatch.setattr(settings_module, "settings", SimpleNamespace(
        external_agent_telemetry=SimpleNamespace(registry_enabled=False)))
    assert await J.sweep_once(at, tenants=tenants, jobs=_Jobs()) == 0


async def test_only_a_verdict_makes_activity_confirmed(fixture):
    service = _service(InMemoryLineageRepository(), fixture)
    await service.reconcile(T)
    assert (await service.risk(T, S.MALICIOUS_HUMAN))["segments"]["confirmed_abusive"] is None

    async def verdicts(_tenant):
        return {"mal-1": "confirmed_malicious", "mal-2": "cleared", "unc-0": "confirmed_malicious"}

    service._adjudication_loader = verdicts
    stats = await service.reconcile(T, full=True)
    risk = await service.risk(T, S.MALICIOUS_HUMAN)
    assert risk["segments"]["confirmed_abusive"] == 1
    assert risk["assessment_level"] == "confirmed_activity"
    assert stats["fanout_signals_published"] > 0
    claims = {r["source"]: r["claim_state"] for r in service._signal_store.rows.values()}
    assert claims["agent_lineage_fanout.confirmed_malicious_agents"] == "verified"
    # A verdict on an unlinked agent says nothing about any principal.
    assert (await service.risk(T, S.LEGIT_HUMAN))["segments"]["confirmed_abusive"] is None


async def test_calibration_reports_insufficient_labels_and_recommends_nothing(fixture):
    service = _service(InMemoryLineageRepository(), fixture)

    async def verdicts(_tenant):
        return {"mal-1": "confirmed_malicious", "legit-1": "cleared"}

    service._adjudication_loader = verdicts
    await service.reconcile(T)
    report = await service.calibration(T)
    assert report["positives"] == 1 and report["negatives"] == 1
    assert report["sufficient"] is False and report["recommended_threshold"] is None


def test_calibration_recommends_only_with_enough_labels():
    from intelligence.risk360.fanout_calibration import MIN_LABELS, evaluate

    points = [{"signals": {"authority_failure_rate": 0.3}, "confirmed": True} for _ in range(MIN_LABELS)]
    points += [{"signals": {"authority_failure_rate": 0.02}, "confirmed": False} for _ in range(MIN_LABELS)]
    report = evaluate(points)
    assert report["sufficient"] is True
    assert report["recommended_threshold"] in (0.05, 0.1, 0.2, 0.3)
    assert evaluate(points[:10])["recommended_threshold"] is None


async def test_concurrent_workers_converge_and_an_erasure_stays_erased(repo, fixture):
    import asyncio

    first, second = _service(repo, fixture), _service(repo, fixture)
    await asyncio.gather(first.reconcile(T), second.reconcile(T))
    expected = (await first.summary(T, S.LEGIT_HUMAN))["direct_agents"]
    assert expected == 1 and await repo.node(T, "legit-orch") is not None

    fixture.authorities[:] = [a for a in fixture.authorities if a.grantor_entity_id != S.LEGIT_HUMAN]
    await asyncio.gather(
        first.erase_subject(T, {S.LEGIT_HUMAN}), second.reconcile(T), first.reconcile(T),
    )
    await second.reconcile(T)
    assert (await second.agents(T, S.LEGIT_HUMAN, filters={"relationship": "direct"}))["items"] == []


async def test_a_declared_link_cannot_put_a_confirmed_finding_on_someone():
    from actions.agent_lineage.evidence import PrincipalBinding

    fixture = S.Fixture(tier=1)
    fixture.facts.append({
        "tenant_id": T, "source_event_id": "e1", "source_event_type": "agent_task_started",
        "agent_id": "a1", "occurred_at": "2026-11-06T10:00:00Z",
    })
    fixture.bindings.append(PrincipalBinding(
        tenant_id=T, kind="agent", principal_entity_id="human:innocent", agent_entity_id="a1",
        evidence_class="TENANT_DECLARED",
    ))
    service = _service(InMemoryLineageRepository(), fixture)

    async def verdicts(_tenant):
        return {"a1": "confirmed_malicious"}

    service._adjudication_loader = verdicts
    await service.reconcile(T)
    risk = await service.risk(T, "human:innocent")
    assert risk["segments"]["confirmed_abusive"] == 0
    assert risk["assessment_level"] != "confirmed_activity"
    assert not [r for r in service._signal_store.rows.values() if r["claim_state"] == "verified"]


async def test_the_plane_honours_typed_holds_on_every_store_and_scrubs_asserters(fixture, monkeypatch):
    from actions.agent_lineage import service as svc
    from actions.agent_lineage.repository import AdjudicationRepository
    from governance.consent.erasure_planes import AGENT_LINEAGE_COMPONENT, erase_agent_lineage_plane

    world = await _erasure_world(fixture, monkeypatch, holds=(("agent_lineage_adjudications", "ala_held"),))
    verdicts = AdjudicationRepository()
    await verdicts.insert("ala_held", {
        "id": "ala_held", "tenant_id": T, "agent_entity_id": S.LEGIT_HUMAN, "verdict": "cleared",
    })
    try:
        receipts = await erase_agent_lineage_plane(_subject())
    finally:
        svc.set_service(None)
    assert receipts[AGENT_LINEAGE_COMPONENT].status == "skipped_legal_hold"
    assert await verdicts.find_by_id("ala_held") is not None
    await verdicts.delete("ala_held")

    world = await _erasure_world(fixture, monkeypatch, holds=(("x", "y"),))
    await world["delegations"].grant("g-asserted", T, "human:other", "agent-z", {}, asserted_by_entity_id=S.LEGIT_HUMAN)
    await world["configs"].register("cfg-asserted", "human:other", T, "m", asserted_by_entity_id=S.LEGIT_HUMAN)
    try:
        await erase_agent_lineage_plane(_subject())
    finally:
        svc.set_service(None)
    grant = await world["delegations"].find_by_id("g-asserted")
    config = await world["configs"].find_by_id("cfg-asserted")
    assert grant["asserted_by_entity_id"] is None and grant["grantor_entity_id"] == "human:other"
    assert config["asserted_by_entity_id"] is None and config["owner_entity_id"] == "human:other"
    await world["delegations"].delete("g-asserted")
    await world["configs"].delete("cfg-asserted")


async def test_erasing_an_agent_removes_its_derived_copies_through_the_rebuild(monkeypatch):
    from actions.agent_lineage import service as svc
    from governance.consent.erasure_planes import ErasureSubject, erase_agent_lineage_plane
    from shared.storage.lifecycle import StorageLifecycle

    async def no_hold(self, tenant, store, ref):
        return None

    monkeypatch.setattr(StorageLifecycle, "active_hold", no_hold)
    facts = [
        {"tenant_id": T, "source_event_id": "e1", "source_event_type": "agent_subagent_spawned",
         "agent_id": "erased", "parent_agent_ref": "erased", "child_agent_ref": "kid",
         "occurred_at": "2026-11-06T10:00:00Z", "operator_entity_id": "human:op"},
    ]
    fixture = S.Fixture(tier=1, facts=facts)
    repo = InMemoryLineageRepository()
    service = _service(repo, fixture)
    await service.reconcile(T)
    assert (await repo.node(T, "kid"))["parent_agent_id"] == "erased"
    svc.set_service(service)
    # What the Silver plane removes before this plane runs.
    facts.clear()
    try:
        await erase_agent_lineage_plane(ErasureSubject(tenant_id=T, user_id="u", entity_ids=frozenset({"erased"})))
    finally:
        svc.set_service(None)
    assert await repo.node(T, "kid") is None and await repo.node(T, "erased") is None


def test_silver_erasure_reaches_agent_reference_columns():
    from governance.consent.erasure_planes import SILVER_SUBJECT_COLUMNS

    for column in ("agent_id", "parent_agent_ref", "child_agent_ref", "delegated_to_ref", "operator_entity_id"):
        assert column in SILVER_SUBJECT_COLUMNS

