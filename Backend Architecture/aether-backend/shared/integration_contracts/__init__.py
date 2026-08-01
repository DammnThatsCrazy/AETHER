"""Canonical integration-contract layer for the Unified Integration Control Plane.

This package is the additive, provider-neutral vocabulary the control plane is
built on:

* :mod:`identity` — per-capability provider identity (§11)
* :mod:`manifest` — the canonical provider manifest + honesty invariants (§12, §32)
* :mod:`results` — the canonical adapter result + bridge mappers (§17)
* :mod:`lifecycle` — the connection lifecycle state machine (§16)
* :mod:`deployment` — the typed per-capability deployment contract (§14)

It reuses (never re-defines) the existing readiness, connector, and provider
types. This wave is purely additive: no existing registry or adapter is
modified.
"""

from __future__ import annotations

from shared.integration_contracts.deployment import (
    DeploymentContract,
    DeploymentContractError,
    load_capability,
)
from shared.integration_contracts.identity import (
    CANONICAL_CAPABILITY_KEYS,
    CapabilityId,
    CapabilityKey,
    IdentityError,
    ProductId,
    ProviderFamily,
    ProviderIdentity,
    format_identity,
    is_canonical_capability,
    parse_capability_key,
    parse_identity,
)
from shared.integration_contracts.lifecycle import (
    TRANSITIONS,
    ConnectionState,
    can_transition,
    from_connector_sync_status,
)
from shared.integration_contracts.manifest import (
    Accounts,
    Authentication,
    AuthType,
    Availability,
    ConfigFieldSpec,
    ConfigFieldType,
    Configuration,
    CredentialFieldSpec,
    CredentialFieldType,
    Deployment,
    EnvironmentAvailability,
    ManifestReadiness,
    ManifestValidationError,
    OAuthSpec,
    ProviderManifest,
    Sync,
    Webhooks,
    validate_manifest,
)
from shared.integration_contracts.results import (
    AdapterResult,
    AdapterStatus,
    RateLimitInfo,
    from_connection_test,
    from_provider_result,
    from_sync_result,
)

__all__ = [
    # identity
    "CANONICAL_CAPABILITY_KEYS",
    "CapabilityId",
    "CapabilityKey",
    "IdentityError",
    "ProductId",
    "ProviderFamily",
    "ProviderIdentity",
    "format_identity",
    "is_canonical_capability",
    "parse_capability_key",
    "parse_identity",
    # manifest
    "Accounts",
    "AuthType",
    "Authentication",
    "Availability",
    "ConfigFieldSpec",
    "ConfigFieldType",
    "Configuration",
    "CredentialFieldSpec",
    "CredentialFieldType",
    "Deployment",
    "EnvironmentAvailability",
    "ManifestReadiness",
    "ManifestValidationError",
    "OAuthSpec",
    "ProviderManifest",
    "Sync",
    "Webhooks",
    "validate_manifest",
    # results
    "AdapterResult",
    "AdapterStatus",
    "RateLimitInfo",
    "from_connection_test",
    "from_provider_result",
    "from_sync_result",
    # lifecycle
    "TRANSITIONS",
    "ConnectionState",
    "can_transition",
    "from_connector_sync_status",
    # deployment
    "DeploymentContract",
    "DeploymentContractError",
    "load_capability",
]
