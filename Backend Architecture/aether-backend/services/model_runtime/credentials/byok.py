"""BYOK (bring-your-own-key) LLM credential resolver (ADR-008 D5).

Tenants/operators supply provider keys via env refs or the existing
``shared.credentials.CredentialBackend`` secret store. The provider client is
constructed at call time from a resolved credential; this module never holds,
logs, prompts, or leaks a plaintext key.

Resolution order (:meth:`ByokCredentialResolver.resolve`):

1. **Cache hit** — a masked :class:`~shared.credentials.interface.CredentialMetadata`
   cached under ``(tenant_id, "llm/{provider}")`` resolves as ``configured=True``
   without touching the source.
2. **Secret backend** — ``source.load(tenant_id, "llm/{provider}")`` resolves as
   ``configured=True`` (source=``"secret_backend"``). A missing credential is
   signalled by :class:`~services.model_runtime.credentials.models.CredentialNotResolved`
   (backend reached, nothing stored) and falls through to env.
3. **Env fallback** — when :meth:`is_configured` is true (the env ref is set),
   resolves as ``configured=True`` (source=``"env"``) with a masked
   ``"****"+last4(sha256(value))`` identifier — never the value itself.
4. **Otherwise** — ``configured=False, resolved=True, source="none"`` with reason
   ``"no credential configured for provider"``.

Fail-closed: any *other* source exception (backend unreachable/misconfigured)
yields ``configured=False`` with reason ``"backend unavailable"`` — the resolver
never crashes and never falls back to env on a backend error (which could leak
or bypass policy).
"""

from __future__ import annotations

import inspect
import os
from datetime import datetime
from typing import Literal, Optional

from services.model_runtime.credentials.interface import (
    CredentialCache,
    CredentialSource,
    NoopCredentialSource,
)
from services.model_runtime.credentials.models import (
    CredentialNotResolved,
    CredentialResolution,
    mask_identifier,
)

__all__ = [
    "ByokCredentialResolver",
    "CredentialCache",
    "CredentialNotResolved",
    "CredentialResolution",
    "CredentialSource",
    "NoopCredentialSource",
]


class ByokCredentialResolver:
    """Resolves per-tenant LLM credentials from cache, secret backend, then env.

    ``env_credential_ref`` is the *name* of the fallback env var (never the key
    value). ``is_configured`` fail-opens the env path only when that ref is set;
    the value never appears in any resolution, log, or prompt.
    """

    def __init__(
        self,
        source: CredentialSource,
        cache: Optional[CredentialCache] = None,
        *,
        env_credential_ref: str = "AETHER_LLM_API_KEY",
    ) -> None:
        self._source = source
        self._cache = cache
        self._env_credential_ref = env_credential_ref

    def is_configured(self, provider: str) -> bool:
        """True when the fallback env ref is set (fail-open only for env path).

        ``provider`` is accepted to keep the surface provider-parameterized; the
        current env path keys on the single configured ``env_credential_ref``.
        Only presence is checked — the value is never read into a model.
        """
        return bool(os.getenv(self._env_credential_ref))

    async def resolve(self, tenant_id: str, provider: str) -> CredentialResolution:
        """Resolve a per-tenant provider credential at call time (masked only)."""
        ref = f"llm/{provider}"

        # 1. Cache hit -> configured, from secret-backend provenance.
        if self._cache is not None:
            cached = await self._cache.get(tenant_id, ref)
            if cached is not None:
                return self._resolution(
                    tenant_id,
                    provider,
                    ref,
                    configured=True,
                    source="secret_backend",
                    masked=cached.masked_identifier,
                    rotated_at=cached.rotated_at,
                    expires_at=cached.expires_at,
                    reason="cached credential",
                )

        # 2. Secret backend. A CredentialNotResolved signal means the backend
        #    was reached but holds nothing for this ref -> try env fallback.
        #    Any other failure is fail-closed: never crash, never leak.
        try:
            meta = await self._source.load(tenant_id, ref)
        except CredentialNotResolved:
            meta = None
        except Exception:
            return self._resolution(
                tenant_id,
                provider,
                ref,
                configured=False,
                source="none",
                reason="backend unavailable",
            )
        if meta is not None:
            if self._cache is not None:
                await self._cache.put(meta)
            return self._resolution(
                tenant_id,
                provider,
                ref,
                configured=True,
                source="secret_backend",
                masked=meta.masked_identifier,
                rotated_at=meta.rotated_at,
                expires_at=meta.expires_at,
                reason="resolved from secret backend",
            )

        # 3. Env fallback (only when the env ref is set).
        if self.is_configured(provider):
            value = os.getenv(self._env_credential_ref)
            if value:
                return self._resolution(
                    tenant_id,
                    provider,
                    self._env_credential_ref,
                    configured=True,
                    source="env",
                    masked=mask_identifier(value),
                    reason="env fallback",
                )

        # 4. No credential configured for this provider.
        return self._resolution(
            tenant_id,
            provider,
            ref,
            configured=False,
            source="none",
            reason="no credential configured for provider",
        )

    async def health(self) -> bool:
        """Report source liveness for circuit breakers.

        Prefers an explicit ``health()`` probe on the source (e.g.
        :class:`NoopCredentialSource`); otherwise falls back to a harmless
        ``load`` round-trip, treating a reached-backend response (including
        ``CredentialNotResolved``) as healthy.
        """
        probe = getattr(self._source, "health", None)
        if callable(probe):
            try:
                result = probe()
                if inspect.isawaitable(result):
                    return bool(await result)
                return bool(result)
            except Exception:
                return False
        try:
            await self._source.load("__aether_health__", "__aether_health__")
            return True
        except CredentialNotResolved:
            return True
        except Exception:
            return False

    def _resolution(
        self,
        tenant_id: str,
        provider: str,
        ref: str,
        *,
        configured: bool,
        source: Literal["env", "secret_backend", "none"],
        masked: Optional[str] = None,
        rotated_at: Optional[datetime] = None,
        expires_at: Optional[datetime] = None,
        reason: str = "",
    ) -> CredentialResolution:
        return CredentialResolution(
            provider=provider,
            tenant_id=tenant_id,
            ref=ref,
            resolved=True,
            configured=configured,
            masked_identifier=masked,
            source=source,
            rotated_at=rotated_at,
            expires_at=expires_at,
            reason=reason,
        )
