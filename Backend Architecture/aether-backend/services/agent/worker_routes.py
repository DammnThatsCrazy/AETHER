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

import os
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from config.settings import settings
from shared.common.common import BadRequestError, NotFoundError
from shared.logger.logger import get_logger, metrics
from services.agent.runtime_repository import (
    MUTATION_CLASSES,
    RUN_STATUSES,
    get_agent_runtime_repository,
    utc_now,
)

logger = get_logger("aether.service.agent.worker_runs")
worker_router = APIRouter(prefix="/v1/agent/runs", tags=["Agent Worker Runs"])

_runtime_repo = get_agent_runtime_repository()

# Upper bound on how many proposals a single completed run may stage for review.
_MAX_PROPOSED_MUTATIONS = int(os.getenv("AETHER_AGENT_MAX_PROPOSED_MUTATIONS", "50"))


async def _stage_proposed_mutations(run: dict[str, Any], request_id: str) -> dict[str, Any] | None:
    """Stage a completed run's PROPOSED mutations for human review.

    The worker returns proposals in its output; they land as a ``pending`` review
    batch with every mutation ``staged`` — the human approval gate still governs
    whether they ever commit. A worker credential can stage a proposal but can
    NEVER approve or commit it. Malformed proposals are dropped, not raised, so a
    bad proposal can't fail the run callback.
    """
    # Idempotent: a retried completion callback must not stage a second batch.
    if run.get("proposals_staged"):
        return None
    output = run.get("output") or {}
    proposals = output.get("proposed_mutations")
    objective_id = run.get("objective_id", "")
    if not isinstance(proposals, list) or not proposals or not objective_id:
        return None
    tenant_id = run["tenant_id"]
    valid: list[dict[str, Any]] = []
    for proposal in proposals[:_MAX_PROPOSED_MUTATIONS]:
        if not isinstance(proposal, dict):
            continue
        try:
            mclass = int(proposal.get("mutation_class", proposal.get("class", 1)))
        except (TypeError, ValueError):
            continue
        if mclass not in MUTATION_CLASSES:
            continue
        valid.append(proposal)
    if not valid:
        return None
    batch = await _runtime_repo.create_review_batch(
        tenant_id, objective_id, valid, actor_id=run.get("worker_id", "worker"), request_id=request_id
    )
    # Persist the staged marker on the durable run BEFORE returning so a retried
    # completion callback is a no-op (durable-before-ack).
    stored = await _runtime_repo.get_run(tenant_id, run["run_id"])
    if stored is not None:
        stored["proposals_staged"] = True
        stored["review_batch_id"] = batch["batch_id"]
        stored["updated_at"] = utc_now()
        await _runtime_repo.worker_runs.set(run["run_id"], stored)
    # An objective with pending proposals moves to awaiting_review so it cannot be
    # re-dispatched around the human gate (record_dispatch refuses that state).
    objective = await _runtime_repo.get_objective(tenant_id, objective_id)
    if objective and objective.get("status") in {"queued", "active"}:
        objective["status"] = "awaiting_review"
        objective["updated_at"] = utc_now()
        await _runtime_repo.objectives.set(objective_id, objective)
        await _runtime_repo.append_event(
            tenant_id, "objective.awaiting_review", "review_queue", objective,
            objective_id, run.get("worker_id", "worker"), request_id,
        )
    metrics.increment("agent_run_proposals_staged", labels={"controller": run.get("controller", "unknown")})
    logger.info(
        "Worker run staged %d proposal(s) for review: tenant=%s run=%s batch=%s request_id=%s",
        len(valid), tenant_id, run.get("run_id"), batch["batch_id"], request_id,
    )
    return batch


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
        # Supervised mutation: a completed step's PROPOSED mutations are staged
        # for human review (pending). Gated by the review flag; the worker
        # credential can stage but never approve/commit.
        if run is not None and settings.one_person_ops.staged_mutation_review_enabled:
            staged_batch = await _stage_proposed_mutations(run, _request_id(request))
            if staged_batch is not None:
                run = await _runtime_repo.get_run(tenant.tenant_id, run_id) or run
                run = dict(run)
                run["review_batch_id"] = staged_batch["batch_id"]
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


async def _replay_and_dispatch(tenant, run_id: str, request: Request) -> dict[str, Any]:
    """Create a fresh queued run from a dead one and (if enabled) re-dispatch it.

    Blocked by the kill switch (this is re-dispatch, i.e. new agent work) and by
    a non-runnable objective (replay_run refuses those). Hosted bridge failure
    marks the replay dispatch_failed and re-raises, mirroring the dispatch path.
    """
    from shared.common.common import ConflictError
    from services.agent import worker_bridge
    from services.agent.worker_bridge import BridgeUnavailableError

    kill_switch = await _runtime_repo.get_kill_switch(tenant.tenant_id)
    if kill_switch.get("enabled"):
        raise ConflictError("Agent kill switch is engaged; run retry/replay is disabled")
    replay = await _runtime_repo.replay_run(tenant.tenant_id, run_id, actor_id=_request_id(request) or "operator", request_id=_request_id(request))
    if replay is None:
        raise NotFoundError("Worker run")
    if settings.one_person_ops.worker_bridge_enabled:
        objective = await _runtime_repo.get_objective(tenant.tenant_id, replay.get("objective_id", "")) or {}
        envelope = worker_bridge.build_dispatch_envelope(
            replay, request_id=_request_id(request), payload=objective.get("payload") or {}
        )
        try:
            replay = dict(replay)
            replay["bridge"] = worker_bridge.dispatch_to_worker(envelope)
        except BridgeUnavailableError as exc:
            await _runtime_repo.mark_run_dispatch_failed(
                tenant.tenant_id, replay["run_id"], exc.reason, "operator", _request_id(request)
            )
            metrics.increment("agent_worker_bridge_dispatch_failed", labels={"queue": replay.get("queue", "default")})
            raise
    metrics.increment("agent_worker_runs_replayed", labels={"controller": replay.get("controller", "unknown")})
    return replay


@worker_router.post("/{run_id}/replay")
async def replay_run(run_id: str, request: Request):
    """Operator recovery: re-queue a failed/stale run under a fresh idempotency key."""
    _require_bridge_enabled()
    tenant = request.state.tenant
    tenant.require_permission("agent:dispatch")
    return _envelope(await _replay_and_dispatch(tenant, run_id, request), request)


@worker_router.post("/{run_id}/retry")
async def retry_run(run_id: str, request: Request):
    """Alias of replay: retry a terminal run by re-queuing fresh work."""
    _require_bridge_enabled()
    tenant = request.state.tenant
    tenant.require_permission("agent:dispatch")
    return _envelope(await _replay_and_dispatch(tenant, run_id, request), request)


@worker_router.post("/sweep-stale")
async def sweep_stale(request: Request):
    """Mark stuck (queued/running past threshold) runs stale for recovery."""
    _require_bridge_enabled()
    tenant = request.state.tenant
    tenant.require_permission("agent:dispatch")
    swept = await _runtime_repo.sweep_stale_runs(tenant.tenant_id, actor_id="operator", request_id=_request_id(request))
    return _envelope({"swept": swept, "total": len(swept)}, request)


__all__ = ["worker_router", "RunStatusUpdate"]
