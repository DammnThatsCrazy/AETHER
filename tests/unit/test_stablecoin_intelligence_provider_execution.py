import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Backend Architecture" / "aether-backend"))

from repositories.lake import BronzeRepository, SilverRepository
from repositories.repos import reset_in_memory_stores
from repositories.stablecoin_repos import (
    StablecoinIngestionCheckpointRepository,
    StablecoinObservationRepository,
    StablecoinProviderHealthRepository,
    StablecoinRemediationAuditRepository,
)
from services.stablecoins.ingestion import ProviderObservation, StablecoinIngestionPipeline
from services.stablecoins.models import FinalityState, StablecoinEventType
from services.stablecoins.providers import StablecoinProviderIngestionRunner


@pytest.fixture(autouse=True)
def reset_repos():
    reset_in_memory_stores()


def _obs(record_id: str = "log-1", tenant_id: str = "tenant-a", contract: str = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913") -> ProviderObservation:
    return ProviderObservation(
        tenant_id=tenant_id,
        provider="rpc",
        source_record_id=record_id,
        source_execution_id="exec-1",
        source_manifest_id="manifest-1",
        observed_at="2026-07-05T00:00:00Z",
        chain_id="8453",
        network="base-mainnet",
        contract_or_mint=contract,
        transaction_hash=f"0x{record_id}",
        log_or_instruction_index=1,
        amount_atomic=100,
        from_address="0xpayer",
        to_address="0xmerchant",
        event_type=StablecoinEventType.PAYMENT,
        finality_status=FinalityState.CONFIRMED,
    )


@pytest.mark.asyncio
async def test_provider_execution_records_health_checkpoint_and_ingests_only_valid_rows():
    bronze = BronzeRepository("stablecoin")
    silver = SilverRepository("stablecoin")
    observations = StablecoinObservationRepository()
    runner = StablecoinProviderIngestionRunner(
        pipeline=StablecoinIngestionPipeline(bronze=bronze, silver=silver, observations=observations),
        health=StablecoinProviderHealthRepository(),
        checkpoints=StablecoinIngestionCheckpointRepository(),
        observations=observations,
        bronze=bronze,
        silver=silver,
    )

    report = await runner.run_execution(
        tenant_id="tenant-a",
        provider="rpc",
        source_execution_id="exec-1",
        source_manifest_id="manifest-1",
        observations=[_obs(), _obs("bad", contract="0x0000000000000000000000000000000000000000")],
        rollback_tag="backfill-1",
    )

    health = await StablecoinProviderHealthRepository().find_by_id("stablecoin_provider_health:tenant-a:rpc:exec-1")
    checkpoint = await StablecoinIngestionCheckpointRepository().find_by_id("stablecoin_checkpoint:tenant-a:rpc:exec-1")
    stored = await observations.find_many(filters={"tenant_id": "tenant-a", "source_execution_id": "exec-1"})

    assert report.rows_observed == 2
    assert report.rows_accepted == 1
    assert report.rows_rejected == 1
    assert report.rejected[0]["reason"] == "unknown_deployment"
    assert health["status"] == "degraded"
    assert checkpoint["rows_accepted"] == 1
    assert len(stored) == 1


@pytest.mark.asyncio
async def test_dry_run_does_not_write_bronze_silver_or_health():
    runner = StablecoinProviderIngestionRunner()

    report = await runner.run_execution(
        tenant_id="tenant-a",
        provider="rpc",
        source_execution_id="exec-1",
        source_manifest_id="manifest-1",
        observations=[_obs()],
        dry_run=True,
    )

    assert report.rows_accepted == 1
    assert await StablecoinObservationRepository().count(filters={"tenant_id": "tenant-a"}) == 0
    assert await StablecoinProviderHealthRepository().count(filters={"tenant_id": "tenant-a"}) == 0
    assert await StablecoinIngestionCheckpointRepository().count(filters={"tenant_id": "tenant-a"}) == 0


@pytest.mark.asyncio
async def test_provider_failure_is_explicit_not_healthy_empty_dataset():
    runner = StablecoinProviderIngestionRunner()

    health = await runner.record_provider_failure(
        tenant_id="tenant-a",
        provider="rpc",
        source_execution_id="exec-fail",
        source_manifest_id="manifest-1",
        error="timeout",
    )

    assert health["status"] == "failed"
    assert health["rows_observed"] == 0
    assert health["freshness"] == "provider_failure"


@pytest.mark.asyncio
async def test_rollback_execution_is_tenant_and_execution_scoped():
    bronze = BronzeRepository("stablecoin")
    silver = SilverRepository("stablecoin")
    observations = StablecoinObservationRepository()
    checkpoints = StablecoinIngestionCheckpointRepository()
    remediation = StablecoinRemediationAuditRepository()
    runner = StablecoinProviderIngestionRunner(
        pipeline=StablecoinIngestionPipeline(bronze=bronze, silver=silver, observations=observations),
        observations=observations,
        bronze=bronze,
        silver=silver,
        checkpoints=checkpoints,
        remediation=remediation,
    )
    await runner.run_execution(
        tenant_id="tenant-a",
        provider="rpc",
        source_execution_id="exec-1",
        source_manifest_id="manifest-1",
        observations=[_obs()],
    )

    result = await runner.rollback_execution(tenant_id="tenant-a", provider="rpc", source_execution_id="exec-1")

    # Rollback is append-only: rows are DEMOTED, never destroyed. The legacy
    # deleted_* keys remain 0 for caller compatibility.
    assert result["deleted_observations"] == 0
    assert result["deleted_bronze"] == 0
    assert result["deleted_silver"] == 0
    assert result["demoted_observations"] == 1
    assert result["demoted_bronze"] == 1
    assert result["demoted_silver"] == 1
    # Evidence survives the reorg for the audit trail — marked demoted, not gone.
    surviving = await observations.find_many(filters={"tenant_id": "tenant-a", "source_execution_id": "exec-1"})
    assert len(surviving) == 1
    assert surviving[0]["demoted"] is True
    assert surviving[0]["demotion_reason"] == "reorg_rollback"
    # The execution checkpoint is marked rolled_back.
    checkpoint = await checkpoints.find_by_id("stablecoin_checkpoint:tenant-a:rpc:exec-1")
    assert checkpoint["status"] == "rolled_back"
    # A durable remediation-audit entry records the demotion.
    audit = await remediation.find_many(filters={"tenant_id": "tenant-a", "source_execution_id": "exec-1"})
    assert len(audit) == 1
    assert audit[0]["action"] == "rollback_demotion"
    assert audit[0]["demoted_observations"] == 1
