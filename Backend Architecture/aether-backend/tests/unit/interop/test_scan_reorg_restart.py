"""Deterministic scan-loop determinism tests (BUILD task: scan/reorg/restart).

Proves the ScanWorker's durable contract against the real CorrelationEngine,
DebridgeAdapter and MockEvmRpcServer (NO live network):
  * scan -> ingest -> checkpoint persist, then a re-run of the SAME checkpoint
    yields zero observations (idempotent resume — no duplication).
  * reorg (block-hash change) -> reorg observation + cursor rewind -> rescan
    re-observes the same event without creating a duplicate message row.
  * restart (fresh worker instance over the same durable stores) resumes from
    the persisted checkpoint without duplication or skip.
  * decode-failure counter increments on malformed logs without aborting.
  * dead-letter counter increments when a poison observation is quarantined.
  * build_interop_scan_coro is importable from services.interop.lifecycle and
    returns a coroutine (the runtime worker-spec entry point).
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from repositories.interop_repos import (
    InteropMessageRepo,
    InteropProviderCheckpointRepo,
)
from repositories.repos import reset_in_memory_stores
from repositories.typed_repo import reset_typed_in_memory_stores
from services.interop.providers.base import InteropProviderAdapter, OperationalFieldsMixin
from services.interop.providers.debridge import (
    TOPIC_CREATED_ORDER,
    DebridgeAdapter,
    encode_created_order_data,
    encode_dln_order,
)
from services.interop.providers.transport import RpcRateLimited
from services.interop.scan_worker import ScanWorker

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


class MockEvmRpcServer:
    def __init__(self):
        self.heads: dict[str, int] = {}
        self.logs: dict[str, list[tuple[int, dict]]] = {}
        self.hashes: dict[tuple[str, int], str] = {}

    def set_head(self, network_id, number):
        self.heads[network_id] = number

    def add_log(self, network_id, block_number, log):
        log = {**log, "blockNumber": block_number}
        self.logs.setdefault(network_id, []).append((block_number, log))
        self.hashes.setdefault((network_id, block_number), f"0xhash-{network_id}-{block_number}")

    def set_block_hash(self, network_id, block, value):
        self.hashes[(network_id, block)] = value

    async def get_head(self, network_id):
        return {"number": self.heads.get(network_id, 0)}

    async def get_logs(self, network_id, from_block, to_block):
        return [dict(log) for block, log in self.logs.get(network_id, []) if from_block <= block <= to_block]

    async def get_block_hash(self, network_id, block):
        return self.hashes.get((network_id, block), f"0xhash-{network_id}-{block}")


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


def _worker(server, *, adapters=None) -> ScanWorker:
    adapter = adapters or DebridgeAdapter(rpc_client=server, chain_networks=CHAINS)
    return ScanWorker(
        tenant_id="public",
        adapters={"debridge": adapter} if adapters is None else adapters,
    )


async def _count_messages() -> int:
    rows = await InteropMessageRepo().find_many(limit=10_000)
    return len(rows)


async def _checkpoints_for(provider_id: str) -> list[dict]:
    rows = await InteropProviderCheckpointRepo().find_many(
        {"provider_id": provider_id}, limit=100,
    )
    return rows


# ── scan -> persist -> idempotent resume ─────────────────────────────────

async def test_scan_persists_checkpoint_and_rerun_is_idempotent():
    server = MockEvmRpcServer()
    server.set_head(ETH, 100)
    server.set_head(ARB, 100)
    server.add_log(ETH, 50, _created_log(_order_id(0x01), "0xtx-scan-1"))
    worker = _worker(server)

    first = await worker.run_cycle("debridge")
    assert first["status"] == "ok"
    assert first["observations"] == 1
    assert first["ingested"] == 1
    assert await _count_messages() == 1

    # Durable checkpoint persisted under the sentinel network.
    rows = await _checkpoints_for("debridge")
    assert len(rows) == 1
    evidence = rows[0]["evidence"]
    assert evidence["networks"][ETH]["last_scanned_block"] >= 50
    assert evidence["runtime"]["reachable"] is True

    # Re-running the SAME checkpoint yields no observations — idempotent resume.
    second = await worker.run_cycle("debridge")
    assert second["status"] == "ok"
    assert second["observations"] == 0
    assert await _count_messages() == 1  # no duplication


# ── restart -> resume without duplication or skip ────────────────────────

async def test_restart_resumes_from_persisted_checkpoint():
    server = MockEvmRpcServer()
    server.set_head(ETH, 100)
    server.set_head(ARB, 100)
    server.add_log(ETH, 50, _created_log(_order_id(0x02), "0xtx-restart-1"))

    # First process instance scans and persists.
    worker_a = _worker(server)
    first = await worker_a.run_cycle("debridge")
    assert first["status"] == "ok"
    assert first["observations"] == 1
    assert await _count_messages() == 1

    # A brand-new worker (restart) over the same durable stores resumes from the
    # persisted checkpoint: cursor is already past block 50, so no new
    # observations are scanned and no messages are duplicated or skipped.
    worker_b = _worker(server)
    resumed = await worker_b.run_cycle("debridge")
    assert resumed["status"] == "ok"
    assert resumed["observations"] == 0
    assert await _count_messages() == 1

    # The restarted worker also picked up the persisted runtime telemetry.
    rows = await _checkpoints_for("debridge")
    assert rows[0]["evidence"]["runtime"]["reachable"] is True


# ── reorg -> rewind -> rescan without duplication ────────────────────────

async def test_reorg_rescan_reobserves_without_duplicate():
    server = MockEvmRpcServer()
    server.set_head(ETH, 100)
    server.set_head(ARB, 100)
    server.add_log(ETH, 50, _created_log(_order_id(0x03), "0xtx-reorg-1"))
    worker = _worker(server)

    first = await worker.run_cycle("debridge")
    assert first["status"] == "ok"
    assert first["observations"] == 1
    assert await _count_messages() == 1

    # Reorg via cursor-drift: the chain head recedes below the scanned cursor
    # (head drops from 100 to 40, below the confirmed cursor at block 88). The
    # adapter emits a reorg observation and rewinds the cursor below the fork.
    server.set_head(ETH, 40)

    reorg = await worker.run_cycle("debridge")
    assert reorg["status"] == "ok"
    assert reorg["observations"] == 1  # the reorg observation
    # Reorg moves the non-terminal message to 'reorged'; no new row.
    assert await _count_messages() == 1

    rows = await _checkpoints_for("debridge")
    assert rows[0]["evidence"]["runtime"]["reorg_count"] == 1
    # Cursor rewound below the log block (safe_head 40-12=28 -> cursor 27).
    assert rows[0]["evidence"]["networks"][ETH]["last_scanned_block"] < 50

    # Rescan with the head restored: the rewound window re-observes block 50
    # and re-confirms the SAME message (conflict key dedups) — still exactly
    # one row, proving no duplication after a reorg.
    server.set_head(ETH, 100)
    rescan = await worker.run_cycle("debridge")
    assert rescan["status"] == "ok"
    assert rescan["observations"] == 1
    assert await _count_messages() == 1

    messages = await InteropMessageRepo().find_many(limit=10_000)
    assert messages[0]["status"] == "source_confirmed"


async def test_hash_mismatch_reorg_counts_and_rewinds():
    """Reorg detected by last-scanned-block hash change also counts."""
    server = MockEvmRpcServer()
    server.set_head(ETH, 100)
    server.set_head(ARB, 100)
    server.add_log(ETH, 50, _created_log(_order_id(0x09), "0xtx-reorg-hash"))
    worker = _worker(server)

    first = await worker.run_cycle("debridge")
    assert first["status"] == "ok"
    rows = await _checkpoints_for("debridge")
    last_scanned = rows[0]["evidence"]["networks"][ETH]["last_scanned_block"]
    assert last_scanned == 88  # safe_head = 100 - 12 confirmations

    # The canonical hash of the last-scanned block changes -> reorg at that point.
    server.set_block_hash(ETH, last_scanned, "0xreorged-hash-88")

    reorg = await worker.run_cycle("debridge")
    assert reorg["status"] == "ok"
    assert reorg["observations"] == 1
    rows = await _checkpoints_for("debridge")
    assert rows[0]["evidence"]["runtime"]["reorg_count"] == 1
    assert rows[0]["evidence"]["networks"][ETH]["last_scanned_block"] == last_scanned - 1
    assert await _count_messages() == 1


# ── decode-failure counter ───────────────────────────────────────────────

async def test_decode_failure_increments_counter_without_aborting():
    server = MockEvmRpcServer()
    server.set_head(ETH, 100)
    server.set_head(ARB, 100)
    # Malformed log: data too short to decode -> decode error, not an abort.
    server.add_log(ETH, 60, {"topics": [TOPIC_CREATED_ORDER], "data": "0x1234",
                             "transactionHash": "0xtx-bad-1", "logIndex": 0})
    server.add_log(ETH, 61, _created_log(_order_id(0x04), "0xtx-good-1"))
    worker = _worker(server)

    result = await worker.run_cycle("debridge")
    assert result["status"] == "ok"
    # The good log was still decoded and ingested.
    assert result["ingested"] >= 1

    rows = await _checkpoints_for("debridge")
    assert rows[0]["evidence"]["runtime"]["decode_failures"] == 1
    # No message row exists for the malformed log (skipped, not dead-lettered).
    assert await _count_messages() == 1


# ── dead-letter counter ──────────────────────────────────────────────────

class _PoisonAdapter(OperationalFieldsMixin, InteropProviderAdapter):
    provider_id = "poison"
    provider_kind = "poison"
    display_name = "Poison (test)"
    implementation_status = "scaffolded"

    async def _scan_cycle(self, checkpoint=None):
        return [{
            "phase": "bogus",
            "correlation_key": "poison:1",
            "provider_id": "poison",
            "provider_kind": "poison",
        }], {"runtime": {}, "networks": {}}

    def decode_log(self, raw_log):
        return None


async def test_dead_letter_counter_increments():
    worker = ScanWorker(tenant_id="public", adapters={"poison": _PoisonAdapter()})
    result = await worker.run_cycle("poison")
    assert result["status"] == "ok"
    assert result["dead_lettered"] == 1
    assert result["ingested"] == 0

    rows = await _checkpoints_for("poison")
    assert rows[0]["evidence"]["runtime"]["dead_letter_count"] == 1


# ── graph projection wiring (dead-code builders now wired) ───────────────

def _obs(provider: str = "debridge") -> dict:
    return {
        "provider_id": provider,
        "provider_kind": provider,
        "phase": "sent",
        "correlation_key": f"{provider}:order:0x1",
        "source_network_id": "ethereum-mainnet",
        "destination_network_id": "arbitrum-mainnet",
        "path_id": f"{provider}:ethereum-mainnet->arbitrum-mainnet",
        "endpoint_ref": {
            "gateway_id": f"{provider}:dln_source:ethereum-mainnet",
            "network_id": "ethereum-mainnet", "native_chain_id": "1",
            "block_number": 50,
        },
        "observed_at": "2026-08-08T00:00:00+00:00",
    }


async def test_graph_projector_wires_topology_mutations():
    from services.interop.graph_wiring import InteropGraphProjector
    from services.interop.providers.debridge import DebridgeAdapter

    adapter = DebridgeAdapter()  # descriptor (structural, no creds needed)
    obs = [_obs()]

    projector = InteropGraphProjector(enabled=True)
    result = await projector.project(
        "public", obs, [], provider=adapter.descriptor(), trace_id="t-graph",
    )
    # Provider vertex + gateway/chain vertices + path + edges all persisted.
    assert result.graph_mutations_built > 0
    assert result.graph_mutations_persisted > 0

    # Disabled projector is a no-op (zero graph cost when gated off).
    disabled = InteropGraphProjector(enabled=False)
    result_off = await disabled.project(
        "public", obs, [], provider=adapter.descriptor(), trace_id="t-off",
    )
    assert result_off.graph_mutations_built == 0


# ── security policy snapshot caller ──────────────────────────────────────

async def test_security_snapshot_caller_snapshots_policy():
    from repositories.interop_repos import SecurityPolicySnapshotRepo
    from services.interop.security import scan_security_policy_snapshots

    obs = [_obs()]
    emitted = await scan_security_policy_snapshots("public", obs)
    assert any(e["event_name"] == "interop_security_policy_snapshot_recorded"
               for e in emitted)

    rows = await SecurityPolicySnapshotRepo().find_many(
        {"tenant_id": "public", "provider_id": "debridge"}, limit=10,
    )
    assert len(rows) == 1
    assert rows[0]["verification_model"] == "external_validator_set"
    assert rows[0]["content_hash"].startswith("sha256:")


# ── runtime worker-spec entry point ──────────────────────────────────────

async def test_build_interop_scan_coro_importable_and_is_coroutine():
    import inspect

    from services.interop.lifecycle import build_interop_scan_coro

    coro = build_interop_scan_coro(poll_interval_seconds=0.01)
    assert inspect.iscoroutine(coro)
    # A single cancelled tick should not raise: run one iteration, cancel.
    import asyncio

    async def _tick_once():
        await coro

    task = asyncio.create_task(coro)
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
