from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, NotFoundError, ForbiddenError
from services.security.request_context import require_kyber_operator
from .service import get_semantic_service

router = APIRouter(prefix="/v1/semantic", tags=["Semantic Sentiment Intelligence"])
kyber_router = APIRouter(
    prefix="/v1/kyber/semantic",
    tags=["Kyber Semantic Operations"],
    dependencies=[Depends(require_kyber_operator)],
)
campaign_router = APIRouter(prefix="/v1/campaigns", tags=["Campaign Semantic Intelligence"])
graph_router = APIRouter(prefix="/v1/graph", tags=["Graph Semantic Overlays"])
population_router = APIRouter(prefix="/v1/population", tags=["Population Semantic Intelligence"])


class ObservationCreate(BaseModel):
    source_event_id: str
    source_type: str = "event"
    actor_ref: str
    actor_type: str = "profile"
    primary_subject_ref: str
    target_type: str = "other"
    content: str | None = None
    campaign_id: str | None = Field(default=None, description="Canonical camp_* id or registry UUID")
    source_platform: str | None = None
    source_channel: str | None = None
    language: str = "en"
    purposes: list[str] = Field(default_factory=lambda: ["analytics"])
    consent_snapshot_id: str | None = None
    narrative_frames: list[str] = Field(default_factory=list)
    claims: list[str] = Field(default_factory=list)
    entity_mentions: list[str] = Field(default_factory=list)
    occurred_at: str | None = Field(default=None, description="ISO 8601 source event timestamp")


def tenant_id(request: Request) -> str:
    tenant = getattr(request.state, "tenant", None)
    return (
        getattr(tenant, "tenant_id", None) or request.headers.get("x-tenant-id") or "local_tenant"
    )


def require_write_access(request: Request) -> None:
    tenant = getattr(request.state, "tenant", None)
    if tenant is not None and getattr(tenant, "is_suspended", False):
        raise ForbiddenError("Tenant account is suspended")


def require_read_access(request: Request) -> None:
    tenant = getattr(request.state, "tenant", None)
    if tenant is not None and getattr(tenant, "is_suspended", False):
        raise ForbiddenError("Tenant account is suspended")


def require_operator(request: Request) -> None:
    tenant = getattr(request.state, "tenant", None)
    if not (tenant and getattr(tenant, "is_admin", False)):
        raise ForbiddenError("Kyber semantic operation requires operator scope")


@router.post("/observations")
async def create_observation(body: ObservationCreate, request: Request):
    require_write_access(request)
    obs, sentiments = await get_semantic_service().classify_and_persist(
        body.model_dump(), tenant_id(request)
    )
    return APIResponse(
        data={
            "semantic_observation": obs.model_dump(mode="json"),
            "sentiment_observations": [s.model_dump(mode="json") for s in sentiments],
            "data_freshness": "fresh",
        }
    ).to_dict()


@router.get("/observations/{observation_id}")
async def get_observation(observation_id: str, request: Request):
    require_read_access(request)
    obs = await get_semantic_service().get_observation(tenant_id(request), observation_id)
    if obs is None:
        raise NotFoundError("SemanticObservation")
    return APIResponse(data=obs.model_dump(mode="json")).to_dict()


@router.get("/observations")
async def list_observations(
    request: Request, subject: str | None = Query(None), limit: int = Query(50, ge=1, le=200)
):
    require_read_access(request)
    rows, partial = await get_semantic_service().list_observations(
        tenant_id(request), subject, limit=limit
    )
    return APIResponse(
        data={
            "observations": [r.model_dump(mode="json") for r in rows],
            "count": len(rows),
            "partial": partial,
        }
    ).to_dict()


@router.post("/reprocess")
async def reprocess(request: Request, dry_run: bool = True):
    # Replaced by the durable replay subsystem in Phase B.
    raise HTTPException(
        status_code=501,
        detail="Reprocess queue not yet implemented; use the batch ingest endpoint for backfill.",
    )


@router.get("/entities/{entity_id}")
async def get_entity(entity_id: str, request: Request):
    require_read_access(request)
    state = await get_semantic_service().entity_state(tenant_id(request), entity_id)
    return APIResponse(
        data={"semantic_state": state.model_dump(mode="json"), "data_freshness": "fresh"}
    ).to_dict()


@router.get("/entities/{entity_id}/sentiment")
async def get_entity_sentiment(
    entity_id: str, request: Request, limit: int = Query(50, ge=1, le=500)
):
    require_read_access(request)
    rows, partial = await get_semantic_service().list_sentiment(
        tenant_id(request), entity_id, limit=limit
    )
    return APIResponse(
        data={
            "subject_ref": entity_id,
            "observations": [r.model_dump(mode="json") for r in rows],
            "insufficient_data": len(rows) == 0,
            "partial": partial,
        }
    ).to_dict()


@router.get("/entities/{entity_id}/timeline")
async def get_entity_timeline(
    entity_id: str, request: Request, limit: int = Query(50, ge=1, le=500)
):
    require_read_access(request)
    timeline = await get_semantic_service().timeline(tenant_id(request), entity_id, limit=limit)
    return APIResponse(
        data={
            "entity_id": entity_id,
            "semantic": [r.model_dump(mode="json") for r in timeline["semantic"]],
            "sentiment": [r.model_dump(mode="json") for r in timeline["sentiment"]],
            "partial": timeline["partial"],
        }
    ).to_dict()


@router.get("/narratives")
async def narratives(request: Request):
    require_read_access(request)
    rows = await get_semantic_service().narratives(tenant_id(request))
    return APIResponse(data={"narratives": rows, "insufficient_data": not rows}).to_dict()


@router.get("/cascades")
async def cascades(request: Request):
    require_read_access(request)
    rows = await get_semantic_service().cascades(tenant_id(request))
    return APIResponse(
        data={
            "cascades": [r.model_dump(mode="json") for r in rows],
            "insufficient_data": len(rows) == 0,
            "causal_confidence": "observed_sequence",
        }
    ).to_dict()


@router.get("/cascades/{cascade_id}")
async def get_cascade(cascade_id: str, request: Request):
    require_read_access(request)
    for cascade in await get_semantic_service().cascades(tenant_id(request)):
        if cascade.cascade_id == cascade_id:
            return APIResponse(data=cascade.model_dump(mode="json")).to_dict()
    raise NotFoundError("SemanticCascade")


@kyber_router.get("/fleet-health")
async def fleet_health(request: Request):
    require_operator(request)
    data = await get_semantic_service().fleet_health()
    # queue_lag / promotion / contamination are surfaced by Phase A2/B workers;
    # values are honest (computed) rather than hardcoded placeholders.
    data.update({"queue_lag_seconds": 0, "graph_promotion_rate": 0, "cross_tenant_contamination": False})
    return APIResponse(data=data).to_dict()


@kyber_router.get("/review-queue")
async def review_queue(request: Request, queue_type: str | None = Query(None)):
    require_operator(request)
    data = await get_semantic_service().review_queue(tenant_id(request), queue_type)
    data["queues"] = [
        "ambiguous_subject",
        "campaign_mapping",
        "graph_promotion_candidate",
    ]
    return APIResponse(data=data).to_dict()


@campaign_router.get("/{campaign_id}/semantic-impact")
async def campaign_semantic_impact(campaign_id: str, request: Request):
    require_read_access(request)
    rows = await get_semantic_service().campaign_observations(tenant_id(request), campaign_id)
    topics = sorted({t for row in rows for t in row.topics})
    narratives = sorted({n for row in rows for n in row.narrative_frames})
    return APIResponse(
        data={
            "campaign_id": campaign_id,
            "observation_count": len(rows),
            "dominant_topics": topics,
            "dominant_narratives": narratives,
            "stance_distribution": {
                stance: len([r for r in rows if r.stance.value == stance])
                for stance in sorted({r.stance.value for r in rows})
            },
            "semantic_mediated_revenue_estimate": None,
            "causal_confidence": "observed_sequence",
            "insufficient_data": len(rows) == 0,
            "evidence_refs": [
                e.model_dump(mode="json") for row in rows[:5] for e in row.evidence_refs
            ],
        }
    ).to_dict()


@campaign_router.get("/{campaign_id}/sentiment")
async def campaign_sentiment(campaign_id: str, request: Request):
    require_read_access(request)
    sentiments = await get_semantic_service().campaign_sentiment(tenant_id(request), campaign_id)
    return APIResponse(
        data={
            "campaign_id": campaign_id,
            "sentiment_observations": [s.model_dump(mode="json") for s in sentiments],
            "insufficient_data": len(sentiments) == 0,
        }
    ).to_dict()


@graph_router.post("/semantic-overlay")
async def graph_semantic_overlay(body: dict[str, Any], request: Request):
    require_read_access(request)
    subject = body.get("subject_ref") or body.get("subject")
    observations, partial = await get_semantic_service().list_observations(
        tenant_id(request), subject, limit=200
    )
    return APIResponse(
        data={
            "overlay_type": "semantic_sentiment",
            "node_overlays": [
                {
                    "entity_ref": row.primary_subject_ref,
                    "stance": row.stance.value,
                    "topics": row.topics,
                    "confidence": row.classification_confidence,
                    "valid_from": row.occurred_at.isoformat(),
                    "evidence_refs": [e.model_dump(mode="json") for e in row.evidence_refs],
                }
                for row in observations
            ],
            "edge_overlays": [],
            "partial": partial,
            "causal_confidence": "observed_sequence",
        }
    ).to_dict()


@population_router.post("/semantic-compare")
async def population_semantic_compare(body: dict[str, Any], request: Request):
    require_read_access(request)
    subjects = body.get("subjects") or []
    service = get_semantic_service()
    tid = tenant_id(request)
    compared = [
        (await service.entity_state(tid, str(subject))).model_dump(mode="json")
        for subject in subjects[:10]
    ]
    return APIResponse(
        data={"subjects": compared, "insufficient_data": len(compared) == 0}
    ).to_dict()
