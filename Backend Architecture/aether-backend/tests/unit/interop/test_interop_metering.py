"""Interop usage-meter hook tests (BUILD: metering hook, dedupe-safe).

Proves the interop metering hook wired into ScanWorker.run_cycle:
  * a successful cycle records billable metering_evidence rows for the
    canonical dimensions (observations ingested, reconciliation runs,
    provider cycles; messages correlated when both legs are seen).
  * a restart replay of the SAME persisted checkpoint reproduces the same
    dedupe keys and is recorded NON-billable (excluded_reason="duplicate")
    — checkpoint re-runs can never double-bill.
  * checkpoint_unit_key is deterministic over the highest persisted cursor.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from repositories.repos import reset_in_memory_stores
from repositories.typed_repo import reset_typed_in_memory_stores
from services.interop.metering import (
    INTEROP_USAGE_DIMENSIONS,
    checkpoint_unit_key,
    record_interop_usage,
)
from services.interop.providers.debridge import (
    TOPIC_CREATED_ORDER,
    TOPIC_FULFILLED_ORDER,
    DebridgeAdapter,
    encode_created_order_data,
    encode_dln_order,
    encode_fulfilled_order_data,
)
from services.interop.scan_worker import ScanWorker
from services.metering_evidence.service import EXCLUDED_DUPLICATE

ETH = "ethereum-mainnet"
ARB = "arbitrum-mainnet"
CHAINS = {
    1: {"network_id": ETH, "native_chain_id": "1"},
    42161: {"network_id": ARB, "native_chain_id": "42161"},
}


@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()
    reset_typed_in_memory_stores()
    yield
    reset_in_memory_stores()


class MockEvmRpcServer:
    def __init__(self):
        self.heads: dict[str, int] = {}
        self.logs: dict[str, list[tuple[int, dict]]] = {}

    def set_head(self, network_id, number):
        self.heads[network_id] = number

    def add_log(self, network_id, block_number, log):
        log = {**log, "blockNumber": block_number}
        self.logs.setdefault(network_id, []).append((block_number, log))

    async def get_head(self, network_id):
        return {"number": self.heads.get(network_id, 0)}

    async def get_logs(self, network_id, from_block, to_block):
        return [dict(log) for block, log in self.logs.get(network_id, [])
                if from_block <= block <= to_block]

    async def get_block_hash(self, network_id, block):
        return f"0xhash-{network_id}-{block}"


def _order_id(byte: int) -> bytes:
    return bytes([byte]) * 32


def _maker32(byte: int) -> bytes:
    return b"\x00" * 12 + bytes([byte]) * 20


def _tail() -> bytes:
    return encode_dln_order(maker_nonce=3, give_chain_id=1, give_amount=1_000_000,
                            take_chain_id=42161, take_amount=990_000, maker32=_maker32(0xBB))


def _created_log(order_id: bytes, tx: str) -> dict:
    return {"topics": [TOPIC_CREATED_ORDER],
            "data": encode_created_order_data(order_id, _tail(), native_fix_fee=1, percent_fee=2),
            "transactionHash": tx, "blockHash": "0xb", "logIndex": 0}


def _fulfilled_log(order_id: bytes, tx: str) -> dict:
    return {"topics": [TOPIC_FULFILLED_ORDER],
            "data": encode_fulfilled_order_data(order_id, _tail(), "0x00000000000000000000000000000000000000C0"),
            "transactionHash": tx, "blockHash": "0xd", "logIndex": 0}


async def _metering_rows(dimension: str, tenant: str = "public") -> list[dict]:
    from services.metering_evidence.service import MeteringEvidenceRepository

    return await MeteringEvidenceRepository().find_many(
        {"tenant_id": tenant, "usage_dimension": dimension}, limit=100,
    )


# ── unit: dimension registry + deterministic anchor ───────────────────

def test_dimensions_and_checkpoint_unit_key_are_deterministic():
    assert "interop_provider_cycles" in INTEROP_USAGE_DIMENSIONS
    assert "interop_observations_ingested" in INTEROP_USAGE_DIMENSIONS
    assert "interop_reconciliation_runs" in INTEROP_USAGE_DIMENSIONS
    cp = {"networks": {
        ETH: {"last_scanned_block": 88},
        ARB: {"last_scanned_block": 91},
    }}
    assert checkpoint_unit_key("debridge", cp) == "debridge:91"
    assert checkpoint_unit_key("debridge", {"networks": {}}) == "debridge:0"
    assert checkpoint_unit_key("debridge", None) == "debridge:0"


def test_unknown_dimension_is_ignored_not_raised():
    # Unknown dimensions warn and no-op (fail-safe), they never raise.
    import asyncio

    async def _run():
        await record_interop_usage("public", dimension="not_a_dimension", unit_key="x")

    asyncio.run(_run())


# ── integration: a successful cycle records billable usage ────────────

async def test_successful_cycle_records_billable_usage():
    server = MockEvmRpcServer()
    server.set_head(ETH, 100)
    server.set_head(ARB, 100)
    # CreatedOrder on ETH (source leg) + FulfilledOrder on ARB (destination
    # leg) of the SAME order -> both legs present -> message correlated.
    order = _order_id(0x10)
    server.add_log(ETH, 50, _created_log(order, "0xtx-meter-1"))
    server.add_log(ARB, 60, _fulfilled_log(order, "0xtx-meter-2"))

    worker = ScanWorker(tenant_id="public", adapters={"debridge": DebridgeAdapter(
        rpc_client=server, chain_networks=CHAINS,
    )})
    result = await worker.run_cycle("debridge")
    assert result["status"] == "ok"
    assert result["ingested"] >= 1

    cycles = await _metering_rows("interop_provider_cycles")
    assert len(cycles) == 1
    assert cycles[0]["billable"] is True
    assert cycles[0]["excluded_reason"] is None
    assert cycles[0]["source_provider"] == "debridge"

    obs = await _metering_rows("interop_observations_ingested")
    assert len(obs) == 1
    assert obs[0]["billable"] is True
    assert obs[0]["quantity"] == 2

    correlated = await _metering_rows("interop_messages_correlated")
    assert len(correlated) == 1
    assert correlated[0]["billable"] is True

    recons = await _metering_rows("interop_reconciliation_runs")
    assert len(recons) == 1
    assert recons[0]["billable"] is True


# ── integration: restart replay cannot double-bill ────────────────────

async def test_restart_replay_is_recorded_non_billable():
    server = MockEvmRpcServer()
    server.set_head(ETH, 100)
    server.set_head(ARB, 100)
    server.add_log(ETH, 50, _created_log(_order_id(0x11), "0xtx-meter-3"))
    server.add_log(ARB, 60, _fulfilled_log(_order_id(0x11), "0xtx-meter-4"))

    worker_a = ScanWorker(tenant_id="public", adapters={"debridge": DebridgeAdapter(
        rpc_client=server, chain_networks=CHAINS,
    )})
    first = await worker_a.run_cycle("debridge")
    assert first["status"] == "ok"

    cycles_first = await _metering_rows("interop_provider_cycles")
    assert len(cycles_first) == 1
    assert cycles_first[0]["billable"] is True

    # A brand-new worker over the same durable stores replays the SAME
    # persisted checkpoint (head unchanged -> cursor does not advance -> same
    # dedupe anchors). The metering service records the re-run but marks it
    # non-billable — fail-closed double-billing protection.
    worker_b = ScanWorker(tenant_id="public", adapters={"debridge": DebridgeAdapter(
        rpc_client=server, chain_networks=CHAINS,
    )})
    resumed = await worker_b.run_cycle("debridge")
    assert resumed["status"] == "ok"
    assert resumed["observations"] == 0

    cycles = await _metering_rows("interop_provider_cycles")
    assert len(cycles) == 2
    billable = [c for c in cycles if c["billable"]]
    duplicates = [c for c in cycles if not c["billable"]]
    assert len(billable) == 1
    assert len(duplicates) == 1
    assert duplicates[0]["excluded_reason"] == EXCLUDED_DUPLICATE

    # The duplicate anchor is the same as the original (same dedupe key).
    assert duplicates[0]["dedupe_key"] == billable[0]["dedupe_key"]
