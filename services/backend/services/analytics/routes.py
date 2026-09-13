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
    APIResponse, BadRequestError, NotFoundError,
    PaginatedResponse, PaginationMeta, utc_now,
)
from shared.cache.cache import CacheClient
from shared.logger.logger import get_logger, metrics
from shared.observability import trace_request, emit_latency, record_graphql_query
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

    # Create the job in queued state
    job = {
        "export_id": export_id,
        "tenant_id": tenant.tenant_id,
        "format": body.format,
        "status": "queued",
        "row_count": 0,
        "query_hash": query_hash,
        "created_at": now,
        "completed_at": None,
        "error": None,
        "download_url": None,
    }
    await _export_store.set(export_id, job)

    # Execute export: try Celery offload, fallback to inline
    try:
        from celery import Celery
        celery_broker = __import__("os").getenv("CELERY_BROKER_URL", "")
        if celery_broker:
            # Offload to Celery worker for large/async exports
            _celery_app = Celery("aether", broker=celery_broker)
            _celery_app.send_task(
                "aether.analytics.export",
                kwargs={
                    "export_id": export_id,
                    "tenant_id": tenant.tenant_id,
                    "query_params": body.query.model_dump(exclude_none=True),
                    "format": body.format,
                },
            )
            job["status"] = "processing"
            await _export_store.set(export_id, job)
            logger.info("Export job %s queued to Celery", export_id)
        else:
            raise ImportError("No Celery broker configured")
    except (ImportError, Exception):
        # Inline execution when Celery is not available
        try:
            results = await repo.query_events(
                tenant.tenant_id,
                body.query.model_dump(exclude_none=True),
                limit=10_000,
            )
            job["row_count"] = len(results)
            job["status"] = "completed"
            job["completed_at"] = utc_now().isoformat()
            job["download_url"] = f"/v1/analytics/export/{export_id}/download"
        except Exception:
            logger.exception("Export query failed for job %s", export_id)
            job["status"] = "failed"
            job["error"] = "Export query failed. Contact support if this persists."

        await _export_store.set(export_id, job)

    emit_latency("analytics_export", ctx.elapsed_ms(), labels={"format": body.format})
    metrics.increment("analytics_exports_created", labels={"format": body.format, "status": job["status"]})
    logger.info("Export job %s: format=%s rows=%d status=%s", export_id, body.format, job["row_count"], job["status"])

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
    """Parse and validate a GraphQL query for analytics dashboard.

    Uses graphql-core for proper AST parsing when available.
    Falls back to regex extraction for environments without graphql-core.
    """
    query = query.strip()
    if not query:
        raise BadRequestError("Empty GraphQL query")

    # Block introspection regardless of parser
    if "__schema" in query or "__type" in query:
        raise BadRequestError("Introspection is disabled")

    # Check depth before parsing (cheap brace-counting guard)
    depth = query.count("{")
    if depth > _MAX_QUERY_DEPTH:
        raise BadRequestError(f"Query too deep ({depth} > {_MAX_QUERY_DEPTH})")

    try:
        from graphql import parse as gql_parse, DocumentNode
        return _parse_graphql_ast(query, gql_parse)
    except ImportError:
        return _parse_graphql_regex(query)


def _parse_graphql_ast(query: str, gql_parse: Any) -> dict:
    """AST-based parser using graphql-core."""
    try:
        doc = gql_parse(query)
    except Exception as e:
        raise BadRequestError(f"Invalid GraphQL syntax: {e}")

    if not doc.definitions:
        raise BadRequestError("Empty GraphQL document")

    op = doc.definitions[0]
    if not hasattr(op, "selection_set") or not op.selection_set:
        raise BadRequestError("Query must have a selection set")

    root_selections = op.selection_set.selections
    if not root_selections:
        raise BadRequestError("Query must specify at least one root field")

    root_field = root_selections[0]
    root_type = root_field.name.value

    if root_type not in _GRAPHQL_FIELDS:
        raise BadRequestError(
            f"Unknown root type: {root_type}. Available: {list(_GRAPHQL_FIELDS.keys())}"
        )

    # Extract nested field names
    fields: list[str] = []
    if root_field.selection_set:
        for sel in root_field.selection_set.selections:
            if hasattr(sel, "name"):
                fields.append(sel.name.value)

    if not fields:
        raise BadRequestError("Query must specify fields")

    # Validate fields against allowed set
    allowed = _GRAPHQL_FIELDS[root_type]
    invalid = [f for f in fields if f not in allowed]
    if invalid:
        raise BadRequestError(f"Unknown fields for {root_type}: {invalid}")

    if len(fields) > _MAX_FIELDS:
        raise BadRequestError(f"Too many fields requested ({len(fields)} > {_MAX_FIELDS})")

    return {"root_type": root_type, "fields": fields}


def _parse_graphql_regex(query: str) -> dict:
    """Regex fallback parser for environments without graphql-core."""
    match = re.match(r"(?:query\s+\w*\s*)?\{\s*(\w+)", query)
    if not match:
        raise BadRequestError("Invalid GraphQL query syntax")

    root_type = match.group(1)
    if root_type not in _GRAPHQL_FIELDS:
        raise BadRequestError(
            f"Unknown root type: {root_type}. Available: {list(_GRAPHQL_FIELDS.keys())}"
        )

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


# ── Commerce KPI Aggregators ──────────────────────────────────────────────────


@router.get("/commerce/kpi")
async def commerce_kpi(request: Request, period: str = "30d"):
    """
    Commerce KPI summary for a tenant: spend rate, approval latency,
    settlement degradation, and entitlement reuse rate.
    Consumes SettlementEventRepository and x402 CommerceStore.
    """
    request.state.tenant.require_permission("commerce:read")
    tenant_id = request.state.tenant.tenant_id

    from repositories.repos import SettlementEventRepository
    from services.x402.commerce_store import get_commerce_store
    from datetime import datetime, timedelta, timezone
    from decimal import Decimal

    now = datetime.now(timezone.utc)
    cutoff: Optional[str] = None
    if period != "all":
        try:
            days = int(period.rstrip("d"))
            cutoff = (now - timedelta(days=days)).isoformat()
        except ValueError:
            pass

    settlements_repo = SettlementEventRepository()
    rows = await settlements_repo.find_many(filters={"tenant_id": tenant_id}, limit=10000)
    if cutoff:
        rows = [r for r in rows if r.get("occurred_at", "") >= cutoff]

    total = len(rows)
    settled = [r for r in rows if r.get("status") in {"settled", "paid", "success", "access_granted"}]
    failed = [r for r in rows if r.get("status") in {"failed", "error"}]

    # Spend rate: total settled volume / period days
    period_days = int(period.rstrip("d")) if period != "all" else 30
    total_volume = sum(float(Decimal(str(r.get("amount") or 0))) for r in settled)
    spend_rate_per_day = round(total_volume / period_days, 6) if period_days else 0.0

    # Settlement degradation: failed / total (0 if no data)
    settlement_degradation = round(len(failed) / total, 4) if total else 0.0

    # Approval latency: read from commerce store approvals
    store = get_commerce_store()
    approvals = await store.list_approvals(tenant_id)
    if cutoff:
        approvals = [a for a in approvals if getattr(a, "created_at", "") >= cutoff]
    decided = [
        a for a in approvals
        if getattr(a, "decided_at", None) and getattr(a, "created_at", None)
    ]
    avg_approval_latency_seconds: Optional[float] = None
    if decided:
        from datetime import datetime as _dt
        def _seconds(a) -> float:
            try:
                c = _dt.fromisoformat(a.created_at)
                d = _dt.fromisoformat(a.decided_at)
                return abs((d - c).total_seconds())
            except Exception:
                return 0.0
        avg_approval_latency_seconds = round(
            sum(_seconds(a) for a in decided) / len(decided), 2
        )

    # Reuse rate: entitlements reused / total entitlements
    entitlements = await store.list_entitlements(tenant_id)
    if cutoff:
        entitlements = [e for e in entitlements if getattr(e, "granted_at", getattr(e, "created_at", "")) >= cutoff]
    reused = [e for e in entitlements if getattr(e, "reuse_count", 0) > 0]
    reuse_rate = round(len(reused) / len(entitlements), 4) if entitlements else 0.0

    result = {
        "tenant_id": tenant_id,
        "period": period,
        "settled_count": len(settled),
        "failed_count": len(failed),
        "total_volume_usd": round(total_volume, 6),
        "spend_rate_per_day_usd": spend_rate_per_day,
        "settlement_degradation_rate": settlement_degradation,
        "avg_approval_latency_seconds": avg_approval_latency_seconds,
        "entitlement_reuse_rate": reuse_rate,
        "computed_at": now.isoformat(),
    }
    metrics.increment("analytics_commerce_kpi_computed")
    return APIResponse(data=result).to_dict()
