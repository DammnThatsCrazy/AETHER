"""Stablecoin PR4 governance: entitlements, metering, market safeguards."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable

from repositories.stablecoin_repos import (
    StablecoinGoldRepository,
    StablecoinMarketBenchmarkRepository,
    StablecoinObservationRepository,
    StablecoinReconciliationRepository,
    StablecoinSupportAssertionRepository,
)


class StablecoinCapabilityEntitlement(str, Enum):
    OBSERVATION = "stablecoin_observation"
    PROFILE360 = "stablecoin_profile360"
    ATTRIBUTION = "stablecoin_attribution"
    SUPPORT_INTELLIGENCE = "stablecoin_support_intelligence"
    MARKET_BENCHMARKS = "stablecoin_market_benchmarks"
    REALTIME = "stablecoin_realtime"
    ALERTS = "stablecoin_alerts"
    EXPORTS = "stablecoin_exports"
    API = "stablecoin_api"
    RISK = "stablecoin_risk"
    AGENT_OBSERVABILITY = "stablecoin_agent_observability"
    CUSTOM_ASSETS = "stablecoin_custom_assets"
    CUSTOM_CHAINS = "stablecoin_custom_chains"
    EXTENDED_RETENTION = "stablecoin_extended_retention"


class MarketDataClass(str, Enum):
    TENANT_RAW = "tenant_raw"
    TENANT_AGGREGATE = "tenant_aggregate"
    PLATFORM_ANONYMIZED_BENCHMARK = "platform_anonymized_benchmark"
    PUBLIC_ONCHAIN = "public_onchain"
    LICENSED_MARKET = "licensed_market"
    OLYMPUS_OWNED = "olympus_owned"
    MODEL_ESTIMATE = "model_estimate"
    SYNTHETIC = "synthetic"


@dataclass(frozen=True)
class BenchmarkInput:
    cohort_id: str
    tenant_count: int
    data_class: MarketDataClass
    metric_name: str
    metric_value: str
    lineage: dict[str, Any]
    estimated: bool = False


class StablecoinGovernanceService:
    def __init__(self) -> None:
        self.observations = StablecoinObservationRepository()
        self.support = StablecoinSupportAssertionRepository()
        self.reconciliation = StablecoinReconciliationRepository()
        self.gold = StablecoinGoldRepository()
        self.market = StablecoinMarketBenchmarkRepository()

    def capability_allowed(
        self,
        granted: Iterable[str],
        required: StablecoinCapabilityEntitlement,
    ) -> dict[str, Any]:
        granted_set = set(granted)
        allowed = required.value in granted_set
        return {
            "capability": required.value,
            "allowed": allowed,
            "reason": "granted" if allowed else "missing_capability",
        }

    async def usage_metering(self, tenant_id: str) -> dict[str, Any]:
        if not tenant_id:
            raise ValueError("tenant_id is required for stablecoin metering")
        observations = await self.observations.count(filters={"tenant_id": tenant_id})
        support = await self.support.count(filters={"tenant_id": tenant_id})
        reconciliation = await self.reconciliation.count(filters={"tenant_id": tenant_id})
        gold = await self.gold.count(filters={"tenant_id": tenant_id})
        return {
            "tenant_id": tenant_id,
            "meters": {
                "observations": observations,
                "transactions_normalized": observations,
                "support_assertions": support,
                "reconciliation_records": reconciliation,
                "gold_materializations": gold,
                "profile360_requests": 0,
                "alerts_evaluated": 0,
                "exports_generated": 0,
            },
            "metering_does_not_alter_metric_truth": True,
        }

    async def publish_benchmark(self, item: BenchmarkInput, *, minimum_cohort: int = 5) -> dict[str, Any]:
        if item.data_class == MarketDataClass.TENANT_RAW:
            raise ValueError("tenant_raw data cannot be published as Olympus benchmark")
        if item.data_class == MarketDataClass.PLATFORM_ANONYMIZED_BENCHMARK and item.tenant_count < minimum_cohort:
            raise ValueError("benchmark cohort threshold not met")
        benchmark_id = f"stablecoin_market:{item.cohort_id}:{item.metric_name}:{item.data_class.value}"
        record: dict[str, Any] = {
            "benchmark_id": benchmark_id,
            "cohort_id": item.cohort_id,
            "tenant_count": item.tenant_count,
            "data_class": item.data_class.value,
            "metric_name": item.metric_name,
            "metric_value": item.metric_value,
            "lineage": dict(item.lineage),
            "estimated": item.estimated or item.data_class == MarketDataClass.MODEL_ESTIMATE,
            "raw_tenant_data_included": False,
        }
        return await self.market.insert(benchmark_id, record)


class StablecoinEntitlementError(Exception):
    """A tenant lacks the capability entitlement for the observation path.

    Fail-closed: a missing entitlement is a typed denial, never an empty
    healthy result.
    """

    def __init__(self, *, tenant_id: str, capability: str, reason: str) -> None:
        self.tenant_id = tenant_id
        self.capability = capability
        self.reason = reason
        super().__init__(
            f"stablecoin entitlement denied: tenant={tenant_id} capability={capability} reason={reason}"
        )


class StablecoinEntitlementGuard:
    """Enforce ``StablecoinCapabilityEntitlement`` on observation paths.

    Composes the governance capability check with the optional tenant readiness
    gate (support-state ladder). Denial is typed and fail-closed — the caller
    records it as a blocked observation, never as healthy empty data.
    """

    def __init__(
        self,
        governance: StablecoinGovernanceService | None = None,
        readiness_gate: Any = None,
    ) -> None:
        self.governance = governance or StablecoinGovernanceService()
        self.readiness_gate = readiness_gate

    def capability_allowed(
        self,
        granted: Iterable[str],
        required: StablecoinCapabilityEntitlement = StablecoinCapabilityEntitlement.OBSERVATION,
    ) -> dict[str, Any]:
        return self.governance.capability_allowed(granted, required)

    async def require_observation(
        self,
        *,
        tenant_id: str,
        granted_capabilities: Iterable[str],
        deployment_id: str,
        capability: StablecoinCapabilityEntitlement = StablecoinCapabilityEntitlement.OBSERVATION,
    ) -> dict[str, Any]:
        """Raise on entitlement or readiness denial; else return the grant."""
        check = self.governance.capability_allowed(granted_capabilities, capability)
        if not check["allowed"]:
            raise StablecoinEntitlementError(
                tenant_id=tenant_id, capability=capability.value, reason=check["reason"]
            )
        if self.readiness_gate is not None:
            await self.readiness_gate.require_observation(
                tenant_id=tenant_id, deployment_id=deployment_id
            )
        return {
            "tenant_id": tenant_id,
            "capability": capability.value,
            "deployment_id": deployment_id,
            "allowed": True,
            "reason": "granted",
        }
