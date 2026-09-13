"""Derivatives venue adapter framework — read-only observation adapters.

Two registries, one canonical interface (:class:`DerivativesAdapter`):

* ``DERIVATIVES_ADAPTERS`` — the reference registry the shared certification
  registry reads. It holds the deterministic simulator only, so the credential-
  waiting readiness of the real venues is derived from their own honest
  descriptors rather than being asserted here.
* ``VENUE_ADAPTERS`` — the real read-only venue adapters (Hyperliquid, dYdX,
  GMX, Drift). Each is CREDENTIAL_WAITING: production-shaped, offline-safe, and
  awaiting only a read-only credential/endpoint to observe live data.

No adapter may hold anything beyond read-only credential authority; the
conformance suite enforces the observation-only invariants mechanically.
"""

from __future__ import annotations

from typing import Optional

from services.derivatives.adapters.base import DerivativesAdapter

# Reference registry (read by shared/certification/registry.py). Simulator only.
DERIVATIVES_ADAPTERS: dict[str, DerivativesAdapter] = {}

# Real read-only venue adapters, surfaced operationally via admin_routes.
VENUE_ADAPTERS: dict[str, DerivativesAdapter] = {}


def register_adapter(adapter: DerivativesAdapter) -> None:
    DERIVATIVES_ADAPTERS[adapter.adapter_id] = adapter


def register_venue_adapter(adapter: DerivativesAdapter) -> None:
    VENUE_ADAPTERS[adapter.adapter_id] = adapter


def all_adapters() -> dict[str, DerivativesAdapter]:
    """Merged view of reference + venue adapters (venues win on id collisions)."""
    return {**DERIVATIVES_ADAPTERS, **VENUE_ADAPTERS}


def get_adapter(adapter_id: str) -> Optional[DerivativesAdapter]:
    return VENUE_ADAPTERS.get(adapter_id) or DERIVATIVES_ADAPTERS.get(adapter_id)


def _register_defaults() -> None:
    from services.derivatives.adapters.simulator import SimulatorAdapter

    register_adapter(SimulatorAdapter())

    from services.derivatives.adapters.drift import DriftAdapter
    from services.derivatives.adapters.dydx import DydxAdapter
    from services.derivatives.adapters.gmx import GmxAdapter
    from services.derivatives.adapters.hyperliquid import HyperliquidAdapter

    for adapter in (HyperliquidAdapter(), DydxAdapter(), GmxAdapter(), DriftAdapter()):
        register_venue_adapter(adapter)


_register_defaults()
