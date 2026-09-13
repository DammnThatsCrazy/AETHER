import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from services.stablecoins.aggregation import StablecoinGoldMaterializer, StablecoinMetricInput
from services.stablecoins.alerts import StablecoinAlertEvaluator, StablecoinAlertSeverity
from services.stablecoins.finality import StablecoinFinalityService
from services.stablecoins.ingestion import ProviderObservation, StablecoinIngestionPipeline
from services.stablecoins.models import (
    FinalityState,
    StablecoinCapability,
    StablecoinEventType,
    StablecoinMoney,
    SupportState,
)
from services.stablecoins.reconciliation import (
    OnchainEvidence,
    PaymentIntentEvidence,
    ReconciliationState,
    StablecoinReconciliationService,
)
from services.stablecoins.support import StablecoinSupportService, SupportEvidence
from repositories.lake import BronzeRepository, SilverRepository
from repositories.stablecoin_repos import (
    StablecoinObservationRepository,
    StablecoinReconciliationRepository,
    StablecoinSupportAssertionRepository,
)


@pytest.mark.asyncio
async def test_provider_observation_ingests_bronze_promotes_silver_and_persists_observation():
    repo = StablecoinObservationRepository()
    pipeline = StablecoinIngestionPipeline(
        bronze=BronzeRepository("stablecoin_pr2_ingest"),
        silver=SilverRepository("stablecoin_pr2_ingest"),
        observations=repo,
    )
    fact = await pipeline.ingest_provider_observation(ProviderObservation(
        tenant_id="tenant-a",
        provider="rpc",
        source_record_id="log-1",
        source_execution_id="exec-1",
        source_manifest_id="manifest-1",
        observed_at="2026-07-05T00:00:00Z",
        chain_id="8453",
        network="base-mainnet",
        contract_or_mint="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        transaction_hash="0xabc",
        log_or_instruction_index=3,
        amount_atomic=2500000,
        from_address="0xpayer",
        to_address="0xmerchant",
        event_type=StablecoinEventType.PAYMENT,
        finality_status=FinalityState.CONFIRMED,
    ))
    stored = await repo.find_by_id(fact.observation.observation_id)
    assert stored["tenant_id"] == "tenant-a"
    assert stored["deployment_id"].startswith("usdc:base")
    assert fact.money.amount_decimal == Decimal("2.500000")


@pytest.mark.asyncio
async def test_unknown_deployment_is_rejected_before_silver_or_graph():
    pipeline = StablecoinIngestionPipeline(
        bronze=BronzeRepository("stablecoin_pr2_unknown"),
        silver=SilverRepository("stablecoin_pr2_unknown"),
        observations=StablecoinObservationRepository(),
    )
    with pytest.raises(ValueError, match="unknown stablecoin deployment"):
        await pipeline.ingest_provider_observation(ProviderObservation(
            tenant_id="tenant-a",
            provider="rpc",
            source_record_id="log-1",
            source_execution_id="exec-1",
            source_manifest_id="manifest-1",
            observed_at="2026-07-05T00:00:00Z",
            chain_id="8453",
            network="base-mainnet",
            contract_or_mint="0x0000000000000000000000000000000000000000",
            transaction_hash="0xabc",
            amount_atomic=1,
        ))


@pytest.mark.asyncio
async def test_finality_reorg_marks_downstream_correction_required():
    repo = StablecoinObservationRepository()
    obs_id = "obs-finality-1"
    await repo.insert(obs_id, {"observation_id": obs_id, "tenant_id": "t", "finality_status": "finalized"})
    transition = await StablecoinFinalityService(repo).transition(
        obs_id, FinalityState.REVERTED, reason="reorg depth 4"
    )
    stored = await repo.find_by_id(obs_id)
    assert transition.correction_event == "stablecoin.transaction.reverted"
    assert stored["requires_downstream_correction"] is True
    assert stored["finality_history"][-1]["to"] == "reverted"


@pytest.mark.asyncio
async def test_reconciliation_matches_partial_pending_and_reverted_states():
    service = StablecoinReconciliationService(StablecoinReconciliationRepository())
    intent = PaymentIntentEvidence("tenant-a", "pi-1", "0xPayer", "0xMerchant", "usdc:base", "8453", 100)
    matched = await service.reconcile(
        intent, OnchainEvidence("0x1", "0xpayer", "0xmerchant", "usdc:base", "8453", 100, FinalityState.FINALIZED)
    )
    partial = await service.reconcile(
        intent, OnchainEvidence("0x2", "0xpayer", "0xmerchant", "usdc:base", "8453", 99, FinalityState.FINALIZED)
    )
    pending = await service.reconcile(
        intent, OnchainEvidence("0x3", "0xpayer", "0xmerchant", "usdc:base", "8453", 100, FinalityState.CONFIRMED)
    )
    reverted = await service.reconcile(
        intent, OnchainEvidence("0x4", "0xpayer", "0xmerchant", "usdc:base", "8453", 100, FinalityState.REVERTED)
    )
    assert matched.state == ReconciliationState.MATCHED
    assert partial.state == ReconciliationState.PARTIAL
    assert pending.state == ReconciliationState.PENDING_FINALITY
    assert reverted.state == ReconciliationState.REVERTED


def test_gold_materializer_excludes_pending_reverted_mints_and_internal_transfers():
    money = StablecoinMoney(100, 6, "usdc", "usdc:base", "8453", "base-mainnet")
    rows = [
        StablecoinMetricInput("t", "merchant", "merchant", StablecoinEventType.PAYMENT, FinalityState.FINALIZED, money, "in", "silver"),
        StablecoinMetricInput("t", "merchant", "merchant", StablecoinEventType.PAYMENT, FinalityState.PENDING, money, "in", "silver"),
        StablecoinMetricInput("t", "merchant", "merchant", StablecoinEventType.PAYMENT, FinalityState.REVERTED, money, "in", "silver"),
        StablecoinMetricInput("t", "merchant", "merchant", StablecoinEventType.MINT, FinalityState.FINALIZED, money, "in", "silver"),
        StablecoinMetricInput("t", "merchant", "merchant", StablecoinEventType.PAYMENT, FinalityState.FINALIZED, money, "in", "silver", internal_transfer=True),
    ]
    metrics = StablecoinGoldMaterializer().summarize_finalized_payment_volume(
        rows, window_start="2026-07-05T00:00:00Z", window_end="2026-07-06T00:00:00Z"
    )
    assert len(metrics) == 1
    assert metrics[0].value["amount_atomic"] == "100"


@pytest.mark.asyncio
async def test_support_state_requires_evidence_and_blocks_invalid_transition():
    service = StablecoinSupportService(StablecoinSupportAssertionRepository())
    with pytest.raises(ValueError, match="evidence_reference"):
        await service.assert_support(SupportEvidence(
            "t", "merchant", "usdc:base", StablecoinCapability.ACCEPT_PAYMENT,
            SupportState.ANNOUNCED, "public_claim", "",
        ))
    record = await service.assert_support(SupportEvidence(
        "t", "merchant", "usdc:base", StablecoinCapability.ACCEPT_PAYMENT,
        SupportState.ANNOUNCED, "public_claim", "url://claim",
    ))
    assert record["support_state"] == "announced"
    with pytest.raises(ValueError, match="invalid support transition"):
        await service.assert_support(SupportEvidence(
            "t", "merchant", "usdc:base", StablecoinCapability.ACCEPT_PAYMENT,
            SupportState.PRODUCTION_ACTIVE, "operator", "ticket://1",
        ))


def test_alert_evaluator_creates_peg_and_reconciliation_alerts_with_dedupe():
    evaluator = StablecoinAlertEvaluator()
    peg = evaluator.evaluate_peg(tenant_id="t", deployment_id="usdc:base", peg_deviation_bps=Decimal("125"))
    assert peg is not None
    assert peg.severity == StablecoinAlertSeverity.CRITICAL
    assert peg.dedupe_key == "t:peg:usdc:base"
    assert evaluator.evaluate_peg(tenant_id="t", deployment_id="usdc:base", peg_deviation_bps=Decimal("10")) is None
    recon = evaluator.evaluate_reconciliation(tenant_id="t", payment_intent_id="pi-1", state="mismatched")
    assert recon is not None
    assert recon.dedupe_key == "t:reconciliation:pi-1:mismatched"
