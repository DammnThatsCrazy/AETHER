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


def _service(repo, fixture):
    facts = list(fixture.facts)

    async def silver(tenant, cursor):
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

    return AgentLineageService(
        repo, silver_reader=silver, authority_loader=authority, binding_loader=bindings, alias_loader=aliases,
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


async def test_export_reads_every_row_past_the_page_budget(repo):
    fixture = S.build_fixture(1000)
    service = _service(repo, fixture)
    await service.reconcile(T)
    rows = await service.export_rows(T, S.LEGIT_HUMAN)
    summary = await service.summary(T, S.LEGIT_HUMAN)
    assert len(rows) == summary["activity"]["agent_count"] > V.MAX_PAGE_SIZE


def test_delegation_rows_map_to_authority_records():
    row = {"delegation_id": "d1", "tenant_id": T, "grantor_entity_id": "h", "grantee_entity_id": "a",
           "scope": {"delegation_allowed": False, "maximum_delegation_depth": 2},
           "starts_at": "2026-01-01T00:00:00Z", "revoked_at": "2026-02-01T00:00:00Z"}
    record = authority_from_delegation(T, row)
    assert record.delegation_allowed is False and record.maximum_delegation_depth == 2
    assert record.revoked_at is not None and record.version == 2 and record.verified
    assert authority_from_delegation("other", row) is None
    assert UNATTRIBUTED == "unattributed"


async def test_the_dsr_plane_erases_the_read_model_and_forces_a_rebuild(fixture):
    from actions.agent_lineage import service as svc
    from actions.agent_lineage.repository import PrincipalBindingRepository
    from governance.consent.erasure_planes import AGENT_LINEAGE_COMPONENT, ErasureSubject, erase_agent_lineage_plane
    from governance.dsr_propagation.models import DSR_COMPONENTS

    assert AGENT_LINEAGE_COMPONENT in DSR_COMPONENTS
    repo = InMemoryLineageRepository()
    service = _service(repo, fixture)
    await service.reconcile(T)
    svc.set_service(service)
    bindings = PrincipalBindingRepository()
    await bindings.insert("alb_dsr", {
        "id": "alb_dsr", "tenant_id": T, "kind": "agent", "principal_entity_id": S.LEGIT_HUMAN,
        "agent_entity_id": "legit-orch", "evidence_class": "TENANT_DECLARED",
    })
    try:
        receipts = await erase_agent_lineage_plane(ErasureSubject(
            tenant_id=T, user_id="u", anonymous_id=None,
            entity_ids=frozenset({S.LEGIT_HUMAN}),
        ))
    finally:
        svc.set_service(None)
    assert receipts[AGENT_LINEAGE_COMPONENT].records_impacted > 500
    assert await bindings.find_by_id("alb_dsr") is None
    assert (await service.summary(T, S.LEGIT_HUMAN))["direct_agents"] is None
    assert T not in service._engines
