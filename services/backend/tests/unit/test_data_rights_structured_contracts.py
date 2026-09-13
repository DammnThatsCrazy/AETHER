"""Unit tests: structured rights contract expansion (blueprint §3) + legacy migration.

Covers:
- exact canonical vocabulary enum members/values (cross-stream frozen contract)
- nested governed-component models
- backward-compatible DataRightsGrant construction (legacy fields, no broadening)
- migration adapter mapping (model_training_allowed -> contributed_model_training)
- §3.6 Intelligence Rights Profile preset factory
- structured_rights() round-trip on an explicitly-populated grant
- DataRightsService.create_grant preserves legacy check_policy behavior
"""
from __future__ import annotations

import pytest

from services.integrations.data_rights.models import (
    DataRightsGrant,
    DataRightsGrantCreate,
    DisclosureAuthority,
    GeneratedOutputRights,
    GrantStatus,
    IntelligenceRightsProfile,
    LearningAuthority,
    RetentionAuthority,
    RightsProfileDefaults,
    SourceUseAuthority,
    TerminationAuthority,
)
from services.integrations.data_rights.service import (
    DataRightsService,
    can_use_for_model_training,
    can_write_olympus_baseline,
    default_disclosure_authority,
    default_generated_output_rights,
    default_termination_authority,
    derive_learning_from_legacy,
    derive_source_use_from_legacy,
    effective_learning_authority,
    resolve_structured_rights,
)

# Expected exact members (UPPER_SNAKE) and values (snake_case) — other streams
# AST-parse models.py for EXACTLY these; do not rename/extend/omit.
EXPECTED_ENUM_MEMBERS = {
    "RightsDerivationClass": [
        "SOURCE_REPRESENTATION", "NORMALIZED", "TENANT_IDENTIFIABLE_DERIVATIVE",
        "AETHER_GENERATED_INTELLIGENCE", "AGGREGATED", "GENERALIZED",
        "MODEL_DERIVED", "PLATFORM_KNOWLEDGE",
    ],
    "LearningClass": [
        "INFERENCE", "TENANT_ADAPTATION", "GENERALIZED_LEARNING",
        "RESOLVER_CALIBRATION", "ONTOLOGY_LEARNING", "SCHEMA_MAPPING_LEARNING",
        "BENCHMARKING", "CONTRIBUTED_MODEL_TRAINING", "OLYMPUS_INTERNAL_INTELLIGENCE",
    ],
    "OwnershipClass": [
        "CONTRIBUTED_SOURCE", "CANONICALIZED",
        "AETHER_GENERATED_INTELLIGENCE", "GENERALIZED_KNOWLEDGE",
    ],
    "IntelligenceRightsProfile": [
        "SOVEREIGN", "PRIVATE", "STANDARD", "COLLABORATIVE",
    ],
    "DisclosureBoundary": [
        "TENANT_INTERNAL", "OLYMPUS_INTERNAL", "CROSS_TENANT_IDENTIFIABLE",
        "EXTERNAL_IDENTIFIABLE", "GENERALIZED_CROSS_TENANT", "GENERALIZED_EXTERNAL",
    ],
    "OlympusPurpose": [
        "PLATFORM_RESEARCH", "MODEL_IMPROVEMENT", "SECURITY_RESEARCH",
        "FRAUD_RESEARCH", "RESOLVER_CALIBRATION", "ONTOLOGY_RESEARCH",
        "PRODUCT_ANALYTICS", "BENCHMARK_ANALYSIS", "SUPPORT_INVESTIGATION",
        "INCIDENT_RESPONSE",
    ],
    "LifecycleAction": [
        "PRESERVE", "DELETE", "HARD_DELETE", "TOMBSTONE", "QUARANTINE",
        "SUPPRESS", "INVALIDATE", "RECOMPUTE", "RETRAIN", "ANONYMIZE",
        "GENERALIZE", "LEGAL_HOLD",
    ],
    "ModelRevocationState": [
        "NO_ACTION_REQUIRED", "RETRAIN_REQUIRED", "MODEL_QUARANTINE_REQUIRED",
        "EVALUATION_REQUIRED", "LEGAL_REVIEW_REQUIRED", "BLOCKED",
    ],
    "RightsDecisionDisposition": [
        "ALLOWED", "DENIED", "REDACTED", "SUPPRESSED",
    ],
}

EXPECTED_ENUM_VALUES = {
    "RightsDerivationClass": {
        "SOURCE_REPRESENTATION": "source_representation",
        "NORMALIZED": "normalized",
        "TENANT_IDENTIFIABLE_DERIVATIVE": "tenant_identifiable_derivative",
        "AETHER_GENERATED_INTELLIGENCE": "aether_generated_intelligence",
        "AGGREGATED": "aggregated",
        "GENERALIZED": "generalized",
        "MODEL_DERIVED": "model_derived",
        "PLATFORM_KNOWLEDGE": "platform_knowledge",
    },
    "LearningClass": {
        "INFERENCE": "inference",
        "TENANT_ADAPTATION": "tenant_adaptation",
        "GENERALIZED_LEARNING": "generalized_learning",
        "RESOLVER_CALIBRATION": "resolver_calibration",
        "ONTOLOGY_LEARNING": "ontology_learning",
        "SCHEMA_MAPPING_LEARNING": "schema_mapping_learning",
        "BENCHMARKING": "benchmarking",
        "CONTRIBUTED_MODEL_TRAINING": "contributed_model_training",
        "OLYMPUS_INTERNAL_INTELLIGENCE": "olympus_internal_intelligence",
    },
    "OwnershipClass": {
        "CONTRIBUTED_SOURCE": "contributed_source",
        "CANONICALIZED": "canonicalized",
        "AETHER_GENERATED_INTELLIGENCE": "aether_generated_intelligence",
        "GENERALIZED_KNOWLEDGE": "generalized_knowledge",
    },
    "IntelligenceRightsProfile": {
        "SOVEREIGN": "sovereign",
        "PRIVATE": "private",
        "STANDARD": "standard",
        "COLLABORATIVE": "collaborative",
    },
    "DisclosureBoundary": {
        "TENANT_INTERNAL": "tenant_internal",
        "OLYMPUS_INTERNAL": "olympus_internal",
        "CROSS_TENANT_IDENTIFIABLE": "cross_tenant_identifiable",
        "EXTERNAL_IDENTIFIABLE": "external_identifiable",
        "GENERALIZED_CROSS_TENANT": "generalized_cross_tenant",
        "GENERALIZED_EXTERNAL": "generalized_external",
    },
    "OlympusPurpose": {
        "PLATFORM_RESEARCH": "platform_research",
        "MODEL_IMPROVEMENT": "model_improvement",
        "SECURITY_RESEARCH": "security_research",
        "FRAUD_RESEARCH": "fraud_research",
        "RESOLVER_CALIBRATION": "resolver_calibration",
        "ONTOLOGY_RESEARCH": "ontology_research",
        "PRODUCT_ANALYTICS": "product_analytics",
        "BENCHMARK_ANALYSIS": "benchmark_analysis",
        "SUPPORT_INVESTIGATION": "support_investigation",
        "INCIDENT_RESPONSE": "incident_response",
    },
    "LifecycleAction": {
        "PRESERVE": "preserve",
        "DELETE": "delete",
        "HARD_DELETE": "hard_delete",
        "TOMBSTONE": "tombstone",
        "QUARANTINE": "quarantine",
        "SUPPRESS": "suppress",
        "INVALIDATE": "invalidate",
        "RECOMPUTE": "recompute",
        "RETRAIN": "retrain",
        "ANONYMIZE": "anonymize",
        "GENERALIZE": "generalize",
        "LEGAL_HOLD": "legal_hold",
    },
    "ModelRevocationState": {
        "NO_ACTION_REQUIRED": "no_action_required",
        "RETRAIN_REQUIRED": "retrain_required",
        "MODEL_QUARANTINE_REQUIRED": "model_quarantine_required",
        "EVALUATION_REQUIRED": "evaluation_required",
        "LEGAL_REVIEW_REQUIRED": "legal_review_required",
        "BLOCKED": "blocked",
    },
    "RightsDecisionDisposition": {
        "ALLOWED": "allowed",
        "DENIED": "denied",
        "REDACTED": "redacted",
        "SUPPRESSED": "suppressed",
    },
}

# §3.6 preset table: profile -> (generated_output_retention, generalized_learning,
# olympus_internal_intelligence, contributed_model_training)
EXPECTED_PROFILE_TABLE = {
    IntelligenceRightsProfile.SOVEREIGN: ("minimal", False, False, False),
    IntelligenceRightsProfile.PRIVATE: ("required_operations_only", False, False, False),
    IntelligenceRightsProfile.STANDARD: ("yes", True, True, False),
    IntelligenceRightsProfile.COLLABORATIVE: ("yes", True, True, True),
}


def _make_legacy_grant(**overrides) -> DataRightsGrant:
    """Build a pure legacy DataRightsGrant using ONLY legacy fields."""
    defaults = {
        "data_rights_grant_id": "drg_legacy_1",
        "tenant_id": "tenant_abc",
        "contract_id": None,
        "source_id": "src_001",
        "connector_id": "dune_api",
        "connector_class": "tenant_byod_data",
        "source_manifest_id": None,
        "data_category": "onchain",
        "data_sensitivity": "unclassified",
        "raw_data_owner": "tenant_abc",
        "legal_basis": "operator_policy",
        "consent_basis": None,
        "granted_by_user_id": "user_1",
        "granted_at": "2026-01-01T00:00:00+00:00",
        "expires_at": None,
        "revoked_at": None,
        "revocation_reason": None,
        "status": GrantStatus.ACTIVE,
        "audit_event_id": "audit_1",
    }
    defaults.update(overrides)
    return DataRightsGrant(**defaults)


# ── (1) Canonical vocabulary enums ────────────────────────────────────────────

def test_enum_members_exact():
    import services.integrations.data_rights.models as models
    for enum_name, expected_members in EXPECTED_ENUM_MEMBERS.items():
        enum_cls = getattr(models, enum_name)
        actual = [m.name for m in enum_cls]
        assert actual == expected_members, f"{enum_name} member mismatch"


def test_enum_values_exact():
    import services.integrations.data_rights.models as models
    for enum_name, expected_values in EXPECTED_ENUM_VALUES.items():
        enum_cls = getattr(models, enum_name)
        actual = {m.name: m.value for m in enum_cls}
        assert actual == expected_values, f"{enum_name} value mismatch"


def test_enum_lookup_by_value_round_trip():
    assert IntelligenceRightsProfile("standard") is IntelligenceRightsProfile.STANDARD
    assert IntelligenceRightsProfile.STANDARD.value == "standard"


# ── (2) Legacy construction must not broaden ──────────────────────────────────

def test_legacy_instantiation_defaults_structured_fields_to_none():
    grant = _make_legacy_grant()
    # Legacy grant carries the structured fields but all unset.
    assert grant.source_use is None
    assert grant.generated_output_rights is None
    assert grant.learning_authority is None
    assert grant.disclosure_authority is None
    assert grant.retention_authority is None
    assert grant.termination_authority is None
    assert grant.rights_profile == IntelligenceRightsProfile.STANDARD.value
    # Legacy top-level semantics untouched.
    assert grant.tenant_lake_allowed is True
    assert grant.olympus_baseline_allowed is False
    assert grant.model_training_allowed is False


def test_legacy_grant_structured_view_does_not_broaden():
    """A pure legacy grant resolves source_use 1:1 and learning only from
    model_training_allowed; every other structured component is fail-closed."""
    grant = _make_legacy_grant(
        model_training_allowed=False,
        olympus_baseline_allowed=False,
    )
    view = grant.structured_rights()

    # source_use mirrors the legacy booleans exactly (no broadening).
    source_use = view["source_use"]
    assert source_use.tenant_lake is True
    assert source_use.tenant_graph is True
    assert source_use.tenant_insights is True
    assert source_use.olympus_baseline is False
    assert source_use.cross_tenant_aggregate is False
    assert source_use.commercial_reuse is False

    # effective_learning_authority: contributed_model_training follows the boolean.
    learning = effective_learning_authority(grant)
    assert learning.contributed_model_training is False
    # Every other learning class stays fail-closed False.
    for flag in (
        "inference", "tenant_adaptation", "generalized_learning",
        "resolver_calibration", "ontology_learning", "schema_mapping_learning",
        "benchmarking", "olympus_internal_intelligence",
    ):
        assert getattr(learning, flag) is False

    # Unexpressed components resolve fail-closed (never the STANDARD preset).
    assert view["generated_output_rights"] == GeneratedOutputRights()
    assert view["disclosure_authority"] == DisclosureAuthority()
    assert view["retention_authority"] == RetentionAuthority()
    assert view["termination_authority"] == TerminationAuthority()
    assert view["rights_profile"] == "standard"


def test_legacy_source_use_migration_all_true_1to1():
    mapped = derive_source_use_from_legacy(
        tenant_lake_allowed=True,
        tenant_graph_allowed=True,
        tenant_insights_allowed=True,
        olympus_baseline_allowed=True,
        cross_tenant_aggregate_allowed=True,
        commercial_reuse_allowed=True,
    )
    assert mapped == SourceUseAuthority(
        tenant_lake=True,
        tenant_graph=True,
        tenant_insights=True,
        olympus_baseline=True,
        cross_tenant_aggregate=True,
        commercial_reuse=True,
    )


# ── (3) model_training_allowed migration maps to contributed_model_training only

def test_legacy_model_training_maps_only_to_contributed_model_training():
    mapped = derive_learning_from_legacy(model_training_allowed=True)
    assert mapped.contributed_model_training is True
    for flag in (
        "inference", "tenant_adaptation", "generalized_learning",
        "resolver_calibration", "ontology_learning", "schema_mapping_learning",
        "benchmarking", "olympus_internal_intelligence",
    ):
        assert getattr(mapped, flag) is False


def test_effective_learning_authority_prefers_explicit():
    legacy = _make_legacy_grant(model_training_allowed=True)
    assert effective_learning_authority(legacy).contributed_model_training is True

    explicit = _make_legacy_grant(
        model_training_allowed=False,
        learning_authority=LearningAuthority(
            contributed_model_training=False,
            generalized_learning=True,
        ),
    )
    learning = effective_learning_authority(explicit)
    assert learning is explicit.learning_authority
    assert learning.generalized_learning is True
    assert learning.contributed_model_training is False


# ── (4) §3.6 profile factory ──────────────────────────────────────────────────

def test_profile_factory_matches_blueprint_table():
    for profile, expected in EXPECTED_PROFILE_TABLE.items():
        preset = RightsProfileDefaults.for_profile(profile)
        assert preset.generated_output_retention == expected[0]
        assert preset.generalized_learning is expected[1]
        assert preset.olympus_internal_intelligence is expected[2]
        assert preset.contributed_model_training is expected[3]


def test_profile_factory_accepts_string_value():
    assert RightsProfileDefaults.for_profile("standard") == RightsProfileDefaults.for_profile(
        IntelligenceRightsProfile.STANDARD
    )


def test_standard_default_presets_match_blueprint():
    """The canonical STANDARD commercial presets (§3.2 / §3.4 / §14)."""
    generated = default_generated_output_rights()
    assert generated.proprietary_holder == "olympus"
    assert generated.tenant_license.view is True
    assert generated.tenant_license.internal_commercial_use is True
    assert generated.olympus.retain is True
    assert generated.olympus.internal_research is True
    assert generated.external_disclosure.identifiable is False
    assert generated.external_disclosure.generalized == "governed"
    assert generated.survival.tenant_exported_outputs is True
    assert generated.survival.olympus_generalized_derivatives is True

    disclosure = default_disclosure_authority()
    assert disclosure.tenant_internal is True
    assert disclosure.olympus_internal is True
    assert disclosure.cross_tenant_identifiable is False
    assert disclosure.external_identifiable is False
    assert disclosure.generalized_cross_tenant is True
    assert disclosure.generalized_external == "governed"

    termination = default_termination_authority()
    assert termination.contributed_source_data == "delete_by_policy"
    assert termination.tenant_identifiable_derived_data == "recompute_or_delete"
    assert termination.tenant_exports == "tenant_retains"
    assert termination.audit_records == "retain_as_required"
    assert termination.generalized_derivatives == "retain_if_independently_qualified"
    assert termination.model_weights == "retain_if_non_reconstructable_and_permitted"
    assert termination.benchmarks == "retain_if_generalization_passed"
    assert termination.ontology_improvements == "retain"
    assert termination.security_fraud_signatures == "governed_retention"


# ── (5) structured_rights() round-trips an explicitly-populated grant ────────

def test_structured_rights_explicit_grant_round_trips():
    source_use = SourceUseAuthority(
        tenant_lake=True,
        tenant_graph=True,
        tenant_insights=True,
        olympus_baseline=False,
        cross_tenant_aggregate=False,
        commercial_reuse=False,
    )
    generated = default_generated_output_rights()
    learning = LearningAuthority(
        generalized_learning=True,
        olympus_internal_intelligence=True,
        contributed_model_training=False,
    )
    disclosure = default_disclosure_authority()
    retention = RetentionAuthority(precedence="grant:retain", lifecycle_defaults=["preserve"])
    termination = default_termination_authority()

    grant = _make_legacy_grant(
        source_use=source_use,
        generated_output_rights=generated,
        learning_authority=learning,
        disclosure_authority=disclosure,
        retention_authority=retention,
        termination_authority=termination,
        rights_profile=IntelligenceRightsProfile.COLLABORATIVE.value,
    )

    view = grant.structured_rights()
    assert view["source_use"] == source_use
    assert view["generated_output_rights"] == generated
    assert view["learning_authority"] == learning
    assert view["disclosure_authority"] == disclosure
    assert view["retention_authority"] == retention
    assert view["termination_authority"] == termination
    assert view["rights_profile"] == "collaborative"

    # resolve_structured_rights is the dict view consumed by the resolver stream.
    assert resolve_structured_rights(grant) == view


# ── (6) DataRightsService.create_grant preserves legacy check_policy behavior ─

@pytest.mark.asyncio
async def test_service_legacy_grant_preserves_policy_behavior():
    svc = DataRightsService()
    body = DataRightsGrantCreate(
        tenant_id="tenant_abc",
        source_id="src_001",
        connector_id="dune_api",
        connector_class="olympus_provider",  # baseline auto-set True, training forced False
        data_category="onchain",
        data_sensitivity="unclassified",
        raw_data_owner="olympus_labs",
        model_training_allowed=False,
        olympus_baseline_allowed=False,
    )
    grant = await svc.create_grant(body, granted_by_user_id="user_1")

    # Legacy fail-closed behavior is byte-identical.
    assert grant.olympus_baseline_allowed is True  # olympus_provider override
    assert grant.model_training_allowed is False

    assert can_write_olympus_baseline(grant) is True
    assert can_use_for_model_training(grant) is False

    result = await svc.check_policy(grant.data_rights_grant_id, "olympus_baseline")
    assert result.allowed is True
    assert result.reason == "allowed"
    training = await svc.check_policy(grant.data_rights_grant_id, "model_training")
    assert training.allowed is False

    # The structured view of the legacy-shaped stored grant does not broaden.
    view = await svc.get_grant_structured(grant.data_rights_grant_id)
    assert view is not None
    assert view["source_use"].olympus_baseline is True  # faithful to the override
    assert view["learning_authority"].contributed_model_training is False
    assert view["disclosure_authority"].olympus_internal is False
    assert view["generated_output_rights"].tenant_license.view is False


@pytest.mark.asyncio
async def test_service_get_grant_structured_missing_returns_none():
    svc = DataRightsService()
    assert await svc.get_grant_structured("nonexistent") is None
