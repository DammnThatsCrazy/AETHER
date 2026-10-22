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
        "account_id": "account-1",
        "agent_id": None,
        "campaign_ids": ["campaign-1"],
        "channel_sequence": ["web", "email"],
        "conversion_ids": ["conversion-1"],
        "entry_touchpoint_id": "touchpoint-entry",
        "exit_touchpoint_id": "touchpoint-exit",
        "touchpoint_ids": ["touchpoint-entry", "touchpoint-exit"],
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


class FakeJourneyTouchpointSource:
    def __init__(self, rows: dict[str, dict] | None = None) -> None:
        self.rows = {} if rows is None else rows
        self.calls: list[tuple[str, str]] = []

    async def get(self, tenant_id: str, touchpoint_id: str):
        self.calls.append((tenant_id, touchpoint_id))
        return self.rows.get(touchpoint_id)


class FakeJourneyConversionSource:
    def __init__(self, rows: dict[str, dict] | None = None) -> None:
        self.rows = {} if rows is None else rows
        self.calls: list[tuple[str, str]] = []

    async def get(self, tenant_id: str, conversion_id: str):
        self.calls.append((tenant_id, conversion_id))
        return self.rows.get(conversion_id)


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
    summary = _section(result, "summary")
    assert summary.content["freshness"] == {
        "state": "unknown",
        "evaluation": "not_performed",
        "reason": "episode_store_freshness_watermark_not_available",
    }
    assert summary.content["policy"]["state"] == "unknown"
    assert summary.content["policy"]["evaluation"] == "not_performed"
    required_slots = summary.content["requiredSlotCoverage"]
    assert set(required_slots) == {
        "episode_summary",
        "timeline",
        "participants",
        "sessions",
        "touchpoints",
        "communications",
        "agent_handoffs",
        "conversion_events",
        "attribution_links",
        "risk_flags",
        "evidence_trace",
    }
    assert required_slots["episode_summary"]["state"] == "available"
    assert required_slots["episode_summary"]["evidenceRefs"]
    assert required_slots["timeline"]["state"] == "degraded"
    assert required_slots["participants"]["state"] == "degraded"
    assert required_slots["sessions"]["state"] == "unknown"
    assert required_slots["touchpoints"]["state"] == "unknown"
    assert required_slots["communications"]["state"] == "unknown"
    assert required_slots["agent_handoffs"]["state"] == "unknown"
    assert required_slots["conversion_events"]["state"] == "unknown"
    assert required_slots["attribution_links"]["state"] == "unknown"
    assert required_slots["risk_flags"]["state"] == "unknown"
    assert required_slots["evidence_trace"]["state"] == "degraded"
    assert _section(result, "timeline").state == "degraded"
    assert _section(result, "interactions").state == "degraded"
    assert _section(result, "outcomes").state == "degraded"
    assert {slot for claim in result.claims for slot in claim.domainSlotIds} == {
        "episode_summary",
        "timeline",
        "participants",
        "evidence_trace",
    }


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
    assert {ref["id"] for ref in evidence["evidence"]} == {
        "episode-with-graph-subject",
        "evidence-episode-with-graph-subject",
    }
    assert {
        ref.id for claim in result.claims for ref in claim.evidenceRefs
    } == {
        "episode-with-graph-subject",
        "evidence-episode-with-graph-subject",
    }
    assert all(
        ref.source != "graph_mutation_ledger"
        for claim in result.claims
        for ref in claim.evidenceRefs
    )
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
    source = FakeJourneySource(
        steps=[
            _step(agent_id=AGENT_ID, actor_type="agent"),
            _step(step_id="step-2", position=2),
        ]
    )
    result = await Episode360Provider(
        journey_source=source,
        touchpoint_source=FakeJourneyTouchpointSource({}),
    ).project(_request(), _context())

    assert [section.id for section in result.sections] == list(
        INTELLIGENCE_PROJECTION_DEFINITIONS["episode360"]["outputSections"]
    )
    assert source.current_calls == [(TENANT, JOURNEY_ID)]
    assert source.step_calls[0]["tenant_id"] == TENANT
    assert source.step_calls[0]["journey_version_id"] == VERSION_ID
    assert source.step_calls[0]["limit"] == 101
    assert _section(result, "summary").content["journey"]["journeyId"] == JOURNEY_ID
    summary = _section(result, "summary")
    slot_coverage = summary.content["requiredSlotCoverage"]
    assert set(slot_coverage) == {
        "journey_summary",
        "stages",
        "episodes",
        "touchpoints",
        "agent_interventions",
        "communications",
        "dropoffs",
        "conversions",
        "attribution",
        "recommended_actions",
        "evidence_trace",
    }
    assert slot_coverage["journey_summary"]["state"] == "available"
    assert slot_coverage["journey_summary"]["evidenceRefs"][0]["id"] == VERSION_ID
    assert slot_coverage["stages"]["state"] == "partial"
    assert slot_coverage["stages"]["coverage"] == "observed_role_markers"
    stage_observations = _section(result, "timeline").content["stageObservations"]
    assert stage_observations["stageTaxonomyState"] == "unknown"
    assert [item["journeyRole"] for item in stage_observations["stageObservations"]] == [
        "entry",
        "entry",
    ]
    assert [item["stepId"] for item in stage_observations["stageObservations"]] == [
        "step-1",
        "step-2",
    ]
    assert all(item["evidenceRefs"] for item in stage_observations["stageObservations"])
    stage_claims = [
        claim for claim in result.claims if "stages" in (claim.domainSlotIds or [])
    ]
    assert [claim.kind for claim in stage_claims] == [
        "explicit_journey_role_marker",
        "explicit_journey_role_marker",
    ]

    frame = compose_experience360_frame(
        Experience360FrameRequest(
            surfaceId="journey360",
            tenantId=TENANT,
            subject=ProjectionSubject(kind="journey", id=JOURNEY_ID),
            requestedSlotIds=["stages"],
            includeEvidence=True,
        ),
        [result],
        frame_policy=Experience360PolicyDisposition(state="allowed"),
        generated_at="2026-10-22T10:01:00+00:00",
    )
    frame_stage_slot = frame.slots[0]
    assert frame_stage_slot.state == "degraded"
    assert {ref.id for ref in frame_stage_slot.evidenceRefs} == {"step-1", "step-2"}
    assert all("stage taxonomy and stage completeness remain unknown" in claim.claims[0]
               for claim in frame_stage_slot.claims)
    assert slot_coverage["episodes"]["reason"] == (
        "episode_record_contract_has_no_typed_journey_subject_reference"
    )
    assert slot_coverage["touchpoints"]["state"] == "unknown"
    assert slot_coverage["agent_interventions"]["state"] == "degraded"
    assert slot_coverage["agent_interventions"]["evidenceRefs"][0]["id"] == "step-1"
    assert slot_coverage["communications"]["state"] == "unknown"
    assert slot_coverage["dropoffs"]["state"] == "unknown"
    assert slot_coverage["conversions"]["state"] == "unknown"
    assert slot_coverage["conversions"]["evidenceRefs"][0]["id"] == VERSION_ID
    assert slot_coverage["attribution"]["state"] == "unknown"
    assert slot_coverage["recommended_actions"]["state"] == "unknown"
    assert slot_coverage["evidence_trace"]["state"] == "degraded"
    assert {ref["id"] for ref in slot_coverage["evidence_trace"]["evidenceRefs"]} >= {
        VERSION_ID,
        "step-1",
        "step-2",
    }
    assert summary.content["continuity"]["state"] == "unknown"
    assert summary.content["freshness"]["state"] == "unknown"
    assert summary.content["freshness"]["evaluation"] == "not_performed"
    assert summary.content["policy"]["state"] == "unknown"
    assert summary.content["provenance"]["state"] == "partial"
    timeline = _section(result, "timeline")
    assert timeline.state == "available"
    assert [row["stepId"] for row in timeline.content["timeline"]] == ["step-1", "step-2"]
    assert timeline.content["evidenceRefs"]
    assert timeline.content["touchpointReferences"]["touchpointIds"] == [
        "touchpoint-entry",
        "touchpoint-exit",
    ]
    assert timeline.content["touchpointReferences"]["state"] == "unknown"
    assert timeline.content["touchpointReferences"]["evidenceRefs"] == []
    assert timeline.content["touchpointReferences"]["journeyVersionEvidenceRefs"][0]["id"] == (
        VERSION_ID
    )
    interactions = _section(result, "interactions")
    agent_activities = interactions.content["agentActivities"]
    assert len(agent_activities) == 1
    assert agent_activities[0]["stepId"] == "step-1"
    assert agent_activities[0]["agentId"] == AGENT_ID
    assert agent_activities[0]["actorType"] == "agent"
    assert agent_activities[0]["evidenceRefs"][0]["id"] == "step-1"
    assert _section(result, "outcomes").state == "unknown"
    assert _section(result, "outcomes").content["recordedConversionIds"] == ["conversion-1"]
    assert "journey_conversion_row_missing" in _section(result, "outcomes").warnings
    assert {
        "agent_interventions",
        "evidence_trace",
        "journey_summary",
        "stages",
        "touchpoints",
    } == {slot_id for claim in result.claims for slot_id in claim.domainSlotIds}
    serialized = json.dumps(result.model_dump(mode="json"))
    assert "must-not-appear" not in serialized


@pytest.mark.parametrize("is_current", [False, None])
async def test_journey_subject_requires_explicit_current_version_marker(is_current) -> None:
    source = FakeJourneySource(journey=_journey(is_current=is_current))

    result = await Episode360Provider(journey_source=source).project(_request(), _context())

    summary = _section(result, "summary")
    coverage = summary.content["requiredSlotCoverage"]
    assert summary.state == "unknown"
    assert coverage["journey_summary"]["reason"] == "journey_current_version_not_proven"
    assert all(slot["state"] == "unknown" for slot in coverage.values())
    assert source.current_calls == [(TENANT, JOURNEY_ID)]
    assert source.step_calls == []
    assert result.claims == []
    assert result.degradedReasons == ["journey_current_version_not_proven"]


async def test_journey_stage_slot_reports_empty_only_for_complete_unmarked_step_inventory() -> None:
    source = FakeJourneySource(steps=[_step(journey_role=None)])
    result = await Episode360Provider(
        journey_source=source,
        touchpoint_source=FakeJourneyTouchpointSource({}),
    ).project(_request(), _context())

    stage_slot = _section(result, "summary").content["requiredSlotCoverage"]["stages"]
    stage_observations = _section(result, "timeline").content["stageObservations"]
    assert stage_slot["state"] == "empty"
    assert stage_slot["coverage"] == "complete_for_explicit_role_markers"
    assert stage_slot["reason"] == (
        "complete_current_journey_step_inventory_has_no_explicit_role_markers"
    )
    assert stage_observations["stageObservations"] == []
    assert [ref["id"] for ref in stage_observations["evidenceRefs"]] == ["step-1"]


async def test_journey_stage_slot_keeps_unmarked_bounded_window_unknown() -> None:
    source = FakeJourneySource(steps=[_step(journey_role=None)])
    result = await Episode360Provider(
        journey_source=source,
        touchpoint_source=FakeJourneyTouchpointSource({}),
    ).project(
        _request(timeRange={"from": "2026-10-16T09:00:00+00:00", "to": "2026-10-16T10:00:00+00:00"}),
        _context(),
    )

    stage_slot = _section(result, "summary").content["requiredSlotCoverage"]["stages"]
    stage_observations = _section(result, "timeline").content["stageObservations"]
    assert stage_slot["state"] == "unknown"
    assert stage_slot["coverage"] == "unknown"
    assert stage_slot["reason"] == (
        "incomplete_journey_step_inventory_cannot_establish_role_marker_absence"
    )
    assert stage_observations["inventoryComplete"] is False
    assert stage_observations["stageObservations"] == []
    assert stage_observations["evidenceRefs"] == []


async def test_journey_stage_marker_without_step_evidence_is_degraded() -> None:
    source = FakeJourneySource(steps=[_step(step_id=None, journey_role="handoff")])
    result = await Episode360Provider(
        journey_source=source,
        touchpoint_source=FakeJourneyTouchpointSource({}),
    ).project(_request(), _context())

    stage_slot = _section(result, "summary").content["requiredSlotCoverage"]["stages"]
    stage_observations = _section(result, "timeline").content["stageObservations"]
    assert stage_slot["state"] == "degraded"
    assert stage_slot["reason"] == "journey_role_marker_invalid_or_missing_exact_step_evidence"
    assert stage_observations["stageObservations"] == []
    assert stage_observations["evidenceRefs"] == []


async def test_journey_conversion_and_touchpoint_references_do_not_claim_outcome_or_attribution() -> (
    None
):
    source = FakeJourneySource(
        journey=_journey(
            conversion_ids=["conversion-recorded"],
            touchpoint_ids=["touchpoint-recorded"],
            entry_touchpoint_id=None,
            exit_touchpoint_id=None,
        ),
        steps=[_step(conversion_id="conversion-recorded")],
    )
    result = await Episode360Provider(journey_source=source).project(_request(), _context())

    outcomes = _section(result, "outcomes")
    assert outcomes.state == "unknown"
    assert outcomes.content["recordedConversionIds"] == ["conversion-recorded"]
    assert outcomes.content["conversionTruthState"] == "unknown"
    assert outcomes.content["attributionState"] == "unknown"
    assert outcomes.content["journeyVersionEvidenceRefs"][0]["id"] == VERSION_ID
    touchpoints = _section(result, "timeline").content["touchpointReferences"]
    assert touchpoints["touchpointIds"] == ["touchpoint-recorded"]
    assert touchpoints["journeyVersionEvidenceRefs"][0]["id"] == VERSION_ID


async def test_journey_conversion_joins_exact_canonical_row_with_evidence() -> None:
    source = FakeJourneySource(
        journey=_journey(conversion_ids=["conversion-1"], touchpoint_ids=[]),
        steps=[],
    )
    conversions = FakeJourneyConversionSource(
        {
            "conversion-1": {
                "tenant_id": TENANT,
                "conversion_id": "conversion-1",
                "conversion_type": "purchase",
                "conversion_status": "confirmed",
                "occurred_at": "2026-10-16T09:30:00+00:00",
                "observed_at": "2026-10-16T09:31:00+00:00",
                "gross_value": "100.00",
                "profile_id": "private-profile-id",
            }
        }
    )
    result = await Episode360Provider(
        journey_source=source,
        touchpoint_source=FakeJourneyTouchpointSource({}),
        conversion_source=conversions,
    ).project(_request(), _context())

    assert conversions.calls == [(TENANT, "conversion-1")]
    coverage = _section(result, "summary").content["requiredSlotCoverage"]["conversions"]
    assert coverage["state"] == "available"
    assert {ref["id"] for ref in coverage["evidenceRefs"]} == {VERSION_ID, "conversion-1"}
    outcomes = _section(result, "outcomes")
    assert outcomes.state == "available"
    assert outcomes.content["conversionTruthState"] == "available"
    assert outcomes.content["conversions"][0]["conversionType"] == "purchase"
    assert outcomes.content["attributionState"] == "unknown"
    claim = next(item for item in result.claims if item.kind == "canonical_journey_conversion")
    assert claim.domainSlotIds == ["conversions"]
    assert {ref.id for ref in claim.evidenceRefs} == {VERSION_ID, "conversion-1"}
    assert "private-profile-id" not in json.dumps(result.model_dump(mode="json"))


async def test_journey_conversion_rejects_foreign_tenant_row() -> None:
    source = FakeJourneySource(journey=_journey(conversion_ids=["conversion-1"]), steps=[])
    conversions = FakeJourneyConversionSource(
        {
            "conversion-1": {
                "tenant_id": "foreign-tenant",
                "conversion_id": "conversion-1",
                "observed_at": "2026-10-16T09:31:00+00:00",
            }
        }
    )
    result = await Episode360Provider(
        journey_source=source,
        conversion_source=conversions,
    ).project(_request(), _context())

    assert _section(result, "summary").content["requiredSlotCoverage"]["conversions"]["state"] == "unknown"
    assert not any(item.domainSlotIds == ["conversions"] for item in result.claims)
    assert "foreign-tenant" not in json.dumps(result.model_dump(mode="json"))


async def test_journey_exact_touchpoint_rows_are_private_evidenced_and_slot_attributed() -> None:
    touchpoint_source = FakeJourneyTouchpointSource(
        {
            "touchpoint-entry": {
                "tenant_id": TENANT,
                "touchpoint_id": "touchpoint-entry",
                "occurred_at": "2026-10-16T09:00:00+00:00",
                "touchpoint_type": "email_click",
                "interaction_type": "click",
                "channel": "email",
                "source": "newsletter",
                "medium": "email",
                "source_class": "owned",
                "traffic_origin": "direct",
                "economic_class": "none",
                "channel_family": "email",
                "entry_method": "link",
                "proof_level": "observed",
                "actor_type": "user",
                "journey_role": "entry",
                "campaign_id": "campaign-1",
                "agent_id": None,
                "attribution_eligible": True,
                "verification_level": "verified",
                # These canonical fields must not leak through the Journey360 projection.
                "profile_id": "private-profile",
                "account_id": "private-account",
                "wallet_id": "private-wallet",
                "device_id": "private-device",
                "referrer": "https://private.example/path",
                "landing_url": "https://private.example/landing",
                "properties": {"private_payload": "must-not-appear"},
                "provenance": {"private_payload": "must-not-appear"},
            },
            "touchpoint-exit": {
                "tenant_id": TENANT,
                "touchpoint_id": "touchpoint-exit",
                "occurred_at": "2026-10-16T10:00:00+00:00",
                "touchpoint_type": "web_event",
                "interaction_type": "page_view",
                "channel": "web",
                "journey_role": "exit",
            },
        }
    )

    result = await Episode360Provider(
        journey_source=FakeJourneySource(),
        touchpoint_source=touchpoint_source,
    ).project(_request(), _context())

    assert touchpoint_source.calls == [
        (TENANT, "touchpoint-entry"),
        (TENANT, "touchpoint-exit"),
    ]
    timeline = _section(result, "timeline")
    touchpoint_slot = _section(result, "summary").content["requiredSlotCoverage"]["touchpoints"]
    assert touchpoint_slot["state"] == "available"
    assert touchpoint_slot["coverage"] == "complete"
    assert [ref["id"] for ref in touchpoint_slot["evidenceRefs"]] == [
        "touchpoint-entry",
        "touchpoint-exit",
    ]
    touchpoints = timeline.content["touchpointReferences"]
    assert touchpoints["state"] == "available"
    assert touchpoints["coverage"] == "complete"
    assert touchpoints["count"] == 2
    assert [row["touchpointId"] for row in touchpoints["touchpoints"]] == [
        "touchpoint-entry",
        "touchpoint-exit",
    ]
    assert touchpoints["touchpoints"][0]["sourceClass"] == "owned"
    assert touchpoints["touchpoints"][0]["attributionEligible"] is True
    assert [ref["id"] for ref in touchpoints["evidenceRefs"]] == [
        "touchpoint-entry",
        "touchpoint-exit",
    ]
    assert {"touchpoint-entry", "touchpoint-exit"}.issubset(
        {ref["id"] for ref in timeline.content["evidenceRefs"]}
    )

    touchpoint_claims = [
        claim for claim in result.claims if claim.kind == "server_recorded_journey_touchpoint"
    ]
    assert [claim.id.rsplit(":", 1)[-1] for claim in touchpoint_claims] == [
        "touchpoint-entry",
        "touchpoint-exit",
    ]
    assert [ref.id for ref in touchpoint_claims[0].evidenceRefs] == [
        VERSION_ID,
        "touchpoint-entry",
    ]
    assert touchpoint_claims[0].domainSlotIds == ["evidence_trace", "touchpoints"]
    serialized = json.dumps(result.model_dump(mode="json"))
    for private_value in (
        "private-profile",
        "private-account",
        "private-wallet",
        "private-device",
        "private.example",
        "must-not-appear",
    ):
        assert private_value not in serialized


async def test_journey_touchpoint_source_gaps_stay_degraded_or_unknown() -> None:
    source = FakeJourneySource(
        journey=_journey(
            touchpoint_ids=["touchpoint-present", "touchpoint-missing"],
            entry_touchpoint_id=None,
            exit_touchpoint_id=None,
        )
    )
    touchpoint_source = FakeJourneyTouchpointSource(
        {
            "touchpoint-present": {
                "tenant_id": TENANT,
                "touchpoint_id": "touchpoint-present",
                "occurred_at": "2026-10-16T09:00:00+00:00",
                "channel": "web",
            },
            "touchpoint-missing": {
                "tenant_id": "tenant-other",
                "touchpoint_id": "touchpoint-missing",
                "channel": "email",
            },
        }
    )

    result = await Episode360Provider(
        journey_source=source,
        touchpoint_source=touchpoint_source,
    ).project(_request(), _context())

    touchpoints = _section(result, "timeline").content["touchpointReferences"]
    assert touchpoints["state"] == "degraded"
    assert touchpoints["coverage"] == "partial"
    assert touchpoints["count"] is None
    assert touchpoints["observedCount"] == 1
    assert touchpoints["missingTouchpointIds"] == ["touchpoint-missing"]
    assert "journey_touchpoint_scope_mismatch" in touchpoints["warnings"]
    assert [row["touchpointId"] for row in touchpoints["touchpoints"]] == [
        "touchpoint-present"
    ]
    touchpoint_claims = [
        claim for claim in result.claims if claim.kind == "server_recorded_journey_touchpoint"
    ]
    assert [claim.id.rsplit(":", 1)[-1] for claim in touchpoint_claims] == [
        "touchpoint-present"
    ]
    assert touchpoint_claims[0].evidenceRefs[-1].id == "touchpoint-present"

    unknown_result = await Episode360Provider(
        journey_source=FakeJourneySource(
            journey=_journey(
                touchpoint_ids=["touchpoint-absent"],
                entry_touchpoint_id=None,
                exit_touchpoint_id=None,
            )
        ),
        touchpoint_source=FakeJourneyTouchpointSource(),
    ).project(_request(), _context())
    unknown_touchpoints = _section(unknown_result, "timeline").content["touchpointReferences"]
    assert unknown_touchpoints["state"] == "unknown"
    assert unknown_touchpoints["coverage"] == "unknown"
    assert unknown_touchpoints["count"] is None
    assert unknown_touchpoints["observedCount"] == 0
    assert unknown_touchpoints["missingTouchpointIds"] == ["touchpoint-absent"]


async def test_journey_touchpoints_preserve_partial_references_when_list_is_missing() -> None:
    touchpoint_source = FakeJourneyTouchpointSource(
        {
            "touchpoint-entry": {
                "tenant_id": TENANT,
                "touchpoint_id": "touchpoint-entry",
                "occurred_at": "2026-10-16T09:00:00+00:00",
            },
            "touchpoint-exit": {
                "tenant_id": TENANT,
                "touchpoint_id": "touchpoint-exit",
                "occurred_at": "2026-10-16T10:00:00+00:00",
            },
        }
    )
    journey = _journey(touchpoint_ids=None)
    result = await Episode360Provider(
        journey_source=FakeJourneySource(journey=journey),
        touchpoint_source=touchpoint_source,
    ).project(_request(), _context())

    touchpoints = _section(result, "timeline").content["touchpointReferences"]
    assert touchpoints["state"] == "degraded"
    assert touchpoints["coverage"] == "partial"
    assert touchpoints["touchpointIds"] == ["touchpoint-entry", "touchpoint-exit"]
    assert touchpoints["observedCount"] == 2
    assert "journey_touchpoint_reference_list_unavailable" in touchpoints["warnings"]


async def test_journey_touchpoint_list_disagreement_degrades_completeness() -> None:
    journey = _journey(
        touchpoint_ids=["touchpoint-entry"],
        entry_touchpoint_id="touchpoint-entry",
        exit_touchpoint_id="touchpoint-exit",
    )
    touchpoint_source = FakeJourneyTouchpointSource(
        {
            touchpoint_id: {
                "tenant_id": TENANT,
                "touchpoint_id": touchpoint_id,
                "occurred_at": "2026-10-16T09:00:00+00:00",
            }
            for touchpoint_id in ("touchpoint-entry", "touchpoint-exit")
        }
    )

    result = await Episode360Provider(
        journey_source=FakeJourneySource(journey=journey),
        touchpoint_source=touchpoint_source,
    ).project(_request(), _context())

    touchpoints = _section(result, "timeline").content["touchpointReferences"]
    assert touchpoints["state"] == "degraded"
    assert touchpoints["coverage"] == "partial"
    assert touchpoints["observedCount"] == 2
    assert "journey_touchpoint_endpoint_reference_not_in_list" in touchpoints["warnings"]


async def test_journey_episode_context_stays_unknown_without_typed_episode_join() -> None:
    coincident_profile_episode = _episode(
        episode_id="same-id-user-episode",
        subject_kind="user",
        subject_id=JOURNEY_ID,
    )
    store = FakeEpisodeStore(
        EpisodePageRead(
            records=(coincident_profile_episode,),
            next_cursor=None,
            truncated=False,
        )
    )
    result = await Episode360Provider(
        episode_store=store,
        journey_source=FakeJourneySource(),
    ).project(_request(), _context())

    episode_context = _section(result, "episode_context")
    assert episode_context.state == "unknown"
    assert episode_context.content["episodeCount"] is None
    assert episode_context.content["episodes"] == []
    assert (
        episode_context.content["reason"]
        == "episode_record_contract_has_no_typed_journey_subject_reference"
    )
    assert store.page_calls == []
    assert _section(result, "evidence").content["coverage"] == "partial"


async def test_journey_step_evidence_missing_degrades_and_does_not_misattribute_claims() -> None:
    source = FakeJourneySource(
        steps=[
            _step(step_id=None, activity_id="activity-without-step-id"),
            _step(step_id="step-2", position=2),
        ]
    )
    result = await Episode360Provider(journey_source=source).project(_request(), _context())

    timeline = _section(result, "timeline")
    assert timeline.state == "degraded"
    assert "journey_step_evidence_missing" in result.degradedReasons
    assert _section(result, "evidence").content["coverage"] == "partial"
    assert [claim.id for claim in result.claims] == [
        f"episode360:{JOURNEY_ID}:{VERSION_ID}:journey-version",
        f"episode360:{JOURNEY_ID}:{VERSION_ID}:step:step-2",
        f"episode360:{JOURNEY_ID}:{VERSION_ID}:stage-marker:step-2",
    ]
    assert result.claims[1].evidenceRefs[0].id == "step-2"


async def test_journey_lookahead_row_keeps_truncation_visible_when_out_of_scope() -> None:
    source = FakeJourneySource(
        steps=[
            _step(),
            _step(step_id="other-version", version_id="other-version"),
        ]
    )
    request = _request(page={"limit": 1})

    result = await Episode360Provider(journey_source=source).project(request, _context())

    assert source.step_calls[0]["limit"] == 2
    assert _section(result, "timeline").state == "degraded"
    assert "journey_steps_truncated" in result.degradedReasons


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
