"""Projection-plane boot wiring (plane-live seam) — context-360 program, Phase 1.

Verifies ``dependencies.projection_plane.register_implemented_projection_providers``
— the app-boot helper that registers the plane's implemented providers on the
runtime ``projection_registry``: the exact registered set and sources,
registration order, and idempotency. Import-time discipline (the global
singleton is populated only by the boot call, never by importing provider
modules) is separately pinned by the existing no-auto-register tests
(``test_outcome360_provider.py``, ``test_infrastructure360_registration.py``).
"""
from __future__ import annotations

from dependencies.projection_plane import (
    IMPLEMENTED_PROJECTION_IDS,
    register_implemented_projection_providers,
)
from shared.intelligence_projections.registry import ProviderRegistry

EXPECTED_SOURCES: dict[str, str] = {
    "economic360": "services/economic",
    "outcome360": "services/measurement/outcome",
    "infrastructure360": "services/infrastructure",
    "temporal360": "services/temporal360",
    "population360": "services/population360",
    "geographic360": "services/geographic360",
}


def test_wiring_registers_exactly_the_implemented_providers() -> None:
    registry = ProviderRegistry()
    sources = register_implemented_projection_providers(registry)

    assert set(sources) == set(IMPLEMENTED_PROJECTION_IDS)
    assert sources == EXPECTED_SOURCES
    for pid in IMPLEMENTED_PROJECTION_IDS:
        provider = registry.get(pid)
        assert provider is not None, f"{pid} was not registered"
        assert provider.projection_id == pid


def test_wiring_registration_order_matches_implemented_ids() -> None:
    registry = ProviderRegistry()
    register_implemented_projection_providers(registry)

    registered_order = [provider.projection_id for provider in registry.list()]
    assert registered_order == list(IMPLEMENTED_PROJECTION_IDS)


def test_wiring_is_idempotent() -> None:
    registry = ProviderRegistry()
    register_implemented_projection_providers(registry)
    # Re-registering the SAME provider objects is a no-op; DuplicateProjection
    # is reserved for a DIFFERENT object on an already-registered id.
    register_implemented_projection_providers(registry)

    assert registry.sources() == EXPECTED_SOURCES
