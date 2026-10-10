"""D-05 consent gate for the Relationship Intelligence read surfaces.

Social360 / relationship reads surface PERSONAL + HISTORICAL relationship data;
the social360 projection registry row
(``shared/intelligence_projections/generated_registry.py``) declares
``security.requiresHistoricalConsentEvaluation: True``. This module enforces
that declaration at read time:

* When the master Social360 flag (``shared.relationship_spine.flags``
  ``social360_enabled``) is OFF this gate is a NO-OP — off-flag behavior is
  unchanged (the D-05 posture is *gating an activated surface*, never turning a
  disabled surface into a consent failure).
* When the flag is ON AND the registry row requires historical-consent
  evaluation AND no consent is established for the tenant/subject, an
  :class:`ConsentRequired` exception is raised (typed, message static and
  content-free — no subject/tenant specifics ever leak).
* Consent establishment is provided by an UPSTREAM entitlement/consent
  subsystem through an injectable ``consent_provider`` callable. The default
  provider is ``None`` => NO consent (fail-closed: never fabricate consent).
  Tests / upstream wiring install a provider via
  :func:`set_default_consent_provider`.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional, Union

from shared.intelligence_projections.generated_registry import (
    INTELLIGENCE_PROJECTION_DEFINITIONS,
)
from shared.relationship_spine import flags as _spine_flags

# The projection surface this gate guards and its registry row id.
SOCIAL360_PROJECTION_ID: str = "social360"

# Static, content-free message (never includes subject/tenant/entity details).
CONSENT_REQUIRED_MESSAGE: str = "consent required for historical relationship read"

# Injectable consent-establishment callable. Signature (keyword-friendly):
#     provider(tenant_id=..., subject_entity_id=..., graph=None) -> bool
# A sync ``bool`` or an awaitable resolving to a truthy value grants consent.
ConsentProvider = Callable[..., Union[bool, Awaitable[bool]]]

_default_consent_provider: Optional[ConsentProvider] = None


class ConsentRequired(Exception):
    """Raised when the D-05 consent gate denies a relationship read.

    The message is static and content-free by design.
    """

    def __init__(self, message: str = CONSENT_REQUIRED_MESSAGE) -> None:
        super().__init__(message)
        self.message = message


def set_default_consent_provider(provider: Optional[ConsentProvider]) -> None:
    """Install (or clear, with ``None``) the module-level consent provider.

    Upstream entitlement/consent subsystems call this at wiring time; tests call
    it to grant or deny consent deterministically.
    """
    global _default_consent_provider
    _default_consent_provider = provider


def clear_default_consent_provider() -> None:
    """Reset the default provider to ``None`` (fail-closed: no consent)."""
    set_default_consent_provider(None)


def _surface_requires_historical_consent(projection_id: str = SOCIAL360_PROJECTION_ID) -> bool:
    """Read the projection registry row's security declaration (never raises).

    A missing/unregistered row fails closed to ``True``: an unregistered surface
    that is somehow activated must still not bypass consent.
    """
    row = INTELLIGENCE_PROJECTION_DEFINITIONS.get(projection_id)
    if row is None:
        return True
    security = row.get("security") or {}
    return bool(security.get("requiresHistoricalConsentEvaluation", True))


async def _provider_grants(
    provider: ConsentProvider,
    *,
    tenant_id: str,
    subject_entity_id: str,
    graph: Any,
) -> bool:
    try:
        outcome = provider(tenant_id=tenant_id, subject_entity_id=subject_entity_id, graph=graph)
        if isinstance(outcome, Awaitable):  # type: ignore[arg-type]
            outcome = await outcome  # type: ignore[assignment]
    except Exception:  # noqa: BLE001 - a raising provider fails closed (no consent)
        return False
    return bool(outcome)


async def require_social_read_consent(
    tenant_id: str,
    *,
    subject_entity_id: str,
    graph: Any = None,
    consent_provider: Optional[ConsentProvider] = None,
) -> None:
    """Enforce the D-05 consent gate for a social360 / relationship read.

    NO-OP when the social360 surface is not activated (``social360_enabled()``
    False). Raises :class:`ConsentRequired` when the surface is activated, the
    registry row requires historical-consent evaluation, and no consent is
    established (provider default ``None`` => no consent).
    """
    if not _spine_flags.social360_enabled():
        # Off-flag behavior unchanged: an un-activated surface is not a consent
        # failure surface.
        return
    if not _surface_requires_historical_consent():
        # Registry row does not require historical-consent evaluation.
        return
    provider = consent_provider if consent_provider is not None else _default_consent_provider
    if provider is None:
        raise ConsentRequired()
    granted = await _provider_grants(
        provider, tenant_id=tenant_id, subject_entity_id=subject_entity_id, graph=graph
    )
    if not granted:
        raise ConsentRequired()


__all__ = [
    "SOCIAL360_PROJECTION_ID",
    "CONSENT_REQUIRED_MESSAGE",
    "ConsentProvider",
    "ConsentRequired",
    "require_social_read_consent",
    "set_default_consent_provider",
    "clear_default_consent_provider",
]
