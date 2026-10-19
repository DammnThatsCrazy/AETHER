"""Focused behavioral contract for the read-only Profile360 provider."""

from __future__ import annotations

from typing import Optional

import pytest
from types import SimpleNamespace

from graph.operational_intelligence.models import TimeRangeFilter
from graph.temporal360.history_replay import SubjectEvent, SubjectHistory
from shared.intelligence_projections.contracts import (
    EvidenceRef,
    ProjectionRequest,
    ProjectionSubject,
)
from shared.intelligence_projections.registry import ProviderRegistry
from identity.profile.profile360_provider import (
    EventRead,
    HistoryRead,
    IdentityBindingRead,
    OUTPUT_SECTIONS,
    Profile360Provider,
    ProfileRead,
    RepositoryProfile360Source,
)


TENANT = "tenant_profile360"
USER_ID = "user-profile-1"
AS_OF = "2026-06-01T12:00:00Z"
WINDOW_START = "2026-05-01T00:00:00Z"
WINDOW_END = "2026-06-01T00:00:00Z"


def _history(*, present: bool = True, event_count: int = 1) -> SubjectHistory:
    events = (
        SubjectEvent(
            recorded_at="2026-05-20T12:00:00Z",
            ledger_offset=4,
            kind="vertex_superseded",
            operation="node_updated",
            aggregate_type="node",
            aggregate_id=f"{TENANT}:user:{USER_ID}",
            mutation_id="mutation-profile-4",
            valid_from="2026-05-20T12:00:00Z",
            vertex_id=f"{TENANT}:user:{USER_ID}",
            changed={"status": {"before": "new", "after": "active"}},
        ),
    ) if event_count else ()
    return SubjectHistory(
        subject_id=f"{TENANT}:user:{USER_ID}",
        as_of=AS_OF,
        present=present,
        vertex={"status": "active", "tenant_id": TENANT},
        first_recorded="2026-05-20T12:00:00Z" if event_count else None,
        last_recorded="2026-05-20T12:00:00Z" if event_count else None,
        event_count=event_count,
        events=events,
        live_edges=(),
        vertex_supersessions=1 if event_count else 0,
        incident_edge_adds=0,
        incident_edge_revocations=0,
        digest="digest-profile360",
    )


class _FakeProfileSource:
    def __init__(
        self,
        *,
        identity: Optional[ProfileRead] = None,
        events: Optional[EventRead] = None,
        history: Optional[HistoryRead] = None,
        binding: Optional[IdentityBindingRead] = None,
        fail: bool = False,
    ) -> None:
        self.identity = identity or ProfileRead(
            record={
                "tenant_id": TENANT,
                "user_id": USER_ID,
                "display_name": "Test Profile",
                "status": "active",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-05-30T00:00:00Z",
                "email": "private@example.invalid",
            },
            available=True,
            scope_known=True,
        )
        self.events = events or EventRead(
            rows=[
                {
                    "tenant_id": TENANT,
                    "canonical_entity_id": USER_ID,
                    "event_id": "event-profile-1",
                    "event_type": "profile_observed",
                    "occurred_at": "2026-05-20T10:00:00Z",
                    "properties": {"private_payload": "must not escape"},
                }
            ],
            available=True,
            scope_known=True,
        )
        self.history = history or HistoryRead(history=_history(), available=True)
        self.binding = binding or IdentityBindingRead(
            tenant_id=TENANT,
            resolved_subject=None,
            evidence_ref=None,
            authority=None,
            relationship=None,
            observed_at=None,
            available=True,
            scope_known=False,
            reason="identity_binding_not_configured",
        )
        self.fail = fail
        self.calls: list[tuple] = []

    async def identity_record(self, tenant_id, subject):
        self.calls.append(("identity", tenant_id, subject.id))
        if self.fail:
            raise RuntimeError("identity database detail must not escape")
        return self.identity

    async def identity_binding(self, tenant_id, subject):
        self.calls.append(("binding", tenant_id, subject.kind, subject.id))
        if self.fail:
            raise RuntimeError("identity binding database detail must not escape")
        return self.binding

    async def analytics_events(
        self, tenant_id, subject, *, limit, start, end
    ):
        self.calls.append(("events", tenant_id, subject.id, limit, start, end))
        if self.fail:
            raise RuntimeError("analytics database detail must not escape")
        return self.events

    async def subject_history(self, tenant_id, subject_id, *, as_of):
        self.calls.append(("history", tenant_id, subject_id, as_of))
        if self.fail:
            raise RuntimeError("ledger detail must not escape")
        return self.history


def _request(*, mode: Optional[str] = None, time_range=None) -> ProjectionRequest:
    return ProjectionRequest(
        projectionId="profile360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="entity", id=USER_ID),
        temporalMode=mode,
        timeRange=time_range,
    )


async def _project(provider: Profile360Provider, request: ProjectionRequest):
    context = await ProviderRegistry().build_context("profile360", request)
    return await provider.project(request, context)


def _section(result, section_id: str):
    return next(section for section in result.sections if section.id == section_id)


@pytest.mark.asyncio
async def test_window_projects_catalog_slots_and_evidence_without_raw_payloads():
    source = _FakeProfileSource()
    result = await _project(
        Profile360Provider(source),
        _request(
            mode="window",
            time_range=TimeRangeFilter(**{"from": WINDOW_START, "to": WINDOW_END}),
        ),
    )

    assert tuple(section.id for section in result.sections) == OUTPUT_SECTIONS
    assert result.tenantId == TENANT
    assert result.asOf is None
    assert source.calls[0] == ("identity", TENANT, USER_ID)
    event_call = next(call for call in source.calls if call[0] == "events")
    assert event_call[-2:] == (WINDOW_START, WINDOW_END)
    assert source.calls[-1][0] == "history"
    assert source.calls[-1][2] == f"{TENANT}:user:{USER_ID}"

    summary = _section(result, "summary")
    assert summary.content["identity"]["record"]["displayName"] == "Test Profile"
    assert "email" not in summary.content["identity"]["record"]
    timeline = _section(result, "timeline")
    assert timeline.content["items"][0]["id"] == "event-profile-1"
    assert "private_payload" not in str(timeline.content)
    assert _section(result, "interactions").state == "unknown"
    assert _section(result, "state").content["dimensions"][-1]["state"] == "unknown"

    identity_claim = next(
        claim for claim in result.claims if claim.id == "profile360.identity_record_present"
    )
    assert identity_claim.domainSlotIds == ["entity_identity"]
    assert identity_claim.evidenceRefs[0].source == "identity_profiles"
    activity_claim = next(
        claim for claim in result.claims if claim.id == "profile360.activity_records_observed"
    )
    assert "observed_state_and_activity" in activity_claim.domainSlotIds
    assert activity_claim.evidenceRefs


@pytest.mark.asyncio
async def test_unresolved_empty_reads_remain_unknown_not_known_empty():
    source = _FakeProfileSource(
        identity=ProfileRead(
            record=None,
            available=True,
            scope_known=False,
            reason="identity_subject_not_resolved",
        ),
        events=EventRead(rows=[], available=True, scope_known=True),
        history=HistoryRead(history=_history(present=False, event_count=0), available=True),
    )
    result = await _project(Profile360Provider(source), _request())

    assert _section(result, "state").content["dimensions"][0]["state"] == "unknown"
    assert _section(result, "state").content["dimensions"][1]["state"] == "unknown"


def _related_request(kind: str, subject_id: str, *, as_of: Optional[str] = None):
    return ProjectionRequest(
        projectionId="profile360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind=kind, id=subject_id),
        temporalMode="as_of" if as_of is not None else "window",
        asOf=as_of,
    )


def _profile_binding(kind: str = "journey") -> IdentityBindingRead:
    if kind == "journey":
        authority = "journeys"
        relationship = "journey_profile_id"
        evidence_id = "journey-version-7"
    else:
        authority = "episode_facts"
        relationship = "episode_user_subject"
        evidence_id = "episode-7"
    return IdentityBindingRead(
        tenant_id=TENANT,
        resolved_subject=ProjectionSubject(kind="entity", id=USER_ID),
        evidence_ref=EvidenceRef(
            id=evidence_id,
            type="relationship",
            source=authority,
            observedAt="2026-05-30T00:00:00Z",
        ),
        authority=authority,
        relationship=relationship,
        observed_at="2026-05-30T00:00:00Z",
        available=True,
        scope_known=True,
    )


@pytest.mark.asyncio
async def test_journey_entity_context_preserves_journey_subject_and_exact_profile_link():
    source = _FakeProfileSource(binding=_profile_binding("journey"))
    result = await _project(
        Profile360Provider(source), _related_request("journey", "journey-1")
    )

    summary = _section(result, "summary").content
    linked = summary["relatedEntityContext"]
    assert summary["subject"] == {"kind": "journey", "id": "journey-1"}
    assert linked["resolvedEntity"] == {
        "kind": "entity",
        "id": USER_ID,
        "status": "active",
    }
    assert linked["relationship"] == "journey_profile_id"
    assert "not the journey or episode subject" in linked["interpretation"]
    assert source.calls == [
        ("binding", TENANT, "journey", "journey-1"),
        ("identity", TENANT, USER_ID),
    ]
    assert result.claims == []
    assert _section(result, "evidence").content["count"] == 2


@pytest.mark.asyncio
async def test_episode_entity_context_requires_exact_user_subject_binding():
    source = _FakeProfileSource(binding=_profile_binding("episode"))
    result = await _project(
        Profile360Provider(source), _related_request("episode", "episode-1")
    )

    linked = _section(result, "state").content["dimensions"][0]["content"]
    assert linked["state"] == "available"
    assert linked["relationship"] == "episode_user_subject"
    assert source.calls == [
        ("binding", TENANT, "episode", "episode-1"),
        ("identity", TENANT, USER_ID),
    ]


@pytest.mark.asyncio
async def test_related_profile_context_does_not_use_current_link_for_historical_request():
    source = _FakeProfileSource(binding=_profile_binding("journey"))
    result = await _project(
        Profile360Provider(source),
        _related_request("journey", "journey-1", as_of=AS_OF),
    )

    assert source.calls == []
    assert _section(result, "summary").state == "unknown"
    assert _section(result, "summary").content["relatedEntityContext"]["reason"] == (
        "identity_binding_valid_time_unavailable"
    )


@pytest.mark.asyncio
async def test_cross_tenant_related_profile_binding_is_unknown():
    binding = _profile_binding("journey")
    source = _FakeProfileSource(
        binding=IdentityBindingRead(
            **{**binding.__dict__, "tenant_id": "tenant-other"}
        )
    )
    result = await _project(
        Profile360Provider(source), _related_request("journey", "journey-1")
    )

    assert _section(result, "summary").state == "unknown"
    assert _section(result, "summary").content["relatedEntityContext"]["reason"] == (
        "identity_binding_tenant_mismatch"
    )
    assert source.calls == [("binding", TENANT, "journey", "journey-1")]
    assert _section(result, "timeline").state == "not_applicable"
    assert _section(result, "evidence").state == "unknown"
    assert result.claims == []


@pytest.mark.asyncio
async def test_repository_journey_binding_requires_one_exact_current_profile_version(monkeypatch):
    class _Journeys:
        async def list_versions(self, tenant_id, journey_id):
            assert (tenant_id, journey_id) == (TENANT, "journey-1")
            return [
                {
                    "tenant_id": TENANT,
                    "journey_id": "journey-1",
                    "journey_type": "profile",
                    "profile_id": USER_ID,
                    "journey_version_id": "journey-version-7",
                    "is_current": True,
                    "computed_at": "2026-05-30T00:00:00Z",
                }
            ]

    monkeypatch.setattr(
        "journeys.measurement.repositories.journey_repo.JourneyRepository",
        lambda: _Journeys(),
    )
    binding = await RepositoryProfile360Source().identity_binding(
        TENANT, ProjectionSubject(kind="journey", id="journey-1")
    )

    assert binding.tenant_id == TENANT
    assert binding.scope_known is True
    assert binding.resolved_subject == ProjectionSubject(kind="entity", id=USER_ID)
    assert binding.authority == "journey_versions"
    assert binding.evidence_ref is not None
    assert binding.evidence_ref.id == "journey-version-7"


@pytest.mark.asyncio
async def test_repository_journey_binding_rejects_ambiguous_current_versions(monkeypatch):
    class _Journeys:
        async def list_versions(self, tenant_id, journey_id):
            return [
                {
                    "tenant_id": TENANT,
                    "journey_id": journey_id,
                    "journey_type": "profile",
                    "profile_id": USER_ID,
                    "journey_version_id": f"journey-version-{index}",
                    "is_current": True,
                }
                for index in (1, 2)
            ]

    monkeypatch.setattr(
        "journeys.measurement.repositories.journey_repo.JourneyRepository",
        lambda: _Journeys(),
    )
    binding = await RepositoryProfile360Source().identity_binding(
        TENANT, ProjectionSubject(kind="journey", id="journey-1")
    )

    assert binding.scope_known is False
    assert binding.resolved_subject is None
    assert binding.reason == "journey_identity_binding_ambiguous"


@pytest.mark.asyncio
async def test_repository_episode_binding_accepts_only_exact_user_subject(monkeypatch):
    episode = SimpleNamespace(
        tenant_id=TENANT,
        episode_id="episode-1",
        subject=SimpleNamespace(kind="user", id=USER_ID),
        created_at="2026-05-30T00:00:00Z",
    )

    class _Episodes:
        async def get(self, tenant_id, episode_id):
            assert (tenant_id, episode_id) == (TENANT, "episode-1")
            return episode

    monkeypatch.setattr(
        "shared.backend_interpretation.stores.EpisodeStore",
        lambda: _Episodes(),
    )
    binding = await RepositoryProfile360Source().identity_binding(
        TENANT, ProjectionSubject(kind="episode", id="episode-1")
    )

    assert binding.scope_known is True
    assert binding.resolved_subject == ProjectionSubject(kind="entity", id=USER_ID)
    assert binding.relationship == "episode_user_subject"


@pytest.mark.asyncio
async def test_repository_episode_binding_rejects_non_user_subject(monkeypatch):
    episode = SimpleNamespace(
        tenant_id=TENANT,
        episode_id="episode-1",
        subject=SimpleNamespace(kind="agent", id="agent-1"),
        created_at="2026-05-30T00:00:00Z",
    )

    class _Episodes:
        async def get(self, tenant_id, episode_id):
            return episode

    monkeypatch.setattr(
        "shared.backend_interpretation.stores.EpisodeStore",
        lambda: _Episodes(),
    )
    binding = await RepositoryProfile360Source().identity_binding(
        TENANT, ProjectionSubject(kind="episode", id="episode-1")
    )

    assert binding.scope_known is False
    assert binding.resolved_subject is None
    assert binding.reason == "episode_subject_not_exact_user_profile"


@pytest.mark.asyncio
async def test_as_of_reads_only_temporal_authority_and_reports_effective_anchor():
    source = _FakeProfileSource()
    result = await _project(
        Profile360Provider(source),
        _request(mode="as_of", time_range=TimeRangeFilter(**{"from": AS_OF})),
    )

    assert [call[0] for call in source.calls] == ["history"]
    assert source.calls[0][-1] == AS_OF
    assert result.asOf == AS_OF
    assert _section(result, "summary").content["identity"]["state"] == "unknown"
    assert _section(result, "timeline").content["asOf"] == result.asOf
    assert not any(claim.id == "profile360.identity_record_present" for claim in result.claims)


@pytest.mark.asyncio
async def test_source_failures_degrade_instead_of_claiming_empty():
    source = _FakeProfileSource(fail=True)
    result = await _project(Profile360Provider(source), _request())

    assert _section(result, "summary").state == "degraded"
    assert _section(result, "timeline").state == "degraded"
    assert _section(result, "evidence").state == "unknown"
    assert all("database detail" not in str(section.content) for section in result.sections)
    assert result.claims == []


@pytest.mark.asyncio
async def test_relative_mode_without_bounds_is_not_silently_relabelled():
    source = _FakeProfileSource()
    result = await _project(Profile360Provider(source), _request(mode="relative"))

    assert source.calls == []
    assert _section(result, "summary").state == "degraded"
    assert any(
        item["code"] == "temporal_request_not_satisfied"
        for item in _section(result, "findings").content["items"]
    )
