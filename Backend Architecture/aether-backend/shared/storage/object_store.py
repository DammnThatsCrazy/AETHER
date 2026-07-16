"""
Aether Shared — Object Store Protocol

Minimal object-store abstraction for the Elastic Data Plane: put / get /
head / delete / list. Two implementations:

  - S3ObjectStore       production (boto3 imported lazily — never required
                        for local dev or the test suite)
  - InMemoryObjectStore local/dev/tests (shared dict, mirrors the in-memory
                        repository backend in repositories/repos.py)

Selection follows ``settings.runtime.object_backend`` ("s3" | "memory") via
``get_object_store()``. Mirroring repos.py: a missing boto3 falls back to the
in-memory store ONLY in AETHER_ENV=local; non-local environments fail closed.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Any, Optional, Protocol, runtime_checkable

from shared.logger.logger import get_logger

logger = get_logger("aether.storage.object_store")


class ObjectNotFoundError(KeyError):
    """Requested object key does not exist in the store."""


@dataclass(frozen=True)
class ObjectStat:
    """Result of a head() call — existence metadata without the payload."""

    key: str
    size_bytes: int


@runtime_checkable
class ObjectStore(Protocol):
    """Minimal protocol every object-store backend implements."""

    def put(self, key: str, data: bytes) -> None: ...

    def get(self, key: str) -> bytes: ...

    def head(self, key: str) -> Optional[ObjectStat]: ...

    def delete(self, key: str) -> bool: ...

    def list(self, prefix: str = "") -> list[str]: ...


# ═══════════════════════════════════════════════════════════════════════════
# IN-MEMORY IMPLEMENTATION — local / dev / tests
# ═══════════════════════════════════════════════════════════════════════════

class InMemoryObjectStore:
    """Dict-backed object store for local/dev/tests. Thread-safe."""

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}
        self._lock = threading.Lock()

    def put(self, key: str, data: bytes) -> None:
        if not key:
            raise ValueError("object key must be non-empty")
        with self._lock:
            self._objects[key] = bytes(data)

    def get(self, key: str) -> bytes:
        with self._lock:
            if key not in self._objects:
                raise ObjectNotFoundError(key)
            return self._objects[key]

    def head(self, key: str) -> Optional[ObjectStat]:
        with self._lock:
            data = self._objects.get(key)
        if data is None:
            return None
        return ObjectStat(key=key, size_bytes=len(data))

    def delete(self, key: str) -> bool:
        with self._lock:
            return self._objects.pop(key, None) is not None

    def list(self, prefix: str = "") -> list[str]:
        with self._lock:
            return sorted(k for k in self._objects if k.startswith(prefix))

    def clear(self) -> None:
        """Test helper: drop every object."""
        with self._lock:
            self._objects.clear()


# ═══════════════════════════════════════════════════════════════════════════
# S3 IMPLEMENTATION — boto3 imported lazily, never required locally
# ═══════════════════════════════════════════════════════════════════════════

class S3ObjectStore:
    """S3-backed object store. boto3 is imported on first use only."""

    def __init__(self, bucket: str, prefix: str = "", client: Any = None) -> None:
        if not bucket:
            raise ValueError(
                "S3ObjectStore requires a bucket — set STORAGE_OBJECT_BUCKET "
                "(settings.storage_plane.object_bucket)"
            )
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self._client = client  # injectable for tests; real client built lazily

    def _s3(self) -> Any:
        if self._client is None:
            try:
                import boto3  # noqa: PLC0415 — lazy by design
            except ImportError as exc:  # pragma: no cover - exercised in prod
                raise RuntimeError(
                    "boto3 is required for OBJECT_BACKEND=s3: pip install boto3"
                ) from exc
            self._client = boto3.client("s3")
        return self._client

    def _full_key(self, key: str) -> str:
        return f"{self.prefix}/{key}" if self.prefix else key

    def put(self, key: str, data: bytes) -> None:
        if not key:
            raise ValueError("object key must be non-empty")
        self._s3().put_object(Bucket=self.bucket, Key=self._full_key(key), Body=data)

    def get(self, key: str) -> bytes:
        try:
            response = self._s3().get_object(Bucket=self.bucket, Key=self._full_key(key))
        except Exception as exc:
            if _is_missing_key_error(exc):
                raise ObjectNotFoundError(key) from exc
            raise
        return response["Body"].read()

    def head(self, key: str) -> Optional[ObjectStat]:
        try:
            response = self._s3().head_object(Bucket=self.bucket, Key=self._full_key(key))
        except Exception as exc:
            if _is_missing_key_error(exc):
                return None
            raise
        return ObjectStat(key=key, size_bytes=int(response.get("ContentLength", 0)))

    def delete(self, key: str) -> bool:
        existed = self.head(key) is not None
        self._s3().delete_object(Bucket=self.bucket, Key=self._full_key(key))
        return existed

    def list(self, prefix: str = "") -> list[str]:
        full_prefix = self._full_key(prefix) if prefix else (
            f"{self.prefix}/" if self.prefix else ""
        )
        keys: list[str] = []
        paginator = self._s3().get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=full_prefix):
            for item in page.get("Contents", []) or []:
                key = item.get("Key", "")
                if self.prefix and key.startswith(f"{self.prefix}/"):
                    key = key[len(self.prefix) + 1:]
                if key:
                    keys.append(key)
        return sorted(keys)


def _is_missing_key_error(exc: Exception) -> bool:
    """True when a boto3 ClientError represents a missing key (404/NoSuchKey)."""
    code = ""
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = str((response.get("Error") or {}).get("Code", ""))
    return code in {"NoSuchKey", "404", "NotFound"}


# ═══════════════════════════════════════════════════════════════════════════
# BACKEND SELECTION — settings.runtime.object_backend ("s3" | "memory")
# ═══════════════════════════════════════════════════════════════════════════

# One shared in-memory store per process so the manager, reconciler, and any
# route singletons observe the same objects (mirrors _IN_MEMORY_STORES).
_SHARED_MEMORY_STORE = InMemoryObjectStore()


def _is_local_env() -> bool:
    return os.getenv("AETHER_ENV", "local").lower() == "local"


def get_object_store(backend: Optional[str] = None) -> ObjectStore:
    """Return the object store selected by settings.runtime.object_backend."""
    if backend is None:
        from config.settings import settings  # lazy — avoids import cycles

        backend = settings.runtime.object_backend
    backend = (backend or "").lower()

    if backend == "memory":
        return _SHARED_MEMORY_STORE

    if backend == "s3":
        from config.settings import settings  # lazy — avoids import cycles

        bucket = settings.storage_plane.object_bucket
        try:
            import boto3  # noqa: F401, PLC0415 — availability probe only
        except ImportError:
            if _is_local_env():
                logger.warning(
                    "boto3 not installed — using in-memory object store (local only)"
                )
                return _SHARED_MEMORY_STORE
            raise RuntimeError(
                "boto3 required for OBJECT_BACKEND=s3 outside local: pip install boto3"
            )
        return S3ObjectStore(bucket=bucket)

    raise ValueError(
        f"Unknown object backend {backend!r} — expected 's3' or 'memory'"
    )
