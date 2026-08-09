"""Credential resolver seam: ``credential_reference_id`` -> read-only venue client.

Phase-0 gap (4): account links store a ``credential_reference_id``
(``runtime_models.AccountLinkRequest`` / ``TradingAccountRepo``), but there was
NO production path resolving that reference into a live read-only client — the
reference sat inert. This module builds the resolver seam:

* :func:`resolve_read_only_credential` — resolve a stored reference into a
  :class:`ResolvedReadOnlyCredential` (revealed secret + type + expiry), with
  the observation-only guard that REJECTS any mutating credential scopes and
  any expired/revoked credential. Never returns a trade/withdraw authority.
* :func:`build_read_only_adapter` — resolve the reference and materialize a
  fresh ``VenueDerivativesAdapter`` instance with an injectable REST client
  bound to the resolved credential. The adapter's ``build_request`` carries the
  resolved ``Authorization`` header; per-venue request builders threading live
  auth into each endpoint is the live-endpoint follow-on (external blocker).
* :func:`enforce_observation_only_credential` — the standalone guard used by
  connectors: any credential whose scopes imply trading/withdrawal/key
  management raises ``ReadOnlyCredentialError`` (fail-closed).

Live endpoints are external blockers: this seam is fully testable against a
mock credential backend + mock ``httpx`` transport with no network.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping, Optional

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
from services.derivatives.models import (
    ReadOnlyCredentialError,
    validate_read_only_scopes,
)


class CredentialResolutionError(Exception):
    """Base error for resolving a stored credential reference."""


class CredentialReferenceNotFound(CredentialResolutionError):
    """The reference does not exist, was revoked, or is unreachable."""


class CredentialNotUsable(CredentialResolutionError):
    """The referenced credential is expired or carries no read-only secret."""


# An entitlement check is an async predicate ``(tenant_id, entitlement) -> bool``
# OR a synchronous ``(tenant_id) -> bool``. The resolver calls whichever the
# integration pass installed (see services.derivatives.guards).
EntitlementCheck = Callable[..., bool]


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
        # tenant, no client.
        allowed = entitlement_check(tenant_id)
        if not allowed:
            from services.derivatives.guards import DerivativesEntitlementError

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

    Returns a fresh instance of the venue's ``VenueDerivativesAdapter`` with an
    injectable ``RestBackfillClient`` bound to the resolved credential. When
    ``http_transport`` is supplied (tests) all reads route through the mock
    transport — no live IO. The adapter's ``build_request`` carries the
    resolved ``Authorization: Bearer`` header (the certification seam); live
    per-venue auth threading is an external blocker (see module docstring).
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
    adapter._resolved_credential = resolved  # type: ignore[attr-defined]
    adapter._auth_headers = {"Authorization": f"Bearer {resolved.api_key}"}  # type: ignore[attr-defined]
    return adapter


def bind_resolved_credential(adapter: Any, resolved: ResolvedReadOnlyCredential) -> None:
    """Attach a resolved credential to an already-built adapter (idempotent)."""
    adapter._resolved_credential = resolved  # type: ignore[attr-defined]
    adapter._auth_headers = {  # type: ignore[attr-defined]
        "Authorization": f"Bearer {resolved.api_key}"
    }


__all__ = [
    "ResolvedReadOnlyCredential",
    "CredentialResolutionError",
    "CredentialReferenceNotFound",
    "CredentialNotUsable",
    "enforce_observation_only_credential",
    "resolve_read_only_credential",
    "build_read_only_adapter",
    "bind_resolved_credential",
]
