"""Axelar GMP fixture + mock-server builder.

Fixtures are generated with the SAME encoders the adapter decodes with
(services.interop.providers.axelar). The source ContractCall's own tx hash +
log index and the destination ContractCallApproved's data fields resolve to one
canonical GMP message id, so both legs correlate on one key even out of order.
"""

from __future__ import annotations

from typing import Any, Optional

from services.interop.providers.axelar import (
    TOPIC_CONTRACT_CALL,
    TOPIC_CONTRACT_CALL_APPROVED,
    TOPIC_CONTRACT_CALL_EXECUTED,
    TOPIC_CONTRACT_CALL_WITH_TOKEN,
    AxelarRateLimitError,
    encode_contract_call_approved_data,
    encode_contract_call_data,
    encode_contract_call_with_token_data,
    gmp_correlation_key,
)
from eth_utils import keccak

SRC_CHAIN = "Ethereum"          # network ethereum-mainnet
DST_CHAIN = "arbitrum"          # network arbitrum-mainnet
SOURCE_TX = "0x" + "ab" * 32
SOURCE_EVENT_INDEX = 4
SENDER = "0x" + "11" * 20
DEST_CONTRACT = "0x" + "22" * 20
PAYLOAD = b"axelar-gmp-observe"
PAYLOAD_HASH = "0x" + keccak(PAYLOAD).hex()
COMMAND_ID = "0x" + "c0" * 32

KEY = gmp_correlation_key(SRC_CHAIN, SOURCE_TX, SOURCE_EVENT_INDEX)


def contract_call(block_number: int = 100, log_index: int = SOURCE_EVENT_INDEX) -> dict[str, Any]:
    return {
        "network_id": "ethereum-mainnet",
        "native_chain_id": "1",
        "axelar_chain": SRC_CHAIN,
        "topics": [TOPIC_CONTRACT_CALL, "0x" + "11" * 20, PAYLOAD_HASH],
        "data": encode_contract_call_data(DST_CHAIN, DEST_CONTRACT, PAYLOAD),
        "transactionHash": SOURCE_TX,
        "blockNumber": hex(block_number),
        "blockHash": "0x" + "b1" * 32,
        "logIndex": hex(log_index),
        "observed_at": "2026-07-11T00:00:00+00:00",
    }


def contract_call_with_token(
    symbol: str = "USDC", amount: int = 1_000_000,
    block_number: int = 100, log_index: int = SOURCE_EVENT_INDEX,
) -> dict[str, Any]:
    return {
        "network_id": "ethereum-mainnet",
        "native_chain_id": "1",
        "axelar_chain": SRC_CHAIN,
        "topics": [TOPIC_CONTRACT_CALL_WITH_TOKEN, "0x" + "11" * 20, PAYLOAD_HASH],
        "data": encode_contract_call_with_token_data(DST_CHAIN, DEST_CONTRACT, PAYLOAD, symbol, amount),
        "transactionHash": SOURCE_TX,
        "blockNumber": hex(block_number),
        "blockHash": "0x" + "b1" * 32,
        "logIndex": hex(log_index),
        "observed_at": "2026-07-11T00:00:00+00:00",
    }


def contract_call_approved(block_number: int = 60, log_index: int = 0) -> dict[str, Any]:
    return {
        "network_id": "arbitrum-mainnet",
        "native_chain_id": "42161",
        "axelar_chain": DST_CHAIN,
        "topics": [TOPIC_CONTRACT_CALL_APPROVED, COMMAND_ID, "0x" + "22" * 20, PAYLOAD_HASH],
        "data": encode_contract_call_approved_data(SRC_CHAIN, SENDER, SOURCE_TX, SOURCE_EVENT_INDEX),
        "transactionHash": "0x" + "cc" * 32,
        "blockNumber": hex(block_number),
        "blockHash": "0x" + "b2" * 32,
        "logIndex": hex(log_index),
        "observed_at": "2026-07-11T00:02:00+00:00",
    }


def contract_call_executed(block_number: int = 61, log_index: int = 1) -> dict[str, Any]:
    return {
        "network_id": "arbitrum-mainnet",
        "native_chain_id": "42161",
        "axelar_chain": DST_CHAIN,
        "topics": [TOPIC_CONTRACT_CALL_EXECUTED, COMMAND_ID],
        "data": "0x",
        "transactionHash": "0x" + "ee" * 32,
        "blockNumber": hex(block_number),
        "blockHash": "0x" + "b3" * 32,
        "logIndex": hex(log_index),
        "observed_at": "2026-07-11T00:03:00+00:00",
    }


def confirmation_record(confirmed: bool = True) -> dict[str, Any]:
    return {
        "confirmed": confirmed,
        "poll_id": "poll-9001",
        "confirmation_height": 21_000_000,
        "verifier_set_id": "vs-7",
        "participants": ["val-a", "val-b", "val-c"],
    }


class MockAxelarRpc:
    def __init__(self) -> None:
        self.heads: dict[str, dict[str, Any]] = {}
        self.logs: dict[str, list[dict]] = {}
        self.block_hashes: dict[tuple[str, int], str] = {}
        self.blocks: dict[tuple[str, int], dict] = {}
        self.fail_get_logs_once: set[str] = set()

    async def get_head(self, network_id: str) -> dict[str, Any]:
        return dict(self.heads.get(network_id, {"number": 0}))

    async def get_logs(self, network_id: str, from_block: int, to_block: int) -> list[dict]:
        if network_id in self.fail_get_logs_once:
            self.fail_get_logs_once.discard(network_id)
            raise AxelarRateLimitError("rate limited", retry_after=3)
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


class MockAxelarConfirmations:
    def __init__(self) -> None:
        self.records: dict[str, dict] = {}

    def publish(self, message_id: str, record: dict) -> None:
        self.records[message_id] = record

    async def get_confirmation(self, message_id: str) -> Optional[dict]:
        return self.records.get(message_id)
