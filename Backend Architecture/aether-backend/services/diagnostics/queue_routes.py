"""
Aether Service — Diagnostics Queue Stats

Aggregated queue depth / throughput / backpressure across the queues that
the platform runs (ingestion, ml_serving, x402 facilitators, agent task,
reward queue). Each named queue can publish a snapshot via POST and the
list/summary endpoints aggregate them for KYBER's diagnostics surface.

Endpoints:
    GET  /v1/diagnostics/queues                   List queue snapshots
    GET  /v1/diagnostics/queues/summary           Aggregated totals
    GET  /v1/diagnostics/queues/{queue_name}      Single queue detail
    POST /v1/diagnostics/queues/{queue_name}      Publish snapshot
    DELETE /v1/diagnostics/queues/{queue_name}    Drop snapshot
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, BadRequestError, NotFoundError
from shared.logger.logger import get_logger, metrics
from shared.store import get_store

logger = get_logger("aether.service.diagnostics.queues")
router = APIRouter(prefix="/v1/diagnostics/queues", tags=["Diagnostics — Queues"])

_queue_store = get_store("queue_snapshots")


class QueueSnapshot(BaseModel):
    depth: int = Field(..., ge=0)
    in_flight: int = Field(default=0, ge=0)
    throughput_per_minute: float = Field(default=0.0, ge=0.0)
    error_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    backpressure: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _key(tenant_id: str, queue_name: str) -> str:
    return f"{tenant_id}:{queue_name}"


@router.get("")
async def list_queues(request: Request):
    """List all queue snapshots known to this tenant."""
    tenant = request.state.tenant
    tenant.require_permission("admin")
    queues = await _queue_store.find(tenant_id=tenant.tenant_id)
    return APIResponse(data={"queues": queues, "count": len(queues)}).to_dict()


@router.get("/summary")
async def summary(request: Request):
    """Aggregate queue health across all known queues."""
    tenant = request.state.tenant
    tenant.require_permission("admin")
    queues = await _queue_store.find(tenant_id=tenant.tenant_id)

    total_depth = sum(int(q.get("depth", 0)) for q in queues)
    total_in_flight = sum(int(q.get("in_flight", 0)) for q in queues)
    total_throughput = sum(float(q.get("throughput_per_minute", 0.0)) for q in queues)
    backpressured = [q["queue_name"] for q in queues if q.get("backpressure")]
    error_rates = [float(q.get("error_rate", 0.0)) for q in queues]
    avg_error_rate = (sum(error_rates) / len(error_rates)) if error_rates else 0.0

    return APIResponse(data={
        "queue_count": len(queues),
        "total_depth": total_depth,
        "total_in_flight": total_in_flight,
        "total_throughput_per_minute": total_throughput,
        "average_error_rate": avg_error_rate,
        "backpressured_queues": backpressured,
    }).to_dict()


@router.get("/{queue_name}")
async def get_queue(queue_name: str, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("admin")
    record = await _queue_store.get(_key(tenant.tenant_id, queue_name))
    if not record:
        raise NotFoundError(f"Queue snapshot not found: {queue_name}")
    return APIResponse(data=record).to_dict()


@router.post("/{queue_name}")
async def publish_snapshot(queue_name: str, body: QueueSnapshot, request: Request):
    """Publish a queue snapshot. Producer-side endpoint for queue managers."""
    tenant = request.state.tenant
    tenant.require_permission("admin")
    if not queue_name.strip():
        raise BadRequestError("queue_name must not be empty")

    record = body.model_dump()
    record["queue_name"] = queue_name
    record["tenant_id"] = tenant.tenant_id
    record["updated_at"] = _now()
    await _queue_store.set(_key(tenant.tenant_id, queue_name), record)
    metrics.increment("queue_snapshots_published", labels={"queue": queue_name})
    return APIResponse(data=record).to_dict()


@router.delete("/{queue_name}")
async def drop_snapshot(queue_name: str, request: Request):
    """Remove a queue snapshot (e.g., when a queue is decommissioned)."""
    tenant = request.state.tenant
    tenant.require_permission("admin")
    deleted = await _queue_store.delete(_key(tenant.tenant_id, queue_name))
    if not deleted:
        raise NotFoundError(f"Queue snapshot not found: {queue_name}")
    return APIResponse(data={"queue_name": queue_name, "deleted": True}).to_dict()
