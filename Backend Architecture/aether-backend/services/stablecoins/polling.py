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
from typing import Any, Coroutine, Protocol

from repositories.stablecoin_repos import (
    StablecoinObservationRepository,
    StablecoinPollingCheckpointRepository,
)
from shared.common.common import utc_now
from shared.logger.logger import get_logger, metrics

from .governance import StablecoinCapabilityEntitlement, StablecoinEntitlementGuard
from .ingestion import ProviderObservation
from .models import FinalityState
from .providers import StablecoinProviderExecutionReport, StablecoinProviderIngestionRunner
from .rpc_observer import StablecoinEVMReceiptVerifier, StablecoinRPCVerificationResult
from .solana_observer import StablecoinSolanaTransactionVerifier, StablecoinSolanaVerificationResult
from .support import StablecoinTenantReadinessGate

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
    skipped: bool = False
    skip_reason: str = ""


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
    skipped: bool = False
    skip_reason: str = ""
    backlog: int = 0


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
        cooldown_seconds: int = 0,
        tenant_entitlements: Any = None,
        entitlement_guard: Any = None,
        readiness_gate: Any = None,
    ) -> StablecoinProviderPollResult:
        if not tenant_id:
            raise ValueError("tenant_id is required for stablecoin provider polling")
        if not source_execution_id:
            raise ValueError("source_execution_id is required for stablecoin provider polling")
        if limit < 1:
            raise ValueError("limit must be positive")
        if cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be non-negative")

        # ── explicit tenant gates: entitlement + support-state readiness ──
        # Fail-closed: a denied tenant is recorded as a failed poll (never an
        # empty healthy run) so the denial is distinguishable from "no data".
        denial = await self._enforce_tenant_gates(
            tenant_id=tenant_id,
            connector=connector,
            source_execution_id=source_execution_id,
            tenant_entitlements=tenant_entitlements,
            entitlement_guard=entitlement_guard,
            readiness_gate=readiness_gate,
            dry_run=dry_run,
        )
        if denial is not None:
            return denial

        checkpoint_id = self._provider_checkpoint_id(tenant_id, connector.provider, source_execution_id)
        if cooldown_seconds and await self._within_cooldown(checkpoint_id, cooldown_seconds):
            # Idempotent re-invocation of the SAME logical poll (same execution
            # id) inside the cooldown window is a no-op — never double-persists,
            # never re-ingests, never fabricates a fresh "healthy" outcome.
            last = await self.checkpoints.find_by_id(checkpoint_id)
            return StablecoinProviderPollResult(
                tenant_id=tenant_id,
                provider=connector.provider,
                source_execution_id=source_execution_id,
                rows_observed=int(last.get("rows_observed", 0)),
                rows_accepted=int(last.get("rows_accepted", 0)),
                rows_rejected=int(last.get("rows_rejected", 0)),
                status=last.get("status", "skipped"),
                cursor=str(last.get("cursor", cursor)),
                checkpoint_id=checkpoint_id,
                errors=tuple(),
                skipped=True,
                skip_reason="cooldown",
            )

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
        cooldown_seconds: int = 0,
    ) -> StablecoinFinalityPollResult:
        if not tenant_id:
            raise ValueError("tenant_id is required for stablecoin finality polling")
        if not chain_id:
            raise ValueError("chain_id is required for stablecoin finality polling")
        if limit < 1:
            raise ValueError("limit must be positive")
        if verifier not in {"evm", "solana"}:
            raise ValueError("verifier must be 'evm' or 'solana'")
        if cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be non-negative")

        checkpoint_id = self._finality_checkpoint_id(tenant_id, chain_id, verifier)
        if cooldown_seconds and await self._within_cooldown(checkpoint_id, cooldown_seconds):
            # Idempotent debounce: a supervised recurring driver ticks often; a
            # fresh completion inside the cooldown window short-circuits the
            # re-scan instead of hammering the verifiers.
            return StablecoinFinalityPollResult(
                tenant_id=tenant_id,
                chain_id=chain_id,
                verifier=verifier,
                scanned=0,
                updated=0,
                checkpoint_id=checkpoint_id,
                skipped=True,
                skip_reason="cooldown",
                backlog=await self.backlog(tenant_id=tenant_id, chain_id=chain_id),
            )

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
            backlog=await self.backlog(tenant_id=tenant_id, chain_id=chain_id),
        )

    # ── scheduler diagnostics (backlog / cursor age / checkpoint audit) ──────

    async def backlog(self, *, tenant_id: str, chain_id: str, limit: int = 10000) -> int:
        """Count observations whose finality is still being re-checked.

        Non-terminal states (observed/pending/confirmed/disputed/unknown) are
        the driver's remaining work for a tenant+chain. 0 is a genuine empty
        backlog — never conflated with a failed poll (the scheduler reports
        failure separately through ``status``/``errors``).
        """
        if not tenant_id or not chain_id:
            return 0
        rows = await self.observations.find_many(
            filters={"tenant_id": tenant_id, "chain_id": chain_id}, limit=limit
        )
        return sum(1 for row in rows if row.get("finality_status") in self.FINALITY_RECHECK_STATES)

    async def backlog_by_status(self, *, tenant_id: str, chain_id: str, limit: int = 10000) -> dict[str, int]:
        """Break a tenant+chain backlog down by finality status for operators."""
        rows = await self.observations.find_many(
            filters={"tenant_id": tenant_id, "chain_id": chain_id}, limit=limit
        )
        counts: dict[str, int] = {}
        for row in rows:
            state = row.get("finality_status")
            if state in self.FINALITY_RECHECK_STATES:
                counts[state] = counts.get(state, 0) + 1
        return counts

    async def cursor_age_seconds(self, *, tenant_id: str, provider: str) -> float | None:
        """Seconds since the provider's cursor last advanced (its last poll).

        ``None`` when the provider has never polled successfully for the tenant
        — distinguishable from a fresh/healthy cursor. Operators page on this to
        detect a stalled provider poller.
        """
        checkpoints = await self.checkpoints.find_many(
            filters={"tenant_id": tenant_id, "poll_type": "provider", "provider": provider}, limit=1
        )
        if not checkpoints:
            return None
        completed_at = checkpoints[0].get("completed_at")
        if not completed_at:
            return None
        from shared.common.common import parse_iso

        try:
            return max(0.0, (utc_now() - parse_iso(completed_at)).total_seconds())
        except (ValueError, TypeError):
            return None

    async def poll_checkpoints(
        self, *, tenant_id: str, poll_type: str | None = None, limit: int = 50
    ) -> list[dict]:
        """Audit trail of durable poll checkpoints for a tenant (operator view)."""
        filters: dict[str, Any] = {"tenant_id": tenant_id}
        if poll_type:
            filters["poll_type"] = poll_type
        return await self.checkpoints.find_many(filters=filters, limit=limit)

    @staticmethod
    def _provider_checkpoint_id(tenant_id: str, provider: str, source_execution_id: str) -> str:
        return f"stablecoin_poll:{tenant_id}:provider:{provider}:{source_execution_id}"

    @staticmethod
    def _finality_checkpoint_id(tenant_id: str, chain_id: str, verifier: str) -> str:
        return f"stablecoin_poll:{tenant_id}:finality:{verifier}_finality:finality:{tenant_id}:{chain_id}:{verifier}"

    async def _within_cooldown(self, checkpoint_id: str, cooldown_seconds: int) -> bool:
        """True when ``checkpoint_id`` completed within ``cooldown_seconds``."""
        last = await self.checkpoints.find_by_id(checkpoint_id)
        if not last or not last.get("completed_at"):
            return False
        from shared.common.common import parse_iso

        try:
            age = (utc_now() - parse_iso(last["completed_at"])).total_seconds()
        except (ValueError, TypeError):
            return False
        return 0 <= age < cooldown_seconds

    async def _enforce_tenant_gates(
        self,
        *,
        tenant_id: str,
        connector: StablecoinProviderConnector,
        source_execution_id: str,
        tenant_entitlements: Any,
        entitlement_guard: Any,
        readiness_gate: Any,
        dry_run: bool,
    ) -> StablecoinProviderPollResult | None:
        """Enforce entitlement + readiness gates on the observation path.

        Returns a typed FAILED poll result when a gate denies the tenant, or
        ``None`` when the tenant may proceed. A denial is recorded as a failed
        checkpoint/health record — it is never reported as healthy empty data.
        """
        if entitlement_guard is None and readiness_gate is None:
            return None
        deployment = getattr(connector, "deployment", None)
        deployment_id = str(getattr(deployment, "deployment_id", "")) if deployment is not None else ""
        context_id = deployment_id or connector.provider
        try:
            if entitlement_guard is not None and tenant_entitlements is not None:
                await entitlement_guard.require_observation(
                    tenant_id=tenant_id,
                    granted_capabilities=tenant_entitlements,
                    deployment_id=context_id,
                )
            if readiness_gate is not None:
                await readiness_gate.require_observation(
                    tenant_id=tenant_id,
                    deployment_id=context_id,
                )
        except Exception as exc:  # typed denial — fail closed, never healthy
            status = "entitlement_denied" if entitlement_guard is not None else "readiness_denied"
            reason = str(exc)
            await self.runner.record_provider_failure(
                tenant_id=tenant_id,
                provider=connector.provider,
                source_execution_id=source_execution_id,
                source_manifest_id=connector.source_manifest_id,
                error=reason,
            )
            checkpoint_id = await self._record_poll_checkpoint(
                tenant_id=tenant_id,
                poll_type="provider",
                provider=connector.provider,
                source_execution_id=source_execution_id,
                status=status,
                cursor="",
                started_at=utc_now().isoformat(),
                rows_observed=0,
                rows_accepted=0,
                rows_rejected=0,
                dry_run=dry_run,
                errors=[reason],
                gate=status,
            )
            return StablecoinProviderPollResult(
                tenant_id=tenant_id,
                provider=connector.provider,
                source_execution_id=source_execution_id,
                rows_observed=0,
                rows_accepted=0,
                rows_rejected=0,
                status=status,
                cursor="",
                checkpoint_id=checkpoint_id,
                errors=(reason,),
            )
        return None

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


# ─────────────────────────────────────────────────────────────────────────────
# Supervised provider + finality polling loop (program sec10/sec11 no-orphan
# sweep). ``build_stablecoin_polling_loop`` is the zero-arg coroutine factory
# the runtime WorkerSpec imports; the loop is supervised-loop-shaped (while
# True, per-iteration exception isolation, heartbeat, graceful shutdown).
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_POLL_INTERVAL_SECONDS = 300.0
PROVIDER_COOLDOWN_SECONDS = 60
FINALITY_COOLDOWN_SECONDS = 300


def _default_poll_tenant() -> str:
    return os.getenv("DEFAULT_TENANT_ID", "tenant_local_dev")


async def run_stablecoin_poll_iteration(
    *,
    tenant_id: str | None = None,
    scheduler: StablecoinPollingScheduler | None = None,
    connector_registry: Any = None,
    provider_cooldown_seconds: int = PROVIDER_COOLDOWN_SECONDS,
    finality_cooldown_seconds: int = FINALITY_COOLDOWN_SECONDS,
) -> dict[str, Any]:
    """Run one supervised provider + finality polling pass for the tenant.

    Returns a deterministic summary dict — counters only, never fabricated
    success. Every provider/finality poll flows through the scheduler's durable
    checkpoint, and the scheduler's own cooldown makes a re-pass inside the
    window a no-op (idempotent). Explicit tenant gates (entitlement guard +
    support-state readiness gate) fail closed: a denied tenant is recorded as a
    denial, never as a healthy empty run.
    """
    tid = tenant_id or _default_poll_tenant()
    scheduler = scheduler or StablecoinPollingScheduler()
    if connector_registry is None:
        from .registry import PLATFORM_STABLECOIN_CONNECTOR_REGISTRY

        connector_registry = PLATFORM_STABLECOIN_CONNECTOR_REGISTRY

    readiness_gate = StablecoinTenantReadinessGate()
    entitlement_guard = StablecoinEntitlementGuard()
    granted = {StablecoinCapabilityEntitlement.OBSERVATION.value}

    deployment_registry = getattr(connector_registry, "deployments", None)
    deployment_items = list(getattr(deployment_registry, "deployments", {}).items())

    providers_polled = 0
    denied = 0
    finality_scanned = 0
    errors: list[str] = []

    for deployment_id, deployment in deployment_items:
        try:
            connector = connector_registry.build_ingestion_connector(deployment_id)
            result = await scheduler.poll_provider(
                tenant_id=tid,
                connector=connector,
                source_execution_id=f"poll:{deployment_id}",
                cooldown_seconds=provider_cooldown_seconds,
                tenant_entitlements=granted,
                entitlement_guard=entitlement_guard,
                readiness_gate=readiness_gate,
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
    for chain_id, verifier in chains.items():
        try:
            fresult = await scheduler.poll_finality(
                tenant_id=tid,
                chain_id=chain_id,
                verifier=verifier,
                cooldown_seconds=finality_cooldown_seconds,
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
        "tenant_id": tid,
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


def build_stablecoin_polling_loop() -> Coroutine[Any, Any, None]:
    """Zero-arg coroutine factory for the runtime WorkerSpec (INT-C wires it)."""
    return stablecoin_polling_loop()
