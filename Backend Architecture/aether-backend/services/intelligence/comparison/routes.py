"""Comparison Intelligence API — /v1/intelligence/comparisons.

Tenant-scoped comparison workbench: definitions CRUD, run trigger/status
(runs execute on the durable jobs plane), findings list + disposition,
watchlists with noise controls, versioned stored baselines, and read-only
counterfactual scenarios.

Flag-gated INSIDE every handler via ``settings.comparison.enabled``
(``AETHER_COMPARISON_INTELLIGENCE_ENABLED``, default OFF): when the flag is
off the surface answers 404 (NotFoundError), indistinguishable from an
unmounted route. Reads require the ``read`` permission, writes ``write``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from config.settings import settings
from shared.auth.auth import TenantContext
from shared.common.common import APIResponse, BadRequestError, NotFoundError, utc_now
from shared.logger.logger import get_logger, metrics

from services.intelligence.comparison.baselines import StoredBaselineRepository
from services.intelligence.comparison.contracts import (
    BaselineSpec,
    ComparisonDefinition,
    ComparisonSubject,
)
from services.intelligence.comparison.engine import validate_definition
from services.intelligence.comparison.findings import FindingsService
from services.intelligence.comparison.jobs import COMPARISON_RUN_JOB_TYPE
from services.intelligence.comparison.store import (
    ComparisonDefinitionRepository,
    ComparisonRunRepository,
)
from services.intelligence.comparison.watchlists import (
    NoiseControls,
    WatchlistDefinition,
    WatchlistRepository,
)

logger = get_logger("aether.intelligence.comparison.routes")
router = APIRouter(
    prefix="/v1/intelligence/comparisons", tags=["Comparison Intelligence"]
)

_definitions = ComparisonDefinitionRepository()
_runs = ComparisonRunRepository()
_findings = FindingsService()
_watchlists = WatchlistRepository()
_baselines = StoredBaselineRepository()


def _require_enabled() -> None:
    if not settings.comparison.enabled:
        raise NotFoundError("comparison intelligence (feature not enabled)")


def _tenant(request: Request, permission: str) -> TenantContext:
    _require_enabled()
    tenant: TenantContext = request.state.tenant
    tenant.require_permission(permission)
    return tenant


def _engine():
    from services.intelligence.comparison.jobs import _default_engine

    return _default_engine()


# ── Request models ──────────────────────────────────────────────────────────

class DefinitionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = None
    mode: str
    subject: ComparisonSubject
    baseline: BaselineSpec
    dimensions: Optional[list[str]] = None
    temporal_mode: Optional[str] = None


class RunTriggerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    as_of: Optional[datetime] = None


class DispositionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    disposition: str
    actor_id: str
    reason: Optional[str] = None


class WatchlistUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    watchlist_id: Optional[str] = None
    name: str
    enabled: bool = True
    definition_ids: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    noise: NoiseControls = Field(default_factory=NoiseControls)


class StoredBaselineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline_id: str
    kind: str  # "manual" | "policy"
    metrics: dict[str, list[dict[str, Any]]]


class ScenarioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition_id: str
    scenario_id: Optional[str] = None
    scenario_params: dict[str, Any]
    as_of: Optional[datetime] = None


# ── Definitions ─────────────────────────────────────────────────────────────

@router.post("")
async def create_definition(request: Request, payload: DefinitionCreateRequest) -> APIResponse:
    tenant = _tenant(request, "write")
    definition = ComparisonDefinition(
        definition_id=str(uuid.uuid4()),
        tenant_id=tenant.tenant_id,
        name=payload.name,
        mode=payload.mode,
        subject=payload.subject,
        baseline=payload.baseline,
        dimensions=payload.dimensions,
        temporal_mode=payload.temporal_mode,
        created_at=utc_now(),
        created_by=tenant.user_id,
        schema_version="1",
    )
    validate_definition(definition)
    stored = await _definitions.upsert_scoped(
        tenant.tenant_id, definition.definition_id, definition.model_dump(mode="json")
    )
    return APIResponse(data={"definition": stored})


@router.get("")
async def list_definitions(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> APIResponse:
    tenant = _tenant(request, "read")
    rows = await _definitions.list_scoped(tenant.tenant_id, limit=limit, offset=offset)
    return APIResponse(data={"definitions": rows})


# ── Runs (registered before /{definition_id} so paths never collide) ────────

@router.get("/runs/{run_id}")
async def get_run(request: Request, run_id: str) -> APIResponse:
    tenant = _tenant(request, "read")
    run = await _runs.get_scoped(tenant.tenant_id, run_id)
    if run is None:
        raise NotFoundError("comparison run")
    return APIResponse(data={"run": run})


# ── Findings ────────────────────────────────────────────────────────────────

@router.get("/findings")
async def list_findings(
    request: Request,
    run_id: Optional[str] = Query(default=None),
    disposition: Optional[str] = Query(default=None),
    severity: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> APIResponse:
    tenant = _tenant(request, "read")
    rows = await _findings.list(
        tenant.tenant_id,
        run_id=run_id,
        disposition=disposition,
        severity=severity,
        limit=limit,
        offset=offset,
    )
    return APIResponse(data={"findings": rows})


@router.get("/findings/{finding_id}")
async def get_finding(request: Request, finding_id: str) -> APIResponse:
    tenant = _tenant(request, "read")
    return APIResponse(data={"finding": await _findings.get(tenant.tenant_id, finding_id)})


@router.post("/findings/{finding_id}/disposition")
async def dispose_finding(
    request: Request, finding_id: str, payload: DispositionRequest
) -> APIResponse:
    tenant = _tenant(request, "write")
    updated = await _findings.dispose(
        tenant.tenant_id,
        finding_id,
        payload.disposition,
        actor_id=payload.actor_id or tenant.user_id or "unknown",
        reason=payload.reason,
    )
    return APIResponse(data={"finding": updated})


# ── Watchlists ──────────────────────────────────────────────────────────────

@router.get("/watchlists")
async def list_watchlists(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> APIResponse:
    tenant = _tenant(request, "read")
    rows = await _watchlists.list_for_tenant(tenant.tenant_id, limit=limit, offset=offset)
    return APIResponse(data={"watchlists": [w.model_dump(mode="json") for w in rows]})


@router.post("/watchlists")
async def upsert_watchlist(request: Request, payload: WatchlistUpsertRequest) -> APIResponse:
    tenant = _tenant(request, "write")
    watchlist = WatchlistDefinition(
        watchlist_id=payload.watchlist_id or str(uuid.uuid4()),
        tenant_id=tenant.tenant_id,
        name=payload.name,
        enabled=payload.enabled,
        definition_ids=payload.definition_ids,
        dimensions=payload.dimensions,
        noise=payload.noise,
        created_by=tenant.user_id,
    )
    stored = await _watchlists.upsert(watchlist)
    return APIResponse(data={"watchlist": stored})


@router.delete("/watchlists/{watchlist_id}")
async def delete_watchlist(request: Request, watchlist_id: str) -> APIResponse:
    tenant = _tenant(request, "write")
    deleted = await _watchlists.delete_scoped(tenant.tenant_id, watchlist_id)
    if not deleted:
        raise NotFoundError("comparison watchlist")
    return APIResponse(data={"deleted": watchlist_id})


# ── Stored (manual/policy) baselines — versioned ────────────────────────────

@router.post("/baselines")
async def put_baseline_version(
    request: Request, payload: StoredBaselineRequest
) -> APIResponse:
    tenant = _tenant(request, "write")
    if payload.kind not in ("manual", "policy"):
        raise BadRequestError(
            f"Stored baseline kind must be 'manual' or 'policy', got {payload.kind!r}"
        )
    stored = await _baselines.put_version(
        tenant.tenant_id,
        payload.baseline_id,
        payload.kind,
        payload.metrics,
        created_by=tenant.user_id or "",
    )
    return APIResponse(data={"baseline": stored})


@router.get("/baselines/{baseline_id}")
async def get_baseline_latest(request: Request, baseline_id: str) -> APIResponse:
    tenant = _tenant(request, "read")
    record = await _baselines.latest(tenant.tenant_id, baseline_id)
    if record is None:
        raise NotFoundError("stored comparison baseline")
    return APIResponse(data={"baseline": record})


# ── Read-only counterfactual scenarios ──────────────────────────────────────

@router.post("/scenarios")
async def run_scenario(request: Request, payload: ScenarioRequest) -> APIResponse:
    """Compute a counterfactual. Persists NOTHING — response-only."""
    tenant = _tenant(request, "read")  # read-only by construction
    record = await _definitions.get_scoped(tenant.tenant_id, payload.definition_id)
    if record is None:
        raise NotFoundError("comparison definition")
    definition = ComparisonDefinition(**record)

    from services.intelligence.comparison.scenarios import ScenarioRunner

    engine = _engine()
    runner = ScenarioRunner(engine._collector, engine._resolver)
    result = await runner.run(
        tenant.tenant_id,
        definition,
        payload.scenario_params,
        scenario_id=payload.scenario_id,
        as_of=payload.as_of,
    )
    metrics.increment("comparison_scenarios_total")
    return APIResponse(data={"scenario": result.model_dump(mode="json")})


# ── Definition detail + run trigger (parameterized paths LAST) ──────────────

@router.get("/{definition_id}")
async def get_definition(request: Request, definition_id: str) -> APIResponse:
    tenant = _tenant(request, "read")
    record = await _definitions.get_scoped(tenant.tenant_id, definition_id)
    if record is None:
        raise NotFoundError("comparison definition")
    return APIResponse(data={"definition": record})


@router.delete("/{definition_id}")
async def delete_definition(request: Request, definition_id: str) -> APIResponse:
    tenant = _tenant(request, "write")
    deleted = await _definitions.delete_scoped(tenant.tenant_id, definition_id)
    if not deleted:
        raise NotFoundError("comparison definition")
    return APIResponse(data={"deleted": definition_id})


@router.post("/{definition_id}/runs")
async def trigger_run(
    request: Request, definition_id: str, payload: RunTriggerRequest
) -> APIResponse:
    """Create a queued run and enqueue it on the durable jobs plane."""
    tenant = _tenant(request, "write")
    engine = _engine()
    run = await engine.create_run(tenant.tenant_id, definition_id, as_of=payload.as_of)

    from services.jobs.service import get_jobs_service

    job = await get_jobs_service().enqueue(
        tenant.tenant_id,
        COMPARISON_RUN_JOB_TYPE,
        {"run_id": run["run_id"]},
        idempotency_key=f"comparison.run:{run['run_id']}",
        requested_by=tenant.user_id,
    )
    return APIResponse(data={"run": run, "job_id": job.get("id")})


@router.get("/{definition_id}/runs")
async def list_runs(
    request: Request,
    definition_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> APIResponse:
    tenant = _tenant(request, "read")
    rows = await _runs.list_for_definition(
        tenant.tenant_id, definition_id, limit=limit, offset=offset
    )
    return APIResponse(data={"runs": rows})
