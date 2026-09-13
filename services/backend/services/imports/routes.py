"""
Aether Service — Import Engine Routes (/v1/imports)

Tenant-facing surface for the ingest → analyze → map → validate lifecycle. Every
mutating route is tenant-scoped and permission-gated; the reads return only the
calling tenant's imports. Uploads are size-capped mid-stream (the archive/zip
class is refused outright) so a hostile file never buffers to the byte ceiling.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from services.imports import service as svc
from services.imports.contracts import FieldMapping
from shared.common.common import BadRequestError
from shared.logger.logger import get_logger

logger = get_logger("aether.imports.routes")

router = APIRouter(prefix="/v1/imports", tags=["Imports"])


def _tenant(request: Request, permission: str = "read"):
    tenant = request.state.tenant
    tenant.require_permission(permission)
    return tenant


def _correlation_id(request: Request):
    return getattr(request.state, "request_id", None)


async def _read_capped(request: Request, max_bytes: int) -> bytes:
    """Read the request body, aborting as soon as it exceeds ``max_bytes`` —
    a hostile upload never buffers past the cap."""
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_bytes:
            raise BadRequestError(
                f"upload exceeds the {max_bytes} byte cap"
            )
        chunks.append(chunk)
    return b"".join(chunks)


# ── request bodies ───────────────────────────────────────────────────────────


class MappingBody(BaseModel):
    fields: list[FieldMapping] = Field(default_factory=list)


class TemplateBody(BaseModel):
    name: str
    fields: list[FieldMapping] = Field(default_factory=list)
    column_names: list[str] = Field(default_factory=list)


class ApplyTemplateBody(BaseModel):
    template_id: str


class RollbackBody(BaseModel):
    commit_id: Optional[str] = None
    reason: str = "operator rollback"


# ── templates (declared before /{import_id} so the literal wins) ─────────────


@router.get("/templates")
async def list_templates(request: Request):
    tenant = _tenant(request, "read")
    templates = await svc.list_templates(tenant.tenant_id)
    return {"templates": templates, "count": len(templates)}


@router.post("/templates")
async def create_template(body: TemplateBody, request: Request):
    tenant = _tenant(request, "write")
    return await svc.create_template(
        tenant.tenant_id,
        name=body.name,
        fields=[f.model_dump(mode="json") for f in body.fields],
        column_names=body.column_names,
    )


@router.delete("/templates/{template_id}")
async def delete_template(template_id: str, request: Request):
    tenant = _tenant(request, "write")
    deleted = await svc.delete_template(tenant.tenant_id, template_id)
    return {"deleted": deleted, "template_id": template_id}


# ── sessions ─────────────────────────────────────────────────────────────────


@router.post("")
async def create_import(request: Request):
    tenant = _tenant(request, "write")
    return await svc.create_import(
        tenant.tenant_id, created_by=getattr(tenant, "user_id", None)
    )


@router.get("")
async def list_imports(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    tenant = _tenant(request, "read")
    sessions = await svc.list_imports(tenant.tenant_id, limit=limit, offset=offset)
    return {"imports": sessions, "count": len(sessions)}


@router.get("/{import_id}")
async def get_import(import_id: str, request: Request):
    tenant = _tenant(request, "read")
    return await svc.get_import(tenant.tenant_id, import_id)


@router.post("/{import_id}/files")
async def upload_file(
    import_id: str,
    request: Request,
    filename: str = Query(..., min_length=1),
):
    tenant = _tenant(request, "write")
    max_bytes = svc.max_upload_bytes_for(getattr(tenant, "plan_tier", None))
    content = await _read_capped(request, max_bytes)
    content_type = request.headers.get("content-type", "application/octet-stream")
    return await svc.store_file(
        tenant.tenant_id,
        import_id,
        filename=filename,
        content=content,
        content_type=content_type,
        max_bytes=max_bytes,
    )


@router.post("/{import_id}/analyze")
async def analyze_import(import_id: str, request: Request):
    tenant = _tenant(request, "write")
    return await svc.analyze_import(tenant.tenant_id, import_id)


@router.put("/{import_id}/mapping")
async def set_mapping(import_id: str, body: MappingBody, request: Request):
    tenant = _tenant(request, "write")
    return await svc.set_mapping(
        tenant.tenant_id, import_id, [f.model_dump(mode="json") for f in body.fields]
    )


@router.get("/{import_id}/templates/suggest")
async def suggest_templates(import_id: str, request: Request):
    tenant = _tenant(request, "read")
    return await svc.suggest_templates(tenant.tenant_id, import_id)


@router.post("/{import_id}/apply-template")
async def apply_template(import_id: str, body: ApplyTemplateBody, request: Request):
    tenant = _tenant(request, "write")
    return await svc.apply_template(tenant.tenant_id, import_id, body.template_id)


@router.post("/{import_id}/validate")
async def validate_import(import_id: str, request: Request):
    tenant = _tenant(request, "write")
    return await svc.validate_import(tenant.tenant_id, import_id)


@router.post("/{import_id}/approve")
async def approve_import(import_id: str, request: Request):
    # Approval is an elevated action — governance-sensitive imports gate here.
    tenant = _tenant(request, "admin")
    return await svc.approve_import(
        tenant.tenant_id, import_id, approver=getattr(tenant, "user_id", None)
    )


@router.post("/{import_id}/cancel")
async def cancel_import(import_id: str, request: Request):
    tenant = _tenant(request, "write")
    return await svc.cancel_import(tenant.tenant_id, import_id)


# ── commit / preview / replay / rollback ─────────────────────────────────────


@router.post("/{import_id}/graph-preview")
async def graph_preview(import_id: str, request: Request):
    from services.imports.commit import graph_preview as _preview

    tenant = _tenant(request, "read")
    return await _preview(tenant.tenant_id, import_id)


@router.post("/{import_id}/commit")
async def commit_import(import_id: str, request: Request):
    """Enqueue a durable commit job (Bronze + graph). The import must be approved."""
    from services.jobs.service import get_jobs_service

    tenant = _tenant(request, "write")
    # Fail fast if not approved, rather than enqueueing a job doomed to fail.
    session = await svc.get_import(tenant.tenant_id, import_id)
    status = session["session"].get("status")
    if status != "approved":
        from shared.common.common import ConflictError

        raise ConflictError(f"import must be approved before commit (current: {status!r})")
    job = await get_jobs_service().enqueue(
        tenant.tenant_id,
        "import.commit",
        {"import_id": import_id},
        idempotency_key=f"import-commit:{import_id}",
        correlation_id=_correlation_id(request),
        requested_by=getattr(tenant, "user_id", None),
    )
    return {"import_id": import_id, "job": job}


@router.post("/{import_id}/replay")
async def replay_import(import_id: str, request: Request):
    from services.jobs.service import get_jobs_service

    tenant = _tenant(request, "write")
    job = await get_jobs_service().enqueue(
        tenant.tenant_id,
        "import.replay",
        {"import_id": import_id},
        correlation_id=_correlation_id(request),
        requested_by=getattr(tenant, "user_id", None),
    )
    return {"import_id": import_id, "job": job}


@router.post("/{import_id}/rollback")
async def rollback_import(import_id: str, body: RollbackBody, request: Request):
    # Rollback is an elevated, destructive-to-graph action → admin.
    from services.imports.commit import rollback_import as _rollback

    tenant = _tenant(request, "admin")
    return await _rollback(
        tenant.tenant_id, import_id, commit_id=body.commit_id, reason=body.reason
    )


@router.get("/{import_id}/commits")
async def list_commits(import_id: str, request: Request):
    tenant = _tenant(request, "read")
    from repositories.imports_repo import get_imports_repository

    repo = get_imports_repository()
    await repo.get_session(tenant.tenant_id, import_id)  # tenant guard
    commits = await repo.list_commits(tenant.tenant_id, import_id)
    return {"commits": commits, "count": len(commits)}
