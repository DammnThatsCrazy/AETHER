"""
Aether Service — Audit Trail Export

Cross-domain audit surface that fans out across the per-service audit stores
(agent_audit, x402 settlements, web3 audit, etc.) plus exposes export jobs
for SOC2 / GDPR compliance reporting.

Endpoints:
    GET  /v1/audit/trails                  Paginated, filterable trail entries
    GET  /v1/audit/trails/{entry_id}       Single trail entry (lookup helper)
    POST /v1/audit/exports                 Request an export (sync or async)
    GET  /v1/audit/exports                 List recent export jobs
    GET  /v1/audit/exports/{export_id}     Export job status
    GET  /v1/audit/reports/soc2            SOC2 compliance summary
    GET  /v1/audit/reports/gdpr            GDPR DSR + consent summary
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, BadRequestError, NotFoundError
from shared.logger.logger import get_logger, metrics
from shared.store import get_store

logger = get_logger("aether.service.audit")
router = APIRouter(prefix="/v1/audit", tags=["Audit"])

_export_store = get_store("audit_exports")

# Sources audit trails are aggregated from. Each is a per-service store.
AUDIT_SOURCES = [
    "agent_audit",
    "guardrail_decisions",
    "extraction_runs",
    "x402_settlements",
    "consent_records",
    "consent_dsr",
]

VALID_EXPORT_FORMATS = ["json", "csv", "ndjson"]
VALID_REPORT_TYPES = ["soc2", "gdpr", "iso27001", "custom"]


class ExportRequest(BaseModel):
    sources: list[str] = Field(default_factory=list, description="Subset of AUDIT_SOURCES; empty = all")
    format: str = Field(default="json", description="json | csv | ndjson")
    from_ts: Optional[str] = None
    to_ts: Optional[str] = None
    report_type: str = Field(default="custom")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _read_source(source: str, tenant_id: str) -> list[dict]:
    """Read all records from a per-service audit store, scoped to tenant."""
    if source not in AUDIT_SOURCES:
        return []
    store = get_store(source)
    return await store.find(tenant_id=tenant_id)


def _filter_by_time(records: list[dict], from_ts: Optional[str], to_ts: Optional[str]) -> list[dict]:
    if not from_ts and not to_ts:
        return records
    out = []
    for r in records:
        ts = r.get("created_at") or r.get("timestamp") or r.get("updated_at") or ""
        if from_ts and ts < from_ts:
            continue
        if to_ts and ts > to_ts:
            continue
        out.append(r)
    return out


@router.get("/trails")
async def list_trails(
    request: Request,
    source: str = "",
    from_ts: str = "",
    to_ts: str = "",
    limit: int = 200,
):
    """List audit trail entries across one or all sources."""
    tenant = request.state.tenant
    tenant.require_permission("admin")

    sources = [source] if source else AUDIT_SOURCES
    if source and source not in AUDIT_SOURCES:
        raise BadRequestError(f"Unknown source '{source}'. Valid: {AUDIT_SOURCES}")

    out: list[dict] = []
    for s in sources:
        records = await _read_source(s, tenant.tenant_id)
        for r in records:
            r = dict(r)
            r["_source"] = s
            out.append(r)

    out = _filter_by_time(out, from_ts or None, to_ts or None)
    out.sort(
        key=lambda r: r.get("created_at") or r.get("timestamp") or r.get("updated_at") or "",
        reverse=True,
    )
    out = out[:limit]
    return APIResponse(data={"trails": out, "count": len(out), "sources": sources}).to_dict()


@router.get("/trails/{entry_id}")
async def get_trail(entry_id: str, request: Request):
    """Look up a single audit entry by id across all sources."""
    tenant = request.state.tenant
    tenant.require_permission("admin")
    for s in AUDIT_SOURCES:
        store = get_store(s)
        record = await store.get(f"{tenant.tenant_id}:{entry_id}")
        if record:
            record = dict(record)
            record["_source"] = s
            return APIResponse(data=record).to_dict()
    raise NotFoundError(f"Audit entry not found: {entry_id}")


@router.post("/exports")
async def request_export(body: ExportRequest, request: Request):
    """Create an audit export job. Synchronous fan-out for now."""
    tenant = request.state.tenant
    tenant.require_permission("admin")

    if body.format not in VALID_EXPORT_FORMATS:
        raise BadRequestError(f"Invalid format. Valid: {VALID_EXPORT_FORMATS}")
    if body.report_type not in VALID_REPORT_TYPES:
        raise BadRequestError(f"Invalid report_type. Valid: {VALID_REPORT_TYPES}")

    sources = body.sources or AUDIT_SOURCES
    for s in sources:
        if s not in AUDIT_SOURCES:
            raise BadRequestError(f"Unknown source '{s}'. Valid: {AUDIT_SOURCES}")

    rows: list[dict] = []
    per_source: dict[str, int] = {}
    for s in sources:
        records = await _read_source(s, tenant.tenant_id)
        records = _filter_by_time(records, body.from_ts, body.to_ts)
        per_source[s] = len(records)
        for r in records:
            row = dict(r)
            row["_source"] = s
            rows.append(row)

    export_id = str(uuid.uuid4())
    record = {
        "export_id": export_id,
        "tenant_id": tenant.tenant_id,
        "format": body.format,
        "report_type": body.report_type,
        "sources": sources,
        "row_count": len(rows),
        "per_source": per_source,
        "from_ts": body.from_ts,
        "to_ts": body.to_ts,
        "status": "complete",
        "created_at": _now(),
    }
    await _export_store.set(f"{tenant.tenant_id}:{export_id}", record)
    metrics.increment("audit_exports", labels={"format": body.format, "report_type": body.report_type})
    return APIResponse(data={**record, "rows": rows}).to_dict()


@router.get("/exports")
async def list_exports(request: Request, limit: int = 50):
    """List recent export jobs for this tenant."""
    tenant = request.state.tenant
    tenant.require_permission("admin")
    exports = await _export_store.find(tenant_id=tenant.tenant_id)
    exports.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return APIResponse(data={"exports": exports[:limit], "count": min(limit, len(exports))}).to_dict()


@router.get("/exports/{export_id}")
async def get_export(export_id: str, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("admin")
    record = await _export_store.get(f"{tenant.tenant_id}:{export_id}")
    if not record:
        raise NotFoundError(f"Export not found: {export_id}")
    return APIResponse(data=record).to_dict()


@router.get("/reports/soc2")
async def soc2_report(request: Request):
    """Compact SOC2-style summary across audit sources."""
    tenant = request.state.tenant
    tenant.require_permission("admin")
    counts: dict[str, int] = {}
    for s in AUDIT_SOURCES:
        records = await _read_source(s, tenant.tenant_id)
        counts[s] = len(records)
    total = sum(counts.values())
    return APIResponse(data={
        "report_type": "soc2",
        "tenant_id": tenant.tenant_id,
        "generated_at": _now(),
        "total_records": total,
        "per_source": counts,
    }).to_dict()


@router.get("/reports/gdpr")
async def gdpr_report(request: Request):
    """GDPR-focused summary highlighting consent + DSR activity."""
    tenant = request.state.tenant
    tenant.require_permission("admin")
    consent = await _read_source("consent_records", tenant.tenant_id)
    dsr = await _read_source("consent_dsr", tenant.tenant_id)

    dsr_by_status: dict[str, int] = {}
    for r in dsr:
        s = str(r.get("status", "unknown"))
        dsr_by_status[s] = dsr_by_status.get(s, 0) + 1

    return APIResponse(data={
        "report_type": "gdpr",
        "tenant_id": tenant.tenant_id,
        "generated_at": _now(),
        "consent_record_count": len(consent),
        "dsr_total": len(dsr),
        "dsr_by_status": dsr_by_status,
    }).to_dict()
