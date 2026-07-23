"""Phase C — Gold episodization of a subject's observation stream.

Time-ordered observations split into episodes on a quiet gap > EPISODE_GAP or a
dominant-stance sign flip; each episode carries type, bounds, observation count
and entry/exit weighted sentiment, durably persisted to gold_semantic_episodes
with content-derived ids (idempotent refresh) and served over the entity route.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from repositories.repos import reset_in_memory_stores
from services.semantic_intelligence import service as service_mod
from services.semantic_intelligence.engine import classify_event, get_store, set_store
from services.semantic_intelligence.models import (
    EvidenceRef,
    IntentLabel,
    SemanticObservation,
    StanceLabel,
    SubjectType,
    utc_now,
)
from services.semantic_intelligence.reducers import (
    EPISODE_GAP,
    REDUCER_VERSION,
    recompute_episodes,
    reduce_episodes,
)
from services.semantic_intelligence.repositories.base_fact_repo import SemanticFactRepository
from services.semantic_intelligence.routes import router
from services.semantic_intelligence.service import SemanticIntelligenceService
from services.semantic_intelligence.store import DurableSemanticSentimentStore
from shared.common.common import AetherError

TENANT = "tenant_episode"
SUBJECT = "prod_episode"


@pytest.fixture(autouse=True)
def _isolate():
    reset_in_memory_stores()
    original = get_store()
    set_store(DurableSemanticSentimentStore())
    service_mod.set_semantic_service(SemanticIntelligenceService())
    yield
    set_store(original)
    service_mod.set_semantic_service(SemanticIntelligenceService())
    reset_in_memory_stores()


def _obs(stance: StanceLabel, *, conf: float = 0.9, age_days: float = 0.0) -> SemanticObservation:
    return SemanticObservation(
        tenant_id=TENANT,
        source_event_id=f"e_{stance.value}_{age_days}",
        source_type="feedback",
        actor_ref="profile_e",
        actor_type=SubjectType.PROFILE,
        primary_subject_ref=SUBJECT,
        target_type=SubjectType.PRODUCT,
        stance=stance,
        intent=IntentLabel.EVALUATE,
        classification_confidence=conf,
        occurred_at=utc_now() - timedelta(days=age_days),
        evidence_refs=[EvidenceRef(evidence_id="e", source_type="event", source_ref="e")],
    )


async def _seed(content: str, *, age_days: float, event_id: str):
    obs, sentiments = classify_event(
        {
            "source_event_id": event_id,
            "source_type": "feedback",
            "actor_ref": "profile_e",
            "primary_subject_ref": SUBJECT,
            "content": content,
            "occurred_at": (utc_now() - timedelta(days=age_days)).isoformat(),
        },
        TENANT,
    )
    store = get_store()
    await store.put_semantic(obs)
    for s in sentiments:
        await store.put_sentiment(s)


def test_empty_input_produces_no_episodes():
    assert reduce_episodes(TENANT, SUBJECT, [], []) == []


def test_quiet_gap_splits_episodes():
    obs = [_obs(StanceLabel.SUPPORTIVE, age_days=10), _obs(StanceLabel.SUPPORTIVE, age_days=0)]
    episodes = reduce_episodes(TENANT, SUBJECT, obs)
    assert len(episodes) == 2  # 10-day silence > EPISODE_GAP
    assert episodes[0].end_at < episodes[1].start_at
    assert episodes[0].status == "closed" and episodes[1].status == "active"
    assert (episodes[1].start_at - episodes[0].end_at) > EPISODE_GAP


def test_stance_sign_flip_splits_episodes():
    obs = [_obs(StanceLabel.SUPPORTIVE, age_days=2), _obs(StanceLabel.OPPOSED, age_days=1)]
    episodes = reduce_episodes(TENANT, SUBJECT, obs)
    assert len(episodes) == 2  # advocacy → grievance is a new arc
    assert episodes[0].episode_type == "advocacy"
    assert episodes[1].episode_type == "grievance"
    assert all(e.observation_refs for e in episodes)


def test_weighted_confidence_dominated_by_higher_confidence():
    obs = [
        _obs(StanceLabel.SUPPORTIVE, conf=0.9, age_days=1),
        _obs(StanceLabel.SUPPORTIVE, conf=0.3, age_days=0),
    ]
    (episode,) = reduce_episodes(TENANT, SUBJECT, obs)
    # Weight ∝ confidence, so the weighted mean exceeds the raw mean (0.6).
    assert episode.confidence > 0.6
    assert episode.episode_type == "advocacy"


async def test_entry_exit_sentiment_from_boundary_valence():
    await _seed("love this, great, excellent", age_days=2, event_id="e_start")
    await _seed("hate this, bad, terrible", age_days=0, event_id="e_end")
    (episode,) = await recompute_episodes(TENANT, SUBJECT)
    assert episode.sentiment_start_state["valence"] > 0
    assert episode.sentiment_end_state["valence"] < 0


async def test_gold_episodes_persisted_and_idempotent():
    await _seed("love this, great", age_days=1, event_id="e_g1")
    first = await recompute_episodes(TENANT, SUBJECT)
    second = await recompute_episodes(TENANT, SUBJECT)
    assert [e.episode_id for e in first] == [e.episode_id for e in second]

    gold = await SemanticFactRepository("gold_semantic_episodes").list_by_tenant(TENANT, SUBJECT)
    assert len(gold) == 1  # content-derived id → refreshed, not duplicated
    assert gold[0]["reducer_version"] == REDUCER_VERSION
    assert gold[0]["episode_id"] == first[0].episode_id


async def test_no_observations_persists_no_rows():
    episodes = await recompute_episodes(TENANT, SUBJECT)
    assert episodes == []
    assert await SemanticFactRepository("gold_semantic_episodes").list_by_tenant(TENANT, SUBJECT) == []
    assert await service_mod.get_semantic_service().episodes(TENANT, SUBJECT) == []


def _episode_app(tenant=None) -> TestClient:
    app = FastAPI()

    @app.exception_handler(AetherError)
    async def aether_error_handler(request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=exc.code.value, content=exc.to_dict())

    if tenant is not None:

        @app.middleware("http")
        async def _inject_tenant(request, call_next):
            request.state.tenant = tenant
            return await call_next(request)

    app.include_router(router)
    return TestClient(app)


def test_episodes_route_serves_gold():
    client = _episode_app()
    headers = {"x-tenant-id": TENANT}
    created = client.post(
        "/v1/semantic/observations",
        json={
            "source_event_id": "evt_ep_route",
            "source_type": "feedback",
            "actor_ref": "profile_e",
            "primary_subject_ref": SUBJECT,
            "target_type": "product",
            "content": "love this, great product",
        },
        headers=headers,
    )
    assert created.status_code == 200

    response = client.get(f"/v1/semantic/entities/{SUBJECT}/episodes", headers=headers)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["entity_id"] == SUBJECT
    assert data["insufficient_data"] is False
    assert data["episodes"][0]["reducer_version"] == REDUCER_VERSION

    empty = client.get("/v1/semantic/entities/ghost_subject/episodes", headers=headers)
    assert empty.json()["data"]["insufficient_data"] is True


def test_episodes_route_requires_same_read_access_as_siblings():
    from types import SimpleNamespace

    suspended = SimpleNamespace(tenant_id=TENANT, is_suspended=True)
    client = _episode_app(suspended)
    denied = client.get(f"/v1/semantic/entities/{SUBJECT}/episodes")
    assert denied.status_code == 403  # same require_read_access gate as siblings
