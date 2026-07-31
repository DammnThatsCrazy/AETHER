"""Derived connector catalog: every manifest is honest and validates.

The catalog is a pure projection of the connector registry onto the canonical
:class:`ProviderManifest`. These tests pin the two properties that make that
projection trustworthy: it *covers* the registry, and it never claims more than
the descriptors evidence (the §32 honesty invariants).
"""

from __future__ import annotations

from services.integrations.connectors.registry import CONNECTORS
from shared.integration_contracts.catalog import (
    ALL_MANIFESTS,
    CONNECTOR_MANIFESTS,
    DEFERRED_CREDIT_BUREAU_MANIFESTS,
    PAYMENT_RAIL_MANIFESTS,
    build_connector_manifests,
    build_deferred_credit_bureau_manifests,
    build_payment_rail_manifests,
    deferred_manifests,
    manifest_by_family,
    manifest_by_identity,
    manifest_from_connector_descriptor,
)
from shared.integration_contracts.manifest import (
    ProviderManifest,
    validate_manifest,
)

# Representative inbound connectors we require the registry to keep exposing.
_EXPECTED_FAMILIES = {
    "slack",
    "shopify",
    "stripe",
    "hubspot",
    "ga4",
    "jira",
    "dune",
    "klaviyo",
}


def test_catalog_is_non_empty_and_covers_the_registry() -> None:
    assert CONNECTOR_MANIFESTS, "catalog must derive at least one manifest"
    # One manifest per registered connector — no drops, no duplicates.
    assert len(CONNECTOR_MANIFESTS) == len(CONNECTORS)
    families = {m.provider_family for m in CONNECTOR_MANIFESTS}
    assert len(families) == len(CONNECTOR_MANIFESTS), "provider_family must be unique"
    assert set(manifest_by_family) == families


def test_representative_connectors_are_present() -> None:
    families = set(manifest_by_family)
    missing = _EXPECTED_FAMILIES - families
    assert not missing, f"expected connectors absent from catalog: {sorted(missing)}"


def test_every_manifest_passes_validate_manifest() -> None:
    # build_connector_manifests already validates; assert it explicitly so a
    # regression that weakens the build surfaces here too.
    for manifest in CONNECTOR_MANIFESTS:
        assert validate_manifest(manifest) is manifest


def test_rebuilding_is_deterministic() -> None:
    rebuilt = build_connector_manifests()
    assert [m.identity_key for m in rebuilt] == [
        m.identity_key for m in CONNECTOR_MANIFESTS
    ]


def test_identity_shape_is_canonical() -> None:
    for manifest in CONNECTOR_MANIFESTS:
        assert manifest.product_id == "ingestion"
        assert manifest.capability_id == "connector"
        assert manifest.identity_key == (
            f"{manifest.provider_family}.ingestion.connector"
        )
        # Every manifest declares at least one output (honesty invariant).
        assert manifest.data_outputs, f"{manifest.provider_family} declares no outputs"
        # A connector is either generic (writes only to Bronze, no downstream
        # product destination) or declares a richer capability surface (e.g. the
        # comms adapters project campaigns/messages/replies into Campaign360 /
        # Profile360). A manifest may not claim product destinations without also
        # declaring the domain outputs that feed them.
        if manifest.data_outputs == ["bronze.connector_events"]:
            assert manifest.product_destinations == []
        else:
            assert manifest.product_destinations, (
                f"{manifest.provider_family} declares domain outputs but no "
                "product destination"
            )


# ── Honesty guards (§32) ─────────────────────────────────────────────────────


def test_no_manifest_claims_staging_or_production() -> None:
    for manifest in CONNECTOR_MANIFESTS:
        envs = manifest.availability.environments
        assert envs.staging is False, f"{manifest.provider_family} claims staging"
        assert envs.production is False, f"{manifest.provider_family} claims production"


def test_no_manifest_claims_level_4_or_higher() -> None:
    # Current reality: nothing is sandbox-validated yet, so no manifest may
    # claim a productization level >= 4.
    for manifest in CONNECTOR_MANIFESTS:
        assert manifest.readiness.level < 4, (
            f"{manifest.provider_family} claims level {manifest.readiness.level}"
        )


def test_visible_connectors_are_at_least_level_3() -> None:
    for manifest in CONNECTOR_MANIFESTS:
        if manifest.availability.environments.any_enabled():
            assert manifest.readiness.level >= 3


def test_oauth2_manifests_declare_non_empty_scopes() -> None:
    for manifest in CONNECTOR_MANIFESTS:
        if manifest.authentication.type == "oauth2":
            oauth = manifest.authentication.oauth
            assert oauth is not None and oauth.scopes, (
                f"{manifest.provider_family} oauth2 without scopes"
            )


def test_webhook_supported_manifests_declare_a_verification_scheme() -> None:
    for manifest in CONNECTOR_MANIFESTS:
        if manifest.webhooks.supported:
            scheme = manifest.webhooks.verification_scheme
            assert scheme and scheme.strip(), (
                f"{manifest.provider_family} webhook without verification_scheme"
            )


def test_incremental_manifests_declare_a_cursor() -> None:
    for manifest in CONNECTOR_MANIFESTS:
        if manifest.sync.incremental:
            cursor = manifest.sync.cursor
            assert cursor and cursor.strip(), (
                f"{manifest.provider_family} incremental sync without a cursor"
            )


def test_required_secrets_match_the_credential_schema() -> None:
    for manifest in CONNECTOR_MANIFESTS:
        expected = [f.name for f in manifest.authentication.credential_schema]
        assert manifest.deployment.required_secrets == expected


# ── Per-connector spot checks (the projection is faithful) ───────────────────


def test_webhook_only_connector_maps_to_webhook_only_auth() -> None:
    # Slack receives events and has no pull API → webhook_only.
    slack = manifest_by_family["slack"]
    assert slack.authentication.type == "webhook_only"
    assert slack.webhooks.supported is True
    assert slack.sync.incremental is False


def test_native_webhook_scheme_is_used_when_known() -> None:
    assert manifest_by_family["shopify"].webhooks.verification_scheme == "shopify_hmac"
    assert manifest_by_family["stripe"].webhooks.verification_scheme == "stripe_signature"
    assert manifest_by_family["jira"].webhooks.verification_scheme == "jira_hub_signature"


def test_pull_connector_is_incremental_with_cursor() -> None:
    # Dune is a pull-only analytics provider (no webhook).
    dune = manifest_by_family["dune"]
    assert dune.authentication.type == "api_key"
    assert dune.webhooks.supported is False
    assert dune.sync.incremental is True
    assert dune.sync.cursor == "updated_at"


def test_klaviyo_declares_initial_backfill() -> None:
    # Klaviyo is the one connector that declares supports_historical_backfill.
    klaviyo = manifest_by_family["klaviyo"]
    assert klaviyo.sync.initial_backfill is True
    assert klaviyo.sync.incremental is True


def test_mapper_is_pure_for_a_single_descriptor() -> None:
    descriptor = CONNECTORS["stripe"].descriptor()
    manifest = manifest_from_connector_descriptor(descriptor)
    assert isinstance(manifest, ProviderManifest)
    assert manifest.provider_family == "stripe"
    assert manifest.display_name == descriptor.label
    assert manifest.category == descriptor.category


# ── Payment rails (observe-only) ─────────────────────────────────────────────

# The five named payment rails Aether OBSERVES (real registry keys — the Stripe
# adapter registers as "stripe", not "stripe_onramp").
_EXPECTED_PAYMENT_RAILS = {"privy", "stripe", "coinbase", "moonpay", "bridge"}
# Real polling rails (advance a cursor); the other two are webhook-only.
_POLLING_RAILS = {"coinbase", "moonpay", "bridge"}
_WEBHOOK_ONLY_RAILS = {"privy", "stripe"}

_rail_by_family = {m.provider_family: m for m in PAYMENT_RAIL_MANIFESTS}


def test_all_five_payment_rails_are_present() -> None:
    assert len(PAYMENT_RAIL_MANIFESTS) == 5
    assert set(_rail_by_family) == _EXPECTED_PAYMENT_RAILS


def test_payment_rail_manifests_validate() -> None:
    for manifest in PAYMENT_RAIL_MANIFESTS:
        assert validate_manifest(manifest) is manifest


def test_payment_rails_are_observe_only_identity() -> None:
    for manifest in PAYMENT_RAIL_MANIFESTS:
        assert manifest.product_id == "payment_rails"
        # "observe": the platform never moves, settles, or custodies funds.
        assert manifest.capability_id == "observe"
        assert manifest.category == "payments"
        assert manifest.data_outputs == ["bronze.payment_rail_events"]
        assert manifest.product_destinations == []


def test_payment_rails_are_level_3_credential_waiting() -> None:
    for manifest in PAYMENT_RAIL_MANIFESTS:
        # Credential-gated observability V1: level 3, never sandbox+ (>=4).
        assert manifest.readiness.level == 3
        assert manifest.readiness.level < 4
        assert manifest.readiness.state.value == "credential_waiting"


def test_payment_rails_never_claim_staging_or_production() -> None:
    for manifest in PAYMENT_RAIL_MANIFESTS:
        envs = manifest.availability.environments
        assert envs.local is True and envs.integration is True
        assert envs.staging is False and envs.production is False
        avail = manifest.availability
        assert avail.tenant_self_service is True
        assert avail.kyber_managed is True
        assert avail.olympus_system is False


def test_payment_rail_webhooks_declare_a_verification_scheme() -> None:
    for manifest in PAYMENT_RAIL_MANIFESTS:
        assert manifest.webhooks.supported is True
        assert manifest.webhooks.registration_supported is False
        scheme = manifest.webhooks.verification_scheme
        assert scheme and scheme.strip()


def test_webhook_only_rails_map_to_webhook_only_auth_and_no_incremental() -> None:
    for family in _WEBHOOK_ONLY_RAILS:
        manifest = _rail_by_family[family]
        assert manifest.authentication.type == "webhook_only"
        assert manifest.sync.incremental is False
        assert manifest.sync.cursor is None
        assert manifest.deployment.required_secrets == ["webhook_secret"]


def test_polling_rails_map_to_api_key_auth_and_incremental_cursor() -> None:
    for family in _POLLING_RAILS:
        manifest = _rail_by_family[family]
        assert manifest.authentication.type == "api_key"
        assert manifest.sync.incremental is True
        assert manifest.sync.cursor == "created"
        # Polling rails carry the webhook secret plus a provider API key.
        assert manifest.deployment.required_secrets[0] == "webhook_secret"
        assert len(manifest.deployment.required_secrets) == 2


def test_payment_rail_required_secrets_match_the_credential_schema() -> None:
    for manifest in PAYMENT_RAIL_MANIFESTS:
        expected = [f.name for f in manifest.authentication.credential_schema]
        assert manifest.deployment.required_secrets == expected


def test_building_payment_rails_is_deterministic() -> None:
    rebuilt = build_payment_rail_manifests()
    assert [m.identity_key for m in rebuilt] == [
        m.identity_key for m in PAYMENT_RAIL_MANIFESTS
    ]


# ── Deferred credit bureaus (§26) ────────────────────────────────────────────

_EXPECTED_BUREAUS = {"experian", "equifax", "transunion"}
_bureau_by_family = {m.provider_family: m for m in DEFERRED_CREDIT_BUREAU_MANIFESTS}


def test_all_three_bureaus_are_present_and_validate() -> None:
    assert len(DEFERRED_CREDIT_BUREAU_MANIFESTS) == 3
    assert set(_bureau_by_family) == _EXPECTED_BUREAUS
    for manifest in DEFERRED_CREDIT_BUREAU_MANIFESTS:
        assert validate_manifest(manifest) is manifest


def test_bureaus_are_deferred_hidden_and_scaffolded() -> None:
    for manifest in DEFERRED_CREDIT_BUREAU_MANIFESTS:
        assert manifest.product_id == "credit"
        assert manifest.capability_id == "report"
        assert manifest.category == "credit_bureau"
        # DEFERRED: scaffolded (level 1), tenant-hidden, enabled in NO env.
        assert manifest.readiness.level == 1
        assert manifest.readiness.state.value == "scaffolded"
        avail = manifest.availability
        assert avail.tenant_self_service is False
        assert avail.kyber_managed is False
        assert avail.olympus_system is False
        envs = avail.environments
        assert envs.any_enabled() is False
        assert (envs.local, envs.integration, envs.staging, envs.production) == (
            False,
            False,
            False,
            False,
        )
        # Claims nothing downstream; no webhooks; no sync.
        assert manifest.data_outputs == []
        assert manifest.product_destinations == []
        assert manifest.webhooks.supported is False
        assert manifest.sync.incremental is False
        assert manifest.sync.initial_backfill is False


def test_bureaus_record_the_activation_gate() -> None:
    for manifest in DEFERRED_CREDIT_BUREAU_MANIFESTS:
        steps = manifest.deployment.provider_registration_steps
        assert steps, "deferred bureau must record its activation gate"
        joined = " ".join(steps).lower()
        for token in ("legal", "consent", "security", "commercial", "certification"):
            assert token in joined, f"activation gate missing '{token}'"


def test_deferred_manifests_accessor_returns_the_bureaus() -> None:
    assert deferred_manifests() == DEFERRED_CREDIT_BUREAU_MANIFESTS
    assert build_deferred_credit_bureau_manifests() == DEFERRED_CREDIT_BUREAU_MANIFESTS


# ── Combined catalog + honesty sweep over ALL_MANIFESTS ──────────────────────


def test_all_manifests_is_the_union_of_the_three_groups() -> None:
    assert len(ALL_MANIFESTS) == (
        len(CONNECTOR_MANIFESTS)
        + len(PAYMENT_RAIL_MANIFESTS)
        + len(DEFERRED_CREDIT_BUREAU_MANIFESTS)
    )


def test_identity_keys_are_unique_across_the_full_catalog() -> None:
    # A family can span multiple products (e.g. "stripe" connector + rail); the
    # identity_key is what must be unique. manifest_by_identity is built with a
    # collision check, so it must cover every manifest.
    keys = [m.identity_key for m in ALL_MANIFESTS]
    assert len(keys) == len(set(keys)), "identity_key collision in the catalog"
    assert set(manifest_by_identity) == set(keys)
    assert len(manifest_by_identity) == len(ALL_MANIFESTS)


def test_manifest_by_family_still_covers_the_connectors() -> None:
    # The connector-scoped family lookup keeps working unchanged.
    assert set(manifest_by_family) == {m.provider_family for m in CONNECTOR_MANIFESTS}


def test_honesty_sweep_visible_requires_level_3_and_validates() -> None:
    for manifest in ALL_MANIFESTS:
        assert validate_manifest(manifest) is manifest
        if manifest.availability.environments.any_enabled():
            assert manifest.readiness.level >= 3, (
                f"{manifest.identity_key} visible but level "
                f"{manifest.readiness.level}"
            )


def test_honesty_sweep_no_bureau_is_tenant_visible() -> None:
    for manifest in ALL_MANIFESTS:
        if manifest.category == "credit_bureau":
            assert manifest.availability.tenant_self_service is False
            assert manifest.availability.environments.any_enabled() is False


def test_honesty_sweep_no_payment_rail_over_claims() -> None:
    for manifest in ALL_MANIFESTS:
        if manifest.product_id == "payment_rails":
            assert manifest.capability_id == "observe"
            assert manifest.readiness.level < 4
            assert manifest.availability.environments.staging is False
            assert manifest.availability.environments.production is False
