import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from repositories.repos import reset_in_memory_stores
from repositories.stablecoin_repos import StablecoinObservationRepository, StablecoinReconciliationRepository
from services.stablecoins.governance import (
    BenchmarkInput,
    MarketDataClass,
    StablecoinCapabilityEntitlement,
    StablecoinGovernanceService,
)
from services.stablecoins.operations import RemediationAction, RemediationRequest, StablecoinOperationsService
from services.stablecoins.release_readiness import StablecoinReleaseReadinessService


@pytest.fixture(autouse=True)
def reset_repos():
    reset_in_memory_stores()


@pytest.mark.asyncio
async def test_kyber_operations_health_lineage_and_audited_remediation_are_tenant_scoped():
    obs_repo = StablecoinObservationRepository()
    recon_repo = StablecoinReconciliationRepository()
    await obs_repo.insert("obs-1", {
        "observation_id": "obs-1",
        "tenant_id": "tenant-a",
        "source": "rpc",
        "source_record_id": "log-1",
        "evidence_id": "bronze-1",
        "finality_status": "finalized",
        "event_type": "payment",
    })
    await obs_repo.insert("obs-other", {"observation_id": "obs-other", "tenant_id": "tenant-b", "source": "rpc"})
    await recon_repo.insert("recon-1", {"tenant_id": "tenant-a", "state": "mismatched"})

    service = StablecoinOperationsService()
    health = await service.tenant_health("tenant-a")
    assert health["observation_count"] == 1
    assert health["reconciliation_failures"] == 1
    assert health["pipeline_state"] == "needs_attention"

    lineage = await service.lineage("tenant-a", "obs-1")
    assert [step["layer"] for step in lineage["lineage"]] == [
        "provider", "bronze", "silver", "classification",
        "reconciliation", "gold", "graph", "profile360", "tenant_ui",
    ]
    with pytest.raises(ValueError, match="not found for tenant"):
        await service.lineage("tenant-a", "obs-other")

    audit = await service.request_remediation(RemediationRequest(
        tenant_id="tenant-a",
        action=RemediationAction.RERUN_RECONCILIATION,
        actor_id="operator-1",
        reason="investigate mismatch",
        evidence_reference="ticket://stablecoin-1",
        target={"observation_id": "obs-1"},
    ))
    assert audit["status"] == "recorded_not_executed"
    assert audit["observation_only"] is True


@pytest.mark.asyncio
async def test_governance_enforces_capabilities_metering_and_benchmark_thresholds():
    obs_repo = StablecoinObservationRepository()
    await obs_repo.insert("obs-1", {"observation_id": "obs-1", "tenant_id": "tenant-a"})
    service = StablecoinGovernanceService()

    allowed = service.capability_allowed(["stablecoin_api"], StablecoinCapabilityEntitlement.API)
    denied = service.capability_allowed([], StablecoinCapabilityEntitlement.EXPORTS)
    assert allowed == {"capability": "stablecoin_api", "allowed": True, "reason": "granted"}
    assert denied["reason"] == "missing_capability"

    usage = await service.usage_metering("tenant-a")
    assert usage["meters"]["observations"] == 1
    assert usage["metering_does_not_alter_metric_truth"] is True

    with pytest.raises(ValueError, match="tenant_raw"):
        await service.publish_benchmark(BenchmarkInput("cohort", 10, MarketDataClass.TENANT_RAW, "volume", "100", {}))
    with pytest.raises(ValueError, match="cohort threshold"):
        await service.publish_benchmark(BenchmarkInput("cohort", 3, MarketDataClass.PLATFORM_ANONYMIZED_BENCHMARK, "volume", "100", {}))
    benchmark = await service.publish_benchmark(BenchmarkInput("cohort", 6, MarketDataClass.MODEL_ESTIMATE, "growth", "0.12", {"source": "public_onchain"}))
    assert benchmark["estimated"] is True
    assert benchmark["raw_tenant_data_included"] is False


def test_release_readiness_is_not_ga_without_staging_security_and_dr_evidence():
    readiness = StablecoinReleaseReadinessService().readiness()
    assert readiness["production_recommendation"] == "NOT_READY"
    assert readiness["ga_ready"] is False
    assert readiness["blocker_count"] > 0
