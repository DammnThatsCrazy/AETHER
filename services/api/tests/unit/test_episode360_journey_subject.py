"""Episode360's journey subject path reads canonical journey versions and steps."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from journeys.measurement.episodes.provider import (  # noqa: E402
    Episode360Provider,
    EpisodeSubjectGraphRead,
    RepositoryJourney360Source,
)
from graph.operational_intelligence.models import EntityRef, EvidenceRef  # noqa: E402
from graph.temporal360.history_replay import SubjectEvent  # noqa: E402
from shared.intelligence_projections.composition import (  # noqa: E402
    compose_experience360_frame,
)
from shared.backend_interpretation.primitives import EpisodeRecord  # noqa: E402
from shared.backend_interpretation.stores import EpisodePageRead  # noqa: E402
from shared.intelligence_projections.contracts import (  # noqa: E402
    Experience360FrameRequest,
    Experience360PolicyDisposition,
    ProjectionContext,
    ProjectionRequest,
    ProjectionSubject,
)
from shared.intelligence_projections.generated_registry import (  # noqa: E402
    INTELLIGENCE_PROJECTION_DEFINITIONS,
)

TENANT = "tenant-journey-episode360"
JOURNEY_ID = "journey-1"
VERSION_ID = "journey-version-1"
AGENT_ID = "agent-episode-1"


def _journey(tenant_id: str = TENANT, **overrides: object) -> dict:
    row = {
        "tenant_id": tenant_id,
        "journey_id": JOURNEY_ID,
        "journey_version_id": VERSION_ID,
        "journey_type": "profile",
        "journey_state": "open",
        "is_current": True,
        "profile_id": "profile-1",
        "cluster_id": None,
        "agent_id": None,
        "campaign_ids": ["campaign-1"],
        "channel_sequence": ["web", "email"],
        "conversion_ids": ["conversion-1"],
        "event_ids": ["event-1"],
        "started_at": "2026-10-15T09:00:00+00:00",
        "ended_at": None,
        "converted_at": None,
        "computed_at": "2026-10-16T10:00:00+00:00",
        "data_watermark": "2026-10-16T09:59:00+00:00",
        "identity_version": "identity-v1",
        "compiler_version": "1.0",
    }
    row.update(overrides)
    return row


def _step(
    *,
    step_id: str = "step-1",
    tenant_id: str = TENANT,
    journey_id: str = JOURNEY_ID,
    version_id: str = VERSION_ID,
    position: int = 1,
    **overrides: object,
) -> dict:
    row = {
        "step_id": step_id,
        "tenant_id": tenant_id,
        "journey_id": journey_id,
        "journey_version_id": version_id,
        "step_position": position,
        "occurred_at": "2026-10-16T09:30:00+00:00",
        "activity_id": f"activity-{step_id}",
        "activity_family": "web",
        "activity_type": "page_view",
        "transition_type": "same_session",
        "actor_type": "user",
        "channel": "web",
        "source_class": "owned",
        "traffic_origin": "direct",
        "economic_class": "none",
        "channel_family": "web",
        "proof_level": "observed",
        "journey_role": "entry",
        "campaign_id": "campaign-1",
        "conversion_id": None,
        "agent_id": None,
        "activity_status": "observed",
        "evidence_summary": {"private_payload": "must-not-appear"},
    }
    row.update(overrides)
    return row


def _request(**overrides: object) -> ProjectionRequest:
    values: dict[str, object] = {
        "projectionId": "episode360",
        "tenantId": TENANT,
        "subject": ProjectionSubject(kind="journey", id=JOURNEY_ID),
        "includeClaims": True,
    }
    values.update(overrides)
    return ProjectionRequest(**values)


def _context(tenant_id: str = TENANT) -> ProjectionContext:
    return ProjectionContext(
        projectionId="episode360",
        tenantId=tenant_id,
        registryState="in_flight",
        dependencyState=[],
        warnings=[],
    )


def _episode(
    *,
    episode_id: str = "episode-1",
    tenant_id: str = TENANT,
    subject_kind: str = "agent",
    subject_id: str = AGENT_ID,
) -> EpisodeRecord:
    return EpisodeRecord(
        episode_id=episode_id,
        tenant_id=tenant_id,
        subject=EntityRef(kind=subject_kind, id=subject_id),
        kind="agent_execution",
        observation_ids=[f"observation-{episode_id}"],
        evidence_refs=[
            EvidenceRef(
                id=f"evidence-{episode_id}",
                type="event",
                source="episode-test",
            )
        ],
    )


class FakeEpisodeStore:
    def __init__(
        self,
        page: EpisodePageRead,
        *,
        direct_record: EpisodeRecord | None = None,
    ) -> None:
        self.page = page
        self.direct_record = direct_record
        self.page_calls: list[dict[str, object]] = []
        self.get_calls: list[tuple[str, str]] = []

    async def get(self, tenant_id: str, episode_id: str) -> EpisodeRecord | None:
        self.get_calls.append((tenant_id, episode_id))
        if (
            self.direct_record is not None
            and self.direct_record.tenant_id == tenant_id
            and self.direct_record.episode_id == episode_id
        ):
            return self.direct_record
        return None

    async def list_page_by_tenant(
        self, tenant_id: str, *, limit: int, cursor: str | None = None
    ) -> EpisodePageRead:
        self.page_calls.append({"tenant_id": tenant_id, "limit": limit, "cursor": cursor})
        return self.page

    async def list_by_tenant(self, tenant_id: str) -> list[EpisodeRecord]:
        raise AssertionError("Episode360 must use bounded tenant paging")


class FakeJourneySource:
    def __init__(
        self,
        journey: dict | None = None,
        steps: list[dict] | None = None,
    ) -> None:
        self.journey = _journey() if journey is None else journey
        self.step_rows = [_step()] if steps is None else steps
        self.current_calls: list[tuple[str, str]] = []
        self.step_calls: list[dict] = []

    async def current_journey(self, *, tenant_id: str, journey_id: str):
        self.current_calls.append((tenant_id, journey_id))
        return self.journey

    async def steps(self, **kwargs: object):
        self.step_calls.append(kwargs)
        return self.step_rows


class FakeEpisodeSubjectRelationshipReader:
    def __init__(self, result: EpisodeSubjectGraphRead | None = None, *, raises=None) -> None:
        self.result = result
        self.raises = raises
        self.calls: list[tuple[str, str]] = []

    async def subject_history(self, *, tenant_id: str, subject_id: str):
        self.calls.append((tenant_id, subject_id))
        if self.raises is not None:
            raise self.raises
        return self.result


class FakeJourneyRepository:
    def __init__(self, row: dict) -> None:
        self.row = row
        self.calls: list[tuple[str, str]] = []

    async def get_current(self, tenant_id: str, journey_id: str):
        self.calls.append((tenant_id, journey_id))
        return self.row


class FakeStepRepository:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.calls: list[dict] = []

    async def list_by_version(self, tenant_id: str, version_id: str, **kwargs: object):
        self.calls.append({"tenant_id": tenant_id, "version_id": version_id, **kwargs})
        return self.rows


def _section(result: object, section_id: str):
    return next(section for section in result.sections if section.id == section_id)


def _episode_request(**overrides: object) -> ProjectionRequest:
    values: dict[str, object] = {
        "projectionId": "episode360",
        "tenantId": TENANT,
        "subject": ProjectionSubject(kind="agent", id=AGENT_ID),
        "page": {"limit": 3, "cursor": "page-cursor"},
    }
    values.update(overrides)
    return ProjectionRequest(**values)


async def test_episode_subject_uses_bounded_page_and_exact_subject_id() -> None:
    store = FakeEpisodeStore(
        EpisodePageRead(
            records=(
                _episode(),
                _episode(episode_id="another-agent", subject_id="agent-other"),
            ),
            next_cursor=None,
            truncated=False,
        )
    )
    result = await Episode360Provider(episode_store=store).project(_episode_request(), _context())

    assert store.page_calls == [{"tenant_id": TENANT, "limit": 3, "cursor": "page-cursor"}]
    assert _section(result, "summary").content["episodeCount"] == 1
    assert _section(result, "timeline").content["timeline"][0]["episodeId"] == "episode-1"
    assert result.page.hasNextPage is False
    assert result.page.totalEstimate is None


async def test_exact_episode_subject_uses_tenant_scoped_episode_key() -> None:
    episode = _episode(episode_id="episode-exact")
    store = FakeEpisodeStore(
        EpisodePageRead(records=(), next_cursor=None, truncated=False),
        direct_record=episode,
    )
    request = _episode_request(subject=ProjectionSubject(kind="episode", id="episode-exact"))

    result = await Episode360Provider(episode_store=store).project(request, _context())

    assert store.get_calls == [(TENANT, "episode-exact")]
    assert store.page_calls == []
    assert _section(result, "summary").content["episodeCount"] == 1
    assert _section(result, "timeline").content["timeline"][0]["episodeId"] == "episode-exact"


async def test_exact_episode_projects_subject_binding_and_separate_graph_relationship_evidence() -> None:
    episode = _episode(episode_id="episode-with-graph-subject")
    event = SubjectEvent(
        recorded_at="2026-10-17T10:00:00+00:00",
        ledger_offset=17,
        kind="edge_added",
        operation="node_versioned",
        aggregate_type="edge",
        aggregate_id="MEMBER_OF:agent-episode-1:org-1",
        mutation_id="graph-mutation-17",
        edge_type="MEMBER_OF",
        from_vertex_id=AGENT_ID,
        to_vertex_id="org-1",
    )
    graph_reader = FakeEpisodeSubjectRelationshipReader(
        EpisodeSubjectGraphRead(
            tenant_id=TENANT,
            subject_id=AGENT_ID,
            events=(event,),
            live_edges=(("MEMBER_OF", AGENT_ID, "org-1"),),
        )
    )
    store = FakeEpisodeStore(
        EpisodePageRead(records=(), next_cursor=None, truncated=False),
        direct_record=episode,
    )
    request = _episode_request(
        subject=ProjectionSubject(kind="episode", id=episode.episode_id)
    )

    result = await Episode360Provider(
        episode_store=store,
        subject_relationship_reader=graph_reader,
    ).project(request, _context())

    assert graph_reader.calls == [(TENANT, AGENT_ID)]
    evidence = _section(result, "evidence").content
    assert evidence["episodeSubjects"] == [
        {
            "episodeId": "episode-with-graph-subject",
            "subject": {"kind": "agent", "id": AGENT_ID},
        }
    ]
    relationship_context = evidence["subjectRelationshipContext"]
    assert relationship_context["episodeId"] == episode.episode_id
    assert relationship_context["subject"] == {"kind": "agent", "id": AGENT_ID}
    assert relationship_context["state"] == "degraded"
    assert relationship_context["coverage"] == "unknown"
    assert relationship_context["reason"] == "graph_history_replay_has_no_completeness_watermark"
    assert relationship_context["observedRelationships"] == [
        {
            "edgeType": "MEMBER_OF",
            "fromEntityId": AGENT_ID,
            "toEntityId": "org-1",
            "state": "active",
            "recordedAt": "2026-10-17T10:00:00+00:00",
            "evidenceRefId": "graph-mutation-17",
        }
    ]
    assert relationship_context["relationshipEvidenceRefs"] == [
        {
            "id": "graph-mutation-17",
            "type": "relationship",
            "source": "graph_mutation_ledger",
            "observedAt": "2026-10-17T10:00:00+00:00",
            "confidence": None,
            "uri": None,
        }
    ]
    # Graph context remains separate from the episode's own evidence and claims.
    assert [ref["id"] for ref in evidence["evidence"]] == ["evidence-episode-with-graph-subject"]
    assert [ref.id for claim in result.claims for ref in claim.evidenceRefs] == [
        "evidence-episode-with-graph-subject"
    ]
    subject_context = _section(result, "episode_context")
    assert subject_context.state == "available"
    assert subject_context.content["state"] == "degraded"
    assert subject_context.content["relationshipEvidenceRefs"][0]["id"] == "graph-mutation-17"


async def test_entity_context_uses_only_exact_tenant_episode_subject_as_graph_anchor() -> None:
    episode = _episode(episode_id="episode-entity-context")
    event = SubjectEvent(
        recorded_at="2026-10-17T10:00:00+00:00",
        ledger_offset=18,
        kind="edge_added",
        operation="node_versioned",
        aggregate_type="edge",
        aggregate_id="MEMBER_OF:agent-episode-1:org-2",
        mutation_id="graph-mutation-18",
        edge_type="MEMBER_OF",
        from_vertex_id=AGENT_ID,
        to_vertex_id="org-2",
    )
    graph_reader = FakeEpisodeSubjectRelationshipReader(
        EpisodeSubjectGraphRead(
            tenant_id=TENANT,
            subject_id=AGENT_ID,
            events=(event,),
            live_edges=(("MEMBER_OF", AGENT_ID, "org-2"),),
        )
    )
    store = FakeEpisodeStore(
        EpisodePageRead(records=(episode,), next_cursor=None, truncated=False)
    )
    request = _episode_request(subject=ProjectionSubject(kind="entity", id=AGENT_ID))

    result = await Episode360Provider(
        episode_store=store,
        subject_relationship_reader=graph_reader,
    ).project(request, _context())

    assert graph_reader.calls == [(TENANT, AGENT_ID)]
    context = _section(result, "episode_context")
    assert context.state == "available"  # observed rows are available; their coverage stays degraded
    assert context.content["state"] == "degraded"
    assert context.content["subject"] == {"kind": "agent", "id": AGENT_ID}
    assert context.content["episodeIds"] == [episode.episode_id]
    assert context.content["episodeAssociationCoverage"] == "complete"
    assert context.content["relationshipEvidenceRefs"] == [
        {
            "id": "graph-mutation-18",
            "type": "relationship",
            "source": "graph_mutation_ledger",
            "observedAt": "2026-10-17T10:00:00+00:00",
            "confidence": None,
            "uri": None,
        }
    ]
    assert "graph_history_replay_has_no_completeness_watermark" in result.degradedReasons


async def test_entity_relationship_context_composition_is_graph_scoped_and_degraded_without_siblings() -> None:
    episode = _episode(episode_id="episode-entity-frame-context")
    event = SubjectEvent(
        recorded_at="2026-10-17T10:00:00+00:00",
        ledger_offset=19,
        kind="edge_added",
        operation="node_versioned",
        aggregate_type="edge",
        aggregate_id="MEMBER_OF:agent-episode-1:org-3",
        mutation_id="graph-mutation-19",
        edge_type="MEMBER_OF",
        from_vertex_id=AGENT_ID,
        to_vertex_id="org-3",
    )
    graph_reader = FakeEpisodeSubjectRelationshipReader(
        EpisodeSubjectGraphRead(
            tenant_id=TENANT,
            subject_id=AGENT_ID,
            events=(event,),
            live_edges=(("MEMBER_OF", AGENT_ID, "org-3"),),
        )
    )
    result = await Episode360Provider(
        episode_store=FakeEpisodeStore(
            EpisodePageRead(records=(episode,), next_cursor=None, truncated=False)
        ),
        subject_relationship_reader=graph_reader,
    ).project(
        _episode_request(subject=ProjectionSubject(kind="entity", id=AGENT_ID)),
        _context(),
    )
    request = Experience360FrameRequest(
        surfaceId="episode360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="entity", id=AGENT_ID),
        requestedSlotIds=["entity_and_relationship_context"],
        includeEvidence=True,
    )

    frame = compose_experience360_frame(
        request,
        [result],
        frame_policy=Experience360PolicyDisposition(state="allowed"),
        generated_at="2026-10-17T10:01:00+00:00",
    )
    slot = frame.slots[0]

    assert slot.id == "entity_and_relationship_context"
    assert slot.state == "degraded"  # Profile360 and Relationship360 remain required bindings.
    assert frame.degradation.missingDependencies == ["profile360", "relationship360"]
    assert "projection_result_missing" in slot.reasonCodes
    episode_provenance = next(
        item for item in slot.provenance if item.projectionId == "episode360"
    )
    assert episode_provenance.sectionId == "episode_context"
    assert episode_provenance.canonicalAuthorityRefs == ["episode_facts", "graph"]
    assert [ref.id for ref in episode_provenance.evidenceRefs] == ["graph-mutation-19"]


async def test_entity_relationship_context_stays_unknown_without_exact_episode_subject() -> None:
    graph_reader = FakeEpisodeSubjectRelationshipReader(
        EpisodeSubjectGraphRead(
            tenant_id=TENANT,
            subject_id=AGENT_ID,
            live_edges=(("MEMBER_OF", AGENT_ID, "org-4"),),
        )
    )
    store = FakeEpisodeStore(EpisodePageRead(records=(), next_cursor=None, truncated=False))

    result = await Episode360Provider(
        episode_store=store,
        subject_relationship_reader=graph_reader,
    ).project(
        _episode_request(subject=ProjectionSubject(kind="entity", id=AGENT_ID)),
        _context(),
    )

    context = _section(result, "episode_context")
    assert graph_reader.calls == []
    assert context.state == "unknown"
    assert context.content["subject"] is None
    assert context.content["reason"] == "episode_subject_record_not_found"
    assert "episode_subject_record_not_found" in result.degradedReasons


async def test_entity_relationship_context_rejects_ambiguous_subject_kinds() -> None:
    store = FakeEpisodeStore(
        EpisodePageRead(
            records=(
                _episode(episode_id="agent-subject", subject_kind="agent"),
                _episode(episode_id="user-subject", subject_kind="user"),
            ),
            next_cursor=None,
            truncated=False,
        )
    )
    graph_reader = FakeEpisodeSubjectRelationshipReader(
        EpisodeSubjectGraphRead(
            tenant_id=TENANT,
            subject_id=AGENT_ID,
            live_edges=(("MEMBER_OF", AGENT_ID, "org-5"),),
        )
    )

    result = await Episode360Provider(
        episode_store=store,
        subject_relationship_reader=graph_reader,
    ).project(
        _episode_request(subject=ProjectionSubject(kind="entity", id=AGENT_ID)),
        _context(),
    )

    context = _section(result, "episode_context")
    assert graph_reader.calls == []
    assert context.state == "unknown"
    assert context.content["reason"] == "episode_subject_kind_ambiguous"
    assert context.content["relationshipEvidenceRefs"] == []
    assert "episode_subject_kind_ambiguous" in result.degradedReasons


async def test_campaign_subject_does_not_bind_entity_graph_history() -> None:
    campaign_id = "ba0c6e04-bc15-4bc3-bc10-ef5a9cf8170d"
    graph_reader = FakeEpisodeSubjectRelationshipReader(
        EpisodeSubjectGraphRead(
            tenant_id=TENANT,
            subject_id=campaign_id,
            live_edges=(("ACQUIRED_VIA", "profile-1", campaign_id),),
        )
    )
    result = await Episode360Provider(
        episode_store=FakeEpisodeStore(
            EpisodePageRead(
                records=(
                    _episode(
                        episode_id="campaign-episode-1",
                        # EntityRef has no campaign kind. Reusing an entity ID
                        # must not turn that episode's graph into campaign context.
                        subject_kind="agent",
                        subject_id=campaign_id,
                    ),
                ),
                next_cursor=None,
                truncated=False,
            )
        ),
        subject_relationship_reader=graph_reader,
    ).project(
        _episode_request(subject=ProjectionSubject(kind="campaign", id=campaign_id)),
        _context(),
    )

    context = _section(result, "episode_context")
    assert graph_reader.calls == []
    assert context.state == "unknown"
    assert context.content["state"] == "unknown"
    assert context.content["reason"] == "campaign_entity_relationship_authority_unavailable"
    assert context.state != "not_applicable"
    assert context.content["subject"] is None
    assert context.content["relationshipEvidenceRefs"] == []
    assert "campaign_entity_relationship_authority_unavailable" in result.degradedReasons

    frame = compose_experience360_frame(
        Experience360FrameRequest(
            surfaceId="episode360",
            tenantId=TENANT,
            subject=ProjectionSubject(kind="campaign", id=campaign_id),
            requestedSlotIds=["entity_and_relationship_context"],
            includeEvidence=True,
        ),
        [result],
        frame_policy=Experience360PolicyDisposition(state="allowed"),
        generated_at="2026-10-17T10:01:00+00:00",
    )
    slot = frame.slots[0]
    assert slot.state == "degraded"
    assert slot.content is None
    assert frame.degradation.missingDependencies == ["campaign360"]
    assert "projection_result_missing" in slot.reasonCodes
    assert "projection_binding_subject_kind_unsupported" in slot.reasonCodes


async def test_episode_subject_graph_context_rejects_tenant_or_subject_mismatch() -> None:
    episode = _episode(episode_id="episode-graph-scope")
    graph_reader = FakeEpisodeSubjectRelationshipReader(
        EpisodeSubjectGraphRead(
            tenant_id="tenant-other",
            subject_id=AGENT_ID,
            events=(
                SubjectEvent(
                    recorded_at="2026-10-17T10:00:00+00:00",
                    ledger_offset=17,
                    kind="edge_added",
                    operation="node_versioned",
                    aggregate_type="edge",
                    aggregate_id="MEMBER_OF:agent-episode-1:org-1",
                    mutation_id="foreign-graph-mutation",
                    edge_type="MEMBER_OF",
                    from_vertex_id=AGENT_ID,
                    to_vertex_id="org-1",
                ),
            ),
            live_edges=(("MEMBER_OF", AGENT_ID, "org-1"),),
        )
    )
    store = FakeEpisodeStore(
        EpisodePageRead(records=(), next_cursor=None, truncated=False),
        direct_record=episode,
    )
    request = _episode_request(subject=ProjectionSubject(kind="episode", id=episode.episode_id))

    result = await Episode360Provider(
        episode_store=store,
        subject_relationship_reader=graph_reader,
    ).project(request, _context())

    relationship_context = _section(result, "evidence").content["subjectRelationshipContext"]
    assert relationship_context["state"] == "unknown"
    assert relationship_context["reason"] == "episode_subject_graph_scope_mismatch"
    assert relationship_context["observedRelationships"] == []
    assert relationship_context["relationshipEvidenceRefs"] == []


async def test_empty_graph_replay_does_not_claim_subject_has_no_relationships() -> None:
    episode = _episode(episode_id="episode-empty-graph-scope")
    graph_reader = FakeEpisodeSubjectRelationshipReader(
        EpisodeSubjectGraphRead(tenant_id=TENANT, subject_id=AGENT_ID)
    )
    store = FakeEpisodeStore(
        EpisodePageRead(records=(), next_cursor=None, truncated=False),
        direct_record=episode,
    )
    request = _episode_request(subject=ProjectionSubject(kind="episode", id=episode.episode_id))

    result = await Episode360Provider(
        episode_store=store,
        subject_relationship_reader=graph_reader,
    ).project(request, _context())

    relationship_context = _section(result, "evidence").content["subjectRelationshipContext"]
    assert relationship_context["coverage"] == "unknown"
    assert relationship_context["state"] == "unknown"
    assert relationship_context["reason"] == "graph_history_replay_has_no_completeness_watermark"
    assert relationship_context["observedRelationships"] == []
    assert relationship_context["relationshipEvidenceRefs"] == []


async def test_episode_subject_graph_context_does_not_use_current_edges_for_historical_request() -> None:
    episode = _episode(episode_id="episode-historical-graph-scope")
    graph_reader = FakeEpisodeSubjectRelationshipReader(
        EpisodeSubjectGraphRead(
            tenant_id=TENANT,
            subject_id=AGENT_ID,
            live_edges=(("MEMBER_OF", AGENT_ID, "org-1"),),
        )
    )
    store = FakeEpisodeStore(
        EpisodePageRead(records=(), next_cursor=None, truncated=False),
        direct_record=episode,
    )
    request = _episode_request(
        subject=ProjectionSubject(kind="episode", id=episode.episode_id),
        temporalMode="as_of",
        asOf="2026-10-17T09:00:00+00:00",
    )

    result = await Episode360Provider(
        episode_store=store,
        subject_relationship_reader=graph_reader,
    ).project(request, _context())

    assert graph_reader.calls == []
    relationship_context = _section(result, "evidence").content["subjectRelationshipContext"]
    assert relationship_context["state"] == "unknown"
    assert relationship_context["reason"] == "episode_subject_relationship_temporal_scope_unsupported"
    assert relationship_context["relationshipEvidenceRefs"] == []


async def test_missing_exact_episode_subject_is_known_empty() -> None:
    store = FakeEpisodeStore(EpisodePageRead(records=(), next_cursor=None, truncated=False))
    request = _episode_request(subject=ProjectionSubject(kind="episode", id="episode-missing"))

    result = await Episode360Provider(episode_store=store).project(request, _context())

    assert store.get_calls == [(TENANT, "episode-missing")]
    assert store.page_calls == []
    assert _section(result, "summary").state == "empty"
    assert _section(result, "summary").content["episodeCount"] == 0


async def test_truncated_episode_page_does_not_claim_known_empty() -> None:
    store = FakeEpisodeStore(
        EpisodePageRead(
            records=(_episode(episode_id="other-agent", subject_id="agent-other"),),
            next_cursor="next-page-cursor",
            truncated=True,
        )
    )
    result = await Episode360Provider(episode_store=store).project(_episode_request(), _context())

    assert all(
        _section(result, section_id).state == "unknown"
        for section_id in (
            "summary",
            "state",
            "evidence",
            "interactions",
            "outcomes",
            "timeline",
        )
    )
    assert "episode_page_truncated" in result.degradedReasons
    assert result.page.hasNextPage is True
    assert result.page.nextCursor == "next-page-cursor"
    assert result.page.totalEstimate is None
    summary = _section(result, "summary").content
    assert summary["episodeCount"] is None
    assert summary["observedEpisodeCount"] == 0
    assert summary["interactionCount"] is None
    assert summary["observedInteractionCount"] == 0
    assert _section(result, "state").content["distribution"] is None
    assert result.claims == []


async def test_truncated_episode_page_exposes_partial_rows_without_exact_aggregates() -> None:
    store = FakeEpisodeStore(
        EpisodePageRead(
            records=(_episode(),),
            next_cursor="next-page-cursor",
            truncated=True,
        )
    )
    result = await Episode360Provider(episode_store=store).project(_episode_request(), _context())

    summary = _section(result, "summary").content
    assert _section(result, "summary").state == "degraded"
    assert summary["episodeCount"] is None
    assert summary["observedEpisodeCount"] == 1
    assert summary["observedInteractionCount"] == 1
    assert summary["coverage"] == "degraded"
    assert _section(result, "timeline").content["timeline"][0]["episodeId"] == "episode-1"
    assert result.page.totalEstimate is None


async def test_unavailable_episode_store_does_not_report_zero_totals() -> None:
    provider = Episode360Provider()
    provider._load_store = lambda: None

    result = await provider.project(_episode_request(), _context())

    summary = _section(result, "summary").content
    assert _section(result, "summary").state == "missing"
    assert summary["episodeCount"] is None
    assert summary["observedEpisodeCount"] == 0
    assert summary["interactionCount"] is None
    assert result.page.totalEstimate is None


async def test_invalid_or_cross_tenant_episode_page_stays_unknown() -> None:
    store = FakeEpisodeStore(
        EpisodePageRead(
            records=(_episode(tenant_id="tenant-other"),),
            next_cursor=None,
            truncated=False,
            invalid_records=True,
        )
    )
    result = await Episode360Provider(episode_store=store).project(_episode_request(), _context())

    assert _section(result, "summary").state == "unknown"
    assert _section(result, "timeline").content["timeline"] == []
    assert "episode_page_contains_invalid_rows" in result.degradedReasons
    assert "episode_page_tenant_mismatch" in result.degradedReasons
    assert result.page.totalEstimate is None
    assert result.claims == []


async def test_journey_subject_projects_tenant_version_and_evidenced_steps() -> None:
    source = FakeJourneySource(steps=[_step(), _step(step_id="step-2", position=2)])
    result = await Episode360Provider(journey_source=source).project(_request(), _context())

    assert [section.id for section in result.sections] == list(
        INTELLIGENCE_PROJECTION_DEFINITIONS["episode360"]["outputSections"]
    )
    assert source.current_calls == [(TENANT, JOURNEY_ID)]
    assert source.step_calls[0]["tenant_id"] == TENANT
    assert source.step_calls[0]["journey_version_id"] == VERSION_ID
    assert source.step_calls[0]["limit"] == 101
    assert _section(result, "summary").content["journey"]["journeyId"] == JOURNEY_ID
    timeline = _section(result, "timeline")
    assert timeline.state == "available"
    assert [row["stepId"] for row in timeline.content["timeline"]] == ["step-1", "step-2"]
    assert timeline.content["evidenceRefs"]
    assert _section(result, "outcomes").state == "unknown"
    assert "journey_outcome_truth_join_unavailable" in _section(result, "outcomes").warnings
    assert {
        "journey_state_and_path",
        "events_and_episode_context",
        "episodes_events_and_journeys",
    }.issubset({slot_id for claim in result.claims for slot_id in claim.domainSlotIds})
    serialized = json.dumps(result.model_dump(mode="json"))
    assert "must-not-appear" not in serialized


async def test_journey_projection_drops_rows_outside_tenant_or_version_scope() -> None:
    source = FakeJourneySource(
        steps=[
            _step(),
            _step(step_id="other-tenant", tenant_id="tenant-other"),
            _step(step_id="other-version", version_id="version-other"),
        ]
    )
    result = await Episode360Provider(journey_source=source).project(_request(), _context())

    timeline = _section(result, "timeline")
    assert timeline.state == "degraded"
    assert [row["stepId"] for row in timeline.content["timeline"]] == ["step-1"]
    assert "unscoped_journey_step_rows_dropped" in result.degradedReasons
    assert result.claims == []


async def test_journey_point_in_time_request_is_unknown_until_history_read_is_supported() -> None:
    source = FakeJourneySource()
    result = await Episode360Provider(journey_source=source).project(
        _request(asOf="2026-10-16T10:00:00+00:00", temporalMode="as_of"), _context()
    )

    assert source.current_calls == []
    assert source.step_calls == []
    assert all(section.state == "unknown" for section in result.sections)
    assert "journey_temporal_mode_unsupported" in result.degradedReasons


async def test_relative_journey_request_without_range_does_not_read() -> None:
    source = FakeJourneySource()
    result = await Episode360Provider(journey_source=source).project(
        _request(temporalMode="relative"), _context()
    )

    assert source.current_calls == []
    assert source.step_calls == []
    assert "relative_time_range_not_resolved" in result.degradedReasons


async def test_repository_adapter_uses_tenant_and_versioned_step_filters() -> None:
    journeys = FakeJourneyRepository(_journey())
    steps = FakeStepRepository([_step()])
    source = RepositoryJourney360Source(journeys=journeys, steps=steps)

    journey = await source.current_journey(tenant_id=TENANT, journey_id=JOURNEY_ID)
    result = await source.steps(
        tenant_id=TENANT,
        journey_id=JOURNEY_ID,
        journey_version_id=VERSION_ID,
        limit=25,
        cursor="cursor-1",
        after=None,
        before=None,
    )

    assert journeys.calls == [(TENANT, JOURNEY_ID)]
    assert journey == _journey()
    assert steps.calls == [
        {
            "tenant_id": TENANT,
            "version_id": VERSION_ID,
            "limit": 25,
            "cursor": "cursor-1",
            "after": None,
            "before": None,
        }
    ]
    assert result == [_step()]
