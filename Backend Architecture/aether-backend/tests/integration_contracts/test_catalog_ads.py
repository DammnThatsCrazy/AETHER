"""Measurement ad-platform catalog: honest manifests + runtime mirror guard.

The seven measurement ad connectors (services/measurement/connectors/*_ads) are
projected into the unified catalog as ``family.ads.metrics`` manifests
(ADR-0008 one-customer-catalog). These tests pin that projection's honesty:

* every manifest validates and claims no more than level 3 / local+integration;
* the per-family credential field table in catalog.py mirrors what each runtime
  connector module actually reads via ``config`` (the AST guard below) so a
  drift between the catalog schema and the connector code fails loudly;
* families are the canonical ids the measurement runtime keys on, never the
  legacy alias names (twitter_ads &c. resolve onto them via the alias map).

The guards parse the connector module *source* rather than importing it, so a
credential-schema regression is caught without pulling the runtime's import
graph into a contract test.
"""

from __future__ import annotations

import ast
import pathlib

from shared.integration_contracts.aliases import (
    ALIAS_ONLY_FAMILIES,
    canonical_family_id,
)
from shared.integration_contracts.catalog import (
    AD_DISPLAY_NAMES,
    AD_FAMILIES,
    AD_MANIFESTS,
    ALL_MANIFESTS,
    ad_manifest_by_family,
    build_ad_platform_manifests,
    manifest_by_identity,
    manifest_from_ad_platform,
)
from shared.integration_contracts.experience import (
    ExperienceCategory,
    experience_category_for,
)
from shared.integration_contracts.manifest import (
    ProviderManifest,
    validate_manifest,
)

# Root of the ad runtime modules relative to this test file
# (<backend>/tests/integration_contracts/test_catalog_ads.py → backend root).
_BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CONNECTORS_DIR = _BACKEND_ROOT / "services" / "measurement" / "connectors"


def _module_ast(family: str) -> ast.Module:
    """Parse one measurement connector module's source (never imports it)."""
    module_path = _CONNECTORS_DIR / f"{family}.py"
    assert module_path.is_file(), f"no runtime module for ad family {family!r}"
    return ast.parse(module_path.read_text(encoding="utf-8"))


def _runtime_connector_type(family: str) -> str:
    """The module's ``_CONNECTOR_TYPE`` constant, read from source."""
    for node in ast.walk(_module_ast(family)):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "_CONNECTOR_TYPE"
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return node.value.value
    raise AssertionError(f"{family} module has no _CONNECTOR_TYPE constant")


def _runtime_config_keys(family: str) -> set[str]:
    """Every config key the runtime module reads (``config.get("k")`` literals
    and ``config["k"]`` subscripts), collected from source."""
    keys: set[str] = set()
    for node in ast.walk(_module_ast(family)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            keys.add(node.args[0].value)
        elif (
            isinstance(node, ast.Subscript)
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        ):
            keys.add(node.slice.value)
    return keys


def _ad_by_family() -> dict[str, ProviderManifest]:
    return {m.provider_family: m for m in AD_MANIFESTS}


# ── Coverage + identity ───────────────────────────────────────────────────────


def test_seven_ad_platforms_are_present_and_validate() -> None:
    assert len(AD_MANIFESTS) == 7
    assert {m.provider_family for m in AD_MANIFESTS} == set(AD_FAMILIES)
    assert set(ad_manifest_by_family) == set(AD_FAMILIES)
    for manifest in AD_MANIFESTS:
        assert validate_manifest(manifest) is manifest


def test_ad_identity_is_family_ads_metrics() -> None:
    for family in AD_FAMILIES:
        manifest = ad_manifest_by_family[family]
        assert manifest.product_id == "ads"
        assert manifest.capability_id == "metrics"
        assert manifest.identity_key == f"{family}.ads.metrics"
        assert manifest.category == "ad_platform"
        assert manifest.display_name == AD_DISPLAY_NAMES[family]


def test_display_names_and_family_tables_cover_each_other() -> None:
    assert set(AD_DISPLAY_NAMES) == set(AD_FAMILIES) == set(ad_manifest_by_family)
    # Display names are the provider product names; no empty/duplicated labels.
    values = list(AD_DISPLAY_NAMES.values())
    assert all(values)
    assert len(values) == len(set(values))


def test_legacy_alias_names_resolve_into_real_ad_families() -> None:
    # twitter_ads/facebook_ads/bing_ads are legacy boundary ids; the catalog
    # keys on the canonical runtime families they resolve to.
    assert "twitter_ads" not in AD_FAMILIES
    assert canonical_family_id("twitter_ads") == "x_ads"
    assert "x_ads" in AD_FAMILIES
    # Alias-only (unbacked) public names are never catalog families.
    for unbacked in ALIAS_ONLY_FAMILIES:
        assert unbacked not in AD_FAMILIES


def test_rebuilding_ad_manifests_is_deterministic() -> None:
    rebuilt = build_ad_platform_manifests()
    assert [m.identity_key for m in rebuilt] == [
        m.identity_key for m in AD_MANIFESTS
    ]


def test_builder_rejects_an_unknown_family() -> None:
    try:
        manifest_from_ad_platform("snapchat_ads")  # no backed runtime
    except KeyError:
        return
    raise AssertionError("unknown ad family must raise KeyError, not ship")


# ── Honesty (§32): readiness + availability ──────────────────────────────────


def test_ad_manifests_are_level_3_credential_waiting() -> None:
    for manifest in AD_MANIFESTS:
        assert manifest.readiness.level == 3
        assert manifest.readiness.level < 4
        assert manifest.readiness.state.value == "credential_waiting"


def test_ad_manifests_visible_only_in_local_and_integration() -> None:
    for manifest in AD_MANIFESTS:
        envs = manifest.availability.environments
        assert envs.local is True and envs.integration is True
        assert envs.staging is False and envs.production is False
        avail = manifest.availability
        assert avail.tenant_self_service is True
        assert avail.kyber_managed is True
        assert avail.olympus_system is False


def test_ad_manifests_claim_no_account_discovery() -> None:
    # The connect runtime + account discovery are later workstreams; today the
    # tenant supplies the ad account id as a credential field.
    for manifest in AD_MANIFESTS:
        assert manifest.accounts.discovery_supported is False
        assert manifest.accounts.selection_required is False


# ── Behaviour shape ──────────────────────────────────────────────────────────


def test_ad_manifests_are_pull_based_daily_incremental_no_webhooks() -> None:
    for manifest in AD_MANIFESTS:
        assert manifest.webhooks.supported is False
        assert manifest.sync.incremental is True
        assert manifest.sync.cursor == "last_sync_date"
        assert manifest.sync.initial_backfill is True
        assert manifest.sync.reconciliation is False


def test_ad_outputs_name_the_measurement_spend_store() -> None:
    for manifest in AD_MANIFESTS:
        assert manifest.data_outputs == ["measurement.spend_records"]
        assert manifest.product_destinations == []


def test_ad_authentication_is_token_paste_and_secrets_match_schema() -> None:
    for manifest in AD_MANIFESTS:
        assert manifest.authentication.type == "api_key"
        # deployment.required_secrets names the SECRET schema fields (identifiers
        # like customer_id/ad_account_id are required but not secrets).
        expected = [f.name for f in manifest.authentication.credential_schema if f.secret]
        assert manifest.deployment.required_secrets == expected


# ── Experience projection ────────────────────────────────────────────────────


def test_every_ad_manifest_derives_advertising_campaigns() -> None:
    for manifest in AD_MANIFESTS:
        assert experience_category_for(manifest) == (
            ExperienceCategory.ADVERTISING_CAMPAIGNS
        )


# ── Runtime mirror guard (catalog schema ↔ measurement connector source) ─────


def test_ad_families_match_runtime_connector_types() -> None:
    for family in AD_FAMILIES:
        assert _runtime_connector_type(family) == family, (
            f"catalog family {family!r} ≠ module _CONNECTOR_TYPE"
        )


def test_credential_fields_are_actually_read_by_the_runtime() -> None:
    # Every credential field the catalog declares for a family must be a key the
    # connector module actually reads — otherwise the schema describes a field
    # the runtime ignores (fabricated credential), which is exactly the drift
    # the derived-catalog pattern exists to catch.
    for family, manifest in _ad_by_family().items():
        declared = {f.name for f in manifest.authentication.credential_schema}
        read = _runtime_config_keys(family)
        missing = declared - read
        assert not missing, (
            f"{family} catalog declares credential fields the runtime never "
            f"reads: {sorted(missing)}"
        )


# ── Full-catalog integration ─────────────────────────────────────────────────


def test_ad_manifests_are_part_of_the_full_catalog() -> None:
    for manifest in AD_MANIFESTS:
        assert manifest in ALL_MANIFESTS
        assert manifest_by_identity[manifest.identity_key] is manifest


def test_ad_identity_keys_do_not_collide_with_other_catalog_entries() -> None:
    keys = {m.identity_key for m in ALL_MANIFESTS}
    assert len(keys) == len(ALL_MANIFESTS)
