"""Interoperability provider adapter registry.

All seven providers register here with HONEST implementation statuses:
LayerZero V2 is CREDENTIAL_GATED (decode complete and fixture-proven; live
scanning requires RPC endpoint configuration); the other six are SCAFFOLDED
descriptors whose decode paths raise NotImplementedError.
"""

from __future__ import annotations

from typing import Optional

from services.interop.providers.base import InteropProviderAdapter

INTEROP_PROVIDERS: dict[str, InteropProviderAdapter] = {}


def register_provider(adapter: InteropProviderAdapter) -> None:
    INTEROP_PROVIDERS[adapter.provider_id] = adapter


def get_provider(provider_id: str) -> Optional[InteropProviderAdapter]:
    return INTEROP_PROVIDERS.get(provider_id)


def _register_defaults() -> None:
    from services.interop.providers.layerzero_v2 import LayerZeroV2Adapter
    from services.interop.providers.scaffolds import SCAFFOLD_ADAPTERS

    register_provider(LayerZeroV2Adapter())
    for adapter in SCAFFOLD_ADAPTERS:
        register_provider(adapter)


_register_defaults()
