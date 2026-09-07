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

Presigned transfers (M2 Data Exchange signed transfers) are an OPTIONAL
capability: the base ``ObjectStore`` protocol deliberately stays byte-plane
only. Backends that can issue short-TTL upload/download URLs advertise the
separate ``PresignableObjectStore`` protocol; callers feature-detect with
``isinstance(store, PresignableObjectStore)`` and fail closed when absent.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional, Protocol, runtime_checkable
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit

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
# PRESIGNED TRANSFER CAPABILITY — OPTIONAL, never on the base protocol
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class PresignedTransfer:
    """Short-TTL, scope-bound transfer URL issued by a presign-capable store.

    ``url`` already carries every signature/token needed to perform the
    operation against the backend (AWS SigV4 query params for S3, a signed
    aether-memory URL for the in-memory backend).  ``headers`` are the extra
    headers a conforming client MUST send (empty for S3 — signed headers are
    embedded in the URL).  ``expires_at`` is an ISO-8601 UTC instant.
    ``token`` is backend-specific (None for S3 — the signature lives in the
    URL query).
    """

    url: str
    method: str
    headers: dict[str, str] = field(default_factory=dict)
    expires_at: str = ""
    token: Optional[str] = None


@runtime_checkable
class PresignableObjectStore(Protocol):
    """Optional capability: backends that can issue signed short-TTL URLs.

    Kept off the base ``ObjectStore`` protocol because only concrete backends
    with a real signing authority can satisfy it.  Callers must feature-detect
    (``isinstance(store, PresignableObjectStore)``) and raise a canonical
    availability error when absent.
    """

    def create_presigned_put_url(
        self,
        object_key: str,
        *,
        tenant_id: str,
        expires_in_seconds: int,
    ) -> PresignedTransfer: ...

    def create_presigned_get_url(
        self,
        object_key: str,
        *,
        tenant_id: str,
        expires_in_seconds: int,
    ) -> PresignedTransfer: ...


# ═══════════════════════════════════════════════════════════════════════════
# IN-MEMORY PRESIGN TOKEN SCHEME — deterministic HMAC-signed memory URLs
# ═══════════════════════════════════════════════════════════════════════════
# The in-memory store cannot speak HTTP, so its "presigned URL" is a
# first-class signed bearer token that the same process can later perform
# through ``perform_presigned_put/get``.  This lets local/dev/tests exercise
# the full signed-transfer contract (unforgeable scope, expiry, tenant binding)
# without AWS.  A URL is ``aether-memory-<put|get>://local/<key>?<sig>`` where
# the HMAC-SHA256 signature covers ``version|tenant_id|object_key|method|
# expires_at`` under a process secret — a URL cannot be re-targeted to another
# tenant, object, verb, or window without invalidating the signature.

_PRESIGN_MEMORY_PUT_PREFIX = "aether-memory-put://local/"
_PRESIGN_MEMORY_GET_PREFIX = "aether-memory-get://local/"
_PRESIGN_VERSION = "1"


def _memory_presign_secret() -> bytes:
    secret = (
        os.environ.get("AETHER_OBJECT_STORE_PRESIGN_SECRET")
        or os.environ.get("JWT_SECRET")
        or "aether-local-object-store-presign"
    )
    return secret.encode("utf-8")


def _sign_payload(
    *,
    tenant_id: str,
    object_key: str,
    method: str,
    expires_at: str,
) -> str:
    return f"{_PRESIGN_VERSION}|{tenant_id}|{object_key}|{method}|{expires_at}"


def _sign_transfer(*, tenant_id: str, object_key: str, method: str, expires_at: str) -> str:
    payload = _sign_payload(
        tenant_id=tenant_id,
        object_key=object_key,
        method=method,
        expires_at=expires_at,
    )
    return hmac.new(
        _memory_presign_secret(), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def _build_memory_presigned_url(
    prefix: str,
    object_key: str,
    *,
    tenant_id: str,
    method: str,
    expires_at: str,
) -> PresignedTransfer:
    signature = _sign_transfer(
        tenant_id=tenant_id, object_key=object_key, method=method, expires_at=expires_at
    )
    query = urlencode(
        {
            "x-aether-presign": _PRESIGN_VERSION,
            "x-aether-tenant": tenant_id,
            "x-aether-expires": expires_at,
            "x-aether-sig": signature,
        }
    )
    url = f"{prefix}{quote(object_key, safe='')}?{query}"
    return PresignedTransfer(
        url=url,
        method=method,
        headers={},
        expires_at=expires_at,
        token=signature,
    )


def _resolve_memory_presigned_url(
    url: str,
    *,
    prefix: str,
    method: str,
    now: datetime,
) -> str:
    """Validate a memory presigned URL and return its bound object key.

    Raises ``ValueError`` on an unrecognized scheme, a signature mismatch
    (tampered / foreign / re-targeted), or an expired window — so a signed
    URL can never be re-targeted to a different object, tenant, or time.
    """
    if not isinstance(url, str) or not url.startswith(prefix):
        raise ValueError("unrecognized presigned transfer URL")
    parts = urlsplit(url)
    object_key = unquote(parts.path.lstrip("/"))
    query = parse_qs(parts.query)
    tenant_id = query.get("x-aether-tenant", [""])[0]
    expires_at = query.get("x-aether-expires", [""])[0]
    signature = query.get("x-aether-sig", [""])[0]
    expected = _sign_transfer(
        tenant_id=tenant_id, object_key=object_key, method=method, expires_at=expires_at
    )
    if not signature or not hmac.compare_digest(expected, signature):
        raise ValueError("presigned transfer URL signature mismatch (tampered or foreign)")
    if not object_key:
        raise ValueError("presigned transfer URL has an empty object key")
    try:
        expires_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError as exc:  # pragma: no cover - malformed internal URL
        raise ValueError("presigned transfer URL has an invalid expiry") from exc
    if now >= expires_dt:
        raise ValueError("presigned transfer URL has expired")
    return object_key


# ═══════════════════════════════════════════════════════════════════════════
# IN-MEMORY IMPLEMENTATION — local / dev / tests
# ═══════════════════════════════════════════════════════════════════════════

class InMemoryObjectStore:
    """Dict-backed object store for local/dev/tests. Thread-safe."""

    def __init__(
        self,
        *,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self._objects: dict[str, bytes] = {}
        self._lock = threading.Lock()
        self._clock = clock

    def _now(self) -> datetime:
        if self._clock is not None:
            return self._clock()
        return datetime.now(timezone.utc)

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

    # ── presigned-transfer capability (HMAC-signed memory URLs) ──────────

    def create_presigned_put_url(
        self,
        object_key: str,
        *,
        tenant_id: str,
        expires_in_seconds: int = 900,
    ) -> PresignedTransfer:
        if not object_key:
            raise ValueError("object key must be non-empty")
        if int(expires_in_seconds) <= 0:
            raise ValueError("expires_in_seconds must be positive")
        expires_at = self._now() + timedelta(seconds=int(expires_in_seconds))
        return _build_memory_presigned_url(
            _PRESIGN_MEMORY_PUT_PREFIX,
            object_key,
            tenant_id=tenant_id,
            method="PUT",
            expires_at=expires_at.isoformat(),
        )

    def create_presigned_get_url(
        self,
        object_key: str,
        *,
        tenant_id: str,
        expires_in_seconds: int = 300,
    ) -> PresignedTransfer:
        if not object_key:
            raise ValueError("object key must be non-empty")
        if int(expires_in_seconds) <= 0:
            raise ValueError("expires_in_seconds must be positive")
        expires_at = self._now() + timedelta(seconds=int(expires_in_seconds))
        return _build_memory_presigned_url(
            _PRESIGN_MEMORY_GET_PREFIX,
            object_key,
            tenant_id=tenant_id,
            method="GET",
            expires_at=expires_at.isoformat(),
        )

    def perform_presigned_put(self, presigned_url: str, data: bytes) -> str:
        """Simulate the external ``PUT`` a client performs against a signed URL.

        Validates signature + expiry, then writes exactly the bound object key.
        Returns the resolved object key.
        """
        object_key = _resolve_memory_presigned_url(
            presigned_url,
            prefix=_PRESIGN_MEMORY_PUT_PREFIX,
            method="PUT",
            now=self._now(),
        )
        self.put(object_key, bytes(data))
        return object_key

    def perform_presigned_get(self, presigned_url: str) -> bytes:
        """Simulate the external ``GET`` a client performs against a signed URL."""
        object_key = _resolve_memory_presigned_url(
            presigned_url,
            prefix=_PRESIGN_MEMORY_GET_PREFIX,
            method="GET",
            now=self._now(),
        )
        return self.get(object_key)

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

    # ── presigned-transfer capability (AWS SigV4 query-param URLs) ────────

    def create_presigned_put_url(
        self,
        object_key: str,
        *,
        tenant_id: str,
        expires_in_seconds: int,
    ) -> PresignedTransfer:
        """Short-TTL presigned ``PUT`` for one object.

        The tenant binding is the object key itself — the key scheme
        (``data-exchange/<tenant_id>/...``) embeds the tenant as the first
        segment, so a signed URL can only ever address that tenant's object.
        """
        if not object_key:
            raise ValueError("object key must be non-empty")
        if int(expires_in_seconds) <= 0:
            raise ValueError("expires_in_seconds must be positive")
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in_seconds))
        url = self._s3().generate_presigned_url(
            "put_object",
            Params={"Bucket": self.bucket, "Key": self._full_key(object_key)},
            ExpiresIn=int(expires_in_seconds),
        )
        return PresignedTransfer(
            url=url,
            method="PUT",
            headers={},
            expires_at=expires_at.isoformat(),
            token=None,
        )

    def create_presigned_get_url(
        self,
        object_key: str,
        *,
        tenant_id: str,
        expires_in_seconds: int,
    ) -> PresignedTransfer:
        """Short-TTL presigned ``GET`` for one object (see put-url note on
        tenant binding — the key carries the tenant scope)."""
        if not object_key:
            raise ValueError("object key must be non-empty")
        if int(expires_in_seconds) <= 0:
            raise ValueError("expires_in_seconds must be positive")
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in_seconds))
        url = self._s3().generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": self._full_key(object_key)},
            ExpiresIn=int(expires_in_seconds),
        )
        return PresignedTransfer(
            url=url,
            method="GET",
            headers={},
            expires_at=expires_at.isoformat(),
            token=None,
        )


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
