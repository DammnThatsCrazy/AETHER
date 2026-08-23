"""Derivatives entitlement + read-only-credential enforcement.

Phase-0 gap (6): ``DERIVATIVES_REQUIRED_ENTITLEMENT`` was declared in
``product.py`` but never enforced — nothing checked that a tenant was entitled
to ``derivatives.enabled`` before observing/pulling their venue data.

This module makes the enforcement real and pluggable:

* :data:`derivatives_entitlement_gate` — the process-wide authority.
* :func:`require_derivatives_entitlement` — the fail-closed check the
  observation/pull path calls.
* :func:`install_derivatives_entitlement_resolver` — the seam the integration
  pass wires to a real entitlement platform (e.g. the plan/entitlement service).
  Until a resolver is installed the gate is FAIL-CLOSED: no tenant is entitled,
  so any path that opts into the gate denies (never claims access it cannot
  verify).
* :func:`seed_derivatives_entitlement` — deterministic in-process seeding used
  by tests and local demo mode (never a production authority).

The gate is deliberately OFF by default: existing local/simulator paths do not
hit it until the integration pass opts them in (see wiringNeeds). Once a
resolver is installed, entitlement becomes an enforced precondition for the
observation/pull path.

The module also owns the read-only credential resolver seam (re-homed from the
branch-only ``services/derivatives/credentials.py`` onto main's canonical
guards):

* :func:`resolve_read_only_credential` — resolve a stored
  ``credential_reference_id`` into a :class:`ResolvedReadOnlyCredential`
  (revealed secret + type + expiry), with the observation-only guard that
  REJECTS any mutating credential scopes and any expired/revoked credential.
* :func:`build_read_only_adapter` — resolve the reference and materialize a
  fresh venue adapter with an injectable REST client bound to the resolved
  credential (``_auth_headers`` / ``_resolved_credential`` attach the
  read-only secret for main's ``build_request`` injection seam).
* :func:`enforce_observation_only_credential` — standalone guard mirroring
  main's ``connectors.base.enforce_read_only_credentials``.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from shared.credentials.service import CredentialService, credential_service
from shared.credentials.types import (
    ApiKeyCredential,
    ApiKeyWebhookSecretCredential,
    KeyIdSecretCredential,
    OAuthTokenCredential,
    StructuredCredential,
    UsernameTokenCredential,
)
from services.derivatives.adapters import get_adapter
from services.derivatives.connectors.transport import RestBackfillClient
from services.derivatives.models import ReadOnlyCredentialError, validate_read_only_scopes
from services.derivatives.product import DERIVATIVES_REQUIRED_ENTITLEMENT

# Resolver signature: ``(tenant_id: str, entitlement: str) -> bool``.
EntitlementResolver = Callable[[str, str], bool]


class DerivativesEntitlementError(Exception):
    """Raised when a tenant lacks the derivatives entitlement."""


class DerivativesEntitlementGate:
    """Pluggable entitlement authority. Fail-closed until a resolver is wired."""

    def __init__(self) -> None:
        self._resolver: Optional[EntitlementResolver] = None
        self._seeded: dict[str, bool] = {}
        self._enforcement_on: bool = False

    def install_resolver(self, resolver: EntitlementResolver) -> None:
        """Install the authoritative resolver (integration pass / production)."""
        self._resolver = resolver

    def set_enforcement(self, on: bool) -> None:
        """Turn gate enforcement on/off. Default off (opt-in per call site)."""
        self._enforcement_on = bool(on)

    @property
    def enforcement_on(self) -> bool:
        return self._enforcement_on

    def seed_tenant(self, tenant_id: str, entitled: bool = True) -> None:
        """Deterministic in-process seeding (tests / local demo only)."""
        self._seeded[tenant_id] = bool(entitled)

    def clear_seeded(self) -> None:
        self._seeded.clear()

    def reset(self) -> None:
        """Test/demo hygiene: drop the resolver, seeding, and enforcement flag."""
        self._resolver = None
        self._seeded.clear()
        self._enforcement_on = False

    def is_entitled(
        self,
        tenant_id: str,
        entitlement: str = DERIVATIVES_REQUIRED_ENTITLEMENT,
    ) -> bool:
        if self._resolver is not None:
            try:
                return bool(self._resolver(tenant_id, entitlement))
            except Exception:
                # A resolver that errors is not evidence of entitlement.
                return False
        return bool(self._seeded.get(tenant_id, False))

    def require(
        self,
        tenant_id: str,
        entitlement: str = DERIVATIVES_REQUIRED_ENTITLEMENT,
    ) -> None:
        """Raise ``DerivativesEntitlementError`` when the tenant is not entitled."""
        if not self.is_entitled(tenant_id, entitlement):
            raise DerivativesEntitlementError(
                f"tenant {tenant_id!r} is not entitled to {entitlement!r}"
            )


derivatives_entitlement_gate = DerivativesEntitlementGate()


def require_derivatives_entitlement(
    tenant_id: str,
    entitlement: str = DERIVATIVES_REQUIRED_ENTITLEMENT,
) -> None:
    """Fail-closed entitlement check for the observation/pull path."""
    derivatives_entitlement_gate.require(tenant_id, entitlement)


def install_derivatives_entitlement_resolver(resolver: EntitlementResolver) -> None:
    derivatives_entitlement_gate.install_resolver(resolver)


def seed_derivatives_entitlement(tenant_id: str, entitled: bool = True) -> None:
    derivatives_entitlement_gate.seed_tenant(tenant_id, entitled)


def clear_derivatives_entitlements() -> None:
    derivatives_entitlement_gate.clear_seeded()


def is_tenant_entitled(
    tenant_id: str,
    entitlement: str = DERIVATIVES_REQUIRED_ENTITLEMENT,
) -> bool:
    return derivatives_entitlement_gate.is_entitled(tenant_id, entitlement)


# ═══════════════════════════════════════════════════════════════════════════
# Read-only credential resolver seam
# ═══════════════════════════════════════════════════════════════════════════

# An entitlement check is an async predicate ``(tenant_id, entitlement) -> bool``
# OR a synchronous ``(tenant_id) -> bool``. The resolver calls whichever the
# integration pass installed (see ``DerivativesEntitlementGate`` above).
EntitlementCheck = Callable[..., bool]


class CredentialResolutionError(Exception):
    """Base error for resolving a stored credential reference."""


class CredentialReferenceNotFound(CredentialResolutionError):
    """The reference does not exist, was revoked, or is unreachable."""


class CredentialNotUsable(CredentialResolutionError):
    """The referenced credential is expired or carries no read-only secret."""


@dataclass(frozen=True)
class ResolvedReadOnlyCredential:
    """The plaintext-safe resolution of one stored credential reference.

    ``api_key`` is the revealed read-only secret (the only secret this object
    carries). Every other field is non-secret. Never log this object verbatim.
    """

    tenant_id: str
    credential_reference_id: str
    credential_type: str
    api_key: str
    authority: str = "read_only"
    expires_at: Optional[str] = None


def _scopes_of(cred: StructuredCredential) -> list[str]:
    """Non-secret scope fields a credential may carry (OAuth scopes only)."""
    if isinstance(cred, OAuthTokenCredential):
        return list(cred.scope or [])
    return []


def _read_only_secret(cred: StructuredCredential) -> Optional[str]:
    """Return the read-only secret for credential types a venue connector can
    legitimately hold, or ``None`` for types with no read-only secret material."""
    if isinstance(cred, ApiKeyCredential):
        return cred.api_key.get_secret_value()
    if isinstance(cred, ApiKeyWebhookSecretCredential):
        return cred.api_key.get_secret_value()
    if isinstance(cred, KeyIdSecretCredential):
        return cred.secret.get_secret_value()
    if isinstance(cred, UsernameTokenCredential):
        return cred.token.get_secret_value()
    if isinstance(cred, OAuthTokenCredential):
        return cred.access_token.get_secret_value()
    # ServiceAccount / ClientSecret / Keypair / Multi are not accepted as
    # read-only venue credentials by the derivatives domain.
    return None


def enforce_observation_only_credential(
    scopes: list[str] | tuple[str, ...] | set[str],
) -> None:
    """Standalone observation-only guard.

    Raises ``ReadOnlyCredentialError`` when the credential grants trade,
    transfer, withdrawal, key-management, or any ``*:write`` scope. This is the
    guard every connector/observer must call before trusting a credential.
    """
    validate_read_only_scopes(list(scopes))


async def resolve_read_only_credential(
    credential_reference_id: str,
    *,
    tenant_id: str,
    service: Optional[CredentialService] = None,
    entitlement_check: Optional[EntitlementCheck] = None,
) -> ResolvedReadOnlyCredential:
    """Resolve a stored reference into a guarded read-only credential.

    Steps (each fail-closed):
    1. If an ``entitlement_check`` is supplied, the tenant must be entitled to
       the derivatives domain or ``DerivativesEntitlementError`` propagates.
    2. ``service.get`` must return a live structured credential — a revoked,
       missing, or unreachable reference raises ``CredentialReferenceNotFound``.
    3. An expired credential raises ``CredentialNotUsable``.
    4. OAuth scopes (or any supplied scopes) are passed through
       :func:`validate_read_only_scopes` — a mutating scope raises
       ``ReadOnlyCredentialError`` (observation-only invariant).
    5. The credential type must carry read-only secret material; otherwise
       ``CredentialNotUsable``.
    """
    if not credential_reference_id:
        raise CredentialReferenceNotFound("credential_reference_id is empty")
    if entitlement_check is not None:
        # The resolver is the enforcement point for the pull path: no entitled
        # tenant, no client. An async predicate returns a coroutine object —
        # which is truthy — so it MUST be awaited before truthiness is used,
        # otherwise a denied tenant silently bypasses the gate.
        allowed = entitlement_check(tenant_id)
        if inspect.isawaitable(allowed):
            allowed = await allowed
        if not allowed:
            raise DerivativesEntitlementError(
                f"tenant {tenant_id!r} is not entitled to derivatives observation"
            )
    svc = service or credential_service
    cred = await svc.get(tenant_id, credential_reference_id)
    if cred is None:
        raise CredentialReferenceNotFound(
            f"credential reference {credential_reference_id!r} for tenant "
            f"{tenant_id!r} is absent or revoked"
        )
    if getattr(cred, "is_expired", lambda: False)():
        raise CredentialNotUsable(
            f"credential reference {credential_reference_id!r} is expired"
        )
    scopes = _scopes_of(cred)
    if scopes:
        validate_read_only_scopes(scopes)
    secret = _read_only_secret(cred)
    if not secret:
        raise CredentialNotUsable(
            f"credential reference {credential_reference_id!r} of type "
            f"{cred.type!r} carries no read-only venue secret material"
        )
    expires_at = (
        cred.expires_at.isoformat()
        if getattr(cred, "expires_at", None) is not None
        else None
    )
    return ResolvedReadOnlyCredential(
        tenant_id=tenant_id,
        credential_reference_id=credential_reference_id,
        credential_type=cred.type,
        api_key=secret,
        authority="read_only",
        expires_at=expires_at,
    )


def bind_resolved_credential(adapter: Any, resolved: ResolvedReadOnlyCredential) -> None:
    """Attach a resolved credential to an already-built adapter (idempotent)."""
    adapter._resolved_credential = resolved  # type: ignore[attr-defined]
    adapter._auth_headers = {  # type: ignore[attr-defined]
        "Authorization": f"Bearer {resolved.api_key}"
    }


async def build_read_only_adapter(
    credential_reference_id: str,
    *,
    tenant_id: str,
    venue_id: str,
    service: Optional[CredentialService] = None,
    entitlement_check: Optional[EntitlementCheck] = None,
    http_transport: Any = None,
    sleeper: Optional[Callable[[float], Awaitable[Any]]] = None,
    http_timeout: float = 15.0,
    account_ref: Optional[str] = None,
) -> Any:
    """Resolve a reference and materialize a configured read-only venue adapter.

    Returns a fresh instance of the venue's adapter with an injectable
    ``RestBackfillClient`` bound to the resolved credential. When
    ``http_transport`` is supplied (tests) all reads route through the mock
    transport — no live IO. The adapter's ``_auth_headers`` /
    ``_resolved_credential`` carry the resolved ``Authorization: Bearer``
    header (main's ``build_request`` credential-injection seam reads the
    resolved secret from the request context).
    """
    adapter_proto = get_adapter(venue_id)
    if adapter_proto is None:
        raise CredentialResolutionError(
            f"no read-only derivatives adapter registered for venue {venue_id!r}"
        )
    resolved = await resolve_read_only_credential(
        credential_reference_id,
        tenant_id=tenant_id,
        service=service,
        entitlement_check=entitlement_check,
    )
    adapter_cls = type(adapter_proto)
    rest = RestBackfillClient(
        http_transport=http_transport,
        base_url=getattr(adapter_cls, "rest_base_url", ""),
        http_timeout=http_timeout,
        sleeper=sleeper,
    )
    adapter = adapter_cls(
        rest_client=rest,
        sleeper=sleeper,
        http_timeout=http_timeout,
        account_ref=account_ref,
    )
    bind_resolved_credential(adapter, resolved)
    return adapter


__all__ = [
    "DERIVATIVES_REQUIRED_ENTITLEMENT",
    "DerivativesEntitlementError",
    "DerivativesEntitlementGate",
    "derivatives_entitlement_gate",
    "require_derivatives_entitlement",
    "install_derivatives_entitlement_resolver",
    "seed_derivatives_entitlement",
    "clear_derivatives_entitlements",
    "is_tenant_entitled",
    "EntitlementCheck",
    "CredentialResolutionError",
    "CredentialReferenceNotFound",
    "CredentialNotUsable",
    "ResolvedReadOnlyCredential",
    "enforce_observation_only_credential",
    "resolve_read_only_credential",
    "build_read_only_adapter",
    "bind_resolved_credential",
]
