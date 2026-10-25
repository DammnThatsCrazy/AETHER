"""Episode360 exact observation-reference joins and partial-state semantics."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from graph.operational_intelligence.models import EntityRef, EvidenceRef  # noqa: E402
from journeys.measurement.episodes.related_authorities import (  # noqa: E402
    AuthorityFactRead,
    EpisodeObservationReferenceRecord,
)
from journeys.measurement.episodes.provider import (  # noqa: E402
    Episode360Provider,
    RepositoryEpisodeObservationSource,
)
from shared.backend_interpretation.primitives import EpisodeRecord  # noqa: E402
from shared.intelligence_projections.contracts import (  # noqa: E402
    ProjectionContext,
    ProjectionRequest,
    ProjectionSubject,
)

TENANT = "tenant-episode360-observation-join"
EPISODE_ID = "episode-observation-join-1"
SOURCE_NAMESPACE = "site:episode-observation-test"


def _episode(observation_ids: list[str]) -> EpisodeRecord:
    return EpisodeRecord(
        episode_id=EPISODE_ID,
        tenant_id=TENANT,
        subject=EntityRef(kind="agent", id="agent-1"),
        kind="agent_execution",
        observation_ids=observation_ids,
    )


def _observation(
    observation_id: str,
    *,
    tenant_id: str = TENANT,
    status: str = "classified",
    source_type: str = "agent_tool_observation",
    occurred_at: str = "2026-10-20T12:00:00+00:00",
) -> dict[str, str]:
    return {
        "record_id": observation_id,
        "observation_id": observation_id,
        "tenant_id": tenant_id,
        "status": status,
        "source_type": source_type,
        "source_namespace": SOURCE_NAMESPACE,
        "source_event_id": f"event-{observation_id}",
        "occurred_at": occurred_at,
        "received_at": occurred_at,
        "processed_at": occurred_at,
        "content": "private event payload must not be projected",
        "actor_ref": "private-actor-id-must-not-be-projected",
    }


class FakeEpisodeStore:
    def __init__(self, episode: EpisodeRecord) -> None:
        self.episode = episode

    async def get(self, tenant_id: str, episode_id: str) -> EpisodeRecord | None:
        if tenant_id == self.episode.tenant_id and episode_id == self.episode.episode_id:
            return self.episode
        return None

    async def list_page_by_tenant(self, *args, **kwargs):
        raise AssertionError("exact episode subject read should not page tenant episodes")


class FakeObservationSource:
    def __init__(self, rows: list[dict[str, str]] | None = None, *, error=None) -> None:
        self.rows = [] if rows is None else rows
        self.error = error
        self.calls: list[tuple[str, dict[str, str]]] = []

    async def find_by_namespaced_ids(
        self, tenant_id: str, namespaces_by_id: dict[str, str]
    ):
        self.calls.append((tenant_id, dict(namespaces_by_id)))
        if self.error is not None:
            raise self.error
        return self.rows


def _typed_reference(
    observation_id: str, *, occurred_at: str = "2026-10-20T12:00:00+00:00"
) -> EpisodeObservationReferenceRecord:
    moment = datetime.fromisoformat(occurred_at)
    uri = f"store://silver_semantic_observations/{TENANT}:{observation_id}"
    source_event_id = f"event-{observation_id}"
    return EpisodeObservationReferenceRecord(
        record_id=f"episode-observation-link-{observation_id}",
        tenant_id=TENANT,
        episode_id=EPISODE_ID,
        observation_id=observation_id,
        source_namespace=SOURCE_NAMESPACE,
        source_event_id=source_event_id,
        occurred_at=moment,
        received_at=moment,
        recorded_at=moment,
        linked_at=moment,
        evidence_refs=[
            EvidenceRef(
                id=observation_id,
                type="event",
                source="semantic_intelligence.silver_semantic_observations",
                observedAt=occurred_at,
                uri=uri,
            ),
            EvidenceRef(
                id=source_event_id,
                type="event",
                source="semantic_intelligence.silver_semantic_observations.source_event_id",
                observedAt=occurred_at,
                uri=f"{uri}/source-event/{source_event_id}",
            ),
            EvidenceRef(
                id=observation_id,
                type="event",
                source="semantic_intelligence.silver_semantic_observations.received_at",
                observedAt=occurred_at,
                uri=f"{uri}/receipt",
            ),
        ],
    )


class FakeEpisodeAuthoritySource:
    def __init__(self, references: list[EpisodeObservationReferenceRecord]) -> None:
        self.references = references

    async def list_for_subject(
        self, tenant_id: str, subject_kind: str, subject_id: str,
        record_type: str, *, limit: int,
    ) -> AuthorityFactRead:
        assert (tenant_id, subject_kind, subject_id, record_type) == (
            TENANT, "episode", EPISODE_ID, "episode_observation_reference"
        )
        return AuthorityFactRead(
            records=tuple(
                record.model_dump(mode="json") for record in self.references[:limit]
            )
        )


class FakeTouchpointSource:
    def __init__(self, rows: dict[str, dict[str, str]] | None = None) -> None:
        self.rows = {} if rows is None else rows
        self.calls: list[tuple[str, str]] = []

    async def get(self, tenant_id: str, touchpoint_id: str):
        self.calls.append((tenant_id, touchpoint_id))
        return self.rows.get(touchpoint_id)


class FakeFactRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []

    async def find_by_ids(self, tenant_id: str, observation_ids: list[str]):
        self.calls.append((tenant_id, list(observation_ids)))
        return []


def _request() -> ProjectionRequest:
    return ProjectionRequest(
        projectionId="episode360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="episode", id=EPISODE_ID),
        includeClaims=True,
    )


def _context() -> ProjectionContext:
    return ProjectionContext(
        projectionId="episode360",
        tenantId=TENANT,
        registryState="in_flight",
        dependencyState=[],
        warnings=[],
    )


def _section(result, section_id: str):
    return next(section for section in result.sections if section.id == section_id)


@pytest.mark.asyncio
async def test_episode_observation_join_uses_exact_tenant_ids_and_preserves_partial_contract():
    observation_source = FakeObservationSource(
        [
            _observation("obs-later", occurred_at="2026-10-20T12:05:00+00:00"),
            _observation("obs-earlier", occurred_at="2026-10-20T12:00:00+00:00"),
        ]
    )
    episode = _episode(["obs-later", "obs-earlier"])
    result = await Episode360Provider(
        episode_store=FakeEpisodeStore(episode),
        observation_source=observation_source,
        episode_authority_source=FakeEpisodeAuthoritySource([
            _typed_reference("obs-later", occurred_at="2026-10-20T12:05:00+00:00"),
            _typed_reference("obs-earlier", occurred_at="2026-10-20T12:00:00+00:00"),
        ]),
    ).project(_request(), _context())

    assert observation_source.calls == [
        (TENANT, {"obs-later": SOURCE_NAMESPACE, "obs-earlier": SOURCE_NAMESPACE})
    ]
    interactions = _section(result, "interactions").content
    observation_refs = interactions["observationReferences"]
    assert observation_refs["state"] == "available"
    assert observation_refs["coverage"] == "recorded_episode_ids_only"
    assert observation_refs["resolvedCount"] == 2
    assert [row["observationId"] for row in observation_refs["observations"]] == [
        "obs-later",
        "obs-earlier",
    ]
    assert observation_refs["policy"]["state"] == "unknown"
    assert observation_refs["freshness"]["state"] == "unknown"

    timeline = _section(result, "timeline").content
    assert [row["observationId"] for row in timeline["observationTimeline"]] == [
        "obs-earlier",
        "obs-later",
    ]
    assert timeline["observationCoverage"]["state"] == "available"
    assert timeline["observationCoverage"]["policy"]["state"] == "unknown"
    assert timeline["observationCoverage"]["freshness"]["state"] == "unknown"

    summary = _section(result, "summary").content
    coverage = summary["requiredSlotCoverage"]
    assert coverage["timeline"]["state"] == "degraded"
    assert coverage["timeline"]["coverage"] == "partial"
    assert {ref["id"] for ref in coverage["timeline"]["evidenceRefs"]} >= {
        EPISODE_ID,
        "obs-later",
        "obs-earlier",
    }
    assert coverage["evidence_trace"]["state"] == "degraded"
    assert {ref["id"] for ref in coverage["evidence_trace"]["evidenceRefs"]} >= {
        "obs-later",
        "obs-earlier",
    }
    serialized = json.dumps(result.model_dump(mode="json"))
    assert "private event payload" not in serialized
    assert "private-actor-id" not in serialized


@pytest.mark.asyncio
async def test_episode_touchpoints_resolve_only_explicit_tenant_references():
    episode = _episode([]).model_copy(
        update={"journey_touchpoint_ids": ["touchpoint-1"]}
    )
    source = FakeTouchpointSource(
        {
            "touchpoint-1": {
                "tenant_id": TENANT,
                "touchpoint_id": "touchpoint-1",
                "occurred_at": "2026-10-20T12:00:00+00:00",
                "touchpoint_type": "email_click",
                "interaction_type": "click",
                "channel": "email",
                "journey_role": "entry",
                "campaign_id": "campaign-private-id",
                "agent_id": "agent-private-id",
                "landing_url": "https://private.example/secret",
            }
        }
    )
    result = await Episode360Provider(
        episode_store=FakeEpisodeStore(episode),
        observation_source=FakeObservationSource(),
        touchpoint_source=source,
    ).project(_request(), _context())

    assert source.calls == [(TENANT, "touchpoint-1")]
    interaction = _section(result, "interactions").content
    touchpoints = interaction["touchpointContext"]
    assert touchpoints["state"] == "available"
    assert touchpoints["coverage"] == "exact_recorded_episode_references_only"
    assert touchpoints["touchpointIds"] == ["touchpoint-1"]
    assert touchpoints["touchpoints"] == [
        {
            "touchpointId": "touchpoint-1",
            "occurredAt": "2026-10-20T12:00:00+00:00",
            "touchpointType": "email_click",
            "interactionType": "click",
            "channel": "email",
            "journeyRole": "entry",
            "episodeIds": [EPISODE_ID],
            "evidenceRefs": [
                {
                    "id": "touchpoint-1",
                    "type": "event",
                    "source": "services/api/journeys/measurement/repositories/touchpoint_repo.py:silver_campaign_touchpoint_facts",
                    "observedAt": "2026-10-20T12:00:00+00:00",
                    "confidence": None,
                    "uri": "store://silver_campaign_touchpoint_facts/touchpoint-1",
                }
            ],
        }
    ]
    assert touchpoints["freshness"]["state"] == "unknown"
    assert touchpoints["policy"]["state"] == "unknown"
    summary_coverage = _section(result, "summary").content["requiredSlotCoverage"]
    assert summary_coverage["touchpoints"]["state"] == "available"
    assert summary_coverage["touchpoints"]["coverage"] == (
        "exact_recorded_episode_references_only"
    )
    assert summary_coverage["attribution_links"]["state"] == "unknown"
    touchpoint_claim = next(
        claim for claim in result.claims if "touchpoints" in (claim.domainSlotIds or [])
    )
    assert touchpoint_claim.kind == "episode_referenced_journey_touchpoint"
    assert {ref.id for ref in touchpoint_claim.evidenceRefs} == {
        EPISODE_ID,
        "touchpoint-1",
    }
    serialized = json.dumps(result.model_dump(mode="json"))
    assert "campaign-private-id" not in serialized
    assert "agent-private-id" not in serialized
    assert "private.example" not in serialized


@pytest.mark.asyncio
async def test_episode_touchpoint_unknown_legacy_and_explicit_empty_are_distinct():
    legacy = await Episode360Provider(
        episode_store=FakeEpisodeStore(_episode([])),
        observation_source=FakeObservationSource(),
    ).project(_request(), _context())
    legacy_context = _section(legacy, "interactions").content["touchpointContext"]
    assert legacy_context["state"] == "unknown"
    assert legacy_context["reason"] == "episode_touchpoint_reference_list_unavailable"

    explicit_empty_episode = _episode([]).model_copy(
        update={"journey_touchpoint_ids": []}
    )
    explicit_empty = await Episode360Provider(
        episode_store=FakeEpisodeStore(explicit_empty_episode),
        observation_source=FakeObservationSource(),
    ).project(_request(), _context())
    empty_context = _section(explicit_empty, "interactions").content["touchpointContext"]
    assert empty_context["state"] == "empty"
    assert empty_context["coverage"] == "explicit_episode_reference_set_empty"
    assert empty_context["touchpoints"] == []


@pytest.mark.asyncio
async def test_episode_handoff_slot_does_not_infer_canonical_handoff_from_observation_metadata():
    observation = _observation(
        "obs-handoff-event",
        source_type="agent_handoff",
    )
    observation.update(
        {
            "source_event_id": "canonical-source-event-1",
            "agent_id": "agent-source-1",
            "beneficiary_actor_id": "agent-target-1",
            "event_type": "agent_handoff",
            "task_id": "task-1",
        }
    )
    result = await Episode360Provider(
        episode_store=FakeEpisodeStore(_episode(["obs-handoff-event"])),
        observation_source=FakeObservationSource([observation]),
    ).project(_request(), _context())

    interactions = _section(result, "interactions").content
    handoffs = interactions["agentHandoffs"]
    assert handoffs["state"] == "unknown"
    assert handoffs["coverage"] == "unknown"
    assert handoffs["reason"] == (
        "no_explicit_episode_agent_handoff_link_recorded_absence_not_established"
    )
    assert handoffs["handoffs"] == []

    required_slot = _section(result, "summary").content["requiredSlotCoverage"]["agent_handoffs"]
    assert required_slot["state"] == "unknown"
    assert required_slot["coverage"] == "unknown"
    assert required_slot["reason"] == handoffs["reason"]
    assert required_slot["evidenceRefs"] == []


@pytest.mark.asyncio
async def test_episode_observation_join_omits_cross_tenant_and_inactive_rows():
    observation_source = FakeObservationSource(
        [
            _observation("obs-active"),
            _observation("obs-cross-tenant", tenant_id="tenant-other"),
            _observation("obs-restricted", status="consent_restricted"),
        ]
    )
    result = await Episode360Provider(
        episode_store=FakeEpisodeStore(
            _episode(["obs-active", "obs-cross-tenant", "obs-restricted"])
        ),
        observation_source=observation_source,
        episode_authority_source=FakeEpisodeAuthoritySource([
            _typed_reference("obs-active"),
            _typed_reference("obs-cross-tenant"),
            _typed_reference("obs-restricted"),
        ]),
    ).project(_request(), _context())

    references = _section(result, "interactions").content["observationReferences"]
    assert references["state"] == "degraded"
    assert [row["observationId"] for row in references["observations"]] == ["obs-active"]
    assert {ref["id"] for ref in references["evidenceRefs"]} >= {"obs-active"}
    assert "semantic_observation_tenant_scope_mismatch" in references["reason"]
    assert "episode_observation_tenant_mismatch" in result.degradedReasons
    assert "episode_observation_non_active_rows_omitted" in result.degradedReasons


@pytest.mark.asyncio
async def test_episode_observation_join_omits_all_duplicate_ids():
    observation = _observation("obs-ambiguous")
    result = await Episode360Provider(
        episode_store=FakeEpisodeStore(_episode(["obs-ambiguous"])),
        observation_source=FakeObservationSource(
            [observation, dict(observation), dict(observation)]
        ),
        episode_authority_source=FakeEpisodeAuthoritySource([
            _typed_reference("obs-ambiguous"),
        ]),
    ).project(_request(), _context())

    references = _section(result, "interactions").content["observationReferences"]
    assert references["state"] == "unknown"
    assert references["observations"] == []
    assert references["evidenceRefs"] == []
    assert references["reason"] == "episode_observation_namespace_or_semantic_rows_invalid"


@pytest.mark.asyncio
async def test_episode_observation_read_failure_stays_unknown_without_claiming_freshness_or_policy():
    result = await Episode360Provider(
        episode_store=FakeEpisodeStore(_episode(["obs-unavailable"])),
        observation_source=FakeObservationSource(error=RuntimeError("private source detail")),
        episode_authority_source=FakeEpisodeAuthoritySource([
            _typed_reference("obs-unavailable"),
        ]),
    ).project(_request(), _context())

    references = _section(result, "interactions").content["observationReferences"]
    assert references["state"] == "unknown"
    assert references["observations"] == []
    assert references["reason"] == "episode_observation_namespace_or_semantic_authority_unavailable"
    assert references["freshness"]["state"] == "unknown"
    assert references["policy"]["state"] == "unknown"
    assert "private source detail" not in json.dumps(result.model_dump(mode="json"))


@pytest.mark.asyncio
async def test_repository_episode_observation_source_keeps_exact_tenant_and_id_query():
    repository = FakeFactRepository()
    source = RepositoryEpisodeObservationSource(repository=repository)

    assert await source.find_by_ids(TENANT, ["obs-exact"]) == []
    assert repository.calls == [(TENANT, ["obs-exact"])]
