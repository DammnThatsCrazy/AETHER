"""Derived connector catalog: every manifest is honest and validates.

The catalog is a pure projection of the connector registry onto the canonical
:class:`ProviderManifest`. These tests pin the two properties that make that
projection trustworthy: it *covers* the registry, and it never claims more than
the descriptors evidence (the §32 honesty invariants).
"""

from __future__ import annotations

from services.integrations.connectors.registry import CONNECTORS
from shared.integration_contracts.catalog import (
    CONNECTOR_MANIFESTS,
    build_connector_manifests,
    manifest_by_family,
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
        # Connectors write to Bronze; downstream destinations are honestly empty.
        assert manifest.data_outputs == ["bronze.connector_events"]
        assert manifest.product_destinations == []


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
