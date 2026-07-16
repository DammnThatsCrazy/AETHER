"""
Aether Shared — Policy-Driven Storage Manager

StorageManager is the single write/read path for externalized objects:

  - ``policy_for(resource_type)`` resolves the storage policy from
    config/storage_policies.yaml (loaded once per process). Unknown resource
    types FAIL CLOSED with UnknownResourceTypeError (a KeyError) — a
    persistent type without a policy must never reach the object store.
  - ``externalize(...)`` packs records (or raw bytes) into one object,
    honoring the policy: externalization must be allowed
    (``allow_object_externalization``) and the policy codec is applied.
    For ``codec: zstd`` the zstandard module is imported lazily; when it is
    absent locally the manager falls back to stdlib gzip (or stores raw) and
    records the codec ACTUALLY used in the descriptor.
  - ``hydrate(descriptor)`` fetches the object, verifies the sha256 checksum
    against the descriptor (raising ChecksumMismatchError on any drift), then
    reverses the recorded codec/format.

Descriptors persist through repositories.repos.StorageDescriptorRepository so
object metadata stays queryable in the hot store.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

from shared.logger.logger import get_logger, metrics
from shared.storage.descriptor import StorageDescriptor, sha256_hex
from shared.storage.object_store import ObjectStore, get_object_store

logger = get_logger("aether.storage.manager")

# Repo root: shared/storage/manager.py -> shared/storage -> shared ->
# aether-backend -> "Backend Architecture" -> repo root.
_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_POLICIES_PATH = _REPO_ROOT / "config" / "storage_policies.yaml"


class UnknownResourceTypeError(KeyError):
    """No storage policy exists for the resource type (fail closed)."""


class StoragePolicyViolationError(RuntimeError):
    """The requested operation is forbidden by the resource's storage policy."""


class ChecksumMismatchError(RuntimeError):
    """Hydrated object bytes do not match the descriptor's sha256 checksum."""


@dataclass(frozen=True)
class StoragePolicy:
    """One resource type's policy row from config/storage_policies.yaml."""

    resource_type: str
    authoritative_store: str
    metadata_store: str
    projection_stores: tuple[str, ...]
    codec: str
    format: str
    cache_ttl_seconds: int
    materialization_mode: str
    retention_class: str
    delete_behavior: str
    legal_hold_supported: bool
    allow_adaptive_materialization: bool
    allow_object_externalization: bool
    allow_historical_table_storage: bool
    requires_consent_invalidation: bool
    requires_permission_hash: bool

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StoragePolicy":
        return cls(
            resource_type=str(data["resource_type"]),
            authoritative_store=str(data.get("authoritative_store", "postgres")),
            metadata_store=str(data.get("metadata_store", "postgres")),
            projection_stores=tuple(data.get("projection_stores") or ()),
            codec=str(data.get("codec", "none")),
            format=str(data.get("format", "row")),
            cache_ttl_seconds=int(data.get("cache_ttl_seconds", 0)),
            materialization_mode=str(data.get("materialization_mode", "none")),
            retention_class=str(data.get("retention_class", "standard")),
            delete_behavior=str(data.get("delete_behavior", "hard_delete")),
            legal_hold_supported=bool(data.get("legal_hold_supported", True)),
            allow_adaptive_materialization=bool(data.get("allow_adaptive_materialization", False)),
            allow_object_externalization=bool(data.get("allow_object_externalization", False)),
            allow_historical_table_storage=bool(data.get("allow_historical_table_storage", True)),
            requires_consent_invalidation=bool(data.get("requires_consent_invalidation", False)),
            requires_permission_hash=bool(data.get("requires_permission_hash", False)),
        )


# Policies are loaded once per process per path (registry is repo config,
# immutable at runtime). Keyed by resolved path so tests can point at fixtures.
_POLICY_CACHE: dict[str, dict[str, StoragePolicy]] = {}


def load_storage_policies(
    path: Optional[Path] = None, *, force_reload: bool = False,
) -> dict[str, StoragePolicy]:
    """Load (once) and return the policy registry keyed by resource_type."""
    resolved = str((path or DEFAULT_POLICIES_PATH).resolve())
    if not force_reload and resolved in _POLICY_CACHE:
        return _POLICY_CACHE[resolved]

    import yaml  # lazy — PyYAML is a repo dependency, keep import cost off startup

    with open(resolved, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    policies: dict[str, StoragePolicy] = {}
    for row in data.get("policies") or []:
        policy = StoragePolicy.from_dict(row or {})
        policies[policy.resource_type] = policy
    _POLICY_CACHE[resolved] = policies
    logger.info(
        f"Storage policy registry loaded ({len(policies)} resource types, "
        f"enforcement_status={data.get('enforcement_status')!r})"
    )
    return policies


def policy_for(resource_type: str, path: Optional[Path] = None) -> StoragePolicy:
    """Resolve one resource type's policy. Unknown types fail closed."""
    policies = load_storage_policies(path)
    try:
        return policies[resource_type]
    except KeyError:
        raise UnknownResourceTypeError(
            f"No storage policy for resource_type {resource_type!r} — add it to "
            "config/storage_policies.yaml (the coverage gate requires one per "
            "persistent resource type)"
        ) from None


# ═══════════════════════════════════════════════════════════════════════════
# CODECS — zstd preferred, lazy import, gzip/none fallback recorded honestly
# ═══════════════════════════════════════════════════════════════════════════

def _compress(data: bytes, requested_codec: str) -> tuple[bytes, str]:
    """Apply the policy codec; return (stored_bytes, codec_actually_used)."""
    if requested_codec == "none":
        return data, "none"
    if requested_codec == "zstd":
        try:
            import zstandard  # noqa: PLC0415 — lazy by design
        except ImportError:
            import gzip  # noqa: PLC0415

            logger.warning(
                "zstandard not installed — falling back to gzip for this object "
                "(descriptor records the actual codec)"
            )
            return gzip.compress(data), "gzip"
        return zstandard.ZstdCompressor().compress(data), "zstd"
    raise StoragePolicyViolationError(f"Unsupported policy codec {requested_codec!r}")


def _decompress(data: bytes, codec: str) -> bytes:
    """Reverse the codec recorded on the descriptor."""
    if codec == "none":
        return data
    if codec == "gzip":
        import gzip  # noqa: PLC0415

        return gzip.decompress(data)
    if codec == "zstd":
        try:
            import zstandard  # noqa: PLC0415 — lazy by design
        except ImportError as exc:
            raise RuntimeError(
                "Object was stored with zstd but the zstandard module is not "
                "installed: pip install zstandard"
            ) from exc
        return zstandard.ZstdDecompressor().decompress(data)
    raise ValueError(f"Unknown descriptor codec {codec!r}")


def _encode_records(records: Sequence[dict]) -> bytes:
    """Canonical jsonl encoding (one compact JSON object per line)."""
    lines = [json.dumps(r, sort_keys=True, default=str) for r in records]
    return ("\n".join(lines) + "\n").encode("utf-8") if lines else b""


def _decode_records(data: bytes) -> list[dict]:
    return [json.loads(line) for line in data.decode("utf-8").splitlines() if line]


# ═══════════════════════════════════════════════════════════════════════════
# STORAGE MANAGER
# ═══════════════════════════════════════════════════════════════════════════

class StorageManager:
    """Policy-driven externalize/hydrate over the object store protocol.

    All collaborators are injectable for tests; defaults resolve lazily from
    settings (object store) and repositories.repos (descriptor repository).
    ``externalization_enabled=None`` reads settings.storage_plane at call time
    so the master flag is honored without freezing it at construction.
    """

    def __init__(
        self,
        object_store: Optional[ObjectStore] = None,
        descriptor_repo: Optional[Any] = None,
        policies_path: Optional[Path] = None,
        externalization_enabled: Optional[bool] = None,
    ) -> None:
        self._object_store = object_store
        self._descriptor_repo = descriptor_repo
        self._policies_path = policies_path
        self._externalization_enabled = externalization_enabled

    # -- collaborators ------------------------------------------------------

    @property
    def object_store(self) -> ObjectStore:
        if self._object_store is None:
            self._object_store = get_object_store()
        return self._object_store

    @property
    def descriptor_repo(self) -> Any:
        if self._descriptor_repo is None:
            from repositories.repos import StorageDescriptorRepository  # lazy

            self._descriptor_repo = StorageDescriptorRepository()
        return self._descriptor_repo

    def _externalization_allowed_globally(self) -> bool:
        if self._externalization_enabled is not None:
            return self._externalization_enabled
        from config.settings import settings  # lazy — avoids import cycles

        return settings.storage_plane.externalization_enabled

    # -- policy -------------------------------------------------------------

    def policy_for(self, resource_type: str) -> StoragePolicy:
        """Fail-closed policy lookup (KeyError for unknown resource types)."""
        return policy_for(resource_type, self._policies_path)

    # -- externalize --------------------------------------------------------

    async def externalize(
        self,
        resource_type: str,
        tenant_id: str,
        records: Optional[Sequence[dict]] = None,
        *,
        payload: Optional[bytes] = None,
        lineage: Sequence[str] = (),
        key: Optional[str] = None,
    ) -> StorageDescriptor:
        """Pack records (or raw payload bytes) into one externalized object.

        Enforces the resource's policy: the type must allow object
        externalization and the master storage-plane flag must be on. Returns
        the persisted StorageDescriptor (codec field reflects what was
        actually applied).
        """
        policy = self.policy_for(resource_type)  # KeyError if unknown
        if not policy.allow_object_externalization:
            raise StoragePolicyViolationError(
                f"Policy for {resource_type!r} forbids object externalization"
            )
        if not self._externalization_allowed_globally():
            raise StoragePolicyViolationError(
                "Storage externalization is disabled "
                "(set STORAGE_EXTERNALIZATION_ENABLED=true)"
            )
        if (records is None) == (payload is None):
            raise ValueError("Provide exactly one of records= or payload=")

        if records is not None:
            raw = _encode_records(records)
            fmt = "jsonl"
            record_count = len(records)
        else:
            raw = bytes(payload or b"")
            fmt = policy.format if policy.format != "row" else "bytes"
            record_count = 0

        stored, codec_used = _compress(raw, policy.codec)
        checksum = sha256_hex(stored)

        descriptor_id = f"sd_{uuid.uuid4().hex}"
        locator = key or (
            f"{resource_type}/{tenant_id or '_platform'}/"
            f"{descriptor_id}.{fmt}.{codec_used}"
        )
        descriptor = StorageDescriptor(
            resource_type=resource_type,
            tenant_id=tenant_id,
            locator=locator,
            codec=codec_used,
            format=fmt,
            checksum_sha256=checksum,
            size_bytes=len(stored),
            record_count=record_count,
            lineage=tuple(lineage),
            descriptor_id=descriptor_id,
        )

        self.object_store.put(descriptor.locator, stored)
        await self.descriptor_repo.record(descriptor)
        metrics.increment("storage_object_externalized_total")
        logger.info(
            f"EXTERNALIZE {resource_type} tenant={tenant_id} "
            f"locator={descriptor.locator} codec={codec_used} "
            f"bytes={len(stored)} records={record_count}"
        )
        return descriptor

    # -- hydrate ------------------------------------------------------------

    async def hydrate(self, descriptor: StorageDescriptor) -> Any:
        """Fetch + verify + decode one externalized object.

        Raises ChecksumMismatchError when the stored bytes do not hash to the
        descriptor's checksum (corruption / tamper / wrong object). Returns a
        list[dict] for jsonl objects, raw bytes otherwise.
        """
        stored = self.object_store.get(descriptor.locator)
        actual = sha256_hex(stored)
        if actual != descriptor.checksum_sha256:
            metrics.increment("storage_hydrate_checksum_mismatch_total")
            raise ChecksumMismatchError(
                f"Checksum mismatch for {descriptor.locator!r}: descriptor "
                f"declares {descriptor.checksum_sha256[:12]}..., object hashes "
                f"to {actual[:12]}..."
            )
        raw = _decompress(stored, descriptor.codec)
        metrics.increment("storage_object_hydrated_total")
        if descriptor.format == "jsonl":
            return _decode_records(raw)
        return raw
