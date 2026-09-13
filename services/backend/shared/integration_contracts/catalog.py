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
from services.integrations.providers.payment_rails import ADAPTERS as PAYMENT_RAIL_ADAPTERS
from services.integrations.providers.payment_rails.base import PaymentRailAdapter
from shared.certification.readiness import CredentialReadiness, to_readiness
from shared.integration_contracts.manifest import (
    Accounts,
    Authentication,
    AuthType,
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
from shared.providers.categories import CATEGORY_PROVIDERS, ProviderCategory

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
    # Comms provider-native schemes (declared ahead of their adapters so the
    # manifest names the provider's real scheme from the start).
    "sendgrid": "sendgrid_ecdsa",
    "customerio": "customerio_hmac_v0",
    "iterable": "iterable_hmac_query",
    # Mailchimp (Marketing) and Postmark send no cryptographic signature; the
    # high-entropy durable endpoint id in the webhook URL is the credential.
    "mailchimp": "endpoint_secret",
    "postmark": "endpoint_secret",
    # Braze does not sign REST webhooks with a provider-native HMAC — its primary
    # ingest path is REST pull (email-list export). Any webhook path therefore
    # verifies through Aether's generic timestamped HMAC ("hmac"): honest, since
    # the framework still HMAC-verifies signed webhooks (pull-model-first).
    "braze": "hmac",
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
    """Backfill/incremental sync shape; a cursor is set whenever incremental.

    ``reconciliation`` is projected from the descriptor: a connector only claims
    provider/Aether reconciliation when its adapter genuinely implements it
    (e.g. Klaviyo's ``reconcile()``); the default stays ``False``.
    """
    incremental = desc.supports_pull
    return Sync(
        initial_backfill=desc.supports_historical_backfill,
        incremental=incremental,
        reconciliation=desc.supports_reconciliation,
        cursor=DEFAULT_INCREMENTAL_CURSOR if incremental else None,
    )


def _accounts_for(desc: ConnectorDescriptor) -> Accounts:
    """Provider-account discovery/selection, projected from the descriptor."""
    return Accounts(
        discovery_supported=desc.supports_account_discovery,
        selection_required=desc.supports_account_selection,
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

    # Connectors that declare a richer capability surface (e.g. comms adapters)
    # project it here; everything else falls back to the connector-generic
    # defaults. The connector class stays the single source of truth.
    data_outputs = list(desc.manifest_data_outputs) or list(DEFAULT_DATA_OUTPUTS)
    product_destinations = list(desc.manifest_product_destinations)

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
        accounts=_accounts_for(desc),
        webhooks=_webhooks_for(desc),
        sync=_sync_for(desc),
        data_outputs=data_outputs,
        product_destinations=product_destinations,
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


# ── Payment-rail catalog (observe-only) ──────────────────────────────────────
#
# Payment rails are ONE product ("payment_rails") exposing ONE capability
# ("observe"). Aether OBSERVES funding flows — it never executes, settles,
# originates, or custodies funds — so the capability is deliberately "observe"
# and nothing in the manifest may imply movement of money.

PAYMENT_RAIL_PRODUCT_ID = "payment_rails"
PAYMENT_RAIL_CAPABILITY_ID = "observe"
PAYMENT_RAIL_CATEGORY = "payments"

# Observed provider events are normalized into Bronze; nothing downstream is
# wired per-rail, so product_destinations is honestly empty.
PAYMENT_RAIL_DATA_OUTPUTS: list[str] = ["bronze.payment_rail_events"]

# A polling rail advances a recency cursor over provider-reported records; the
# adapters order by a "created"-style field, so "created" is the honest cursor.
PAYMENT_RAIL_INCREMENTAL_CURSOR = "created"

# The one credential every rail needs is the inbound webhook signing secret;
# the adapters name it "webhook_signing_secret" in their cert declaration and we
# surface it as the manifest field "webhook_secret".
_WEBHOOK_SIGNING_CREDENTIAL = "webhook_signing_secret"
_WEBHOOK_SECRET_FIELD = "webhook_secret"

# Adapter HMAC signature scheme → honest webhook verification-scheme name. The
# base adapter verifies inbound webhooks with HMAC-SHA256; "timestamped_hex"
# signs f"{timestamp}.{body}" (Privy / Stripe / MoonPay / Bridge), "body_hex"
# signs the raw body (Coinbase). Both are real, in-process schemes. Unknown
# schemes fall back to a generic "hmac" (still an honest HMAC verification).
_PAYMENT_RAIL_WEBHOOK_SCHEMES: dict[str, str] = {
    "timestamped_hex": "hmac_sha256_timestamped",
    "body_hex": "hmac_sha256_body",
}


def _payment_rail_credential_schema(
    adapter: PaymentRailAdapter,
) -> list[CredentialFieldSpec]:
    """Honest credential shape read from the adapter's real required credentials.

    Every rail requires the inbound webhook signing secret (surfaced as
    ``webhook_secret``); a polling rail additionally requires a provider API key,
    carried through under the adapter's own credential name. All are secrets.
    """
    fields: list[CredentialFieldSpec] = []
    for name in adapter.cert_required_credentials:
        field_name = (
            _WEBHOOK_SECRET_FIELD if name == _WEBHOOK_SIGNING_CREDENTIAL else name
        )
        fields.append(CredentialFieldSpec(name=field_name, type="secret", secret=True))
    return fields


def manifest_from_payment_rail_adapter(
    adapter: PaymentRailAdapter,
) -> ProviderManifest:
    """Derive an observe-only :class:`ProviderManifest` from one payment-rail
    adapter's real declared mode (webhook-only vs polling, HMAC scheme,
    required credentials).

    Honesty: readiness is CREDENTIAL_WAITING (code complete, offline-safe,
    awaiting tenant credentials) → level 3 — never >=4, since no rail is
    sandbox-validated. Visible only in local/integration; never staging/
    production. The capability is "observe": the platform never moves funds.
    """
    credential_schema = _payment_rail_credential_schema(adapter)
    auth_type: AuthType = "webhook_only" if adapter.webhook_only else "api_key"
    polling = adapter.polling_supported
    scheme = _PAYMENT_RAIL_WEBHOOK_SCHEMES.get(adapter.signature_scheme, "hmac")
    readiness = ManifestReadiness(
        state=CredentialReadiness.CREDENTIAL_WAITING,
        level=_READINESS_LEVEL[CredentialReadiness.CREDENTIAL_WAITING],
    )

    return ProviderManifest(
        provider_family=adapter.provider_name,
        product_id=PAYMENT_RAIL_PRODUCT_ID,
        capability_id=PAYMENT_RAIL_CAPABILITY_ID,
        display_name=adapter.display_name,
        category=PAYMENT_RAIL_CATEGORY,
        readiness=readiness,
        availability=Availability(
            tenant_self_service=True,
            kyber_managed=True,
            olympus_system=False,
            environments=EnvironmentAvailability(
                local=True,
                integration=True,
                staging=False,
                production=False,
            ),
        ),
        authentication=Authentication(
            type=auth_type, credential_schema=credential_schema
        ),
        configuration=Configuration(),
        accounts=Accounts(),
        webhooks=Webhooks(
            supported=True,
            registration_supported=False,
            verification_scheme=scheme,
        ),
        sync=Sync(
            initial_backfill=False,
            incremental=polling,
            reconciliation=False,
            cursor=PAYMENT_RAIL_INCREMENTAL_CURSOR if polling else None,
        ),
        data_outputs=list(PAYMENT_RAIL_DATA_OUTPUTS),
        product_destinations=[],
        deployment=Deployment(
            required_secrets=[field.name for field in credential_schema],
        ),
    )


def build_payment_rail_manifests() -> list[ProviderManifest]:
    """Derive + honesty-validate one manifest per registered payment rail.

    Each manifest passes through :func:`validate_manifest`, so a dishonest or
    invalid mapping raises here rather than shipping. Ordered by the rail
    registry's insertion order for stable output.
    """
    return [
        validate_manifest(manifest_from_payment_rail_adapter(adapter))
        for adapter in PAYMENT_RAIL_ADAPTERS.values()
    ]


# ── Deferred credit-bureau catalog (§26) ─────────────────────────────────────
#
# Credit bureaus are honestly DEFERRED: scaffolded at the policy level, hidden
# from tenants, and enabled in NO environment. Activation is gated on legal,
# consent, security, commercial, and certification approval — none of which has
# happened — so the manifest claims nothing (level 1, all-false availability).

CREDIT_BUREAU_PRODUCT_ID = "credit"
CREDIT_BUREAU_CAPABILITY_ID = "report"
CREDIT_BUREAU_CATEGORY = ProviderCategory.CREDIT_BUREAU.value  # "credit_bureau"

_CREDIT_BUREAU_DISPLAY_NAMES: dict[str, str] = {
    "experian": "Experian",
    "equifax": "Equifax",
    "transunion": "TransUnion",
}

# The activation gate recorded on every deferred bureau manifest — a standing
# reminder that turning any of this on is a multi-approval decision, not a code
# change. Recorded as provider_registration_steps (deployment guidance only).
_CREDIT_BUREAU_ACTIVATION_STEPS: list[str] = [
    "DEFERRED (§26): not activated in any environment.",
    "Activation requires legal approval (FCRA / permissible-purpose review).",
    "Activation requires end-user consent capture for every credit pull.",
    "Activation requires a security review of PII / SSN handling.",
    "Activation requires an executed commercial agreement with the bureau.",
    "Activation requires certification (replay + sandbox) before any enablement.",
]


def _credit_bureau_credential_schema() -> list[CredentialFieldSpec]:
    """Describe the composite credential SHAPE only.

    Declaring the shape enables nothing — no environment is turned on and the
    capability stays hidden from tenants. The fields mirror a typical tri-bureau
    integration (client id + client secret + api key); the shape is descriptive,
    not a claim of readiness.
    """
    return [
        CredentialFieldSpec(
            name="client_id", type="string", required=True, secret=False
        ),
        CredentialFieldSpec(
            name="client_secret", type="secret", required=True, secret=True
        ),
        CredentialFieldSpec(name="api_key", type="secret", required=True, secret=True),
    ]


def manifest_from_credit_bureau(bureau: str) -> ProviderManifest:
    """Build the honestly-DEFERRED (§26) manifest for one credit bureau.

    SCAFFOLDED readiness → level 1; tenant-invisible and enabled in NO
    environment; webhooks unsupported; sync all False. This keeps
    :func:`validate_manifest` satisfied (no env enabled ⇒ no level>=3 demand)
    while claiming nothing the program has not approved.
    """
    credential_schema = _credit_bureau_credential_schema()
    readiness = ManifestReadiness(
        state=CredentialReadiness.SCAFFOLDED,
        level=_READINESS_LEVEL[CredentialReadiness.SCAFFOLDED],
    )
    return ProviderManifest(
        provider_family=bureau,
        product_id=CREDIT_BUREAU_PRODUCT_ID,
        capability_id=CREDIT_BUREAU_CAPABILITY_ID,
        display_name=_CREDIT_BUREAU_DISPLAY_NAMES[bureau],
        category=CREDIT_BUREAU_CATEGORY,
        readiness=readiness,
        availability=Availability(
            tenant_self_service=False,
            kyber_managed=False,
            olympus_system=False,
            environments=EnvironmentAvailability(
                local=False,
                integration=False,
                staging=False,
                production=False,
            ),
        ),
        authentication=Authentication(
            type="composite", credential_schema=credential_schema
        ),
        configuration=Configuration(),
        accounts=Accounts(),
        webhooks=Webhooks(supported=False),
        sync=Sync(
            initial_backfill=False,
            incremental=False,
            reconciliation=False,
            cursor=None,
        ),
        data_outputs=[],
        product_destinations=[],
        deployment=Deployment(
            required_secrets=[f.name for f in credential_schema if f.secret],
            provider_registration_steps=list(_CREDIT_BUREAU_ACTIVATION_STEPS),
        ),
    )


def build_deferred_credit_bureau_manifests() -> list[ProviderManifest]:
    """Build + honesty-validate the DEFERRED (§26) credit-bureau manifests.

    Derived from the ``credit_bureau`` category roster
    (experian / equifax / transunion). Each passes :func:`validate_manifest`.
    """
    return [
        validate_manifest(manifest_from_credit_bureau(bureau))
        for bureau in CATEGORY_PROVIDERS[ProviderCategory.CREDIT_BUREAU]
    ]


# ── Ad-platform catalog (measurement runtime) ────────────────────────────────
#
# The seven measurement ad connectors (services/measurement/connectors/*_ads)
# are a second provider family behind the same customer job — campaign
# measurement. Each is exposed here as ONE manifest under product "ads" exposing
# ONE capability ("metrics"): the runtime pulls normalized campaign spend from
# the provider API into the canonical measurement spend store. Identity keys on
# the canonical family ids (google_ads … microsoft_ads) — the ids the measurement
# runtime and campaign normalization already use — NOT the legacy alias names
# (twitter_ads &c.), which resolve onto these families via the boundary alias
# map (shared.integration_contracts.aliases).
#
# Honesty mirrors the payment-rail projection: readiness is CREDENTIAL_WAITING
# (code complete, offline-safe, awaiting tenant credentials) → level 3, never >=4
# since no ad connector is sandbox-validated; visible only in local/integration.
# No ad connector executes syncs yet (the connect runtime and account discovery
# are later workstreams), so accounts claims no discovery/selection surface — the
# ad account id is simply a field the tenant supplies in the credential form.
#
# Display names and credential field tables below are the SINGLE catalog mirror
# of each connector module's documented "Required config keys"; the catalog
# honesty tests assert every declared field is actually read by the module so a
# drift fails loudly rather than shipping a stale schema.

AD_PRODUCT_ID = "ads"
AD_CAPABILITY_ID = "metrics"
AD_CATEGORY = ProviderCategory.AD_PLATFORM.value  # "ad_platform"

# Canonical ad-platform families in stable catalog order.
AD_FAMILIES: tuple[str, ...] = (
    "google_ads",
    "meta_ads",
    "tiktok_ads",
    "linkedin_ads",
    "x_ads",
    "reddit_ads",
    "microsoft_ads",
)

AD_DISPLAY_NAMES: dict[str, str] = {
    "google_ads": "Google Ads",
    "meta_ads": "Meta Ads",
    "tiktok_ads": "TikTok Ads",
    "linkedin_ads": "LinkedIn Ads",
    "x_ads": "X (Twitter) Ads",
    "reddit_ads": "Reddit Ads",
    "microsoft_ads": "Microsoft Advertising",
}

# Normalized campaign spend written into the canonical measurement spend store
# (CampaignMeasurementWriter → SpendRepository). Bronze connector events do NOT
# carry ad spend — the measurement spend store is where these records land.
AD_DATA_OUTPUTS: list[str] = ["measurement.spend_records"]

# Each connector advances a "last_sync_date" recency cursor over daily spend.
AD_INCREMENTAL_CURSOR = "last_sync_date"

# (field name, secret?) per family — mirrored from each connector module's
# documented "Required config keys". Identifiers are non-secret strings; tokens
# and client secrets are secrets. Kept authoritative for the catalog by the
# module-read honesty tests in tests/integration_contracts/test_catalog_ads.py.
_AD_CREDENTIAL_FIELDS: dict[str, list[tuple[str, bool]]] = {
    "google_ads": [
        ("customer_id", False),
        ("developer_token", True),
        ("client_id", False),
        ("client_secret", True),
        ("refresh_token", True),
    ],
    "meta_ads": [
        ("access_token", True),
        ("ad_account_id", False),
    ],
    "tiktok_ads": [
        ("access_token", True),
        ("advertiser_id", False),
    ],
    "linkedin_ads": [
        ("access_token", True),
        ("ad_account_id", False),
    ],
    # x_ads reads access_token + account_id (Bearer-token path) at runtime. Its
    # class docstring also lists OAuth 1.0a consumer/secret keys, but the code
    # never consumes them — the schema mirrors what the connector actually reads.
    "x_ads": [
        ("access_token", True),
        ("account_id", False),
    ],
    "reddit_ads": [
        ("access_token", True),
        ("account_id", False),
    ],
    "microsoft_ads": [
        ("client_id", False),
        ("client_secret", True),
        ("refresh_token", True),
        ("customer_id", False),
        ("account_id", False),
    ],
}


def _ad_credential_schema(family: str) -> list[CredentialFieldSpec]:
    """Credential shape from the per-family table (identifiers vs secrets)."""
    return [
        CredentialFieldSpec(
            name=name,
            type="secret" if secret else "string",
            secret=secret,
        )
        for name, secret in _AD_CREDENTIAL_FIELDS[family]
    ]


def manifest_from_ad_platform(family: str) -> ProviderManifest:
    """Derive one campaign-metrics :class:`ProviderManifest` for an ad platform.

    Honesty: CREDENTIAL_WAITING → level 3 (code complete, offline-safe, awaiting
    tenant credentials) — never >=4, since no ad connector is sandbox-validated.
    Visible only in local/integration; token-paste authentication (no Aether-side
    OAuth drive yet, so no empty-scope ``oauth2`` claim); incremental daily spend
    pull on a ``last_sync_date`` cursor; no webhooks.
    """
    readiness = ManifestReadiness(
        state=CredentialReadiness.CREDENTIAL_WAITING,
        level=_READINESS_LEVEL[CredentialReadiness.CREDENTIAL_WAITING],
    )
    credential_schema = _ad_credential_schema(family)
    return ProviderManifest(
        provider_family=family,
        product_id=AD_PRODUCT_ID,
        capability_id=AD_CAPABILITY_ID,
        display_name=AD_DISPLAY_NAMES[family],
        category=AD_CATEGORY,
        readiness=readiness,
        availability=Availability(
            tenant_self_service=True,
            kyber_managed=True,
            olympus_system=False,
            environments=EnvironmentAvailability(
                local=True,
                integration=True,
                staging=False,
                production=False,
            ),
        ),
        authentication=Authentication(
            type="api_key", credential_schema=credential_schema
        ),
        configuration=Configuration(),
        accounts=Accounts(),
        webhooks=Webhooks(supported=False),
        sync=Sync(
            initial_backfill=True,
            incremental=True,
            reconciliation=False,
            cursor=AD_INCREMENTAL_CURSOR,
        ),
        data_outputs=list(AD_DATA_OUTPUTS),
        product_destinations=[],
        deployment=Deployment(
            required_secrets=[field.name for field in credential_schema if field.secret],
        ),
    )


def build_ad_platform_manifests() -> list[ProviderManifest]:
    """Derive + honesty-validate one manifest per canonical ad platform.

    Each passes :func:`validate_manifest`. Iterates :data:`AD_FAMILIES` for a
    stable catalog order; a family missing from the display/credential tables
    raises (KeyError) rather than silently shipping a half-described manifest.
    """
    return [
        validate_manifest(manifest_from_ad_platform(family)) for family in AD_FAMILIES
    ]


# Computed once at import — each ad manifest is already honesty-validated.
AD_MANIFESTS: list[ProviderManifest] = build_ad_platform_manifests()

# Ad-family lookup (connector-scoped manifest_by_family stays the BYOD catalog).
ad_manifest_by_family: dict[str, ProviderManifest] = {
    manifest.provider_family: manifest for manifest in AD_MANIFESTS
}


# ── Combined catalog ─────────────────────────────────────────────────────────

# Computed once at import — each list is already honesty-validated at build.
PAYMENT_RAIL_MANIFESTS: list[ProviderManifest] = build_payment_rail_manifests()
DEFERRED_CREDIT_BUREAU_MANIFESTS: list[ProviderManifest] = (
    build_deferred_credit_bureau_manifests()
)

# The full catalog: inbound connectors + campaign-metrics ad platforms +
# observe-only payment rails + deferred (non-tenant-visible) credit bureaus.
ALL_MANIFESTS: list[ProviderManifest] = [
    *CONNECTOR_MANIFESTS,
    *AD_MANIFESTS,
    *PAYMENT_RAIL_MANIFESTS,
    *DEFERRED_CREDIT_BUREAU_MANIFESTS,
]


def _index_by_identity(
    manifests: list[ProviderManifest],
) -> dict[str, ProviderManifest]:
    """Index manifests by canonical ``identity_key`` (family.product.capability).

    A provider *family* may legitimately appear under more than one product
    (e.g. "stripe" is both an ingestion connector and an observe-only payment
    rail), so family alone is NOT unique across the full catalog — the
    identity_key is. A collision here would mean two manifests claim the same
    capability identity; fail loudly at import rather than silently drop one.
    """
    index: dict[str, ProviderManifest] = {}
    for manifest in manifests:
        if manifest.identity_key in index:
            raise ValueError(f"duplicate manifest identity_key: {manifest.identity_key}")
        index[manifest.identity_key] = manifest
    return index


# Combined lookup keyed by identity_key (collision-checked at import).
manifest_by_identity: dict[str, ProviderManifest] = _index_by_identity(ALL_MANIFESTS)


def deferred_manifests() -> list[ProviderManifest]:
    """The honestly-DEFERRED (§26) manifests — credit bureaus, enabled nowhere."""
    return list(DEFERRED_CREDIT_BUREAU_MANIFESTS)


__all__ = [
    "AD_FAMILIES",
    "AD_DISPLAY_NAMES",
    "AD_MANIFESTS",
    "ALL_MANIFESTS",
    "CONNECTOR_MANIFESTS",
    "ad_manifest_by_family",
    "DEFAULT_DATA_OUTPUTS",
    "DEFAULT_INCREMENTAL_CURSOR",
    "DEFERRED_CREDIT_BUREAU_MANIFESTS",
    "PAYMENT_RAIL_MANIFESTS",
    "build_ad_platform_manifests",
    "build_connector_manifests",
    "build_deferred_credit_bureau_manifests",
    "build_payment_rail_manifests",
    "deferred_manifests",
    "manifest_by_family",
    "manifest_by_identity",
    "manifest_from_ad_platform",
    "manifest_from_connector_descriptor",
    "manifest_from_credit_bureau",
    "manifest_from_payment_rail_adapter",
]
