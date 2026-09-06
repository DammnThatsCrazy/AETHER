"""Data Exchange Plane — ObjectStore import-storage seam (M1).

M1 moves artifact payload bytes onto the shared ObjectStore while Postgres
BYTEA stays canonical for the legacy window (see ``docs/plans/
DATA_EXCHANGE_PHASES.md`` M1 and ``docs/plans/data-exchange-api.md`` M1).

Two pieces:

- A deterministic, tenant-scoped **object-key scheme**:
  ``data-exchange/<tenant_id>/<direction>/<artifact_id>``.  The tenant is the
  first path segment after the fixed prefix and every list/read is rooted at a
  trailing-slash tenant prefix, so no tenant can list or traverse another
  tenant's keys (``acme`` never matches ``acme2`` because of the trailing
  ``/``).  Segments are validated to reject ``/``, ``\\`` and ``.``/``..``
  traversal.

- ``ObjectStoreImportStorage`` — an ``ImportStorageAdapter`` implementation
  (see ``services/imports/storage.py``) that stores bytes *only* in the shared
  ``ObjectStore`` and records the durable metadata in the ``data_artifacts``
  table (``repositories/data_artifacts.py``).  Bytes never touch Postgres on
  this path; ``data_artifacts`` holds metadata only.

``get_data_exchange_import_storage()`` returns the ObjectStore-backed adapter
when ``settings.data_exchange.object_store_enabled`` is truthy, otherwise the
canonical BYTEA ``get_import_storage()`` (compat window).  The Data Exchange
Plane is a control envelope over canonical seams — this is not a parallel
storage abstraction and nothing is replaced while the flag is off.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Optional

from repositories.data_artifacts import (
    DataArtifactRepository,
    get_data_artifact_repository,
)
from services.data_exchange.contracts import DATA_EXCHANGE_DIRECTIONS
from services.imports.storage import ImportStorageAdapter, get_import_storage
from shared.common.common import BadRequestError, NotFoundError
from shared.storage.object_store import (
    ObjectNotFoundError,
    ObjectStore,
    get_object_store,
)

# ── tenant-scoped object-key scheme ─────────────────────────────────────────

OBJECT_KEY_PREFIX = "data-exchange"


def _validate_segment(value: str, *, label: str) -> None:
    if not isinstance(value, str) or not value:
        raise BadRequestError(f"{label} must be a non-empty string")
    if value in (".", ".."):
        raise BadRequestError(f"{label} must not be a path-traversal segment")
    if any(ch in value for ch in "/\\\x00"):
        raise BadRequestError(
            f"{label} must not contain path separators (got {value!r})"
        )


def object_key_for(tenant_id: str, *, direction: str, artifact_id: str) -> str:
    """Deterministic tenant-scoped object key for an artifact.

    ``data-exchange/<tenant_id>/<direction>/<artifact_id>``.  The tenant is a
    validated first segment; callers must always derive keys (and list
    prefixes) through this helper so no caller-supplied artifact id can
    escape its tenant prefix.
    """
    if direction not in DATA_EXCHANGE_DIRECTIONS:
        raise BadRequestError(
            f"invalid data exchange direction {direction!r} — expected one of "
            f"{', '.join(DATA_EXCHANGE_DIRECTIONS)}"
        )
    _validate_segment(tenant_id, label="tenant_id")
    _validate_segment(artifact_id, label="artifact_id")
    return f"{OBJECT_KEY_PREFIX}/{tenant_id}/{direction}/{artifact_id}"


def tenant_object_prefix(tenant_id: str) -> str:
    """List prefix rooted at a tenant (trailing slash guards ``acme``/``acme2``)."""
    _validate_segment(tenant_id, label="tenant_id")
    return f"{OBJECT_KEY_PREFIX}/{tenant_id}/"


# ── ingress format inference for stored metadata ────────────────────────────

_INGRESS_EXT_FORMATS: tuple[tuple[str, str], ...] = (
    (".csv", "csv"),
    (".json", "json"),
    (".jsonl", "jsonl"),
    (".parquet", "parquet"),
)

_INGRESS_CONTENT_TYPE_FORMATS: dict[str, str] = {
    "text/csv": "csv",
    "application/csv": "csv",
    "application/json": "json",
    "application/jsonl": "jsonl",
    "application/x-jsonlines": "jsonl",
    "application/x-ndjson": "jsonl",
    "application/ndjson": "jsonl",
    "application/vnd.apache.parquet": "parquet",
}


def infer_ingress_format(filename: str = "", content_type: str = "") -> str:
    """Best-effort ingress format from filename/content_type.

    The legacy import-engine ``put`` seam does not carry an explicit format
    (the engine detects it separately via ``detect_format``); the
    ``data_artifacts`` row still requires one, so M1 infers it from the file
    extension or content type.  This is dormant metadata — accurate detection
    at the control surface lands with M3.
    """
    name = (filename or "").lower()
    for ext, fmt in _INGRESS_EXT_FORMATS:
        if name.endswith(ext):
            return fmt
    content_type = (content_type or "").lower().split(";")[0].strip()
    if content_type in _INGRESS_CONTENT_TYPE_FORMATS:
        return _INGRESS_CONTENT_TYPE_FORMATS[content_type]
    if content_type.endswith("+json"):
        return "json"
    return "json"


# ── ObjectStore-backed ImportStorageAdapter ─────────────────────────────────


class ObjectStoreImportStorage:
    """``ImportStorageAdapter`` backed by the shared ``ObjectStore``.

    Bytes are written/read/head/deleted against ObjectStore at the
    tenant-scoped key scheme; metadata (sha256, size, filename, content type,
    import linkage) lives in the ``data_artifacts`` table.  This satisfies the
    exact ``ImportStorageAdapter`` protocol (``put`` / ``get_meta`` /
    ``get_content`` / ``list_for_import``) so the Import Engine can swap the
    canonical Postgres-BYTEA adapter for an ObjectStore-backed one without
    touching its callers.
    """

    def __init__(
        self,
        *,
        object_store: Optional[ObjectStore] = None,
        artifact_repo: Optional[DataArtifactRepository] = None,
        artifact_type: str = "import_source",
    ) -> None:
        self._object_store: ObjectStore = (
            object_store if object_store is not None else get_object_store()
        )
        self._repo: DataArtifactRepository = (
            artifact_repo if artifact_repo is not None else get_data_artifact_repository()
        )
        self._artifact_type = artifact_type

    @staticmethod
    def _as_import_meta(row: dict) -> dict:
        """Import-engine-shaped metadata (``id`` is the import file id)."""
        meta = {k: v for k, v in dict(row).items() if v is not None}
        meta["id"] = row["artifact_id"]
        meta.setdefault("import_id", row.get("canonical_id"))
        return meta

    async def put(
        self,
        tenant_id: str,
        *,
        import_id: str,
        filename: str,
        content: bytes,
        content_type: str,
    ) -> dict:
        if not tenant_id:
            raise BadRequestError("tenant_id is required")
        if not import_id:
            raise BadRequestError("import_id is required")
        if not filename:
            raise BadRequestError("filename is required")
        if content is None or len(content) == 0:
            raise BadRequestError("uploaded content is empty")
        # Canonical import-file id shape keeps drop-in compatibility.
        file_id = f"impf_{uuid.uuid4().hex}"
        object_key = object_key_for(
            tenant_id, direction="ingress", artifact_id=file_id
        )
        sha256 = hashlib.sha256(content).hexdigest()
        # Bytes first, metadata second.  A metadata failure leaves an orphan
        # object (never a metadata row pointing at missing bytes).
        self._object_store.put(object_key, content)
        row = await self._repo.create_artifact(
            file_id,
            tenant_id,
            direction="ingress",
            artifact_type=self._artifact_type,
            object_key=object_key,
            filename=filename,
            format=infer_ingress_format(filename, content_type),
            content_type=content_type,
            size_bytes=len(content),
            sha256=sha256,
            classification="none",
            status="uploaded",
            canonical_id=import_id,
            source_or_destination={
                "import_id": import_id,
                "import_file": True,
                "storage": "object_store",
            },
        )
        return self._as_import_meta(row)

    async def get_meta(self, tenant_id: str, file_id: str) -> dict:
        try:
            row = await self._repo.get(tenant_id, file_id)
        except NotFoundError:
            raise NotFoundError("import file") from None
        return self._as_import_meta(row)

    async def get_content(self, tenant_id: str, file_id: str) -> tuple[dict, bytes]:
        meta = await self.get_meta(tenant_id, file_id)
        if meta.get("status") in {"deleted", "expired"}:
            raise NotFoundError("import file (deleted or expired)")
        try:
            content = self._object_store.get(meta["object_key"])
        except ObjectNotFoundError:
            raise NotFoundError("import file content") from None
        return meta, bytes(content)

    async def list_for_import(self, tenant_id: str, import_id: str) -> list[dict]:
        rows = await self._repo.list_by_canonical_id(tenant_id, import_id)
        return [self._as_import_meta(r) for r in rows]

    async def delete(self, tenant_id: str, file_id: str) -> bool:
        """Delete object bytes and tombstone the metadata row."""
        try:
            meta = await self.get_meta(tenant_id, file_id)
        except NotFoundError:
            return False
        existed = self._object_store.delete(meta["object_key"])
        await self._repo.mark_deleted(tenant_id, file_id)
        return existed

    async def head(self, tenant_id: str, file_id: str) -> Optional[dict]:
        """Size-only existence probe (no payload, no Postgres metadata read)."""
        try:
            meta = await self.get_meta(tenant_id, file_id)
        except NotFoundError:
            return None
        return {"id": meta["id"], "size_bytes": meta.get("size_bytes")}


# ── factory ─────────────────────────────────────────────────────────────────

_adapter: Optional[ImportStorageAdapter] = None


def get_data_exchange_import_storage() -> ImportStorageAdapter:
    """Return the ObjectStore-backed storage when the M1 flag is on.

    ``settings.data_exchange.object_store_enabled`` selects the ObjectStore
    path; otherwise the canonical ``get_import_storage()`` (Postgres BYTEA)
    remains authoritative through the compat window.  Imported lazily so a
    default-OFF deployment never constructs the object-store path.
    """
    global _adapter
    from config.settings import settings  # lazy — avoids import cycles

    if not getattr(settings.data_exchange, "object_store_enabled", False):
        return get_import_storage()
    if _adapter is None:
        _adapter = ObjectStoreImportStorage()
    return _adapter
