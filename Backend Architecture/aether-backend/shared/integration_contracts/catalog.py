"""Derived provider catalog — one honest :class:`ProviderManifest` per connector.

The manifest system becomes *real* here: instead of hand-authoring a manifest
per provider (duplicate data that rots), every inbound connector's manifest is
**derived** from its existing :class:`ConnectorDescriptor`. The connector
registry stays the single source of truth; this module is a pure projection of
it onto the canonical manifest shape.

Honesty is enforced two ways:

* the mapping is deliberately conservative — it never claims more readiness,
  availability, or capability than the descriptor evidences (no
  staging/production, no OAuth without real scopes, no webhook without a
  verification scheme, no incremental sync without a cursor); and
* every derived manifest is passed through :func:`validate_manifest` at build
  time, so a dishonest or structurally-invalid mapping fails loudly at import
  rather than shipping a lie.
"""

from __future__ import annotations

from services.integrations.connectors.base import ConnectorDescriptor
from services.integrations.connectors.registry import CONNECTORS
from shared.certification.readiness import CredentialReadiness, to_readiness
from shared.integration_contracts.manifest import (
    Accounts,
    Authentication,
    Availability,
    Configuration,
    CredentialFieldSpec,
    Deployment,
    EnvironmentAvailability,
    ManifestReadiness,
    OAuthSpec,
    ProviderManifest,
    Sync,
    Webhooks,
    validate_manifest,
)

# ── Constants ──────────────────────────────────────────────────────────────

# Inbound connectors are one product ("ingestion") exposing one capability
# ("connector"); the provider_family (connector_type) makes the identity unique.
PRODUCT_ID = "ingestion"
CAPABILITY_ID = "connector"

# Connectors write normalized events to Bronze (FeederService); nothing beyond
# that is wired per-connector, so product_destinations is honestly empty.
DEFAULT_DATA_OUTPUTS: list[str] = ["bronze.connector_events"]

# A pull-based incremental sync advances a recency cursor. The adapters filter
# on an "updated"/"updated_at"/"since"-style field; "updated_at" is the honest,
# generic name for that cursor.
DEFAULT_INCREMENTAL_CURSOR = "updated_at"


# Conservative projection of a readiness state onto the manifest's coarse 1-5
# productization level. Level >= 4 is NEVER emitted below sandbox_validated.
_READINESS_LEVEL: dict[CredentialReadiness, int] = {
    CredentialReadiness.SCAFFOLDED: 1,
    CredentialReadiness.DISABLED: 1,
    CredentialReadiness.DEGRADED: 1,
    CredentialReadiness.CREDENTIAL_WAITING: 3,
    CredentialReadiness.REPLAY_VALIDATED: 3,
    CredentialReadiness.SANDBOX_VALIDATED: 4,
    CredentialReadiness.PARTNER_LIVE: 5,
}

# Native webhook verification schemes for connectors whose adapters verify
# inbound signatures in-process (a ``verify_webhook_signature`` staticmethod).
# Webhook-supporting connectors NOT listed here fall back to a generic "hmac"
# scheme — honest, since the framework still HMAC-verifies signed webhooks.
_NATIVE_WEBHOOK_SCHEMES: dict[str, str] = {
    "shopify": "shopify_hmac",
    "stripe": "stripe_signature",
    "hubspot": "hubspot_signature_v3",
    "jira": "jira_hub_signature",
    "linear": "linear_signature",
}

# Real, non-empty OAuth scopes keyed by connector_type. Empty today: no
# registry connector declares honest scopes, so no manifest emits oauth2 with
# empty scopes (which validate_manifest would reject). Populate this — never the
# mapping below — to turn a connector's authentication into real OAuth.
_OAUTH_SCOPES: dict[str, list[str]] = {}


# ── Sub-mappers ────────────────────────────────────────────────────────────


def _readiness_for(desc: ConnectorDescriptor) -> ManifestReadiness:
    """Readiness state (reused token) + conservative 1-5 level."""
    state = to_readiness(desc.implementation_status)
    return ManifestReadiness(state=state, level=_READINESS_LEVEL[state])


def _availability_for(level: int) -> Availability:
    """Where the capability is honestly exposed.

    Tenant self-service and Kyber-managed surfaces are on; the Olympus system
    surface is off (these are tenant BYOD connectors). Nothing is
    staging/production-enabled yet, so those environments are always False. A
    connector is only visible in local/integration once it is at least
    replay-validated *material* (level >= 3); scaffolded/disabled/degraded
    (level < 3) are visible nowhere, which also keeps the manifest honest under
    ``validate_manifest``'s "visible-in-environment requires level>=3" rule.
    """
    env_enabled = level >= 3
    return Availability(
        tenant_self_service=True,
        kyber_managed=True,
        olympus_system=False,
        environments=EnvironmentAvailability(
            local=env_enabled,
            integration=env_enabled,
            staging=False,
            production=False,
        ),
    )


def _authentication_for(desc: ConnectorDescriptor) -> Authentication:
    """Map the descriptor's credential shape onto an honest authentication.

    Precedence: genuine OAuth *with real scopes* → ``oauth2``; a webhook-only
    ingest connector (receives events, no pull API) → ``webhook_only`` keyed on
    the inbound signing secret; a secret-bearing connector → ``api_key``;
    otherwise ``none``.
    """
    # OAuth only when the connector genuinely uses OAuth AND we can supply real,
    # non-empty scopes — otherwise fall through (never emit empty-scope oauth2).
    if desc.supports_oauth:
        scopes = _OAUTH_SCOPES.get(desc.connector_type, [])
        if scopes:
            return Authentication(
                type="oauth2",
                credential_schema=[
                    CredentialFieldSpec(
                        name="oauth_token", type="oauth_token", secret=True
                    )
                ],
                oauth=OAuthSpec(scopes=list(scopes), refresh_supported=True),
            )

    # Webhook-only ingest: the credential is the inbound webhook signing secret.
    if desc.supports_webhook and not desc.supports_pull:
        return Authentication(
            type="webhook_only",
            credential_schema=[
                CredentialFieldSpec(name="webhook_secret", type="secret", secret=True)
            ],
        )

    # Secret / API-key based — the common case for pull-capable connectors.
    if desc.requires_secret:
        return Authentication(
            type="api_key",
            credential_schema=[
                CredentialFieldSpec(name="api_key", type="secret", secret=True)
            ],
        )

    return Authentication(type="none")


def _webhooks_for(desc: ConnectorDescriptor) -> Webhooks:
    """Webhook support + verification scheme (required when supported)."""
    if not desc.supports_webhook:
        return Webhooks(supported=False)
    scheme = _NATIVE_WEBHOOK_SCHEMES.get(desc.connector_type, "hmac")
    return Webhooks(
        supported=True,
        registration_supported=False,
        verification_scheme=scheme,
    )


def _sync_for(desc: ConnectorDescriptor) -> Sync:
    """Backfill/incremental sync shape; a cursor is set whenever incremental."""
    incremental = desc.supports_pull
    return Sync(
        initial_backfill=desc.supports_historical_backfill,
        incremental=incremental,
        reconciliation=False,
        cursor=DEFAULT_INCREMENTAL_CURSOR if incremental else None,
    )


# ── Public API ─────────────────────────────────────────────────────────────


def manifest_from_connector_descriptor(desc: ConnectorDescriptor) -> ProviderManifest:
    """Derive a :class:`ProviderManifest` from one :class:`ConnectorDescriptor`.

    Pure projection: identity, readiness, availability, authentication,
    webhooks, and sync are all read out of the descriptor's existing fields —
    no hand-authored duplicate data.
    """
    readiness = _readiness_for(desc)
    authentication = _authentication_for(desc)
    required_secrets = [field.name for field in authentication.credential_schema]

    return ProviderManifest(
        provider_family=desc.connector_type,
        product_id=PRODUCT_ID,
        capability_id=CAPABILITY_ID,
        display_name=desc.label,
        category=desc.category,
        readiness=readiness,
        availability=_availability_for(readiness.level),
        authentication=authentication,
        configuration=Configuration(),
        accounts=Accounts(),
        webhooks=_webhooks_for(desc),
        sync=_sync_for(desc),
        data_outputs=list(DEFAULT_DATA_OUTPUTS),
        product_destinations=[],
        deployment=Deployment(required_secrets=required_secrets),
    )


def build_connector_manifests() -> list[ProviderManifest]:
    """Derive + honesty-validate a manifest for every registered connector.

    Each manifest passes through :func:`validate_manifest`, so any dishonest or
    invalid mapping raises :class:`ManifestValidationError` here rather than
    shipping. Ordered by the registry's insertion order for stable output.
    """
    manifests: list[ProviderManifest] = []
    for connector in CONNECTORS.values():
        descriptor = connector.descriptor()
        manifests.append(
            validate_manifest(manifest_from_connector_descriptor(descriptor))
        )
    return manifests


# Computed once at import: the honest, validated catalog of connector manifests.
CONNECTOR_MANIFESTS: list[ProviderManifest] = build_connector_manifests()

# Lookup by provider family (connector_type is unique per connector).
manifest_by_family: dict[str, ProviderManifest] = {
    manifest.provider_family: manifest for manifest in CONNECTOR_MANIFESTS
}


__all__ = [
    "CONNECTOR_MANIFESTS",
    "DEFAULT_DATA_OUTPUTS",
    "DEFAULT_INCREMENTAL_CURSOR",
    "build_connector_manifests",
    "manifest_by_family",
    "manifest_from_connector_descriptor",
]
