"""Episode writes produce typed links only for exact semantic Silver observations."""

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

from graph.operational_intelligence.models import EntityRef  # noqa: E402
from intelligence.semantic_intelligence.models import (  # noqa: E402
    EvidenceRef,
    SemanticObservation,
    SubjectType,
)
from intelligence.semantic_intelligence.store import (  # noqa: E402
    DurableSemanticSentimentStore,
)
from journeys.measurement.episodes.engine import EpisodeEngine  # noqa: E402
from journeys.measurement.episodes.related_authorities import (  # noqa: E402
    EpisodeJourneyAuthorityRepository,
)
from intelligence.semantic_intelligence.consumer import SemanticEventConsumer  # noqa: E402
from intelligence.semantic_intelligence import engine as semantic_engine  # noqa: E402
from shared.events.events import Event, Topic  # noqa: E402
from journeys.measurement.episodes.provider import Episode360Provider  # noqa: E402
from repositories.repos import reset_in_memory_stores as reset_fact_stores  # noqa: E402
from shared.backend_interpretation import flags  # noqa: E402
from shared.store import reset_in_memory_stores as reset_episode_stores  # noqa: E402
from shared.intelligence_projections.contracts import (  # noqa: E402
    ProjectionContext,
    ProjectionRequest,
    ProjectionSubject,
)

TENANT = "tenant-episode-semantic-producer"
AUTHORITY = "semantic_intelligence.silver_semantic_observations"


@pytest.fixture(autouse=True)
def _isolate_stores():
    reset_fact_stores()
    reset_episode_stores()
    yield
    reset_fact_stores()
    reset_episode_stores()


async def _seed_semantic_observation(
    *, observation_id: str, tenant_id: str = TENANT, namespace: str | None = "site:shop-a"
) -> SemanticObservation:
    observation = SemanticObservation(
        observation_id=observation_id,
        tenant_id=tenant_id,
        source_event_id=f"event-{observation_id}",
        source_namespace=namespace,
        source_type="agent_tool_observation",
        actor_ref="agent-1",
        actor_type=SubjectType.AGENT,
        primary_subject_ref="agent-1",
        target_type=SubjectType.AGENT,
        evidence_refs=[
            EvidenceRef(
                evidence_id=f"evidence-{observation_id}",
                source_type="event",
                source_ref=f"event-{observation_id}",
            )
        ],
    )
    return await DurableSemanticSentimentStore().put_semantic(observation)


async def _references(episode_id: str):
    return await EpisodeJourneyAuthorityRepository().list_for_subject(
        TENANT, "episode", episode_id, "episode_observation_reference", limit=10
    )


@pytest.mark.asyncio
async def test_episode_ingest_produces_exact_typed_semantic_reference_on_replay(monkeypatch):
    monkeypatch.setattr(flags, "episode_engine_enabled", lambda: True)
    await _seed_semantic_observation(observation_id="sem-one")
    await _seed_semantic_observation(observation_id="sem-two")
    engine = EpisodeEngine()
    subject = EntityRef(kind="agent", id="agent-1")

    episode = await engine.ingest_observation(
        tenant_id=TENANT,
        subject=subject,
        kind="agent_execution",
        observation_id="sem-one",
        observation_authority=AUTHORITY,
    )
    replayed = await engine.ingest_observation(
        tenant_id=TENANT,
        subject=subject,
        kind="agent_execution",
        observation_id="sem-one",
        observation_authority=AUTHORITY,
    )
    appended = await engine.ingest_observation(
        tenant_id=TENANT,
        subject=subject,
        kind="agent_execution",
        observation_id="sem-two",
        observation_authority=AUTHORITY,
    )

    assert episode.episode_id == replayed.episode_id == appended.episode_id
    assert appended.observation_ids == ["sem-one", "sem-two"]
    read = await _references(episode.episode_id)
    assert read.complete
    assert len(read.records) == 2
    assert {row["observation_id"] for row in read.records} == {"sem-one", "sem-two"}
    assert {row["source_namespace"] for row in read.records} == {"site:shop-a"}
    assert {row["source_event_id"] for row in read.records} == {
        "event-sem-one",
        "event-sem-two",
    }


@pytest.mark.asyncio
async def test_episode_ingest_never_asserts_untrusted_or_unavailable_semantic_source(monkeypatch):
    monkeypatch.setattr(flags, "episode_engine_enabled", lambda: True)
    engine = EpisodeEngine()
    subject = EntityRef(kind="agent", id="agent-1")
    await _seed_semantic_observation(observation_id="sem-legacy", namespace=None)
    await _seed_semantic_observation(
        observation_id="sem-foreign", tenant_id="foreign-tenant"
    )

    without_marker = await engine.ingest_observation(
        tenant_id=TENANT,
        subject=subject,
        kind="agent_execution",
        observation_id="sem-legacy",
    )
    assert (await _references(without_marker.episode_id)).records == ()

    with pytest.raises(ValueError, match="source_namespace_unavailable"):
        await engine.ingest_observation(
            tenant_id=TENANT,
            subject=subject,
            kind="agent_execution",
            observation_id="sem-legacy",
            observation_authority=AUTHORITY,
        )
    with pytest.raises(ValueError, match="not_unique_for_episode_reference"):
        await engine.ingest_observation(
            tenant_id=TENANT,
            subject=subject,
            kind="agent_execution",
            observation_id="sem-foreign",
            observation_authority=AUTHORITY,
        )
    assert (await _references(without_marker.episode_id)).records == ()


@pytest.mark.asyncio
async def test_episode_link_failure_leaves_no_claim_and_retry_recovers_once(monkeypatch):
    monkeypatch.setattr(flags, "episode_engine_enabled", lambda: True)
    subject = EntityRef(kind="agent", id="agent-1")
    first_engine = EpisodeEngine()

    with pytest.raises(ValueError, match="not_unique_for_episode_reference"):
        await first_engine.ingest_observation(
            tenant_id=TENANT,
            subject=subject,
            kind="agent_execution",
            observation_id="sem-delayed",
            observation_authority=AUTHORITY,
            completion_hint=True,
        )
    (pending_episode,) = await first_engine.store.list_for_subject(
        TENANT, "agent", "agent-1"
    )
    assert pending_episode.observation_ids == ["sem-delayed"]
    assert pending_episode.status == "open"
    assert (await _references(pending_episode.episode_id)).records == ()

    await _seed_semantic_observation(observation_id="sem-delayed")
    # Simulate a worker restart: the open episode is recovered from durable
    # state and the exact association is retried, without a duplicate ID.
    retry_engine = EpisodeEngine()
    recovered = await retry_engine.ingest_observation(
        tenant_id=TENANT,
        subject=subject,
        kind="agent_execution",
        observation_id="sem-delayed",
        observation_authority=AUTHORITY,
        completion_hint=True,
    )
    assert recovered.episode_id == pending_episode.episode_id
    assert recovered.observation_ids == ["sem-delayed"]
    assert recovered.status == "closed"
    read = await _references(recovered.episode_id)
    assert len(read.records) == 1
    assert read.records[0]["observation_id"] == "sem-delayed"


@pytest.mark.asyncio
async def test_episode_semantic_reference_producer_respects_flag(monkeypatch):
    monkeypatch.setattr(flags, "episode_engine_enabled", lambda: False)
    await _seed_semantic_observation(observation_id="sem-disabled")
    episode = await EpisodeEngine().ingest_observation(
        tenant_id=TENANT,
        subject=EntityRef(kind="agent", id="agent-1"),
        kind="agent_execution",
        observation_id="sem-disabled",
        observation_authority=AUTHORITY,
    )
    assert (await _references(episode.episode_id)).records == ()


@pytest.mark.asyncio
async def test_semantic_ingestion_producer_reaches_episode360_reader(monkeypatch):
    monkeypatch.setattr(flags, "episode_engine_enabled", lambda: True)
    monkeypatch.setattr(semantic_engine, "_store", DurableSemanticSentimentStore())
    consumer = SemanticEventConsumer()
    event = Event(
        topic=Topic.SDK_EVENTS_VALIDATED,
        tenant_id=TENANT,
        source_service="ingestion.batch",
        payload={
            "event_id": "event-live",
            "event_type": "feedback_submitted",
            "properties": {
                "agent_id": "agent-1",
                "content": "I recommend this product, it is excellent",
            },
            "context": {"identity_namespace": "site:shop-a"},
        },
    )
    await consumer.on_validated_event(event)
    await consumer.on_validated_event(event)

    (episode,) = await EpisodeEngine().store.list_for_subject(TENANT, "agent", "agent-1")
    assert episode.kind == "semantic_observation_stream"
    assert len(episode.observation_ids) == 1
    references = await _references(episode.episode_id)
    assert references.complete
    assert len(references.records) == 1

    provider = Episode360Provider()
    request = ProjectionRequest(
        projectionId="episode360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="episode", id=episode.episode_id),
    )
    context = ProjectionContext(
        projectionId="episode360",
        tenantId=TENANT,
        registryState="in_flight",
        dependencyState=[],
        warnings=[],
    )
    result = await provider.project(request, context)
    interactions = next(section for section in result.sections if section.id == "interactions")
    assert interactions.content["observationReferences"]["state"] == "available"
    assert [
        row["observationId"]
        for row in interactions.content["observationReferences"]["observations"]
    ] == episode.observation_ids


@pytest.mark.asyncio
async def test_semantic_ingestion_producer_rejects_incomplete_observation(monkeypatch):
    monkeypatch.setattr(flags, "episode_engine_enabled", lambda: True)
    observation = await _seed_semantic_observation(observation_id="sem-incomplete")
    observation.source_namespace = None

    await SemanticEventConsumer()._produce_episode_observation(TENANT, observation)

    assert await EpisodeEngine().store.list_for_subject(TENANT, "agent", "agent-1") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["disabled", "namespace", "quarantined", "untyped"])
async def test_validated_event_does_not_create_unsupported_episode(monkeypatch, boundary):
    monkeypatch.setattr(flags, "episode_engine_enabled", lambda: boundary != "disabled")
    monkeypatch.setattr(semantic_engine, "_store", DurableSemanticSentimentStore())
    payload = {
        "event_id": f"event-{boundary}",
        "event_type": "feedback_submitted",
        "properties": {
            "agent_id": "agent-1",
            "content": "I recommend this product, it is excellent",
        },
        "context": {"identity_namespace": "site:shop-a"},
    }
    if boundary == "namespace":
        payload["context"] = {}
    elif boundary == "quarantined":
        payload["event_type"] = "unregistered-episode-event"
    elif boundary == "untyped":
        payload["primary_subject_ref"] = "agent-1"
        payload["properties"].pop("agent_id")
    await SemanticEventConsumer().on_validated_event(
        Event(
            topic=Topic.SDK_EVENTS_VALIDATED,
            tenant_id=TENANT,
            source_service="ingestion.batch",
            payload=payload,
        )
    )
    assert await EpisodeEngine().store.list_for_subject(TENANT, "agent", "agent-1") == []
