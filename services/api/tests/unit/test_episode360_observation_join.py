"""Episode360 exact observation-reference joins and partial-state semantics."""

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

from graph.operational_intelligence.models import EntityRef  # noqa: E402
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
        "occurred_at": occurred_at,
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
        self.calls: list[tuple[str, list[str]]] = []

    async def find_by_ids(self, tenant_id: str, observation_ids: list[str]):
        self.calls.append((tenant_id, list(observation_ids)))
        if self.error is not None:
            raise self.error
        return self.rows


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
    ).project(_request(), _context())

    assert observation_source.calls == [(TENANT, ["obs-later", "obs-earlier"])]
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
        "episode_records_and_observations_do_not_reference_canonical_agent_execution_or_handoff_id"
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
    ).project(_request(), _context())

    references = _section(result, "interactions").content["observationReferences"]
    assert references["state"] == "degraded"
    assert [row["observationId"] for row in references["observations"]] == ["obs-active"]
    assert [ref["id"] for ref in references["evidenceRefs"]] == ["obs-active"]
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
    ).project(_request(), _context())

    references = _section(result, "interactions").content["observationReferences"]
    assert references["state"] == "unknown"
    assert references["observations"] == []
    assert references["evidenceRefs"] == []
    assert references["reason"] == "semantic_observation_rows_invalid_or_ambiguous"


@pytest.mark.asyncio
async def test_episode_observation_read_failure_stays_unknown_without_claiming_freshness_or_policy():
    result = await Episode360Provider(
        episode_store=FakeEpisodeStore(_episode(["obs-unavailable"])),
        observation_source=FakeObservationSource(error=RuntimeError("private source detail")),
    ).project(_request(), _context())

    references = _section(result, "interactions").content["observationReferences"]
    assert references["state"] == "unknown"
    assert references["observations"] == []
    assert references["reason"] == "semantic_observation_authority_unavailable"
    assert references["freshness"]["state"] == "unknown"
    assert references["policy"]["state"] == "unknown"
    assert "private source detail" not in json.dumps(result.model_dump(mode="json"))


@pytest.mark.asyncio
async def test_repository_episode_observation_source_keeps_exact_tenant_and_id_query():
    repository = FakeFactRepository()
    source = RepositoryEpisodeObservationSource(repository=repository)

    assert await source.find_by_ids(TENANT, ["obs-exact"]) == []
    assert repository.calls == [(TENANT, ["obs-exact"])]
