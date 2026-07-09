"""Derivatives venue adapter framework — read-only observation adapters.

Registry of adapter instances by adapter id. No adapter may hold anything
beyond read-only credential authority; the conformance suite enforces the
observation-only invariants every adapter must satisfy.
"""

from __future__ import annotations

from typing import Optional

from services.derivatives.adapters.base import DerivativesAdapter

DERIVATIVES_ADAPTERS: dict[str, DerivativesAdapter] = {}


def register_adapter(adapter: DerivativesAdapter) -> None:
    DERIVATIVES_ADAPTERS[adapter.adapter_id] = adapter


def get_adapter(adapter_id: str) -> Optional[DerivativesAdapter]:
    return DERIVATIVES_ADAPTERS.get(adapter_id)


def _register_defaults() -> None:
    from services.derivatives.adapters.simulator import SimulatorAdapter

    register_adapter(SimulatorAdapter())


_register_defaults()
