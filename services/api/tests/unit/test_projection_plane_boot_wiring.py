"""Projection-plane boot wiring for complete and in-flight providers.

Verifies ``dependencies.projection_plane.register_implemented_projection_providers``
— the app-boot helper that registers the plane's declared providers on the
runtime ``projection_registry``: the exact registered set and sources,
registration order, implementation-state separation, and idempotency. Import-time discipline (the global
singleton is populated only by the boot call, never by importing provider
modules) is separately pinned by the existing no-auto-register tests
(``test_outcome360_provider.py``, ``test_infrastructure360_registration.py``).
"""

from __future__ import annotations

from dependencies.projection_plane import (
    IMPLEMENTED_PROJECTION_IDS,
    IN_FLIGHT_PROVIDER_IDS,
    REGISTERED_PROJECTION_IDS,
    register_implemented_projection_providers,
)
from shared.intelligence_projections.composition import PRODUCT_360_SURFACE_DEFINITIONS
from shared.intelligence_projections.registry import ProviderRegistry

EXPECTED_SOURCES: dict[str, str] = {
    "economic360": "services/api/value/economic",
    "outcome360": "services/api/journeys/measurement/outcome",
    "infrastructure360": "services/api/graph/infrastructure",
    "temporal360": "services/api/graph/temporal360",
    "population360": "services/api/identity/population360",
    "geographic360": "services/api/graph/geographic360",
    "risk360": "services/api/intelligence/risk360",
    "fraud360": "services/api/intelligence/fraud360",
    "communication360": "services/api/journeys/communication360",
    "agent360": "services/api/actions/agent",
    "execution360": "services/api/actions/agent/execution360_provider",
    "profile360": "services/api/identity/profile",
    "relationship360": "services/api/identity/relationship_intelligence",
    "episode360": "services/api/journeys/measurement/episodes",
    "social360": "social_silver",
    "cluster360": "services/api/graph/cluster",
    "campaign360": "services/api/journeys/campaign",
    "source360": "services/api/connectors/provider_runtime",
    "connection360": "services/api/connectors/provider_runtime",
    "support360": "services/api/journeys/support360",
    "signals360": "services/api/intelligence/signals/signals360_provider",
    "memory360": "services/api/intelligence/semantic_intelligence",
    "commerce360": "services/api/value/commerce",
    "workflow360": "services/api/intelligence/workflow/workflow360_provider",
}


def test_wiring_registers_implemented_and_concrete_in_flight_providers() -> None:
    registry = ProviderRegistry()
    sources = register_implemented_projection_providers(registry)

    assert set(sources) == set(REGISTERED_PROJECTION_IDS)
    assert sources == EXPECTED_SOURCES
    for pid in REGISTERED_PROJECTION_IDS:
        provider = registry.get(pid)
        assert provider is not None, f"{pid} was not registered"
        assert provider.projection_id == pid

    availability = registry.availability()
    assert all(
        availability[pid]["registryState"] == "implemented" for pid in IMPLEMENTED_PROJECTION_IDS
    )
    assert all(availability[pid]["registryState"] == "in_flight" for pid in IN_FLIGHT_PROVIDER_IDS)


def test_wiring_registration_order_matches_implemented_ids() -> None:
    registry = ProviderRegistry()
    register_implemented_projection_providers(registry)

    registered_order = [provider.projection_id for provider in registry.list()]
    assert registered_order == list(REGISTERED_PROJECTION_IDS)


def test_every_product_surface_projection_binding_has_a_boot_registered_provider() -> None:
    """Keep the product-to-runtime crosswalk connected for all 18 surfaces."""
    catalog_projection_ids = {
        binding["projectionId"]
        for surface in PRODUCT_360_SURFACE_DEFINITIONS.values()
        for slot in surface.get("domainSlots", [])
        for binding in slot.get("projectionBindings", [])
        if isinstance(binding, dict) and isinstance(binding.get("projectionId"), str)
    }

    assert len(PRODUCT_360_SURFACE_DEFINITIONS) == 18
    assert catalog_projection_ids <= set(REGISTERED_PROJECTION_IDS)


def test_wiring_is_idempotent() -> None:
    registry = ProviderRegistry()
    register_implemented_projection_providers(registry)
    # Re-registering the SAME provider objects is a no-op; DuplicateProjection
    # is reserved for a DIFFERENT object on an already-registered id.
    register_implemented_projection_providers(registry)

    assert registry.sources() == EXPECTED_SOURCES
