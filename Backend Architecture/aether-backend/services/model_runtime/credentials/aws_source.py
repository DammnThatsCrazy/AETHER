"""AWS Secrets Manager credential lifecycle adapter (ADR-008 D5).

:class:`~services.model_runtime.credentials.aws_secrets.AwsSecretsCredentialResolver`
stores its ``CredentialBackendLike`` as ``_backend`` — it exposes no
``source``/``_source`` attribute — so ``CredentialService``'s seam lookup
(:meth:`CredentialService._source`) returns ``None`` and the advertised AWS
lifecycle controls silently degrade: ``list_metadata()`` always returns an empty
list, ``revoke()`` always returns ``False``, and rotation builds an orchestrator
whose source is ``None`` and fails.

This module provides :class:`AwsCredentialSource` — a
:class:`~services.model_runtime.credentials.interface.CredentialSource` adapter
over the resolver's backend that makes those controls operate:

* ``list`` / ``load`` read masked, secret-free metadata from the backend
  (``list`` fails closed to ``[]`` on backend error; ``load`` raises
  :class:`CredentialNotResolved` when no secret exists and
  :class:`CredentialBackendUnavailable` on backend error);
* ``revoke`` marks the secret revoked through the backend's
  ``revoke(tenant_id, ref)`` and fails closed to ``False`` on error;
* ``rotate`` writes a replacement credential through the backend's
  ``rotate(tenant_id, ref, credential)`` path. The ``CredentialSource.rotate``
  seam carries no replacement, so the adapter sources one from an explicit
  ``rotate_replacement_factory``; without one it fails closed with
  :class:`CredentialBackendUnavailable` — it never manufactures a secret or
  writes garbage to AWS.

Credential hygiene (binding): no raw secret value is ever returned, logged, or
cached here. Only masked :class:`CredentialMetadata` (or ``bool`` for revoke)
crosses the seam, and every surfaced metadata is guarded by
:func:`assert_no_raw_secrets`.
"""

from __future__ import annotations

import inspect
from typing import Any, Callable

from services.model_runtime.credentials.interface import CredentialSource
from services.model_runtime.credentials.models import (
    CredentialBackendUnavailable,
    CredentialNotResolved,
    CredentialResolverError,
    assert_no_raw_secrets,
)
from shared.credentials.interface import CredentialMetadata

__all__ = ["AwsCredentialSource", "RotationReplacementFactory"]

#: Provides the replacement credential for an AWS rotation: ``(tenant_id, ref)``
#: returns a :class:`~shared.credentials.types.StructuredCredential` or an
#: opaque secret string accepted by ``CredentialBackend.rotate`` (an awaitable is
#: allowed). The returned value flows straight into the backend's documented
#: secret-update path and is never surfaced, logged, or cached by the adapter.
RotationReplacementFactory = Callable[[str, str], Any]


class AwsCredentialSource:
    """Adapts an ``AwsSecretsCredentialResolver`` to the ``CredentialSource`` seam.

    Reads the resolver's ``_backend`` (the ``CredentialBackendLike``) so the
    facade's list / revoke / rotate controls operate against the real AWS-backed
    store. Rotation requires an explicit replacement provider; without one it
    fails closed rather than overwriting a live secret with synthetic material.
    """

    def __init__(
        self,
        resolver: Any,
        *,
        rotate_replacement_factory: RotationReplacementFactory | None = None,
    ) -> None:
        self._resolver = resolver
        backend = getattr(resolver, "_backend", None)
        if backend is None:
            raise CredentialBackendUnavailable(
                "aws credential source requires a backend-backed resolver"
            )
        self._backend = backend
        self._rotate_replacement_factory = rotate_replacement_factory

    # ── CredentialSource seam ───────────────────────────────────────────────

    async def load(self, tenant_id: str, ref: str) -> CredentialMetadata:
        """Return masked metadata for ``ref``, fail-closed on absence/error.

        ``CredentialNotResolved`` signals a reached-but-empty backend (mirroring
        the resolver's "no aws secret"); backend failures raise
        :class:`CredentialBackendUnavailable` so callers never conflate "empty"
        with "unavailable" (which could otherwise fall through to env).
        """
        try:
            meta = await self._backend.metadata(tenant_id, ref)
        except CredentialResolverError:
            raise
        except Exception as exc:
            raise CredentialBackendUnavailable(
                f"aws backend unavailable for tenant={tenant_id!r} ref={ref!r}"
            ) from exc
        if meta is None:
            raise CredentialNotResolved(
                f"no aws secret for tenant={tenant_id!r} ref={ref!r}"
            )
        assert_no_raw_secrets(repr(meta))
        return meta

    async def rotate(self, tenant_id: str, ref: str) -> CredentialMetadata:
        """Rotate ``ref`` with a replacement credential (fail closed otherwise).

        The ``CredentialSource.rotate`` seam carries no replacement credential,
        so the adapter obtains one from ``rotate_replacement_factory`` and passes
        it through the backend's documented ``rotate(tenant_id, ref, credential)``
        secret-update path. When no factory is configured, or it yields no
        replacement, rotation fails closed with
        :class:`CredentialBackendUnavailable` — nothing is written.
        """
        replacement = await self._replacement(tenant_id, ref)
        try:
            meta = await self._backend.rotate(tenant_id, ref, replacement)
        except CredentialBackendUnavailable:
            raise
        except Exception as exc:
            raise CredentialBackendUnavailable(
                f"aws credential rotation failed for tenant={tenant_id!r} ref={ref!r}"
            ) from exc
        assert_no_raw_secrets(repr(meta))
        return meta

    async def revoke(self, tenant_id: str, ref: str) -> bool:
        """Revoke ``ref`` through the backend; fail closed to ``False`` on error."""
        try:
            return bool(await self._backend.revoke(tenant_id, ref))
        except Exception:
            return False

    # ── list surface (CredentialService.list_metadata delegation) ───────────

    async def list(self, tenant_id: str) -> list[CredentialMetadata]:
        """Return masked metadata for every secret owned by ``tenant_id``.

        Fails closed to an empty list on backend error — never leaks a secret
        and never raises into the facade.
        """
        try:
            items = await self._backend.list(tenant_id)
        except Exception:
            return []
        items = list(items or [])
        assert_no_raw_secrets(repr(items))
        return items

    # ── helpers ─────────────────────────────────────────────────────────────

    async def _replacement(self, tenant_id: str, ref: str) -> Any:
        """Resolve the replacement credential for a rotation, fail-closed.

        Returns the (awaitable-resolved) value from ``rotate_replacement_factory``
        or raises :class:`CredentialBackendUnavailable`. The value is passed
        straight to the backend and never crosses any masked surface.
        """
        factory = self._rotate_replacement_factory
        if factory is None:
            raise CredentialBackendUnavailable(
                "aws credential rotation requires a rotate_replacement_factory; "
                "none configured — rotation fails closed"
            )
        try:
            value = factory(tenant_id, ref)
            if inspect.isawaitable(value):
                value = await value
        except CredentialBackendUnavailable:
            raise
        except Exception as exc:
            raise CredentialBackendUnavailable(
                f"aws rotation replacement unavailable for tenant={tenant_id!r} ref={ref!r}"
            ) from exc
        if value is None:
            raise CredentialBackendUnavailable(
                f"aws rotation replacement unavailable for tenant={tenant_id!r} ref={ref!r}"
            )
        return value
