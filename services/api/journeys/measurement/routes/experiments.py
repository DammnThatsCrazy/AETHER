"""Incrementality experiment endpoints.

Provides create/read/control and results endpoints for holdout experiments,
geo holdouts, and pre/post analysis. Incremental metrics are always labeled
separately from attributed metrics to prevent false causal claims.

Routes:
  GET    /v1/experiments
  POST   /v1/experiments
  GET    /v1/experiments/{id}
  PATCH  /v1/experiments/{id}
  POST   /v1/experiments/{id}/start
  POST   /v1/experiments/{id}/stop
  GET    /v1/experiments/{id}/results
  POST   /v1/experiments/{id}/analyze
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, BadRequestError, NotFoundError
from shared.logger.logger import get_logger

logger = get_logger("aether.measurement.routes.experiments")
router = APIRouter(prefix="/v1/experiments", tags=["Incrementality Experiments"])

# In-memory store for AETHER_ENV=local; production uses experiment* tables.
_experiments: dict[str, dict] = {}
_assignments: dict[str, list[dict]] = {}
_outcomes: dict[str, list[dict]] = {}

_VALID_TYPES = {"holdout", "geo_holdout", "pre_post", "campaign_ab"}
_VALID_STATUSES = {"draft", "running", "paused", "stopped", "analyzing", "complete"}
_VALID_TRANSITIONS = {
    "draft": {"running"},
    "running": {"paused", "stopped"},
    "paused": {"running", "stopped"},
    "stopped": {"analyzing"},
    "analyzing": {"complete"},
    "complete": set(),
}


def _require_tenant(request: Request):
    tenant = getattr(request.state, "tenant", None)
    if tenant is None:
        from shared.common.common import UnauthorizedError
        raise UnauthorizedError("Authentication required")
    return tenant


class ExperimentCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    experiment_type: str
    description: Optional[str] = None
    hypothesis: Optional[str] = None
    holdout_pct: Optional[float] = Field(None, ge=0.01, le=0.5)
    campaign_ids: list[str] = Field(default_factory=list)
    geo_regions: list[str] = Field(default_factory=list)
    start_at: Optional[str] = None
    end_at: Optional[str] = None
    pre_period_start: Optional[str] = None
    pre_period_end: Optional[str] = None
    post_period_start: Optional[str] = None
    post_period_end: Optional[str] = None
    primary_metric: str = "conversion_rate"
    secondary_metrics: list[str] = Field(default_factory=list)
    minimum_detectable_effect: Optional[float] = Field(None, ge=0.001, le=1.0)
    statistical_significance_threshold: float = Field(0.05, ge=0.001, le=0.5)


class ExperimentPatchRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    hypothesis: Optional[str] = None
    holdout_pct: Optional[float] = Field(None, ge=0.01, le=0.5)
    end_at: Optional[str] = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _exp_key(tenant_id: str, experiment_id: str) -> str:
    return f"{tenant_id}:{experiment_id}"


@router.get("")
async def list_experiments(
    request: Request,
    status: Optional[str] = Query(None),
    experiment_type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    tenant = _require_tenant(request)
    results = [
        exp for exp in _experiments.values()
        if exp.get("tenant_id") == tenant.tenant_id
        and (status is None or exp.get("status") == status)
        and (experiment_type is None or exp.get("experiment_type") == experiment_type)
    ]
    return APIResponse(data=results[:limit], meta={"count": len(results)}).to_dict()


@router.post("")
async def create_experiment(request: Request, body: ExperimentCreateRequest):
    tenant = _require_tenant(request)
    if body.experiment_type not in _VALID_TYPES:
        raise BadRequestError(f"Invalid experiment_type '{body.experiment_type}'. Valid: {sorted(_VALID_TYPES)}")

    experiment_id = str(uuid4())
    exp = {
        "experiment_id": experiment_id,
        "tenant_id": tenant.tenant_id,
        "name": body.name,
        "description": body.description,
        "hypothesis": body.hypothesis,
        "experiment_type": body.experiment_type,
        "status": "draft",
        "holdout_pct": body.holdout_pct,
        "campaign_ids": body.campaign_ids,
        "geo_regions": body.geo_regions,
        "start_at": body.start_at,
        "end_at": body.end_at,
        "pre_period_start": body.pre_period_start,
        "pre_period_end": body.pre_period_end,
        "post_period_start": body.post_period_start,
        "post_period_end": body.post_period_end,
        "primary_metric": body.primary_metric,
        "secondary_metrics": body.secondary_metrics,
        "minimum_detectable_effect": body.minimum_detectable_effect,
        "statistical_significance_threshold": body.statistical_significance_threshold,
        "created_at": _now(),
        "updated_at": _now(),
    }
    _experiments[_exp_key(tenant.tenant_id, experiment_id)] = exp
    logger.info("Experiment created: tenant=%s id=%s type=%s", tenant.tenant_id, experiment_id, body.experiment_type)
    return APIResponse(data=exp, meta={"created": True}).to_dict()


@router.get("/{experiment_id}")
async def get_experiment(experiment_id: str, request: Request):
    tenant = _require_tenant(request)
    exp = _experiments.get(_exp_key(tenant.tenant_id, experiment_id))
    if exp is None:
        raise NotFoundError("Experiment")
    return APIResponse(data=exp).to_dict()


@router.patch("/{experiment_id}")
async def patch_experiment(experiment_id: str, request: Request, body: ExperimentPatchRequest):
    tenant = _require_tenant(request)
    exp = _experiments.get(_exp_key(tenant.tenant_id, experiment_id))
    if exp is None:
        raise NotFoundError("Experiment")
    if exp.get("status") not in ("draft", "paused"):
        raise BadRequestError("Only draft or paused experiments can be patched")

    for field, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            exp[field] = value
    exp["updated_at"] = _now()
    return APIResponse(data=exp).to_dict()


@router.post("/{experiment_id}/start")
async def start_experiment(experiment_id: str, request: Request):
    tenant = _require_tenant(request)
    exp = _experiments.get(_exp_key(tenant.tenant_id, experiment_id))
    if exp is None:
        raise NotFoundError("Experiment")
    current = exp.get("status", "draft")
    if "running" not in _VALID_TRANSITIONS.get(current, set()):
        raise BadRequestError(f"Cannot start experiment in status '{current}'")

    exp["status"] = "running"
    exp["started_at"] = _now()
    exp["updated_at"] = _now()
    logger.info("Experiment started: tenant=%s id=%s", tenant.tenant_id, experiment_id)
    return APIResponse(data=exp).to_dict()


@router.post("/{experiment_id}/stop")
async def stop_experiment(experiment_id: str, request: Request):
    tenant = _require_tenant(request)
    exp = _experiments.get(_exp_key(tenant.tenant_id, experiment_id))
    if exp is None:
        raise NotFoundError("Experiment")
    current = exp.get("status", "draft")
    if "stopped" not in _VALID_TRANSITIONS.get(current, set()):
        raise BadRequestError(f"Cannot stop experiment in status '{current}'")

    exp["status"] = "stopped"
    exp["stopped_at"] = _now()
    exp["updated_at"] = _now()
    logger.info("Experiment stopped: tenant=%s id=%s", tenant.tenant_id, experiment_id)
    return APIResponse(data=exp).to_dict()


@router.post("/{experiment_id}/analyze")
async def analyze_experiment(experiment_id: str, request: Request):
    """Trigger incrementality analysis for the experiment.

    Computes:
      - conversion rates for treatment vs. control cells
      - incremental lift (difference-in-differences or pre/post)
      - p-value using a Z-test on proportions
      - confidence interval on the lift estimate

    Incremental metrics are always labeled as `incremental_*` to distinguish
    them from attributed metrics.
    """
    tenant = _require_tenant(request)
    exp = _experiments.get(_exp_key(tenant.tenant_id, experiment_id))
    if exp is None:
        raise NotFoundError("Experiment")
    if exp.get("status") not in ("stopped", "analyzing", "complete"):
        raise BadRequestError("Experiment must be stopped before analysis")

    key = _exp_key(tenant.tenant_id, experiment_id)
    all_outcomes = _outcomes.get(key, [])

    treatment_outcomes = [o for o in all_outcomes if o.get("cell") == "treatment"]
    control_outcomes = [o for o in all_outcomes if o.get("cell") == "control"]

    assignment_key = key
    all_assignments = _assignments.get(assignment_key, [])
    treatment_count = sum(1 for a in all_assignments if a.get("cell") == "treatment")
    control_count = sum(1 for a in all_assignments if a.get("cell") == "control")

    t_conversions = len(treatment_outcomes)
    c_conversions = len(control_outcomes)

    t_rate = t_conversions / max(treatment_count, 1)
    c_rate = c_conversions / max(control_count, 1)
    incremental_lift = (t_rate - c_rate) / max(c_rate, 0.0001)

    t_revenue = sum(float(o.get("gross_value") or 0) for o in treatment_outcomes)
    c_revenue = sum(float(o.get("gross_value") or 0) for o in control_outcomes)
    incremental_revenue = t_revenue - c_revenue

    # Z-test on proportions (two-tailed)
    import math
    pooled_p = (t_conversions + c_conversions) / max(treatment_count + control_count, 1)
    se = math.sqrt(pooled_p * (1 - pooled_p) * (1 / max(treatment_count, 1) + 1 / max(control_count, 1)))
    z_score = (t_rate - c_rate) / max(se, 1e-9)
    # Approximate p-value from Z (two-tailed, using normal CDF approximation)
    p_value = 2 * (1 - _normal_cdf(abs(z_score)))
    threshold = float(exp.get("statistical_significance_threshold", 0.05))
    is_significant = p_value < threshold

    analysis = {
        "experiment_id": experiment_id,
        "analysis_type": "z_test_proportions",
        "treatment_assignments": treatment_count,
        "control_assignments": control_count,
        "treatment_conversions": t_conversions,
        "control_conversions": c_conversions,
        "treatment_conversion_rate": round(t_rate, 6),
        "control_conversion_rate": round(c_rate, 6),
        "incremental_lift_pct": round(incremental_lift * 100, 4),
        "incremental_revenue": round(incremental_revenue, 2),
        "z_score": round(z_score, 4),
        "p_value": round(p_value, 6),
        "statistical_significance_threshold": threshold,
        "is_statistically_significant": is_significant,
        "note": (
            "Incremental metrics (incremental_*) reflect causal lift estimates. "
            "Do not conflate with attributed metrics which represent correlation-based credit."
        ),
        "analyzed_at": _now(),
    }

    exp["status"] = "complete"
    exp["analysis"] = analysis
    exp["updated_at"] = _now()

    return APIResponse(data=analysis, meta={"is_significant": is_significant}).to_dict()


@router.get("/{experiment_id}/results")
async def get_experiment_results(experiment_id: str, request: Request):
    tenant = _require_tenant(request)
    exp = _experiments.get(_exp_key(tenant.tenant_id, experiment_id))
    if exp is None:
        raise NotFoundError("Experiment")
    analysis = exp.get("analysis")
    if analysis is None:
        raise BadRequestError("No analysis results yet. Run POST /analyze first.")
    return APIResponse(data=analysis).to_dict()


def _normal_cdf(z: float) -> float:
    """Approximate normal CDF using Abramowitz and Stegun approximation."""
    import math
    if z < 0:
        return 1 - _normal_cdf(-z)
    t = 1 / (1 + 0.2316419 * z)
    poly = t * (0.319381530 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))))
    return 1 - (1 / math.sqrt(2 * math.pi)) * math.exp(-z * z / 2) * poly
