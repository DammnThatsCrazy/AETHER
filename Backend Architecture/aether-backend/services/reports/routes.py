"""Data Exchange reports plane — routes (/v1/data-exchange/reports, M5).

Tenant-facing surface for human-readable **PDF report artifacts**.  Every route
resolves ``request.state.tenant``, is tenant-scoped at the envelope edge, and is
gated on the ``data_exchange.*`` grants declared in
``services/data_exchange/policy.py`` (registered in the RBAC registry by the
coordinator at M3 integration; the router itself mounts only behind
``settings.data_exchange.reports_enabled``).

PDF is an ``artifact_type="report"`` egress artifact — *never* a structured
EgressFormat.  Downloads re-authorize at download time and are audited, mirroring
the canonical ``/v1/exports/{id}/download`` semantics; expired/deleted/revoked
or still-``generating`` reports refuse with a canonical error.  Grant gating
mirrors the sibling envelope routers (``routes_export.py`` /
``routes_transfer.py``): a report byte download requires a report grant *or* the
canonical egress-download grant ``data_exchange.export.download`` — never plain
``data_exchange.read`` — and a report delete requires the dedicated
``data_exchange.report.delete`` grant, so a read-only tenant can neither pull
PDF bytes nor delete reports.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel

from services.data_exchange.authz import require_data_exchange
from services.data_exchange.contracts import ReportSpecContract
from services.reports.service import (
    delete_report,
    download_report,
    emit_report_downloaded,
    get_report_detail,
    list_report_artifacts,
    request_report,
)
from services.security.audit_ledger import audit_ledger
from shared.common.common import ForbiddenError
from shared.logger.logger import get_logger, metrics
from shared.privacy.ip_hmac import audit_ip_token

logger = get_logger("aether.data_exchange.reports.routes")

router = APIRouter(prefix="/v1/data-exchange/reports", tags=["Data Exchange Reports"])

# data_exchange.* grant tuples each report route requires (source:
# services/data_exchange/policy.py).  Mirrors the sibling envelope routers
# (routes_transfer.py / routes_export.py): the dotted grant is the primary
# vocabulary and ``admin`` is the legacy egress bypass — require_data_exchange
# resolves each grant *or* its legacy parity alias, and Role.ADMIN
# short-circuits via require_any_permission.
#   - create  requires the report.create grant (like export routes require a
#              create-scoped grant);
#   - list / detail require the domain read grant (metadata reads, like the
#              export list/detail routes);
#   - download is a byte GET and must never be weaker than the canonical
#              export-download gate — it requires a report grant *or* the
#              canonical egress-download grant ``data_exchange.export.download``
#              (never plain ``data_exchange.read``);
#   - delete  requires the dedicated ``data_exchange.report.delete`` grant and
#              is deliberately *not* reachable by a read-only tenant.
REPORT_CREATE_REQUIRED_GRANTS: tuple[str, ...] = ("data_exchange.report.create", "admin")
REPORT_READ_REQUIRED_GRANTS: tuple[str, ...] = ("data_exchange.read", "admin")
REPORT_DOWNLOAD_REQUIRED_GRANTS: tuple[str, ...] = (
    "data_exchange.report.create",
    "data_exchange.export.download",
    "admin",
)
REPORT_DELETE_REQUIRED_GRANTS: tuple[str, ...] = ("data_exchange.report.delete", "admin")


class _ReportListResponse(BaseModel):
    artifacts: list[dict]
    count: int


def _require_tenant(request: Request, *grants: str):
    """Resolve the authenticated tenant and require any of ``grants`` (dotted
    data_exchange grant id or its legacy parity alias, via authz)."""
    tenant = request.state.tenant
    require_data_exchange(tenant, *grants)
    return tenant


def _actor_id(tenant) -> str:
    return getattr(tenant, "user_id", None) or tenant.tenant_id


def _ip(request: Request, tenant_id: str) -> Optional[str]:
    return audit_ip_token(
        request.client.host if request.client else None, tenant_id
    )


@router.post("", summary="Request a report artifact (PDF)")
async def create_report(body: ReportSpecContract, request: Request):
    tenant = _require_tenant(request, *REPORT_CREATE_REQUIRED_GRANTS)
    if body.tenant_id != tenant.tenant_id:
        raise ForbiddenError(
            "cross-tenant report request refused — report.tenant_id must match "
            "the authenticated tenant"
        )
    requested_by = getattr(tenant, "user_id", None) or tenant.tenant_id
    result = await request_report(
        tenant.tenant_id,
        body,
        requested_by=requested_by,
        correlation_id=getattr(request.state, "request_id", None),
    )
    metrics.increment("data_exchange_report_request_http_total")
    return result


@router.get("", summary="List report artifacts", response_model=_ReportListResponse)
async def list_reports(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    status_filter: Optional[str] = Query(default=None),
):
    tenant = _require_tenant(request, *REPORT_READ_REQUIRED_GRANTS)
    return await list_report_artifacts(
        tenant.tenant_id, limit=limit, offset=offset, status=status_filter
    )


@router.get("/{report_id}", summary="Report detail (envelope + render meta)")
async def report_detail(report_id: str, request: Request):
    tenant = _require_tenant(request, *REPORT_READ_REQUIRED_GRANTS)
    return await get_report_detail(tenant.tenant_id, report_id)


@router.get("/{report_id}/download", summary="Download report PDF bytes")
async def download_report_bytes(report_id: str, request: Request):
    tenant = _require_tenant(request, *REPORT_DOWNLOAD_REQUIRED_GRANTS)
    # Re-check authorization at download time (permission may have changed since
    # generation); the service refuses deleted/expired/failed/not-ready reports.
    meta, content = await download_report(tenant.tenant_id, report_id)

    try:
        await audit_ledger.record(
            actor_id=_actor_id(tenant),
            actor_type="tenant_user",
            event_type="report.download",
            resource_type="report_artifact",
            action="download",
            outcome="allowed",
            tenant_id=tenant.tenant_id,
            resource_id=report_id,
            ip_address=_ip(request, tenant.tenant_id),
            metadata={
                "artifact_id": meta["artifact_id"],
                "size_bytes": meta["size_bytes"],
                "sha256": meta["sha256"],
            },
        )
    except Exception as exc:  # noqa: BLE001 — audit must never block bytes
        logger.debug(f"report download audit record skipped: {exc}")

    metrics.increment("data_exchange_report_downloaded_total")
    try:
        await emit_report_downloaded(tenant.tenant_id, meta)
    except Exception as exc:  # noqa: BLE001 — event must never block served bytes
        logger.debug(f"report download event publish skipped: {exc}")
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{meta["filename"]}"',
            "X-Checksum-SHA256": meta["sha256"],
        },
    )


@router.delete("/{report_id}", summary="Revoke/delete a report artifact")
async def delete_report_by_id(report_id: str, request: Request):
    tenant = _require_tenant(request, *REPORT_DELETE_REQUIRED_GRANTS)
    result = await delete_report(tenant.tenant_id, report_id)
    metrics.increment("data_exchange_report_deleted_total")
    return result
