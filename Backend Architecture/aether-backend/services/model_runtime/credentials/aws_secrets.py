"""AWS Secrets Manager credential resolver for the model-runtime harness.

Per-tenant LLM credentials are stored through the existing ``CredentialBackend``
abstraction; production uses ``AwsSecretsManagerCredentialBackend`` scoped to
``aether/credentials/{tenant_id}/{ref}`` (ADR-008 D5). This module provides the
model_runtime-side, provider-free resolver over any object satisfying
:class:`CredentialBackendLike` — it never imports the concrete AWS backend and
never fetches or returns raw secret payloads (only masked
``CredentialMetadata`` is read from the backend).

Fail-closed by construction: when AWS is not configured, the region env var is
absent, the backend is unhealthy/raising, a resolution misses, or the stored
metadata is revoked/expired, ``resolve`` returns a ``CredentialResolution`` with
``configured=False`` — it never raises and never leaks secret material.
Revoked/expired metadata (``DISABLED``/``DEGRADED`` readiness, or an aware
``expires_at`` in the past) is rejected before it can be cached or reported as
serviceable, mirroring :meth:`ByokCredentialResolver`'s rejection semantics.
"""

from __future__ import annotations

import os
import re
import typing
from datetime import datetime, timezone
from typing import Optional

from shared.certification.readiness import CredentialReadiness
from shared.credentials.interface import CredentialBackendHealth, CredentialMetadata
from shared.credentials.types import StructuredCredential

from .interface import CredentialCache
from .models import CredentialResolution, mask_identifier

# A provider/tenant token is an unqualified slug: no path separators, no ``..``,
# no leading dot. Enforcing this keeps the derived ref ``llm/{provider}`` inside
# the ``aether/credentials/{tenant_id}/llm/`` scope — it can never escape it.
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,127}$")

SECRET_PREFIX = "aether/credentials"
REF_PREFIX = "llm"

_REASON_OK = "resolved from aws secrets manager"
_REASON_UNAVAILABLE = "aws backend unavailable"
_REASON_MISSING = "no aws secret"
_REASON_UNSAFE = "invalid provider ref"
_REASON_REVOKED = "aws secret revoked"
_REASON_DEGRADED = "aws secret degraded"
_REASON_EXPIRED = "aws secret expired"


class CredentialBackendLike(typing.Protocol):
    """Minimal async ``CredentialBackend`` surface this resolver needs.

    Matches the corresponding ``shared.credentials.interface.CredentialBackend``
    signatures so the real Secrets Manager (and local/in-memory) backends
    satisfy it, while the resolver stays provider-free and testable with an
    in-memory stub (no AWS SDK required).
    """

    async def get(self, tenant_id: str, ref: str) -> Optional[StructuredCredential]: ...

    async def rotate(
        self, tenant_id: str, ref: str, credential: "StructuredCredential | str"
    ) -> CredentialMetadata: ...

    async def revoke(self, tenant_id: str, ref: str) -> bool: ...

    async def metadata(self, tenant_id: str, ref: str) -> Optional[CredentialMetadata]: ...

    async def list(self, tenant_id: str) -> list[CredentialMetadata]: ...

    async def health_check(self) -> CredentialBackendHealth: ...


class AwsSecretsCredentialResolver:
    """Fail-closed per-tenant LLM credential resolver over a ``CredentialBackend``.

    Resolutions are scoped to ``aether/credentials/{tenant_id}/llm/{provider}``.
    Only masked ``CredentialMetadata`` is read from the backend; the raw secret
    payload is never fetched or returned.
    """

    def __init__(
        self,
        backend: CredentialBackendLike,
        cache: Optional[CredentialCache] = None,
        *,
        aws_region: Optional[str] = None,
    ) -> None:
        self._backend = backend
        self._cache = cache
        self._aws_region = aws_region

    # ── public API ──────────────────────────────────────────────────────────

    def is_configured(self, provider: str) -> bool:
        """True only when an AWS region is set AND the backend reports ready.

        Fail-closed default: without ``AWS_REGION``/``aws_region``, when the
        backend object is missing, when the provider token could escape the
        scope prefix, or when the backend exposes no synchronous readiness
        signal, this is False.
        """
        if not self._region():
            return False
        if self._backend is None:
            return False
        if not self._token_safe(provider):
            return False
        return self._backend_reports_ready()

    def secret_arn_path(self, tenant_id: str, provider: str) -> str:
        """Derive the scoped Secrets Manager name for ``tenant_id``/``provider``.

        Always yields ``aether/credentials/{tenant_id}/llm/{provider}`` and
        raises :class:`ValueError` when either token could escape the
        ``aether/credentials/`` scope prefix.
        """
        if not self._token_safe(tenant_id):
            raise ValueError(f"unsafe tenant_id ref: {tenant_id!r}")
        if not self._token_safe(provider):
            raise ValueError(f"unsafe provider ref: {provider!r}")
        return f"{SECRET_PREFIX}/{tenant_id}/{self._ref_for(provider)}"

    async def resolve(self, tenant_id: str, provider: str) -> CredentialResolution:
        """Resolve masked metadata for ``tenant_id``/``provider`` (fail-closed).

        Never raises on backend failure and never reads the raw secret payload.
        A cached resolution short-circuits the backend entirely. Revoked or
        expired metadata (``DISABLED``/``DEGRADED`` readiness, or an aware
        ``expires_at`` in the past) is rejected before it can be cached or
        reported as ``configured=True`` — it resolves as ``configured=False``.
        """
        if not self._token_safe(tenant_id) or not self._token_safe(provider):
            return self._resolution(
                tenant_id=tenant_id,
                provider=provider,
                resolved=False,
                configured=False,
                source="none",
                reason=_REASON_UNSAFE,
            )

        ref = self._ref_for(provider)
        cached = await self._cache_get(tenant_id, ref)
        if cached is not None:
            # A cached revoked/expired credential must never be served as usable.
            unusable = self._unusable_reason(cached)
            if unusable is not None:
                return self._resolution(
                    tenant_id=tenant_id,
                    provider=provider,
                    resolved=True,
                    configured=False,
                    source="none",
                    reason=unusable,
                )
            return self._resolution_from_metadata(tenant_id, provider, ref, cached)

        if not self._region():
            return self._resolution(
                tenant_id=tenant_id,
                provider=provider,
                resolved=False,
                configured=False,
                source="none",
                reason=_REASON_UNAVAILABLE,
            )

        try:
            metadata = await self._backend.metadata(tenant_id, ref)
        except Exception:
            return self._resolution(
                tenant_id=tenant_id,
                provider=provider,
                resolved=False,
                configured=False,
                source="none",
                reason=_REASON_UNAVAILABLE,
            )
        if metadata is None:
            return self._resolution(
                tenant_id=tenant_id,
                provider=provider,
                resolved=False,
                configured=False,
                source="none",
                reason=_REASON_MISSING,
            )

        # Fail closed on revoked/expired metadata BEFORE it can be cached or
        # returned as usable — never serve a disabled or expired credential.
        unusable = self._unusable_reason(metadata)
        if unusable is not None:
            return self._resolution(
                tenant_id=tenant_id,
                provider=provider,
                resolved=True,
                configured=False,
                source="none",
                reason=unusable,
            )

        await self._cache_put(metadata)
        return self._resolution_from_metadata(tenant_id, provider, ref, metadata)

    async def health(self) -> bool:
        """True when the underlying backend reports healthy."""
        try:
            result = await self._backend.health_check()
        except Exception:
            return False
        return bool(getattr(result, "healthy", False))

    # ── helpers ─────────────────────────────────────────────────────────────

    def _resolution(
        self,
        *,
        tenant_id: str,
        provider: str,
        resolved: bool,
        configured: bool,
        source: str,
        reason: str,
    ) -> CredentialResolution:
        return CredentialResolution(
            provider=provider,
            tenant_id=tenant_id,
            ref=self._ref_for(provider),
            resolved=resolved,
            configured=configured,
            source=source,  # type: ignore[arg-type]
            reason=reason,
        )

    def _resolution_from_metadata(
        self,
        tenant_id: str,
        provider: str,
        ref: str,
        metadata: CredentialMetadata,
    ) -> CredentialResolution:
        return CredentialResolution(
            provider=provider,
            tenant_id=tenant_id,
            ref=ref,
            resolved=True,
            configured=True,
            source="secret_backend",
            masked_identifier=metadata.masked_identifier or mask_identifier(f"{tenant_id}:{ref}"),
            reason=_REASON_OK,
        )

    @staticmethod
    def _unusable_reason(metadata: CredentialMetadata) -> Optional[str]:
        """Fail-closed check for revoked/expired credential metadata.

        Mirrors :meth:`ByokCredentialResolver._reject_unusable`: ``DISABLED``
        (revoked) and ``DEGRADED`` (expired) readiness are off-ramp states that
        must never yield a usable credential, and an aware ``expires_at`` in the
        past is rejected even when the status snapshot predates the expiry.
        Returns a reason string when unusable, ``None`` when usable.
        """
        status = getattr(metadata, "status", None)
        if status == CredentialReadiness.DISABLED:
            return _REASON_REVOKED
        if status == CredentialReadiness.DEGRADED:
            return _REASON_DEGRADED
        exp = getattr(metadata, "expires_at", None)
        if exp is not None and exp.tzinfo is not None and datetime.now(timezone.utc) >= exp:
            return _REASON_EXPIRED
        return None

    def _region(self) -> Optional[str]:
        return self._aws_region or os.getenv("AWS_REGION")

    def _ref_for(self, provider: str) -> str:
        return f"{REF_PREFIX}/{provider}"

    def _token_safe(self, value: str) -> bool:
        return bool(value) and _SAFE_TOKEN.match(value) is not None

    def _backend_reports_ready(self) -> bool:
        backend = self._backend
        if backend is None:
            return False
        sync = getattr(backend, "is_ready", None)
        if callable(sync):
            return bool(sync())
        ready = getattr(backend, "ready", None)
        if ready is not None:
            return bool(ready)
        return False

    async def _cache_get(self, tenant_id: str, ref: str) -> Optional[CredentialMetadata]:
        cache = self._cache
        if cache is None:
            return None
        try:
            return await cache.get(tenant_id, ref)
        except Exception:
            return None

    async def _cache_put(self, metadata: CredentialMetadata) -> None:
        cache = self._cache
        if cache is None:
            return
        try:
            await cache.put(metadata)
        except Exception:
            return


__all__ = [
    "AwsSecretsCredentialResolver",
    "CredentialBackendLike",
    "REF_PREFIX",
    "SECRET_PREFIX",
]
