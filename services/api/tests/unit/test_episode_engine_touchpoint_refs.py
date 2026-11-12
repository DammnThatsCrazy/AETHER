"""Canonical EpisodeEngine writes preserve explicit journey touchpoint links."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from graph.operational_intelligence.models import EntityRef, EvidenceRef  # noqa: E402
from journeys.measurement.episodes.engine import EpisodeEngine  # noqa: E402
from shared.backend_interpretation.primitives import EpisodeRecord  # noqa: E402


class MemoryEpisodeStore:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str], EpisodeRecord] = {}

    async def upsert(self, record: EpisodeRecord) -> EpisodeRecord:
        self.records[(record.tenant_id, record.episode_id)] = record
        return record

    async def get(self, tenant_id: str, episode_id: str) -> EpisodeRecord | None:
        return self.records.get((tenant_id, episode_id))

    async def list_for_subject(
        self, tenant_id: str, kind: str, subject_id: str
    ) -> list[EpisodeRecord]:
        return [
            record
            for (row_tenant_id, _), record in self.records.items()
            if row_tenant_id == tenant_id
            and record.subject.kind == kind
            and record.subject.id == subject_id
        ]


class MemoryJourneySource:
    async def get_current(self, tenant_id: str, journey_id: str) -> dict | None:
        if tenant_id not in {"tenant-a", "tenant-b"} or journey_id != "journey-1":
            return None
        return {
            "tenant_id": tenant_id,
            "journey_id": journey_id,
            "journey_version_id": "journey-version-1",
            "is_current": True,
        }


@pytest.mark.asyncio
async def test_episode_engine_records_only_explicit_touchpoint_ids_and_appends_idempotently():
    store = MemoryEpisodeStore()
    engine = EpisodeEngine(store=store)  # type: ignore[arg-type]
    subject = EntityRef(kind="agent", id="agent-episode-engine")

    record = await engine.ingest_observation(
        tenant_id="tenant-episode-engine",
        subject=subject,
        kind="agent_execution",
        observation_id="observation-1",
        event_time="2026-10-20T10:00:00+00:00",
    )
    assert record.journey_touchpoint_ids is None

    appended = await engine.ingest_observation(
        tenant_id="tenant-episode-engine",
        subject=subject,
        kind="agent_execution",
        observation_id="observation-2",
        journey_touchpoint_ids=["touchpoint-1", "touchpoint-1"],
        event_time="2026-10-20T10:01:00+00:00",
    )
    assert appended.episode_id == record.episode_id
    assert appended.journey_touchpoint_ids == ["touchpoint-1"]

    linked = await engine.link_journey_touchpoint(
        "tenant-episode-engine", record.episode_id, "touchpoint-2"
    )
    assert linked.journey_touchpoint_ids == ["touchpoint-1", "touchpoint-2"]
    duplicate = await engine.link_journey_touchpoint(
        "tenant-episode-engine", record.episode_id, "touchpoint-1"
    )
    assert duplicate.journey_touchpoint_ids == ["touchpoint-1", "touchpoint-2"]


@pytest.mark.asyncio
async def test_episode_engine_requires_exact_existing_tenant_episode_for_touchpoint_link():
    engine = EpisodeEngine(store=MemoryEpisodeStore())  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="non-empty touchpoint_id"):
        await engine.link_journey_touchpoint("tenant-a", "episode-1", " ")
    with pytest.raises(KeyError, match="not found for tenant"):
        await engine.link_journey_touchpoint("tenant-a", "episode-1", "touchpoint-1")


@pytest.mark.asyncio
async def test_episode_engine_links_exact_journey_with_source_evidence():
    store = MemoryEpisodeStore()
    engine = EpisodeEngine(
        store=store,
        journey_source=MemoryJourneySource(),
    )  # type: ignore[arg-type]
    record = await engine.ingest_observation(
        tenant_id="tenant-a",
        subject=EntityRef(kind="agent", id="agent-1"),
        kind="agent_execution",
        observation_id="observation-1",
    )
    evidence = EvidenceRef(
        id="journey-link-event",
        type="relationship",
        source="canonical-journey-writer",
    )

    linked = await engine.link_journey(
        "tenant-a", record.episode_id, "journey-1", evidence=evidence
    )

    assert linked.journey_id == "journey-1"
    assert linked.evidence_refs == [evidence]
    with pytest.raises(ValueError, match="different canonical journey"):
        await engine.link_journey(
            "tenant-a", record.episode_id, "journey-2", evidence=evidence
        )
    unlinked = await engine.ingest_observation(
        tenant_id="tenant-a",
        subject=EntityRef(kind="agent", id="agent-2"),
        kind="agent_execution",
        observation_id="observation-2",
    )
    with pytest.raises(KeyError, match="current journey .* not found for tenant"):
        await engine.link_journey(
            "tenant-a", unlinked.episode_id, "journey-missing", evidence=evidence
        )
    with pytest.raises(KeyError, match="not found for tenant"):
        await engine.link_journey("tenant-b", record.episode_id, "journey-1", evidence=evidence)
