"""Chainlink CCIP fixture + mock-server builder.

Fixtures are generated with the SAME encoders the adapter decodes with
(services.interop.providers.chainlink_ccip). Source CCIPSendRequested, the
CommitStore ReportAccepted interval, and OffRamp ExecutionStateChanged all key
on one messageId (the commit via sequence-interval expansion), so the lifecycle
correlates on one canonical key.
"""

from __future__ import annotations

from typing import Any, Optional

from services.interop.providers.chainlink_ccip import (
    TOPIC_CCIP_SEND_REQUESTED,
    TOPIC_EXECUTION_STATE_CHANGED,
    TOPIC_REPORT_ACCEPTED,
    CcipRateLimitError,
    ccip_correlation_key,
    encode_ccip_send_requested_data,
    encode_commit_report_data,
    encode_execution_state_changed_data,
)

SRC_SELECTOR = 5009297550715157269      # ethereum-mainnet
DST_SELECTOR = 4949039107694359620      # arbitrum-mainnet
SEQUENCE = 100
MESSAGE_ID = "0x" + "7e" * 32
SENDER = "0x" + "11" * 20
RECEIVER = "0x" + "22" * 20
MERKLE_ROOT = "0x" + "cc" * 32

KEY = ccip_correlation_key(MESSAGE_ID)


def ccip_send_requested(
    block_number: int = 100, log_index: int = 0,
    message_id: str = MESSAGE_ID, sequence: int = SEQUENCE,
) -> dict[str, Any]:
    return {
        "network_id": "ethereum-mainnet",
        "native_chain_id": "1",
        "dest_chain_selector": DST_SELECTOR,
        "topics": [TOPIC_CCIP_SEND_REQUESTED],
        "data": encode_ccip_send_requested_data(
            SRC_SELECTOR, SENDER, RECEIVER, sequence, message_id,
        ),
        "transactionHash": "0x" + "aa" * 32,
        "blockNumber": hex(block_number),
        "blockHash": "0x" + "b1" * 32,
        "logIndex": hex(log_index),
        "observed_at": "2026-07-12T00:00:00+00:00",
    }


def report_accepted(
    min_seq: int = 90, max_seq: int = 110, block_number: int = 55, log_index: int = 0,
) -> dict[str, Any]:
    return {
        "network_id": "arbitrum-mainnet",
        "native_chain_id": "42161",
        "source_chain_selector": SRC_SELECTOR,
        "topics": [TOPIC_REPORT_ACCEPTED],
        "data": encode_commit_report_data(min_seq, max_seq, MERKLE_ROOT),
        "transactionHash": "0x" + "bb" * 32,
        "blockNumber": hex(block_number),
        "blockHash": "0x" + "b2" * 32,
        "logIndex": hex(log_index),
        "observed_at": "2026-07-12T00:01:00+00:00",
    }


def execution_state_changed(
    state: int = 2, sequence: int = SEQUENCE, message_id: str = MESSAGE_ID,
    return_data: bytes = b"", block_number: int = 56, log_index: int = 0,
) -> dict[str, Any]:
    return {
        "network_id": "arbitrum-mainnet",
        "native_chain_id": "42161",
        "source_chain_selector": SRC_SELECTOR,
        "topics": [
            TOPIC_EXECUTION_STATE_CHANGED,
            hex(sequence),
            message_id,
        ],
        "data": encode_execution_state_changed_data(state, return_data),
        "transactionHash": "0x" + "dd" * 32,
        "blockNumber": hex(block_number),
        "blockHash": "0x" + "b3" * 32,
        "logIndex": hex(log_index),
        "observed_at": "2026-07-12T00:02:00+00:00",
    }


class MockCcipRpc:
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
            raise CcipRateLimitError("rate limited", retry_after=5)
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
