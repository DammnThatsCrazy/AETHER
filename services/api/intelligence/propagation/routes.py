"""Propagation & Diffusion lens API (flag-gated, tenant-scoped, read-only).

``POST /v1/social360/propagation/runs`` computes one bounded propagation run
over the caller's own tenant and returns the ``PropagationRun`` contract.
``POST /v1/social360/propagation/subjects/{subject_id}/summary`` returns the
Profile360 view of one subject inside that run. It
never writes graph truth and never reads another tenant's data. Disabled unless
``AETHER_PROPAGATION_LENS_ENABLED`` is on.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from shared.auth.auth import Permissions
from shared.common.common import APIResponse, BadRequestError, NotFoundError, ServiceUnavailableError

router = APIRouter(prefix="/v1/social360/propagation", tags=["Propagation & Diffusion"])


class PropagationRunRequest(BaseModel):
    window_start: str
    window_end: str
    instrument_keys: list[str] = Field(default_factory=list, max_length=200)
    channels: Optional[list[str]] = None
    exposure_window_seconds: int = Field(default=72 * 3600, ge=60, le=30 * 24 * 3600)
    max_hops: int = Field(default=4, ge=1, le=16)
    include_live: bool = Field(default=False, description="Sync linked accounts (through rights admission) before computing")
    save: bool = Field(default=False, description="Keep the run for later reads, staleness checks and recompute")


def _require_enabled() -> None:
    from config.settings import settings

    if not settings.social360.propagation_lens_enabled:
        raise ServiceUnavailableError("Propagation lens is disabled")


def _require_permissions(request: Request) -> str:
    tenant = request.state.tenant
    if hasattr(tenant, "require_permission"):
        tenant.require_permission(Permissions.ANALYTICS)
        tenant.require_permission(Permissions.DERIVATIVES_READ)
    return tenant.tenant_id


async def _require_entitlement(tenant_id: str) -> None:
    """Propagation reads derivatives account data: the tenant must hold the
    ``derivatives.enabled`` entitlement (billing authority; missing means deny)."""
    from value.derivatives.runtime_routes import _require_entitlement as derivatives_entitlement

    await derivatives_entitlement(tenant_id)


async def _meter(tenant_id: str, result, *, kind: str, include_live: bool) -> None:
    """One durable usage record per computed run (idempotent on the run id)."""
    from billing.billing.revops import MeteringService, UsageMeteringEvent

    await MeteringService().record_event(UsageMeteringEvent(
        tenant_id=tenant_id,
        event_type="propagation_run_computed",
        source_type="propagation_lens",
        source_id=str(getattr(result, "run_id", "") or ""),
        metadata={"kind": kind, "include_live": include_live,
                  "episodes": len(getattr(result, "episodes", ()) or ())},
    ))


async def _run(body: PropagationRunRequest, tenant_id: str):
    from intelligence.propagation.contracts import ExposureChannel, PropagationQuery
    from intelligence.propagation.service import PropagationService

    try:
        channels = (
            tuple(ExposureChannel(c) for c in body.channels) if body.channels else tuple(ExposureChannel)
        )
        query = PropagationQuery(
            tenant_id=tenant_id,
            window_start=body.window_start,
            window_end=body.window_end,
            instrument_keys=tuple(body.instrument_keys),
            channels=channels,
            exposure_window_seconds=body.exposure_window_seconds,
            max_hops=body.max_hops,
        )
        service = PropagationService()
        run = await service.run(query, include_live=body.include_live)
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    if body.save:
        from intelligence.propagation.runs import PropagationRunStore

        await PropagationRunStore().save(run, service.last_inputs, include_live=body.include_live)
    return run


@router.post("/runs")
async def create_propagation_run(body: PropagationRunRequest, request: Request) -> dict:
    _require_enabled()
    tenant_id = _require_permissions(request)
    await _require_entitlement(tenant_id)
    result = await _run(body, tenant_id)
    await _meter(tenant_id, result, kind="run", include_live=body.include_live)
    return APIResponse(data=result.to_dict()).to_dict()


@router.post("/subjects/{subject_id}/summary")
async def subject_propagation_summary(subject_id: str, body: PropagationRunRequest, request: Request) -> dict:
    """Profile360 view: the subject's episodes and inbound/outbound paths."""
    from intelligence.propagation.engine import subject_summary

    _require_enabled()
    tenant_id = _require_permissions(request)
    await _require_entitlement(tenant_id)
    result = await _run(body, tenant_id)
    await _meter(tenant_id, result, kind="subject_summary", include_live=body.include_live)
    return APIResponse(data=subject_summary(result, subject_id)).to_dict()


@router.get("/runs")
async def list_saved_propagation_runs(request: Request) -> dict:
    """The tenant's saved runs, newest first (summaries only)."""
    from intelligence.propagation.runs import PropagationRunStore

    _require_enabled()
    tenant_id = _require_permissions(request)
    items = await PropagationRunStore().list(tenant_id)
    return APIResponse(data={"items": items}).to_dict()


@router.get("/runs/{run_id}")
async def get_saved_propagation_run(run_id: str, request: Request) -> dict:
    """A saved run with ``stale`` / ``stale_reasons`` checked against current state."""
    from intelligence.propagation.runs import PropagationRunStore

    _require_enabled()
    tenant_id = _require_permissions(request)
    record = await PropagationRunStore().get(tenant_id, run_id)
    if record is None:
        raise NotFoundError("Propagation run")
    return APIResponse(data=record).to_dict()


@router.post("/runs/{run_id}/recompute")
async def recompute_saved_propagation_run(run_id: str, request: Request) -> dict:
    """Run a saved run's query again over current inputs; the new run supersedes it."""
    from intelligence.propagation.runs import PropagationRunStore

    _require_enabled()
    tenant_id = _require_permissions(request)
    await _require_entitlement(tenant_id)
    record = await PropagationRunStore().recompute(tenant_id, run_id)
    if record is None:
        raise NotFoundError("Propagation run")
    await _meter(tenant_id, _RunRef(record["run_id"], record["run"].get("episodes") or ()),
                 kind="recompute", include_live=bool(record.get("include_live")))
    return APIResponse(data=record).to_dict()


class _RunRef:
    def __init__(self, run_id: str, episodes) -> None:
        self.run_id = run_id
        self.episodes = episodes
