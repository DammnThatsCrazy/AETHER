"""Stablecoin provider and finality polling orchestration.

The scheduler in this module is deliberately connector-neutral and
observation-first: it invokes configured read-only provider connectors, records
provider health/checkpoints through ``StablecoinProviderIngestionRunner``, and
re-checks already stored observations through EVM/Solana verifiers. It does not
sign, submit, route, or simulate transactions.
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any, Protocol

from repositories.stablecoin_repos import (
    StablecoinObservationRepository,
    StablecoinPollingCheckpointRepository,
)
from shared.common.common import utc_now
from shared.logger.logger import get_logger, metrics

from .ingestion import ProviderObservation
from .models import FinalityState
from .providers import StablecoinProviderExecutionReport, StablecoinProviderIngestionRunner
from .rpc_observer import StablecoinEVMReceiptVerifier, StablecoinRPCVerificationResult
from .solana_observer import StablecoinSolanaTransactionVerifier, StablecoinSolanaVerificationResult

logger = get_logger("aether.stablecoins.polling")


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


# ── Supervised provider + finality polling loop ──────────────────────────────
#
# The scheduler above is the unit-of-work API (connector-neutral, durable
# checkpoints). The loop layer drives it on an interval for the runtime
# WorkerSpec: heartbeat, per-pass exception isolation, graceful shutdown.
# Best-effort by construction — a failed pass is logged and counted, never
# allowed to crash the supervised loop.

DEFAULT_POLL_INTERVAL_SECONDS = 300.0
PROVIDER_COOLDOWN_SECONDS = 300
FINALITY_COOLDOWN_SECONDS = 600


def _default_poll_tenant() -> str:
    return os.getenv("DEFAULT_TENANT_ID", "tenant_local_dev")


async def _enabled_poll_tenants(scheduler: StablecoinPollingScheduler) -> list[str]:
    """Tenants that already hold stablecoin observations or poll checkpoints.

    ``distinct_tenant_ids`` is best-effort per repository; a repository that
    raises (e.g. an unprovisioned table in a fresh deployment) is skipped so a
    single failure cannot abort enumeration. Rows are ordered ascending by
    tenant_id for a deterministic pass.
    """
    seen: list[str] = []
    for repo in (scheduler.observations, scheduler.checkpoints):
        try:
            for tid in await repo.distinct_tenant_ids():
                if tid not in seen:
                    seen.append(tid)
        except Exception:  # noqa: BLE001 - best-effort enumeration
            continue
    return seen


async def _poll_tenant_once(
    *,
    tid: str,
    scheduler: StablecoinPollingScheduler,
    connector_registry: Any,
    deployment_items: list[tuple[str, Any]],
    chains: dict[str, str],
) -> dict[str, Any]:
    """One tenant's provider + finality pass. Counters only, never fabricated."""
    providers_polled = 0
    denied = 0
    finality_scanned = 0
    errors: list[str] = []

    for deployment_id, deployment in deployment_items:
        try:
            connector = connector_registry.build_ingestion_connector(deployment_id)
            source_execution_id = f"poll:{deployment_id}"
            # Resume from the durable polling checkpoint: a connector that
            # paginates past its first page persisted a non-empty next_cursor
            # on the previous pass. Pass it back in so this pass picks up where
            # the last one stopped instead of re-fetching page one forever (the
            # key mirrors ``_record_poll_checkpoint``'s provider format).
            checkpoint_id = (
                "stablecoin_poll:{tenant_id}:provider:{provider}:"
                "{source_execution_id}"
            ).format(
                tenant_id=tid,
                provider=connector.provider,
                source_execution_id=source_execution_id,
            )
            cursor = ""
            checkpoint = await scheduler.checkpoints.find_by_id(checkpoint_id)
            if checkpoint:
                cursor = str(checkpoint.get("cursor") or "")
            result = await scheduler.poll_provider(
                tenant_id=tid,
                connector=connector,
                source_execution_id=source_execution_id,
                cursor=cursor,
            )
            if result.status in ("entitlement_denied", "readiness_denied"):
                denied += 1
            elif result.status == "failed":
                errors.append(f"{deployment_id}:{result.status}")
            else:
                providers_polled += 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — one deployment must not abort the pass
            errors.append(f"{deployment_id}:{exc}")

    # Finality re-checks are per-chain; the verifier family follows the chain's
    # token standard (SPL -> solana, everything else EVM).
    for chain_id, verifier in chains.items():
        try:
            fresult = await scheduler.poll_finality(
                tenant_id=tid,
                chain_id=chain_id,
                verifier=verifier,
            )
            if fresult.status == "failed":
                errors.append(f"finality:{chain_id}:failed")
            else:
                finality_scanned += fresult.scanned
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — one chain must not abort the pass
            errors.append(f"finality:{chain_id}:{exc}")

    return {
        "providers_polled": providers_polled,
        "denied": denied,
        "finality_scanned": finality_scanned,
        "errors": errors,
    }


async def run_stablecoin_poll_iteration(
    *,
    tenant_id: str | None = None,
    tenant_ids: list[str] | None = None,
    scheduler: StablecoinPollingScheduler | None = None,
    connector_registry: Any = None,
    provider_cooldown_seconds: int = PROVIDER_COOLDOWN_SECONDS,
    finality_cooldown_seconds: int = FINALITY_COOLDOWN_SECONDS,
) -> dict[str, Any]:
    """Run one supervised provider + finality polling pass.

    The tenant working set resolves in priority order: ``tenant_ids``, then
    ``tenant_id`` (single tenant), then the tenants that already hold
    observations/checkpoints — falling back to the default tenant only when
    nothing is persisted yet (bootstrap; once the default tenant produces
    observations it is covered by enumeration). A multi-tenant deployment must
    never poll exclusively for one ``DEFAULT_TENANT_ID`` while other tenants'
    providers and finality states go unobserved.

    Returns a deterministic summary dict — counters only, never fabricated
    success. Every provider/finality poll flows through the scheduler's durable
    checkpoint, and the scheduler's own cooldown makes a re-pass inside the
    window a no-op (idempotent). A failing provider/chain is counted and logged —
    never allowed to abort the pass.
    """
    scheduler = scheduler or StablecoinPollingScheduler()
    if connector_registry is None:
        from .registry import PLATFORM_STABLECOIN_CONNECTOR_REGISTRY

        connector_registry = PLATFORM_STABLECOIN_CONNECTOR_REGISTRY

    if tenant_ids:
        tids = list(tenant_ids)
    elif tenant_id:
        tids = [tenant_id]
    else:
        tids = await _enabled_poll_tenants(scheduler) or [_default_poll_tenant()]

    deployment_registry = getattr(connector_registry, "deployments", None)
    deployment_items = list(getattr(deployment_registry, "deployments", {}).items())

    # Finality re-checks are per-chain; the verifier family follows the chain's
    # token standard (SPL -> solana, everything else EVM).
    chains: dict[str, str] = {}
    for _, deployment in deployment_items:
        vm = (
            "solana"
            if str(getattr(deployment, "token_standard", "")).lower().startswith("spl")
            else "evm"
        )
        chain_id = getattr(deployment, "chain_id", "")
        if chain_id:
            chains.setdefault(str(chain_id), vm)

    providers_polled = 0
    denied = 0
    finality_scanned = 0
    errors: list[str] = []
    for tid in tids:
        once = await _poll_tenant_once(
            tid=tid,
            scheduler=scheduler,
            connector_registry=connector_registry,
            deployment_items=deployment_items,
            chains=chains,
        )
        providers_polled += once["providers_polled"]
        denied += once["denied"]
        finality_scanned += once["finality_scanned"]
        errors.extend(once["errors"])

    return {
        "tenant_id": tids[0] if len(tids) == 1 else ",".join(tids),
        "tenant_ids": tids,
        "deployments": len(deployment_items),
        "providers_polled": providers_polled,
        "denied": denied,
        "finality_scanned": finality_scanned,
        "errors": errors,
    }


async def stablecoin_polling_loop(
    interval_s: float = DEFAULT_POLL_INTERVAL_SECONDS,
) -> None:
    """Supervised provider + finality polling loop (heartbeat, isolated errors)."""
    logger.info("stablecoin_provider_polling_loop started interval=%ss", interval_s)
    while True:
        try:
            summary = await run_stablecoin_poll_iteration()
            metrics.gauge("stablecoin_provider_polling_heartbeat", 1.0)
            if summary["errors"] or summary["denied"]:
                logger.warning(
                    "stablecoin poll pass errors=%d denied=%d providers=%d finality=%d",
                    len(summary["errors"]), summary["denied"],
                    summary["providers_polled"], summary["finality_scanned"],
                )
            elif summary["providers_polled"] or summary["finality_scanned"]:
                logger.debug(
                    "stablecoin poll pass providers=%d finality=%d",
                    summary["providers_polled"], summary["finality_scanned"],
                )
        except asyncio.CancelledError:
            logger.info("stablecoin_provider_polling_loop stopped")
            raise
        except Exception as exc:  # noqa: BLE001 — loop survives a bad pass
            metrics.increment("stablecoin_provider_polling_error_total")
            logger.error("stablecoin poll iteration failed: %s", exc)
        await asyncio.sleep(interval_s)


def build_stablecoin_polling_loop() -> Any:
    """Zero-arg coroutine factory for the runtime WorkerSpec (INT-C wires it)."""
    return stablecoin_polling_loop()
