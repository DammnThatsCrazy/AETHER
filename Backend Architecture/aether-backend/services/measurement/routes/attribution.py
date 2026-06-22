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
    "markov", "shapley_heuristic",
}

# In-memory config store for AETHER_ENV=local; production uses attribution_model_configs table.
_model_configs: dict[str, list[dict]] = {}


def _get_tenant_configs(tenant_id: str) -> list[dict]:
    return _model_configs.get(tenant_id, [])


def _require_tenant(request: Request):
    tenant = getattr(request.state, "tenant", None)
    if tenant is None:
        from shared.common.common import UnauthorizedError
        raise UnauthorizedError("Authentication required")
    return tenant


class ModelConfigRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    model_type: str
    model_version: str = "1.0"
    conversion_types: list[str] = Field(default_factory=lambda: ["all"])
    click_lookback_window: int = Field(720, ge=1, le=8760)
    view_lookback_window: int = Field(168, ge=1, le=8760)
    session_timeout_seconds: int = Field(1800, ge=60, le=86400)
    direct_traffic_policy: str = "include"
    identity_confidence_min: float = Field(0.5, ge=0.0, le=1.0)
    fraud_policy: str = "exclude"
    status: str = "active"


class RunAttributionRequest(BaseModel):
    conversion_id: str
    model_type: str = "last_touch"
    model_config_id: Optional[str] = None
    lookback_hours: int = Field(720, ge=1, le=8760)


class BackfillRequest(BaseModel):
    start_at: str = Field(..., description="ISO datetime")
    end_at: str = Field(..., description="ISO datetime")
    model_type: str = "last_touch"


class ModelComparisonRequest(BaseModel):
    model_a: str
    model_b: str
    conversion_ids: list[str] = Field(..., min_length=1, max_length=50)


@router.get("/configurations")
async def list_model_configs(request: Request):
    tenant = _require_tenant(request)
    configs = _get_tenant_configs(tenant.tenant_id)
    return APIResponse(data=configs, meta={"count": len(configs), "supported_models": sorted(_SUPPORTED_MODELS)}).to_dict()


@router.post("/configurations")
async def create_model_config(request: Request, body: ModelConfigRequest):
    import uuid
    from datetime import datetime, timezone
    tenant = _require_tenant(request)
    if body.model_type not in _SUPPORTED_MODELS:
        raise BadRequestError(
            f"Unknown model_type '{body.model_type}'. Supported: {sorted(_SUPPORTED_MODELS)}"
        )
    config = {
        "model_config_id": str(uuid.uuid4()),
        "tenant_id": tenant.tenant_id,
        "name": body.name,
        "model_type": body.model_type,
        "model_version": body.model_version,
        "conversion_types": body.conversion_types,
        "click_lookback_window": body.click_lookback_window,
        "view_lookback_window": body.view_lookback_window,
        "session_timeout_seconds": body.session_timeout_seconds,
        "direct_traffic_policy": body.direct_traffic_policy,
        "identity_confidence_min": body.identity_confidence_min,
        "fraud_policy": body.fraud_policy,
        "status": body.status,
        "effective_from": datetime.now(timezone.utc).isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _model_configs.setdefault(tenant.tenant_id, []).append(config)
    logger.info(
        "Attribution model config created: tenant=%s model_type=%s name=%s",
        tenant.tenant_id, body.model_type, body.name,
    )
    return APIResponse(data=config, meta={"created": True}).to_dict()


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


@router.post("/model-comparisons")
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


@router.get("/models")
async def list_available_models(request: Request):
    _require_tenant(request)
    models = []
    for name in sorted(_SUPPORTED_MODELS):
        is_algorithmic = name in ("markov", "shapley_heuristic")
        models.append({
            "name": name,
            "type": "algorithmic" if is_algorithmic else "heuristic",
            "description": _MODEL_DESCRIPTIONS.get(name, ""),
        })
    return APIResponse(data=models).to_dict()


_MODEL_DESCRIPTIONS: dict[str, str] = {
    "first_touch": "100% credit to the first touchpoint in the journey.",
    "last_touch": "100% credit to the last touchpoint before conversion.",
    "linear": "Equal credit distributed across all touchpoints.",
    "time_decay": "Exponential decay — more recent touchpoints receive more credit.",
    "position_based": "40% first, 40% last, 20% distributed across middle touchpoints.",
    "data_driven": "Shapley-value approximation using heuristic coalition values.",
    "actor_weighted": "U-shaped with human/agent actor splitting per touchpoint.",
    "exposure_aware": "View-through weighted by viewability and dwell time.",
    "markov": "Removal-effect Markov chain — trained on historical journey paths.",
    "shapley_heuristic": "Honest alias for data_driven (Shapley heuristic).",
}
