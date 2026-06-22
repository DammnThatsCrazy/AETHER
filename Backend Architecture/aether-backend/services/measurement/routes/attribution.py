"""Attribution runs, model configs, backfill, and model comparison endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, NotFoundError, BadRequestError
from shared.logger.logger import get_logger
from services.measurement.repositories.attribution_run_repo import AttributionRunRepository
from services.measurement.engine.attribution_engine import AttributionEngine

logger = get_logger("aether.measurement.routes.attribution")
router = APIRouter(prefix="/v1/attribution", tags=["Attribution"])

_run_repo = AttributionRunRepository()
_engine = AttributionEngine()

_SUPPORTED_MODELS = {
    "first_touch", "last_touch", "linear", "time_decay",
    "position_based", "data_driven", "actor_weighted", "exposure_aware",
}


def _require_tenant(request: Request):
    tenant = getattr(request.state, "tenant", None)
    if tenant is None:
        from shared.common.common import UnauthorizedError
        raise UnauthorizedError("Authentication required")
    return tenant


class RunAttributionRequest(BaseModel):
    conversion_id: str
    model_type: str = "last_touch"
    lookback_hours: int = Field(720, ge=1, le=8760)


class BackfillRequest(BaseModel):
    start_at: str = Field(..., description="ISO datetime")
    end_at: str = Field(..., description="ISO datetime")
    model_type: str = "last_touch"


class ModelComparisonRequest(BaseModel):
    model_a: str
    model_b: str
    conversion_ids: list[str] = Field(..., min_length=1, max_length=50)


@router.get("/runs")
async def list_attribution_runs(
    request: Request,
    conversion_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    cursor: Optional[str] = Query(None),
):
    tenant = _require_tenant(request)
    runs = await _run_repo.list_runs(
        tenant.tenant_id,
        conversion_id=conversion_id,
        status=status,
        limit=limit,
        cursor=cursor,
    )
    next_cursor = runs[-1].get("created_at") if len(runs) == limit else None
    return {
        "data": runs,
        "pagination": {
            "limit": limit,
            "next_cursor": next_cursor,
            "has_more": next_cursor is not None,
        },
    }


@router.get("/runs/{run_id}")
async def get_attribution_run(run_id: str, request: Request):
    tenant = _require_tenant(request)
    run = await _run_repo.get_run(run_id, tenant_id=tenant.tenant_id)
    if run is None:
        raise NotFoundError("Attribution run")
    credits = await _run_repo.list_credits_for_run(tenant.tenant_id, run_id)
    return APIResponse(data={
        "run": run,
        "credits": credits,
        "credit_count": len(credits),
    }).to_dict()


@router.post("/runs")
async def trigger_attribution_run(request: Request, body: RunAttributionRequest):
    tenant = _require_tenant(request)
    if body.model_type not in _SUPPORTED_MODELS:
        raise BadRequestError(
            f"Unknown model_type '{body.model_type}'. "
            f"Supported: {sorted(_SUPPORTED_MODELS)}"
        )
    try:
        run = await _engine.run_for_conversion(
            tenant.tenant_id,
            body.conversion_id,
            model_type=body.model_type,
            lookback_hours=body.lookback_hours,
            trigger_reason="api_triggered",
        )
    except ValueError as exc:
        raise BadRequestError(str(exc))
    return APIResponse(data=run, meta={"triggered": True}).to_dict()


@router.post("/backfills")
async def schedule_backfill(request: Request, body: BackfillRequest):
    tenant = _require_tenant(request)
    if body.model_type not in _SUPPORTED_MODELS:
        raise BadRequestError(f"Unknown model_type '{body.model_type}'")

    try:
        start_at = datetime.fromisoformat(body.start_at.replace("Z", "+00:00"))
        end_at = datetime.fromisoformat(body.end_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BadRequestError(f"Invalid datetime format: {exc}")

    if (end_at - start_at).days > 365:
        raise BadRequestError("Backfill window cannot exceed 365 days")

    result = await _engine.run_backfill(
        tenant.tenant_id,
        start_at=start_at,
        end_at=end_at,
        model_type=body.model_type,
    )
    return APIResponse(data=result).to_dict()


@router.get("/model-comparisons")
async def compare_models(request: Request, body: ModelComparisonRequest):
    tenant = _require_tenant(request)
    for model in (body.model_a, body.model_b):
        if model not in _SUPPORTED_MODELS:
            raise BadRequestError(f"Unknown model '{model}'")

    result = await _engine.compare_models(
        tenant.tenant_id,
        body.model_a,
        body.model_b,
        body.conversion_ids,
    )
    return APIResponse(data=result).to_dict()
