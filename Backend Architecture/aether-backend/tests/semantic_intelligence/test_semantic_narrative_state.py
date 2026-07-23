"""Phase C — durable per-narrative Gold state.

Replaces the flat distinct-frames list as the only narrative surface: each
narrative_frame gets a weighted aggregate (supporting count, stance
distribution, first/last observed, momentum) persisted to gold_narrative_state,
while the flat list stays served for backward compatibility.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from repositories.repos import reset_in_memory_stores
from services.semantic_intelligence import service as service_mod
from services.semantic_intelligence.engine import get_store, set_store
from services.semantic_intelligence.models import (
    EvidenceRef,
    IntentLabel,
    SemanticObservation,
    StanceLabel,
    SubjectType,
    utc_now,
)
from services.semantic_intelligence.reducers import (
    REDUCER_VERSION,
    recompute_narrative_states,
    reduce_narrative_state,
)
from services.semantic_intelligence.repositories.base_fact_repo import SemanticFactRepository
from services.semantic_intelligence.routes import router
from services.semantic_intelligence.service import SemanticIntelligenceService
from services.semantic_intelligence.store import DurableSemanticSentimentStore
from shared.common.common import AetherError

TENANT = "tenant_narrative"
FRAME = "privacy_first"


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


def _obs(
    actor: str,
    stance: StanceLabel,
    *,
    frames: list[str] | None = None,
    conf: float = 0.9,
    age_days: float = 0.0,
) -> SemanticObservation:
    return SemanticObservation(
        tenant_id=TENANT,
        source_event_id=f"e_{actor}_{stance.value}_{age_days}",
        source_type="feedback",
        actor_ref=actor,
        actor_type=SubjectType.PROFILE,
        primary_subject_ref="prod_narr",
        target_type=SubjectType.PRODUCT,
        narrative_frames=frames if frames is not None else [FRAME],
        stance=stance,
        intent=IntentLabel.EVALUATE,
        classification_confidence=conf,
        occurred_at=utc_now() - timedelta(days=age_days),
        evidence_refs=[EvidenceRef(evidence_id="e", source_type="event", source_ref="e")],
    )


def test_empty_input_produces_no_states():
    assert reduce_narrative_state(TENANT, []) == []


def test_per_narrative_aggregates():
    obs = [
        _obs("a1", StanceLabel.SUPPORTIVE, frames=[FRAME, "speed_matters"]),
        _obs("a2", StanceLabel.SUPPORTIVE, frames=[FRAME], age_days=1),
    ]
    states = reduce_narrative_state(TENANT, obs)
    by_ref = {s["narrative_ref"]: s for s in states}
    assert set(by_ref) == {FRAME, "speed_matters"}
    frame = by_ref[FRAME]
    assert frame["observation_count"] == 2
    assert frame["unique_actor_count"] == 2
    assert abs(sum(frame["stance_distribution"].values()) - 1.0) < 0.05
    assert frame["first_observed_at"] < frame["last_observed_at"]
    assert frame["reducer_version"] == REDUCER_VERSION


def test_weighting_higher_confidence_dominates():
    states = reduce_narrative_state(
        TENANT,
        [
            _obs("a1", StanceLabel.SUPPORTIVE, conf=0.95),
            _obs("a2", StanceLabel.OPPOSED, conf=0.2),
        ],
    )
    distribution = states[0]["stance_distribution"]
    assert distribution["supportive"] > distribution["opposed"]


def test_momentum_reflects_recent_vs_prior_window():
    # Two fresh observations vs one in the prior window → positive momentum.
    states = reduce_narrative_state(
        TENANT,
        [
            _obs("a1", StanceLabel.SUPPORTIVE, age_days=0),
            _obs("a2", StanceLabel.SUPPORTIVE, age_days=1),
            _obs("a3", StanceLabel.SUPPORTIVE, age_days=10),
        ],
    )
    state = states[0]
    assert state["recent_weight"] > state["prior_weight"] > 0
    assert state["momentum"] > 0


async def test_gold_narrative_persisted_and_served():
    store = get_store()
    await store.put_semantic(_obs("a1", StanceLabel.SUPPORTIVE))
    states = await recompute_narrative_states(TENANT)
    assert len(states) == 1

    gold = await SemanticFactRepository("gold_narrative_state").list_by_tenant(TENANT, FRAME)
    assert gold and gold[0]["reducer_version"] == REDUCER_VERSION

    served = await service_mod.get_semantic_service().narrative_states(TENANT)
    assert served and served[0]["narrative_ref"] == FRAME


async def test_no_frames_persists_no_rows():
    states = await recompute_narrative_states(TENANT)
    assert states == []
    assert await SemanticFactRepository("gold_narrative_state").list_by_tenant(TENANT) == []


def test_narratives_route_serves_flat_list_and_states():
    app = FastAPI()

    @app.exception_handler(AetherError)
    async def aether_error_handler(request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=exc.code.value, content=exc.to_dict())

    app.include_router(router)
    client = TestClient(app)
    headers = {"x-tenant-id": TENANT}
    created = client.post(
        "/v1/semantic/observations",
        json={
            "source_event_id": "evt_narr_1",
            "source_type": "social_post",
            "actor_ref": "profile_a",
            "primary_subject_ref": "prod_narr",
            "target_type": "product",
            "content": "I support this product",
            "narrative_frames": [FRAME],
        },
        headers=headers,
    )
    assert created.status_code == 200

    response = client.get("/v1/semantic/narratives", headers=headers)
    assert response.status_code == 200
    data = response.json()["data"]
    # Backward-compatible flat list plus the durable Gold aggregates.
    assert data["narratives"] == [FRAME]
    assert data["states"][0]["narrative_ref"] == FRAME
    assert data["states"][0]["reducer_version"] == REDUCER_VERSION
    assert data["insufficient_data"] is False
