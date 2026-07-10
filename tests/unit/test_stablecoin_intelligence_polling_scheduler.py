import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Backend Architecture" / "aether-backend"))

from repositories.lake import BronzeRepository, SilverRepository
from repositories.repos import reset_in_memory_stores
from repositories.stablecoin_repos import (
    StablecoinObservationRepository,
    StablecoinPollingCheckpointRepository,
    StablecoinProviderHealthRepository,
)
from services.stablecoins.ingestion import ProviderObservation, StablecoinIngestionPipeline
from services.stablecoins.models import FinalityState, StablecoinEventType
from services.stablecoins.polling import StablecoinPollingScheduler
from services.stablecoins.providers import StablecoinProviderIngestionRunner


@pytest.fixture(autouse=True)
def reset_repos():
    reset_in_memory_stores()


def _obs(record_id="poll-1", tenant_id="tenant-a"):
    return ProviderObservation(
        tenant_id=tenant_id,
        provider="rpc",
        source_record_id=record_id,
        source_execution_id="exec-poll-1",
        source_manifest_id="manifest-poll-1",
        observed_at="2026-07-06T00:00:00Z",
        chain_id="8453",
        network="base-mainnet",
        contract_or_mint="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        transaction_hash=f"0x{record_id}",
        log_or_instruction_index=1,
        amount_atomic=100,
        from_address="0xpayer",
        to_address="0xmerchant",
        event_type=StablecoinEventType.PAYMENT,
        finality_status=FinalityState.CONFIRMED,
    )


class FakeConnector:
    provider = "rpc"
    source_manifest_id = "manifest-poll-1"

    def __init__(self, rows=None, error=None):
        self.rows = list(rows or [])
        self.error = error
        self.calls = []

    async def fetch_observations(self, *, tenant_id: str, cursor: str = "", limit: int = 100):
        self.calls.append({"tenant_id": tenant_id, "cursor": cursor, "limit": limit})
        if self.error:
            raise RuntimeError(self.error)
        return self.rows[:limit], "next-cursor"


class FakeVerifier:
    def __init__(self, repo, target=FinalityState.FINALIZED):
        self.repo = repo
        self.target = target
        self.calls = []

    async def verify_observation(self, *, tenant_id, observation_id, finality_threshold=12, finality_threshold_slots=None):
        self.calls.append((tenant_id, observation_id, finality_threshold, finality_threshold_slots))
        record = await self.repo.find_by_id(observation_id)
        before = record["finality_status"]
        record["finality_status"] = self.target.value
        await self.repo.update(observation_id, record)

        class Result:
            finality_status = self.target
            warnings = ()
            finality_transitions = (object(),) if before != self.target.value else ()

        return Result()


@pytest.mark.asyncio
async def test_provider_poll_writes_checkpoint_and_runs_ingestion_pipeline():
    bronze = BronzeRepository("stablecoin")
    silver = SilverRepository("stablecoin")
    observations = StablecoinObservationRepository()
    runner = StablecoinProviderIngestionRunner(
        pipeline=StablecoinIngestionPipeline(bronze=bronze, silver=silver, observations=observations),
        observations=observations,
        bronze=bronze,
        silver=silver,
    )
    scheduler = StablecoinPollingScheduler(runner=runner, observations=observations)

    result = await scheduler.poll_provider(
        tenant_id="tenant-a",
        connector=FakeConnector([_obs()]),
        source_execution_id="exec-poll-1",
        cursor="cursor-0",
    )

    checkpoint = await StablecoinPollingCheckpointRepository().find_by_id(
        "stablecoin_poll:tenant-a:provider:rpc:exec-poll-1"
    )
    assert result.rows_observed == 1
    assert result.rows_accepted == 1
    assert result.status == "healthy"
    assert result.cursor == "next-cursor"
    assert checkpoint["cursor"] == "next-cursor"
    assert await observations.count(filters={"tenant_id": "tenant-a"}) == 1


@pytest.mark.asyncio
async def test_provider_poll_records_failure_instead_of_healthy_empty_dataset():
    scheduler = StablecoinPollingScheduler()

    result = await scheduler.poll_provider(
        tenant_id="tenant-a",
        connector=FakeConnector(error="provider timeout"),
        source_execution_id="exec-fail",
    )

    health = await StablecoinProviderHealthRepository().find_by_id("stablecoin_provider_health:tenant-a:rpc:exec-fail")
    checkpoint = await StablecoinPollingCheckpointRepository().find_by_id(
        "stablecoin_poll:tenant-a:provider:rpc:exec-fail"
    )
    assert result.status == "failed"
    assert result.errors == ("provider timeout",)
    assert health["status"] == "failed"
    assert checkpoint["status"] == "failed"


@pytest.mark.asyncio
async def test_finality_poll_is_tenant_scoped_and_only_scans_recheckable_states():
    repo = StablecoinObservationRepository()
    pending = await repo.upsert_observation(
        {
            "tenant_id": "tenant-a",
            "schema_version": "stablecoin.observation.v1",
            "source": "rpc",
            "source_record_id": "pending",
            "source_execution_id": "exec-1",
            "observed_at": "2026-07-06T00:00:00Z",
            "chain_id": "8453",
            "network": "base-mainnet",
            "transaction_hash": "0xpending",
            "log_or_instruction_index": 1,
            "finality_status": FinalityState.PENDING.value,
            "event_type": StablecoinEventType.PAYMENT.value,
            "deployment_id": "usdc-base-mainnet-native",
            "canonical_asset_id": "usdc",
            "amount_atomic": 100,
        }
    )
    tenant_b = dict(pending)
    for key in ("id", "observation_id", "created_at", "updated_at"):
        tenant_b.pop(key, None)
    await repo.upsert_observation(
        {
            **tenant_b,
            "tenant_id": "tenant-b",
            "source_record_id": "other-tenant",
            "transaction_hash": "0xother",
            "finality_status": FinalityState.PENDING.value,
        }
    )
    already_final = dict(pending)
    for key in ("id", "observation_id", "created_at", "updated_at"):
        already_final.pop(key, None)
    await repo.upsert_observation(
        {
            **already_final,
            "source_record_id": "already-final",
            "transaction_hash": "0xfinal",
            "finality_status": FinalityState.FINALIZED.value,
        }
    )
    verifier = FakeVerifier(repo)
    scheduler = StablecoinPollingScheduler(observations=repo, evm_verifier=verifier)

    result = await scheduler.poll_finality(tenant_id="tenant-a", chain_id="8453", verifier="evm", limit=10)

    checkpoint = await StablecoinPollingCheckpointRepository().find_by_id(
        "stablecoin_poll:tenant-a:finality:evm_finality:finality:tenant-a:8453:evm"
    )
    assert result.scanned == 1
    assert result.updated == 1
    assert verifier.calls[0][0] == "tenant-a"
    assert checkpoint["rows_observed"] == 1
    assert checkpoint["rows_accepted"] == 1


@pytest.mark.asyncio
async def test_finality_poll_records_verification_errors_without_cross_tenant_leakage():
    repo = StablecoinObservationRepository()
    await repo.upsert_observation(
        {
            "tenant_id": "tenant-a",
            "schema_version": "stablecoin.observation.v1",
            "source": "rpc",
            "source_record_id": "bad",
            "source_execution_id": "exec-1",
            "observed_at": "2026-07-06T00:00:00Z",
            "chain_id": "8453",
            "network": "base-mainnet",
            "transaction_hash": "0xbad",
            "log_or_instruction_index": 1,
            "finality_status": FinalityState.PENDING.value,
            "event_type": StablecoinEventType.PAYMENT.value,
            "deployment_id": "usdc-base-mainnet-native",
            "canonical_asset_id": "usdc",
            "amount_atomic": 100,
        }
    )

    class BrokenVerifier:
        async def verify_observation(self, **kwargs):
            raise ValueError("rpc unavailable")

    scheduler = StablecoinPollingScheduler(observations=repo, evm_verifier=BrokenVerifier())

    result = await scheduler.poll_finality(tenant_id="tenant-a", chain_id="8453", verifier="evm")

    assert result.scanned == 1
    assert result.updated == 0
    assert result.errors[0]["error"] == "rpc unavailable"
    assert result.errors[0]["observation_id"]
