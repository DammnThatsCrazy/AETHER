"""Data Exchange Plane — import control envelope (M3).

``/v1/data-exchange/imports*`` proxies the canonical ``/v1/imports`` engine
(import FSM + ``import.commit`` / ``import.replay`` durable jobs +
``rollback_by_source_tag``) and registers an envelope ``data_artifacts`` row
per import source.  The Data Exchange Plane is a *control envelope* — these
routes never run a second import state machine.  Every mutating verb translates
onto a canonical service function (``services/imports/service.py`` /
``services/imports/commit.py`` / the durable-jobs platform); reads render
canonical state in the Data Exchange vocabulary
(``services/data_exchange/contracts.py`` ``DataArtifactStatus``).

Surface (freeze ``docs/plans/data-exchange-api.md`` M3, flag
``DATA_EXCHANGE_ENABLED``):

- ``POST   /imports``                       create canonical session + envelope artifact
- ``GET    /imports``                       envelope import-history feed (M6 source)
- ``GET    /imports/{import_id}``           envelope detail (source + artifact + FSM)
- ``POST   /imports/{import_id}/files``     capped upload proxying the engine
- ``POST   /imports/{import_id}/analyze``   analyze proxy
- ``PUT    /imports/{import_id}/mapping``   envelope mapping -> canonical mapping
- ``POST   /imports/{import_id}/preview/identity``  net-new identity preview adapter
- ``POST   /imports/{import_id}/preview/graph``     graph-preview adapter
- ``POST   /imports/{import_id}/commit``    enqueue ``import.commit``
- ``POST   /imports/{import_id}/rollback``  rollback proxy

Identity: the envelope ``import_id`` (the caller's opaque source-session id,
from ``ImportSourceContract.import_id``) is the address every envelope route
uses; the canonical engine's session id is preserved as ``canonical_id`` on the
``data_artifacts`` row.  Envelope sub-routes translate
``import_id -> canonical_id`` through the envelope marker row before calling the
canonical service.  All handlers resolve the tenant from
``request.state.tenant`` and hold the ``data_exchange.*`` grant (RBAC domain
registered by the coordinator at M3 integration; grant names are the
``services/data_exchange/policy.py`` list).
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from repositories.data_artifacts import (
    get_data_artifact_repository,
)
from repositories.imports_repo import get_imports_repository
from services.data_exchange.contracts import (
    DATA_ARTIFACT_STATUSES,
    DATA_EXCHANGE_DIRECTIONS,
    DATA_EXCHANGE_INGRESS_FORMATS,
    DATA_EXCHANGE_SOURCE_TYPES,
    ImportMappingContract,
    ImportSourceContract,
)
from services.data_exchange.authz import require_data_exchange
from services.data_exchange.identity_preview import IdentityPreviewBody
from services.data_exchange.storage import object_key_for
from shared.common.common import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)

router = APIRouter(prefix="/v1/data-exchange/imports", tags=["Data Exchange Imports"])

# Canonical session statuses that are absorbing for the underlying engine.
_CANONICAL_TERMINAL = frozenset(
    {"committed", "partially_committed", "failed", "cancelled", "rolled_back"}
)

# Canonical import-session status -> envelope artifact status vocabulary.
_CANONICAL_TO_ENVELOPE_STATUS: dict[str, str] = {
    "created": "created",
    "files_pending": "created",
    "uploaded": "uploaded",
    "analyzing": "analyzing",
    "analyzed": "ready",
    "mapping": "ready",
    "mapped": "ready",
    "validating": "processing",
    "validated": "ready",
    "review_required": "ready",
    "approved": "processing",
    "committing": "processing",
    "committed": "committed",
    "partially_committed": "partially_committed",
    "failed": "failed",
    "cancelled": "deleted",
    "rolled_back": "revoked",
}

_FORMAT_CONTENT_TYPES: dict[str, str] = {
    "csv": "text/csv",
    "json": "application/json",
    "jsonl": "application/jsonl",
    "parquet": "application/vnd.apache.parquet",
}

_ENVELOPE_MARKER_KEY = "envelope"
_ENVELOPE_MARKER_VALUE = "import_source"


# ── tenant/permission gate ──────────────────────────────────────────────────


def _tenant(request: Request, permission: str):
    tenant = request.state.tenant
    require_data_exchange(tenant, permission)
    return tenant


def _request_id(request: Request) -> Optional[str]:
    return getattr(request.state, "request_id", None)


def _user(request: Request) -> Optional[str]:
    tenant = request.state.tenant
    return getattr(tenant, "user_id", None)


# ── envelope ↔ canonical id helpers ─────────────────────────────────────────


async def _artifact_repo():
    return get_data_artifact_repository()


async def _envelope_marker_rows(tenant_id: str) -> list[dict]:
    """The tenant's envelope *source-session marker* artifacts (not file rows)."""
    repo = await _artifact_repo()
    rows = await repo.list_for_tenant(
        tenant_id,
        limit=10000,
        direction="ingress",
        artifact_type="import_source",
    )
    return [
        r
        for r in rows
        if (r.get("source_or_destination") or {}).get(_ENVELOPE_MARKER_KEY)
        == _ENVELOPE_MARKER_VALUE
    ]


async def _find_envelope_marker(tenant_id: str, envelope_import_id: str) -> Optional[dict]:
    """Locate the envelope marker whose ``import_id`` matches (tenant-scoped)."""
    for row in await _envelope_marker_rows(tenant_id):
        src = row.get("source_or_destination") or {}
        if src.get("import_id") == envelope_import_id:
            return row
    return None


async def _resolve_canonical(tenant_id: str, envelope_import_id: str) -> tuple[str, dict]:
    """Envelope import id -> (canonical session id, marker row)."""
    marker = await _find_envelope_marker(tenant_id, envelope_import_id)
    if marker is None or not marker.get("canonical_id"):
        raise NotFoundError("data exchange import")
    return marker["canonical_id"], marker


async def _marker_status(repo: Any, tenant_id: str, artifact_id: str, status: str) -> dict:
    """Update an envelope marker artifact to an envelope vocabulary status."""
    if status not in DATA_ARTIFACT_STATUSES:
        raise BadRequestError(
            f"invalid data artifact status {status!r} — expected one of "
            f"{', '.join(DATA_ARTIFACT_STATUSES)}"
        )
    return await repo.update_status(tenant_id, artifact_id, status)


def _envelope_status_from_canonical(canonical_status: Optional[str]) -> str:
    status = canonical_status or "created"
    return _CANONICAL_TO_ENVELOPE_STATUS.get(status, "created")


def _effective_envelope_status(
    marker_status: Optional[str], canonical_status: Optional[str]
) -> str:
    """Prefer the canonical FSM for terminal/authoritative outcomes, else the
    envelope marker's coarse progress status."""
    if canonical_status in _CANONICAL_TERMINAL:
        return _envelope_status_from_canonical(canonical_status)
    return marker_status or _envelope_status_from_canonical(canonical_status)


def _content_type_for(fmt: str) -> str:
    return _FORMAT_CONTENT_TYPES.get(fmt, "application/octet-stream")


def _format_extension(fmt: str) -> str:
    return {"jsonl": "jsonl"}.get(fmt, fmt)


def _envelope_sha256_empty() -> str:
    return hashlib.sha256(b"").hexdigest()


async def _session_exists(tenant_id: str, canonical_id: str) -> bool:
    try:
        await get_imports_repository().get_session(tenant_id, canonical_id)
        return True
    except NotFoundError:
        return False


# ── request bodies ──────────────────────────────────────────────────────────


class RollbackBody(BaseModel):
    commit_id: Optional[str] = None
    reason: str = "operator rollback"


class MappingVersionBody(BaseModel):
    mapping_version: Optional[int] = Field(default=None, ge=1)


def _import_service():
    from services.imports import service as svc

    return svc


# ── POST /imports — create envelope import ──────────────────────────────────


@router.post("")
async def create_import(request: Request, body: Optional[ImportSourceContract] = None):
    """Create a canonical import session and register the envelope artifact.

    ``body`` is read from the JSON payload when present; a body-less call is
    tolerated so the envelope can be exercised before M6 (defaults to a
    ``file`` source).  The canonical session id is preserved as ``canonical_id``
    on the envelope marker row; the caller's ``import_id`` is the envelope
    address for every subsequent sub-route.
    """
    tenant = _tenant(request, "data_exchange.import.create")

    if body is None:
        now = datetime.now(timezone.utc)
        body = ImportSourceContract(
            import_id=f"de_imp_{uuid.uuid4().hex}",
            tenant_id=tenant.tenant_id,
            source_type="file",
            artifact_id=f"de_art_{uuid.uuid4().hex}",
            format="csv",
            ownership="unknown",
            terms_status="accepted",
            provenance={
                "created_at": now.isoformat(),
                "created_via": "data_exchange_envelope",
            },
        )
    if body.tenant_id != tenant.tenant_id:
        raise ForbiddenError(
            f"tenant_id {body.tenant_id!r} does not match the authenticated tenant"
        )
    if body.source_type not in DATA_EXCHANGE_SOURCE_TYPES:
        raise BadRequestError(f"unsupported source_type {body.source_type!r}")
    if body.format not in DATA_EXCHANGE_INGRESS_FORMATS:
        raise BadRequestError(f"unsupported ingress format {body.format!r}")

    # A caller-supplied artifact_id must not already be registered for this
    # tenant as an import source (each import is a distinct source artifact).
    repo = await _artifact_repo()
    if await _find_envelope_marker(tenant.tenant_id, body.import_id) is not None:
        raise ConflictError(
            f"data exchange import {body.import_id!r} already exists for this tenant"
        )
    try:
        await repo.get(tenant.tenant_id, body.artifact_id)
        raise ConflictError(
            f"artifact {body.artifact_id!r} is already registered for this tenant"
        )
    except NotFoundError:
        pass  # available — safe to register

    svc = _import_service()
    session = await svc.create_import(
        tenant.tenant_id, created_by=getattr(tenant, "user_id", None)
    )
    canonical_id = session["id"]

    try:
        row = await repo.create_artifact(
            body.artifact_id,
            tenant.tenant_id,
            direction="ingress",
            artifact_type="import_source",
            object_key=object_key_for(
                tenant.tenant_id, direction="ingress", artifact_id=body.artifact_id
            ),
            filename=f"{body.import_id}.{_format_extension(body.format)}",
            format=body.format,
            content_type=_content_type_for(body.format),
            size_bytes=0,
            sha256=_envelope_sha256_empty(),
            classification="none",
            status="created",
            canonical_id=canonical_id,
            schema_version=body.schema_version,
            created_by=getattr(tenant, "user_id", None),
            correlation_id=_request_id(request),
            source_or_destination={
                _ENVELOPE_MARKER_KEY: _ENVELOPE_MARKER_VALUE,
                "import_id": body.import_id,
                "source_type": body.source_type,
                "artifact_id": body.artifact_id,
                "declared_timezone": body.declared_timezone,
                "declared_currency": body.declared_currency,
                "ownership": body.ownership,
                "terms_status": body.terms_status,
                "provenance": body.provenance,
            },
        )
    except Exception:
        # Leave no dangling canonical session when the envelope row cannot be
        # registered.  Best-effort: cancel is FSM-legal from ``created``.
        try:
            await svc.cancel_import(tenant.tenant_id, canonical_id)
        except Exception:
            pass
        raise

    return {
        "import_id": body.import_id,
        "artifact_id": row["artifact_id"],
        "status": "created",
        "canonical_id": canonical_id,
    }


# ── GET /imports — envelope import-history feed ─────────────────────────────


def _envelope_list_entry(
    canonical_session: dict, marker: Optional[dict]
) -> dict:
    canonical_id = canonical_session.get("id") or canonical_session.get("import_id")
    canonical_status = canonical_session.get("status") or "created"
    src = (marker or {}).get("source_or_destination") or {}
    fmt = None
    schema_version = None
    source_type = "file"
    if marker is not None:
        fmt = marker.get("format")
        schema_version = marker.get("schema_version")
        source_type = src.get("source_type") or "file"
    return {
        "import_id": (src.get("import_id") or canonical_id) if marker is not None else canonical_id,
        "canonical_id": canonical_id,
        "artifact_id": marker.get("artifact_id") if marker is not None else None,
        "status": _effective_envelope_status(
            marker.get("status") if marker is not None else None, canonical_status
        ),
        "source_type": source_type,
        "format": fmt,
        "schema_version": schema_version,
        "ownership": src.get("ownership") or "unknown",
        "terms_status": src.get("terms_status") or "accepted",
        "provenance": src.get("provenance") or {},
        "canonical_status": canonical_status,
        "file_count": canonical_session.get("file_count"),
        "row_count": canonical_session.get("row_count"),
        "created_at": canonical_session.get("created_at"),
        "created_by": canonical_session.get("created_by"),
    }


@router.get("")
async def list_imports(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    direction_filter: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None),
    format_filter: Optional[str] = Query(default=None),
):
    """Envelope import-history feed (M6 ``GET /imports`` source).

    Renders canonical import sessions in the Data Exchange vocabulary, joined
    with the envelope marker artifact when one exists (imports created through
    the envelope) and synthesized for canonical-only imports (legacy
    ``/v1/imports`` sessions).
    """
    tenant = _tenant(request, "data_exchange.read")
    if direction_filter is not None:
        if direction_filter not in DATA_EXCHANGE_DIRECTIONS:
            raise BadRequestError(
                f"invalid direction_filter {direction_filter!r} — expected one of "
                f"{', '.join(DATA_EXCHANGE_DIRECTIONS)}"
            )
        if direction_filter == "egress":
            return {"imports": [], "count": 0}
    if status_filter is not None and status_filter not in DATA_ARTIFACT_STATUSES:
        raise BadRequestError(
            f"invalid status_filter {status_filter!r} — expected one of "
            f"{', '.join(DATA_ARTIFACT_STATUSES)}"
        )
    if format_filter is not None and format_filter not in DATA_EXCHANGE_INGRESS_FORMATS:
        raise BadRequestError(
            f"invalid format_filter {format_filter!r} — expected one of "
            f"{', '.join(DATA_EXCHANGE_INGRESS_FORMATS)}"
        )

    svc = _import_service()
    # Fetch a window large enough to page after the envelope-side filters are
    # applied; filter-then-paginate is documented in the plan (M6 uses the
    # unfiltered default feed).
    window_limit = min(1000, max(1, offset + limit))
    sessions = await svc.list_imports(tenant.tenant_id, limit=window_limit, offset=0)
    markers_by_canonical: dict[str, dict] = {}
    for m in await _envelope_marker_rows(tenant.tenant_id):
        canonical_id = m.get("canonical_id")
        if canonical_id:
            markers_by_canonical.setdefault(canonical_id, m)

    entries: list[dict] = []
    for session in sessions:
        canonical_id = session.get("id")
        marker = markers_by_canonical.get(canonical_id)
        entry = _envelope_list_entry(session, marker)
        if status_filter is not None and entry["status"] != status_filter:
            continue
        if format_filter is not None and entry.get("format") != format_filter:
            continue
        entries.append(entry)

    paged = entries[offset : offset + limit]
    return {"imports": paged, "count": len(paged)}


# ── GET /imports/{import_id} — envelope detail ──────────────────────────────


def _source_summary_from_marker(marker: dict) -> dict:
    src = marker.get("source_or_destination") or {}
    return {
        "import_id": src.get("import_id"),
        "tenant_id": marker.get("tenant_id"),
        "source_type": src.get("source_type") or "file",
        "artifact_id": marker.get("artifact_id"),
        "format": marker.get("format"),
        "schema_version": marker.get("schema_version"),
        "declared_timezone": src.get("declared_timezone"),
        "declared_currency": src.get("declared_currency"),
        "ownership": src.get("ownership") or "unknown",
        "terms_status": src.get("terms_status") or "accepted",
        "provenance": src.get("provenance") or {},
        "created_at": marker.get("created_at"),
    }


@router.get("/{import_id}")
async def get_import(import_id: str, request: Request):
    """Envelope detail: source summary + envelope artifact + canonical FSM."""
    tenant = _tenant(request, "data_exchange.read")
    marker = await _find_envelope_marker(tenant.tenant_id, import_id)
    if marker is not None:
        envelope_id = (marker.get("source_or_destination") or {}).get("import_id") or import_id
        canonical_id = marker.get("canonical_id") or import_id
    else:
        # A canonical-only import (created via legacy /v1/imports) is addressable
        # directly by its canonical session id.
        if not await _session_exists(tenant.tenant_id, import_id):
            raise NotFoundError("data exchange import")
        envelope_id = import_id
        canonical_id = import_id
        marker = None

    svc = _import_service()
    detail = await svc.get_import(tenant.tenant_id, canonical_id)
    session = detail.get("session") or {}
    canonical_status = session.get("status") or "created"
    return {
        "import_id": envelope_id,
        "canonical_id": canonical_id,
        "status": _effective_envelope_status(
            marker.get("status") if marker is not None else None, canonical_status
        ),
        "canonical_status": canonical_status,
        "artifact": marker,
        "source": _source_summary_from_marker(marker) if marker is not None else {
            "import_id": envelope_id,
            "tenant_id": tenant.tenant_id,
            "source_type": "file",
            "artifact_id": None,
            "format": None,
        },
        "files": detail.get("files") or [],
        "schemas": detail.get("schemas") or [],
        "mapping": detail.get("mapping"),
        "validation": detail.get("validation"),
        "canonical": session,
    }


# ── POST /imports/{import_id}/files — capped upload proxy ──────────────────


async def _read_capped(request: Request, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_bytes:
            raise BadRequestError(f"upload exceeds the {max_bytes} byte cap")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/{import_id}/files")
async def upload_file(
    import_id: str,
    request: Request,
    filename: str = Query(..., min_length=1),
):
    """Capped upload proxying the canonical import engine's file seam."""
    tenant = _tenant(request, "data_exchange.import.create")
    canonical_id, marker = await _resolve_canonical(tenant.tenant_id, import_id)

    svc = _import_service()
    max_bytes = svc.max_upload_bytes_for(getattr(tenant, "plan_tier", None))
    content = await _read_capped(request, max_bytes)
    content_type = request.headers.get("content-type", "application/octet-stream")
    stored = await svc.store_file(
        tenant.tenant_id,
        canonical_id,
        filename=filename,
        content=content,
        content_type=content_type,
        max_bytes=max_bytes,
    )
    # Advance the envelope marker to the coarse uploaded state.
    await _marker_status(await _artifact_repo(), tenant.tenant_id, marker["artifact_id"], "uploaded")
    return {
        "import_id": import_id,
        "artifact_id": stored.get("id"),
        "status": "uploaded",
    }


# ── POST /imports/{import_id}/analyze — analyze proxy ───────────────────────


@router.post("/{import_id}/analyze")
async def analyze_import(import_id: str, request: Request):
    tenant = _tenant(request, "data_exchange.import.create")
    canonical_id, marker = await _resolve_canonical(tenant.tenant_id, import_id)
    repo = await _artifact_repo()
    await _marker_status(repo, tenant.tenant_id, marker["artifact_id"], "analyzing")
    svc = _import_service()
    try:
        payload = await svc.analyze_import(tenant.tenant_id, canonical_id)
    except Exception:
        # Best-effort: back the marker off to ``uploaded`` so it is not pinned
        # in ``analyzing`` forever; canonical engine owns failure vocabulary.
        try:
            await _marker_status(repo, tenant.tenant_id, marker["artifact_id"], "uploaded")
        except Exception:
            pass
        raise
    await _marker_status(repo, tenant.tenant_id, marker["artifact_id"], "ready")
    payload = dict(payload)
    payload["import_id"] = import_id  # translate to the envelope namespace
    return payload


# ── PUT /imports/{import_id}/mapping — envelope mapping translate ───────────


def _translate_fields(fields: list[dict]) -> list[dict]:
    """Translate envelope ``fields`` onto canonical ``FieldMapping`` dicts.

    The envelope contract delegates field-level mapping details to the import
    engine's ``FieldMapping`` model, so translation is structural: each item
    must name the canonical keys and is otherwise passed through untouched.
    """
    canonical_fields: list[dict] = []
    for i, f in enumerate(fields):
        if not isinstance(f, dict):
            raise BadRequestError(f"mapping field {i} must be an object")
        missing = [k for k in ("source_column", "primitive", "target_field") if k not in f]
        if missing:
            raise BadRequestError(
                f"mapping field {i} is missing canonical keys: {', '.join(missing)}"
            )
        canonical_fields.append(
            {
                "source_column": f["source_column"],
                "primitive": f["primitive"],
                "target_field": f["target_field"],
                "transform": f.get("transform", "none"),
                "required": bool(f.get("required", False)),
            }
        )
    return canonical_fields


@router.put("/{import_id}/mapping")
async def set_mapping(import_id: str, body: ImportMappingContract, request: Request):
    """Translate an envelope ``ImportMappingContract`` onto the canonical mapping."""
    tenant = _tenant(request, "data_exchange.import.map")
    if body.tenant_id != tenant.tenant_id:
        raise ForbiddenError(
            f"tenant_id {body.tenant_id!r} does not match the authenticated tenant"
        )
    if body.import_id != import_id:
        raise BadRequestError(
            f"body.import_id {body.import_id!r} does not match the path import_id {import_id!r}"
        )
    canonical_id, _marker = await _resolve_canonical(tenant.tenant_id, import_id)

    svc = _import_service()
    fields = _translate_fields(body.fields)
    stored = await svc.set_mapping(tenant.tenant_id, canonical_id, fields)
    return {
        "import_id": import_id,
        "mapping_version": int(stored.get("version", 1)),
    }


# ── preview adapters ────────────────────────────────────────────────────────


@router.post("/{import_id}/preview/identity")
async def preview_identity(import_id: str, body: IdentityPreviewBody, request: Request):
    """Net-new identity-preview adapter (read-only resolution decisions)."""
    from services.data_exchange.identity_preview import preview_identity_decisions

    tenant = _tenant(request, "data_exchange.read")
    canonical_id, _marker = await _resolve_canonical(tenant.tenant_id, import_id)
    result = await preview_identity_decisions(
        tenant.tenant_id,
        canonical_id,
        identity_fields=body.identity_fields,
    )
    result["import_id"] = import_id
    return result


@router.post("/{import_id}/preview/graph")
async def preview_graph(
    import_id: str,
    request: Request,
    body: Optional[MappingVersionBody] = None,
):
    """Graph-preview proxy over the canonical import graph-preview seam."""
    from services.data_exchange.graph_preview import preview_graph as _preview_graph

    tenant = _tenant(request, "data_exchange.read")
    canonical_id, _marker = await _resolve_canonical(tenant.tenant_id, import_id)
    mapping_version = body.mapping_version if body is not None else None
    payload = await _preview_graph(
        tenant.tenant_id,
        canonical_id,
        mapping_version=mapping_version,
    )
    # Translate the canonical id back into the envelope namespace (the
    # adapter reports the canonical import id it previewed).
    payload["import_id"] = import_id
    return payload


# ── POST /imports/{import_id}/commit — enqueue canonical commit ─────────────


@router.post("/{import_id}/commit")
async def commit_import(import_id: str, request: Request):
    """Enqueue the canonical ``import.commit`` durable job."""
    tenant = _tenant(request, "data_exchange.import.commit")
    canonical_id, marker = await _resolve_canonical(tenant.tenant_id, import_id)

    # Fail fast when the canonical session is not approved (mirrors the
    # canonical /v1/imports commit route) rather than enqueueing a doomed job.
    session = await get_imports_repository().get_session(tenant.tenant_id, canonical_id)
    status = session.get("status")
    if status != "approved":
        raise ConflictError(f"import must be approved before commit (current: {status!r})")

    from services.jobs.service import get_jobs_service

    job = await get_jobs_service().enqueue(
        tenant.tenant_id,
        "import.commit",
        {"import_id": canonical_id},
        idempotency_key=f"import-commit:{canonical_id}",
        correlation_id=_request_id(request),
        requested_by=_user(request),
    )
    await _marker_status(await _artifact_repo(), tenant.tenant_id, marker["artifact_id"], "processing")
    return {
        "import_id": import_id,
        "job_id": job.get("id"),
        "status": "processing",
    }


# ── POST /imports/{import_id}/rollback — rollback proxy ─────────────────────


@router.post("/{import_id}/rollback")
async def rollback_import(import_id: str, body: RollbackBody, request: Request):
    """Proxy the canonical engine's graph rollback (elevated, admin)."""
    from services.imports.commit import rollback_import as _rollback

    tenant = _tenant(request, "data_exchange.import.rollback")
    canonical_id, marker = await _resolve_canonical(tenant.tenant_id, import_id)
    result = await _rollback(
        tenant.tenant_id,
        canonical_id,
        commit_id=body.commit_id,
        reason=body.reason,
    )
    # After a rollback the marker is revoked (tombstone vocabulary).
    await _marker_status(await _artifact_repo(), tenant.tenant_id, marker["artifact_id"], "revoked")
    return {
        "import_id": import_id,
        "rolled_back_commit_id": result.get("commit_id"),
    }
