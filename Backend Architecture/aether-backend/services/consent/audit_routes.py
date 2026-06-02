"""
Aether Service — Audit Trail Export

Cross-domain audit surface that fans out across the persistence layers each
service actually uses. Sources that already exist:

  - agent_audit          shared.store, list-backed (key=tenant_id)
  - guardrail_decisions  shared.store, list-backed (key="decisions:{tenant_id}")
  - extraction_runs      shared.store, set-backed  (records have tenant_id)
  - consent_records      ConsentRepository (DB-backed via repositories.repos)
  - consent_dsr          ConsentRepository (same table, id prefix "dsr_")

Endpoints:
    GET  /v1/audit/trails                  Paginated, filterable trail entries
    GET  /v1/audit/trails/{entry_id}       Cross-source single-entry lookup
    POST /v1/audit/exports                 Synchronous fan-out + persist job
    GET  /v1/audit/exports                 Recent export jobs
    GET  /v1/audit/exports/{export_id}     Export job status
    GET  /v1/audit/reports/soc2            Per-source counts
    GET  /v1/audit/reports/gdpr            Consent + DSR breakdown
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from repositories.repos import ConsentRepository
from services.security.export_governance import audit_export_governance
from shared.common.common import APIResponse, BadRequestError, NotFoundError
from shared.logger.logger import get_logger, metrics
from shared.store import get_store

logger = get_logger("aether.service.audit")
router = APIRouter(prefix="/v1/audit", tags=["Audit"])

_export_store = get_store("audit_exports")
_consent_repo = ConsentRepository()

VALID_EXPORT_FORMATS = ["json", "csv", "ndjson"]
VALID_REPORT_TYPES = ["soc2", "gdpr", "iso27001", "custom"]


# ── Source readers ─────────────────────────────────────────────────────
# Each reader returns the audit records for a single tenant. The signature
# is async (tenant_id) -> list[dict].
SourceReader = Callable[[str], Awaitable[list[dict]]]


async def _read_list_store(name: str, key_fn: Callable[[str], str], tenant_id: str) -> list[dict]:
    store = get_store(name)
    return await store.get_list(key_fn(tenant_id), limit=10_000)


async def _read_set_store(name: str, tenant_id: str) -> list[dict]:
    store = get_store(name)
    return await store.find(tenant_id=tenant_id)


async def _read_agent_audit(tenant_id: str) -> list[dict]:
    return await _read_list_store("agent_audit", lambda t: t, tenant_id)


async def _read_guardrail_decisions(tenant_id: str) -> list[dict]:
    return await _read_list_store(
        "guardrail_decisions", lambda t: f"decisions:{t}", tenant_id,
    )


async def _read_extraction_runs(tenant_id: str) -> list[dict]:
    return await _read_set_store("extraction_runs", tenant_id)


async def _read_consent_records(tenant_id: str) -> list[dict]:
    """Consent records, excluding DSRs (which are co-located in the same table)."""
    records = await _consent_repo.find_many(filters={"tenant_id": tenant_id}, limit=10_000)
    return [r for r in records if not _looks_like_dsr(r)]


async def _read_consent_dsr(tenant_id: str) -> list[dict]:
    records = await _consent_repo.find_many(filters={"tenant_id": tenant_id}, limit=10_000)
    return [r for r in records if _looks_like_dsr(r)]


def _looks_like_dsr(record: dict) -> bool:
    return "dsr_id" in record or "request_type" in record


SOURCE_READERS: dict[str, SourceReader] = {
    "agent_audit": _read_agent_audit,
    "guardrail_decisions": _read_guardrail_decisions,
    "extraction_runs": _read_extraction_runs,
    "consent_records": _read_consent_records,
    "consent_dsr": _read_consent_dsr,
}
AUDIT_SOURCES = list(SOURCE_READERS.keys())


class ExportRequest(BaseModel):
    sources: list[str] = Field(default_factory=list, description="Subset of AUDIT_SOURCES; empty = all")
    format: str = Field(default="json")
    from_ts: Optional[str] = None
    to_ts: Optional[str] = None
    report_type: str = Field(default="custom")
    approval_id: Optional[str] = Field(default=None, description="Required for high-risk export types")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _read_source(source: str, tenant_id: str) -> list[dict]:
    reader = SOURCE_READERS.get(source)
    if not reader:
        return []
    return await reader(tenant_id)


def _filter_by_time(records: list[dict], from_ts: Optional[str], to_ts: Optional[str]) -> list[dict]:
    if not from_ts and not to_ts:
        return records
    out = []
    for r in records:
        ts = (
            r.get("created_at") or r.get("timestamp")
            or r.get("recorded_at") or r.get("submitted_at")
            or r.get("updated_at") or ""
        )
        if from_ts and ts < from_ts:
            continue
        if to_ts and ts > to_ts:
            continue
        out.append(r)
    return out


def _sort_key(r: dict) -> str:
    return (
        r.get("created_at") or r.get("timestamp")
        or r.get("recorded_at") or r.get("submitted_at")
        or r.get("updated_at") or ""
    )


@router.get("/trails")
async def list_trails(
    request: Request,
    source: str = "",
    from_ts: str = "",
    to_ts: str = "",
    limit: int = 200,
):
    tenant = request.state.tenant
    tenant.require_permission("admin")

    if source and source not in AUDIT_SOURCES:
        raise BadRequestError(f"Unknown source '{source}'. Valid: {AUDIT_SOURCES}")
    sources = [source] if source else AUDIT_SOURCES

    out: list[dict] = []
    for s in sources:
        for r in await _read_source(s, tenant.tenant_id):
            r = dict(r)
            r["_source"] = s
            out.append(r)

    out = _filter_by_time(out, from_ts or None, to_ts or None)
    out.sort(key=_sort_key, reverse=True)
    out = out[:limit]
    return APIResponse(data={"trails": out, "count": len(out), "sources": sources}).to_dict()


@router.get("/trails/{entry_id}")
async def get_trail(entry_id: str, request: Request):
    """Look up a single audit entry by id across all sources.

    Each source persists differently; we scan readers and match on common id
    fields (`task_id`, `policy_id`, `run_id`, `dsr_id`, or repository id).
    """
    tenant = request.state.tenant
    tenant.require_permission("admin")

    id_fields = ("id", "task_id", "policy_id", "run_id", "dsr_id", "export_id")
    for s in AUDIT_SOURCES:
        for r in await _read_source(s, tenant.tenant_id):
            for field in id_fields:
                if r.get(field) == entry_id:
                    record = dict(r)
                    record["_source"] = s
                    return APIResponse(data=record).to_dict()
    raise NotFoundError(f"Audit entry not found: {entry_id}")


@router.post("/exports")
async def request_export(body: ExportRequest, request: Request):
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
    # Governance: enforce export permission, block cross-tenant export, flag
    # high-risk exports, and attach an integrity hash + expiry. Emits/records via
    # the security policy engine + audit ledger.
    governance = await audit_export_governance.authorize_create(
        actor_id=getattr(tenant, "user_id", None) or tenant.tenant_id,
        actor_type='tenant_user', tenant_id=tenant.tenant_id,
        export_type=body.report_type,
        has_export_permission=tenant.has_permission("export") or tenant.has_permission("admin"),
        target_tenant=tenant.tenant_id,
        approval_id=getattr(body, "approval_id", None),
        manifest={"sources": sources, "row_count": len(rows), "per_source": per_source},
        ip_address=request.client.host if request.client else None,
    )
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
        "integrity_hash": governance["integrity_hash"],
        "expires_at": governance["expires_at"],
        "high_risk": governance["high_risk"],
        "policy_decision_id": governance["policy_decision_id"],
    }
    await _export_store.set(f"{tenant.tenant_id}:{export_id}", record)
    metrics.increment(
        "audit_exports",
        labels={"format": body.format, "report_type": body.report_type},
    )
    return APIResponse(data={**record, "rows": rows}).to_dict()


@router.get("/exports")
async def list_exports(request: Request, limit: int = 50):
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
    # Governance: enforce permission + expiry on download, and audit the access.
    await audit_export_governance.authorize_download(
        actor_id=getattr(tenant, "user_id", None) or tenant.tenant_id,
        actor_type='tenant_user', tenant_id=tenant.tenant_id, export_id=export_id,
        has_export_permission=tenant.has_permission("export") or tenant.has_permission("admin"),
        expires_at=record.get("expires_at"),
        ip_address=request.client.host if request.client else None,
    )
    return APIResponse(data=record).to_dict()


@router.get("/reports/soc2")
async def soc2_report(request: Request):
    tenant = request.state.tenant
    tenant.require_permission("admin")
    counts: dict[str, int] = {}
    for s in AUDIT_SOURCES:
        counts[s] = len(await _read_source(s, tenant.tenant_id))
    return APIResponse(data={
        "report_type": "soc2",
        "tenant_id": tenant.tenant_id,
        "generated_at": _now(),
        "total_records": sum(counts.values()),
        "per_source": counts,
    }).to_dict()


@router.get("/reports/gdpr")
async def gdpr_report(request: Request):
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
