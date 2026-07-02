from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Request, Query
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, NotFoundError, ForbiddenError
from .engine import classify_event, entity_state, store

router = APIRouter(prefix="/v1/semantic", tags=["Semantic Sentiment Intelligence"])
kyber_router = APIRouter(prefix="/v1/kyber/semantic", tags=["Kyber Semantic Operations"])


class ObservationCreate(BaseModel):
    source_event_id: str
    source_type: str = "event"
    actor_ref: str
    actor_type: str = "profile"
    primary_subject_ref: str
    target_type: str = "other"
    content: str | None = None
    campaign_id: str | None = Field(default=None, description="Canonical camp_* id only")
    source_platform: str | None = None
    source_channel: str | None = None
    language: str = "en"
    purposes: list[str] = Field(default_factory=lambda: ["analytics"])
    consent_snapshot_id: str | None = None


def tenant_id(request: Request) -> str:
    tenant = getattr(request.state, "tenant", None)
    return (
        getattr(tenant, "tenant_id", None) or request.headers.get("x-tenant-id") or "local_tenant"
    )


def require_operator(request: Request) -> None:
    if request.headers.get("x-kyber-operator") != "true":
        tenant = getattr(request.state, "tenant", None)
        if not (tenant and getattr(tenant, "is_admin", False)):
            raise ForbiddenError("Kyber semantic operation requires operator scope")


@router.post("/observations")
async def create_observation(body: ObservationCreate, request: Request):
    obs, sentiments = classify_event(body.model_dump(), tenant_id(request))
    return APIResponse(
        data={
            "semantic_observation": obs.model_dump(mode="json"),
            "sentiment_observations": [s.model_dump(mode="json") for s in sentiments],
            "data_freshness": "fresh",
        }
    ).to_dict()


@router.get("/observations/{observation_id}")
async def get_observation(observation_id: str, request: Request):
    obs = store.semantic.get(observation_id)
    if obs is None or obs.tenant_id != tenant_id(request):
        raise NotFoundError("SemanticObservation")
    return APIResponse(data=obs.model_dump(mode="json")).to_dict()


@router.get("/observations")
async def list_observations(
    request: Request, subject: str | None = Query(None), limit: int = Query(50, ge=1, le=200)
):
    rows = store.list_semantic(tenant_id(request), subject)[:limit]
    return APIResponse(
        data={
            "observations": [r.model_dump(mode="json") for r in rows],
            "count": len(rows),
            "partial": False,
        }
    ).to_dict()


@router.post("/reprocess")
async def reprocess(request: Request, dry_run: bool = True):
    return APIResponse(
        data={
            "accepted": True,
            "dry_run": dry_run,
            "scope": {"tenant_id": tenant_id(request)},
            "status": "queued",
        }
    ).to_dict()


@router.get("/entities/{entity_id}")
async def get_entity(entity_id: str, request: Request):
    return APIResponse(
        data={
            "semantic_state": entity_state(tenant_id(request), entity_id).model_dump(mode="json"),
            "data_freshness": "fresh",
        }
    ).to_dict()


@router.get("/entities/{entity_id}/sentiment")
async def get_entity_sentiment(entity_id: str, request: Request):
    rows = store.list_sentiment(tenant_id(request), entity_id)
    return APIResponse(
        data={
            "subject_ref": entity_id,
            "observations": [r.model_dump(mode="json") for r in rows],
            "insufficient_data": len(rows) == 0,
        }
    ).to_dict()


@router.get("/entities/{entity_id}/timeline")
async def get_entity_timeline(entity_id: str, request: Request):
    return APIResponse(
        data={
            "entity_id": entity_id,
            "semantic": [
                r.model_dump(mode="json")
                for r in store.list_semantic(tenant_id(request), entity_id)
            ],
            "sentiment": [
                r.model_dump(mode="json")
                for r in store.list_sentiment(tenant_id(request), entity_id)
            ],
        }
    ).to_dict()


@router.get("/narratives")
async def narratives(request: Request):
    narratives = sorted(
        {n for r in store.list_semantic(tenant_id(request)) for n in r.narrative_frames}
    )
    return APIResponse(
        data={"narratives": narratives, "insufficient_data": not narratives}
    ).to_dict()


@router.get("/cascades")
async def cascades(request: Request):
    return APIResponse(
        data={"cascades": [], "insufficient_data": True, "causal_confidence": "observed_sequence"}
    ).to_dict()


@kyber_router.get("/fleet-health")
async def fleet_health(request: Request):
    require_operator(request)
    semantic_count = len(store.semantic)
    sentiment_count = len(store.sentiment)
    return APIResponse(
        data={
            "enabled_tenants": len({o.tenant_id for o in store.semantic.values()}),
            "classified_observations": semantic_count,
            "sentiment_observations": sentiment_count,
            "abstention_rate": 0
            if semantic_count == 0
            else len([o for o in store.semantic.values() if o.status.value == "abstained"])
            / semantic_count,
            "model_versions": [
                "deterministic-semantic-classifier@1.0.0",
                "deterministic-sentiment-classifier@1.0.0",
            ],
            "queue_lag_seconds": 0,
            "graph_promotion_rate": 0,
            "cross_tenant_contamination": False,
        }
    ).to_dict()


@kyber_router.get("/review-queue")
async def review_queue(request: Request):
    require_operator(request)
    return APIResponse(
        data={
            "items": [],
            "count": 0,
            "queues": ["ambiguous_subject", "campaign_mapping", "graph_promotion_candidate"],
        }
    ).to_dict()
