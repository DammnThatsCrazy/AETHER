"""Data Exchange Plane — signed transfer orchestration (M2).

M2 adds short-TTL **presigned URL** transfers over the shared ObjectStore so
artifact bytes move directly between the tenant client and object storage —
never proxied through the envelope (see ``docs/plans/data-exchange-api.md``
M2).  This module is the DB-free core; the FastAPI surface lives in
``routes_transfer.py``.

Three operations, all tenant-scoped and derived from the M1 object-key scheme
(``services/data_exchange/storage.py``):

- ``issue_upload_url``      — assert the artifact row exists, is tenant-owned,
  and sits in a pre-upload state; return a short-TTL presigned PUT bound to the
  artifact's object key.
- ``verify_upload_complete`` — server-side verify after the external PUT: head
  the object, re-assert the tenant key prefix, compare declared size/sha256
  when supplied, then flip the artifact status to ``uploaded``.
- ``issue_download_url``    — presigned GET, only for artifacts whose status is
  ``available`` or ``committed`` and whose retention has not lapsed.  Records
  the download audit + event the canonical ``/v1/exports/{id}/download`` route
  records (mirrored through module seams so tests stay DB-free).

Security model.  The presign *layer* binds a signed URL to
``tenant_id + object_key + method + expiry`` (the object key scheme embeds
``tenant_id`` and ``artifact_id``, so artifact binding rides the key).  A URL
issued for one tenant or artifact cannot be re-targeted to another.  Tenant
ownership of the *metadata row* is enforced independently here against
``data_artifacts`` (cross-tenant reads raise ``NotFoundError``), and every
issued URL is only minted from a row the caller owns.

Availability.  Presigning is an optional store capability
(``PresignableObjectStore`` in ``shared/storage/object_store.py``).  A backend
that cannot sign (e.g. a bespoke read-only store) surfaces the canonical
``ServiceUnavailableError`` — the route surface is flag-gated, so this is an
availability issue, never a semantic fallback.

Events.  At first emission the topics below map onto canonical topics where one
exists (download issuance reuses the canonical ``EXPORT_DOWNLOADED`` the export
download route emits); genuinely-new transfer topics are referenced by member
*name* so emission is a silent no-op until the coordinator registers them in
``shared/events/events.py`` + the SDK event registry (see module constants).
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional

from repositories.data_artifacts import (
    DataArtifactRepository,
    get_data_artifact_repository,
)
from services.data_exchange.storage import tenant_object_prefix
from shared.common.common import BadRequestError, NotFoundError, ServiceUnavailableError
from shared.logger.logger import get_logger, metrics
from shared.storage.object_store import (
    ObjectStore,
    PresignableObjectStore,
    get_object_store,
)

logger = get_logger("aether.data_exchange.transfers")

# ── TTL policy ──────────────────────────────────────────────────────────────
# Short windows by default; a caller may shorten but never extend beyond the
# cap.  The coordinator may surface these as env knobs at integration.

DEFAULT_UPLOAD_URL_TTL_SECONDS = 15 * 60
DEFAULT_DOWNLOAD_URL_TTL_SECONDS = 5 * 60
MAX_TRANSFER_URL_TTL_SECONDS = 60 * 60

# ── artifact-state gates ────────────────────────────────────────────────────

# An artifact may receive a signed upload only before durable bytes land.
PRE_UPLOAD_ARTIFACT_STATUSES = frozenset({"created", "upload_pending", "uploading"})

# verify_upload_complete also accepts an already-``uploaded`` artifact so a
# client retry of upload-complete is a safe idempotent re-verify.
VERIFY_ACCEPTED_STATUSES = frozenset(PRE_UPLOAD_ARTIFACT_STATUSES) | frozenset({"uploaded"})

# Downloads are only minted for verified, durable, non-tombstone artifacts.
DOWNLOADABLE_ARTIFACT_STATUSES = frozenset({"available", "committed"})

# ── events / audit (proposed shared-surface names — see module docstring) ──

# Canonical Topic member *name* emitted after a verified signed upload.  There
# is no canonical "artifact uploaded" topic yet, so this resolves to nothing
# (silent no-op) until the coordinator registers it.  Coordinator may instead
# map onto the canonical IMPORT_UPLOADED at M3 integration.
UPLOAD_COMPLETE_TOPIC = "DATA_EXCHANGE_ARTIFACT_UPLOADED"

# Canonical Topic member name for download issuance — reuses the topic the
# canonical /v1/exports/{id}/download route emits.
DOWNLOAD_URL_ISSUED_TOPIC = "EXPORT_DOWNLOADED"

# Audit event_type for a signed download-URL issuance (canonical export
# downloads use ``audit_export.download``; data-exchange artifacts are their
# own resource type and get their own audit event name).
DOWNLOAD_AUDIT_EVENT_TYPE = "data_exchange.artifact.download"


def _clamp_ttl(expires_in_seconds: Optional[int], default: int) -> int:
    if expires_in_seconds is None:
        seconds = default
    else:
        try:
            seconds = int(expires_in_seconds)
        except (TypeError, ValueError) as exc:
            raise BadRequestError("expires_in_seconds must be an integer") from exc
    if seconds <= 0:
        raise BadRequestError("expires_in_seconds must be positive")
    if seconds > MAX_TRANSFER_URL_TTL_SECONDS:
        raise BadRequestError(
            f"expires_in_seconds must be at most {MAX_TRANSFER_URL_TTL_SECONDS}"
        )
    return seconds


def _require_presignable(object_store: ObjectStore) -> PresignableObjectStore:
    if not isinstance(object_store, PresignableObjectStore):
        raise ServiceUnavailableError(
            "data exchange signed transfers (object store backend cannot presign)"
        )
    return object_store


def _require_tenant(tenant_id: str) -> str:
    if not tenant_id:
        raise BadRequestError("tenant_id is required")
    return tenant_id


def _assert_tenant_object_key(row: dict, tenant_id: str) -> str:
    """Re-assert the artifact's object key stays inside the tenant's subtree.

    The M1 key scheme is ``data-exchange/<tenant_id>/<direction>/<artifact_id>``;
    the trailing-slash tenant prefix means ``acme`` never matches ``acme2``.  A
    row whose key escaped its tenant prefix is refused outright — this is the
    load-bearing check on upload-complete verify and download issuance.
    """
    object_key = row.get("object_key") or ""
    if not object_key.startswith(tenant_object_prefix(tenant_id)):
        raise BadRequestError(
            f"artifact object key is not tenant-scoped to {tenant_id!r}; refusing transfer"
        )
    return object_key


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _emit(topic_name: str, tenant_id: str, payload: dict) -> None:
    """Best-effort bus publish (mirrors ``services/export/service.py:_emit``).

    The flow never fails on telemetry, and a topic that has not been registered
    on the canonical ``Topic`` enum is a silent no-op.
    """
    try:
        from shared.events.events import Event, Topic

        topic = getattr(Topic, topic_name, None)
        if topic is None:
            return
        from dependencies.providers import get_producer

        producer = get_producer()
        await producer.publish(Event(topic=topic, tenant_id=tenant_id, payload=payload))
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("data exchange transfer event publish skipped: %s", exc)


async def _record_download_audit(
    *,
    actor_id: str,
    tenant_id: str,
    artifact_id: str,
    ip_address: Optional[str],
    metadata: Optional[dict],
) -> None:
    """Mirror the canonical export-download audit (``audit_export.download``)
    for a data-exchange artifact download-URL issuance."""
    from services.security.audit_ledger import audit_ledger

    await audit_ledger.record(
        actor_id=actor_id,
        actor_type="tenant_user",
        event_type=DOWNLOAD_AUDIT_EVENT_TYPE,
        resource_type="data_artifact",
        action="download",
        outcome="allowed",
        tenant_id=tenant_id,
        resource_id=artifact_id,
        ip_address=ip_address,
        metadata=metadata,
    )


class ObjectTransferService:
    """Signed transfer orchestration over ``data_artifacts`` + ObjectStore.

    Constructed with the shared ObjectStore and the Data Exchange artifact
    repository (both injectable for tests); module default resolves the
    canonical singletons, so routes stay thin.
    """

    def __init__(
        self,
        *,
        object_store: Optional[ObjectStore] = None,
        artifact_repo: Optional[DataArtifactRepository] = None,
    ) -> None:
        self._object_store: ObjectStore = (
            object_store if object_store is not None else get_object_store()
        )
        self._repo: DataArtifactRepository = (
            artifact_repo if artifact_repo is not None else get_data_artifact_repository()
        )

    # ── upload ────────────────────────────────────────────────────────────

    async def issue_upload_url(
        self,
        tenant_id: str,
        artifact_id: str,
        *,
        expires_in_seconds: Optional[int] = None,
    ) -> dict:
        """Issue a short-TTL presigned PUT for a tenant-owned, pre-upload artifact.

        Returns the exact ``/transfers/{artifact_id}/upload-url`` response shape
        ({artifact_id, object_key, upload_url, upload_method, upload_headers,
        expires_at, status}) and leaves the artifact in ``upload_pending``.
        """
        _require_tenant(tenant_id)
        seconds = _clamp_ttl(expires_in_seconds, DEFAULT_UPLOAD_URL_TTL_SECONDS)
        row = await self._repo.get(tenant_id, artifact_id)  # NotFound cross-tenant
        status = row.get("status") or "created"
        if status not in PRE_UPLOAD_ARTIFACT_STATUSES:
            raise BadRequestError(
                f"data exchange artifact {artifact_id!r} is in status {status!r} and "
                "cannot accept an upload — expected one of "
                + ", ".join(sorted(PRE_UPLOAD_ARTIFACT_STATUSES))
            )
        object_key = _assert_tenant_object_key(row, tenant_id)
        presignable = _require_presignable(self._object_store)
        transfer = presignable.create_presigned_put_url(
            object_key, tenant_id=tenant_id, expires_in_seconds=seconds
        )
        if status != "upload_pending":
            await self._repo.update_status(tenant_id, artifact_id, "upload_pending")
        metrics.increment(
            "data_exchange_upload_url_issued_total",
            labels={"artifact_type": row.get("artifact_type", "unknown")},
        )
        return {
            "artifact_id": artifact_id,
            "object_key": object_key,
            "upload_url": transfer.url,
            "upload_method": transfer.method,
            "upload_headers": dict(transfer.headers or {}),
            "expires_at": transfer.expires_at,
            "status": "upload_pending",
        }

    async def verify_upload_complete(
        self,
        tenant_id: str,
        artifact_id: str,
        *,
        declared_size_bytes: Optional[int] = None,
        declared_sha256: Optional[str] = None,
    ) -> dict:
        """Server-side verify after the external PUT, then flip to ``uploaded``.

        Heads the object, re-asserts the tenant key prefix, compares the
        declared size/sha256 when supplied, computes the authoritative
        size/hash, and refuses on any mismatch.  Returns the frozen
        ``{artifact_id, status, verified:{size_bytes, sha256}, stored_bytes}``
        upload-complete shape.
        """
        _require_tenant(tenant_id)
        row = await self._repo.get(tenant_id, artifact_id)  # NotFound cross-tenant
        status = row.get("status") or "created"
        if status not in VERIFY_ACCEPTED_STATUSES:
            raise BadRequestError(
                f"data exchange artifact {artifact_id!r} is in status {status!r} and "
                "has no pending upload to verify"
            )
        object_key = _assert_tenant_object_key(row, tenant_id)

        stat = self._object_store.head(object_key)
        if stat is None:
            raise BadRequestError(
                f"no bytes found at object key for artifact {artifact_id!r} — "
                "the signed upload has not completed"
            )
        actual_size = int(stat.size_bytes)
        actual_bytes = self._object_store.get(object_key)
        actual_sha256 = hashlib.sha256(actual_bytes).hexdigest()

        if declared_size_bytes is not None:
            try:
                declared_size = int(declared_size_bytes)
            except (TypeError, ValueError) as exc:
                raise BadRequestError("declared_size_bytes must be an integer") from exc
            if declared_size < 0:
                raise BadRequestError("declared_size_bytes must be >= 0")
            if declared_size != actual_size:
                raise BadRequestError(
                    f"declared size {declared_size} does not match stored size "
                    f"{actual_size} for artifact {artifact_id!r}"
                )

        if declared_sha256:
            declared = str(declared_sha256).strip().lower()
            if len(declared) != 64 or any(c not in "0123456789abcdef" for c in declared):
                raise BadRequestError("declared_sha256 must be a hex sha256 digest")
            if declared != actual_sha256:
                raise BadRequestError(
                    f"declared sha256 does not match stored content for artifact "
                    f"{artifact_id!r}"
                )

        transitioned = status != "uploaded"
        if transitioned:
            await self._repo.update_status(tenant_id, artifact_id, "uploaded")
        if transitioned and row.get("direction") == "ingress":
            await _emit(
                UPLOAD_COMPLETE_TOPIC,
                tenant_id,
                {
                    "artifact_id": artifact_id,
                    "object_key": object_key,
                    "direction": row.get("direction"),
                    "artifact_type": row.get("artifact_type"),
                    "size_bytes": actual_size,
                    "sha256": actual_sha256,
                },
            )
        metrics.increment(
            "data_exchange_upload_complete_total",
            labels={"artifact_type": row.get("artifact_type", "unknown")},
        )
        return {
            "artifact_id": artifact_id,
            "status": "uploaded",
            "verified": {"size_bytes": actual_size, "sha256": actual_sha256},
            "stored_bytes": actual_size,
        }

    # ── download ──────────────────────────────────────────────────────────

    async def issue_download_url(
        self,
        tenant_id: str,
        artifact_id: str,
        *,
        expires_in_seconds: Optional[int] = None,
        actor_id: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> dict:
        """Issue a short-TTL presigned GET for a download-eligible artifact.

        Only ``available``/``committed`` artifacts with unexpired retention are
        downloadable; deleted/expired/revoked and every other status refuse with
        ``NotFoundError``.  Mirrors the canonical export download route's audit
        (ledger record + ``EXPORT_DOWNLOADED`` event + metric).  Returns the
        frozen ``/transfers/{artifact_id}/download-url`` response shape.
        """
        _require_tenant(tenant_id)
        seconds = _clamp_ttl(expires_in_seconds, DEFAULT_DOWNLOAD_URL_TTL_SECONDS)
        row = await self._repo.get(tenant_id, artifact_id)  # NotFound cross-tenant
        if row.get("status") not in DOWNLOADABLE_ARTIFACT_STATUSES:
            # Matches the canonical "import file (deleted or expired) not found"
            # refusal idiom for non-downloadable/revoked/expired artifacts.
            raise NotFoundError("data exchange artifact (not available for download)")
        expires_at = row.get("expires_at")
        if expires_at is not None:
            from shared.common.common import parse_iso

            if _now() >= parse_iso(expires_at):
                raise NotFoundError("data exchange artifact (expired)")
        object_key = _assert_tenant_object_key(row, tenant_id)
        presignable = _require_presignable(self._object_store)
        transfer = presignable.create_presigned_get_url(
            object_key, tenant_id=tenant_id, expires_in_seconds=seconds
        )

        actor = actor_id or tenant_id
        await _record_download_audit(
            actor_id=actor,
            tenant_id=tenant_id,
            artifact_id=artifact_id,
            ip_address=ip_address,
            metadata={
                "object_key": object_key,
                "direction": row.get("direction"),
                "artifact_type": row.get("artifact_type"),
                "filename": row.get("filename"),
                "checksum_sha256": row.get("sha256"),
                "via": "presigned_url",
            },
        )
        await _emit(
            DOWNLOAD_URL_ISSUED_TOPIC,
            tenant_id,
            {
                "artifact_id": artifact_id,
                "artifact_type": row.get("artifact_type"),
                "direction": row.get("direction"),
                "object_key": object_key,
                "via": "presigned_url",
            },
        )
        metrics.increment(
            "data_exchange_download_url_issued_total",
            labels={"artifact_type": row.get("artifact_type", "unknown")},
        )
        return {
            "artifact_id": artifact_id,
            "download_url": transfer.url,
            "download_headers": dict(transfer.headers or {}),
            "expires_at": transfer.expires_at,
            "checksum_sha256": row.get("sha256") or "",
        }


_transfer_service: Optional[ObjectTransferService] = None


def get_object_transfer_service() -> ObjectTransferService:
    """Module singleton mirroring the repository/service factory pattern."""
    global _transfer_service
    if _transfer_service is None:
        _transfer_service = ObjectTransferService()
    return _transfer_service
