"""Product 360 contract checks that span catalog and runtime providers."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import generate_platform_contracts as platform_contracts  # noqa: E402
from lib.intelligence_projection_validation import (  # noqa: E402
    validate_product_surface_catalog,
)

REGISTRY_PATH = (
    REPO_ROOT / "packages" / "shared" / "contracts" / "intelligence-projection-registry.json"
)


def _registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def test_product_surface_catalog_is_structurally_valid() -> None:
    assert validate_product_surface_catalog(_registry()) == []


def test_each_product_binding_declares_a_shared_canonical_authority() -> None:
    registry = _registry()
    projection_authorities = {
        projection["id"]: set(projection.get("canonicalAuthorities", []))
        for projection in registry["projections"]
    }

    unmapped = []
    for surface in registry["productSurfaces"]:
        for slot in surface["domainSlots"]:
            slot_authorities = set(slot.get("canonicalAuthorityRefs", []))
            for binding in slot["projectionBindings"]:
                projection_id = binding["projectionId"]
                if not slot_authorities & projection_authorities.get(projection_id, set()):
                    unmapped.append((surface["id"], slot["id"], projection_id))

    assert unmapped == []


def test_risk360_required_slots_include_agent_subjects() -> None:
    """Persisted agent risk assessments must enter both required Risk 360 slots."""
    registry = _registry()
    risk_surface = next(
        surface for surface in registry["productSurfaces"] if surface["id"] == "risk360"
    )

    required_slots = {
        slot["id"]: slot
        for slot in risk_surface["domainSlots"]
        if slot["requirement"] == "required"
    }
    for slot_id in ("risk_assessment_state", "risk_evidence_and_limitations"):
        slot = required_slots[slot_id]
        risk_binding = next(
            binding
            for binding in slot["projectionBindings"]
            if binding["projectionId"] == "risk360" and binding["role"] == "primary"
        )
        assert "agent" in risk_binding["subjectKinds"]


def test_signals360_projects_agent_risk_through_risk360() -> None:
    """Signals360 Agent subjects use the canonical Risk360 authority."""
    registry = _registry()
    signals_surface = next(
        surface for surface in registry["productSurfaces"] if surface["id"] == "signals360"
    )
    risk_slot = next(
        slot for slot in signals_surface["domainSlots"] if slot["id"] == "risk_signals"
    )
    risk_binding = next(
        binding
        for binding in risk_slot["projectionBindings"]
        if binding["projectionId"] == "risk360" and binding["role"] == "primary"
    )

    assert "agent" in risk_binding["subjectKinds"]
    risk_projection = next(
        projection for projection in registry["projections"] if projection["id"] == "risk360"
    )
    assert "agent" in risk_projection["subjectKinds"]
    assert set(risk_slot["canonicalAuthorityRefs"]).issubset(
        set(risk_projection["canonicalAuthorities"])
    )


def test_execution360_agent_temporal_slot_binds_episode_authority() -> None:
    registry = _registry()
    execution_surface = next(
        surface for surface in registry["productSurfaces"] if surface["id"] == "execution360"
    )
    temporal_slot = next(
        slot
        for slot in execution_surface["domainSlots"]
        if slot["id"] == "temporal_and_episode_context"
    )
    binding = next(
        binding
        for binding in temporal_slot["projectionBindings"]
        if binding["projectionId"] == "execution360"
    )
    assert binding["subjectKinds"] == ["agent"]
    assert set(binding["sectionIds"]) == {"episode_context", "timeline", "evidence"}
    provider = next(
        projection for projection in registry["projections"] if projection["id"] == "execution360"
    )
    assert set(temporal_slot["canonicalAuthorityRefs"]).issubset(
        set(provider["canonicalAuthorities"])
    )
    assert "episode_context" in provider["outputSections"]


def test_episode360_identity_context_has_a_provider_for_each_supported_subject_kind() -> None:
    registry = _registry()
    surface = next(
        item for item in registry["productSurfaces"] if item["id"] == "episode360"
    )
    slot = next(
        item for item in surface["domainSlots"] if item["id"] == "entity_and_relationship_context"
    )
    supported = {
        kind
        for binding in slot["projectionBindings"]
        for kind in binding["subjectKinds"]
    }

    assert set(surface["subjectKinds"]).issubset(supported)
    assert {"episode_facts", "campaign_facts"}.issubset(
        set(slot["canonicalAuthorityRefs"])
    )
    assert any(
        binding["projectionId"] == "profile360"
        and "episode" in binding["subjectKinds"]
        for binding in slot["projectionBindings"]
    )
    assert any(
        binding["projectionId"] == "campaign360"
        and "campaign" in binding["subjectKinds"]
        for binding in slot["projectionBindings"]
    )


def test_account_and_identity_direct_providers_are_separate_from_projection_bindings() -> None:
    registry = _registry()
    surfaces = {surface["id"]: surface for surface in registry["productSurfaces"]}
    projection_ids = {projection["id"] for projection in registry["projections"]}

    assert surfaces["account360"]["directProviderBindings"] == [
        {
            "providerClass": "Account360Provider",
            "providerKind": "surface_frame_provider",
            "bindingStatus": "runtime_wired",
            "subjectKinds": ["entity"],
            "domainSlotIds": ["account_identity_and_state"],
            "implementationRef": "services/api/identity/account360_provider.py",
            "runtimeBindingRef": "services/api/shared/intelligence_projections/frame_runtime.py",
        }
    ]
    assert surfaces["identity360"]["directProviderBindings"] == [
        {
            "providerClass": "Identity360Provider",
            "providerKind": "surface_authority_reader",
            "bindingStatus": "runtime_wired",
            "subjectKinds": ["agent", "entity", "source"],
            "domainSlotIds": [
                "identity_evidence",
                "relationship_identity_context",
                "resolved_subject_identity",
                "source_identifier_lineage",
            ],
            "implementationRef": "services/api/identity/identity/identity360_provider.py",
            "runtimeBindingRef": "services/api/shared/intelligence_projections/frame_runtime.py",
        }
    ]

    for surface_id in ("account360", "identity360"):
        surface = surfaces[surface_id]
        assert surface["contractStatus"] == "reconstructed_pending_source_alignment"
        assert surface["lensContract"]["sourceAlignmentStatus"] == "pending_source_alignment"
        for binding in surface["directProviderBindings"]:
            assert "projectionId" not in binding
            assert binding["providerClass"] not in projection_ids


def test_direct_provider_metadata_is_generated_into_contracts_and_catalog_docs() -> None:
    registry = _registry()

    typescript = platform_contracts.gen_intelligence_projection_ts(registry)
    python_contract = platform_contracts.gen_intelligence_projection_py(registry)
    catalog_docs = platform_contracts.gen_product_360_surface_catalog_md(registry)

    assert "Product360DirectProviderBinding" in typescript
    assert "bindingStatus: 'runtime_wired'" in typescript
    assert "Identity360Provider" in typescript
    assert "Account360Provider" in python_contract
    assert "Direct surface-provider bindings" in catalog_docs
    assert "`Identity360Provider` (runtime_wired)" in catalog_docs
    assert "`Account360Provider` (runtime_wired)" in catalog_docs
    assert "not full surface completion" in catalog_docs
    assert "18 surface contracts" in catalog_docs
    assert "20-row technical projection provider registry" in catalog_docs


def test_direct_provider_catalog_rejects_unwired_or_unapproved_paths() -> None:
    registry = _registry()
    identity_surface = next(
        surface for surface in registry["productSurfaces"] if surface["id"] == "identity360"
    )
    identity_surface["directProviderBindings"][0]["bindingStatus"] = "catalog_only"

    violations = validate_product_surface_catalog(registry)

    assert any("direct provider status" in violation.message for violation in violations)
    assert any("runtime-wired Account360 and Identity360 paths" in violation.message for violation in violations)
