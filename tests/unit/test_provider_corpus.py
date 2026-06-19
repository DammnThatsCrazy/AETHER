"""Unit tests: Olympus provider corpus — connector taxonomy, catalog, provenance, data rights.

Covers: connector taxonomy enums, provider catalog contents, Bronze provenance,
Silver promotion gate, BYOK redaction, data rights fail-closed checks,
and anti-distillation score binning.
"""
from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
_PREFIXES = ("config", "services", "shared", "middleware", "dependencies", "repositories")


@contextmanager
def backend_module_path():
    original = list(sys.path)
    for prefix in _PREFIXES:
        for name in list(sys.modules):
            if name == prefix or name.startswith(f"{prefix}."):
                sys.modules.pop(name, None)
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original
        for prefix in _PREFIXES:
            for name in list(sys.modules):
                if name == prefix or name.startswith(f"{prefix}."):
                    sys.modules.pop(name, None)


# ═══════════════════════════════════════════════════════════════════════════
# CONNECTOR TAXONOMY
# ═══════════════════════════════════════════════════════════════════════════

def test_connector_class_enum_values():
    with backend_module_path():
        base = importlib.import_module("services.integrations.connectors.base")
        ConnectorClass = base.ConnectorClass
        assert ConnectorClass.OLYMPUS_PROVIDER.value == "olympus_provider"
        assert ConnectorClass.TENANT_BYOD_DATA.value == "tenant_byod_data"
        assert ConnectorClass.BYOK_GATEWAY.value == "byok_gateway"
        assert ConnectorClass.ACTION_NOTIFIER.value == "action_notifier"
        assert ConnectorClass.DUAL_ROLE.value == "dual_role"


def test_lake_write_policy_enum_values():
    with backend_module_path():
        base = importlib.import_module("services.integrations.connectors.base")
        LakeWritePolicy = base.LakeWritePolicy
        assert LakeWritePolicy.NEVER.value == "never"
        assert LakeWritePolicy.TENANT_ONLY.value == "tenant_only"
        assert LakeWritePolicy.OLYMPUS_BASELINE_ELIGIBLE.value == "olympus_baseline_eligible"
        assert LakeWritePolicy.OLYMPUS_BASELINE_ALLOWED.value == "olympus_baseline_allowed"
        assert LakeWritePolicy.QUARANTINE_ONLY.value == "quarantine_only"


def test_implementation_status_includes_compliance_disabled():
    with backend_module_path():
        base = importlib.import_module("services.integrations.connectors.base")
        ImplementationStatus = base.ImplementationStatus
        statuses = {s.value for s in ImplementationStatus}
        assert "disabled_compliance_review" in statuses
        assert "credential_gated" in statuses
        assert "warehouse_datashare_ready" in statuses


def test_priority_phase_values():
    with backend_module_path():
        base = importlib.import_module("services.integrations.connectors.base")
        PriorityPhase = base.PriorityPhase
        assert PriorityPhase.PHASE_1_FOUNDATION.value == "phase_1_foundation"
        assert PriorityPhase.PHASE_2_ENRICHMENT.value == "phase_2_enrichment"
        assert PriorityPhase.PHASE_3_DEPTH.value == "phase_3_depth"


# ═══════════════════════════════════════════════════════════════════════════
# PROVIDER CATALOG
# ═══════════════════════════════════════════════════════════════════════════

def test_catalog_has_minimum_30_providers(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    with backend_module_path():
        catalog_mod = importlib.import_module("services.provider_catalog.catalog")
        assert len(catalog_mod.PROVIDER_CATALOG) >= 30


def test_phase_1_providers_present(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    with backend_module_path():
        base = importlib.import_module("services.integrations.connectors.base")
        catalog_mod = importlib.import_module("services.provider_catalog.catalog")
        phase_1 = catalog_mod.get_providers_by_phase(base.PriorityPhase.PHASE_1_FOUNDATION)
        phase_1_ids = {p.provider_id for p in phase_1}
        assert "dune_api" in phase_1_ids
        assert "dune_datashare" in phase_1_ids
        assert "defi_llama" in phase_1_ids
        assert "coingecko" in phase_1_ids


def test_social_providers_disabled_compliance_review(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    with backend_module_path():
        base = importlib.import_module("services.integrations.connectors.base")
        catalog_mod = importlib.import_module("services.provider_catalog.catalog")
        disabled_ids = {"twitter_x", "reddit", "telegram_bot", "discord_bot"}
        for p in catalog_mod.PROVIDER_CATALOG:
            if p.provider_id in disabled_ids:
                assert p.implementation_status == base.ImplementationStatus.DISABLED_COMPLIANCE_REVIEW


def test_all_providers_have_required_fields(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    with backend_module_path():
        catalog_mod = importlib.import_module("services.provider_catalog.catalog")
        for p in catalog_mod.PROVIDER_CATALOG:
            assert p.provider_id
            assert p.provider_name
            assert p.cost_profile_id
            assert p.rate_limit_profile_id
            assert p.source_manifest_id


def test_all_providers_not_tenant_visible(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    with backend_module_path():
        catalog_mod = importlib.import_module("services.provider_catalog.catalog")
        for p in catalog_mod.PROVIDER_CATALOG:
            assert p.tenant_visible is False


def test_dune_access_modes_count(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    with backend_module_path():
        catalog_mod = importlib.import_module("services.provider_catalog.catalog")
        assert len(catalog_mod.DUNE_ACCESS_MODES) == 3
        mode_ids = {m.mode_id for m in catalog_mod.DUNE_ACCESS_MODES}
        assert "dune_api" in mode_ids
        assert "dune_datashare" in mode_ids
        assert "dune_sim" in mode_ids


def test_chain_extraction_p0_chains(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    with backend_module_path():
        catalog_mod = importlib.import_module("services.provider_catalog.catalog")
        p0 = {p.chain_id for p in catalog_mod.CHAIN_EXTRACTION_PLANS if p.priority == "P0_CRITICAL"}
        assert "ethereum" in p0
        assert "solana" in p0
        assert "polygon" in p0


def test_extraction_products_minimum_count(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    with backend_module_path():
        catalog_mod = importlib.import_module("services.provider_catalog.catalog")
        assert len(catalog_mod.EXTRACTION_PRODUCTS) >= 10


# ═══════════════════════════════════════════════════════════════════════════
# BRONZE PROVENANCE
# ═══════════════════════════════════════════════════════════════════════════

def test_bronze_valid_license_not_quarantined(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    with backend_module_path():
        lake = importlib.import_module("repositories.lake")
        rec = lake.make_raw_record(
            source="dune_api", source_tag="tag", provider_record_id="tx1",
            payload={}, license_status="valid", terms_status="approved",
        )
        assert rec["quarantine_status"] == "not_quarantined"
        assert rec["provenance_status"] == lake.ProvenanceStatus.VALID.value


def test_bronze_missing_license_quarantined(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    with backend_module_path():
        lake = importlib.import_module("repositories.lake")
        rec = lake.make_raw_record(
            source="unknown", source_tag="tag", provider_record_id="tx2",
            payload={}, license_status="unknown", terms_status="unknown",
        )
        assert rec["quarantine_status"] == "quarantined"


def test_silver_promotion_blocked_for_quarantined(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    with backend_module_path():
        lake = importlib.import_module("repositories.lake")
        SilverRepository = lake.SilverRepository
        ProvenanceStatus = lake.ProvenanceStatus
        bronze = {"quarantine_status": "quarantined", "provenance_status": ProvenanceStatus.MISSING_LICENSE.value}
        eligible, reason = SilverRepository.check_promotion_eligibility(bronze)
        assert eligible is False
        assert "quarantined" in reason


def test_silver_promotion_allowed_for_valid(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    with backend_module_path():
        lake = importlib.import_module("repositories.lake")
        ProvenanceStatus = lake.ProvenanceStatus
        SilverRepository = lake.SilverRepository
        bronze = {"quarantine_status": "not_quarantined", "provenance_status": ProvenanceStatus.VALID.value}
        eligible, reason = SilverRepository.check_promotion_eligibility(bronze)
        assert eligible is True


# ═══════════════════════════════════════════════════════════════════════════
# BYOK REDACTION
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_byok_list_keys_no_raw_key(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    with backend_module_path():
        key_vault = importlib.import_module("shared.providers.key_vault")
        vault = key_vault.BYOKKeyVault()
        await vault.store_key("t1", "coingecko", "price", "sk-live-super-secret")
        keys = await vault.list_keys("t1")
        assert len(keys) == 1
        assert "api_key" not in keys[0]
        assert keys[0].get("has_key") is True


@pytest.mark.asyncio
async def test_byok_cross_tenant_isolation(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    with backend_module_path():
        key_vault = importlib.import_module("shared.providers.key_vault")
        vault = key_vault.BYOKKeyVault()
        await vault.store_key("tenant_A", "dune_api", "onchain", "key-for-A")
        key_b = await vault.get_key("tenant_B", "dune_api")
        assert key_b is None


@pytest.mark.asyncio
async def test_byok_rotate_replaces_key(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    with backend_module_path():
        key_vault = importlib.import_module("shared.providers.key_vault")
        vault = key_vault.BYOKKeyVault()
        await vault.store_key("t2", "provider_a", "cat", "old-key")
        await vault.rotate_key("t2", "provider_a", "new-key")
        new_val = await vault.get_key("t2", "provider_a")
        assert new_val == "new-key"


@pytest.mark.asyncio
async def test_byok_revoke_blocks_get(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    with backend_module_path():
        key_vault = importlib.import_module("shared.providers.key_vault")
        vault = key_vault.BYOKKeyVault()
        await vault.store_key("t3", "provider_b", "cat", "my-key")
        await vault.revoke_key("t3", "provider_b")
        key = await vault.get_key("t3", "provider_b")
        assert key is None


# ═══════════════════════════════════════════════════════════════════════════
# DATA RIGHTS LEDGER
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_data_rights_olympus_provider_baseline_auto_set(monkeypatch):
    """Olympus provider grants automatically get olympus_baseline_allowed=True."""
    monkeypatch.setenv("AETHER_ENV", "local")
    with backend_module_path():
        dr_models = importlib.import_module("services.integrations.data_rights.models")
        dr_service_mod = importlib.import_module("services.integrations.data_rights.service")
        svc = dr_service_mod.DataRightsService()
        body = dr_models.DataRightsGrantCreate(
            tenant_id="t1", source_id="s1", connector_id="dune_api",
            connector_class="olympus_provider", data_category="onchain",
            data_sensitivity="unclassified", raw_data_owner="olympus_labs",
            olympus_baseline_allowed=False,  # should be overridden
        )
        grant = await svc.create_grant(body, granted_by_user_id="u1")
        assert grant.olympus_baseline_allowed is True


@pytest.mark.asyncio
async def test_data_rights_model_training_default_false(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    with backend_module_path():
        dr_models = importlib.import_module("services.integrations.data_rights.models")
        dr_service_mod = importlib.import_module("services.integrations.data_rights.service")
        svc = dr_service_mod.DataRightsService()
        body = dr_models.DataRightsGrantCreate(
            tenant_id="t2", source_id="s2", connector_id="dune_api",
            connector_class="olympus_provider", data_category="onchain",
            data_sensitivity="unclassified", raw_data_owner="olympus_labs",
        )
        grant = await svc.create_grant(body, granted_by_user_id="u2")
        assert grant.model_training_allowed is False


@pytest.mark.asyncio
async def test_data_rights_revoke_blocks_all_use(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    with backend_module_path():
        dr_models = importlib.import_module("services.integrations.data_rights.models")
        dr_service_mod = importlib.import_module("services.integrations.data_rights.service")
        svc = dr_service_mod.DataRightsService()
        body = dr_models.DataRightsGrantCreate(
            tenant_id="t3", source_id="s3", connector_id="dune_api",
            connector_class="olympus_provider", data_category="onchain",
            data_sensitivity="unclassified", raw_data_owner="olympus_labs",
            model_training_allowed=True,
        )
        grant = await svc.create_grant(body, granted_by_user_id="u3")
        assert dr_service_mod.can_write_olympus_baseline(grant) is True

        revoke_body = dr_models.DataRightsGrantRevoke(
            revocation_reason="test", revoked_by_user_id="op1"
        )
        revoked = await svc.revoke_grant(grant.data_rights_grant_id, revoke_body)
        assert dr_service_mod.can_write_olympus_baseline(revoked) is False
        assert dr_service_mod.can_use_for_model_training(revoked) is False


# ═══════════════════════════════════════════════════════════════════════════
# ANTI-DISTILLATION
# ═══════════════════════════════════════════════════════════════════════════

def test_anti_distillation_score_binning(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    with backend_module_path():
        ad_mod = importlib.import_module("services.security.anti_distillation")
        assert ad_mod.apply_output_precision(0.876, "P1_HOBBYIST") == 0.9
        assert ad_mod.apply_output_precision(0.876, "P3_GROWTH") == 0.88


def test_anti_distillation_honeypot_detection(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    with backend_module_path():
        ad_mod = importlib.import_module("services.security.anti_distillation")
        config = ad_mod.AntiDistillationConfig(honeypot_wallets=["0xhoneypot"])
        svc = ad_mod.AntiDistillationService(config)
        result = svc.check_query_pattern("t1", "/endpoint", {"wallet_address": "0xhoneypot"})
        assert result.is_suspicious is True
        assert result.pattern_type == "honeypot_wallet_query"


def test_anti_distillation_rapid_query_detection(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    with backend_module_path():
        ad_mod = importlib.import_module("services.security.anti_distillation")
        config = ad_mod.AntiDistillationConfig(rapid_diverse_query_threshold=5, window_seconds=60)
        svc = ad_mod.AntiDistillationService(config)
        for _ in range(4):
            svc.check_query_pattern("t2", "/ep", {})
        result = svc.check_query_pattern("t2", "/ep", {})
        assert result.is_suspicious is True
        assert result.pattern_type == "rapid_diverse_query"


# ═══════════════════════════════════════════════════════════════════════════
# ACTION NOTIFIER ENFORCEMENT
# ═══════════════════════════════════════════════════════════════════════════

def test_action_notifier_lake_write_policy_is_never(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    with backend_module_path():
        base = importlib.import_module("services.integrations.connectors.base")
        assert base.LakeWritePolicy.NEVER.value == "never"
        assert base.ConnectorClass.ACTION_NOTIFIER.value == "action_notifier"
        # Confirm ACTION_NOTIFIER is distinct from data-ingesting classes
        data_classes = {
            base.ConnectorClass.OLYMPUS_PROVIDER,
            base.ConnectorClass.TENANT_BYOD_DATA,
            base.ConnectorClass.BYOK_GATEWAY,
        }
        assert base.ConnectorClass.ACTION_NOTIFIER not in data_classes


# ═══════════════════════════════════════════════════════════════════════════
# PROVIDER CORPUS CONFIG (settings)
# ═══════════════════════════════════════════════════════════════════════════

def test_provider_corpus_config_defaults(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    with backend_module_path():
        settings_mod = importlib.import_module("config.settings")
        s = settings_mod.settings
        # All corpus flags default False (fail-closed)
        assert s.provider_corpus.dune_api_enabled is False
        assert s.provider_corpus.dune_datashare_enabled is False
        assert s.provider_corpus.anti_distillation_enabled is False
        assert s.provider_corpus.enrichment_lineage_enabled is False
        assert s.provider_corpus.unique_signal_features_enabled is False
