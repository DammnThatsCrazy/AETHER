"""
Aether Service — Diagnostics Observability

Exposes the in-process metrics collector that lives in
shared.logger.logger.MetricsCollector, plus a thin trace log surface backed
by the `observability_traces` durable store. Production deployments wire
trace ingestion to OTLP; this surface gives operators a usable view either
way.

Endpoints:
    GET  /v1/diagnostics/observability/metrics              Snapshot of counters + histograms
    GET  /v1/diagnostics/observability/metrics/{name}       Single metric series
    GET  /v1/diagnostics/observability/traces               Recent trace records
    POST /v1/diagnostics/observability/traces               Append a trace record
    GET  /v1/diagnostics/observability/summary              Compact health summary
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, BadRequestError
from shared.logger.logger import get_logger, metrics
from shared.store import get_store

logger = get_logger("aether.service.diagnostics.observability")
router = APIRouter(
    prefix="/v1/diagnostics/observability",
    tags=["Diagnostics — Observability"],
)

_trace_store = get_store("observability_traces")


class TraceRecord(BaseModel):
    request_id: str
    service: str
    endpoint: str
    duration_ms: float = Field(..., ge=0.0)
    status: str = Field(..., pattern="^(ok|error|timeout|cancelled)$")
    error: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


def _trace_key(tenant_id: str) -> str:
    return f"traces:{tenant_id}"


@router.get("/metrics")
async def metrics_snapshot(request: Request):
    """Return the full counter + histogram snapshot."""
    tenant = request.state.tenant
    tenant.require_permission("admin")
    snap = metrics.snapshot()
    return APIResponse(data=snap).to_dict()


@router.get("/metrics/{name}")
async def get_metric(name: str, request: Request):
    """Return all counter + histogram series whose name starts with `name`."""
    tenant = request.state.tenant
    tenant.require_permission("admin")
    snap = metrics.snapshot()

    counter_matches = {k: v for k, v in snap.get("counters", {}).items() if k.startswith(name)}
    hist_matches = {k: v for k, v in snap.get("histograms", {}).items() if k.startswith(name)}

    if not counter_matches and not hist_matches:
        return APIResponse(data={"name": name, "counters": {}, "histograms": {}}).to_dict()

    return APIResponse(data={
        "name": name,
        "counters": counter_matches,
        "histograms": hist_matches,
    }).to_dict()


@router.post("/traces")
async def append_trace(body: TraceRecord, request: Request):
    """Append a trace record to the per-tenant trace log."""
    tenant = request.state.tenant
    tenant.require_permission("admin")
    if body.duration_ms < 0:
        raise BadRequestError("duration_ms must be non-negative")

    record = body.model_dump()
    record["tenant_id"] = tenant.tenant_id
    await _trace_store.append_list(_trace_key(tenant.tenant_id), record)
    metrics.observe("observability_trace_duration_ms", body.duration_ms,
                    labels={"service": body.service, "status": body.status})
    return APIResponse(data=record).to_dict()


@router.get("/traces")
async def list_traces(
    request: Request,
    service: str = "",
    status: str = "",
    limit: int = 100,
):
    """Return the most recent trace records for this tenant."""
    tenant = request.state.tenant
    tenant.require_permission("admin")
    traces = await _trace_store.get_list(_trace_key(tenant.tenant_id), limit=limit)

    if service:
        traces = [t for t in traces if t.get("service") == service]
    if status:
        traces = [t for t in traces if t.get("status") == status]

    return APIResponse(data={"traces": traces, "count": len(traces)}).to_dict()


@router.get("/summary")
async def summary(request: Request):
    """Compact health summary suitable for top-of-page widgets."""
    tenant = request.state.tenant
    tenant.require_permission("admin")
    snap = metrics.snapshot()
    traces = await _trace_store.get_list(_trace_key(tenant.tenant_id), limit=500)

    error_traces = [t for t in traces if t.get("status") in ("error", "timeout")]
    total = len(traces)
    err_rate = (len(error_traces) / total) if total else None

    durations = [
        float(t["duration_ms"]) for t in traces if t.get("duration_ms") is not None
    ]
    durations.sort()
    p50 = durations[len(durations) // 2] if durations else None
    p95_idx = max(0, int(len(durations) * 0.95) - 1)
    p95 = durations[p95_idx] if durations else None

    return APIResponse(data={
        "trace_sample_size": total,
        "error_rate": err_rate,
        "p50_duration_ms": p50,
        "p95_duration_ms": p95,
        "counter_keys": len(snap.get("counters", {})),
        "histogram_keys": len(snap.get("histograms", {})),
        "availability": "available" if traces else "insufficient_evidence",
    }).to_dict()
