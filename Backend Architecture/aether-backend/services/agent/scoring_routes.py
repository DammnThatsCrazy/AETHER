"""
Aether Service — Scoring (extraction)

Standalone API surface for the extraction risk scorer that has lived inside
shared/scoring/extraction_score.py without an HTTP contract.

Endpoints:
    GET  /v1/scoring/models                List sensitivity tiers per known model
    GET  /v1/scoring/runs                  List recent extraction runs (paginated)
    GET  /v1/scoring/runs/{run_id}         Get a single run
    POST /v1/scoring/extract               Score an extraction request (synchronous)
    GET  /v1/scoring/policies              List recommended policies seen so far

Runs are persisted in the `extraction_runs` durable store keyed by
{tenant_id}:{run_id}.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, BadRequestError, NotFoundError
from shared.logger.logger import get_logger, metrics
from shared.scoring.extraction_models import (
    ExtractionIdentity,
    ExtractionSignal,
    ModelSensitivityTier,
    SignalSeverity,
    get_model_tier,
)
from shared.scoring.extraction_score import ExtractionRiskScorer
from shared.store import get_store

logger = get_logger("aether.service.scoring")
router = APIRouter(prefix="/v1/scoring", tags=["Scoring"])

_runs_store = get_store("extraction_runs")
_scorer = ExtractionRiskScorer()


class SignalIn(BaseModel):
    name: str
    value: float = Field(..., ge=0.0, le=1.0)
    severity: str = Field(default="info", pattern="^(info|low|medium|high|critical)$")
    description: str = ""


class IdentityIn(BaseModel):
    api_key_id: Optional[str] = None
    user_id: Optional[str] = None
    source_ip: Optional[str] = None
    session_id: Optional[str] = None


class ExtractionRequest(BaseModel):
    identity: IdentityIn
    signals: list[SignalIn] = Field(default_factory=list)
    model_name: str = ""
    budget_utilization: float = Field(default=0.0, ge=0.0, le=1.0)
    canary_triggered: bool = False
    fraud_score: float = Field(default=0.0, ge=0.0, le=100.0)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _key(tenant_id: str, run_id: str) -> str:
    return f"{tenant_id}:{run_id}"


@router.get("/models")
async def list_models(request: Request):
    """List the model sensitivity tiers recognized by the scorer."""
    tenant = request.state.tenant
    tenant.require_permission("agent:manage")

    common_models = [
        "claude-opus-4", "claude-sonnet-4", "claude-haiku-4",
        "gpt-4", "gpt-4-turbo", "gpt-3.5-turbo",
        "gemini-1.5-pro", "gemini-1.5-flash",
        "mistral-large", "llama-3-70b",
    ]
    data = [
        {"model_name": m, "tier": get_model_tier(m).value}
        for m in common_models
    ]
    tiers = [t.value for t in ModelSensitivityTier]
    return APIResponse(data={"models": data, "tiers": tiers}).to_dict()


@router.post("/extract")
async def extract(body: ExtractionRequest, request: Request):
    """Score an extraction request and persist the run."""
    tenant = request.state.tenant
    tenant.require_permission("agent:manage")

    identity = ExtractionIdentity(
        api_key_id=body.identity.api_key_id,
        user_id=body.identity.user_id,
        source_ip=body.identity.source_ip,
        session_id=body.identity.session_id,
        tenant_id=tenant.tenant_id,
    )
    if identity.primary_key == "anonymous":
        raise BadRequestError(
            "identity must include at least one of api_key_id, user_id, source_ip"
        )

    signals: list[ExtractionSignal] = []
    for s in body.signals:
        try:
            severity = SignalSeverity(s.severity)
        except ValueError as exc:
            raise BadRequestError(f"Unknown severity: {s.severity}") from exc
        signals.append(ExtractionSignal(
            name=s.name,
            value=s.value,
            severity=severity,
            description=s.description,
        ))

    assessment = _scorer.score(
        identity=identity,
        expectation_signals=signals,
        model_name=body.model_name,
        budget_utilization=body.budget_utilization,
        canary_triggered=body.canary_triggered,
        fraud_score=body.fraud_score,
    )

    run_id = str(uuid.uuid4())
    record = {
        "run_id": run_id,
        "tenant_id": tenant.tenant_id,
        "actor_key": identity.primary_key,
        "model_name": body.model_name,
        "score": assessment.score,
        "band": assessment.band.value if hasattr(assessment.band, "value") else str(assessment.band),
        "reasons": list(assessment.reasons or []),
        "policy": getattr(assessment, "policy_recommendation", None),
        "canary_triggered": body.canary_triggered,
        "fraud_score": body.fraud_score,
        "budget_utilization": body.budget_utilization,
        "created_at": _now(),
    }
    await _runs_store.set(_key(tenant.tenant_id, run_id), record)
    metrics.increment("extraction_runs", labels={"band": record["band"]})
    return APIResponse(data=record).to_dict()


@router.get("/runs")
async def list_runs(
    request: Request,
    actor_key: str = "",
    band: str = "",
    limit: int = 100,
):
    """List recent extraction runs for the current tenant."""
    tenant = request.state.tenant
    tenant.require_permission("agent:manage")

    filters: dict[str, Any] = {"tenant_id": tenant.tenant_id}
    if actor_key:
        filters["actor_key"] = actor_key
    if band:
        filters["band"] = band

    runs = await _runs_store.find(**filters)
    runs_sorted = sorted(runs, key=lambda r: r.get("created_at", ""), reverse=True)[:limit]
    return APIResponse(data={"runs": runs_sorted, "count": len(runs_sorted)}).to_dict()


@router.get("/runs/{run_id}")
async def get_run(run_id: str, request: Request):
    """Get a single extraction run."""
    tenant = request.state.tenant
    tenant.require_permission("agent:manage")
    record = await _runs_store.get(_key(tenant.tenant_id, run_id))
    if not record:
        raise NotFoundError(f"Extraction run not found: {run_id}")
    return APIResponse(data=record).to_dict()


@router.get("/policies")
async def list_policies(request: Request):
    """Aggregate counts of recommended policies seen across recent runs."""
    tenant = request.state.tenant
    tenant.require_permission("agent:manage")
    runs = await _runs_store.find(tenant_id=tenant.tenant_id)

    counts: dict[str, int] = {}
    for r in runs:
        key = str(r.get("policy") or "unspecified")
        counts[key] = counts.get(key, 0) + 1

    return APIResponse(data={
        "policies": [{"policy": k, "count": v} for k, v in counts.items()],
        "total_runs": len(runs),
    }).to_dict()
