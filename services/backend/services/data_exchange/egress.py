"""Data Exchange Plane — M4 egress-completion bridge (coordinator delta).

Closes the materialization gap named in ``services/data_exchange/routes_export.py``
(the module comment at ``_EMPTY_PAYLOAD_SHA256``): ``POST /v1/data-exchange/exports``
records a ``generating`` envelope row whose bytes only exist after the canonical
``export.generate`` durable job succeeds at the *canonical* artifact key.  This
module is the completion bridge the route comment defers to the coordinator:

- Invoked best-effort from the canonical job handler
  (``services/export/service.py::generate_export_artifact``) *after* the
  canonical engine wrote + checksum-verified its own artifact, so a bridge
  failure can never lose canonical bytes — the M7 ``finalize_pending_egress``
  job reconciles any straggler (it refuses to flip a row it cannot verify
  bytes for).
- The bridge mirrors the verified bytes onto the envelope's own tenant-scoped
  object key and atomically flips the row to terminal ``available`` with the
  real sha256/size and ``source_or_destination.materialized: true`` via
  ``DataArtifactRepository.mark_available``.
- Strict tenant/prefix discipline: the row's stored ``object_key`` must equal
  the deterministically-derived key for ``(tenant_id, direction, artifact_id)``
  or the bridge refuses (never writes outside a tenant's envelope prefix).
  A cross-tenant or missing row is a no-op ``skip``, never an error the
  canonical job must fail on.

Core logic is a plain async function (DB-free testable, mirrors the M1
``jobs_migrate.py`` style); the canonical handler call is best-effort.
"""

from __future__ import annotations

import hashlib
from typing import Optional

from repositories.data_artifacts import (
    DataArtifactRepository,
    get_data_artifact_repository,
)
from services.data_exchange.contracts import DATA_ARTIFACT_TERMINAL_STATUSES
from services.data_exchange.storage import object_key_for
from shared.common.common import NotFoundError
from shared.logger.logger import get_logger
from shared.storage.object_store import ObjectStore, get_object_store

logger = get_logger("aether.data_exchange.egress")


async def finalize_egress_envelope(
    tenant_id: str,
    export_id: str,
    *,
    content: bytes,
    content_type: str = "application/octet-stream",
    canonical_artifact_id: Optional[str] = None,
    artifact_repo: Optional[DataArtifactRepository] = None,
    object_store: Optional[ObjectStore] = None,
) -> dict:
    """Materialize one egress envelope: mirror verified bytes + flip to ``available``.

    Returns a result dict (``skipped`` / ``reason`` / ``artifact_id`` /
    ``object_key`` / ``sha256`` / ``size_bytes``).  Never raises for a missing
    or cross-tenant row — those are skipped so a canonical export that already
    succeeded is never failed retroactively by the envelope bridge.
    """
    if not tenant_id or not export_id:
        return {"skipped": True, "reason": "missing_ids", "artifact_id": export_id}
    repo = artifact_repo if artifact_repo is not None else get_data_artifact_repository()
    store = object_store if object_store is not None else get_object_store()

    try:
        row = await repo.get(tenant_id, export_id)
    except NotFoundError:
        logger.warning(
            "egress finalize skip=no_envelope_row tenant=%s export=%s",
            tenant_id,
            export_id,
        )
        return {"skipped": True, "reason": "no_envelope_row", "artifact_id": export_id}

    status = row.get("status") or "created"
    if status == "available":
        return {
            "skipped": True,
            "reason": "already_available",
            "artifact_id": export_id,
            "object_key": row.get("object_key"),
            "sha256": row.get("sha256"),
            "size_bytes": row.get("size_bytes"),
        }
    # Bytes are never written for a row that has already left the live state
    # (failed / deleted / expired / revoked / committed …): terminal statuses are
    # absorbing, so flipping one to ``available`` is forbidden and putting bytes
    # first would orphan an object behind a row that can never claim them.
    if status in DATA_ARTIFACT_TERMINAL_STATUSES:
        return {
            "skipped": True,
            "reason": "terminal_status",
            "artifact_id": export_id,
            "status": status,
        }

    # Never write outside the tenant's own envelope prefix: the stored key must
    # equal the deterministic key derived from (tenant, direction, artifact_id).
    direction = row.get("direction") or "egress"
    expected_key = object_key_for(tenant_id, direction=direction, artifact_id=export_id)
    object_key = row.get("object_key")
    if not object_key or object_key != expected_key:
        logger.error(
            "egress finalize skip=object_key_mismatch tenant=%s export=%s "
            "stored=%s expected=%s",
            tenant_id,
            export_id,
            object_key,
            expected_key,
        )
        return {
            "skipped": True,
            "reason": "object_key_mismatch",
            "artifact_id": export_id,
        }

    size_bytes = len(content)
    sha256 = hashlib.sha256(content).hexdigest()

    # Bytes first, metadata second (same ordering doctrine as jobs_migrate.py):
    # a crash after the put leaves an orphan object that reconcile/cleanup
    # sweep, never a row claiming bytes that are absent.
    store.put(object_key, content)
    updated = await repo.mark_available(
        tenant_id,
        export_id,
        size_bytes=size_bytes,
        sha256=sha256,
        metadata={
            "materialized": True,
            "content_type": content_type,
            "canonical_artifact_id": canonical_artifact_id,
        },
    )
    logger.info(
        "egress finalize ok tenant=%s export=%s key=%s bytes=%d sha=%s",
        tenant_id,
        export_id,
        object_key,
        size_bytes,
        sha256,
    )
    return {
        "skipped": False,
        "reason": None,
        "artifact_id": export_id,
        "object_key": object_key,
        "sha256": sha256,
        "size_bytes": size_bytes,
        "status": updated.get("status"),
    }


async def try_finalize_egress_envelope(
    tenant_id: str,
    export_id: str,
    *,
    content: bytes,
    content_type: str = "application/octet-stream",
    canonical_artifact_id: Optional[str] = None,
    artifact_repo: Optional[DataArtifactRepository] = None,
    object_store: Optional[ObjectStore] = None,
) -> None:
    """Best-effort bridge entry used by the canonical job handler.

    Telemetry/annotation must never break the canonical export that already
    succeeded — any failure is logged and left for the M7 reconcile job.
    Dependency overrides pass through to :func:`finalize_egress_envelope` for
    DB-free tests.
    """
    try:
        await finalize_egress_envelope(
            tenant_id,
            export_id,
            content=content,
            content_type=content_type,
            canonical_artifact_id=canonical_artifact_id,
            artifact_repo=artifact_repo,
            object_store=object_store,
        )
    except Exception as exc:  # noqa: BLE001 - defensive; never fails the job
        logger.warning(
            "egress finalize skipped tenant=%s export=%s error=%s",
            tenant_id,
            export_id,
            exc,
        )
