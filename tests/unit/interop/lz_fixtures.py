"""LayerZero V2 fixture builder.

Fixtures are generated with the SAME encoders the adapter decodes with
(services.interop.providers.layerzero_abi), so decoder and fixtures can
never drift: the guid embedded in PacketSent is computed by compute_guid,
and the verify/deliver legs recompute it from the origin tuple.
"""

from __future__ import annotations

from services.interop.providers.layerzero_abi import (
    TOPIC_PACKET_DELIVERED,
    TOPIC_PACKET_SENT,
    TOPIC_PACKET_VERIFIED,
    compute_guid,
    encode_origin_data,
    encode_packet,
    encode_packet_sent_data,
)
from eth_utils import keccak

NONCE = 7
SRC_EID = 30101   # ethereum-mainnet
DST_EID = 30110   # arbitrum-mainnet
# EVM convention: the packet's bytes32 sender/receiver are left-padded
# addresses — that is what lets PacketVerified/PacketDelivered (which carry
# only the address) recompute the same GUID as PacketSent.
SENDER = b"\x00" * 12 + b"\x11" * 20
RECEIVER = b"\x00" * 12 + b"\x22" * 20
RECEIVER_ADDRESS = "0x" + RECEIVER[-20:].hex()
MESSAGE = b"hello-aether"
SEND_LIBRARY = "0x" + "ab" * 20

GUID = compute_guid(NONCE, SRC_EID, SENDER, DST_EID, RECEIVER)
MESSAGE_HASH = "0x" + keccak(MESSAGE).hex()


def packet_sent_log(block_number: int = 120, log_index: int = 3) -> dict:
    payload = encode_packet(NONCE, SRC_EID, SENDER, DST_EID, RECEIVER, MESSAGE)
    return {
        "network_id": "ethereum-mainnet",
        "native_chain_id": "1",
        "local_eid": SRC_EID,
        "topics": [TOPIC_PACKET_SENT],
        "data": encode_packet_sent_data(payload, b"\x00\x03", SEND_LIBRARY),
        "transactionHash": "0x" + "aa" * 32,
        "blockNumber": hex(block_number),
        "blockHash": "0x" + "b1" * 32,
        "logIndex": hex(log_index),
        "observed_at": "2026-07-08T12:00:00+00:00",
    }


def packet_verified_log(block_number: int = 60, log_index: int = 1) -> dict:
    return {
        "network_id": "arbitrum-mainnet",
        "native_chain_id": "42161",
        "local_eid": DST_EID,
        "topics": [TOPIC_PACKET_VERIFIED],
        "data": encode_origin_data(
            SRC_EID, SENDER, NONCE, RECEIVER_ADDRESS,
            payload_hash=keccak(MESSAGE),
        ),
        "transactionHash": "0x" + "cc" * 32,
        "blockNumber": hex(block_number),
        "blockHash": "0x" + "b2" * 32,
        "logIndex": hex(log_index),
        "observed_at": "2026-07-08T12:01:00+00:00",
    }


def packet_delivered_log(block_number: int = 61, log_index: int = 2) -> dict:
    return {
        "network_id": "arbitrum-mainnet",
        "native_chain_id": "42161",
        "local_eid": DST_EID,
        "topics": [TOPIC_PACKET_DELIVERED],
        "data": encode_origin_data(SRC_EID, SENDER, NONCE, RECEIVER_ADDRESS),
        "transactionHash": "0x" + "dd" * 32,
        "blockNumber": hex(block_number),
        "blockHash": "0x" + "b3" * 32,
        "logIndex": hex(log_index),
        "observed_at": "2026-07-08T12:02:00+00:00",
    }


class FixtureRpcClient:
    """Injectable RPC stub: scripted heads, logs, and block hashes per
    network — reorgs are simulated by changing a block hash between scans."""

    def __init__(self) -> None:
        self.heads: dict[str, int] = {}
        self.logs: dict[str, list[dict]] = {}
        self.block_hashes: dict[tuple[str, int], str] = {}

    async def get_head(self, network_id: str) -> dict:
        return {"number": self.heads.get(network_id, 0)}

    async def get_logs(self, network_id: str, from_block: int, to_block: int) -> list[dict]:
        out = []
        for log in self.logs.get(network_id, []):
            number = int(log["blockNumber"], 16)
            if from_block <= number <= to_block:
                out.append(dict(log))
        return out

    async def get_block_hash(self, network_id: str, block_number: int) -> str:
        return self.block_hashes.get((network_id, block_number), f"0xhash{block_number}")
