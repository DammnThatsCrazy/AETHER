"""Population360 provider tests (population360 P3.4).

Pins the population360 provider contract (blueprint test surface):

* valid ``ProjectionResult`` with snapshots/deltas/overlap/transitions/composition
  over canonical population truth — never a competing store;
* ``unknown`` subject, ``empty`` cohort, ``missing`` snapshot source and a
  ``not_applicable`` lens stay distinct typed states — never ``0``/``false``;
* a definition with no membership observation renders ``unknown``, never a
  fabricated ``0`` member count;
* missing-dependency honest degradation (never raises), tenant isolation
  (fail-closed), registration gates (success / duplicate / version-mismatch /
  unknown id), read-only graph policy, no auto-register at import;
* the demographic lens is served when a caller names it via ``lensIds`` and
  degrades honestly while ``profile360`` is ``in_flight``;
* the default repository reader is tenant-scoped over real registry rows.
"""

from __future__ import annotations

import pytest

from repositories.repos import reset_in_memory_stores

from shared.intelligence_projections.contracts import (
    ProjectionRequest,
    ProjectionSubject,
)
from shared.intelligence_projections.errors import (
    ContractVersionIncompatible,
    DuplicateProjection,
    ProjectionNotFound,
)
from shared.intelligence_projections.registry import ProviderRegistry

from services.population.models import MembershipBasis, PopulationType
from services.population.registry import membership_repo, population_repo
from services.population360.demographics import DemographicLens, HumanProfileFact
from services.population360.provider import (
    OUTPUT_SECTIONS,
    Population360Provider,
    PopulationRepositoryReader,
    SubjectView,
    register_provider,
    # posture model (canned views are built from these)
    EntityPosture,
    MembershipRow,
    PopulationPosture,
    SiblingCandidate,
)

TENANT = "tenant_pop360_provider"
OTHER_TENANT = "tenant_pop360_foreign"

# Stable ISO timestamps (same shape so lexicographic ordering == chronological).
T_CREATE = "2026-07-01T00:00:00+00:00"
T_V1 = "2026-07-01T00:00:00+00:00"
T_MEMBER = "2026-07-02T00:00:00+00:00"
T_V2 = "2026-07-10T00:00:00+00:00"
T_SNAP1 = "2026-07-11T00:00:00+00:00"
T_SNAP2 = "2026-07-20T00:00:00+00:00"
T_LEAVE = "2026-07-21T00:00:00+00:00"


# ── Canned view builders ─────────────────────────────────────────────────────


def _member(pid: str, eid: str, *, entity_type: str = "user",
            basis: str = "rule", confidence: float = 1.0,
            state: str = "active") -> MembershipRow:
    return MembershipRow(
        population_id=pid,
        entity_id=eid,
        entity_type=entity_type,
        basis=basis,
        confidence=confidence,
        reason="",
        membership_state=state,
        definition_version="1",
        source_tag="",
        joined_at=T_MEMBER,
        left_at=T_LEAVE if state == "left" else "",
        leave_reason="churn" if state == "left" else "",
    )


def _def_version(pop: str, version: str, *, at: str, reason: str,
                 supersedes: str | None) -> dict:
    return {
        "population_id": pop,
        "definition_version": version,
        "created_at": at,
        "reason": reason,
        "supersedes_version": supersedes,
        "created_by": "population_api",
        "definition": {},
        "definition_hash": "abc",
    }


def _snapshot(pop: str, *, at: str, count: int, version: str = "2") -> dict:
    return {
        "population_id": pop,
        "population_name": "VIPs",
        "population_type": "segment",
        "definition_version": version,
        "member_count": count,
        "tenant_id": TENANT,
        "snapshot_at": at,
    }


def _population_posture(
    *,
    pid: str = "pop-vips",
    members: tuple[MembershipRow, ...] = (),
    snapshots: tuple[dict, ...] = (),
    transitions: tuple[dict, ...] = (),
    siblings: tuple[SiblingCandidate, ...] = (),
    updated_at: str = T_SNAP2,
) -> PopulationPosture:
    active = [m for m in members if m.membership_state == "active"]
    return PopulationPosture(
        population_id=pid,
        name="VIPs",
        population_type="segment",
        status="active",
        definition_version="2",
        consent_purpose="analytics",
        created_at=T_CREATE,
        updated_at=updated_at,
        active_member_count=len(active),
        members_sample=members,
        members_truncated=False,
        snapshots=snapshots,
        definition_transitions=transitions,
        siblings=siblings,
        siblings_truncated=False,
    )


def _entity_row(
    *,
    pop: str, eid: str, state: str = "active", basis: str = "rule",
    confidence: float = 1.0, pop_type: str = "segment",
) -> dict:
    return {
        "id": f"{pop}:{eid}",
        "population_id": pop,
        "entity_id": eid,
        "entity_type": "user",
        "basis": basis,
        "confidence": confidence,
        "reason": "",
        "tenant_id": TENANT,
        "membership_state": state,
        "status": state,
        "definition_version": "1",
        "joined_at": T_MEMBER,
        "left_at": T_LEAVE if state == "left" else "",
        "leave_reason": "churn" if state == "left" else "",
        "population_name": "VIPs",
        "population_type": pop_type,
        "population_status": "active",
    }


class _FakePopulationReader:
    """Strictly tenant-scoped canned reader over prebuilt SubjectViews."""

    def __init__(self, views: dict[tuple[str, str], SubjectView],
                 *, tenant: str = TENANT) -> None:
        self._views = views
        self._tenant = tenant
        self.calls: list[tuple[str, str, str]] = []

    async def view(self, *, tenant_id: str, subject_kind: str,
                   subject_id: str) -> SubjectView:
        self.calls.append((tenant_id, subject_kind, subject_id))
        if tenant_id != self._tenant:
            raise KeyError("tenant isolated")
        missing = SubjectView(
            kind=subject_kind, id=subject_id, posture=None,
            missing_reason="no population-plane observation",
        )
        return self._views.get((subject_kind, subject_id), missing)


class _FakeProfileFactsReader:
    """Canonical-profile-fact seam feeding the demographic lens."""

    def __init__(self, facts: dict[str, HumanProfileFact]) -> None:
        self._facts = facts

    async def facts_for(self, *, tenant_id: str, entity_ids: list[str]):
        return {eid: self._facts[eid] for eid in entity_ids if eid in self._facts}


def _request(*, kind: str = "population", sid: str = "pop-vips",
             temporal_mode: str | None = None,
             lens_ids: list[str] | None = None) -> ProjectionRequest:
    return ProjectionRequest(
        projectionId="population360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind=kind, id=sid),
        temporalMode=temporal_mode,
        lensIds=lens_ids,
    )


async def _context(request: ProjectionRequest):
    # Fresh registry: only population360 is registered, so sibling projection
    # dependencies compute as missing — exactly the honest in_flight story.
    return await ProviderRegistry().build_context("population360", request)


def _sections(result):
    return {s.id: s for s in result.sections}


def _dim(result, wanted: str) -> dict:
    dims = _sections(result)["state"].content["dimensions"]
    return next(d for d in dims if d["id"] == wanted)


# ── Registration gates ────────────────────────────────────────────────────────


def test_no_auto_register_at_import():
    assert ProviderRegistry().get("population360") is None


def test_register_provider_registers_and_reports_source():
    registry = ProviderRegistry()
    register_provider(registry)
    assert registry.get("population360") is not None
    assert registry.sources() == {"population360": "services/population360"}


def test_register_same_object_is_idempotent_different_object_duplicates():
    registry = ProviderRegistry()
    register_provider(registry)
    # Re-registering the SAME provider object is an idempotent no-op.
    provider = registry.get("population360")
    registry.register(provider)
    # A DIFFERENT object for an already-registered id is a hard error.
    with pytest.raises(DuplicateProjection):
        registry.register(Population360Provider(), source="x")


def test_register_version_mismatch_raises():
    class _WrongMajorProvider(Population360Provider):
        contract_version = "0.0.1"

    with pytest.raises(ContractVersionIncompatible):
        ProviderRegistry().register(_WrongMajorProvider())


def test_register_unknown_id_raises():
    class _BogusProvider(Population360Provider):
        projection_id = "not_a_projection_360"

    with pytest.raises(ProjectionNotFound):
        ProviderRegistry().register(_BogusProvider())


def test_provider_is_read_only_with_no_write_path():
    assert Population360Provider.graph_mutation_policy == "read_only"
    # A read-only provider has no governed write surface.
    assert not any(name.startswith(("add_", "remove_", "write_", "apply_"))
                   for name in dir(Population360Provider))


# ── Valid population projection (snapshots / deltas / transitions / overlap) ──


@pytest.mark.asyncio
async def test_population_projection_is_a_valid_typed_result():
    members = (
        _member("pop-vips", "u1"),
        _member("pop-vips", "u2"),
        _member("pop-vips", "u3", basis="ml_model", confidence=0.4),
    )
    sibling = SiblingCandidate(
        population_id="pop-prospects",
        name="Prospects",
        population_type="cohort",
        active_member_ids=("u1", "u2", "u7"),
        member_ids_truncated=False,
    )
    posture = _population_posture(
        members=members,
        snapshots=(_snapshot("pop-vips", at=T_SNAP1, count=2),
                   _snapshot("pop-vips", at=T_SNAP2, count=3)),
        transitions=(_def_version("pop-vips", "1", at=T_V1,
                                  reason="initial definition", supersedes=None),
                     _def_version("pop-vips", "2", at=T_V2,
                                  reason="recomputed cohort", supersedes="1")),
        siblings=(sibling,),
    )
    provider = Population360Provider(reader=_FakePopulationReader({
        ("population", "pop-vips"): SubjectView(
            kind="population", id="pop-vips", posture=posture, missing_reason=None),
    }))
    request = _request()
    result = await provider.project(request, await _context(request))

    assert result.projectionId == "population360"
    assert result.tenantId == TENANT
    assert result.generatedAt and result.asOf
    assert result.degradedReasons == []
    assert [s.id for s in result.sections] == list(OUTPUT_SECTIONS)

    # dependencyState is echoed from the registry (profile360 etc. missing now).
    assert result.dependencyState == (await _context(request)).dependencyState
    dep_ids = {d.projectionId for d in result.dependencyState}
    assert {"profile360", "relationship360", "temporal360"} <= dep_ids

    sections = _sections(result)
    assert sections["summary"].state == "available"
    summary = sections["summary"].content
    assert summary["member_count"] == 3
    assert summary["population"]["definition_version"] == "2"
    # Composition is sample-based but names the authoritative count + coverage.
    comp = summary["composition"]
    assert comp["member_count"] == 3 and comp["distribution_covers"] == 3
    assert comp["by_basis"] == {"rule": 2, "ml_model": 1}
    assert comp["by_confidence_band"]["low"] == 1   # confidence 0.4 -> low
    assert comp["by_confidence_band"]["very_high"] == 2  # defaults (1.0) -> very_high
    # Snapshot delta between the two consecutive snapshots (2 -> 3).
    assert summary["snapshot_delta"]["delta"] == 1

    # Timeline carries definition transitions + snapshots with deltas, newest first.
    timeline = sections["timeline"].content
    kinds = [e["kind"] for e in timeline["events"]]
    assert "population_created" in kinds
    assert kinds.count("definition_version") == 2
    assert kinds.count("snapshot") == 2
    assert timeline["events"][0]["kind"] == "snapshot"  # newest first
    series = timeline["snapshot_series"]
    assert [d["delta"] for d in series] == [None, 1]

    # Definition transitions + overlap surprise surface as findings.
    codes = {f["code"] for f in sections["findings"].content["findings"]}
    assert "population.definition_transition" in codes
    assert "population.overlap_surprise" in codes  # u1/u2 overlap -> ~0.5 jaccard
    assert "population.low_confidence_members" in codes

    # Every claim is evidence-grounded.
    assert result.claims
    assert all(c.evidenceRefs for c in result.claims)
    sources = {r.source for c in result.claims for r in c.evidenceRefs}
    assert {"population_memberships", "population_definition_versions",
            "population_snapshots"} <= sources


@pytest.mark.asyncio
async def test_known_population_without_snapshots_degrades_snapshot_history():
    # A fully-known population with no snapshot ever taken: snapshot_history is
    # missing (honest), never fabricated; unsnapshotted members surface.
    members = (_member("pop-vips", "u1"), _member("pop-vips", "u2"))
    posture = _population_posture(members=members, updated_at=T_CREATE)
    provider = Population360Provider(reader=_FakePopulationReader({
        ("population", "pop-vips"): SubjectView(
            kind="population", id="pop-vips", posture=posture, missing_reason=None),
    }))
    result = await provider.project(_request(), await _context(_request()))

    assert _dim(result, "snapshot_history")["state"] == "missing"
    codes = {f["code"] for f in _sections(result)["findings"].content["findings"]}
    assert "population.unsnapshotted" in codes


@pytest.mark.asyncio
async def test_known_population_no_members_is_zero_observation_not_fabricated():
    posture = _population_posture(members=(), updated_at=T_CREATE)
    provider = Population360Provider(reader=_FakePopulationReader({
        ("population", "pop-vips"): SubjectView(
            kind="population", id="pop-vips", posture=posture, missing_reason=None),
    }))
    result = await provider.project(_request(), await _context(_request()))
    assert _sections(result)["summary"].content["member_count"] == 0
    # A 0 is a real read over owned rows once the definition is known.
    assert _dim(result, "membership_count")["state"] == "available"


# ── Entity subject ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_entity_projection_lists_definitions_and_transitions():
    entity = EntityPosture(entity_id="u1", memberships=(
        _entity_row(pop="pop-vips", eid="u1"),
        _entity_row(pop="pop-churned", eid="u1", state="left"),
    ))
    provider = Population360Provider(reader=_FakePopulationReader({
        ("entity", "u1"): SubjectView(
            kind="entity", id="u1", posture=entity, missing_reason=None),
    }))
    request = _request(kind="entity", sid="u1")
    result = await provider.project(request, await _context(request))

    summary = _sections(result)["summary"].content
    assert summary["membership_count"] == 1          # one active
    assert summary["membership_episode_count"] == 2  # both episodes recorded
    assert summary["membership_state_distribution"] == {"active": 1, "left": 1}

    events = _sections(result)["timeline"].content["events"]
    kinds = [e["kind"] for e in events]
    assert kinds.count("membership_join") == 2
    assert "membership_leave" in kinds              # the churned membership
    leave = next(e for e in events if e["kind"] == "membership_leave")
    assert leave["leave_reason"] == "churn"

    codes = {f["code"] for f in _sections(result)["findings"].content["findings"]}
    assert "entity.has_inactive_memberships" in codes
    assert "entity.multi_membership" in codes
    assert all(c.evidenceRefs for c in result.claims)


# ── Unknown / degraded / honest-typed ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_subject_renders_unknown_never_fabricated_zero():
    provider = Population360Provider(reader=_FakePopulationReader({}))
    request = _request(sid="pop-does-not-exist")
    result = await provider.project(request, await _context(request))

    sections = _sections(result)
    assert sections["summary"].state == "unknown"
    assert sections["summary"].content["member_count"] is None  # never 0
    assert _dim(result, "subject")["state"] == "unknown"
    assert sections["timeline"].state == "missing"
    codes = {f["code"] for f in sections["findings"].content["findings"]}
    assert "subject.unknown" in codes
    assert any(c.id == "summary.unknown" for c in result.claims)


@pytest.mark.asyncio
async def test_reader_failure_degrades_never_raises():
    class _ExplodingReader(_FakePopulationReader):
        async def view(self, **kwargs):
            raise RuntimeError("backing store down")

    provider = Population360Provider(reader=_ExplodingReader({}))
    result = await provider.project(_request(), await _context(_request()))
    assert result.degradedReasons == []
    assert _sections(result)["summary"].state == "unknown"


@pytest.mark.asyncio
async def test_unsupported_temporal_mode_serves_window_never_raises():
    posture = _population_posture(
        members=(_member("pop-vips", "u1"),),
        snapshots=(_snapshot("pop-vips", at=T_SNAP1, count=1),),
        updated_at=T_SNAP1,
    )
    provider = Population360Provider(reader=_FakePopulationReader({
        ("population", "pop-vips"): SubjectView(
            kind="population", id="pop-vips", posture=posture, missing_reason=None),
    }))
    request = _request(temporal_mode="compare")  # population360 supports only window/relative
    result = await provider.project(request, await _context(request))
    assert result.temporalMode == "window"
    assert _sections(result)["summary"].content["effective_temporal_mode"] == "window"


@pytest.mark.asyncio
async def test_tenant_isolation_never_projects_other_tenants():
    posture = _population_posture(
        members=(_member("pop-vips", "u-secret"),), updated_at=T_CREATE)
    reader = _FakePopulationReader({
        ("population", "pop-vips"): SubjectView(
            kind="population", id="pop-vips", posture=posture, missing_reason=None),
    })
    provider = Population360Provider(reader=reader)
    request = ProjectionRequest(
        projectionId="population360",
        tenantId=OTHER_TENANT,                      # not the reader's tenant
        subject=ProjectionSubject(kind="population", id="pop-vips"),
    )
    result = await provider.project(request, await _context(request))
    # Fail-closed: nothing about the other tenant's posture leaks; the provider
    # degrades instead of raising.
    assert result.degradedReasons == []
    sections = _sections(result)
    assert sections["summary"].state == "unknown"
    assert sections["summary"].content["member_count"] is None
    assert any(c.id == "summary.unknown" for c in result.claims)
    assert reader.calls[-1][0] == OTHER_TENANT


# ── Demographic lens (opt-in via lensIds; honest while profile360 in_flight) ──


@pytest.mark.asyncio
async def test_demographic_lens_is_dormant_unless_requested():
    members = (_member("pop-vips", "u1"), _member("pop-vips", "u2"))
    posture = _population_posture(members=members, updated_at=T_CREATE)
    provider = Population360Provider(reader=_FakePopulationReader({
        ("population", "pop-vips"): SubjectView(
            kind="population", id="pop-vips", posture=posture, missing_reason=None),
    }))
    result = await provider.project(_request(), await _context(_request()))
    ids = [d["id"] for d in _sections(result)["state"].content["dimensions"]]
    assert "demographics" not in ids


@pytest.mark.asyncio
async def test_demographic_lens_requested_degrades_missing_while_profile360_in_flight():
    # No lens injected -> the default UnavailableProfileFactsReader -> the lens
    # degrades to missing (profile360 in_flight). Honest, never fabricated.
    members = (_member("pop-vips", "u1"), _member("pop-vips", "u2"))
    posture = _population_posture(members=members, updated_at=T_CREATE)
    provider = Population360Provider(reader=_FakePopulationReader({
        ("population", "pop-vips"): SubjectView(
            kind="population", id="pop-vips", posture=posture, missing_reason=None),
    }))
    request = _request(lens_ids=["demographic"])
    result = await provider.project(request, await _context(request))
    assert _dim(result, "demographics")["state"] == "missing"
    codes = {f["code"] for f in _sections(result)["findings"].content["findings"]}
    assert "demographics.missing" in codes


@pytest.mark.asyncio
async def test_demographic_lens_reads_canonical_profile_facts():
    facts: dict[str, HumanProfileFact] = {
        "u1": {"age": 30, "gender": "female", "language": "en"},
        "u2": {"age": 40, "gender": "male", "language": "en"},
    }
    lens = DemographicLens(facts_reader=_FakeProfileFactsReader(facts))
    members = (_member("pop-vips", "u1"), _member("pop-vips", "u2"))
    posture = _population_posture(members=members, updated_at=T_CREATE)
    provider = Population360Provider(
        reader=_FakePopulationReader({
            ("population", "pop-vips"): SubjectView(
                kind="population", id="pop-vips", posture=posture,
                missing_reason=None),
        }),
        demographic_lens=lens,
    )
    request = _request(lens_ids=["demographic"])
    result = await provider.project(request, await _context(request))
    dim = _dim(result, "demographics")
    assert dim["state"] == "available"
    # Small-cell suppression (default floor 5) withholds the sparse cells.
    assert "demographics.available" not in {
        f["code"] for f in _sections(result)["findings"].content["findings"]}


@pytest.mark.asyncio
async def test_demographic_lens_non_human_cohort_not_applicable():
    members = (_member("pop-bots", "d1", entity_type="device"),)
    posture = _population_posture(pid="pop-bots", members=members, updated_at=T_CREATE)
    provider = Population360Provider(reader=_FakePopulationReader({
        ("population", "pop-bots"): SubjectView(
            kind="population", id="pop-bots", posture=posture, missing_reason=None),
    }))
    request = _request(sid="pop-bots", lens_ids=["demographic"])
    result = await provider.project(request, await _context(request))
    assert _dim(result, "demographics")["state"] == "not_applicable"


# ── Default repository reader (real registry rows, tenant-scoped) ────────────


@pytest.mark.asyncio
async def test_default_reader_is_tenant_scoped_over_registry_rows():
    reset_in_memory_stores()
    pop_a = await population_repo.create_population(
        name="VIPs", population_type=PopulationType.SEGMENT,
        tenant_id=TENANT,
    )
    pop_b = await population_repo.create_population(
        name="Foreign", population_type=PopulationType.COHORT,
        tenant_id=OTHER_TENANT,
    )
    await membership_repo.add_member(
        pop_a["id"], "u1", basis=MembershipBasis.RULE, tenant_id=TENANT,
    )
    await membership_repo.add_member(
        pop_a["id"], "u2", basis=MembershipBasis.ML_MODEL,
        confidence=0.6, tenant_id=TENANT,
    )
    await membership_repo.add_member(
        pop_b["id"], "u-x", basis=MembershipBasis.RULE, tenant_id=OTHER_TENANT,
    )

    reader = PopulationRepositoryReader()

    # Owned population under the right tenant.
    view_a = await reader.view(
        tenant_id=TENANT, subject_kind="population", subject_id=pop_a["id"])
    assert view_a.posture is not None
    assert view_a.posture.active_member_count == 2
    assert view_a.posture.definition_transitions  # v1 seeded at creation
    assert {m.entity_id for m in view_a.posture.members_sample} == {"u1", "u2"}
    # Composition over owned rows only (row order is not a read contract).
    by_basis = {m.entity_id: m.basis for m in view_a.posture.members_sample}
    assert by_basis == {"u1": "rule", "u2": "ml_model"}

    # Same population id under ANOTHER tenant resolves to no owned observation.
    view_b = await reader.view(
        tenant_id=OTHER_TENANT, subject_kind="population", subject_id=pop_a["id"])
    assert view_b.posture is None and view_b.missing_reason is not None

    # Entity subject: only its own tenant's memberships are returned.
    view_entity = await reader.view(
        tenant_id=TENANT, subject_kind="entity", subject_id="u1")
    assert view_entity.posture is not None
    pops = {m["population_id"] for m in view_entity.posture.memberships}
    assert pops == {pop_a["id"]}
    assert view_entity.posture.memberships[0]["population_name"] == "VIPs"

    # Unknown entity under the tenant -> no owned observation.
    view_missing = await reader.view(
        tenant_id=TENANT, subject_kind="entity", subject_id="nobody")
    assert view_missing.posture is None
