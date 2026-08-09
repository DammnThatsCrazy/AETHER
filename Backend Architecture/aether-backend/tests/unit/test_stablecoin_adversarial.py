"""Adversarial deterministic tests for the stablecoin observer stack.

Covers the 11 Phase-0 adversarial scenarios with in-memory MOCK RPC / price-feed
servers — NO live network:

    1. RPC timeout
    2. RPC rate limit
    3. malformed RPC response
    4. chain mismatch
    5. reorg
    6. conflicting price providers
    7. stale price
    8. unpriced token
    9. duplicate transaction
   10. restart after checkpoint
   11. credential rotation

INVARIANT threaded through every scenario: a failure is ALWAYS distinguishable
from an empty-but-healthy result. Polls degrade to ``failed``/``denied``,
preflights return ``ok=False`` with a classified ``CONNECTOR_*`` token, prices
become UNAVAILABLE (``None``, never 0 / never assumed 1 USD), and gates deny —
nothing is ever reported as a healthy empty dataset.
"""
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from repositories.repos import reset_in_memory_stores
from repositories.stablecoin_repos import (
    StablecoinObservationRepository,
    StablecoinPollingCheckpointRepository,
    StablecoinProviderHealthRepository,
    StablecoinReconciliationRepository,
)
from services.onchain.rpc_gateway import RPCGateway
from services.stablecoins.connector_base import (
    CONNECTOR_BAD_RESPONSE,
    CONNECTOR_CHAIN_MISMATCH,
    CONNECTOR_RATE_LIMITED,
    CONNECTOR_TIMEOUT,
    StablecoinConnectorError,
)
from services.stablecoins.evm_connector import TRANSFER_TOPIC0, StablecoinEVMIngestionConnector
from services.stablecoins.governance import (
    StablecoinCapabilityEntitlement,
    StablecoinEntitlementError,
    StablecoinEntitlementGuard,
    StablecoinGovernanceService,
)
from services.stablecoins.ingestion import ProviderObservation, StablecoinIngestionPipeline
from services.stablecoins.models import (
    FinalityState,
    StablecoinCapability,
    StablecoinEventType,
    SupportState,
)
from services.stablecoins.polling import StablecoinPollingScheduler
from services.stablecoins.price_feed import (
    CONFIDENCE_STALE,
    CONFIDENCE_UNAVAILABLE,
    CONFLICT_STATE,
    CONSENSUS_STATE,
    PRICE_UNAVAILABLE_STATE,
    PEG_UNKNOWN,
    StablecoinChainlinkPriceConnector,
    StablecoinPriceConflictDetector,
    StablecoinPriceObservationSink,
)
from services.stablecoins.providers import StablecoinProviderIngestionRunner
from services.stablecoins.reconciliation import (
    OnchainEvidence,
    PaymentIntentEvidence,
    ReconciliationState,
    StablecoinReconciliationService,
)
from services.stablecoins.routes import StablecoinOperatorDiagnostics
from services.stablecoins.registry import (
    PLATFORM_STABLECOIN_REGISTRY,
    PLATFORM_STABLECOIN_REGISTRY_STAGING,
    resolve_chainlink_feed_address,
    resolve_platform_registry,
)
from services.stablecoins.support import (
    StablecoinReadinessError,
    StablecoinSupportService,
    StablecoinTenantReadinessGate,
    SupportEvidence,
)

BASE_USDC = "usdc:base:mainnet:0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
BASE_DEPLOYMENT = PLATFORM_STABLECOIN_REGISTRY.deployments[BASE_USDC]

ADDR_A = "0x" + "a" * 40
ADDR_B = "0x" + "b" * 40


@pytest.fixture(autouse=True)
def reset_repos():
    reset_in_memory_stores()


# ─────────────────────────────────────────────────────────────────────────────
# Mock RPC / price servers (in-memory, deterministic — no live network)
# ─────────────────────────────────────────────────────────────────────────────


class FakeHTTPStatusError(Exception):
    """Mimics an httpx status error (carries ``response.status_code``)."""

    class _Resp:
        def __init__(self, code):
            self.status_code = code

    def __init__(self, code):
        self.response = self._Resp(code)
        super().__init__(f"HTTP {code}")


def _addr_topic(addr: str) -> str:
    return "0x" + "0" * 24 + addr[2:].rjust(40, "0")


class MockEVMRpcServer:
    def __init__(self, *, chain_id, contract):
        self._chain_id = int(chain_id)
        self.contract = contract.lower()
        self.blocks: list[dict] = []
        self._raise: dict[str, list[Exception]] = {}
        self._raise_always: dict[str, Exception] = {}
        self.calls: list[str] = []

    def raise_always(self, method, exc):
        """Persistent failure: EVERY call to ``method`` raises until cleared.

        Unlike ``raise_on`` (one-shot, consumed by a single call), a persistent
        raise survives across the preflight probe, the direct fetch, AND the
        scheduler poll — so each layer is provably exposed to the same failure.
        """
        self._raise_always[method] = exc

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
        if method in self._raise_always:
            raise self._raise_always[method]
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


class _RawResponse:
    """Carrier for a deliberately malformed RPC response (non-dict / bad shape)."""

    def __init__(self, payload):
        self.payload = payload


class MockMalformedRpcServer(MockEVMRpcServer):
    """Serves a malformed (non-dict / error-shaped) response for one method."""

    async def execute(self, chain_id, method, params=None, vm_type="evm"):
        self.calls.append(method)
        if method in self._raise_always:
            raise self._raise_always[method]
        queued = self._raise.get(method)
        if queued:
            payload = queued.pop(0)
            if isinstance(payload, _RawResponse):
                return payload.payload
            raise payload
        params = params or []
        if method == "eth_chainId":
            return {"result": hex(self._chain_id)}
        if method == "eth_blockNumber":
            return "0x"  # malformed: not a dict at all
        if method == "eth_getLogs":
            return []  # malformed: not a dict
        raise ValueError(f"unexpected method {method}")


def _word(value: int) -> str:
    return f"{value & (2**256 - 1):064x}"


def _round_data(answer, *, updated_at, round_id=10, answered_in_round=10):
    body = _word(round_id) + _word(answer) + _word(updated_at) + _word(updated_at) + _word(answered_in_round)
    return "0x" + body


class MockPriceServer:
    def __init__(self, *, decimals=8):
        self._decimals = decimals
        self._round = None
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
        if data == "0x313ce567":
            return {"result": "0x" + _word(self._decimals)}
        if data.startswith("0xfeaf"):
            return {"result": self._round if self._round is not None else "0x"}
        raise ValueError(data)


def make_evm_connector(mock, **kw):
    kw.setdefault("confirmations", 1)
    kw.setdefault("max_block_span", 100)
    return StablecoinEVMIngestionConnector(deployment=BASE_DEPLOYMENT, rpc=mock, **kw)


def make_price_connector(mock, *, provider="chainlink_price_feed", **kw):
    kw.setdefault("feed_address", "0xFEED000000000000000000000000000000000001")
    kw.setdefault("staleness_threshold_seconds", 3600)
    kw.setdefault("provider", provider)
    return StablecoinChainlinkPriceConnector(deployment=BASE_DEPLOYMENT, rpc=mock, **kw)


def _fresh_ts():
    from shared.common.common import utc_now

    return int(utc_now().timestamp())


async def _poll(scheduler, connector, tenant, execution, **kw):
    return await scheduler.poll_provider(
        tenant_id=tenant, connector=connector, source_execution_id=execution, **kw
    )


# ═══════════════════════════════════════════════════════════════════════════
# Scenario 1 — RPC timeout
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_scenario1_rpc_timeout_is_failed_never_healthy_or_empty():
    mock = MockEVMRpcServer(chain_id=8453, contract=BASE_DEPLOYMENT.contract_or_mint)
    mock.add_block()
    mock.add_block()
    # Persistent timeout on the chain-identity probe so the preflight AND the
    # poll's fetch path BOTH see the same failure (a one-shot raise would let
    # the poll proceed to a genuinely-empty healthy run).
    mock.raise_always("eth_chainId", TimeoutError("rpc read timed out"))
    connector = make_evm_connector(mock)

    # Preflight classifies the timeout and fails closed (never raises).
    preflight = await connector.preflight()
    assert preflight.ok is False
    assert preflight.status == CONNECTOR_TIMEOUT

    scheduler = StablecoinPollingScheduler()
    result = await _poll(scheduler, connector, "t-timeout", "exec-timeout")
    # Distinguishable from empty: status is 'failed', not 'empty'/'healthy'.
    assert result.status == "failed"
    assert result.rows_observed == 0
    assert any(CONNECTOR_TIMEOUT in e for e in result.errors)

    health = await StablecoinProviderHealthRepository().find_many(
        filters={"tenant_id": "t-timeout", "provider": connector.provider}, limit=10
    )
    assert health and health[0]["status"] == "failed"


# ═══════════════════════════════════════════════════════════════════════════
# Scenario 2 — RPC rate limit
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_scenario2_rate_limit_fails_closed_across_connector_price_and_poll():
    # Ingestion connector: 429 → classified, poll degrades to failed.
    mock = MockEVMRpcServer(chain_id=8453, contract=BASE_DEPLOYMENT.contract_or_mint)
    mock.add_block()
    mock.add_block()
    # Persistent 429 on the tip probe: the direct fetch AND the scheduler poll
    # both hit the rate limit (never a one-shot that lets the poll slip through).
    mock.raise_always("eth_blockNumber", FakeHTTPStatusError(429))
    connector = make_evm_connector(mock)
    with pytest.raises(StablecoinConnectorError) as ei:
        await connector.fetch_observations(tenant_id="t-rate", cursor="")
    assert ei.value.classification == CONNECTOR_RATE_LIMITED

    scheduler = StablecoinPollingScheduler()
    result = await _poll(scheduler, connector, "t-rate", "exec-rate")
    assert result.status == "failed"
    assert any("rate_limited" in e for e in result.errors)

    # Price connector: a rate-limited read is UNAVAILABLE, never 0 / never 1.
    price_mock = MockPriceServer()
    price_mock.set_raise(FakeHTTPStatusError(429))
    snapshot = await make_price_connector(price_mock).get_price_observation()
    assert snapshot.available is False
    assert snapshot.price_usd is None
    assert snapshot.peg_status == PEG_UNKNOWN
    assert snapshot.confidence == CONFIDENCE_UNAVAILABLE
    assert snapshot.reason == CONNECTOR_RATE_LIMITED


# ═══════════════════════════════════════════════════════════════════════════
# Scenario 3 — malformed RPC response
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_scenario3_malformed_rpc_response_is_bad_response_never_healthy():
    mock = MockMalformedRpcServer(chain_id=8453, contract=BASE_DEPLOYMENT.contract_or_mint)
    mock.add_block()
    mock.add_block()
    connector = make_evm_connector(mock)

    with pytest.raises(StablecoinConnectorError) as ei:
        await connector.fetch_observations(tenant_id="t-malformed", cursor="")
    assert ei.value.classification == CONNECTOR_BAD_RESPONSE

    scheduler = StablecoinPollingScheduler()
    result = await _poll(scheduler, connector, "t-malformed", "exec-malformed")
    assert result.status == "failed"
    assert any(CONNECTOR_BAD_RESPONSE in e for e in result.errors)

    # A malformed price response (empty body) is UNAVAILABLE, never a price.
    price_mock = MockPriceServer()
    price_mock.set_raw("0x")
    snapshot = await make_price_connector(price_mock).get_price_observation()
    assert snapshot.available is False
    assert snapshot.price_usd is None
    assert snapshot.reason == "empty_round_data"

    # A non-dict RPC response is classified bad_response through guarded_rpc.
    raw_mock = MockPriceServer()
    raw_mock.set_raw("not-hex-garbage")
    bad = await make_price_connector(raw_mock).get_price_observation()
    assert bad.available is False and bad.price_usd is None


# ═══════════════════════════════════════════════════════════════════════════
# Scenario 4 — chain mismatch
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_scenario4_chain_mismatch_fails_closed_everywhere():
    wrong = MockEVMRpcServer(chain_id=1, contract=BASE_DEPLOYMENT.contract_or_mint)  # mainnet, not base
    wrong.add_block()
    connector = make_evm_connector(wrong)

    preflight = await connector.preflight()
    assert preflight.ok is False and preflight.status == CONNECTOR_CHAIN_MISMATCH

    with pytest.raises(StablecoinConnectorError) as ei:
        await connector.test_connection()
    assert ei.value.classification == CONNECTOR_CHAIN_MISMATCH

    scheduler = StablecoinPollingScheduler()
    result = await _poll(scheduler, connector, "t-chain", "exec-chain")
    assert result.status == "failed"
    assert any("chain_mismatch" in e for e in result.errors)
    # Distinguishable from empty: failed, not 'empty'.
    health = await StablecoinProviderHealthRepository().find_many(
        filters={"tenant_id": "t-chain", "provider": connector.provider}, limit=10
    )
    assert health and health[0]["status"] == "failed"


# ═══════════════════════════════════════════════════════════════════════════
# Scenario 5 — reorg: orphaned rolled back, canonical re-emitted
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_scenario5_reorg_rolls_back_orphan_and_reemits_canonical():
    obs_repo = StablecoinObservationRepository()
    scheduler = StablecoinPollingScheduler()
    mock = MockEVMRpcServer(chain_id=8453, contract=BASE_DEPLOYMENT.contract_or_mint)
    mock.add_block()  # 0
    mock.add_block([(ADDR_A, ADDR_B, 111, "0xORPHAN")])  # 1
    mock.add_block()  # 2
    mock.add_block()  # 3 -> tip; block1 confirmed
    connector = make_evm_connector(mock, reorg_rewind_depth=64)

    r1 = await _poll(scheduler, connector, "t-reorg", "exec-reorg-1")
    assert r1.rows_accepted == 1
    assert any(o["transaction_hash"] == "0xORPHAN" for o in await obs_repo.find_many(filters={"tenant_id": "t-reorg"}, limit=50))

    # Reorg from block 1: replace the orphaned transfer and rewrite hashes so
    # parent-hash continuity breaks.
    mock.blocks[1]["logs"] = [{
        "address": mock.contract,
        "topics": [TRANSFER_TOPIC0, _addr_topic(ADDR_B), _addr_topic(ADDR_A)],
        "data": f"0x{222:064x}", "blockNumber": hex(1), "blockHash": "",
        "transactionHash": "0xCANON", "logIndex": hex(0),
    }]
    mock.rebuild_from(1, salt="f")
    mock.add_block()  # extend so safe head advances past reorged blocks

    r2 = await _poll(scheduler, connector, "t-reorg", "exec-reorg-2")
    rows = await obs_repo.find_many(filters={"tenant_id": "t-reorg"}, limit=50)
    orphan = [o for o in rows if o["transaction_hash"] == "0xORPHAN"]
    canonical = [o for o in rows if o["transaction_hash"] == "0xCANON"]
    # Append-only reorg rollback (program 1E): the orphaned observation is
    # DEMOTED, never deleted — its evidence survives for the audit trail.
    assert orphan, "orphaned observation must remain as evidence (append-only)"
    assert all(o.get("demoted") is True for o in orphan)
    assert all(o.get("demotion_reason") == "reorg_rollback" for o in orphan)
    # The canonical chain is re-emitted and observed (not fabricated empty).
    assert canonical and any(o.get("demoted") is not True for o in canonical)
    assert r2.status == "healthy"  # the recovery itself is healthy, not empty


# ═══════════════════════════════════════════════════════════════════════════
# Scenario 6 — conflicting price providers
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_scenario6_conflicting_price_providers_never_silently_averaged():
    mock_a = MockPriceServer()
    mock_a.set_round(1_00_000_000, updated_at=_fresh_ts())  # 1.00000000
    snap_a = await make_price_connector(mock_a, provider="chainlink_provider_a").get_price_observation()

    mock_b = MockPriceServer()
    mock_b.set_round(1_05_000_000, updated_at=_fresh_ts())  # 1.05000000 -> 500 bps apart
    snap_b = await make_price_connector(mock_b, provider="chainlink_provider_b").get_price_observation()

    detector = StablecoinPriceConflictDetector()
    verdict = detector.detect([snap_a, snap_b])
    assert verdict.state == CONFLICT_STATE
    assert "bps" in verdict.reason  # disagreement is quantified, not averaged
    assert set(verdict.providers) == {"chainlink_provider_a", "chainlink_provider_b"}

    # Providers within threshold agree -> consensus, still source-attributed.
    mock_c = MockPriceServer()
    mock_c.set_round(1_00_000_000, updated_at=_fresh_ts())
    snap_c = await make_price_connector(mock_c, provider="chainlink_provider_c").get_price_observation()
    verdict_ok = detector.detect([snap_a, snap_c])
    assert verdict_ok.state == CONSENSUS_STATE

    # One unavailable provider never fabricates a price or forces consensus.
    bad_mock = MockPriceServer()
    bad_mock.set_raise(FakeHTTPStatusError(429))
    snap_unavail = await make_price_connector(bad_mock, provider="chainlink_provider_down").get_price_observation()
    verdict_partial = detector.detect([snap_a, snap_unavail])
    assert verdict_partial.state == CONSENSUS_STATE
    assert verdict_partial.prices == (Decimal("1.00000000"), None)

    # ALL providers unavailable -> unavailable, never an invented consensus.
    assert detector.detect([snap_unavail]).state == PRICE_UNAVAILABLE_STATE


# ═══════════════════════════════════════════════════════════════════════════
# Scenario 7 — stale price is real evidence but never trusted for peg
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_scenario7_stale_price_never_assumed_on_peg():
    mock = MockPriceServer()
    mock.set_round(1_00_000_000, updated_at=_fresh_ts() - 10_000)  # older than window
    connector = make_price_connector(mock, staleness_threshold_seconds=3600)

    # Persistence seam emits the stale snapshot faithfully (value preserved,
    # peg honest-unknown) — emitting is not the same as trusting it.
    sink = StablecoinPriceObservationSink()
    connector.sink = sink
    connector.emit_enabled = True
    snapshot = await connector.get_price_observation(tenant_id="t-stale")
    assert snapshot.available is True
    assert snapshot.stale is True
    assert snapshot.price_usd == Decimal("1.00000000")  # value preserved honestly
    assert snapshot.peg_status == PEG_UNKNOWN           # never on_peg
    assert snapshot.peg_deviation_bps is None
    assert snapshot.confidence == CONFIDENCE_STALE

    stored = await sink.repo.find_many(filters={"tenant_id": "t-stale"}, limit=10)
    assert stored and stored[0]["stale"] is True
    assert stored[0]["peg_status"] == PEG_UNKNOWN
    # Re-persisting the SAME snapshot collapses instead of duplicating
    # (the sink is idempotent on snapshot identity).
    await sink.persist_snapshot(snapshot, tenant_id="t-stale")
    await sink.persist_snapshot(snapshot, tenant_id="t-stale")
    assert len(await sink.repo.find_many(filters={"tenant_id": "t-stale"}, limit=100)) == 1


# ═══════════════════════════════════════════════════════════════════════════
# Scenario 8 — unpriced token
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_scenario8_unpriced_token_is_unavailable_never_zero_or_one():
    # Non-positive feed answer is NOT a price.
    zero = MockPriceServer()
    zero.set_round(0, updated_at=_fresh_ts())
    snap = await make_price_connector(zero).get_price_observation()
    assert snap.available is False
    assert snap.price_usd is None
    assert snap.reason == "non_positive_answer"
    assert snap.price_usd != Decimal("0") and snap.price_usd != Decimal("1")

    # No feed provisioned for an environment -> '' (fail-closed, not fabricated).
    staging_sepolia = PLATFORM_STABLECOIN_REGISTRY_STAGING.deployments["usdc:ethereum:sepolia:0x1c7d4b196cb0c7b01d743fbc6116a902379c7238"]
    assert resolve_chainlink_feed_address(staging_sepolia.deployment_id, environment="staging") == ""
    # Mainnet reference seed resolves, so an operator can build the connector.
    assert resolve_chainlink_feed_address(BASE_USDC, environment="production") != ""

    # Env registry separation: staging sees the sepolia twin, mainnet registry
    # does not (distinguishable deployments, never cross-contaminated).
    assert resolve_platform_registry(environment="production") is PLATFORM_STABLECOIN_REGISTRY
    assert resolve_platform_registry(environment="staging") is PLATFORM_STABLECOIN_REGISTRY_STAGING
    assert staging_sepolia.testnet is True and staging_sepolia.issuer_verified is False


# ═══════════════════════════════════════════════════════════════════════════
# Scenario 9 — duplicate transaction
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_scenario9_duplicate_transaction_collapses_and_reconciliation_is_duplicate():
    # (a) Ingestion idempotency: the same observation replayed under a second
    # execution collapses to the same deterministic observation_id.
    obs_repo = StablecoinObservationRepository()
    runner = StablecoinProviderIngestionRunner()
    obs = ProviderObservation(
        tenant_id="t-dup", provider="stablecoin_evm_rpc", source_record_id="r1",
        source_execution_id="x1", source_manifest_id="sm1", observed_at="2026-01-01T00:00:00Z",
        chain_id="8453", network="base-mainnet", contract_or_mint=BASE_DEPLOYMENT.contract_or_mint,
        transaction_hash="0xdup", amount_atomic=1_000_000, from_address=ADDR_A, to_address=ADDR_B,
        event_type=StablecoinEventType.TRANSFER, finality_status=FinalityState.CONFIRMED,
    )
    await runner.run_execution(tenant_id="t-dup", provider=obs.provider, source_execution_id="x1",
                               source_manifest_id="sm1", observations=[obs])
    await runner.run_execution(tenant_id="t-dup", provider=obs.provider, source_execution_id="x2",
                               source_manifest_id="sm1", observations=[obs])
    stored = await obs_repo.find_many(filters={"tenant_id": "t-dup"}, limit=50)
    assert len({o["observation_id"] for o in stored}) == 1  # no duplicate rows

    # (b) Reconciliation DUPLICATE: replaying the SAME confirmed tx resolves to
    # DUPLICATE, never a second MATCHED.
    intent = PaymentIntentEvidence(
        tenant_id="t-dup", payment_intent_id="pi-9", expected_payer=ADDR_A,
        expected_recipient=ADDR_B, deployment_id=BASE_DEPLOYMENT.deployment_id,
        chain_id="8453", amount_atomic=1_000_000,
    )
    onchain = OnchainEvidence(
        transaction_hash="0xdup", payer=ADDR_A, recipient=ADDR_B,
        deployment_id=BASE_DEPLOYMENT.deployment_id, chain_id="8453",
        amount_atomic=1_000_000, finality_status=FinalityState.FINALIZED,
    )
    service = StablecoinReconciliationService()
    first = await service.reconcile(intent, onchain)
    assert first.state == ReconciliationState.MATCHED
    replay = await service.reconcile(intent, onchain)
    assert replay.state == ReconciliationState.DUPLICATE

    # (c) reconcile_batch: a provider that replays the same tx in one batch gets
    # one MATCHED + one DUPLICATE (never double-counted volume). A FRESH intent
    # so the earlier MATCHED row for pi-9 does not pre-empt the batch's first hit.
    batch_intent = PaymentIntentEvidence(
        tenant_id="t-dup", payment_intent_id="pi-9-batch", expected_payer=ADDR_A,
        expected_recipient=ADDR_B, deployment_id=BASE_DEPLOYMENT.deployment_id,
        chain_id="8453", amount_atomic=1_000_000,
    )
    batch = await service.reconcile_batch(batch_intent, [onchain, onchain])
    states = [r.state for r in batch]
    assert states.count(ReconciliationState.MATCHED) == 1
    assert states.count(ReconciliationState.DUPLICATE) == 1


# ═══════════════════════════════════════════════════════════════════════════
# Scenario 10 — restart after checkpoint
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_scenario10_restart_after_checkpoint_resumes_without_reemission():
    obs_repo = StablecoinObservationRepository()
    scheduler = StablecoinPollingScheduler()
    mock = MockEVMRpcServer(chain_id=8453, contract=BASE_DEPLOYMENT.contract_or_mint)
    mock.add_block()
    mock.add_block([(ADDR_A, ADDR_B, 100, "0xpre")])  # 1
    mock.add_block()  # 2 -> tip; block1 confirmed
    connector = make_evm_connector(mock)

    r1 = await _poll(scheduler, connector, "t-restart", "exec-restart-1")
    assert r1.status == "healthy"
    assert r1.rows_accepted == 1

    # New blocks appear while the process is "down".
    mock.add_block([(ADDR_B, ADDR_A, 200, "0xpost")])
    mock.add_block()  # advance safe head so block3 confirmed

    # Simulated restart: fresh connector + the scheduler's persisted checkpoint
    # cursor threaded back in (the durable cursor store is shared in-memory).
    restarted = make_evm_connector(mock)
    r2 = await _poll(scheduler, restarted, "t-restart", "exec-restart-2", cursor=r1.cursor)
    assert r2.status == "healthy"

    txs = {o["transaction_hash"] for o in await obs_repo.find_many(filters={"tenant_id": "t-restart"}, limit=50)}
    assert "0xpre" in txs and "0xpost" in txs
    # No re-emission: exactly the two distinct transactions exist.
    assert len(txs) == 2
    assert len(await obs_repo.find_many(filters={"tenant_id": "t-restart"}, limit=50)) == 2

    # Cursor age is exposed and non-negative after the checkpoint.
    age = await scheduler.cursor_age_seconds(tenant_id="t-restart", provider=restarted.provider)
    assert age is not None and age >= 0
    # A provider that never polled reports None (distinguishable from fresh).
    assert await scheduler.cursor_age_seconds(tenant_id="t-never", provider="nope") is None


# ═══════════════════════════════════════════════════════════════════════════
# Scenario 11 — credential rotation
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_scenario11_credential_rotation_changes_fingerprint_and_clears_cache():
    # A tenant-scoped gateway holds an ATOMIC (endpoint, key) pair.
    gateway = RPCGateway(endpoint="https://tenant-rpc.example/old", api_key="old-secret")
    fp_before = gateway.credential_fingerprint
    assert gateway.credential_scope == "tenant"
    assert fp_before != "global"

    # Prime the read cache with a result fetched under the OLD credential.
    gateway._cache["1:eth_getBalance:abc"] = {"result": "0x0"}

    # Rotation: the pair changes atomically; cache is cleared so no stale
    # response is served from the prior credential.
    fp_after = await gateway.refresh_credentials("https://tenant-rpc.example/new", "new-secret")
    assert fp_after != fp_before
    assert gateway.credential_fingerprint == fp_after
    assert gateway._cache == {}  # old-credential cache purged
    assert gateway._endpoint == "https://tenant-rpc.example/new"
    assert gateway._api_key == "new-secret"

    # Re-setting the SAME pair is a no-op (idempotent rotation) — fingerprint
    # stable, cache untouched.
    gateway._cache["1:eth_getBalance:def"] = {"result": "0x1"}
    await gateway.refresh_credentials("https://tenant-rpc.example/new", "new-secret")
    assert gateway.credential_fingerprint == fp_after
    assert gateway._cache  # unchanged

    # A global (non-tenant) gateway reports global scope, never a tenant key.
    global_gateway = RPCGateway()
    assert global_gateway.credential_scope == "global"
    assert global_gateway.credential_fingerprint == "global"

    health = await gateway.health_check()
    assert health["credential_scope"] == "tenant"
    assert health["credential_fingerprint"] == fp_after


@pytest.mark.asyncio
async def test_scenario11b_observation_blocked_until_tenant_readiness_met():
    # Explicit readiness gate fails closed with NO support assertion.
    gate = StablecoinTenantReadinessGate()
    decision = await gate.observation_ready(
        tenant_id="t-rotate", deployment_id=BASE_DEPLOYMENT.deployment_id
    )
    assert decision["ready"] is False
    assert decision["support_state"] == "missing_assertion"
    with pytest.raises(StablecoinReadinessError):
        await gate.require_observation(tenant_id="t-rotate", deployment_id=BASE_DEPLOYMENT.deployment_id)

    # Climb the support ladder REGISTERED -> CONFIGURED (the gate's threshold).
    support = StablecoinSupportService()
    await support.assert_support(SupportEvidence(
        tenant_id="t-rotate", subject_entity_id="entity-t-rotate",
        deployment_id=BASE_DEPLOYMENT.deployment_id, capability=StablecoinCapability.OBSERVATION,
        support_state=SupportState.REGISTERED, evidence_type="operator_assertion",
        evidence_reference="ev:registered",
    ))
    await support.assert_support(SupportEvidence(
        tenant_id="t-rotate", subject_entity_id="entity-t-rotate",
        deployment_id=BASE_DEPLOYMENT.deployment_id, capability=StablecoinCapability.OBSERVATION,
        support_state=SupportState.CONFIGURED, evidence_type="operator_assertion",
        evidence_reference="ev:configured",
    ))
    ready = await gate.observation_ready(tenant_id="t-rotate", deployment_id=BASE_DEPLOYMENT.deployment_id)
    assert ready["ready"] is True and ready["support_state"] == SupportState.CONFIGURED.value

    # The gate is wired into the ingestion path: an observation for a tenant
    # that is NOT ready is rejected, never ingested as healthy empty data.
    pipeline_blocked = StablecoinIngestionPipeline(readiness_gate=gate)
    obs = ProviderObservation(
        tenant_id="t-rotate-other", provider="stablecoin_evm_rpc", source_record_id="r1",
        source_execution_id="x1", source_manifest_id="sm1", observed_at="2026-01-01T00:00:00Z",
        chain_id="8453", network="base-mainnet", contract_or_mint=BASE_DEPLOYMENT.contract_or_mint,
        transaction_hash="0xblocked", amount_atomic=5, from_address=ADDR_A, to_address=ADDR_B,
        event_type=StablecoinEventType.TRANSFER, finality_status=FinalityState.CONFIRMED,
    )
    with pytest.raises(StablecoinReadinessError):
        await pipeline_blocked.ingest_provider_observation(obs)
    assert await StablecoinObservationRepository().count(filters={"tenant_id": "t-rotate-other"}) == 0

    # The gate is wired into the scheduler poll path: a tenant that is NOT yet
    # ready gets a typed denial poll, never a healthy/empty run.
    mock = MockEVMRpcServer(chain_id=8453, contract=BASE_DEPLOYMENT.contract_or_mint)
    mock.add_block()
    mock.add_block()
    scheduler = StablecoinPollingScheduler()
    result = await _poll(
        scheduler, make_evm_connector(mock), "t-rotate-notready", "exec-rotate-denied",
        readiness_gate=gate,
    )
    assert result.status == "readiness_denied"
    assert result.rows_observed == 0 and result.rows_accepted == 0
    assert result.errors  # denial reason present — distinguishable from empty


@pytest.mark.asyncio
async def test_scenario11c_entitlement_enforced_in_observation_path():
    governance = StablecoinGovernanceService()
    guard = StablecoinEntitlementGuard(governance=governance)

    # A tenant WITHOUT the observation entitlement is denied (fail-closed).
    with pytest.raises(StablecoinEntitlementError):
        await guard.require_observation(
            tenant_id="t-ent", granted_capabilities=["stablecoin_profile360"],
            deployment_id=BASE_DEPLOYMENT.deployment_id,
        )

    # Granting the entitlement allows observation (typed, auditable).
    decision = await guard.require_observation(
        tenant_id="t-ent",
        granted_capabilities=[StablecoinCapabilityEntitlement.OBSERVATION.value],
        deployment_id=BASE_DEPLOYMENT.deployment_id,
    )
    assert decision["allowed"] is True and decision["reason"] == "granted"

    # Entitlement gate wired into the scheduler: a denied tenant is a typed
    # denial poll (never healthy/empty); a granted tenant proceeds to fetch.
    mock = MockEVMRpcServer(chain_id=8453, contract=BASE_DEPLOYMENT.contract_or_mint)
    mock.add_block()
    mock.add_block()
    scheduler = StablecoinPollingScheduler()
    denied = await _poll(
        scheduler, make_evm_connector(mock), "t-ent", "exec-ent-denied",
        tenant_entitlements=["stablecoin_profile360"], entitlement_guard=guard,
    )
    assert denied.status == "entitlement_denied"
    assert denied.rows_observed == 0

    mock2 = MockEVMRpcServer(chain_id=8453, contract=BASE_DEPLOYMENT.contract_or_mint)
    mock2.add_block()
    mock2.add_block()
    mock2.add_block()  # tip so a transfer can confirm
    mock2.add_block([(ADDR_A, ADDR_B, 9, "0xent")])
    mock2.add_block()  # confirm depth
    granted = await _poll(
        scheduler, make_evm_connector(mock2), "t-ent", "exec-ent-granted",
        tenant_entitlements=[StablecoinCapabilityEntitlement.OBSERVATION.value],
        entitlement_guard=guard,
    )
    assert granted.status == "healthy"
    stored = await StablecoinObservationRepository().find_many(filters={"tenant_id": "t-ent"}, limit=50)
    assert any(o["transaction_hash"] == "0xent" for o in stored)


# ═══════════════════════════════════════════════════════════════════════════
# Scheduler idempotency + backlog + cursor age (robustness levers)
# ═══════════════════════════════════════════════════════════════════════════


class _StubFinalityVerifier:
    """Deterministic stand-in that never touches a network — a finality poll
    records its errors as a failed checkpoint without any live RPC."""

    async def verify_observation(self, *, tenant_id, observation_id, finality_threshold):
        raise RuntimeError("verifier offline (deterministic stub)")


@pytest.mark.asyncio
async def test_scheduler_backlog_and_cooldown_are_idempotent_and_visible():
    obs_repo = StablecoinObservationRepository()
    scheduler = StablecoinPollingScheduler(evm_verifier=_StubFinalityVerifier())

    # Seed a non-terminal observation (re-check backlog candidate).
    record = {
        "tenant_id": "t-backlog", "chain_id": "8453", "network": "base-mainnet",
        "deployment_id": BASE_DEPLOYMENT.deployment_id,
        "transaction_hash": "0xbacklog", "finality_status": "observed",
        "observation_id": "obs-backlog-1", "source_execution_id": "seed",
    }
    await obs_repo.insert("obs-backlog-1", record)

    backlog = await scheduler.backlog(tenant_id="t-backlog", chain_id="8453")
    assert backlog == 1
    breakdown = await scheduler.backlog_by_status(tenant_id="t-backlog", chain_id="8453")
    assert breakdown == {"observed": 1}

    # Finality poll cooldown: first run scans (and, with the stub verifier,
    # degrades to failed — still recorded); a second run inside the window
    # short-circuits (skipped) instead of re-hammering the verifier.
    first = await scheduler.poll_finality(
        tenant_id="t-backlog", chain_id="8453", verifier="evm", limit=50
    )
    assert first.backlog == 1
    second = await scheduler.poll_finality(
        tenant_id="t-backlog", chain_id="8453", verifier="evm", limit=50, cooldown_seconds=3600
    )
    assert second.skipped is True and second.skip_reason == "cooldown"

    checkpoints = await scheduler.poll_checkpoints(tenant_id="t-backlog", poll_type="finality")
    assert checkpoints  # durable audit trail present


# ═══════════════════════════════════════════════════════════════════════════
# Operator diagnostics — reconciliation / finality / cursor / provider-health /
# repair. The Kyber operator surface (``StablecoinOperatorDiagnostics``) is
# read-only plus ONE non-destructive repair (re-queue a failed poll checkpoint).
# Every endpoint keeps failure distinguishable from empty: an unready tenant,
# a never-polled provider, or a missing checkpoint is a typed signal, never a
# fabricated healthy dataset.
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_operator_diagnostics_reconciliation_tenant_and_status_filtered():
    repo = StablecoinReconciliationRepository()
    rows = [
        ("r-diag:1", "t-diag", "pi-1", ReconciliationState.MATCHED.value, "0xdiag1"),
        ("r-diag:2", "t-diag", "pi-2", ReconciliationState.DUPLICATE.value, "0xdiag2"),
        ("r-diag:3", "t-other", "pi-3", ReconciliationState.MATCHED.value, "0xdiag3"),
    ]
    for rid, tenant, pi, state, tx in rows:
        await repo.insert(rid, {
            "reconciliation_id": rid, "tenant_id": tenant, "payment_intent_id": pi,
            "state": state, "transaction_hash": tx, "evidence": {},
        })
    diag = StablecoinOperatorDiagnostics()

    scoped = await diag.reconciliation_records(tenant_id="t-diag")
    assert scoped["count"] == 2  # tenant-scoped, never cross-tenant
    assert {r["reconciliation_id"] for r in scoped["items"]} == {"r-diag:1", "r-diag:2"}

    matched = await diag.reconciliation_records(tenant_id="t-diag", status="matched")
    assert matched["count"] == 1 and matched["items"][0]["reconciliation_id"] == "r-diag:1"

    # A status with no records is a genuine empty list (count 0), never an error.
    none = await diag.reconciliation_records(tenant_id="t-diag", status="missing_onchain")
    assert none["count"] == 0 and none["items"] == []


@pytest.mark.asyncio
async def test_operator_diagnostics_finality_backlog_and_recent_polls():
    obs_repo = StablecoinObservationRepository()
    await obs_repo.insert("obs-diag-f", {
        "observation_id": "obs-diag-f", "tenant_id": "t-diag-f", "chain_id": "8453",
        "finality_status": "observed", "deployment_id": BASE_DEPLOYMENT.deployment_id,
        "transaction_hash": "0xfin", "source_execution_id": "seed",
    })
    ckpt = StablecoinPollingCheckpointRepository()
    fid = "stablecoin_poll:t-diag-f:finality:evm_finality:finality:t-diag-f:8453:evm"
    await ckpt.insert(fid, {
        "checkpoint_id": fid, "tenant_id": "t-diag-f", "poll_type": "finality",
        "provider": "evm_finality", "status": "healthy", "scanned": 1,
        "source_execution_id": f"finality:t-diag-f:8453:evm",
    })
    diag = StablecoinOperatorDiagnostics()

    # Backlog counts the non-terminal observation; breakdown attributes it.
    status = await diag.finality_status(tenant_id="t-diag-f", chain_id="8453")
    assert status["backlog"] == 1
    assert status["backlog_by_status"] == {"observed": 1}
    assert any(p["checkpoint_id"] == fid for p in status["recent_finality_polls"])

    # Tenant-less request is a typed error marker, never a healthy empty view.
    missing = await diag.finality_status(tenant_id="")
    assert missing["error"] == "tenant_id required"
    assert missing["scanned"] == 0


@pytest.mark.asyncio
async def test_operator_diagnostics_cursor_age_distinguishes_stale_from_never():
    ckpt = StablecoinPollingCheckpointRepository()
    pid = "stablecoin_poll:t-diag-c:provider:stablecoin_evm_rpc:exec-c"
    await ckpt.insert(pid, {
        "checkpoint_id": pid, "tenant_id": "t-diag-c", "poll_type": "provider",
        "provider": "stablecoin_evm_rpc", "status": "healthy", "cursor": "0x10",
        "source_execution_id": "exec-c",
        "completed_at": "2026-01-01T00:00:00Z",
    })
    diag = StablecoinOperatorDiagnostics()
    cursors = await diag.cursor_status(tenant_id="t-diag-c")
    assert "stablecoin_evm_rpc" in cursors["providers"]
    age = cursors["cursor_age_seconds"].get("stablecoin_evm_rpc")
    assert age is not None and age > 0  # stale-but-known, distinguishable

    # A tenant that never polled reports no providers (never fabricated age=0).
    fresh = await diag.cursor_status(tenant_id="t-diag-never")
    assert fresh["providers"] == [] and fresh["cursor_age_seconds"] == {}


@pytest.mark.asyncio
async def test_operator_diagnostics_provider_health_records_failure_not_empty():
    health = StablecoinProviderHealthRepository()
    await health.insert("stablecoin_provider_health:t-diag-h:stablecoin_evm_rpc:exec-h", {
        "health_id": "stablecoin_provider_health:t-diag-h:stablecoin_evm_rpc:exec-h",
        "tenant_id": "t-diag-h", "provider": "stablecoin_evm_rpc",
        "source_execution_id": "exec-h", "status": "failed", "freshness": "provider_failure",
    })
    diag = StablecoinOperatorDiagnostics()
    scoped = await diag.provider_health(tenant_id="t-diag-h")
    assert scoped["count"] == 1 and scoped["items"][0]["status"] == "failed"
    # Unknown tenant: real empty, not conflated with a failure record.
    assert await diag.provider_health(tenant_id="t-diag-none") == {"items": [], "count": 0}


@pytest.mark.asyncio
async def test_operator_diagnostics_repair_requeues_failed_never_healthy():
    ckpt = StablecoinPollingCheckpointRepository()
    diag = StablecoinOperatorDiagnostics()

    # Missing checkpoint -> typed not-found, no mutation.
    missing = await diag.repair_checkpoint("stablecoin_poll:t-diag-r:provider:x:missing")
    assert missing["repaired"] is False and missing["reason"] == "not_found"

    # A healthy checkpoint is NOT repairable (repair is only for failures).
    healthy_id = "stablecoin_poll:t-diag-r:provider:stablecoin_evm_rpc:healthy"
    await ckpt.insert(healthy_id, {
        "checkpoint_id": healthy_id, "tenant_id": "t-diag-r", "poll_type": "provider",
        "provider": "stablecoin_evm_rpc", "source_execution_id": "healthy",
        "status": "healthy",
    })
    untouched = await diag.repair_checkpoint(healthy_id)
    assert untouched["repaired"] is False and untouched["reason"] == "not_repairable"
    assert (await ckpt.find_by_id(healthy_id))["status"] == "healthy"

    # A failed poll checkpoint is re-queued for retry (non-destructive).
    failed_id = "stablecoin_poll:t-diag-r:provider:stablecoin_evm_rpc:failed"
    await ckpt.insert(failed_id, {
        "checkpoint_id": failed_id, "tenant_id": "t-diag-r", "poll_type": "provider",
        "provider": "stablecoin_evm_rpc", "source_execution_id": "failed",
        "status": "failed",
    })
    repaired = await diag.repair_checkpoint(failed_id)
    assert repaired["repaired"] is True
    assert repaired["from"] == "failed" and repaired["to"] == "queued_for_retry"
    assert (await ckpt.find_by_id(failed_id))["status"] == "queued_for_retry"

    # An entitlement-denied checkpoint is re-queued too (denials are repairable).
    denied_id = "stablecoin_poll:t-diag-r:provider:stablecoin_evm_rpc:denied"
    await ckpt.insert(denied_id, {
        "checkpoint_id": denied_id, "tenant_id": "t-diag-r", "poll_type": "provider",
        "provider": "stablecoin_evm_rpc", "source_execution_id": "denied",
        "status": "entitlement_denied",
    })
    denied_repaired = await diag.repair_checkpoint(denied_id)
    assert denied_repaired["repaired"] is True
    assert (await ckpt.find_by_id(denied_id))["status"] == "queued_for_retry"
