"""Per-tenant credential resolution seam for the model runtime (ADR-008 D5).

This module defines the *interface* for resolving per-tenant LLM credentials at
call time through the existing ``shared.credentials.CredentialBackend``
platform. The data shapes (:class:`CredentialResolution`, :class:`ResolverConfig`,
and the error hierarchy) live in :mod:`services.model_runtime.credentials.models`
and are owned by the models team; this seam only composes them.

Security contract (MUST NOT violate):
- The resolver protocol never returns raw secrets — every read surfaces only a
  masked, secret-free :class:`CredentialResolution`.
- :class:`CredentialCache` stores only :class:`CredentialMetadata`, which is
  secret-free by construction — raw keys never enter the cache.
- No logging of keys, refs-with-secrets, or any secret material on this seam.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

from shared.credentials.interface import (
    STATUS_ACTIVE,
    STATUS_REVOKED,
    CredentialMetadata,
    make_metadata,
)
from services.model_runtime.credentials.models import (
    CredentialNotResolved,
    CredentialResolution,
)

__all__ = [
    "CredentialCache",
    "CredentialSource",
    "NoopCredentialSource",
    "ProviderCredentialResolver",
]


@runtime_checkable
class ProviderCredentialResolver(Protocol):
    """Structural contract for a per-provider credential resolver.

    Implementations resolve a per-tenant credential for ``provider`` at call
    time and return a masked :class:`CredentialResolution`. The protocol never
    exposes plaintext secrets.

    - :meth:`is_configured` is a synchronous, env-gated fast path: it checks
      whether ``provider`` can be served from process env before any async
      backend work.
    - :meth:`resolve` may hit the secret backend + cache.
    - :meth:`health` reports backend liveness for circuit breakers.
    """

    def is_configured(self, provider: str) -> bool: ...

    async def resolve(self, tenant_id: str, provider: str) -> CredentialResolution: ...

    async def health(self) -> bool: ...


@runtime_checkable
class CredentialSource(Protocol):
    """Adapter seam over ``shared.credentials.CredentialBackend``.

    A source knows how to load / rotate / revoke a stored credential by its
    opaque ``ref``. Every operation returns masked :class:`CredentialMetadata`
    (or ``bool`` for :meth:`revoke`) — plaintext never crosses this seam.
    """

    async def load(self, tenant_id: str, ref: str) -> CredentialMetadata: ...

    async def rotate(self, tenant_id: str, ref: str) -> CredentialMetadata: ...

    async def revoke(self, tenant_id: str, ref: str) -> bool: ...


class CredentialCache:
    """In-memory, TTL-bounded cache of masked credential metadata.

    Thread-safe under an :class:`asyncio.Lock`. Stores only
    :class:`CredentialMetadata` (secret-free by construction) — raw secrets
    never enter this cache. Entries expire ``ttl_seconds`` after insertion and
    are lazily evicted on read.
    """

    def __init__(self, ttl_seconds: int = 60) -> None:
        self._ttl_seconds = ttl_seconds
        self._lock = asyncio.Lock()
        # key -> (monotonic expiry, metadata)
        self._entries: dict[tuple[str, str], tuple[float, CredentialMetadata]] = {}

    async def get(self, tenant_id: str, ref: str) -> CredentialMetadata | None:
        """Return the cached metadata, or ``None`` on miss / TTL expiry."""
        key = (tenant_id, ref)
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            expires_at, meta = entry
            if time.monotonic() >= expires_at:
                del self._entries[key]
                return None
            return meta

    async def put(self, meta: CredentialMetadata) -> None:
        """Insert ``meta`` under its own ``(tenant_id, ref)`` key."""
        key = (meta.tenant_id, meta.ref)
        async with self._lock:
            self._entries[key] = (time.monotonic() + self._ttl_seconds, meta)

    async def invalidate(self, tenant_id: str, ref: str) -> None:
        """Drop any cached entry for ``(tenant_id, ref)`` (no-op if absent)."""
        key = (tenant_id, ref)
        async with self._lock:
            self._entries.pop(key, None)


class NoopCredentialSource:
    """In-memory test double for :class:`CredentialSource`.

    Seeds its store from ``initial`` (or via :meth:`put`) and never touches a
    real backend. Unknown refs raise :class:`CredentialNotResolved`;
    :meth:`health` is always ``True``. Safe for every team's tests.
    """

    def __init__(
        self,
        initial: dict[tuple[str, str], CredentialMetadata] | None = None,
    ) -> None:
        self._store: dict[tuple[str, str], CredentialMetadata] = dict(initial or {})

    def put(self, tenant_id: str, ref: str, meta: CredentialMetadata) -> None:
        """Seed a credential without going through the backend."""
        self._store[(tenant_id, ref)] = meta

    async def load(self, tenant_id: str, ref: str) -> CredentialMetadata:
        try:
            return self._store[(tenant_id, ref)]
        except KeyError:
            raise CredentialNotResolved(
                f"no credential stored for tenant={tenant_id!r} ref={ref!r}"
            ) from None

    async def rotate(self, tenant_id: str, ref: str) -> CredentialMetadata:
        meta = self._store.get((tenant_id, ref))
        if meta is None:
            raise CredentialNotResolved(
                f"cannot rotate unknown credential tenant={tenant_id!r} ref={ref!r}"
            )
        now = datetime.now(timezone.utc)
        rotated = make_metadata(
            tenant_id=meta.tenant_id,
            ref=meta.ref,
            credential_type=meta.credential_type,
            version=meta.version + 1,
            lifecycle_status=STATUS_ACTIVE,
            masked_identifier=meta.masked_identifier,
            created_at=meta.created_at,
            updated_at=now,
            rotated_at=now,
            expires_at=meta.expires_at,
            extra=meta.metadata,
        )
        self._store[(tenant_id, ref)] = rotated
        return rotated

    async def revoke(self, tenant_id: str, ref: str) -> bool:
        meta = self._store.get((tenant_id, ref))
        if meta is None:
            raise CredentialNotResolved(
                f"cannot revoke unknown credential tenant={tenant_id!r} ref={ref!r}"
            )
        now = datetime.now(timezone.utc)
        revoked = make_metadata(
            tenant_id=meta.tenant_id,
            ref=meta.ref,
            credential_type=meta.credential_type,
            version=meta.version,
            lifecycle_status=STATUS_REVOKED,
            masked_identifier=meta.masked_identifier,
            created_at=meta.created_at,
            updated_at=now,
            rotated_at=meta.rotated_at,
            revoked_at=now,
            expires_at=meta.expires_at,
            extra=meta.metadata,
        )
        self._store[(tenant_id, ref)] = revoked
        return True

    async def health(self) -> bool:
        return True
