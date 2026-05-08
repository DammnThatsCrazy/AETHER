"""
Aether Service — Agent Feedback Loops (routes)

Read/observability surface over the feedback learning loop. The loop itself
runs in `Agent Layer/feedback/learning.py`; this module exposes its state to
operator tooling (KYBER) without coupling the API layer to that package.

State is persisted in two durable stores:
  - `agent_feedback_loops`  : per-worker-type loop record
  - `agent_feedback_events` : append-only learning events

Endpoints:
    GET  /v1/agent/feedback/loops                          List loops
    GET  /v1/agent/feedback/loops/{worker_type}            Loop detail
    POST /v1/agent/feedback/loops/{worker_type}            Upsert loop snapshot
    POST /v1/agent/feedback/loops/{worker_type}/refit      Record a refit event
    GET  /v1/agent/feedback/loops/{worker_type}/events     Recent learning events
    GET  /v1/agent/feedback/loops/{worker_type}/metrics    Metrics snapshot
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, BadRequestError, NotFoundError
from shared.logger.logger import get_logger, metrics
from shared.store import get_store

logger = get_logger("aether.service.agent.feedback")
router = APIRouter(prefix="/v1/agent/feedback", tags=["Agent Feedback"])

_loop_store = get_store("agent_feedback_loops")
_event_store = get_store("agent_feedback_events")


VALID_EVENT_TYPES = ["sample_added", "refit", "threshold_shifted", "priority_boosted"]


class LoopSnapshot(BaseModel):
    auto_accept_threshold: float = Field(..., ge=0.0, le=1.0)
    discard_threshold: float = Field(..., ge=0.0, le=1.0)
    sample_count: int = Field(default=0, ge=0)
    approval_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    priority_boost: float = Field(default=0.0)
    last_refit_at: Optional[str] = None


class LearningEvent(BaseModel):
    event_type: str
    worker_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _key(tenant_id: str, worker_type: str) -> str:
    return f"{tenant_id}:{worker_type}"


@router.get("/loops")
async def list_loops(request: Request):
    """List feedback loops (one per worker type) for the current tenant."""
    tenant = request.state.tenant
    tenant.require_permission("agent:manage")
    loops = await _loop_store.find(tenant_id=tenant.tenant_id)
    return APIResponse(data={"loops": loops, "count": len(loops)}).to_dict()


@router.get("/loops/{worker_type}")
async def get_loop(worker_type: str, request: Request):
    """Get the loop snapshot for a single worker type."""
    tenant = request.state.tenant
    tenant.require_permission("agent:manage")
    record = await _loop_store.get(_key(tenant.tenant_id, worker_type))
    if not record:
        raise NotFoundError(f"Feedback loop not found for worker_type={worker_type}")
    return APIResponse(data=record).to_dict()


@router.post("/loops/{worker_type}")
async def upsert_loop(worker_type: str, body: LoopSnapshot, request: Request):
    """Upsert the loop snapshot. Used by the agent layer to publish state."""
    tenant = request.state.tenant
    tenant.require_permission("agent:manage")
    if body.discard_threshold > body.auto_accept_threshold:
        raise BadRequestError(
            "discard_threshold must be <= auto_accept_threshold"
        )

    record = body.model_dump()
    record["worker_type"] = worker_type
    record["tenant_id"] = tenant.tenant_id
    record["updated_at"] = _now()
    await _loop_store.set(_key(tenant.tenant_id, worker_type), record)
    metrics.increment("agent_feedback_loop_upserts", labels={"worker_type": worker_type})
    return APIResponse(data=record).to_dict()


@router.post("/loops/{worker_type}/refit")
async def record_refit(worker_type: str, request: Request, body: dict[str, Any] | None = None):
    """Record a refit event in the learning event log."""
    tenant = request.state.tenant
    tenant.require_permission("agent:manage")
    if not await _loop_store.get(_key(tenant.tenant_id, worker_type)):
        raise NotFoundError(f"Feedback loop not found for worker_type={worker_type}")

    event = LearningEvent(
        event_type="refit",
        worker_type=worker_type,
        payload=body or {},
    ).model_dump()
    event["tenant_id"] = tenant.tenant_id
    await _event_store.append_list(_key(tenant.tenant_id, worker_type), event)

    record = await _loop_store.get(_key(tenant.tenant_id, worker_type))
    record["last_refit_at"] = event["timestamp"]
    record["updated_at"] = _now()
    await _loop_store.set(_key(tenant.tenant_id, worker_type), record)

    metrics.increment("agent_feedback_refits", labels={"worker_type": worker_type})
    return APIResponse(data=event).to_dict()


@router.get("/loops/{worker_type}/events")
async def list_events(worker_type: str, request: Request, limit: int = 100):
    """Return recent learning events for a loop."""
    tenant = request.state.tenant
    tenant.require_permission("agent:manage")
    if not await _loop_store.get(_key(tenant.tenant_id, worker_type)):
        raise NotFoundError(f"Feedback loop not found for worker_type={worker_type}")
    events = await _event_store.get_list(
        _key(tenant.tenant_id, worker_type), limit=limit
    )
    return APIResponse(data={"events": events, "count": len(events)}).to_dict()


@router.get("/loops/{worker_type}/metrics")
async def get_metrics(worker_type: str, request: Request):
    """Compact metrics snapshot suitable for dashboards."""
    tenant = request.state.tenant
    tenant.require_permission("agent:manage")
    record = await _loop_store.get(_key(tenant.tenant_id, worker_type))
    if not record:
        raise NotFoundError(f"Feedback loop not found for worker_type={worker_type}")
    events = await _event_store.get_list(_key(tenant.tenant_id, worker_type), limit=1000)
    refit_count = sum(1 for e in events if e.get("event_type") == "refit")

    return APIResponse(data={
        "worker_type": worker_type,
        "auto_accept_threshold": record.get("auto_accept_threshold"),
        "discard_threshold": record.get("discard_threshold"),
        "sample_count": record.get("sample_count", 0),
        "approval_rate": record.get("approval_rate", 0.0),
        "priority_boost": record.get("priority_boost", 0.0),
        "refit_count": refit_count,
        "last_refit_at": record.get("last_refit_at"),
    }).to_dict()
