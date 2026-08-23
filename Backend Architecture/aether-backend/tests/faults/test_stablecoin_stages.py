"""Stage-boundary failures: stablecoin observation + materialization.

Pipeline: receive (validate payload) -> normalize (resolve canonical asset,
scale atomic to decimal) -> persist (idempotent insert keyed on
(tenant_id, idempotency_key)) -> publish (canonical observation event) ->
materialize (windowed flow aggregate, idempotent on (window, metric_version))
-> reconcile (finalized observation vs onchain evidence).

Boundary recovery asserted per stage:

  * receive: a malformed payload raises BEFORE anything is persisted — no row,
    no event (failure is distinguishable from healthy-empty).
  * normalize: a provisional / stale observation is persisted but never enters
    the materialized flow window (no fabricated finality).
  * persist: a DB write failure raises loudly; the retry inserts exactly once;
    a replay collapses (inserted=False) — no duplicate authoritative row.
  * publish: exactly one canonical event per inserted observation; a replay
    emits zero events — no double-publish.
  * materialize: the same window computed twice yields exactly one aggregate
    row and one event — immutable historical windows.
  * reconcile: a finalized observation whose onchain match conflicts is
    MISMATCHED, never a fabricated MATCHED.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
ADV = Path(__file__).resolve().parents[1] / "adversarial"
if str(ADV) not in sys.path:
    sys.path.insert(0, str(ADV))

import faultkit  # noqa: E402
from faultkit import (  # noqa: E402
    DB_UNAVAILABLE,
    RECONCILIATION_CONFLICT,
    STALE,
    arm,
    assert_no_duplicates,
    expect_fault,
    make_fault,
)
from repositories.stablecoin_repos import (  # noqa: E402
    FlowAggregateRepo,
    StablecoinObservationRepo,
)
from services.stablecoin.flows import FlowService  # noqa: E402
from services.stablecoin.models import (  # noqa: E402
    StablecoinDeployment,
    StablecoinFlowComputeRequest,
    StablecoinObservationIngest,
)
from services.stablecoin.registry import StablecoinRegistry  # noqa: E402
from services.stablecoin.service import StablecoinObservationService  # noqa: E402
from services.stablecoins.reconciliation import (  # noqa: E402
    OnchainEvidence,
    PaymentIntentEvidence,
    ReconciliationState,
    StablecoinReconciliationService,
)

_USDC_BASE = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
_DEPLOYMENT_ID = "usdc:base:mainnet:0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"


async def _seed_usdc_base() -> None:
    """Register the base-USDC deployment the pipeline resolves observations to.

    The x402 seed map uses ``chain_id`` keyed ``eip155:8453`` and
    ``deployment_id="usdc:eip155:8453"``; the test payload uses the platform
    display form ``deployment_id="usdc:base:mainnet:0x8335..."`` /
    ``chain_id="8453"``. Registering the display-form deployment makes
    resolution faithful to a real production registry entry so the observation
    carries ``canonical_asset_id="usdc"`` and the flow window actually counts it.
    """
    await StablecoinRegistry().register_deployment(StablecoinDeployment(
        deployment_id=_DEPLOYMENT_ID,
        canonical_asset_id="usdc",
        chain_id="8453",
        network="base-mainnet",
        token_standard="erc20",
        contract_or_mint=_USDC_BASE,
        decimals=6,
        deployment_type="canonical",
        issuer_verified=True,
        testnet=False,
    ))


def _flow_request() -> StablecoinFlowComputeRequest:
    return StablecoinFlowComputeRequest(
        canonical_asset_id="usdc", deployment_id=_DEPLOYMENT_ID,
        chain_id="8453", window_start="2026-08-09T00:00:00Z",
        window_end="2026-08-09T01:00:00Z",
    )


def _ingest_payload(**overrides) -> dict:
    base = {
        "observation_type": "transfer",
        "chain_id": "8453",
        "network": "base-mainnet",
        "transaction_hash": "0xstages",
        "contract_or_mint": _USDC_BASE,
        "amount_atomic": 1_000_000,
        "finality_status": "finalized",
        "observed_at": "2026-08-09T00:00:00Z",
    }
    base.update(overrides)
    return base


# ── receive boundary ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_receive_boundary_malformed_payload_persists_nothing():
    bad = _ingest_payload(transaction_hash=None, amount_atomic=None)  # required fields
    with pytest.raises(ValidationError):
        StablecoinObservationIngest(**bad)
    rows = await StablecoinObservationRepo().find_many({"tenant_id": "t1"}, limit=10)
    assert rows == []  # nothing crossed the receive boundary


# ── normalize / stale boundary ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_normalize_boundary_stale_finality_never_materializes():
    """A provisional observation is accepted for the record but is STALE for
    flow materialization — it must never fabricate finalized volume."""
    await _seed_usdc_base()
    service = StablecoinObservationService()
    result = await service.ingest_observation(
        "t1", StablecoinObservationIngest(**_ingest_payload(finality_status="provisional"))
    )
    assert result["inserted"] is True  # recorded, but not finalized
    # Even though the asset RESOLVED to a real canonical asset, provisional
    # finality never enters the flow window.
    assert result["deployment_resolution"] == "by_contract"

    materialized = await FlowService().compute_flow_aggregate("t1", _flow_request())
    assert materialized["gross_transfer_volume"] == "0"  # stale never counted
    assert materialized["transfer_count"] == 0
    assert materialized["inserted"] is True  # the window is materialized as empty


# ── persist boundary ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_persist_boundary_db_unavailable_raises_then_inserts_exactly_once():
    service = StablecoinObservationService()
    injector = faultkit.FaultInjector(make_fault(DB_UNAVAILABLE), mode="once")
    restore = arm(service.observations, "insert", injector)

    exc = await expect_fault(
        service.ingest_observation("t1", StablecoinObservationIngest(**_ingest_payload())),
        DB_UNAVAILABLE,
    )
    assert faultkit.classify(exc) == DB_UNAVAILABLE
    assert await StablecoinObservationRepo().find_many({"tenant_id": "t1"}, limit=10) == []

    restore()
    ok = await service.ingest_observation("t1", StablecoinObservationIngest(**_ingest_payload()))
    assert ok["inserted"] is True
    assert len(ok["emitted_events"]) == 1

    replay = await service.ingest_observation("t1", StablecoinObservationIngest(**_ingest_payload()))
    assert replay["inserted"] is False  # deterministic idempotency collapsed it
    rows = await StablecoinObservationRepo().find_many({"tenant_id": "t1"}, limit=10)
    assert len(rows) == 1
    assert_no_duplicates(rows, "observation_id", label="stablecoin observation")


# ── publish boundary ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_publish_boundary_event_emitted_once_no_double_publish_on_replay():
    service = StablecoinObservationService()
    first = await service.ingest_observation("t1", StablecoinObservationIngest(**_ingest_payload(transaction_hash="0xpub")))
    assert first["inserted"] is True and len(first["emitted_events"]) == 1

    # Replay: the same canonical event must NOT be re-published.
    second = await service.ingest_observation("t1", StablecoinObservationIngest(**_ingest_payload(transaction_hash="0xpub")))
    assert second["inserted"] is False
    assert second["emitted_events"] == []

    # A DIFFERENT observation publishes its own single event.
    third = await service.ingest_observation("t1", StablecoinObservationIngest(**_ingest_payload(transaction_hash="0xpub2")))
    assert third["inserted"] is True and len(third["emitted_events"]) == 1


# ── materialize boundary ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_materialize_boundary_immutable_window_computed_once():
    await _seed_usdc_base()
    service = StablecoinObservationService()
    first_ingest = await service.ingest_observation("t1", StablecoinObservationIngest(**_ingest_payload(transaction_hash="0xmat")))
    assert first_ingest["deployment_resolution"] == "by_contract"

    flow = FlowService()
    first = await flow.compute_flow_aggregate("t1", _flow_request())
    assert first["inserted"] is True
    assert len(first["emitted_events"]) == 1
    assert first["gross_transfer_volume"] == "1.000000"

    # Historical windows are immutable: recompute collapses, never duplicates.
    second = await flow.compute_flow_aggregate("t1", _flow_request())
    assert second["inserted"] is False
    assert second["emitted_events"] == []

    rows = await FlowAggregateRepo().find_many({"tenant_id": "t1"}, limit=10)
    assert len(rows) == 1
    assert_no_duplicates(rows, "flow_aggregate_id", label="flow aggregate")


# ── reconcile boundary ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reconcile_boundary_conflict_never_fabricates_match():
    """A finalized observation reconciled against conflicting onchain evidence
    is MISMATCHED — a conflict is distinguishable from a healthy MATCHED."""
    intent = PaymentIntentEvidence(
        tenant_id="t1", payment_intent_id="pi-1", expected_payer="0x" + "a" * 40,
        expected_recipient="0x" + "b" * 40, deployment_id="usdc:base:mainnet:0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        chain_id="8453", amount_atomic=1_000_000,
    )
    onchain = OnchainEvidence(
        transaction_hash="0xstages", payer="0x" + "e" * 40,
        recipient="0x" + "b" * 40, deployment_id="usdc:base:mainnet:0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        chain_id="8453", amount_atomic=1_000_000, finality_status="finalized",
    )
    svc = StablecoinReconciliationService()
    result = await svc.reconcile(intent, onchain)
    assert result.state == ReconciliationState.MISMATCHED
    assert "conflicts" in result.reason
