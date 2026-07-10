"""
Aether Service — Agent Worker Run Routes

Worker → backend callback path for the execution bridge, plus operator-facing
run inspection. Status updates require the worker service credential
permission ``agent:run_update`` (mirrors the ``agent:heartbeat`` pattern):
ordinary operators holding ``agent:manage`` must NOT be able to spoof worker
execution results.

Mount (main.py, inside the agent-layer block):
    from services.agent.worker_routes import worker_router
    app.include_router(worker_router)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from config.settings import settings
from shared.common.common import BadRequestError, NotFoundError
from shared.logger.logger import get_logger, metrics
from services.agent.runtime_repository import (
    RUN_STATUSES,
    get_agent_runtime_repository,
    utc_now,
)

logger = get_logger("aether.service.agent.worker_runs")
worker_router = APIRouter(prefix="/v1/agent/runs", tags=["Agent Worker Runs"])

_runtime_repo = get_agent_runtime_repository()


def _require_bridge_enabled() -> None:
    if not settings.one_person_ops.worker_bridge_enabled:
        raise BadRequestError("Agent worker bridge is not enabled")


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "") or request.headers.get("X-Correlation-ID", "")


def _envelope(data: Any, request: Request, status: str = "success") -> dict[str, Any]:
    return {
        "data": data,
        "status": status,
        "timestamp": utc_now(),
        "meta": {"request_id": _request_id(request)},
    }


class RunStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(running|completed|failed|retry)$")
    output: dict[str, Any] | None = None
    error: str = ""
    heartbeat_at: str | None = None
    worker_id: str = ""


@worker_router.get("")
async def list_runs(
    request: Request,
    status: str | None = None,
    objective_id: str | None = None,
    limit: int = 100,
):
    """List worker runs for the tenant, filterable by status/objective."""
    _require_bridge_enabled()
    tenant = request.state.tenant
    tenant.require_permission("agent:manage")
    if status and status not in RUN_STATUSES:
        raise BadRequestError(f"Invalid run status: {status}")
    runs = await _runtime_repo.list_runs(tenant.tenant_id, status=status, objective_id=objective_id, limit=limit)
    return _envelope({"runs": runs, "total": len(runs)}, request)


# NOTE: declared before "/{run_id}" so the literal path wins the match.
@worker_router.get("/stuck")
async def list_stuck_runs(request: Request):
    """Runs still queued/running past the stale threshold (operator recovery)."""
    _require_bridge_enabled()
    tenant = request.state.tenant
    tenant.require_permission("agent:manage")
    runs = await _runtime_repo.list_stuck_runs(tenant.tenant_id)
    return _envelope({"runs": runs, "total": len(runs)}, request)


@worker_router.get("/{run_id}")
async def get_run(run_id: str, request: Request):
    _require_bridge_enabled()
    tenant = request.state.tenant
    tenant.require_permission("agent:manage")
    run = await _runtime_repo.get_run(tenant.tenant_id, run_id)
    if run is None:
        raise NotFoundError("Worker run")
    return _envelope(run, request)


@worker_router.post("/{run_id}/status")
async def update_run_status(run_id: str, body: RunStatusUpdate, request: Request):
    """Worker execution callback: running / completed / failed / retry.

    Requires the worker service credential permission ``agent:run_update``
    (same trust boundary as ``agent:heartbeat``): run state drives health,
    stuck detection and review flow, so an ordinary operator token must not
    be able to fake a completion or bury a failure.
    """
    _require_bridge_enabled()
    tenant = request.state.tenant
    tenant.require_permission("agent:run_update")
    actor = body.worker_id or "worker"
    if body.status == "running":
        run = await _runtime_repo.start_run(
            tenant.tenant_id, run_id, worker_id=body.worker_id, request_id=_request_id(request)
        )
    elif body.status == "completed":
        run = await _runtime_repo.complete_run(
            tenant.tenant_id, run_id, output=body.output,
            actor_id=actor, request_id=_request_id(request),
        )
    else:  # failed | retry
        run = await _runtime_repo.fail_run(
            tenant.tenant_id, run_id, error=body.error, retry=body.status == "retry",
            actor_id=actor, request_id=_request_id(request),
        )
    if run is None:
        raise NotFoundError("Worker run")
    if body.heartbeat_at:
        run["heartbeat_at"] = body.heartbeat_at
        run["updated_at"] = utc_now()
        await _runtime_repo.worker_runs.set(run_id, run)
    metrics.increment(
        "agent_worker_run_updates",
        labels={"status": body.status, "controller": run.get("controller", "unknown")},
    )
    logger.info(
        "Worker run update: tenant=%s run=%s objective=%s status=%s request_id=%s",
        tenant.tenant_id, run_id, run.get("objective_id"), body.status, _request_id(request),
    )
    return _envelope(run, request)


__all__ = ["worker_router", "RunStatusUpdate"]
