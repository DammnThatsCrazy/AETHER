"""Product 360 contract checks that span catalog and runtime providers."""

from __future__ import annotations

import hashlib
import json
import re
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
BLUEPRINT_PATH = (
    REPO_ROOT
    / "docs"
    / "reference"
    / "source-of-truth"
    / "AETHER_360_BACKEND_SINGLE_SOURCE_OF_TRUTH.md"
)


def _registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def test_product_surface_catalog_is_structurally_valid() -> None:
    assert validate_product_surface_catalog(_registry()) == []


def test_generated_catalog_exposes_all_slots_direct_providers_and_gaps() -> None:
    catalog = platform_contracts.gen_product_360_surface_catalog_md(_registry())
    assert "This product catalog has 18 surface contracts" in catalog
    assert "originally reviewed 3,013-line" not in catalog
    assert "| Direct surface provider | Implementation gap |" in catalog
    assert "Unbound: `" in catalog
    assert "Partial: `" in catalog
    assert "Lens alignment: `source_aligned`" in catalog


def test_unbound_surface_slot_must_name_its_implementation_gap() -> None:
    registry = _registry()
    campaign = next(
        surface for surface in registry["productSurfaces"] if surface["id"] == "campaign360"
    )
    slot = next(
        slot for slot in campaign["domainSlots"] if slot["id"] == "signal_sources"
    )
    slot["projectionBindings"] = []
    slot.pop("partialImplementationReason", None)
    slot["unboundReason"] = "canonical_signal_source_provider_not_connected"

    assert validate_product_surface_catalog(registry) == []

    slot.pop("unboundReason")
    assert any(
        violation.message
        == "an unbound slot must declare its implementation gap in unboundReason"
        for violation in validate_product_surface_catalog(registry)
    )


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


def test_partial_binding_must_expose_exact_missing_authorities() -> None:
    registry = _registry()
    agent = next(surface for surface in registry["productSurfaces"] if surface["id"] == "agent360")
    capabilities = next(slot for slot in agent["domainSlots"] if slot["id"] == "capabilities")
    assert capabilities["unboundCanonicalAuthorityRefs"] == ["actions", "resources", "tools"]

    capabilities["unboundCanonicalAuthorityRefs"] = ["actions"]
    assert any(
        "unboundCanonicalAuthorityRefs must exactly list authorities" in violation.message
        for violation in validate_product_surface_catalog(registry)
    )

    capabilities["unboundCanonicalAuthorityRefs"] = ["actions", "resources", "tools"]
    capabilities.pop("authorityGapReason")
    assert any(
        violation.message == "a partially bound slot must explain its unbound authorities"
        for violation in validate_product_surface_catalog(registry)
    )


def test_partial_implementation_reason_must_be_nonempty_on_a_bound_slot() -> None:
    registry = _registry()
    risk = next(surface for surface in registry["productSurfaces"] if surface["id"] == "risk360")
    financial = next(slot for slot in risk["domainSlots"] if slot["id"] == "financial_contagion")
    assert financial["partialImplementationReason"]

    financial["partialImplementationReason"] = ""
    assert any(
        violation.message == "partialImplementationReason requires a bound slot and non-empty reason"
        for violation in validate_product_surface_catalog(registry)
    )


def test_product_surface_contract_metadata_matches_primary_blueprint() -> None:
    registry = _registry()
    source = BLUEPRINT_PATH.read_text(encoding="utf-8")
    source_hash = hashlib.sha256(BLUEPRINT_PATH.read_bytes()).hexdigest()
    assert registry["productSurfaceBlueprintSource"]["sha256"] == source_hash

    sections = re.split(r"(?m)^### (11\.\d+) ", source)
    blueprint_by_surface: dict[str, dict[str, object]] = {}
    for index in range(1, len(sections), 2):
        section_id = sections[index]
        section_text = sections[index + 1]
        header = section_text.splitlines()[0]
        surface_slug = re.search(r"`([a-z][a-z0-9_]*)`", header)
        assert surface_slug is not None
        required_section = re.search(
            r"\*\*Required slots:\*\*\s*\n\n(?P<slots>(?:- `[^`]+`\s*\n)+)",
            section_text,
        )
        assert required_section is not None
        required_lenses = re.search(r"\*\*Required lenses:\*\* ([^\n]+)", section_text)
        subjects = re.search(r"\*\*Subjects:\*\* ([^\n]+)", section_text)
        owner = re.search(r"\*\*Canonical owner:\*\* `([^`]+)`", section_text)
        priority = re.search(r"\*\*Priority:\*\* ([^\n]+)", section_text)
        purpose = re.search(r"\*\*Purpose:\*\* ([^\n]+)", section_text)
        assert all(item is not None for item in (required_lenses, subjects, owner, priority, purpose))

        def _field(match: re.Match[str]) -> str:
            # The source document ends field lines with a markdown "<br>" line break.
            return match.group(1).strip().removesuffix("<br>").strip()

        blueprint_by_surface[f"{surface_slug.group(1)}360"] = {
            "sourceSection": section_id,
            "priority": _field(priority),
            "canonicalOwner": owner.group(1),
            "subjectIdentifiers": [item.strip() for item in _field(subjects).split(",")],
            "requiredLensIds": [item.strip() for item in _field(required_lenses).split(",")],
            "purpose": _field(purpose),
            "requiredSlotIds": re.findall(r"- `([^`]+)`", required_section.group("slots")),
        }

    assert len(blueprint_by_surface) == 18
    assert len(registry["productSurfaces"]) == 18
    assert all(
        surface["contractStatus"] == "source_aligned"
        for surface in registry["productSurfaces"]
    )
    for surface in registry["productSurfaces"]:
        contract = surface["blueprintContract"]
        assert contract == blueprint_by_surface[surface["id"]]
        actual_required_slots = [
            slot["id"]
            for slot in surface["domainSlots"]
            if slot["requirement"] == "required"
        ]
        assert (surface["contractStatus"] == "source_aligned") is (
            actual_required_slots == contract["requiredSlotIds"]
        )
        if surface["contractStatus"] == "source_aligned":
            assert surface["lensContract"]["sourceAlignmentStatus"] == "source_aligned"
            assert surface["lensContract"]["lensIds"] == contract["requiredLensIds"]


def test_source_aligned_campaign_lenses_match_the_primary_blueprint() -> None:
    registry = _registry()
    campaign = next(
        surface for surface in registry["productSurfaces"] if surface["id"] == "campaign360"
    )
    assert campaign["lensContract"]["sourceAlignmentStatus"] == "source_aligned"
    assert campaign["lensContract"]["lensIds"] == campaign["blueprintContract"]["requiredLensIds"]
    assert campaign["lensContract"]["expectedCount"] == len(
        campaign["blueprintContract"]["requiredLensIds"]
    )

    campaign["lensContract"]["lensIds"].pop()
    assert any(
        violation.message
        == "source-aligned lensContract must match blueprint requiredLensIds and expectedCount"
        for violation in validate_product_surface_catalog(registry)
    )


def test_source_aligned_required_slot_order_matches_the_primary_blueprint() -> None:
    registry = _registry()
    surface = next(
        item for item in registry["productSurfaces"] if item["id"] == "profile360"
    )
    surface["domainSlots"][0], surface["domainSlots"][1] = (
        surface["domainSlots"][1],
        surface["domainSlots"][0],
    )

    assert any(
        violation.message
        == "source-aligned required domain slots must match blueprint requiredSlotIds in order"
        for violation in validate_product_surface_catalog(registry)
    )


def test_risk360_required_slots_include_agent_subjects() -> None:
    """Agent assessments and delegation signals bind exact required Risk slots."""
    registry = _registry()
    risk_surface = next(
        surface for surface in registry["productSurfaces"] if surface["id"] == "risk360"
    )

    required_slots = {
        slot["id"]: slot
        for slot in risk_surface["domainSlots"]
        if slot["requirement"] == "required"
    }
    assert list(required_slots) == risk_surface["blueprintContract"]["requiredSlotIds"]
    for slot_id in ("risk_summary", "agent_amplification", "evidence_trace"):
        slot = required_slots[slot_id]
        risk_binding = next(
            binding
            for binding in slot["projectionBindings"]
            if binding["projectionId"] == "risk360" and binding["role"] == "primary"
        )
        assert "agent" in risk_binding["subjectKinds"]
    source_binding = required_slots["source_trust"]["projectionBindings"][0]
    assert source_binding["subjectKinds"] == ["source"]


def test_signals360_keeps_unjoined_risk_unknown_and_binds_derived_summary() -> None:
    """A signal risk flag needs an exact signal-to-risk join before it can render."""
    registry = _registry()
    signals_surface = next(
        surface for surface in registry["productSurfaces"] if surface["id"] == "signals360"
    )
    slots = {slot["id"]: slot for slot in signals_surface["domainSlots"]}
    assert slots["risk_flags"]["canonicalAuthorityRefs"] == ["risk_outputs"]
    assert slots["risk_flags"]["projectionBindings"] == []
    assert slots["risk_flags"]["unboundReason"]
    assert slots["signal_summary"]["projectionBindings"] == [
        {
            "projectionId": "signals360",
            "role": "primary",
            "sectionIds": ["signal_summary"],
            "subjectKinds": ["entity"],
        }
    ]


def test_execution360_plan_steps_binds_agent_episode_and_exact_execution_subjects() -> None:
    registry = _registry()
    execution_surface = next(
        surface for surface in registry["productSurfaces"] if surface["id"] == "execution360"
    )
    temporal_slot = next(
        slot
        for slot in execution_surface["domainSlots"]
        if slot["id"] == "plan_steps"
    )
    binding = next(
        binding
        for binding in temporal_slot["projectionBindings"]
        if binding["projectionId"] == "execution360"
    )
    assert binding["subjectKinds"] == ["agent", "entity", "episode", "execution"]
    assert set(binding["sectionIds"]) == {
        "episode_context",
        "evidence",
        "state",
        "summary",
        "timeline",
    }
    provider = next(
        projection for projection in registry["projections"] if projection["id"] == "execution360"
    )
    bound_authorities = {
        authority
        for slot_binding in temporal_slot["projectionBindings"]
        for projection in registry["projections"]
        if projection["id"] == slot_binding["projectionId"]
        for authority in projection["canonicalAuthorities"]
    }
    assert set(temporal_slot["canonicalAuthorityRefs"]).issubset(bound_authorities)
    assert "episode_context" in provider["outputSections"]


def test_episode360_legacy_identity_context_only_binds_supported_subject_kinds() -> None:
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

    assert supported == {"episode", "entity", "campaign"}
    assert {"session", "conversation", "activity_window"}.issubset(
        set(surface["subjectKinds"]) - supported
    )
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


def test_episode360_communications_binds_exact_facts_with_partial_message_coverage() -> None:
    registry = _registry()
    surface = next(
        item for item in registry["productSurfaces"] if item["id"] == "episode360"
    )
    slot = next(item for item in surface["domainSlots"] if item["id"] == "communications")

    assert slot["canonicalAuthorityRefs"] == ["communication_facts"]
    assert slot["projectionBindings"] == [
        {
            "projectionId": "communication360",
            "role": "supporting",
            "sectionIds": ["interactions"],
            "subjectKinds": ["episode"],
        }
    ]
    assert slot["partialImplementationReason"] == (
        "episode_communication_facts_are_exact_but_message_spine_join_and_completeness_are_unavailable"
    )


def test_execution360_risk_events_binds_exact_recorded_signals_with_partial_coverage() -> None:
    registry = _registry()
    projection = next(item for item in registry["projections"] if item["id"] == "execution360")
    surface = next(
        item for item in registry["productSurfaces"] if item["id"] == "execution360"
    )
    slot = next(item for item in surface["domainSlots"] if item["id"] == "risk_events")

    assert "risk_signals" in projection["canonicalAuthorities"]
    assert slot["canonicalAuthorityRefs"] == [
        "agent_executions",
        "execution_facts",
        "risk_signals",
    ]
    assert slot["projectionBindings"] == [
        {
            "projectionId": "execution360",
            "role": "primary",
            "sectionIds": ["interactions"],
            "subjectKinds": ["agent", "entity", "episode", "execution"],
        }
    ]
    assert slot["partialImplementationReason"] == (
        "only_existing_execution_subject_risk_signals_joined_to_admitted_lifecycle_executions_producer_coverage_and_freshness_threshold_unknown"
    )


def test_social360_propagation_binds_governed_paths_but_remains_partial() -> None:
    registry = _registry()
    projection = next(item for item in registry["projections"] if item["id"] == "social360")
    surface = next(item for item in registry["productSurfaces"] if item["id"] == "social360")
    slot = next(item for item in surface["domainSlots"] if item["id"] == "propagation")

    assert "propagation" in projection["outputSections"]
    assert slot["canonicalAuthorityRefs"] == [
        "graph",
        "influence_propagation",
        "relationship_facts",
        "relationship_predicate_registry",
        "social_observations",
    ]
    assert slot["projectionBindings"] == [
        {
            "projectionId": "social360",
            "role": "primary",
            "sectionIds": ["propagation"],
            "subjectKinds": ["entity", "relationship"],
        }
    ]
    assert slot["partialImplementationReason"] == (
        "bounded_observed_paths_have_no_component_measurements_or_completeness_and_freshness_sla"
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
            "domainSlotIds": ["account_summary", "members", "agents", "profiles", "risk"],
            "canonicalAuthorityRefs": [
                "entities",
                "entity_registry",
                "graph",
                "identity",
                "risk_outputs",
            ],
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
                "identifier_inventory",
                "namespace_map",
                "match_evidence",
                "conflicts",
                "confidence",
                "aliases",
                "devices_sessions",
                "wallets",
                "policy_redactions",
                "evidence_trace",
            ],
            "canonicalAuthorityRefs": [
                "entities",
                "entity_registry",
                "evidence",
                "identity",
                "source_provenance",
            ],
            "implementationRef": "services/api/identity/identity/identity360_provider.py",
            "runtimeBindingRef": "services/api/shared/intelligence_projections/frame_runtime.py",
        }
    ]

    for surface_id in ("account360", "identity360"):
        surface = surfaces[surface_id]
        assert surface["contractStatus"] == "source_aligned"
        assert surface["lensContract"]["sourceAlignmentStatus"] == "source_aligned"
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
    assert f"{len(registry['projections'])}-row technical projection provider registry" in catalog_docs


def test_direct_provider_catalog_rejects_unwired_or_unapproved_paths() -> None:
    registry = _registry()
    identity_surface = next(
        surface for surface in registry["productSurfaces"] if surface["id"] == "identity360"
    )
    identity_surface["directProviderBindings"][0]["bindingStatus"] = "catalog_only"

    violations = validate_product_surface_catalog(registry)

    assert any("direct provider status" in violation.message for violation in violations)
    assert any("registered runtime-wired surface paths" in violation.message for violation in violations)
