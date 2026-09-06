"""WS-D item 2 tests: episode engine + episode360 provider surface."""

from __future__ import annotations

import pytest

from services.operational_intelligence.models import EntityRef, EvidenceRef

SUBJECT = EntityRef(kind="user", id="u-1")


def _ref(event_id: str, source: str = "sdk") -> EvidenceRef:
    return EvidenceRef(id=event_id, type="event", source=source)


@pytest.mark.asyncio
async def test_episode_engine_open_append_close(wsd_flags):
    from shared.store import reset_in_memory_stores
    from services.measurement.episodes.engine import EpisodeEngine

    reset_in_memory_stores()
    wsd_flags(episode_engine_enabled=True)
    engine = EpisodeEngine()

    first = await engine.ingest_observation(
        tenant_id="tenant-a", subject=SUBJECT, kind="support",
        evidence=_ref("evt-1"), observation_id="evt-1",
        event_time="2026-09-06T00:00:00Z",
    )
    assert first.status == "open"
    ep_id = first.episode_id

    second = await engine.ingest_observation(
        tenant_id="tenant-a", subject=SUBJECT, kind="support",
        evidence=_ref("evt-2"), observation_id="evt-2",
        event_time="2026-09-06T00:05:00Z",
    )
    # Same open episode, appended.
    assert second.episode_id == ep_id
    assert len(second.observation_ids) == 2
    assert len(second.evidence_refs) == 2
    assert second.occurred_to == "2026-09-06T00:05:00Z"

    closed = await engine.close("tenant-a", ep_id)
    assert closed.status == "closed"

    # A later observation for the same key opens a NEW episode.
    later = await engine.ingest_observation(
        tenant_id="tenant-a", subject=SUBJECT, kind="support",
        evidence=_ref("evt-3"), observation_id="evt-3",
        event_time="2026-09-07T00:00:00Z",
    )
    assert later.episode_id != ep_id
    assert later.status == "open"


@pytest.mark.asyncio
async def test_episode_completion_hint_closes(wsd_flags):
    from shared.store import reset_in_memory_stores
    from services.measurement.episodes.engine import EpisodeEngine

    reset_in_memory_stores()
    wsd_flags(episode_engine_enabled=True)
    engine = EpisodeEngine()
    rec = await engine.ingest_observation(
        tenant_id="tenant-a", subject=SUBJECT, kind="support",
        evidence=_ref("evt-1"), observation_id="evt-1",
        event_time="2026-09-06T00:00:00Z", completion_hint=True,
    )
    assert rec.status == "closed"


@pytest.mark.asyncio
async def test_episode360_provider_renders_sections(wsd_flags):
    from shared.intelligence_projections import (
        ProjectionContext,
        ProjectionDependencyState,
        ProjectionRequest,
        ProjectionSubject,
    )
    from shared.store import reset_in_memory_stores
    from services.measurement.episodes.engine import EpisodeEngine
    from services.measurement.episodes.provider import Episode360Provider

    reset_in_memory_stores()
    wsd_flags(episode_engine_enabled=True)
    engine = EpisodeEngine()
    first = await engine.ingest_observation(
        tenant_id="tenant-a", subject=SUBJECT, kind="support",
        evidence=_ref("evt-1"), observation_id="evt-1",
        event_time="2026-09-06T00:00:00Z",
    )
    await engine.link_outcome("tenant-a", first.episode_id, "oc-1")
    # Injected store so availability is not derived from the durable KV in a
    # way that depends on other test state.
    provider = Episode360Provider(episode_store=engine.store)
    request = ProjectionRequest(
        projectionId="episode360",
        tenantId="tenant-a",
        # Durable rows carry EntityRef kind "user"; a projection request
        # addresses them with the coarse registry kind "entity" + the same id.
        subject=ProjectionSubject(kind="entity", id="u-1"),
        temporalMode="window",
    )
    context = ProjectionContext(
        projectionId="episode360",
        tenantId="tenant-a",
        registryState="in_flight",
        dependencyState=[
            ProjectionDependencyState(
                projectionId="relationship360", state="missing",
                reason="no provider registered",
            )
        ],
        warnings=[],
    )
    result = await provider.project(request, context)
    assert result.projectionId == "episode360"
    by_id = {s.id: s for s in result.sections}
    assert set(by_id) == {"evidence", "interactions", "outcomes", "state", "summary", "timeline"}
    assert by_id["summary"].state == "available"
    assert by_id["summary"].content["episodeCount"] == 1
    assert by_id["outcomes"].content["outcomeIds"] == ["oc-1"]
    assert by_id["timeline"].content["timeline"][0]["kind"] == "support"
    assert result.claims and all(c.evidenceRefs for c in result.claims)


@pytest.mark.asyncio
async def test_episode360_provider_empty_store_is_typed_empty(wsd_flags):
    from shared.intelligence_projections import (
        ProjectionContext,
        ProjectionRequest,
        ProjectionSubject,
    )
    from shared.backend_interpretation.stores import EpisodeStore
    from shared.store import reset_in_memory_stores
    from services.measurement.episodes.provider import Episode360Provider

    reset_in_memory_stores()
    wsd_flags(episode_engine_enabled=True)
    provider = Episode360Provider(episode_store=EpisodeStore())
    request = ProjectionRequest(
        projectionId="episode360",
        tenantId="tenant-a",
        subject=ProjectionSubject(kind="entity", id="u-1"),
    )
    context = ProjectionContext(
        projectionId="episode360", tenantId="tenant-a",
        registryState="in_flight", dependencyState=[], warnings=[],
    )
    result = await provider.project(request, context)
    assert result.sections
    assert all(s.state == "empty" for s in result.sections)
