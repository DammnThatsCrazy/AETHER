"""Data Exchange Plane — idempotent legacy BYTEA → ObjectStore migration (M1).

``data_exchange.migrate_legacy_artifact`` copies ONE legacy BYTEA import-file
payload (still held by the canonical ``import_files`` BYTEA store, read through
the canonical ``ImportStorageAdapter`` seam) onto the shared ObjectStore at the
tenant-scoped object-key scheme, and records a ``data_artifacts`` metadata row
(direction ``ingress``; ``canonical_id`` = the legacy import-file id).

Idempotency: a retry MUST not duplicate.  The job first looks up the artifact
row by ``canonical_id`` (deterministic given the legacy file id), and — because
the ``artifact_id`` (and therefore the object key) is derived deterministically
from ``(tenant_id, canonical_id)`` — also probes the object store for an
already-written object.  If either already exists, the job no-ops
(``skipped``) and returns the existing identity.  BYTEA remains canonical
through the compat window; this job *adds* the ObjectStore-backed copy.

The core logic is a plain async function (``migrate_legacy_artifact``) that is
unit-testable without the durable-job runtime; the ``register``-ed handler is a
thin adapter onto the jobs-platform signature (``(payload, ctx) -> JobOutcome``,
see ``services/jobs/handlers.py``).
"""

from __future__ import annotations

import hashlib
from typing import Optional

from repositories.data_artifacts import (
    DataArtifactRepository,
    get_data_artifact_repository,
)
from services.data_exchange.storage import (
    infer_ingress_format,
    object_key_for,
)
from services.imports.storage import ImportStorageAdapter, get_import_storage
from shared.common.common import BadRequestError
from shared.logger.logger import get_logger
from shared.storage.object_store import (
    ObjectNotFoundError,
    ObjectStore,
    get_object_store,
)

logger = get_logger("aether.data_exchange.migrate")

# Default artifact_type for a migrated legacy import source (matches the M0
# ingress-artifact vocabulary used across data_exchange).
DEFAULT_ARTIFACT_TYPE = "import_source"
DEFAULT_MIGRATION_STATUS = "uploaded"


def migrate_artifact_id(tenant_id: str, canonical_id: str) -> str:
    """Deterministic Data Exchange artifact id for a legacy payload.

    Derived from ``(tenant_id, canonical_id)`` so a retry reconstructs the same
    ``artifact_id`` and therefore the same object key — the object-existence
    probe stays meaningful across attempts.
    """
    digest = hashlib.sha256(
        f"{tenant_id}:{canonical_id}".encode("utf-8")
    ).hexdigest()
    return f"dxa_{digest[:32]}"


async def migrate_legacy_artifact(
    tenant_id: str,
    file_id: str,
    *,
    source_storage: Optional[ImportStorageAdapter] = None,
    object_store: Optional[ObjectStore] = None,
    artifact_repo: Optional[DataArtifactRepository] = None,
    artifact_type: str = DEFAULT_ARTIFACT_TYPE,
    classification: str = "none",
    status: str = DEFAULT_MIGRATION_STATUS,
    job_id: Optional[str] = None,
    created_by: Optional[str] = None,
    correlation_id: Optional[str] = None,
    expires_at: Optional[str] = None,
) -> dict:
    """Migrate one legacy BYTEA import file onto the ObjectStore.

    Idempotent: no-ops (``skipped``) when the artifact row already exists for
    ``canonical_id=file_id`` or when the deterministic object already exists.

    Returns a result dict with ``skipped``, ``reason``, ``canonical_id``,
    ``artifact_id`` and ``object_key``.
    """
    if not tenant_id or not file_id:
        raise BadRequestError("tenant_id and file_id are required")

    source = source_storage if source_storage is not None else get_import_storage()
    store = object_store if object_store is not None else get_object_store()
    repo = artifact_repo if artifact_repo is not None else get_data_artifact_repository()

    existing = await repo.get_by_canonical_id(tenant_id, file_id)
    if existing is not None:
        logger.info(
            "migrate_legacy_artifact skip=already_migrated tenant=%s file=%s artifact=%s",
            tenant_id,
            file_id,
            existing.get("artifact_id"),
        )
        return {
            "skipped": True,
            "reason": "already_migrated",
            "canonical_id": file_id,
            "artifact_id": existing["artifact_id"],
            "object_key": existing["object_key"],
        }

    artifact_id = migrate_artifact_id(tenant_id, file_id)
    object_key = object_key_for(
        tenant_id, direction="ingress", artifact_id=artifact_id
    )

    meta, content = await source.get_content(tenant_id, file_id)
    if content is None or len(content) == 0:
        raise BadRequestError(
            f"legacy import file {file_id!r} holds no content to migrate"
        )

    filename = meta.get("filename") or file_id
    content_type = meta.get("content_type") or "application/octet-stream"
    sha256 = meta.get("sha256") or hashlib.sha256(content).hexdigest()

    # Self-heal a crash-window orphan: a prior attempt may have written bytes
    # (deterministic key) then died before ``create_artifact``.  Retrying must
    # not strand a permanent byte-only orphan — if the existing object matches
    # the current source we keep it and back-fill the row (bytes-then-row was
    # already satisfied); if it is STALE (the legacy source changed since) we
    # drop it and rewrite.  Either way the retry COMPLETES the migration and the
    # object at the deterministic key is exactly ``content`` before the row is
    # created, so no metadata row ever points at missing/mismatched bytes.
    if store.head(object_key) is not None:
        try:
            matches = store.get(object_key) == content
        except ObjectNotFoundError:
            matches = False  # vanished between head and get — rewrite below
        if not matches:
            logger.warning(
                "migrate_legacy_artifact stale-orphan tenant=%s file=%s key=%s "
                "(object differs from current legacy source — rewriting)",
                tenant_id,
                file_id,
                object_key,
            )
            store.delete(object_key)

    # Bytes first, metadata second.
    store.put(object_key, content)
    await repo.create_artifact(
        artifact_id,
        tenant_id,
        direction="ingress",
        artifact_type=artifact_type,
        object_key=object_key,
        filename=filename,
        format=meta.get("format") or infer_ingress_format(filename, content_type),
        content_type=content_type,
        size_bytes=meta.get("size_bytes", len(content)),
        sha256=sha256,
        classification=classification,
        status=status,
        canonical_id=file_id,
        job_id=job_id,
        source_or_destination={
            "legacy_file_id": file_id,
            "import_id": meta.get("import_id"),
            "storage": "object_store",
            "migration": True,
        },
        created_by=created_by,
        correlation_id=correlation_id,
        expires_at=expires_at,
    )
    logger.info(
        "migrate_legacy_artifact ok tenant=%s file=%s artifact=%s key=%s bytes=%d",
        tenant_id,
        file_id,
        artifact_id,
        object_key,
        len(content),
    )
    return {
        "skipped": False,
        "reason": None,
        "canonical_id": file_id,
        "artifact_id": artifact_id,
        "object_key": object_key,
        "size_bytes": len(content),
    }


async def migrate_legacy_artifact_job(payload: dict, ctx: object) -> object:
    """``data_exchange.migrate_legacy_artifact`` durable-job handler.

    Thin adapter onto the jobs-platform handler contract; the core logic lives
    in ``migrate_legacy_artifact`` (directly unit-testable).  Uses the runtime
    singletons (canonical BYTEA source, shared ObjectStore, artifact repo).
    """
    from services.jobs.handlers import JobOutcome

    file_id = payload["file_id"]
    result = await migrate_legacy_artifact(
        getattr(ctx, "tenant_id", payload.get("tenant_id") or ""),
        file_id,
        artifact_type=payload.get("artifact_type", DEFAULT_ARTIFACT_TYPE),
        status=payload.get("status", DEFAULT_MIGRATION_STATUS),
        created_by=payload.get("created_by"),
        correlation_id=getattr(ctx, "correlation_id", None)
        or payload.get("correlation_id"),
        job_id=getattr(ctx, "job_id", None),
        expires_at=payload.get("expires_at"),
    )
    return JobOutcome(status="succeeded", result=result)


def register() -> None:
    """Register the ``data_exchange.migrate_legacy_artifact`` handler.

    Idempotent (a re-import during tests never double-registers).  Called from
    the FastAPI lifespan startup, alongside ``register_import_handlers()``.
    Registration is inert until a job is enqueued — enqueuing this type is
    gated on ``settings.data_exchange.object_store_enabled`` by the caller.
    """
    from services.jobs.handlers import HANDLER_REGISTRY, register_handler

    if "data_exchange.migrate_legacy_artifact" in HANDLER_REGISTRY:
        return
    register_handler("data_exchange.migrate_legacy_artifact")(
        migrate_legacy_artifact_job
    )
    logger.info("registered data_exchange.migrate_legacy_artifact job handler")
