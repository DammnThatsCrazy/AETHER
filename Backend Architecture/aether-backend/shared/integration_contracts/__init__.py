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
    CertificationState,
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
    TransportProtocol,
    Webhooks,
    is_financial_provider,
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
from shared.integration_contracts.acquisition import (
    AcquisitionContext,
    ProviderAccount,
)
from shared.integration_contracts.capabilities import (
    CAPABILITY_ADAPTER_METHODS,
    AccountAdapter,
    AuthAdapter,
    PullAdapter,
    ReconciliationAdapter,
    ReportAdapter,
    StreamAdapter,
    WebhookAdapter,
)
from shared.integration_contracts.certification import (
    CertificationCheck,
    CertificationReport,
    ProviderReadinessLevel,
)
from shared.integration_contracts.events import (
    AetherEvent,
    RawProviderRecord,
    ReadBatch,
    compute_checksum,
    make_aether_event,
    make_raw_record,
    verify_checksum,
)
from shared.integration_contracts.health import ProviderHealthReport
from shared.integration_contracts.normalization import (
    EventNormalizer,
    NormalizationResult,
)
from shared.integration_contracts.plugin import (
    CapabilitySet,
    PluginValidationError,
    ProviderPlugin,
    capability_set,
    plugin_identity_key,
)
from shared.integration_contracts.reconciliation import (
    ProviderReconciliationReport,
    ReconciliationCheck,
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
    "CertificationState",
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
    "TransportProtocol",
    "Webhooks",
    "is_financial_provider",
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
    # acquisition
    "AcquisitionContext",
    "ProviderAccount",
    # capabilities
    "CAPABILITY_ADAPTER_METHODS",
    "AccountAdapter",
    "AuthAdapter",
    "PullAdapter",
    "ReconciliationAdapter",
    "ReportAdapter",
    "StreamAdapter",
    "WebhookAdapter",
    # certification
    "CertificationCheck",
    "CertificationReport",
    "ProviderReadinessLevel",
    # events
    "AetherEvent",
    "RawProviderRecord",
    "ReadBatch",
    "compute_checksum",
    "make_aether_event",
    "make_raw_record",
    "verify_checksum",
    # health
    "ProviderHealthReport",
    # normalization
    "EventNormalizer",
    "NormalizationResult",
    # plugin
    "CapabilitySet",
    "PluginValidationError",
    "ProviderPlugin",
    "capability_set",
    "plugin_identity_key",
    # reconciliation
    "ProviderReconciliationReport",
    "ReconciliationCheck",
]
