"""LayerZero V2 reference adapter — the complete, fixture-proven decode path.

Implementation status: CREDENTIAL_GATED. The decode/correlation/reorg logic
is complete and proven against fixtures; LIVE scanning requires configured
RPC endpoints per network, which this environment does not hold. The RPC
client is injected so tests (and future live wiring) share one code path.

Mapping (provider-native → canonical):
    OApp            → InteropApplication
    Endpoint        → InteropGateway
    GUID            → correlation key alias ("lz2:<guid>") + provider ref
    Packet          → InteropMessage
    Pathway (EIDs)  → InteropPath
    PacketSent      → phase "sent"       (source endpoint ref)
    PacketVerified  → phase "verified"
    PacketDelivered → phase "delivered"  (destination endpoint ref)
"""

from __future__ import annotations

from typing import Any, Optional, Protocol

from services.integrations.connectors.base import ImplementationStatus
from services.interop.foundation import utc_now_iso
from services.interop.providers.base import InteropProviderAdapter
from services.interop.providers.layerzero_abi import (
    TOPIC_PACKET_DELIVERED,
    TOPIC_PACKET_SENT,
    TOPIC_PACKET_VERIFIED,
    compute_guid,
    decode_origin_data,
    decode_packet_sent_data,
)

# EID → network metadata (seeded mainnets; extended via configuration).
DEFAULT_EID_NETWORKS: dict[int, dict[str, str]] = {
    30101: {"network_id": "ethereum-mainnet", "native_chain_id": "1"},
    30110: {"network_id": "arbitrum-mainnet", "native_chain_id": "42161"},
    30184: {"network_id": "base-mainnet", "native_chain_id": "8453"},
}

DEFAULT_CONFIRMATIONS = 15
_RECENT_HASHES_KEPT = 32


class RpcClient(Protocol):
    """Injected JSON-RPC access — FixtureRpcClient in tests, HTTP in prod."""

    async def get_head(self, network_id: str) -> dict[str, Any]: ...
    async def get_logs(
        self, network_id: str, from_block: int, to_block: int,
    ) -> list[dict[str, Any]]: ...
    async def get_block_hash(self, network_id: str, block_number: int) -> str: ...


class LayerZeroV2Adapter(InteropProviderAdapter):
    provider_id = "layerzero_v2"
    provider_kind = "layerzero_v2"
    display_name = "LayerZero V2 (reference adapter)"
    protocol_products = ("messaging", "asset_transfer")
    supported_versions = ("v2",)
    implementation_status = ImplementationStatus.CREDENTIAL_GATED
    capabilities = (
        "message_observation", "historical_backfill", "direct_rpc_observation",
        "payload_decoding", "delivery_observation",
    )
    known_limitations = (
        "Decode, GUID correlation, and reorg handling are complete and "
        "fixture-proven. Live scanning requires per-network RPC endpoints "
        "(credential-gated); security-policy snapshots additionally require "
        "eth_call access to the configured receive libraries."
    )

    def __init__(
        self,
        rpc_client: Optional[RpcClient] = None,
        eid_networks: Optional[dict[int, dict[str, str]]] = None,
        confirmations: int = DEFAULT_CONFIRMATIONS,
    ) -> None:
        self.rpc = rpc_client
        self.eid_networks = eid_networks or dict(DEFAULT_EID_NETWORKS)
        self.confirmations = confirmations

    # ── decoding ────────────────────────────────────────────────────────────

    def decode_log(self, raw_log: dict[str, Any]) -> Optional[dict[str, Any]]:
        topics = raw_log.get("topics") or []
        if not topics:
            return None
        topic0 = topics[0].lower()
        base = {
            "provider_id": self.provider_id,
            "provider_kind": self.provider_kind,
            "observed_at": raw_log.get("observed_at") or utc_now_iso(),
            "endpoint_ref": {
                "network_id": raw_log.get("network_id", "unknown"),
                "native_chain_id": raw_log.get("native_chain_id", ""),
                "transaction_hash": raw_log.get("transactionHash"),
                "block_number": str(int(raw_log.get("blockNumber", "0x0"), 16))
                if isinstance(raw_log.get("blockNumber"), str)
                else str(raw_log.get("blockNumber", 0)),
                "block_hash": raw_log.get("blockHash"),
                "log_index": int(raw_log.get("logIndex", "0x0"), 16)
                if isinstance(raw_log.get("logIndex"), str)
                else int(raw_log.get("logIndex", 0)),
                "gateway_id": f"layerzero_v2:endpoint:{raw_log.get('network_id', 'unknown')}",
            },
        }

        if topic0 == TOPIC_PACKET_SENT:
            decoded = decode_packet_sent_data(raw_log["data"])
            packet = decoded["packet"]
            return {
                **base,
                "phase": "sent",
                "correlation_key": f"lz2:{packet['guid']}",
                "sequence": str(packet["nonce"]),
                "payload_hash": packet["message_hash"],
                "source_network_id": self._network(packet["src_eid"]),
                "destination_network_id": self._network(packet["dst_eid"]),
                "provider_message_refs": [
                    {"alias_type": "guid", "alias_value": packet["guid"], "canonical": True},
                    {"alias_type": "nonce", "alias_value": str(packet["nonce"]), "canonical": False},
                    {"alias_type": "src_eid", "alias_value": str(packet["src_eid"]), "canonical": False},
                    {"alias_type": "dst_eid", "alias_value": str(packet["dst_eid"]), "canonical": False},
                ],
                "provider_native_stage": "PacketSent",
                "provider_extension": {
                    "send_library": decoded["send_library"],
                    "options": decoded["options"],
                    "sender": packet["sender"],
                    "receiver": packet["receiver"],
                },
            }

        if topic0 in (TOPIC_PACKET_VERIFIED, TOPIC_PACKET_DELIVERED):
            verified = topic0 == TOPIC_PACKET_VERIFIED
            origin = decode_origin_data(raw_log["data"], expect_payload_hash=verified)
            # These events carry no GUID — recompute it from the origin tuple
            # plus the local (destination) EID and receiver.
            dst_eid = raw_log.get("local_eid")
            if dst_eid is None:
                return None
            guid = compute_guid(
                origin["nonce"], origin["src_eid"],
                bytes.fromhex(origin["sender"][2:]),
                int(dst_eid),
                bytes.fromhex(origin["receiver"][2:].rjust(64, "0")),
            )
            observation = {
                **base,
                "phase": "verified" if verified else "delivered",
                "correlation_key": f"lz2:{guid}",
                "sequence": str(origin["nonce"]),
                "source_network_id": self._network(origin["src_eid"]),
                "destination_network_id": self._network(int(dst_eid)),
                "provider_message_refs": [
                    {"alias_type": "guid", "alias_value": guid, "canonical": True},
                    {"alias_type": "nonce", "alias_value": str(origin["nonce"]), "canonical": False},
                ],
                "provider_native_stage": "PacketVerified" if verified else "PacketDelivered",
            }
            if verified:
                observation["payload_hash"] = origin.get("payload_hash")
            return observation

        return None

    def _network(self, eid: int) -> str:
        return self.eid_networks.get(eid, {}).get("network_id", f"lz2-eid:{eid}")

    # ── scanning ────────────────────────────────────────────────────────────

    async def scan(
        self, checkpoint: Optional[dict[str, Any]] = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Scan every configured network from the checkpoint to head minus
        the confirmation horizon. Reorg detection: the stored block hash for
        the last scanned block must still match the chain; a mismatch yields
        a reorg observation and resets the checkpoint to the fork point."""
        if self.rpc is None:
            raise NotImplementedError(
                "layerzero_v2: live scanning requires an RPC client "
                "(credential-gated — configure per-network RPC endpoints)"
            )
        checkpoint = dict(checkpoint or {})
        networks: dict[str, dict] = checkpoint.setdefault("networks", {})
        observations: list[dict[str, Any]] = []

        for eid, meta in self.eid_networks.items():
            network_id = meta["network_id"]
            state = networks.setdefault(
                network_id, {"last_scanned_block": 0, "recent_hashes": {}},
            )
            head = await self.rpc.get_head(network_id)
            safe_head = int(head["number"]) - self.confirmations
            last = int(state["last_scanned_block"])

            # Reorg check against the recorded hash of the last scanned block.
            recent = state.get("recent_hashes", {})
            if last and str(last) in recent:
                current_hash = await self.rpc.get_block_hash(network_id, last)
                if current_hash != recent[str(last)]:
                    fork_point = min(
                        (int(number) for number, block_hash in recent.items()
                         if block_hash != current_hash),
                        default=last,
                    )
                    observations.append({
                        "provider_id": self.provider_id,
                        "provider_kind": self.provider_kind,
                        "phase": "reorged",
                        "network_id": network_id,
                        "from_block": fork_point,
                        "observed_at": utc_now_iso(),
                    })
                    state["last_scanned_block"] = max(0, fork_point - 1)
                    state["recent_hashes"] = {}
                    continue

            if safe_head <= last:
                continue
            raw_logs = await self.rpc.get_logs(network_id, last + 1, safe_head)
            for raw_log in raw_logs:
                raw_log.setdefault("network_id", network_id)
                raw_log.setdefault("native_chain_id", meta["native_chain_id"])
                raw_log.setdefault("local_eid", eid)
                decoded = self.decode_log(raw_log)
                if decoded:
                    observations.append(decoded)
            state["last_scanned_block"] = safe_head
            block_hash = await self.rpc.get_block_hash(network_id, safe_head)
            recent[str(safe_head)] = block_hash
            if len(recent) > _RECENT_HASHES_KEPT:
                for stale_key in sorted(recent, key=int)[:-_RECENT_HASHES_KEPT]:
                    recent.pop(stale_key, None)
            state["recent_hashes"] = recent

        return observations, checkpoint
