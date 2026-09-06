"""Data Exchange Plane — export control envelope + egress history (M4).

Sub-router under ``/v1/data-exchange/exports``.  Every route is a *thin proxy /
read adapter* over the canonical export engine (``services/export/service.py``
``request_export`` + the canonical ``EXPORTERS`` registry) and the M1
``data_artifacts`` metadata repository — never a second export engine.

Route map (frozen in ``docs/plans/data-exchange-api.md`` M4):

- ``GET    /v1/data-exchange/exports/types``   → ``{export_types, formats}``
- ``POST   /v1/data-exchange/exports``         → ``{export_id, artifact_id,
  job_id, status:"generating"}`` (enqueues the canonical ``export.generate``
  job; records the egress ``data_artifacts`` envelope row)
- ``GET    /v1/data-exchange/exports``         → ``{artifacts:[...], count}``
  (list egress artifacts — the M6 export-history feed)
- ``GET    /v1/data-exchange/exports/{export_id}`` → envelope + manifest +
  canonical exporter meta
- ``DELETE /v1/data-exchange/exports/{export_id}`` → ``{deleted:true}``

All routes are tenant-scoped: the envelope's ``tenant_id`` must match the
authenticated tenant and every repository read is rooted at the tenant id.
"""

from __future__ import annotations

import hashlib
from typing import Any, Callable, Optional

from fastapi import APIRouter, Query, Request

from repositories.data_artifacts import (
    DataArtifactRepository,
    get_data_artifact_repository,
)
from services.data_exchange.authz import require_data_exchange
from services.data_exchange.contracts import (
    DATA_EXCHANGE_EGRESS_FORMATS,
    ExportSpecContract,
)
from services.data_exchange.exporters import (
    EGRESS_CONTENT_TYPES,
    EXPORT_TYPE_DATA_EXCHANGE,
    EXPORT_TYPE_DATA_EXCHANGE_PARQUET,
)
from services.data_exchange.storage import object_key_for
from shared.common.common import BadRequestError, ForbiddenError, NotFoundError
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.data_exchange.export.routes")

router = APIRouter(prefix="/v1/data-exchange/exports", tags=["Data Exchange — Exports"])

#: Egress data_artifacts rows this surface creates.
EGRESS_ARTIFACT_TYPE = "export"

#: Default content classification for day-one exports (elevated classification
#: enforcement lands with the M3/M4 policy wiring).
DEFAULT_EXPORT_CLASSIFICATION = "none"

# Generating egress rows are created before bytes exist (generation is the
# durable job).  The repository records a checksum at row creation; the M4
# egress-completion bridge (``egress.py``, invoked best-effort from the
# canonical ``export.generate`` handler) flips the row to ``available`` with the
# real ObjectStore bytes + sha/size.  Until that bridge runs a generating row
# carries the digest of the empty payload as an explicit "not materialized"
# sentinel.
_EMPTY_PAYLOAD_SHA256 = hashlib.sha256(b"").hexdigest()


# ── row shaping ─────────────────────────────────────────────────────────────


def artifact_payload(row: dict) -> dict:
    """Shape a ``data_artifacts`` repo row as a DataArtifactContract payload.

    ``updated_at`` is repository bookkeeping (not part of the contract); it is
    dropped.  ``canonical_id`` is kept as an additive envelope extension so the
    egress row can link to the canonical engine artifact it maps onto.
    """
    payload = {k: v for k, v in dict(row).items() if k != "updated_at"}
    return payload


# ── auth / tenant helpers ───────────────────────────────────────────────────


def _tenant(request: Request, *grants: str) -> Any:
    """Resolve the authenticated tenant and require one of ``grants`` (or admin)."""
    tenant = request.state.tenant
    if grants:
        require_data_exchange(tenant, *grants, "admin")
    else:
        # Read verbs still require a data-exchange grant (not just any tenant).
        require_data_exchange(tenant, "data_exchange.read", "admin")
    return tenant


def _envelope_tenant_allowed(tenant: Any, spec: ExportSpecContract) -> None:
    """Re-assert tenant scoping at the envelope edge (never trust the body)."""
    if spec.tenant_id and spec.tenant_id != tenant.tenant_id:
        raise ForbiddenError(
            "export spec tenant_id does not match the authenticated tenant"
        )


def _parquet_enabled(override: Optional[bool]) -> bool:
    if override is not None:
        return override
    from config.settings import settings  # lazy — avoids import cycles

    return bool(getattr(settings.data_exchange, "parquet_enabled", False))


def _canonical_export_types() -> tuple[dict[str, Any], tuple[str, ...]]:
    """Read-only view of the canonical exporter registry (lazy import).

    Returns ``(EXPORTERS, SUPPORTED_FORMATS)`` from ``services/export/service.py``
    without importing the canonical engine until a route actually needs it.
    """
    from services.export.service import EXPORTERS, SUPPORTED_FORMATS

    return EXPORTERS, SUPPORTED_FORMATS


# ── canonical job enqueue seam ──────────────────────────────────────────────


async def _enqueue_export_job(
    tenant_id: str,
    *,
    export_type: str,
    params: dict,
    requested_by: Optional[str],
    correlation_id: Optional[str],
) -> dict:
    """Enqueue the canonical ``export.generate`` job for the envelope.

    Every format — including ``parquet``, since the M4 coordinator delta taught
    the canonical ``serialize_rows`` / ``SUPPORTED_FORMATS`` surface parquet —
    proxies the canonical ``request_export`` seam unchanged, so the envelope is
    always one thin translation onto the canonical engine.
    """
    from services.export.service import request_export

    return await request_export(
        tenant_id,
        export_type=export_type,
        params=params,
        requested_by=requested_by,
        correlation_id=correlation_id,
    )


# ── core logic (DB-free testable, mirrors M1 job-function style) ────────────


def _canonical_params_from_spec(spec: ExportSpecContract) -> dict:
    """Translate the envelope spec onto canonical exporter params."""
    return {
        "export_id": spec.export_id,
        "resource": spec.resource,
        "scope": dict(spec.scope or {}),
        "fields": list(spec.fields) if spec.fields else None,
        "include_relationships": spec.include_relationships,
        "include_identifiers": spec.include_identifiers,
        "include_provenance": spec.include_provenance,
        "include_raw_events": spec.include_raw_events,
        "filters": dict(spec.filters or {}),
        "temporal": dict(spec.temporal or {}),
        "display_timezone": spec.display_timezone,
        "destination": dict(spec.destination or {}),
        "compression": spec.compression,
        "format": spec.format,
    }


def _resolve_export_type(resource: str, fmt: str) -> str:
    """Map an envelope spec to a canonical ``export.generate`` export_type.

    Parquet requests always target the parquet envelope export_type so the
    intent is explicit.  Otherwise a resource that is itself a registered
    canonical domain exporter is proxied directly; anything else targets the
    generic data-exchange envelope exporter.
    """
    if fmt == "parquet":
        return EXPORT_TYPE_DATA_EXCHANGE_PARQUET
    exporters, _ = _canonical_export_types()
    if resource and resource in exporters and resource not in {
        EXPORT_TYPE_DATA_EXCHANGE,
        EXPORT_TYPE_DATA_EXCHANGE_PARQUET,
    }:
        return resource
    return EXPORT_TYPE_DATA_EXCHANGE


async def create_export(
    tenant_id: str,
    spec: ExportSpecContract,
    *,
    artifact_repo: Optional[DataArtifactRepository] = None,
    enqueue: Optional[Callable[..., Any]] = None,
    parquet_enabled: Optional[bool] = None,
    created_by: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> dict:
    """Create an egress export: enqueue the canonical job + record the envelope row.

    DB-free contract (mirrors M1): pass an in-memory-backed artifact repo and an
    injected ``enqueue`` when testing without the durable-job runtime.

    Returns ``{export_id, artifact_id, job_id, status:"generating"}``.
    """
    if not tenant_id:
        raise BadRequestError("tenant_id is required")
    if not spec.export_id:
        raise BadRequestError("export_id is required")
    fmt = str(spec.format or "json").strip().lower()
    if fmt not in DATA_EXCHANGE_EGRESS_FORMATS:
        raise BadRequestError(
            f"Unsupported export format {spec.format!r} — expected one of "
            f"{', '.join(DATA_EXCHANGE_EGRESS_FORMATS)}"
        )
    if fmt == "parquet" and not _parquet_enabled(parquet_enabled):
        raise BadRequestError(
            "parquet egress is disabled — set DATA_EXCHANGE_PARQUET_ENABLED=true"
        )

    repo = artifact_repo if artifact_repo is not None else get_data_artifact_repository()
    # ``artifact_id`` is the client-supplied export_id.  These ids are unique
    # only WITHIN a tenant — the ``data_artifacts`` PK is (tenant_id,
    # artifact_id), so two tenants may legally reuse the same export_id
    # (finding #14); the duplicate check below is tenant-scoped accordingly.
    artifact_id = spec.export_id

    # Reject duplicate envelope ids (create-before-read; opaque id uniqueness,
    # scoped to this tenant by the composite PK).
    try:
        existing = await repo.get(tenant_id, artifact_id)
    except NotFoundError:
        existing = None
    if existing is not None:
        raise BadRequestError(
            f"export_id {artifact_id!r} already exists for this tenant"
        )

    # Tenant-scoped object key (validates the export_id as a safe key segment).
    object_key = object_key_for(tenant_id, direction="egress", artifact_id=artifact_id)

    params = _canonical_params_from_spec(spec)
    export_type = _resolve_export_type(spec.resource, fmt)

    # Enqueue first: a failed enqueue never leaves an orphan envelope row.
    enqueue_fn = enqueue if enqueue is not None else _enqueue_export_job
    job = await enqueue_fn(
        tenant_id,
        export_type=export_type,
        params=params,
        requested_by=spec.requested_by or created_by,
        correlation_id=correlation_id,
    )
    job_id = job.get("job_id") or job.get("id")

    row = await repo.create_artifact(
        artifact_id,
        tenant_id,
        direction="egress",
        artifact_type=EGRESS_ARTIFACT_TYPE,
        object_key=object_key,
        filename=f"{spec.resource or 'export'}-{artifact_id}.{fmt}",
        format=fmt,
        content_type=EGRESS_CONTENT_TYPES.get(fmt, "application/octet-stream"),
        size_bytes=0,
        sha256=_EMPTY_PAYLOAD_SHA256,
        classification=DEFAULT_EXPORT_CLASSIFICATION,
        status="generating",
        canonical_id=None,
        job_id=job_id,
        source_or_destination={
            "export": True,
            "export_id": artifact_id,
            "resource": spec.resource,
            "export_type": export_type,
            "destination": dict(spec.destination or {}),
            "materialized": False,
        },
        schema_version="1.0",
        created_by=spec.requested_by or created_by,
        correlation_id=correlation_id,
    )
    metrics.increment(
        "data_exchange_export_requested_total",
        labels={"export_type": export_type, "format": fmt},
    )
    logger.info(
        "data_exchange export requested tenant=%s export=%s job=%s format=%s",
        tenant_id,
        artifact_id,
        job_id,
        fmt,
    )
    return {
        "export_id": spec.export_id,
        "artifact_id": row["artifact_id"],
        "job_id": job_id,
        "status": "generating",
    }


async def list_export_artifacts(
    tenant_id: str,
    *,
    limit: int = 50,
    offset: int = 0,
    status_filter: Optional[str] = None,
    artifact_repo: Optional[DataArtifactRepository] = None,
) -> dict:
    """List this tenant's egress export artifacts (newest-first)."""
    repo = artifact_repo if artifact_repo is not None else get_data_artifact_repository()
    rows = await repo.list_for_tenant(
        tenant_id,
        limit=limit,
        offset=offset,
        direction="egress",
        artifact_type=EGRESS_ARTIFACT_TYPE,
        status=status_filter,
    )
    return {"artifacts": [artifact_payload(r) for r in rows], "count": len(rows)}


async def get_export_artifact(
    tenant_id: str,
    export_id: str,
    *,
    artifact_repo: Optional[DataArtifactRepository] = None,
) -> dict:
    """Envelope detail for one export: row + manifest + canonical exporter meta."""
    repo = artifact_repo if artifact_repo is not None else get_data_artifact_repository()
    row = await repo.get(tenant_id, export_id)
    source = row.get("source_or_destination") or {}
    export_type = source.get("export_type") or row.get("artifact_type")
    exporters, _ = _canonical_export_types()
    job_id = row.get("job_id")
    return {
        **artifact_payload(row),
        "canonical": {
            "export_type": export_type,
            "registered": export_type in exporters,
            "resource": source.get("resource"),
            "job_id": job_id,
            "status_url": f"/v1/jobs/{job_id}" if job_id else None,
        },
    }


async def delete_export_artifact(
    tenant_id: str,
    export_id: str,
    *,
    artifact_repo: Optional[DataArtifactRepository] = None,
) -> dict:
    """Revoke/delete an export: tombstone the envelope row (status ``deleted``)."""
    repo = artifact_repo if artifact_repo is not None else get_data_artifact_repository()
    meta = await repo.mark_deleted(tenant_id, export_id)
    metrics.increment("data_exchange_export_deleted_total")
    return {"deleted": True, "artifact_id": export_id, "tombstone_sha256": meta.get("sha256")}


# ── routes ──────────────────────────────────────────────────────────────────


@router.get("/types")
async def list_export_types(request: Request):
    """Mirror of canonical ``/v1/exports/types`` incl. the M4 envelope exporters."""
    tenant = _tenant(request, "data_exchange.read")
    exporters, canonical_formats = _canonical_export_types()
    formats: list[str] = []
    for fmt in canonical_formats:  # canonical json/csv/ndjson
        if fmt not in formats:
            formats.append(fmt)
    for fmt in ("parquet",):  # M4 addition, availability-flag gated
        if fmt not in formats and _parquet_enabled(None):
            formats.append(fmt)
    return {"export_types": sorted(exporters), "formats": formats}


@router.post("")
async def create_export_route(body: ExportSpecContract, request: Request):
    """Create an export: enqueue the canonical job + record the egress envelope."""
    tenant = _tenant(request, "data_exchange.export.create")
    _envelope_tenant_allowed(tenant, body)
    return await create_export(
        tenant.tenant_id,
        body,
        created_by=getattr(tenant, "user_id", None) or tenant.tenant_id,
        correlation_id=getattr(request.state, "request_id", None),
    )


@router.get("")
async def list_export_artifacts_route(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    status_filter: Optional[str] = Query(default=None, alias="status_filter"),
):
    """List egress export artifacts — the M6 export-history feed."""
    tenant = _tenant(request, "data_exchange.read")
    return await list_export_artifacts(
        tenant.tenant_id,
        limit=limit,
        offset=offset,
        status_filter=status_filter,
    )


@router.get("/{export_id}")
async def get_export_artifact_route(export_id: str, request: Request):
    """Export envelope detail + manifest + canonical exporter meta."""
    tenant = _tenant(request, "data_exchange.read")
    return await get_export_artifact(tenant.tenant_id, export_id)


@router.delete("/{export_id}")
async def delete_export_artifact_route(export_id: str, request: Request):
    """Revoke/delete an export (canonical delete semantics → envelope tombstone)."""
    tenant = _tenant(request, "data_exchange.export.create", "data_exchange.settings.manage")
    return await delete_export_artifact(tenant.tenant_id, export_id)
