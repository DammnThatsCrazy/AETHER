"""Durable, multi-slot provider-credential authority.

Public surface is intentionally narrow. Import the frozen contracts (slot
registry + domain schema) from the package root; import the authority, cipher,
and routes from their submodules directly to avoid import cycles with the
payment-rails package and the API layer.
"""

from __future__ import annotations

from services.providers.credentials.schema import (
    CREDENTIAL_ENVIRONMENTS,
    CREDENTIAL_STATES,
    CREDENTIAL_VERSION_FIELDS,
    PAYMENTS_DOMAIN,
    CredentialEnvironment,
    CredentialState,
)
from services.providers.credentials.slot_registry import (
    CredentialSlot,
    build_slot_registry,
    declared_domains,
    get_slot,
    known_providers,
    slots_for,
    slots_for_domain,
)

__all__ = [
    # domain schema
    "CredentialState",
    "CredentialEnvironment",
    "CREDENTIAL_STATES",
    "CREDENTIAL_ENVIRONMENTS",
    "CREDENTIAL_VERSION_FIELDS",
    "PAYMENTS_DOMAIN",
    # slot registry
    "CredentialSlot",
    "build_slot_registry",
    "declared_domains",
    "slots_for",
    "slots_for_domain",
    "get_slot",
    "known_providers",
]
