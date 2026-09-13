"""``CredentialService`` — the runtime / Kyber control-plane credential facade.

ADR-008 D5. A thin, resolver-agnostic surface over a
:class:`~services.model_runtime.credentials.interface.ProviderCredentialResolver`
that the model runtime and the Kyber control plane call to:

* resolve a provider credential at call time (masked, secret-free),
* list masked credential metadata,
* trigger rotation / revocation through the source + rotation orchestrator.

Security contract (binding, ADR-008 D5):

* Only masked, secret-free metadata ever leaves this facade. Raw keys never
  appear in any return value, ``describe()``, or log line here.
* Resolution is fail-closed behind a D9 feature gate that is **OFF by default**:
  when disabled, ``resolve`` returns a ``configured=False`` resolution without
  touching any backend.
* Rotation is delegated to the ``RotationOrchestrator`` (which fails closed);
  revocation fails closed to ``False`` rather than surfacing backend errors.
* AWS-backed resolvers (``AwsSecretsCredentialResolver``, which stores its
  backend as ``_backend``) are adapted to the :class:`CredentialSource` seam by
  :class:`~services.model_runtime.credentials.aws_source.AwsCredentialSource`,
  so listing, revocation, and rotation operate against the real AWS store.
"""

from __future__ import annotations

import inspect
from typing import Any, Callable

from services.model_runtime.credentials.interface import ProviderCredentialResolver
from services.model_runtime.credentials.models import (
    CredentialResolution,
    CredentialResolverError,
    ResolverConfig,
    assert_no_raw_secrets,
)
from services.model_runtime.credentials.rotation import RotationPolicy
from shared.credentials.interface import CredentialMetadata

_DISABLED_REASON = "credential resolution disabled"


async def _maybe_await(value: Any) -> Any:
    """Await ``value`` when it is a coroutine, otherwise pass it through."""
    if inspect.isawaitable(value):
        return await value
    return value


class CredentialService:
    """Facade over a provider credential resolver (masked, secret-free)."""

    def __init__(
        self,
        resolver: ProviderCredentialResolver,
        *,
        rotation_policy: RotationPolicy | None = None,
        config: ResolverConfig | None = None,
        aws_rotate_replacement: Callable[[str, str], Any] | None = None,
    ) -> None:
        self._resolver = resolver
        self._rotation_policy = rotation_policy
        # D9 feature gate defaults OFF (ResolverConfig.enabled=False).
        self._config = config if config is not None else ResolverConfig()
        # Cached lifecycle adapter for backend-backed (AWS) resolvers.
        self._aws_source: Any = None
        # Replacement-credential provider for AWS rotation (see aws_source.py);
        # ``None`` makes AWS rotation fail closed rather than write a synthetic
        # secret. Never logged or surfaced.
        self._aws_rotate_replacement = aws_rotate_replacement

    # -- resolver internals -------------------------------------------------

    def _source(self) -> Any:
        """The underlying credential source the resolver wraps, if any.

        Resolvers exposing ``source``/``_source`` return it directly.
        :class:`~services.model_runtime.credentials.aws_secrets.AwsSecretsCredentialResolver`
        stores its ``CredentialBackendLike`` as ``_backend`` instead, so this
        facade adapts it to the :class:`CredentialSource` seam — otherwise
        ``list_metadata``/``revoke``/``rotate`` would silently degrade (empty
        list, ``False``, and an orchestrator with a ``None`` source).
        """
        source = _attr_any(self._resolver, "source", "_source")
        if source is not None:
            return source
        if self._aws_source is None:
            self._aws_source = self._build_aws_source()
        return self._aws_source

    def _build_aws_source(self) -> Any:
        """Build the AWS lifecycle adapter for an AWS-backed resolver, if any."""
        from services.model_runtime.credentials.aws_secrets import (
            AwsSecretsCredentialResolver,
        )
        from services.model_runtime.credentials.aws_source import AwsCredentialSource

        if not isinstance(self._resolver, AwsSecretsCredentialResolver):
            return None
        return AwsCredentialSource(
            self._resolver,
            rotate_replacement_factory=self._aws_rotate_replacement,
        )

    def _cache(self) -> Any:
        """The resolver's credential cache, if any."""
        return _attr_any(self._resolver, "cache", "_cache")

    # -- resolution ---------------------------------------------------------

    async def resolve(self, tenant_id: str, provider: str) -> CredentialResolution:
        """Resolve the provider credential for ``tenant_id`` at call time.

        Fail-closed feature gate (D9, default OFF): when the resolver is not
        enabled, return a ``configured=False`` resolution instead of touching
        any backend. Otherwise delegate to the resolver.
        """
        if not self._config.enabled:
            return CredentialResolution(
                provider=provider,
                tenant_id=tenant_id,
                ref=f"disabled:{provider}:{tenant_id}",
                resolved=False,
                configured=False,
                source="none",
                reason=_DISABLED_REASON,
            )
        return await _maybe_await(self._resolver.resolve(tenant_id, provider))

    async def list_metadata(self, tenant_id: str) -> list[CredentialMetadata]:
        """List masked, secret-free metadata for ``tenant_id``.

        Delegates to the underlying source when it exposes a list surface;
        returns an empty list otherwise. The result is guarded so raw secret
        material can never cross this boundary (fail closed with
        :class:`CredentialUnsafe`).
        """
        source = self._source()
        if source is None:
            return []
        lst = getattr(source, "list", None)
        if not callable(lst):
            lst = getattr(source, "list_metadata", None)
        if not callable(lst):
            return []
        items = await _maybe_await(lst(tenant_id))
        items = list(items or [])
        assert_no_raw_secrets(repr(items))
        return items

    async def rotate(self, tenant_id: str, ref: str) -> CredentialMetadata | None:
        """Rotate ``ref`` when a rotation policy is configured, else ``None``.

        Delegates to :class:`RotationOrchestrator` (source + cache + policy),
        which issues a new masked version and invalidates the cache only after a
        successful source rotation.
        """
        if self._rotation_policy is None:
            return None
        from services.model_runtime.credentials.rotation import RotationOrchestrator

        orchestrator = RotationOrchestrator(
            self._source(),
            self._cache(),
            policy=self._rotation_policy,
        )
        return await orchestrator.rotate(tenant_id, ref)

    async def revoke(self, tenant_id: str, ref: str) -> bool:
        """Revoke ``ref`` through the underlying source (fail closed).

        Returns ``False`` when the source exposes no revoke surface or reports
        failure. ``CredentialResolverError`` is swallowed so revocation fails
        closed rather than surfacing raw backend errors. On success the cache
        is invalidated so a revoked credential is never served.
        """
        source = self._source()
        if source is None:
            return False
        revoke = getattr(source, "revoke", None)
        if not callable(revoke):
            return False
        try:
            revoked = bool(await _maybe_await(revoke(tenant_id, ref)))
        except CredentialResolverError:
            return False
        if revoked:
            cache = self._cache()
            invalidate = getattr(cache, "invalidate", None)
            if callable(invalidate):
                await _maybe_await(invalidate(tenant_id, ref))
        return revoked

    async def health(self) -> bool:
        """Delegate to the resolver's health check."""
        return bool(await _maybe_await(self._resolver.health()))

    def describe(self) -> str:
        """Audit-safe one-liner: resolver, gate, backend — never secrets."""
        line = (
            "CredentialService(resolver=%s, enabled=%s, backend=%s, rotation=%s)"
            % (
                type(self._resolver).__name__,
                self._config.enabled,
                self._config.backend,
                "on" if self._rotation_policy is not None else "off",
            )
        )
        assert_no_raw_secrets(line)
        return line


def _attr_any(obj: Any, *names: str) -> Any:
    """Return the first non-``None`` attribute among ``names`` on ``obj``."""
    for name in names:
        value = getattr(obj, name, None)
        if value is not None:
            return value
    return None


__all__ = ["CredentialService"]
