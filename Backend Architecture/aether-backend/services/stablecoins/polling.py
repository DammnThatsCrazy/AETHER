"""Stablecoin provider and finality polling orchestration.

The scheduler in this module is deliberately connector-neutral and
observation-first: it invokes configured read-only provider connectors, records
provider health/checkpoints through ``StablecoinProviderIngestionRunner``, and
re-checks already stored observations through EVM/Solana verifiers. It does not
sign, submit, route, or simulate transactions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from repositories.stablecoin_repos import (
    StablecoinObservationRepository,
    StablecoinPollingCheckpointRepository,
)
from shared.common.common import utc_now

from .ingestion import ProviderObservation
from .models import FinalityState
from .providers import StablecoinProviderExecutionReport, StablecoinProviderIngestionRunner
from .rpc_observer import StablecoinEVMReceiptVerifier, StablecoinRPCVerificationResult
from .solana_observer import StablecoinSolanaTransactionVerifier, StablecoinSolanaVerificationResult


class StablecoinProviderConnector(Protocol):
    """Read-only connector contract used by the polling scheduler."""

    provider: str
    source_manifest_id: str

    async def fetch_observations(self, *, tenant_id: str, cursor: str = "", limit: int = 100) -> tuple[list[ProviderObservation], str]:
        """Return connector observations and the next cursor.

        Implementations must not write directly to Bronze, Silver, Gold, graph,
        or Profile360 state. The scheduler owns persistence through the runner.
        """


@dataclass(frozen=True)
class StablecoinProviderPollResult:
    tenant_id: str
    provider: str
    source_execution_id: str
    rows_observed: int
    rows_accepted: int
    rows_rejected: int
    status: str
    cursor: str = ""
    checkpoint_id: str = ""
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class StablecoinFinalityPollResult:
    tenant_id: str
    chain_id: str
    verifier: str
    scanned: int
    updated: int
    warnings: tuple[str, ...] = ()
    errors: tuple[dict[str, str], ...] = field(default_factory=tuple)
    checkpoint_id: str = ""


class StablecoinPollingScheduler:
    """Run deterministic provider and finality polling units of work.

    The scheduler records a durable checkpoint for every provider/finality poll
    so workers can be paused, resumed, retried, and audited by tenant/provider.
    """

    FINALITY_RECHECK_STATES = {
        FinalityState.OBSERVED.value,
        FinalityState.PENDING.value,
        FinalityState.CONFIRMED.value,
        FinalityState.DISPUTED.value,
        FinalityState.UNKNOWN.value,
    }

    def __init__(
        self,
        *,
        runner: StablecoinProviderIngestionRunner | None = None,
        observations: StablecoinObservationRepository | None = None,
        checkpoints: StablecoinPollingCheckpointRepository | None = None,
        evm_verifier: StablecoinEVMReceiptVerifier | None = None,
        solana_verifier: StablecoinSolanaTransactionVerifier | None = None,
    ) -> None:
        self.runner = runner or StablecoinProviderIngestionRunner()
        self.observations = observations or StablecoinObservationRepository()
        self.checkpoints = checkpoints or StablecoinPollingCheckpointRepository()
        self.evm_verifier = evm_verifier or StablecoinEVMReceiptVerifier(observations=self.observations)
        self.solana_verifier = solana_verifier or StablecoinSolanaTransactionVerifier(observations=self.observations)

    async def poll_provider(
        self,
        *,
        tenant_id: str,
        connector: StablecoinProviderConnector,
        source_execution_id: str,
        limit: int = 100,
        cursor: str = "",
        dry_run: bool = False,
    ) -> StablecoinProviderPollResult:
        if not tenant_id:
            raise ValueError("tenant_id is required for stablecoin provider polling")
        if not source_execution_id:
            raise ValueError("source_execution_id is required for stablecoin provider polling")
        if limit < 1:
            raise ValueError("limit must be positive")

        started_at = utc_now().isoformat()
        try:
            rows, next_cursor = await connector.fetch_observations(tenant_id=tenant_id, cursor=cursor, limit=limit)
            report = await self.runner.run_execution(
                tenant_id=tenant_id,
                provider=connector.provider,
                source_execution_id=source_execution_id,
                source_manifest_id=connector.source_manifest_id,
                observations=rows,
                dry_run=dry_run,
                rollback_tag=f"poll:{source_execution_id}",
            )
            checkpoint_id = await self._record_poll_checkpoint(
                tenant_id=tenant_id,
                poll_type="provider",
                provider=connector.provider,
                source_execution_id=source_execution_id,
                status=report.health_status,
                cursor=next_cursor,
                started_at=started_at,
                rows_observed=report.rows_observed,
                rows_accepted=report.rows_accepted,
                rows_rejected=report.rows_rejected,
                dry_run=dry_run,
            )
            return StablecoinProviderPollResult(
                tenant_id=tenant_id,
                provider=connector.provider,
                source_execution_id=source_execution_id,
                rows_observed=report.rows_observed,
                rows_accepted=report.rows_accepted,
                rows_rejected=report.rows_rejected,
                status=report.health_status,
                cursor=next_cursor,
                checkpoint_id=checkpoint_id,
            )
        except Exception as exc:
            await self.runner.record_provider_failure(
                tenant_id=tenant_id,
                provider=connector.provider,
                source_execution_id=source_execution_id,
                source_manifest_id=connector.source_manifest_id,
                error=str(exc),
            )
            checkpoint_id = await self._record_poll_checkpoint(
                tenant_id=tenant_id,
                poll_type="provider",
                provider=connector.provider,
                source_execution_id=source_execution_id,
                status="failed",
                cursor=cursor,
                started_at=started_at,
                rows_observed=0,
                rows_accepted=0,
                rows_rejected=0,
                dry_run=dry_run,
                errors=[str(exc)],
            )
            return StablecoinProviderPollResult(
                tenant_id=tenant_id,
                provider=connector.provider,
                source_execution_id=source_execution_id,
                rows_observed=0,
                rows_accepted=0,
                rows_rejected=0,
                status="failed",
                cursor=cursor,
                checkpoint_id=checkpoint_id,
                errors=(str(exc),),
            )

    async def poll_finality(
        self,
        *,
        tenant_id: str,
        chain_id: str,
        verifier: str,
        limit: int = 100,
        finality_threshold: int = 12,
    ) -> StablecoinFinalityPollResult:
        if not tenant_id:
            raise ValueError("tenant_id is required for stablecoin finality polling")
        if not chain_id:
            raise ValueError("chain_id is required for stablecoin finality polling")
        if limit < 1:
            raise ValueError("limit must be positive")
        if verifier not in {"evm", "solana"}:
            raise ValueError("verifier must be 'evm' or 'solana'")

        candidates = [
            row
            for row in await self.observations.find_many(filters={"tenant_id": tenant_id, "chain_id": chain_id}, limit=limit)
            if row.get("finality_status") in self.FINALITY_RECHECK_STATES
        ][:limit]
        updated = 0
        warnings: list[str] = []
        errors: list[dict[str, str]] = []
        for row in candidates:
            observation_id = str(row.get("observation_id") or row.get("id"))
            try:
                before = row.get("finality_status")
                result = await self._verify(verifier, tenant_id, observation_id, finality_threshold)
                warnings.extend(result.warnings)
                if result.finality_status.value != before or result.finality_transitions:
                    updated += 1
            except Exception as exc:
                errors.append({"observation_id": observation_id, "error": str(exc)})

        status = "failed" if errors and not updated else "degraded" if errors else "healthy"
        checkpoint_id = await self._record_poll_checkpoint(
            tenant_id=tenant_id,
            poll_type="finality",
            provider=f"{verifier}_finality",
            source_execution_id=f"finality:{tenant_id}:{chain_id}:{verifier}",
            status=status,
            cursor="",
            started_at=utc_now().isoformat(),
            rows_observed=len(candidates),
            rows_accepted=updated,
            rows_rejected=len(errors),
            dry_run=False,
            errors=errors,
            chain_id=chain_id,
        )
        return StablecoinFinalityPollResult(
            tenant_id=tenant_id,
            chain_id=chain_id,
            verifier=verifier,
            scanned=len(candidates),
            updated=updated,
            warnings=tuple(dict.fromkeys(warnings)),
            errors=tuple(errors),
            checkpoint_id=checkpoint_id,
        )

    async def _verify(
        self,
        verifier: str,
        tenant_id: str,
        observation_id: str,
        finality_threshold: int,
    ) -> StablecoinRPCVerificationResult | StablecoinSolanaVerificationResult:
        if verifier == "evm":
            return await self.evm_verifier.verify_observation(
                tenant_id=tenant_id,
                observation_id=observation_id,
                finality_threshold=finality_threshold,
            )
        return await self.solana_verifier.verify_observation(
            tenant_id=tenant_id,
            observation_id=observation_id,
            finality_threshold_slots=finality_threshold,
        )

    async def _record_poll_checkpoint(self, **data: Any) -> str:
        checkpoint_id = "stablecoin_poll:{tenant_id}:{poll_type}:{provider}:{source_execution_id}".format(**data)
        now = utc_now().isoformat()
        record = {"checkpoint_id": checkpoint_id, **data, "completed_at": now, "updated_at": now}
        existing = await self.checkpoints.find_by_id(checkpoint_id)
        if existing:
            await self.checkpoints.update(checkpoint_id, {**existing, **record})
        else:
            await self.checkpoints.insert(checkpoint_id, record)
        return checkpoint_id
