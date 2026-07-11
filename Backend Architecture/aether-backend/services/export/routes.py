"""
Aether Service — Export Routes (/v1/exports)

Tenant-facing artifact export surface. POST enqueues a durable export job on
the jobs platform; the artifact becomes downloadable only after the job
succeeds with a verified checksum. Downloads re-check authorization through
the export governance policy engine and are audited; expired/deleted
artifacts refuse with a canonical error rather than an empty file.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from repositories.artifacts import get_artifact_repository
from services.export.service import (
    EXPORTERS,
    SUPPORTED_FORMATS,
    _emit,
    request_export,
)
from services.security.export_governance import audit_export_governance
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.export.routes")

router = APIRouter(prefix="/v1/exports", tags=["Exports"])


class ExportRequestBody(BaseModel):
    export_type: str = Field(..., description=f"One of the registered exporters")
    params: dict = Field(default_factory=dict)
    format: str = Field(default="json", description=f"One of {list(SUPPORTED_FORMATS)}")


def _tenant(request: Request):
    tenant = request.state.tenant
    tenant.require_permission("admin")
    return tenant


@router.get("/types")
async def list_export_types(request: Request):
    _tenant(request)
    return {"export_types": sorted(EXPORTERS), "formats": list(SUPPORTED_FORMATS)}


@router.post("")
async def create_export(body: ExportRequestBody, request: Request):
    tenant = _tenant(request)
    # Governance up front: permission, cross-tenant block, sensitivity flag.
    await audit_export_governance.authorize_create(
        actor_id=getattr(tenant, "user_id", None) or tenant.tenant_id,
        actor_type="tenant_user",
        tenant_id=tenant.tenant_id,
        export_type=body.export_type,
        has_export_permission=tenant.has_permission("export") or tenant.has_permission("admin"),
        target_tenant=tenant.tenant_id,
        manifest={"params": body.params, "format": body.format},
        ip_address=request.client.host if request.client else None,
    )
    params = {**body.params, "format": body.format}
    return await request_export(
        tenant.tenant_id,
        export_type=body.export_type,
        params=params,
        requested_by=getattr(tenant, "user_id", None),
        correlation_id=getattr(request.state, "request_id", None),
    )


@router.get("")
async def list_artifacts(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    tenant = _tenant(request)
    artifacts = await get_artifact_repository().list_for_tenant(
        tenant.tenant_id, limit=limit, offset=offset
    )
    return {"artifacts": artifacts, "count": len(artifacts)}


@router.get("/{artifact_id}")
async def get_artifact_meta(artifact_id: str, request: Request):
    tenant = _tenant(request)
    return await get_artifact_repository().get_meta(tenant.tenant_id, artifact_id)


@router.get("/{artifact_id}/download")
async def download_artifact(artifact_id: str, request: Request):
    tenant = _tenant(request)
    repo = get_artifact_repository()
    meta = await repo.get_meta(tenant.tenant_id, artifact_id)
    # Re-check authorization at download time (permission may have changed
    # since generation) and refuse expired artifacts; the governance call
    # also writes the download audit record.
    await audit_export_governance.authorize_download(
        actor_id=getattr(tenant, "user_id", None) or tenant.tenant_id,
        actor_type="tenant_user",
        tenant_id=tenant.tenant_id,
        export_id=artifact_id,
        has_export_permission=tenant.has_permission("export") or tenant.has_permission("admin"),
        expires_at=meta.get("expires_at"),
        ip_address=request.client.host if request.client else None,
    )
    meta, content = await repo.get_content(tenant.tenant_id, artifact_id)
    metrics.increment(
        "export_downloaded_total", labels={"export_type": meta.get("export_type", "unknown")}
    )
    await _emit(
        "EXPORT_DOWNLOADED",
        tenant.tenant_id,
        {"artifact_id": artifact_id, "export_type": meta.get("export_type")},
    )
    return Response(
        content=content,
        media_type=meta.get("content_type", "application/octet-stream"),
        headers={
            "Content-Disposition": f'attachment; filename="{meta.get("filename", artifact_id)}"',
            "X-Checksum-SHA256": meta.get("sha256", ""),
        },
    )


@router.delete("/{artifact_id}")
async def delete_artifact(artifact_id: str, request: Request):
    tenant = _tenant(request)
    meta = await get_artifact_repository().soft_delete(tenant.tenant_id, artifact_id)
    metrics.increment("export_artifact_deleted_total")
    return {"deleted": True, "artifact_id": artifact_id, "tombstone_sha256": meta.get("sha256")}
