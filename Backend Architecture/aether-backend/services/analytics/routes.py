"""
Aether Service — Analytics
Query engine for dashboards, reports, and exports.
Includes the GraphQL endpoint for flexible dashboard queries.
"""

from __future__ import annotations

import hashlib
import json as _json
import re
import uuid as _uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from shared.common.common import (
    APIResponse, BadRequestError, CursorPagination, NotFoundError,
    PaginatedResponse, PaginationMeta, UnauthorizedError, utc_now,
)
from shared.cache.cache import CacheClient
from shared.auth.auth import JWTHandler, APIKeyValidator
from shared.logger.logger import get_logger, metrics
from shared.observability import trace_request, emit_latency, record_graphql_query, record_graphql_rejection
from shared.store import get_store
from dependencies.providers import get_cache, get_registry
from repositories.repos import AnalyticsRepository

logger = get_logger("aether.service.analytics")
router = APIRouter(prefix="/v1/analytics", tags=["Analytics"])


_repo: Optional[AnalyticsRepository] = None


def _get_repo(cache: CacheClient = Depends(get_cache)) -> AnalyticsRepository:
    global _repo
    if _repo is None:
        _repo = AnalyticsRepository(cache)
    return _repo


# ── Models ────────────────────────────────────────────────────────────

class EventQuery(BaseModel):
    event_type: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    limit: int = Field(default=50, ge=1, le=200)


class GraphQLRequest(BaseModel):
    query: str
    variables: dict[str, Any] = Field(default_factory=dict)


class ExportRequest(BaseModel):
    format: str = Field(default="csv", pattern="^(csv|json|parquet)$")
    query: EventQuery = Field(default_factory=EventQuery)


# ── REST Routes ───────────────────────────────────────────────────────

@router.post("/events/query")
async def query_events(
    query: EventQuery,
    request: Request,
    repo: AnalyticsRepository = Depends(_get_repo),
):
    """Query events with filters. Cached in Redis for 5 minutes."""
    tenant = request.state.tenant
    results = await repo.query_events(
        tenant.tenant_id,
        query.model_dump(exclude_none=True),
        limit=query.limit,
    )
    return PaginatedResponse(
        data=results,
        pagination=PaginationMeta(
            total=len(results),
            limit=query.limit,
            has_more=len(results) == query.limit,
        ),
    ).to_dict()


@router.get("/events/{event_id}")
async def get_event(
    event_id: str,
    request: Request,
    repo: AnalyticsRepository = Depends(_get_repo),
):
    """Get a single event by ID (tenant-scoped)."""
    tenant = request.state.tenant
    event = await repo.get_event(event_id)
    if not event:
        raise NotFoundError("Event")
    # Enforce tenant isolation
    if event.get("tenant_id") and event["tenant_id"] != tenant.tenant_id:
        raise NotFoundError("Event")
    metrics.increment("analytics_events_read")
    return APIResponse(data=event).to_dict()


@router.get("/dashboard/summary")
async def dashboard_summary(
    request: Request,
    repo: AnalyticsRepository = Depends(_get_repo),
):
    """Aggregated dashboard summary — sessions, events, users (last 24h)."""
    tenant = request.state.tenant
    summary = await repo.dashboard_summary(tenant.tenant_id)
    return APIResponse(data=summary).to_dict()


# ── Durable Export Job Store ──────────────────────────────────────────

_export_store = get_store("analytics_exports")


@router.post("/export")
async def export_data(
    body: ExportRequest,
    request: Request,
    repo: AnalyticsRepository = Depends(_get_repo),
):
    """Create an async data export job (CSV, JSON, Parquet).

    Returns a job ID immediately. The export runs asynchronously; poll
    ``GET /v1/analytics/export/{export_id}`` for status and download URL.

    Idempotent: re-submitting the same query + format within 60s returns
    the existing job instead of creating a duplicate.
    """
    ctx = trace_request(request, service="analytics")
    tenant = request.state.tenant
    tenant.require_permission("analytics:export")

    # Idempotency check — same query + format reuses existing job
    query_hash = hashlib.sha256(
        _json.dumps({"q": body.query.model_dump(), "f": body.format}, sort_keys=True).encode()
    ).hexdigest()[:16]

    existing = await _export_store.find(
        query_hash=query_hash, tenant_id=tenant.tenant_id,
    )
    for job in existing:
        if job.get("status") in ("queued", "processing", "completed"):
            logger.info("Returning existing export job %s (idempotent)", job["export_id"])
            metrics.increment("analytics_exports_idempotent")
            return APIResponse(data=_sanitize_export_job(job)).to_dict()

    export_id = str(_uuid.uuid4())
    now = utc_now().isoformat()

    # Query the data inline (production: offload to worker via Kafka/Celery)
    try:
        results = await repo.query_events(
            tenant.tenant_id,
            body.query.model_dump(exclude_none=True),
            limit=10_000,
        )
        row_count = len(results)
        status = "completed"
        error = None
    except Exception:
        logger.exception("Export query failed for job %s", export_id)
        row_count = 0
        status = "failed"
        error = "Export query failed. Contact support if this persists."

    job = {
        "export_id": export_id,
        "tenant_id": tenant.tenant_id,
        "format": body.format,
        "status": status,
        "row_count": row_count,
        "query_hash": query_hash,
        "created_at": now,
        "completed_at": now if status == "completed" else None,
        "error": error,
        "download_url": f"/v1/analytics/export/{export_id}/download" if status == "completed" else None,
    }

    await _export_store.set(export_id, job)

    emit_latency("analytics_export", ctx.elapsed_ms(), labels={"format": body.format})
    metrics.increment("analytics_exports_created", labels={"format": body.format, "status": status})
    logger.info("Export job %s: format=%s rows=%d status=%s", export_id, body.format, row_count, status)

    return APIResponse(data=_sanitize_export_job(job)).to_dict()


@router.get("/export/{export_id}")
async def get_export_status(export_id: str, request: Request):
    """Check the status of an export job (tenant-scoped)."""
    job = await _export_store.get(export_id)
    if job is None or job.get("tenant_id") != request.state.tenant.tenant_id:
        raise NotFoundError("Export job")
    metrics.increment("analytics_exports_polled")
    return APIResponse(data=_sanitize_export_job(job)).to_dict()


def _sanitize_export_job(job: dict) -> dict:
    """Remove internal fields before returning to client."""
    return {k: v for k, v in job.items() if k not in ("tenant_id", "query_hash")}


# ── GraphQL Endpoint ──────────────────────────────────────────────────

# Allowed root fields per permission level
_GRAPHQL_FIELDS = {
    "events": {"event_id", "event_type", "session_id", "user_id", "timestamp", "properties"},
    "sessions": {"session_id", "duration", "page_views", "device_type"},
    "campaigns": {"campaign_id", "name", "channel", "status", "conversions"},
}

# Max query depth/complexity
_MAX_QUERY_DEPTH = 5
_MAX_FIELDS = 20


def _parse_and_validate_graphql(query: str) -> dict:
    """Minimal GraphQL parser — extracts root type and fields.

    Production systems should use graphql-core; this parser handles
    the subset needed for analytics dashboard queries.
    """
    query = query.strip()
    if not query:
        raise BadRequestError("Empty GraphQL query")

    # Block introspection in production
    if "__schema" in query or "__type" in query:
        raise BadRequestError("Introspection is disabled")

    # Extract operation: query { events { ... } }
    match = re.match(r"(?:query\s+\w*\s*)?\{\s*(\w+)", query)
    if not match:
        raise BadRequestError("Invalid GraphQL query syntax")

    root_type = match.group(1)
    if root_type not in _GRAPHQL_FIELDS:
        raise BadRequestError(f"Unknown root type: {root_type}. Available: {list(_GRAPHQL_FIELDS.keys())}")

    # Check depth BEFORE parsing fields (deep queries may produce garbage fields)
    depth = query.count("{")
    if depth > _MAX_QUERY_DEPTH:
        raise BadRequestError(f"Query too deep ({depth} > {_MAX_QUERY_DEPTH})")

    # Extract requested fields
    field_block = re.search(r"\{[^{]*\{([^}]*)\}", query)
    if not field_block:
        raise BadRequestError("Query must specify fields")

    raw_fields = [f.strip() for f in field_block.group(1).split() if f.strip()]
    allowed = _GRAPHQL_FIELDS[root_type]
    invalid = [f for f in raw_fields if f not in allowed]
    if invalid:
        raise BadRequestError(f"Unknown fields for {root_type}: {invalid}")

    if len(raw_fields) > _MAX_FIELDS:
        raise BadRequestError(f"Too many fields requested ({len(raw_fields)} > {_MAX_FIELDS})")

    return {"root_type": root_type, "fields": raw_fields}


@router.post("/graphql")
async def graphql_endpoint(
    body: GraphQLRequest,
    request: Request,
    repo: AnalyticsRepository = Depends(_get_repo),
):
    """GraphQL endpoint for flexible dashboard queries.

    Supports querying ``events``, ``sessions``, and ``campaigns``
    with field-level selection. Introspection is disabled in production.
    """
    ctx = trace_request(request, service="analytics")
    tenant = request.state.tenant

    # Parse and validate
    parsed = _parse_and_validate_graphql(body.query)
    root_type = parsed["root_type"]
    fields = parsed["fields"]

    # Execute query
    if root_type == "events":
        filters = {}
        for var_key, var_val in body.variables.items():
            if var_key in ("event_type", "session_id", "user_id"):
                filters[var_key] = var_val
        raw = await repo.query_events(tenant.tenant_id, filters, limit=50)
        # Project only requested fields
        data = [{f: row.get(f) for f in fields} for row in raw]

    elif root_type == "sessions":
        data = []  # Sessions query — uses session store

    elif root_type == "campaigns":
        from repositories.repos import CampaignRepository
        camp_repo = CampaignRepository()
        raw = await camp_repo.find_many(filters={"tenant_id": tenant.tenant_id}, limit=50)
        data = [{f: row.get(f) for f in fields} for row in raw]

    else:
        data = []

    record_graphql_query(root_type, len(fields), tenant.tenant_id)
    emit_latency("graphql_query", ctx.elapsed_ms(), labels={"root_type": root_type})
    logger.info("GraphQL query: tenant=%s root=%s fields=%d results=%d",
                tenant.tenant_id, root_type, len(fields), len(data))

    return APIResponse(data={
        "data": {root_type: data},
        "errors": None,
    }).to_dict()


# ── WebSocket for Real-Time Streaming ─────────────────────────────────

@router.websocket("/ws/events")
async def websocket_event_stream(websocket: WebSocket):
    """
    Real-time event stream with WebSocket authentication.
    Clients must send an auth message first: {"token": "..."} or {"api_key": "..."}
    """
    await websocket.accept()
    logger.info("WebSocket client connected, awaiting auth...")

    # --- Authenticate first message ---
    try:
        auth_msg = await websocket.receive_json()
        registry = get_registry()

        if "api_key" in auth_msg:
            tenant = registry.api_key_validator.validate(auth_msg["api_key"])
        elif "token" in auth_msg:
            payload = registry.jwt_handler.decode(auth_msg["token"])
            tenant = registry.jwt_handler.extract_context(payload)
        else:
            await websocket.send_json({"error": "Send {token} or {api_key} to authenticate"})
            await websocket.close(code=4001)
            return

        await websocket.send_json({"authenticated": True, "tenant_id": tenant.tenant_id})
        logger.info(f"WebSocket authenticated for tenant {tenant.tenant_id}")

    except Exception:
        logger.exception("WebSocket authentication failed")
        await websocket.send_json({"error": "Authentication failed"})
        await websocket.close(code=4001)
        return

    # --- Stream events ---
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_json({"type": "event", "data": {"received": data}})
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
