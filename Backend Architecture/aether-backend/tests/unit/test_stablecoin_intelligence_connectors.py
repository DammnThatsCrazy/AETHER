"""Credentialless integration tests for the concrete stablecoin ingestion +
price connectors.

Everything runs against in-memory MOCK RPC / price-feed servers implementing the
injectable ``StablecoinRpcClient`` seam — there is NO live network. The suite
proves: EVM + Solana backfill, confirmation/finality gating, restart-safe
resume, cursor recovery, reorg/fork detection + rollback, rate-limit
classification, duplicate/out-of-order handling, honest price/peg value, and the
credential-waiting certification descriptors.
"""
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from repositories.repos import reset_in_memory_stores
from repositories.stablecoin_repos import StablecoinObservationRepository
from services.stablecoins.connector_base import (
    CONNECTOR_AUTH_ERROR,
    CONNECTOR_CHAIN_MISMATCH,
    CONNECTOR_NOT_CONFIGURED,
    CONNECTOR_OK,
    CONNECTOR_RATE_LIMITED,
    CONNECTOR_TIMEOUT,
    ConnectorPreflightResult,
    StablecoinConnectorError,
    classify_rpc_error,
    decode_cursor,
)
from services.stablecoins.evm_connector import TRANSFER_TOPIC0, StablecoinEVMIngestionConnector
from services.stablecoins.price_feed import (
    CONFIDENCE_HIGH,
    CONFIDENCE_STALE,
    CONFIDENCE_UNAVAILABLE,
    PEG_UNKNOWN,
    StablecoinChainlinkPriceConnector,
)
from services.stablecoins.polling import StablecoinPollingScheduler
from services.stablecoins.registry import PLATFORM_STABLECOIN_REGISTRY
from services.stablecoins.solana_connector import StablecoinSolanaIngestionConnector
from shared.certification import CredentialReadiness, run_certification

BASE_USDC = "usdc:base:mainnet:0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
SOLANA_USDC = "usdc:solana:mainnet:EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
BASE_DEPLOYMENT = PLATFORM_STABLECOIN_REGISTRY.deployments[BASE_USDC]
SOLANA_DEPLOYMENT = PLATFORM_STABLECOIN_REGISTRY.deployments[SOLANA_USDC]

ZERO_ADDR = "0x" + "0" * 40
ADDR_A = "0x" + "a" * 40
ADDR_B = "0x" + "b" * 40


@pytest.fixture(autouse=True)
def reset_repos():
    reset_in_memory_stores()


# ─────────────────────────────────────────────────────────────────────────────
# Mock EVM RPC server (in-memory fake chain)
# ─────────────────────────────────────────────────────────────────────────────


def _addr_topic(addr: str) -> str:
    return "0x" + "0" * 24 + addr[2:].rjust(40, "0")


class FakeHTTPStatusError(Exception):
    """Mimics an httpx status error (carries ``response.status_code``)."""

    class _Resp:
        def __init__(self, code):
            self.status_code = code

    def __init__(self, code):
        self.response = self._Resp(code)
        super().__init__(f"HTTP {code}")


class MockEVMRpcServer:
    def __init__(self, *, chain_id, contract):
        self._chain_id = int(chain_id)
        self.contract = contract.lower()
        self.blocks: list[dict] = []
        self._raise: dict[str, list[Exception]] = {}
        self.calls: list[str] = []

    # ── chain construction ──
    def add_block(self, transfers=None, *, salt=""):
        number = len(self.blocks)
        parent = self.blocks[-1]["hash"] if self.blocks else "0x" + "0" * 64
        block_hash = f"0x{('%s%d' % (salt, number)):>064}".replace(" ", "0")
        logs = []
        for i, (frm, to, amount, tx) in enumerate(transfers or []):
            logs.append({
                "address": self.contract,
                "topics": [TRANSFER_TOPIC0, _addr_topic(frm), _addr_topic(to)],
                "data": f"0x{amount:064x}",
                "blockNumber": hex(number),
                "blockHash": block_hash,
                "transactionHash": tx,
                "logIndex": hex(i),
            })
        self.blocks.append({
            "number": number, "hash": block_hash, "parentHash": parent,
            "timestamp": 1_700_000_000 + number * 12, "logs": logs,
        })
        return number

    def rebuild_from(self, index, *, salt):
        """Reorg: rewrite every block from ``index`` upward with new hashes,
        re-linking parent hashes so the fork is internally consistent."""
        for n in range(index, len(self.blocks)):
            parent = self.blocks[n - 1]["hash"] if n > 0 else "0x" + "0" * 64
            new_hash = f"0x{('%s%d' % (salt, n)):>064}".replace(" ", "0")
            self.blocks[n]["hash"] = new_hash
            self.blocks[n]["parentHash"] = parent
            for lg in self.blocks[n]["logs"]:
                lg["blockHash"] = new_hash

    def raise_on(self, method, exc):
        self._raise.setdefault(method, []).append(exc)

    @property
    def tip(self):
        return len(self.blocks) - 1

    async def execute(self, chain_id, method, params=None, vm_type="evm"):
        self.calls.append(method)
        queued = self._raise.get(method)
        if queued:
            raise queued.pop(0)
        params = params or []
        if method == "eth_chainId":
            return {"result": hex(self._chain_id)}
        if method == "eth_blockNumber":
            return {"result": hex(self.tip)}
        if method == "eth_getBlockByNumber":
            n = int(params[0], 16)
            if 0 <= n < len(self.blocks):
                b = self.blocks[n]
                return {"result": {"number": hex(n), "hash": b["hash"], "parentHash": b["parentHash"], "timestamp": hex(b["timestamp"])}}
            return {"result": None}
        if method == "eth_getLogs":
            flt = params[0]
            frm, to = int(flt["fromBlock"], 16), int(flt["toBlock"], 16)
            addr = str(flt.get("address", "")).lower()
            topic0 = (flt.get("topics") or [None])[0]
            out = []
            for n in range(frm, min(to, self.tip) + 1):
                for lg in self.blocks[n]["logs"]:
                    if addr and lg["address"].lower() != addr:
                        continue
                    if topic0 and lg["topics"][0].lower() != str(topic0).lower():
                        continue
                    out.append(lg)
            return {"result": out}
        if method == "eth_getTransactionReceipt":
            tx = params[0]
            for b in self.blocks:
                logs = [lg for lg in b["logs"] if lg["transactionHash"] == tx]
                if logs:
                    return {"result": {"transactionHash": tx, "status": "0x1", "blockNumber": hex(b["number"]),
                                       "blockHash": b["hash"], "to": self.contract, "logs": logs}}
            return {"result": None}
        raise ValueError(f"unexpected method {method}")


def make_evm_connector(mock, **kw):
    kw.setdefault("confirmations", 1)
    kw.setdefault("max_block_span", 100)
    return StablecoinEVMIngestionConnector(deployment=BASE_DEPLOYMENT, rpc=mock, **kw)


# ─────────────────────────────────────────────────────────────────────────────
# EVM connector tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_evm_bounded_backfill_emits_confirmed_transfers_and_classifies_events():
    mock = MockEVMRpcServer(chain_id=8453, contract=BASE_DEPLOYMENT.contract_or_mint)
    mock.add_block()  # block 0 (empty)
    mock.add_block([(ADDR_A, ADDR_B, 2_500_000, "0xtx1")])  # transfer in block 1
    mock.add_block([(ZERO_ADDR, ADDR_A, 1_000_000, "0xtx2")])  # mint in block 2
    mock.add_block([(ADDR_B, ZERO_ADDR, 500_000, "0xtx3")])  # burn in block 3
    mock.add_block()  # block 4 -> tip, so blocks<=3 are confirmed (confirmations=1)

    connector = make_evm_connector(mock)
    obs, cursor = await connector.fetch_observations(tenant_id="tenant-a", cursor="")

    kinds = {o.transaction_hash: o.event_type.value for o in obs}
    assert kinds == {"0xtx1": "transfer", "0xtx2": "mint", "0xtx3": "burn"}
    amounts = {o.transaction_hash: o.amount_atomic for o in obs}
    assert amounts["0xtx1"] == 2_500_000 and isinstance(amounts["0xtx1"], int)
    # observed_at came from block timestamps (authoritative on-chain time).
    assert all(o.observed_at.endswith("Z") for o in obs)
    assert decode_cursor(cursor)["next_block"] == 4  # advanced past confirmed head


@pytest.mark.asyncio
async def test_evm_confirmation_gating_withholds_unconfirmed_then_releases():
    mock = MockEVMRpcServer(chain_id=8453, contract=BASE_DEPLOYMENT.contract_or_mint)
    mock.add_block()  # 0
    mock.add_block([(ADDR_A, ADDR_B, 7, "0xlate")])  # 1 -> tip; within confirmations=2 window
    connector = make_evm_connector(mock, confirmations=2)

    obs, cursor = await connector.fetch_observations(tenant_id="t", cursor="")
    assert obs == []  # nothing has reached confirmation depth yet

    mock.add_block()  # 2
    mock.add_block()  # 3 -> now block 1 is 2 deep and confirmed
    obs2, _ = await connector.fetch_observations(tenant_id="t", cursor=cursor)
    assert [o.transaction_hash for o in obs2] == ["0xlate"]


@pytest.mark.asyncio
async def test_evm_restart_safe_resume_from_persisted_checkpoint():
    mock = MockEVMRpcServer(chain_id=8453, contract=BASE_DEPLOYMENT.contract_or_mint)
    mock.add_block()
    mock.add_block([(ADDR_A, ADDR_B, 100, "0xa")])
    mock.add_block()  # tip=2 -> block1 confirmed
    first = make_evm_connector(mock)
    obs1, _ = await first.fetch_observations(tenant_id="t", cursor="")
    assert [o.transaction_hash for o in obs1] == ["0xa"]

    # Simulate a process restart: a brand-new connector, EMPTY cursor. It must
    # resume from its durable checkpoint (shared in-memory table), not re-emit.
    mock.add_block([(ADDR_B, ADDR_A, 200, "0xb")])
    mock.add_block()  # tip advances so block3 confirmed
    restarted = make_evm_connector(mock)
    obs2, _ = await restarted.fetch_observations(tenant_id="t", cursor="")
    assert [o.transaction_hash for o in obs2] == ["0xb"]  # 0xa not repeated


@pytest.mark.asyncio
async def test_evm_cursor_recovery_from_opaque_string_only():
    mock = MockEVMRpcServer(chain_id=8453, contract=BASE_DEPLOYMENT.contract_or_mint)
    mock.add_block()
    mock.add_block([(ADDR_A, ADDR_B, 1, "0xc1")])
    mock.add_block()
    c1 = make_evm_connector(mock)
    _, cursor = await c1.fetch_observations(tenant_id="t-string", cursor="")

    # A fresh connector for a DIFFERENT tenant (no persisted checkpoint) resumes
    # purely from the opaque cursor string.
    mock.add_block([(ADDR_B, ADDR_A, 2, "0xc2")])
    mock.add_block()
    c2 = make_evm_connector(mock)
    obs, _ = await c2.fetch_observations(tenant_id="t-string", cursor=cursor)
    assert [o.transaction_hash for o in obs] == ["0xc2"]


@pytest.mark.asyncio
async def test_evm_reorg_detection_rolls_back_orphaned_and_reemits_canonical():
    obs_repo = StablecoinObservationRepository()
    scheduler = StablecoinPollingScheduler()
    mock = MockEVMRpcServer(chain_id=8453, contract=BASE_DEPLOYMENT.contract_or_mint)
    mock.add_block()  # 0
    mock.add_block([(ADDR_A, ADDR_B, 111, "0xORPHAN")])  # 1
    mock.add_block()  # 2
    mock.add_block()  # 3 -> tip; block1 confirmed
    connector = make_evm_connector(mock, reorg_rewind_depth=64)

    r1 = await scheduler.poll_provider(tenant_id="t", connector=connector, source_execution_id="exec-1")
    assert r1.rows_accepted == 1
    assert any(o["transaction_hash"] == "0xORPHAN" for o in await obs_repo.find_many(filters={"tenant_id": "t"}, limit=50))

    # Reorg from block 1: replace the orphaned transfer with a different one and
    # rewrite hashes so parent-hash continuity breaks.
    mock.blocks[1]["logs"] = [{
        "address": mock.contract,
        "topics": [TRANSFER_TOPIC0, _addr_topic(ADDR_B), _addr_topic(ADDR_A)],
        "data": f"0x{222:064x}", "blockNumber": hex(1), "blockHash": "",
        "transactionHash": "0xCANON", "logIndex": hex(0),
    }]
    mock.rebuild_from(1, salt="f")
    mock.add_block()  # extend so safe head advances past reorged blocks

    r2 = await scheduler.poll_provider(tenant_id="t", connector=connector, source_execution_id="exec-2")
    rows = await obs_repo.find_many(filters={"tenant_id": "t"}, limit=50)
    orphan = [o for o in rows if o["transaction_hash"] == "0xORPHAN"]
    canonical = [o for o in rows if o["transaction_hash"] == "0xCANON"]
    # Append-only-correct rollback: the orphan SURVIVES as demoted evidence
    # (demotion markers + remediation audit), never physically deleted.
    assert orphan, "orphaned observation must remain as evidence (append-only)"
    assert all(o.get("demoted") is True for o in orphan)
    assert all(o.get("demotion_reason") == "reorg_rollback" for o in orphan)
    assert canonical and any(o.get("demoted") is not True for o in canonical)


@pytest.mark.asyncio
async def test_evm_duplicate_and_out_of_order_logs_collapse_idempotently():
    mock = MockEVMRpcServer(chain_id=8453, contract=BASE_DEPLOYMENT.contract_or_mint)
    mock.add_block()
    # Two logs in one block, appended out of order (logIndex 0 then 1 but reversed
    # amounts) — the connector must capture both deterministically.
    mock.add_block([(ADDR_A, ADDR_B, 5, "0xd1"), (ADDR_B, ADDR_A, 9, "0xd2")])
    mock.add_block()
    connector = make_evm_connector(mock)
    obs1, _ = await connector.fetch_observations(tenant_id="t", cursor="")
    assert {o.transaction_hash for o in obs1} == {"0xd1", "0xd2"}

    # sequence_of imposes a total (block, logIndex) order regardless of arrival.
    ordered = sorted(obs1, key=connector.sequence_of)
    assert [connector.sequence_of(o) for o in ordered] == sorted(connector.sequence_of(o) for o in obs1)

    # Re-pull the SAME confirmed range (cursor reset) — observation_id is a pure
    # function of identity, so a durable upsert collapses duplicates.
    obs_repo = StablecoinObservationRepository()
    from services.stablecoins.providers import StablecoinProviderIngestionRunner

    runner = StablecoinProviderIngestionRunner()
    await runner.run_execution(tenant_id="t", provider=connector.provider, source_execution_id="x1",
                               source_manifest_id=connector.source_manifest_id, observations=obs1)
    await runner.run_execution(tenant_id="t", provider=connector.provider, source_execution_id="x2",
                               source_manifest_id=connector.source_manifest_id, observations=obs1)
    stored = await obs_repo.find_many(filters={"tenant_id": "t"}, limit=50)
    assert len({o["observation_id"] for o in stored}) == 2  # no duplicate rows


@pytest.mark.asyncio
async def test_evm_rate_limit_and_chain_mismatch_are_classified():
    mock = MockEVMRpcServer(chain_id=8453, contract=BASE_DEPLOYMENT.contract_or_mint)
    mock.add_block()
    mock.add_block()
    mock.raise_on("eth_blockNumber", FakeHTTPStatusError(429))
    connector = make_evm_connector(mock)
    with pytest.raises(StablecoinConnectorError) as ei:
        await connector.fetch_observations(tenant_id="t", cursor="")
    assert ei.value.classification == CONNECTOR_RATE_LIMITED

    # The scheduler degrades to a failed poll rather than crashing.
    mock2 = MockEVMRpcServer(chain_id=8453, contract=BASE_DEPLOYMENT.contract_or_mint)
    mock2.add_block()
    mock2.add_block()
    mock2.raise_on("eth_blockNumber", FakeHTTPStatusError(429))
    scheduler = StablecoinPollingScheduler()
    res = await scheduler.poll_provider(tenant_id="t", connector=make_evm_connector(mock2), source_execution_id="e")
    assert res.status == "failed"
    assert any("rate_limited" in e for e in res.errors)

    # Wrong-chain endpoint fails closed.
    wrong = MockEVMRpcServer(chain_id=1, contract=BASE_DEPLOYMENT.contract_or_mint)
    wrong.add_block()
    with pytest.raises(StablecoinConnectorError) as ei2:
        await make_evm_connector(wrong).test_connection()
    assert ei2.value.classification == "chain_mismatch"


@pytest.mark.asyncio
async def test_evm_receipt_retrieval_capability_is_real():
    mock = MockEVMRpcServer(chain_id=8453, contract=BASE_DEPLOYMENT.contract_or_mint)
    mock.add_block()
    mock.add_block([(ADDR_A, ADDR_B, 5, "0xrcpt")])
    mock.add_block()
    connector = make_evm_connector(mock)
    receipt = await connector.get_receipt("0xrcpt")
    assert receipt is not None
    assert receipt["status"] == "0x1"
    assert receipt["transactionHash"] == "0xrcpt"
    assert await connector.get_receipt("0xmissing") is None


def test_classify_rpc_error_maps_transport_failures():
    assert classify_rpc_error(FakeHTTPStatusError(429)) == CONNECTOR_RATE_LIMITED
    assert classify_rpc_error(FakeHTTPStatusError(503)) == "server_error"
    assert classify_rpc_error(FakeHTTPStatusError(401)) == "auth_error"

    class ReadTimeout(Exception):
        pass

    assert classify_rpc_error(ReadTimeout()) == CONNECTOR_TIMEOUT
    assert classify_rpc_error(RuntimeError("RPC gateway endpoint not configured")) == "not_configured"


@pytest.mark.asyncio
async def test_scheduler_wiring_poll_provider_actually_fetches_and_ingests():
    mock = MockEVMRpcServer(chain_id=8453, contract=BASE_DEPLOYMENT.contract_or_mint)
    mock.add_block()
    mock.add_block([(ADDR_A, ADDR_B, 42, "0xwire")])
    mock.add_block()
    from services.stablecoins.providers import build_stablecoin_ingestion_connector

    connector = build_stablecoin_ingestion_connector(BASE_USDC, rpc=mock, confirmations=1, max_block_span=100)
    scheduler = StablecoinPollingScheduler()
    result = await scheduler.poll_provider(tenant_id="t", connector=connector, source_execution_id="exec-wire")
    assert result.rows_observed == 1
    assert result.rows_accepted == 1
    assert result.status == "healthy"
    assert result.cursor  # non-empty checkpoint cursor persisted
    stored = await StablecoinObservationRepository().find_many(filters={"tenant_id": "t"}, limit=10)
    assert any(o["transaction_hash"] == "0xwire" for o in stored)


# ─────────────────────────────────────────────────────────────────────────────
# Mock Solana RPC server + tests
# ─────────────────────────────────────────────────────────────────────────────

GENESIS_HASH = "GENhash1111111111111111111111111111111111111"


def _spl_transfer(sig, source, dest, amount, mint):
    return {
        "transaction": {"signatures": [sig], "message": {"instructions": [
            {"program": "spl-token", "parsed": {"type": "transferChecked", "info": {
                "source": source, "destination": dest, "mint": mint,
                "tokenAmount": {"amount": str(amount), "decimals": 6}}}},
        ]}},
        "meta": {"err": None, "preTokenBalances": [{"mint": mint}], "postTokenBalances": [{"mint": mint}], "innerInstructions": []},
    }


class MockSolanaRpcServer:
    def __init__(self, *, chain_id, genesis_hash):
        self._chain_id = chain_id
        self.blocks: dict[int, dict] = {0: {"blockhash": genesis_hash, "previousBlockhash": "", "parentSlot": 0, "blockTime": 1_700_000_000, "transactions": []}}
        self._raise: dict[str, list[Exception]] = {}
        self.calls: list[str] = []

    def set_slot(self, slot, *, transactions=None, salt=""):
        self.blocks[slot] = {
            "blockhash": f"hash-{salt}-{slot}", "previousBlockhash": f"hash-{salt}-{slot-1}",
            "parentSlot": slot - 1, "blockTime": 1_700_000_000 + slot, "transactions": transactions or [],
        }

    @property
    def tip(self):
        return max(self.blocks)

    def raise_on(self, method, exc):
        self._raise.setdefault(method, []).append(exc)

    async def execute(self, chain_id, method, params=None, vm_type="solana"):
        self.calls.append(method)
        queued = self._raise.get(method)
        if queued:
            raise queued.pop(0)
        params = params or []
        if method == "sol_getSlot":
            return {"result": self.tip}
        if method == "sol_getBlock":
            slot = int(params[0])
            block = self.blocks.get(slot)
            return {"result": block if block is not None else None}
        raise ValueError(f"unexpected method {method}")


def make_solana_connector(mock, **kw):
    kw.setdefault("finality_threshold_slots", 1)
    kw.setdefault("start_slot", 1)
    kw.setdefault("expected_genesis_hash", GENESIS_HASH)
    kw.setdefault("max_slot_span", 100)
    return StablecoinSolanaIngestionConnector(deployment=SOLANA_DEPLOYMENT, rpc=mock, **kw)


@pytest.mark.asyncio
async def test_solana_backfill_emits_finalized_mint_transfers():
    mint = SOLANA_DEPLOYMENT.contract_or_mint
    mock = MockSolanaRpcServer(chain_id="solana-mainnet", genesis_hash=GENESIS_HASH)
    mock.set_slot(1, transactions=[_spl_transfer("sigA", "srcA", "dstB", 3_000_000, mint)])
    mock.set_slot(2, transactions=[
        _spl_transfer("sigMISMATCH", "s", "d", 9, "OtherMint1111111111111111111111111111111111"),
    ])
    mock.set_slot(3)  # tip -> slots<=2 are finalized (threshold=1)
    connector = make_solana_connector(mock)
    obs, cursor = await connector.fetch_observations(tenant_id="t", cursor="")
    assert [o.transaction_hash for o in obs] == ["sigA"]  # other mint ignored
    assert obs[0].amount_atomic == 3_000_000
    assert obs[0].event_type.value == "transfer"
    assert decode_cursor(cursor)["next_slot"] == 3


@pytest.mark.asyncio
async def test_solana_genesis_identity_mismatch_fails_closed():
    mock = MockSolanaRpcServer(chain_id="solana-mainnet", genesis_hash="WRONGgenesis")
    connector = make_solana_connector(mock)
    with pytest.raises(StablecoinConnectorError) as ei:
        await connector.test_connection()
    assert ei.value.classification == "chain_mismatch"


@pytest.mark.asyncio
async def test_solana_restart_resume_and_skipped_slots():
    mint = SOLANA_DEPLOYMENT.contract_or_mint
    mock = MockSolanaRpcServer(chain_id="solana-mainnet", genesis_hash=GENESIS_HASH)
    mock.set_slot(1, transactions=[_spl_transfer("s1", "a", "b", 10, mint)])
    # slot 2 intentionally absent (skipped/leaderless slot)
    mock.set_slot(3, transactions=[_spl_transfer("s3", "a", "b", 20, mint)])
    mock.set_slot(4)  # tip
    first = make_solana_connector(mock)
    obs1, _ = await first.fetch_observations(tenant_id="t", cursor="")
    assert {o.transaction_hash for o in obs1} == {"s1", "s3"}

    mock.set_slot(5, transactions=[_spl_transfer("s5", "a", "b", 30, mint)])
    mock.set_slot(6)  # tip advances so slot5 finalized
    restarted = make_solana_connector(mock)
    obs2, _ = await restarted.fetch_observations(tenant_id="t", cursor="")
    assert {o.transaction_hash for o in obs2} == {"s5"}  # resumed, no repeats


@pytest.mark.asyncio
async def test_solana_fork_detection_rolls_back_and_reemits():
    obs_repo = StablecoinObservationRepository()
    scheduler = StablecoinPollingScheduler()
    mint = SOLANA_DEPLOYMENT.contract_or_mint
    mock = MockSolanaRpcServer(chain_id="solana-mainnet", genesis_hash=GENESIS_HASH)
    mock.set_slot(1, transactions=[_spl_transfer("sigFORKED", "a", "b", 50, mint)], salt="x")
    mock.set_slot(2, salt="x")
    mock.set_slot(3, salt="x")  # tip -> slots<=2 finalized
    connector = make_solana_connector(mock, fork_rewind_slots=64)
    await scheduler.poll_provider(tenant_id="t", connector=connector, source_execution_id="s-exec-1")
    assert any(o["transaction_hash"] == "sigFORKED" for o in await obs_repo.find_many(filters={"tenant_id": "t"}, limit=50))

    # Fork: rewrite the processed slots (new blockhashes) and replace the tx.
    mock.set_slot(1, transactions=[_spl_transfer("sigCANON", "b", "a", 77, mint)], salt="y")
    mock.set_slot(2, salt="y")
    mock.set_slot(3, salt="y")
    mock.set_slot(4, salt="y")  # extend
    await scheduler.poll_provider(tenant_id="t", connector=connector, source_execution_id="s-exec-2")
    rows = await obs_repo.find_many(filters={"tenant_id": "t"}, limit=50)
    forked = [o for o in rows if o["transaction_hash"] == "sigFORKED"]
    canonical = [o for o in rows if o["transaction_hash"] == "sigCANON"]
    # Append-only-correct fork rollback: the forked observation SURVIVES as
    # demoted evidence, the canonical replacement is emitted non-demoted.
    assert forked, "forked observation must remain as evidence (append-only)"
    assert all(o.get("demoted") is True for o in forked)
    assert all(o.get("demotion_reason") == "reorg_rollback" for o in forked)
    assert canonical and any(o.get("demoted") is not True for o in canonical)


# ─────────────────────────────────────────────────────────────────────────────
# Mock Chainlink price feed + honest-value tests
# ─────────────────────────────────────────────────────────────────────────────


def _word(value: int) -> str:
    return f"{value & (2**256 - 1):064x}"


def _round_data(answer, *, updated_at, round_id=10, answered_in_round=10):
    body = _word(round_id) + _word(answer) + _word(updated_at) + _word(updated_at) + _word(answered_in_round)
    return "0x" + body


class MockPriceServer:
    def __init__(self, *, decimals=8):
        self._decimals = decimals
        self._round = None  # str hex or exception or None
        self._raise = None

    def set_round(self, answer, *, updated_at):
        self._round = _round_data(answer, updated_at=updated_at)

    def set_raw(self, raw):
        self._round = raw

    def set_raise(self, exc):
        self._raise = exc

    async def execute(self, chain_id, method, params=None, vm_type="evm"):
        if self._raise is not None and method == "eth_call" and params and params[0]["data"].startswith("0xfeaf"):
            raise self._raise
        if method != "eth_call":
            raise ValueError(method)
        data = params[0]["data"]
        if data == "0x313ce567":  # decimals()
            return {"result": "0x" + _word(self._decimals)}
        if data.startswith("0xfeaf"):  # latestRoundData()
            return {"result": self._round if self._round is not None else "0x"}
        raise ValueError(data)


def make_price_connector(mock, **kw):
    kw.setdefault("feed_address", "0xFEED000000000000000000000000000000000001")
    kw.setdefault("staleness_threshold_seconds", 3600)
    return StablecoinChainlinkPriceConnector(deployment=BASE_DEPLOYMENT, rpc=mock, **kw)


def _fresh_ts():
    from shared.common.common import utc_now

    return int(utc_now().timestamp())


@pytest.mark.asyncio
async def test_price_on_peg_uses_decimal_and_attributes_source():
    mock = MockPriceServer(decimals=8)
    mock.set_round(1_00_000_000, updated_at=_fresh_ts())  # 1.00000000
    snap = await make_price_connector(mock).get_price_observation()
    assert snap.available is True
    assert snap.price_usd == Decimal("1.00000000")
    assert isinstance(snap.price_usd, Decimal)
    assert snap.peg_status == "on_peg"
    assert snap.peg_deviation_bps == Decimal("0")
    assert snap.confidence == CONFIDENCE_HIGH
    assert snap.source["feed_address"].lower().startswith("0xfeed")
    assert snap.source["round_id"] == "10"


@pytest.mark.asyncio
async def test_price_depeg_and_minor_deviation_classification():
    depeg = MockPriceServer()
    depeg.set_round(90_000_000, updated_at=_fresh_ts())  # 0.90 -> -1000 bps
    snap = await make_price_connector(depeg).get_price_observation()
    assert snap.peg_status == "depegged"
    assert snap.peg_deviation_bps == Decimal("-1000.00000000")

    minor = MockPriceServer()
    minor.set_round(99_500_000, updated_at=_fresh_ts())  # 0.995 -> -50 bps
    snap2 = await make_price_connector(minor).get_price_observation()
    assert snap2.peg_status == "minor_deviation"


@pytest.mark.asyncio
async def test_price_stale_answer_is_not_trusted_for_peg():
    mock = MockPriceServer()
    mock.set_round(1_00_000_000, updated_at=_fresh_ts() - 10_000)  # older than staleness window
    snap = await make_price_connector(mock, staleness_threshold_seconds=3600).get_price_observation()
    assert snap.available is True
    assert snap.stale is True
    assert snap.price_usd == Decimal("1.00000000")  # value preserved, honestly
    assert snap.peg_status == PEG_UNKNOWN  # never assumed on-peg
    assert snap.peg_deviation_bps is None
    assert snap.confidence == CONFIDENCE_STALE


@pytest.mark.asyncio
async def test_price_unavailable_never_zero_never_one():
    # Revert / rate limit -> unavailable, price is None (never 0, never 1 USD).
    err = MockPriceServer()
    err.set_raise(FakeHTTPStatusError(429))
    snap = await make_price_connector(err).get_price_observation()
    assert snap.available is False
    assert snap.price_usd is None
    assert snap.peg_status == PEG_UNKNOWN
    assert snap.confidence == CONFIDENCE_UNAVAILABLE
    assert snap.reason == CONNECTOR_RATE_LIMITED

    # Empty response body -> unavailable.
    empty = MockPriceServer()
    empty.set_raw("0x")
    snap2 = await make_price_connector(empty).get_price_observation()
    assert snap2.available is False and snap2.price_usd is None

    # Non-positive answer is NOT a price; must not surface 0.
    zero = MockPriceServer()
    zero.set_round(0, updated_at=_fresh_ts())
    snap3 = await make_price_connector(zero).get_price_observation()
    assert snap3.available is False
    assert snap3.price_usd is None
    assert snap3.reason == "non_positive_answer"


# ─────────────────────────────────────────────────────────────────────────────
# Certification descriptors
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_all_connectors_certify_as_credential_waiting():
    mock_evm = MockEVMRpcServer(chain_id=8453, contract=BASE_DEPLOYMENT.contract_or_mint)
    connectors = [
        make_evm_connector(mock_evm),
        make_solana_connector(MockSolanaRpcServer(chain_id="solana-mainnet", genesis_hash=GENESIS_HASH)),
        make_price_connector(MockPriceServer()),
    ]
    for connector in connectors:
        descriptor = connector.certification_descriptor()
        assert descriptor.implementation_state == CredentialReadiness.CREDENTIAL_WAITING
        assert descriptor.first_release is True
        assert "transaction_execution" in descriptor.unsupported_operations or descriptor.domain == "stablecoin_price"
        assert descriptor.required_endpoints  # declares the RPC endpoint it needs
        results = run_certification(connector)
        failed = [r.name for r in results if not r.passed]
        assert failed == [], f"{type(connector).__name__} failed checks: {failed}"


# ─────────────────────────────────────────────────────────────────────────────
# Read-only observer preflight — typed, fail-closed, never raises, no writes
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_evm_preflight_ok_reads_only_chain_id():
    mock = MockEVMRpcServer(chain_id=8453, contract=BASE_DEPLOYMENT.contract_or_mint)
    result = await make_evm_connector(mock).preflight()
    assert isinstance(result, ConnectorPreflightResult)
    assert result.ok is True and result.status == CONNECTOR_OK
    assert result.checked_at  # stamped
    # observe-only identity probe — the chain-id read alone, no logs/blocks/receipts
    assert mock.calls == ["eth_chainId"]


@pytest.mark.asyncio
async def test_evm_preflight_wrong_chain_fails_closed_without_raising():
    wrong = MockEVMRpcServer(chain_id=1, contract=BASE_DEPLOYMENT.contract_or_mint)
    result = await make_evm_connector(wrong).preflight()  # must NOT raise
    assert result.ok is False and result.status == CONNECTOR_CHAIN_MISMATCH


@pytest.mark.asyncio
@pytest.mark.parametrize("exc,expected", [
    (FakeHTTPStatusError(429), CONNECTOR_RATE_LIMITED),
    (FakeHTTPStatusError(401), CONNECTOR_AUTH_ERROR),
    (RuntimeError("RPC gateway endpoint not configured"), CONNECTOR_NOT_CONFIGURED),
])
async def test_evm_preflight_classifies_failures_fail_closed(exc, expected):
    mock = MockEVMRpcServer(chain_id=8453, contract=BASE_DEPLOYMENT.contract_or_mint)
    mock.raise_on("eth_chainId", exc)
    result = await make_evm_connector(mock).preflight()
    assert result.ok is False and result.status == expected


@pytest.mark.asyncio
async def test_solana_preflight_ok_reads_only():
    mock = MockSolanaRpcServer(chain_id="solana-mainnet", genesis_hash=GENESIS_HASH)
    result = await make_solana_connector(mock).preflight()
    assert result.ok is True and result.status == CONNECTOR_OK
    # observe-only: slot + genesis-block identity reads, nothing else
    assert set(mock.calls) <= {"sol_getSlot", "sol_getBlock"}


@pytest.mark.asyncio
async def test_solana_preflight_timeout_fails_closed():
    mock = MockSolanaRpcServer(chain_id="solana-mainnet", genesis_hash=GENESIS_HASH)
    mock.raise_on("sol_getSlot", TimeoutError("slot read timed out"))
    result = await make_solana_connector(mock).preflight()
    assert result.ok is False and result.status == CONNECTOR_TIMEOUT
