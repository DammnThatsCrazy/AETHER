"""Interoperability provider adapter registry.

All seven first-release providers register here as CREDENTIAL_GATED: each has a
real, fixture-proven event decoder and protocol-neutral lifecycle correlation;
live on-chain scanning requires a wired RPC endpoint (the unwired-client path
fails closed with NotImplementedError). None claim provider-live status;
observation-only (execution_by_aether=False).
"""

from __future__ import annotations

from typing import Optional

from graph.interop.providers.base import InteropProviderAdapter

INTEROP_PROVIDERS: dict[str, InteropProviderAdapter] = {}


def register_provider(adapter: InteropProviderAdapter) -> None:
    INTEROP_PROVIDERS[adapter.provider_id] = adapter


def get_provider(provider_id: str) -> Optional[InteropProviderAdapter]:
    return INTEROP_PROVIDERS.get(provider_id)


def _register_defaults() -> None:
    from graph.interop.providers.axelar import AxelarAdapter
    from graph.interop.providers.chainlink_ccip import ChainlinkCcipAdapter
    from graph.interop.providers.debridge import DebridgeAdapter
    from graph.interop.providers.hyperlane import HyperlaneAdapter
    from graph.interop.providers.ibc import IbcAdapter
    from graph.interop.providers.layerzero_v2 import LayerZeroV2Adapter
    from graph.interop.providers.wormhole import WormholeAdapter

    for adapter in (
        LayerZeroV2Adapter(),
        WormholeAdapter(),
        AxelarAdapter(),
        ChainlinkCcipAdapter(),
        HyperlaneAdapter(),
        IbcAdapter(),
        DebridgeAdapter(),
    ):
        register_provider(adapter)


_register_defaults()
