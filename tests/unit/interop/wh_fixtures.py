"""Wormhole fixture + mock-server builder.

Fixtures are generated with the SAME encoders the adapter decodes with
(services.interop.providers.wormhole), so decoder and fixtures can never drift:
the source LogMessagePublished, the guardian VAA, and the destination
TransferRedeemed all reference one (emitterChain, emitterAddress, sequence)
triple and therefore correlate on one canonical key.
"""

from __future__ import annotations

from typing import Any, Optional

from services.interop.providers.wormhole import (
    TOPIC_LOG_MESSAGE_PUBLISHED,
    TOPIC_TRANSFER_REDEEMED,
    WormholeRateLimitError,
    encode_log_message_published_data,
    encode_vaa,
    vaa_correlation_key,
)

SRC_CHAIN = 2            # ethereum-mainnet (Wormhole chain id)
DST_CHAIN = 23           # arbitrum-mainnet
SEQUENCE = 4242
NONCE = 7
CONSISTENCY = 200
EMITTER_BYTES32 = b"\x00" * 12 + b"\x11" * 20   # left-padded EVM emitter contract
EMITTER_TOPIC = "0x" + EMITTER_BYTES32.hex()
PAYLOAD = b"aether-observes-only"

KEY = vaa_correlation_key(SRC_CHAIN, EMITTER_TOPIC, SEQUENCE)


def log_message_published(block_number: int = 100, log_index: int = 0) -> dict[str, Any]:
    return {
        "network_id": "ethereum-mainnet",
        "native_chain_id": "1",
        "wormhole_chain_id": SRC_CHAIN,
        "topics": [TOPIC_LOG_MESSAGE_PUBLISHED, EMITTER_TOPIC],
        "data": encode_log_message_published_data(SEQUENCE, NONCE, PAYLOAD, CONSISTENCY),
        "transactionHash": "0x" + "aa" * 32,
        "blockNumber": hex(block_number),
        "blockHash": "0x" + "b1" * 32,
        "logIndex": hex(log_index),
        "observed_at": "2026-07-10T00:00:00+00:00",
    }


def transfer_redeemed(block_number: int = 55, log_index: int = 1) -> dict[str, Any]:
    return {
        "network_id": "arbitrum-mainnet",
        "native_chain_id": "42161",
        "wormhole_chain_id": DST_CHAIN,
        "topics": [
            TOPIC_TRANSFER_REDEEMED,
            hex(SRC_CHAIN),
            EMITTER_TOPIC,
            hex(SEQUENCE),
        ],
        "data": "0x",
        "transactionHash": "0x" + "dd" * 32,
        "blockNumber": hex(block_number),
        "blockHash": "0x" + "b3" * 32,
        "logIndex": hex(log_index),
        "observed_at": "2026-07-10T00:02:00+00:00",
    }


def signed_vaa(signature_count: int = 13) -> bytes:
    sigs = [(i, bytes([i + 1]) * 65) for i in range(signature_count)]
    return encode_vaa(
        guardian_set_index=4,
        signatures=sigs,
        timestamp=1_700_000_000,
        nonce=NONCE,
        emitter_chain=SRC_CHAIN,
        emitter_address=EMITTER_BYTES32,
        sequence=SEQUENCE,
        consistency_level=CONSISTENCY,
        payload=PAYLOAD,
    )


class MockWormholeRpc:
    """In-process mock JSON-RPC server. Scripted heads/logs/hashes/blocks;
    reorgs are simulated by rewriting a block hash between scans; rate limits by
    arming ``fail_get_logs_once``."""

    def __init__(self) -> None:
        self.heads: dict[str, dict[str, Any]] = {}
        self.logs: dict[str, list[dict]] = {}
        self.block_hashes: dict[tuple[str, int], str] = {}
        self.blocks: dict[tuple[str, int], dict] = {}
        self.fail_get_logs_once: set[str] = set()
        self.get_logs_calls = 0

    async def get_head(self, network_id: str) -> dict[str, Any]:
        head = self.heads.get(network_id, {"number": 0})
        return dict(head)

    async def get_logs(self, network_id: str, from_block: int, to_block: int) -> list[dict]:
        self.get_logs_calls += 1
        if network_id in self.fail_get_logs_once:
            self.fail_get_logs_once.discard(network_id)
            raise WormholeRateLimitError("rate limited", retry_after=2)
        out = []
        for log in self.logs.get(network_id, []):
            number = int(log["blockNumber"], 16)
            if from_block <= number <= to_block:
                out.append(dict(log))
        return out

    async def get_block_hash(self, network_id: str, block_number: int) -> str:
        return self.block_hashes.get((network_id, block_number), f"0xhash{block_number}")

    async def get_block(self, network_id: str, block_number: int) -> Optional[dict]:
        return self.blocks.get((network_id, block_number))


class MockGuardianApi:
    """In-process mock guardian/Wormholescan server: returns scripted VAA bytes
    for a (chain, emitter, sequence) triple once quorum is 'reached'."""

    def __init__(self) -> None:
        self.vaas: dict[tuple[int, str, int], bytes] = {}
        self.fail_once = False

    def publish(self, emitter_chain: int, emitter_address: str, sequence: int, vaa: bytes) -> None:
        self.vaas[(emitter_chain, emitter_address.lower(), sequence)] = vaa

    async def get_signed_vaa(
        self, emitter_chain: int, emitter_address: str, sequence: int,
    ) -> Optional[bytes]:
        if self.fail_once:
            self.fail_once = False
            raise WormholeRateLimitError("guardian rate limited", retry_after=1)
        return self.vaas.get((emitter_chain, emitter_address.lower(), sequence))
