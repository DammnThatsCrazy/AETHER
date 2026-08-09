"""Rotation and revocation orchestration for harness credentials (ADR-008 D5).

Builds on the credential contracts in this package:

* ``models.py`` — ``RotationDecision`` and the resolution error hierarchy
  (including :class:`CredentialBackendUnavailable`).
* ``interface.py`` — the :class:`CredentialSource` seam (load / rotate /
  revoke), :class:`CredentialCache`, and the masked ``CredentialMetadata``
  re-exported from ``shared.credentials``.

Security invariants (binding, ADR-008 D5):

* **Decision-only evaluation.** :meth:`RotationOrchestrator.evaluate_all`
  only *decides* whether credentials should rotate. It NEVER rotates — rotation
  is applied explicitly through :meth:`RotationOrchestrator.rotate`.
* **No secret ever crosses this module.** Every value returned is a masked,
  secret-free ``CredentialMetadata`` or a ``RotationDecision``; raw keys are
  never accepted, returned, logged, or cached here.
* **Fail closed on revocation.** A failed revocation reports ``False`` and
  leaves the cache untouched, so the (possibly still-active) credential is not
  accidentally dropped from the resolution path while the source is degraded.
* **Rotated credentials are re-resolved, never reused in-flight.** After a
  rotation the runtime must re-resolve the credential from the source; this
  module never hands a rotated credential to a call that was already in flight.
  The cache is invalidated so no stale entry is served.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from typing import Protocol

from services.model_runtime.credentials.interface import CredentialCache, CredentialSource
from services.model_runtime.credentials.models import (
    CredentialBackendUnavailable,
    RotationDecision,
)
from shared.credentials.interface import CredentialMetadata

__all__ = [
    "ExpiryBasedRotationPolicy",
    "RotationOrchestrator",
    "RotationPolicy",
]


def _aware_utc(value: datetime) -> datetime:
    """Normalize to an aware UTC datetime (naive input is assumed UTC)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class RotationPolicy(Protocol):
    """Decides whether a stored credential should rotate.

    Implementations return a :class:`RotationDecision` — a pure, recordable
    fact. They must never mutate state or rotate anything themselves; rotation
    is applied only through :class:`RotationOrchestrator`.
    """

    async def evaluate(self, meta: CredentialMetadata) -> RotationDecision:
        """Return the rotation decision for ``meta``."""


class ExpiryBasedRotationPolicy:
    """Rotate when a credential is stale by age or within grace of expiry.

    A credential rotates when either condition holds:

    * ``max_age_seconds`` is set and the credential's last modification
      (``updated_at``, falling back to ``created_at``) is older than
      ``max_age_seconds``; or
    * ``expires_at`` is set and falls within ``grace_seconds`` of the clock
      (inclusive; an already-expired credential therefore also rotates).

    Deterministic: pass ``now`` to :meth:`evaluate` to pin the clock; without
    it the current UTC time is used.
    """

    def __init__(
        self,
        *,
        max_age_seconds: int | None = None,
        grace_seconds: int = 300,
    ) -> None:
        if max_age_seconds is not None and max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be > 0 when set")
        if grace_seconds < 0:
            raise ValueError("grace_seconds must be >= 0")
        self._max_age = timedelta(seconds=max_age_seconds) if max_age_seconds is not None else None
        self._grace = timedelta(seconds=grace_seconds)

    async def evaluate(
        self,
        meta: CredentialMetadata,
        *,
        now: datetime | None = None,
    ) -> RotationDecision:
        reference = _aware_utc(now or datetime.now(timezone.utc))

        modified = self._last_modified(meta)
        if self._max_age is not None and modified is not None:
            if reference - _aware_utc(modified) > self._max_age:
                return RotationDecision(
                    ref=meta.ref,
                    should_rotate=True,
                    reason=f"credential older than max age of {self._max_age}",
                    expires_at=meta.expires_at,
                )

        if meta.expires_at is not None:
            expires = _aware_utc(meta.expires_at)
            if reference + self._grace >= expires:
                return RotationDecision(
                    ref=meta.ref,
                    should_rotate=True,
                    reason=f"credential expires within {self._grace} grace window",
                    expires_at=meta.expires_at,
                )

        return RotationDecision(
            ref=meta.ref,
            should_rotate=False,
            reason="not due for rotation",
            expires_at=meta.expires_at,
        )

    @staticmethod
    def _last_modified(meta: CredentialMetadata) -> datetime | None:
        """Return the most recent modification stamp (updated_at wins)."""
        stamps = [stamp for stamp in (meta.updated_at, meta.created_at) if stamp is not None]
        return max(stamps) if stamps else None


class RotationOrchestrator:
    """Applies rotation/revocation through a source + cache, never raw secrets.

    Callers only ever receive masked ``CredentialMetadata`` or ``bool`` — no
    plaintext crosses this boundary. Rotation is graceful in the sense that the
    underlying source issues a new version while (per backend policy) the old
    version may remain valid through its grace period; the orchestrator
    coordinates the source and cache, it does not manufacture keys.
    """

    def __init__(
        self,
        source: CredentialSource,
        cache: CredentialCache,
        *,
        policy: RotationPolicy,
    ) -> None:
        self._source = source
        self._cache = cache
        self._policy = policy

    async def rotate(self, tenant_id: str, ref: str) -> CredentialMetadata:
        """Rotate ``ref``: issue a new version, then invalidate the cache.

        Returns the new (masked) metadata. The cache is invalidated only AFTER
        a successful source rotation, and never on failure — so a stale entry
        is never discarded while the source is degraded.

        Rotation safety: the runtime must re-resolve the credential after a
        rotation; an in-flight call that already resolved the old version keeps
        that version and is never handed the rotated one here.

        Raises :class:`CredentialBackendUnavailable` when the source fails.
        """
        try:
            new_meta = await self._source.rotate(tenant_id, ref)
        except CredentialBackendUnavailable:
            raise
        except Exception as exc:  # fail closed: wrap, do not leak state
            raise CredentialBackendUnavailable(
                f"credential rotation failed for tenant={tenant_id!r} ref={ref!r}"
            ) from exc
        await self._cache.invalidate(tenant_id, ref)
        return new_meta

    async def revoke(self, tenant_id: str, ref: str) -> bool:
        """Revoke ``ref`` immediately; fail closed on source errors.

        Returns ``True`` on success (the cache is invalidated so the revoked
        credential is never served). Returns ``False`` — WITHOUT invalidating
        the cache — when the source cannot revoke, so the resolution path keeps
        failing closed rather than silently dropping the credential.
        """
        try:
            revoked = await self._source.revoke(tenant_id, ref)
        except Exception:
            return False
        if not revoked:
            return False
        await self._cache.invalidate(tenant_id, ref)
        return True

    async def evaluate_all(
        self,
        tenant_id: str,
        refs: Sequence[str],
    ) -> list[RotationDecision]:
        """Evaluate every ``ref`` against the policy; never rotates.

        This is a decision-only pass over the current masked metadata: each ref
        is loaded from the source and evaluated, and the decisions are returned
        in order. No rotation is applied here — applying one is the explicit job
        of :meth:`rotate`, invoked by the operator/runtime.
        """
        decisions: list[RotationDecision] = []
        for ref in refs:
            meta = await self._source.load(tenant_id, ref)
            decisions.append(await self._policy.evaluate(meta))
        return decisions
