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
3. **Env fallback (tenant-scoped only)** — when the *per-tenant* env ref
   ``{TENANT_ID}_{PROVIDER}_API_KEY`` is set, resolves as ``configured=True``
   (source=``"env"``) with a masked ``"****"+last4(sha256(value))`` identifier —
   never the value itself. The ref embeds the tenant, so a missing per-tenant
   key can never resolve to another tenant's key or the operator's global key
   (cross-tenant credential use is impossible by construction). Both
   identifiers are constrained to ``[A-Z0-9-]`` (see
   :meth:`_tenant_env_ref`) so a tenant/provider containing ``_`` can never
   forge a differently-split ref pair — the fallback fails closed to
   ``source="none"`` instead.
4. **Otherwise** — ``configured=False, resolved=True, source="none"`` with reason
   ``"no credential configured for provider"``.

Fail-closed: any *other* source exception (backend unreachable/misconfigured)
yields ``configured=False`` with reason ``"backend unavailable"`` — the resolver
never crashes and never falls back to env on a backend error (which could leak
or bypass policy).

Revoked/expired metadata is rejected outright: a credential whose status is
``DISABLED`` (revoked) or ``DEGRADED`` (expired), or whose ``expires_at`` has
passed, raises :class:`CredentialUnusable` — it is never returned as usable and
never falls back to the env path (which could bypass the revocation).
"""

from __future__ import annotations

import inspect
import os
import re
from datetime import datetime, timezone
from typing import Literal, Optional

from shared.certification.readiness import CredentialReadiness
from services.model_runtime.credentials.interface import (
    CredentialCache,
    CredentialSource,
    NoopCredentialSource,
)
from services.model_runtime.credentials.models import (
    CredentialNotResolved,
    CredentialResolution,
    CredentialResolverError,
    mask_identifier,
)

__all__ = [
    "ByokCredentialResolver",
    "CredentialCache",
    "CredentialNotResolved",
    "CredentialResolution",
    "CredentialResolverError",
    "CredentialSource",
    "CredentialUnusable",
    "NoopCredentialSource",
]


class CredentialUnusable(CredentialResolverError):
    """Raised when a stored credential is not usable (DISABLED/DEGRADED/expired).

    Fail-closed: a revoked or expired credential must never resolve as usable.
    Raising (rather than returning ``configured=False``) prevents any caller
    from treating it as a missing credential and falling back to env, which
    would bypass the revocation.
    """


class ByokCredentialResolver:
    """Resolves per-tenant LLM credentials from cache, secret backend, then env.

    ``env_credential_ref`` is the *name* of the retained, operator-facing env
    var (never the key value) — kept for health/protocol tooling and no longer
    served to tenant resolution. The resolve-time env path keys on a
    **tenant-scoped** ref (``{TENANT}_{PROVIDER}_API_KEY``) so one tenant can
    never resolve another tenant's or the operator's global key. The value
    never appears in any resolution, log, or prompt.
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
        """True when the retained global ``env_credential_ref`` is set.

        Operator/health-facing only — this no longer gates tenant resolution,
        which keys on a per-tenant ref (see :meth:`resolve`). Presence-only
        check; the value is never read into a model.
        """
        return bool(os.getenv(self._env_credential_ref))

    #: Allowed identifier charset for the per-tenant env ref. ``_`` (and any
    #: other separator-looking character) is excluded so the ref cannot be
    #: forged by concatenation: without this, a tenant ``a_b`` + provider
    #: ``openai`` would construct the same ref as tenant ``a`` + provider
    #: ``b_openai`` (cross-tenant/cross-provider key reach).
    _ENV_REF_IDENTIFIER_RE = re.compile(r"^[A-Z0-9-]+$")

    @staticmethod
    def _tenant_env_ref(tenant_id: str, provider: str) -> str | None:
        """Per-tenant env ref: ``{TENANT_ID}_{PROVIDER}_API_KEY``.

        Returns ``None`` when either identifier contains a character outside
        ``[A-Z0-9-]`` — the env fallback then fails closed instead of
        resolving to another tenant's or provider's key.
        """
        tenant = tenant_id.upper()
        provider_ref = provider.upper()
        if not (
            ByokCredentialResolver._ENV_REF_IDENTIFIER_RE.fullmatch(tenant)
            and ByokCredentialResolver._ENV_REF_IDENTIFIER_RE.fullmatch(
                provider_ref
            )
        ):
            return None
        return f"{tenant}_{provider_ref}_API_KEY"

    async def resolve(self, tenant_id: str, provider: str) -> CredentialResolution:
        """Resolve a per-tenant provider credential at call time (masked only)."""
        ref = f"llm/{provider}"

        # 1. Cache hit -> configured, from secret-backend provenance. A cached
        #    revoked/expired credential is rejected (never served as usable).
        if self._cache is not None:
            cached = await self._cache.get(tenant_id, ref)
            if cached is not None:
                self._reject_unusable(cached)
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
            # Fail closed on revoked/expired metadata before it can be cached or
            # returned as usable.
            self._reject_unusable(meta)
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

        # 3. Env fallback — tenant-scoped only. The ref embeds the tenant and
        #    provider, so a missing per-tenant key can never resolve to another
        #    tenant's (or the operator's global) key: cross-tenant credential
        #    use (IDOR) is impossible by construction.
        tenant_ref = self._tenant_env_ref(tenant_id, provider)
        value = os.getenv(tenant_ref) if tenant_ref is not None else None
        if value:
            return self._resolution(
                tenant_id,
                provider,
                tenant_ref,
                configured=True,
                source="env",
                masked=mask_identifier(value),
                reason="tenant-scoped env fallback",
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

    @staticmethod
    def _reject_unusable(meta) -> None:
        """Fail closed on revoked/expired credential metadata.

        ``CredentialReadiness.DISABLED`` (revoked) and ``DEGRADED`` (expired)
        are off-ramp states that must never yield a usable credential. An
        aware ``expires_at`` in the past is rejected even when the status
        snapshot predates the expiry. Raises :class:`CredentialUnusable`.
        """
        status = getattr(meta, "status", None)
        if status in (CredentialReadiness.DISABLED, CredentialReadiness.DEGRADED):
            raise CredentialUnusable(
                f"credential {meta.ref!r} is not usable (status={status.value})"
            )
        exp = getattr(meta, "expires_at", None)
        if exp is not None and exp.tzinfo is not None:
            if datetime.now(timezone.utc) >= exp:
                raise CredentialUnusable(f"credential {meta.ref!r} is expired")

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
