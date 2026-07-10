"""Honest scaffolds for the remaining interoperability providers.

Each descriptor states what the adapter WILL cover and what blocks it;
decode paths raise NotImplementedError. None of these may report a live
status — tests/unit/interop/test_provider_scaffold_honesty.py enforces it.
"""

from __future__ import annotations

from typing import Any, Optional

from services.integrations.connectors.base import ImplementationStatus
from services.interop.providers.base import InteropProviderAdapter


class _ScaffoldAdapter(InteropProviderAdapter):
    implementation_status = ImplementationStatus.SCAFFOLDED

    async def scan(
        self, checkpoint: Optional[dict[str, Any]] = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        raise NotImplementedError(
            f"{self.provider_id}: scaffolded provider — no production scan implemented"
        )

    def decode_log(self, raw_log: dict[str, Any]) -> Optional[dict[str, Any]]:
        raise NotImplementedError(
            f"{self.provider_id}: scaffolded provider — no production decode implemented"
        )


class WormholeAdapter(_ScaffoldAdapter):
    provider_id = "wormhole"
    provider_kind = "wormhole"
    display_name = "Wormhole (scaffold)"
    protocol_products = ("messaging", "asset_transfer")
    supported_versions = ("v2",)
    capabilities = ("message_observation", "asset_transfer", "historical_backfill")
    known_limitations = (
        "Planned: core-bridge LogMessagePublished decode, VAA observation via "
        "guardian RPC, token-bridge asset legs. Blocked on guardian/API access "
        "and per-chain RPC endpoints."
    )


class AxelarAdapter(_ScaffoldAdapter):
    provider_id = "axelar"
    provider_kind = "axelar"
    display_name = "Axelar (scaffold)"
    protocol_products = ("messaging", "asset_transfer")
    supported_versions = ("v1",)
    capabilities = ("message_observation", "asset_transfer")
    known_limitations = (
        "Planned: gateway ContractCall/ContractCallWithToken decode + Axelarscan "
        "reconciliation. Blocked on validator/API access."
    )


class ChainlinkCcipAdapter(_ScaffoldAdapter):
    provider_id = "chainlink_ccip"
    provider_kind = "chainlink_ccip"
    display_name = "Chainlink CCIP (scaffold)"
    protocol_products = ("messaging", "asset_transfer")
    supported_versions = ("v1.5",)
    capabilities = ("message_observation", "asset_transfer")
    known_limitations = (
        "Planned: OnRamp CCIPSendRequested / OffRamp ExecutionStateChanged "
        "decode. Blocked on per-lane RPC endpoints and DON metadata."
    )


class HyperlaneAdapter(_ScaffoldAdapter):
    provider_id = "hyperlane"
    provider_kind = "hyperlane"
    display_name = "Hyperlane (scaffold)"
    protocol_products = ("messaging",)
    supported_versions = ("v3",)
    capabilities = ("message_observation",)
    known_limitations = (
        "Planned: Mailbox Dispatch/Process decode with ISM security snapshots. "
        "Blocked on per-chain RPC endpoints."
    )


class IbcAdapter(_ScaffoldAdapter):
    provider_id = "ibc"
    provider_kind = "ibc"
    display_name = "IBC (scaffold)"
    protocol_products = ("messaging", "asset_transfer")
    supported_versions = ("v1",)
    capabilities = ("message_observation", "asset_transfer")
    known_limitations = (
        "Planned: send_packet/recv_packet/acknowledge_packet over Tendermint "
        "RPC with channel/client security context. Blocked on chain RPC access."
    )


class DebridgeAdapter(_ScaffoldAdapter):
    provider_id = "debridge"
    provider_kind = "debridge"
    display_name = "deBridge (scaffold)"
    protocol_products = ("messaging", "intent")
    supported_versions = ("dln-v1",)
    capabilities = ("message_observation", "intent_execution")
    known_limitations = (
        "Planned: DLN order created/fulfilled decode with solver attribution. "
        "Blocked on API access and per-chain RPC endpoints."
    )


SCAFFOLD_ADAPTERS: tuple[InteropProviderAdapter, ...] = (
    WormholeAdapter(),
    AxelarAdapter(),
    ChainlinkCcipAdapter(),
    HyperlaneAdapter(),
    IbcAdapter(),
    DebridgeAdapter(),
)
