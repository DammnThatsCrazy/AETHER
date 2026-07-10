"""Stablecoin provider execution, checkpoint, and rollback helpers.

This module is the first operational layer above the PR2 ingestion primitives. It
still does not fetch from external networks directly; configured connectors pass
observed rows into the runner, which records tenant-scoped health/checkpoint
state and then uses the canonical Bronze -> Silver -> observation pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from repositories.stablecoin_repos import (
    StablecoinIngestionCheckpointRepository,
    StablecoinObservationRepository,
    StablecoinProviderHealthRepository,
)
from repositories.lake import BronzeRepository, SilverRepository
from shared.common.common import utc_now

from .ingestion import ProviderObservation, StablecoinIngestionPipeline
from .registry import PLATFORM_STABLECOIN_REGISTRY, StablecoinDeploymentRegistry


@dataclass(frozen=True)
class StablecoinProviderExecutionReport:
    tenant_id: str
    provider: str
    source_execution_id: str
    source_manifest_id: str
    dry_run: bool
    rows_observed: int
    rows_accepted: int
    rows_rejected: int
    rejected: list[dict[str, Any]] = field(default_factory=list)
    checkpoint_id: str = ""
    health_status: str = "unknown"
    rollback_tag: str = ""


class StablecoinProviderIngestionRunner:
    """Run one tenant-scoped provider execution through stablecoin ingestion.

    The runner makes repeated provider executions first-class by requiring a
    source execution ID and writing checkpoint/health records keyed by tenant,
    provider, and execution. Provider failures are explicit health records; they
    are never represented as healthy empty datasets.
    """

    def __init__(
        self,
        *,
        pipeline: StablecoinIngestionPipeline | None = None,
        health: StablecoinProviderHealthRepository | None = None,
        checkpoints: StablecoinIngestionCheckpointRepository | None = None,
        observations: StablecoinObservationRepository | None = None,
        bronze: BronzeRepository | None = None,
        silver: SilverRepository | None = None,
        registry: StablecoinDeploymentRegistry | None = None,
    ) -> None:
        self.pipeline = pipeline or StablecoinIngestionPipeline()
        self.health = health or StablecoinProviderHealthRepository()
        self.checkpoints = checkpoints or StablecoinIngestionCheckpointRepository()
        self.observations = observations or StablecoinObservationRepository()
        self.bronze = bronze or BronzeRepository("stablecoin")
        self.silver = silver or SilverRepository("stablecoin")
        self.registry = registry or PLATFORM_STABLECOIN_REGISTRY

    async def run_execution(
        self,
        *,
        tenant_id: str,
        provider: str,
        source_execution_id: str,
        source_manifest_id: str,
        observations: Iterable[ProviderObservation],
        dry_run: bool = False,
        rollback_tag: str = "",
    ) -> StablecoinProviderExecutionReport:
        if not tenant_id:
            raise ValueError("tenant_id is required for stablecoin provider execution")
        if not source_execution_id:
            raise ValueError("source_execution_id is required for stablecoin provider execution")
        rows = list(observations)
        rejected: list[dict[str, Any]] = []
        accepted = 0
        for row in rows:
            if row.tenant_id != tenant_id:
                rejected.append({"source_record_id": row.source_record_id, "reason": "tenant_mismatch"})
                continue
            deployment = self.registry.resolve(chain_id=row.chain_id, network=row.network, contract_or_mint=row.contract_or_mint)
            if deployment is None:
                rejected.append({"source_record_id": row.source_record_id, "reason": "unknown_deployment"})
                continue
            if dry_run:
                accepted += 1
                continue
            try:
                await self.pipeline.ingest_provider_observation(row)
                accepted += 1
            except Exception as exc:  # provider rows are isolated; execution health records the rejection
                rejected.append({"source_record_id": row.source_record_id, "reason": type(exc).__name__, "detail": str(exc)})

        status = "healthy" if rows and not rejected else "degraded" if rows else "empty"
        if rejected and accepted == 0:
            status = "failed"
        checkpoint_id = ""
        if not dry_run:
            checkpoint_id = await self._record_checkpoint(
                tenant_id=tenant_id,
                provider=provider,
                source_execution_id=source_execution_id,
                source_manifest_id=source_manifest_id,
                rows_observed=len(rows),
                rows_accepted=accepted,
                rows_rejected=len(rejected),
                status=status,
                rollback_tag=rollback_tag,
            )
            await self._record_health(
                tenant_id=tenant_id,
                provider=provider,
                source_execution_id=source_execution_id,
                source_manifest_id=source_manifest_id,
                rows_observed=len(rows),
                rows_accepted=accepted,
                rows_rejected=len(rejected),
                status=status,
                rejected=rejected,
            )
        return StablecoinProviderExecutionReport(
            tenant_id=tenant_id,
            provider=provider,
            source_execution_id=source_execution_id,
            source_manifest_id=source_manifest_id,
            dry_run=dry_run,
            rows_observed=len(rows),
            rows_accepted=accepted,
            rows_rejected=len(rejected),
            rejected=rejected,
            checkpoint_id=checkpoint_id,
            health_status=status,
            rollback_tag=rollback_tag,
        )

    async def record_provider_failure(
        self,
        *,
        tenant_id: str,
        provider: str,
        source_execution_id: str,
        source_manifest_id: str,
        error: str,
    ) -> dict[str, Any]:
        if not tenant_id:
            raise ValueError("tenant_id is required for provider failure health")
        now = utc_now().isoformat()
        record_id = f"stablecoin_provider_health:{tenant_id}:{provider}:{source_execution_id}"
        record = {
            "health_id": record_id,
            "tenant_id": tenant_id,
            "provider": provider,
            "source_execution_id": source_execution_id,
            "source_manifest_id": source_manifest_id,
            "configured_state": "configured",
            "status": "failed",
            "last_failure_at": now,
            "freshness": "provider_failure",
            "rows_observed": 0,
            "rows_accepted": 0,
            "rows_rejected": 0,
            "errors": [{"at": now, "error": error}],
        }
        existing = await self.health.find_by_id(record_id)
        return await self.health.update(record_id, {**existing, **record}) if existing else await self.health.insert(record_id, record)

    async def rollback_execution(self, *, tenant_id: str, provider: str, source_execution_id: str) -> dict[str, Any]:
        if not tenant_id:
            raise ValueError("tenant_id is required for stablecoin rollback")
        source_tag = f"tenant:{tenant_id}:stablecoin:{provider}"
        deleted_observations = 0
        for row in await self.observations.find_many(filters={"tenant_id": tenant_id, "source_execution_id": source_execution_id}, limit=10000):
            if await self.observations.delete(row["id"]):
                deleted_observations += 1
        deleted_silver = 0
        for row in await self.silver.find_many(filters={"tenant_id": tenant_id, "source_tag": source_tag, "source_execution_id": source_execution_id}, limit=10000):
            if str(row.get("source", "")) == provider:
                if await self.silver.delete(row["id"]):
                    deleted_silver += 1
        deleted_bronze = 0
        for row in await self.bronze.find_many(filters={"tenant_id": tenant_id, "source_tag": source_tag}, limit=10000):
            if str(row.get("provider_record_id", "")).startswith(f"{source_execution_id}:"):
                if await self.bronze.delete(row["id"]):
                    deleted_bronze += 1
        checkpoint_id = f"stablecoin_checkpoint:{tenant_id}:{provider}:{source_execution_id}"
        checkpoint = await self.checkpoints.find_by_id(checkpoint_id)
        if checkpoint:
            await self.checkpoints.update(checkpoint_id, {**checkpoint, "status": "rolled_back", "rolled_back_at": utc_now().isoformat()})
        return {
            "tenant_id": tenant_id,
            "provider": provider,
            "source_execution_id": source_execution_id,
            "deleted_bronze": deleted_bronze,
            "deleted_silver": deleted_silver,
            "deleted_observations": deleted_observations,
        }

    async def _record_checkpoint(self, **data: Any) -> str:
        checkpoint_id = f"stablecoin_checkpoint:{data['tenant_id']}:{data['provider']}:{data['source_execution_id']}"
        record = {"checkpoint_id": checkpoint_id, **data, "updated_at": utc_now().isoformat()}
        existing = await self.checkpoints.find_by_id(checkpoint_id)
        if existing:
            await self.checkpoints.update(checkpoint_id, {**existing, **record})
        else:
            await self.checkpoints.insert(checkpoint_id, record)
        return checkpoint_id

    async def _record_health(self, **data: Any) -> None:
        health_id = f"stablecoin_provider_health:{data['tenant_id']}:{data['provider']}:{data['source_execution_id']}"
        now = utc_now().isoformat()
        record = {
            "health_id": health_id,
            **data,
            "configured_state": "configured",
            "last_success_at": now if data["status"] in {"healthy", "degraded", "empty"} else "",
            "last_failure_at": now if data["status"] == "failed" else "",
            "freshness": "current_execution",
            "rate_limit_state": "unknown",
            "data_rights_state": "approved",
            "tenant_impact": [data["tenant_id"]],
            "updated_at": now,
        }
        existing = await self.health.find_by_id(health_id)
        if existing:
            await self.health.update(health_id, {**existing, **record})
        else:
            await self.health.insert(health_id, record)
