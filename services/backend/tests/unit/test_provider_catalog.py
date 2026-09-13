"""Unit tests: Olympus provider source catalog."""
from __future__ import annotations

import pytest

from services.integrations.connectors.base import (
    ConnectorClass,
    ImplementationStatus,
    PriorityPhase,
)
from services.provider_catalog.catalog import (
    CHAIN_EXTRACTION_PLANS,
    DUNE_ACCESS_MODES,
    EXTRACTION_PRODUCTS,
    PROVIDER_CATALOG,
    get_cost_profile,
    get_enabled_providers,
    get_provider,
    get_providers_by_category,
    get_providers_by_phase,
    get_rate_limit_profile,
)


def test_catalog_has_minimum_providers():
    assert len(PROVIDER_CATALOG) >= 30


def test_all_catalog_entries_have_required_fields():
    for p in PROVIDER_CATALOG:
        assert p.provider_id, f"{p.provider_name} missing provider_id"
        assert p.provider_name, f"{p.provider_id} missing provider_name"
        assert p.provider_category, f"{p.provider_id} missing provider_category"
        assert p.source_category, f"{p.provider_id} missing source_category"
        assert p.cost_profile_id, f"{p.provider_id} missing cost_profile_id"
        assert p.rate_limit_profile_id, f"{p.provider_id} missing rate_limit_profile_id"
        assert p.source_manifest_id, f"{p.provider_id} missing source_manifest_id"


def test_all_catalog_entries_are_olympus_provider_class():
    for p in PROVIDER_CATALOG:
        assert p.connector_class == ConnectorClass.OLYMPUS_PROVIDER, (
            f"{p.provider_id} should be OLYMPUS_PROVIDER class"
        )


def test_all_catalog_entries_not_tenant_visible():
    for p in PROVIDER_CATALOG:
        assert p.tenant_visible is False, f"{p.provider_id} should not be tenant visible"


def test_phase_1_providers_present():
    phase_1 = get_providers_by_phase(PriorityPhase.PHASE_1_FOUNDATION)
    phase_1_ids = {p.provider_id for p in phase_1}
    assert "dune_api" in phase_1_ids
    assert "dune_datashare" in phase_1_ids
    assert "defi_llama" in phase_1_ids
    assert "coingecko" in phase_1_ids
    assert "polymarket_gamma" in phase_1_ids
    assert "kalshi" in phase_1_ids
    assert "binance_public" in phase_1_ids


def test_phase_2_providers_present():
    phase_2 = get_providers_by_phase(PriorityPhase.PHASE_2_ENRICHMENT)
    phase_2_ids = {p.provider_id for p in phase_2}
    assert "etherscan" in phase_2_ids
    assert "farcaster_neynar" in phase_2_ids
    assert "ens_public" in phase_2_ids


def test_social_providers_disabled_compliance_review():
    disabled = {
        "twitter_x", "reddit", "telegram_bot", "discord_bot",
    }
    for p in PROVIDER_CATALOG:
        if p.provider_id in disabled:
            assert p.implementation_status == ImplementationStatus.DISABLED_COMPLIANCE_REVIEW, (
                f"{p.provider_id} should be DISABLED_COMPLIANCE_REVIEW"
            )


def test_get_provider_by_id():
    p = get_provider("dune_api")
    assert p is not None
    assert p.provider_id == "dune_api"


def test_get_provider_nonexistent():
    p = get_provider("nonexistent_provider_xyz")
    assert p is None


def test_get_providers_by_category():
    onchain = get_providers_by_category("onchain")
    assert len(onchain) > 0
    for p in onchain:
        assert p.provider_category == "onchain"


def test_enabled_providers_excludes_disabled():
    enabled = get_enabled_providers()
    disabled_ids = {p.provider_id for p in PROVIDER_CATALOG
                    if p.implementation_status == ImplementationStatus.DISABLED_COMPLIANCE_REVIEW}
    enabled_ids = {p.provider_id for p in enabled}
    for did in disabled_ids:
        assert did not in enabled_ids


def test_cost_profiles_defined_for_all_providers():
    for p in PROVIDER_CATALOG:
        profile = get_cost_profile(p.cost_profile_id)
        assert profile is not None, f"Missing cost profile: {p.cost_profile_id}"
        assert profile.cost_profile_id == p.cost_profile_id


def test_rate_limit_profiles_defined_for_all_providers():
    for p in PROVIDER_CATALOG:
        profile = get_rate_limit_profile(p.rate_limit_profile_id)
        assert profile is not None, f"Missing rate limit profile: {p.rate_limit_profile_id}"


def test_dune_access_modes():
    assert len(DUNE_ACCESS_MODES) == 3
    mode_ids = {m.mode_id for m in DUNE_ACCESS_MODES}
    assert "dune_api" in mode_ids
    assert "dune_datashare" in mode_ids
    assert "dune_sim" in mode_ids


def test_dune_datashare_mode_warehouse():
    datashare = next(m for m in DUNE_ACCESS_MODES if m.mode_id == "dune_datashare")
    assert datashare.supports_warehouse_datashare is True
    assert datashare.supports_historical_backfill is True


def test_chain_extraction_plans_have_p0_chains():
    p0 = [p for p in CHAIN_EXTRACTION_PLANS if p.priority == "P0_CRITICAL"]
    p0_ids = {p.chain_id for p in p0}
    assert "ethereum" in p0_ids
    assert "solana" in p0_ids
    assert "polygon" in p0_ids
    assert "arbitrum" in p0_ids
    assert "base" in p0_ids


def test_chain_extraction_plans_have_p1_chains():
    p1 = [p for p in CHAIN_EXTRACTION_PLANS if p.priority == "P1_HIGH"]
    p1_ids = {p.chain_id for p in p1}
    assert "optimism" in p1_ids
    assert "avalanche" in p1_ids


def test_extraction_products_count():
    assert len(EXTRACTION_PRODUCTS) >= 10


def test_extraction_products_have_dedupe_keys():
    for prod in EXTRACTION_PRODUCTS:
        assert prod.dedupe_key, f"Missing dedupe_key for {prod.product_id}"
        assert prod.product_id
        assert prod.source_tables
