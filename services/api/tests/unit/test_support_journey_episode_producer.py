"""Live support context ingress to canonical episode and real-registry frame."""

from __future__ import annotations

from uuid import uuid4
from datetime import datetime, timedelta, timezone

import pytest

from tests.unit.test_support_case_context_authorities import (
    ACTOR, CONNECTION, NOW, TENANT, EmptyCaseFactsSource, FakeConnections, FakeJourneys, _case,
)
from journeys.support360.context_authorities import (
    SupportCaseContextAuthorityError, SupportCaseContextIngestionService,
    SupportCaseContextRepository, SupportJourneyLinkEventInput, SupportJourneyLinkEventType,
    reset_local_support_case_context_store,
)
from journeys.support360.cases import reset_local_support_case_store
from journeys.support360.provider import Support360Provider, _validated_case_journey_episodes
from shared.backend_interpretation import flags
from shared.backend_interpretation.stores import EpisodePageRead, EpisodeStore
from shared.intelligence_projections.contracts import (
    Experience360FrameRequest, Experience360PolicyDisposition, Experience360PolicyEvaluation,
    ProjectionContext, ProjectionSubject,
)
from shared.intelligence_projections.frame_runtime import build_experience360_frame
from shared.store import reset_in_memory_stores


@pytest.fixture(autouse=True)
def isolated_stores(monkeypatch):
    reset_local_support_case_store()
    reset_local_support_case_context_store()
    reset_in_memory_stores()
    monkeypatch.setattr(flags, "episode_engine_enabled", lambda: True)
    yield
    reset_local_support_case_store()
    reset_local_support_case_context_store()
    reset_in_memory_stores()


async def produce(**changes):
    cases, case = await _case()
    journey_id = str(uuid4())
    journeys = FakeJourneys(journey_id)
    contexts = SupportCaseContextRepository()
    service = SupportCaseContextIngestionService(
        repository=contexts, cases=cases, connections=FakeConnections(), journeys=journeys,
    )
    event = SupportJourneyLinkEventInput(**{
        "case_id": case["case_id"], "journey_id": journey_id,
        "source_link_id": "source-link", "source_revision_id": "revision-1",
        "source_event_id": "link-event", "event_type": SupportJourneyLinkEventType.LINKED,
        "source_observed_at": NOW, "effective_at": NOW, **changes,
    })
    record = await service.ingest(
        "journey_links", TENANT, CONNECTION, event, actor_id=ACTOR, actor_type="tenant_user",
    )
    return cases, case, contexts, journeys, service, event, record


@pytest.mark.asyncio
async def test_context_ingress_produces_exact_replay_safe_episode_and_real_frame():
    cases, case, contexts, journeys, service, event, record = await produce()
    episodes = await EpisodeStore().list_by_tenant(TENANT)
    assert len(episodes) == 1
    episode = episodes[0]
    assert episode.journey_id == event.journey_id
    assert episode.subject.kind == "resource"
    assert episode.subject.id == f"store://support_cases/{case['case_id']}"
    assert episode.kind == "support_journey_link_observation"
    assert episode.observation_ids == [record["context_event_id"]]
    assert episode.outcome_ids == []
    await service.ingest(
        "journey_links", TENANT, CONNECTION, event, actor_id=ACTOR, actor_type="tenant_user",
    )
    assert await EpisodeStore().list_by_tenant(TENANT) == episodes
    assert await EpisodeStore().list_by_tenant("foreign-tenant") == []
    support = Support360Provider(
        EmptyCaseFactsSource(), case_repository=cases, case_context_repository=contexts,
        canonical_journey_repository=journeys, canonical_episode_store=EpisodeStore(),
    )

    class Policy:
        async def evaluate(self, request):
            return Experience360PolicyEvaluation(
                surfaceId="support360", tenantId=TENANT, evaluatedAt=NOW.isoformat(),
                frameDisposition=Experience360PolicyDisposition(state="allowed"),
                slotDispositions={
                    "journey_links": Experience360PolicyDisposition(state="allowed"),
                    "risk": Experience360PolicyDisposition(state="denied"),
                },
            )

    class Runtime:
        async def execute_projection(self, request, **kwargs):
            assert request.projectionId == "support360"
            assert request.includeSections == ["support_journey_links"]
            return await support.project(request, ProjectionContext(
                projectionId="support360", tenantId=TENANT, registryState="in_flight",
                dependencyState=[], warnings=[],
            ))

    frame = await build_experience360_frame(
        Experience360FrameRequest(
            surfaceId="support360", tenantId=TENANT,
            subject=ProjectionSubject(kind="support_case", id=case["case_id"]),
            requestedSlotIds=["journey_links", "risk"], includeEvidence=True,
        ), policy_evaluator=Policy(), projection_runtime=Runtime(),
    )
    journey_slot = next(slot for slot in frame.slots if slot.id == "journey_links")
    content = journey_slot.content["sections"][0]["content"]
    relation = content["episodeFacts"]["relations"][0]
    assert relation["canonicalEpisodeId"] == episode.episode_id
    assert relation["contextEventId"] == record["context_event_id"]
    assert relation["canonicalJourneyId"] == event.journey_id
    assert journey_slot.evidenceRefs and journey_slot.claims
    assert next(slot for slot in frame.slots if slot.id == "risk").content is None


@pytest.mark.asyncio
async def test_episode_write_failure_is_repaired_by_same_authenticated_context_replay(monkeypatch):
    from journeys.support360 import episodes

    publish = episodes.publish_journey_link_episode

    async def unavailable(record):
        raise SupportCaseContextAuthorityError("store unavailable; replay required")

    monkeypatch.setattr(episodes, "publish_journey_link_episode", unavailable)
    with pytest.raises(SupportCaseContextAuthorityError):
        await produce()
    contexts = SupportCaseContextRepository()
    cases, case = await _case()
    read = await contexts.list_for_case(
        TENANT, case["case_id"], connection_id=CONNECTION, kind="journey_links",
    )
    record = read.events[0]
    monkeypatch.setattr(episodes, "publish_journey_link_episode", publish)
    service = SupportCaseContextIngestionService(
        repository=contexts, cases=cases, connections=FakeConnections(),
        journeys=FakeJourneys(record["payload"]["journey_id"]),
    )
    replay = await service.ingest(
        "journey_links", TENANT, CONNECTION, SupportJourneyLinkEventInput(**record["payload"]),
        actor_id=ACTOR, actor_type="tenant_user",
    )
    assert replay == record
    assert len(await EpisodeStore().list_by_tenant(TENANT)) == 1


@pytest.mark.asyncio
async def test_episode_feature_flag_disables_only_episode_producer(monkeypatch):
    monkeypatch.setattr(flags, "episode_engine_enabled", lambda: False)
    *_, record = await produce()
    assert record["context_kind"] == "journey_links"
    assert await EpisodeStore().list_by_tenant(TENANT) == []


@pytest.mark.asyncio
async def test_episode_replay_rejects_conflicting_durable_document_without_overwrite():
    *_, service, event, _ = await produce()
    store = EpisodeStore()
    episode = (await store.list_by_tenant(TENANT))[0]
    altered = episode.model_copy(update={"journey_id": str(uuid4())})
    await store.upsert(altered)
    with pytest.raises(SupportCaseContextAuthorityError):
        await service.ingest(
            "journey_links", TENANT, CONNECTION, event,
            actor_id=ACTOR, actor_type="tenant_user",
        )
    assert await store.get(TENANT, episode.episode_id) == altered


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["source_observed_at", "effective_at"])
async def test_future_journey_observations_cannot_produce_episodes(field):
    with pytest.raises(SupportCaseContextAuthorityError):
        await produce(**{field: datetime.now(timezone.utc) + timedelta(days=1)})
    assert await EpisodeStore().list_by_tenant(TENANT) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(("field", "value"), [
    ("connection_id", "foreign-connection"), ("tenant_id", "foreign-tenant"),
    ("provider_identity", "foreign-provider"), ("last_verified_at", "invalid"),
    ("last_verified_at", (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()),
])
async def test_journey_episode_ingress_rejects_wrong_verified_connection(field, value):
    _, _, _, _, service, event, _ = await produce()
    original = service._connections

    class WrongConnection:
        async def find(self, connection_id):
            connection = await original.find(connection_id)
            setattr(connection, field, value)
            return connection

    service._connections = WrongConnection()
    existing = await EpisodeStore().list_by_tenant(TENANT)
    with pytest.raises(SupportCaseContextAuthorityError):
        await service.ingest(
            "journey_links", TENANT, CONNECTION, event,
            actor_id=ACTOR, actor_type="tenant_user",
        )
    assert await EpisodeStore().list_by_tenant(TENANT) == existing


@pytest.mark.asyncio
@pytest.mark.parametrize("incomplete", ["truncated", "next_cursor", "invalid_records"])
async def test_episode_scan_incompleteness_clears_even_exact_relations(incomplete):
    *_, record = await produce()
    episode = (await EpisodeStore().list_by_tenant(TENANT))[0]
    event_ref = next(ref for ref in episode.evidence_refs if ref.source == "support_case_context_events")

    class Incomplete:
        async def list_page_by_tenant(self, *args, **kwargs):
            return EpisodePageRead(records=(episode,), **{
                "truncated": False, "next_cursor": None, "invalid_records": False,
                incomplete: {"truncated": True, "next_cursor": "next", "invalid_records": True}[incomplete],
            })

    slot, refs, reasons = await _validated_case_journey_episodes(
        tenant_id=TENANT, links=[{
            "canonicalJourneyId": episode.journey_id,
            "contextEventId": record["context_event_id"], "evidenceRefs": [event_ref],
        }], episode_store=Incomplete(), windowed=False,
    )
    assert slot["state"] == "unknown" and slot["relations"] == [] and refs == []
    assert "support_case_journey_episode_read_truncated" in reasons
