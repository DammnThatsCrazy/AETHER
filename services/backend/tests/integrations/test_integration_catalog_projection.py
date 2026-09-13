"""Unified catalog read-model projection (R1 spine endpoints).

The /v1/integration-catalog, /v1/tenant-integrations, and
/v1/integration-readiness endpoints are thin projections over the derived
manifests + tenant connector records. These tests pin the *pure projection
helpers* (no HTTP/auth harness needed): coverage of the four catalog groups,
honest readiness reuse, and tenant-connection facts that never overclaim.
"""

from __future__ import annotations

from shared.certification.readiness import CredentialReadiness, readiness_rank
from shared.integration_contracts.catalog import (
    AD_MANIFESTS,
    ALL_MANIFESTS,
    CONNECTOR_MANIFESTS,
    DEFERRED_CREDIT_BUREAU_MANIFESTS,
    PAYMENT_RAIL_MANIFESTS,
)
from shared.integration_contracts.experience import (
    EXPERIENCE_CATEGORIES,
    ExperienceCategory,
)
from services.integrations.connectors.catalog_endpoints import (
    _manifest_entry,
    _tenant_integration_entry,
    _visible_catalog_entries,
)

# The ladder tokens CredentialReadiness may emit (its values are the single
# source; the projection must never invent a readiness word).
_READINESS_VALUES = {r.value for r in CredentialReadiness}
_EXPERIENCE_VALUES = {c.value for c in ExperienceCategory}


def _visible(manifests) -> list:
    return [m for m in manifests if m.availability.environments.any_enabled()]


def test_visible_catalog_covers_each_connectable_group_exactly() -> None:
    entries = _visible_catalog_entries()
    # Deferred bureaus are enabled-in-no-env, so they are the only group that
    # must be absent from a connectable catalog.
    assert {e["key"] for e in entries} == {
        m.identity_key for m in _visible(ALL_MANIFESTS)
    }
    by_source = {e["key"]: e["source"] for e in entries}
    for manifest in _visible(CONNECTOR_MANIFESTS):
        assert by_source[manifest.identity_key] == "byod_connector"
    for manifest in AD_MANIFESTS:
        assert by_source[manifest.identity_key] == "ad_platform"
    for manifest in _visible(PAYMENT_RAIL_MANIFESTS):
        assert by_source[manifest.identity_key] == "payment_rail"
    # No deferred bureau leaks into the connectable catalog.
    for manifest in DEFERRED_CREDIT_BUREAU_MANIFESTS:
        assert manifest.identity_key not in by_source


def test_every_catalog_entry_is_honest_and_typed() -> None:
    for entry in _visible_catalog_entries():
        assert entry["tenant_self_service"] is True
        assert entry["environments"], "visible entry must name enabled envs"
        assert entry["readiness"]["state"] in _READINESS_VALUES
        assert entry["readiness"]["rank"] == readiness_rank(
            CredentialReadiness(entry["readiness"]["state"])
        )
        assert 1 <= entry["readiness"]["level"] <= 5
        # Visible material is never below the credential-waiting tier.
        assert entry["readiness"]["level"] >= 3
        # A connectable entry always lands in exactly one customer experience.
        assert entry["experience_category"] in _EXPERIENCE_VALUES


def test_ad_platforms_and_rails_project_to_their_experience() -> None:
    entries = {e["key"]: e for e in _visible_catalog_entries()}
    for manifest in AD_MANIFESTS:
        assert entries[manifest.identity_key]["experience_category"] == (
            ExperienceCategory.ADVERTISING_CAMPAIGNS.value
        )
    for manifest in _visible(PAYMENT_RAIL_MANIFESTS):
        assert entries[manifest.identity_key]["experience_category"] == (
            ExperienceCategory.COMMERCE_REVENUE.value
        )


def test_catalog_entries_are_stable_grouped_by_experience_order() -> None:
    entries = _visible_catalog_entries()
    order = [c.value for c in EXPERIENCE_CATEGORIES]
    ranks = [order.index(e["experience_category"]) for e in entries]
    assert ranks == sorted(ranks), "entries must follow experience order"
    # Advertising leads the connectable catalog (ads + ad-classified connectors).
    assert entries[0]["experience_category"] == "advertising_campaigns"


def test_manifest_entry_keys_are_canonical_identities() -> None:
    entries = {e["key"]: e for e in _visible_catalog_entries()}
    assert entries["meta_ads.ads.metrics"]["family"] == "meta_ads"
    assert entries["shopify.ingestion.connector"]["source"] == "byod_connector"


def test_tenant_integration_entry_reports_facts_not_readiness_claims() -> None:
    row = {
        "connector_type": "shopify",
        "label": "Shopify",
        "enabled": True,
        "secret_configured": True,
        "sync_status": "success",
        "last_synced_at": "2026-09-04T00:00:00Z",
        "name": "My Shop",
    }
    entry = _tenant_integration_entry("shopify", row)
    assert entry["id"] == "shopify"
    assert entry["display_name"] == "Shopify"
    assert entry["experience_category"] == ExperienceCategory.COMMERCE_REVENUE.value
    assert entry["connected"] is True
    assert entry["enabled"] is True
    assert entry["secret_configured"] is True
    assert entry["sync_status"] == "success"
    assert entry["last_synced_at"] == "2026-09-04T00:00:00Z"
    # Readiness is the manifest's catalog baseline, and honest about it.
    assert entry["readiness"]["state"] == "credential_waiting"
    assert entry["readiness"]["level"] == 3


def test_tenant_integration_entry_unconfigured_is_not_connected() -> None:
    row = {
        "connector_type": "slack",
        "label": "Slack",
        "enabled": False,
        "secret_configured": False,
        "sync_status": "never_synced",
        "last_synced_at": None,
        "name": "Slack",
    }
    entry = _tenant_integration_entry("slack", row)
    assert entry["connected"] is False
    assert entry["sync_status"] == "never_synced"
    assert entry["last_synced_at"] is None
    # Even unconnected, the manifest baseline is present (a fact, not a claim).
    assert entry["readiness"]["state"] in _READINESS_VALUES


def test_manifest_entry_is_pure_and_serializable() -> None:
    manifest = next(m for m in AD_MANIFESTS if m.provider_family == "google_ads")
    entry = _manifest_entry(manifest)
    assert isinstance(entry["key"], str)
    assert isinstance(entry["readiness"]["rank"], int)
    assert isinstance(entry["data_outputs"], list)
    assert entry["data_outputs"] == ["measurement.spend_records"]
