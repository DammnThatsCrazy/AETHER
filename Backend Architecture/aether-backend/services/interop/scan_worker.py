"""Durable Interoperability scan-loop worker.

One governed cycle (``ScanWorker.run_cycle``) drives one provider adapter
through: load checkpoint -> supervised :meth:`scan` -> correlation ingest ->
dead-letter quarantine -> reconciliation evidence -> graph projection ->
policy snapshot -> checkpoint persist -> event publish -> metering.

Resume contract: the checkpoint (per-network cursors + ``runtime`` telemetry)
is persisted under ``interop_provider_checkpoints.evidence`` keyed
(tenant_id, provider_id, network_id='*'). A worker killed mid-cycle restarts
from the last persisted checkpoint — never from scratch — so the cursor never
moves backward and a re-run of the same checkpoint is idempotent (the
adapter's windowed scan returns no observations, the message repo's conflict
key dedups replays). ``runtime`` counters (decode_failures, reorg_count,
dead_letter_count, reconciliation_conflicts, last_success/last_failure)
survive restarts inside the checkpoint.

``build_interop_scan_coro`` is the poll loop the runtime worker spec imports
from ``services.interop.lifecycle`` (gated on
``settings.interop.adapters_enabled``).
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from config.settings import settings
from repositories.interop_repos import (
    InteropProviderCheckpointRepo,
    InteropMessageRepo,
    InteropMessageEventRepo,
)
from services.interop.correlation import CorrelationEngine
from services.interop.foundation import (
    deterministic_id,
    deterministic_idempotency_key,
    utc_now_iso,
)
from services.interop.graph_wiring import InteropGraphProjector
from services.interop.providers import INTEROP_PROVIDERS, get_provider
from services.interop.providers.transport import RpcRateLimited
from services.interop.publisher import InteropEventPublisher
from services.interop.reconcile import InteropReconciler
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.interop.scan_worker")

POLL_INTERVAL_SECONDS = 30.0
SENTINEL_NETWORK = "*"


class ScanWorker:
    """One durable scan-loop worker over the registered interop adapters."""

    def __init__(
        self,
        tenant_id: str = "public",
        checkpoint_repo: Optional[InteropProviderCheckpointRepo] = None,
        message_repo: Optional[InteropMessageRepo] = None,
        event_repo: Optional[InteropMessageEventRepo] = None,
        publisher: Optional[InteropEventPublisher] = None,
        reconciler: Optional[InteropReconciler] = None,
        graph_projector: Optional[InteropGraphProjector] = None,
        graph_enabled: Optional[bool] = None,
        security_snapshots_enabled: bool = False,
        adapters: Optional[dict[str, Any]] = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.checkpoints = checkpoint_repo or InteropProviderCheckpointRepo()
        self.engine = CorrelationEngine(
            message_repo=message_repo or InteropMessageRepo(),
            event_repo=event_repo or InteropMessageEventRepo(),
        )
        self.publisher = publisher or InteropEventPublisher()
        self.reconciler = reconciler or InteropReconciler()
        if graph_enabled is None:
            graph_enabled = bool(settings.interop.graph_enabled)
        self.graph_projector = graph_projector or InteropGraphProjector(enabled=graph_enabled)
        self.security_snapshots_enabled = security_snapshots_enabled
        # Provider override for tests (injected RPC client without mutating the
        # global registry); production uses the canonical registry.
        self._adapters = adapters or {}

    async def run_cycle(self, provider_id: str) -> dict[str, Any]:
        """Run one governed scan cycle for one provider. Returns a summary dict.

        Never raises on a provider's own failure modes: ``NotImplementedError``
        (credential-gated guard) returns ``skipped``, ``RpcRateLimited`` returns
        ``rate_limited``, and other scan exceptions are caught, telemetry is
        recorded by the mixin, and the cycle reports ``error``. The checkpoint
        is only advanced after the cycle fully succeeds, so a failed cycle
        restarts from the same cursor.
        """
        adapter = self._adapters.get(provider_id) or get_provider(provider_id)
        if adapter is None:
            return {"provider_id": provider_id, "status": "unknown_provider"}

        stored = await self.checkpoints.find_one({
            "tenant_id": self.tenant_id,
            "provider_id": provider_id,
            "network_id": SENTINEL_NETWORK,
        })
        checkpoint = (stored or {}).get("evidence") or None

        try:
            observations, new_checkpoint = await adapter.scan(checkpoint)
        except NotImplementedError as exc:
            return {
                "provider_id": provider_id,
                "status": "skipped",
                "reason": str(exc),
            }
        except RpcRateLimited as exc:
            logger.warning(
                "interop scan rate-limited for %s (retry_after=%s)",
                provider_id, exc.retry_after,
            )
            return {
                "provider_id": provider_id,
                "status": "rate_limited",
                "reason": str(exc),
                "retry_after": exc.retry_after,
            }
        except Exception as exc:  # noqa: BLE001 — cycle failure, resume next poll
            logger.warning("interop scan cycle failed for %s: %s", provider_id, exc)
            return {
                "provider_id": provider_id,
                "status": "error",
                "reason": str(exc),
            }
        new_checkpoint = new_checkpoint or {}
        new_checkpoint.setdefault("runtime", {})
        new_checkpoint.setdefault("networks", {})

        # ── correlate ────────────────────────────────────────────────────────
        results = []
        for observation in observations:
            results.append(await self.engine.ingest_observation(self.tenant_id, observation))

        emitted: list[dict] = []
        for result in results:
            emitted.extend(result.get("emitted_events", []))

        # ── dead-letter quarantine ───────────────────────────────────────────
        dead_lettered = 0
        for observation, result in zip(observations, results):
            if not result.get("accepted") and observation.get("phase") != "reorged":
                dead_lettered += 1
        if dead_lettered:
            runtime = new_checkpoint["runtime"]
            runtime["dead_letter_count"] = runtime.get("dead_letter_count", 0) + dead_lettered

        # ── reconciliation evidence ──────────────────────────────────────────
        conflicts, reconcile_events = await self.reconciler.run(self.tenant_id, results)
        if conflicts:
            runtime = new_checkpoint["runtime"]
            runtime["reconciliation_conflicts"] = (
                runtime.get("reconciliation_conflicts", 0) + conflicts
            )
        emitted.extend(reconcile_events)

        # ── persist per-adapter reconciliation STATE (durable write path) ────
        # Record the adapter's current reconciliation state (operational fields
        # + source-vs-delivered snapshot) as an idempotent
        # interop_reconciliation_records row. Best-effort: a state-write failure
        # must never fail the cycle — the checkpoint itself is the resume anchor.
        try:
            operational = (
                adapter.operational_state(new_checkpoint)
                if hasattr(adapter, "operational_state")
                else {}
            )
            await self.reconciler.persist_reconciliation_state(
                tenant_id=self.tenant_id,
                provider_id=provider_id,
                operational=operational,
                reconciliation_conflicts=runtime.get("reconciliation_conflicts", 0) if isinstance(runtime, dict) else 0,
            )
        except Exception as exc:  # noqa: BLE001 — telemetry, not a cycle failure
            logger.warning(
                "interop reconciliation-state persist failed for %s: %s",
                provider_id, exc,
            )

        # ── graph projection (gated) ─────────────────────────────────────────
        if self.graph_projector.enabled:
            await self.graph_projector.project(
                self.tenant_id, observations, results,
                provider=adapter.descriptor(), trace_id=provider_id,
            )

        # ── security policy snapshot (gated) ────────────────────────────────
        security_snapshot_count = 0
        if self.security_snapshots_enabled:
            from services.interop.security import scan_security_policy_snapshots
            snapshot_events = await scan_security_policy_snapshots(
                self.tenant_id, observations,
            )
            security_snapshot_count = sum(
                1 for event in snapshot_events
                if event.get("event_name") == "interop_security_policy_snapshot_recorded"
            )
            emitted.extend(snapshot_events)

        # ── persist checkpoint (durable resume) ──────────────────────────────
        basis = f"{self.tenant_id}|{provider_id}|{SENTINEL_NETWORK}"
        if stored is None:
            await self.checkpoints.insert({
                "tenant_id": self.tenant_id,
                "checkpoint_id": deterministic_id("iocp_", basis),
                "provider_id": provider_id,
                "network_id": SENTINEL_NETWORK,
                "last_scanned_block": 0,
                "confirmed_block": 0,
                "advanced_at": utc_now_iso(),
                "idempotency_key": deterministic_idempotency_key(basis),
                "evidence": new_checkpoint,
                "execution_by_aether": False,
            })
        else:
            await self.checkpoints.update_by_key(
                {"tenant_id": self.tenant_id, "provider_id": provider_id,
                 "network_id": SENTINEL_NETWORK},
                {"evidence": new_checkpoint, "advanced_at": utc_now_iso()},
            )

        # ── event publish (broker external; fails loud after retries) ────────
        if emitted:
            await self.publisher.publish_batch(emitted, correlation_id=provider_id)

        # ── metering (canonical interop meter names only) ────────────────────
        if observations:
            metrics.increment("interop_observation_ingested", value=len(observations))
        correlated = sum(
            1 for result in results
            if any(e.get("event_name") == "interop_message_correlated"
                   for e in result.get("emitted_events", []))
        )
        if correlated:
            metrics.increment("interop_message_correlated", value=correlated)
        metrics.increment("interop_reconciliation_run")

        # ── billable usage metering (dedupe-safe; a restart replay of this same
        # checkpoint reproduces the same dedupe keys and cannot double-bill) ──
        try:
            from services.interop.metering import record_cycle_usage
            await record_cycle_usage(
                self.tenant_id, provider_id,
                checkpoint=new_checkpoint,
                observations=len(observations),
                correlated=correlated,
                reconciliation_runs=1,
                security_snapshots=security_snapshot_count,
            )
        except Exception as exc:  # noqa: BLE001 — metering never breaks the cycle
            logger.warning(
                "interop cycle metering failed for %s: %s", provider_id, exc,
            )

        return {
            "provider_id": provider_id,
            "status": "ok",
            "observations": len(observations),
            "ingested": sum(1 for r in results if r.get("accepted")),
            "dead_lettered": dead_lettered,
            "reconciliation_conflicts": conflicts,
            "events_published": len(emitted),
            "checkpoint_advanced": True,
        }


def build_interop_scan_coro(
    tenant_id: str = "public",
    poll_interval_seconds: float = POLL_INTERVAL_SECONDS,
) -> Any:
    """Poll-loop coroutine over every registered interop adapter.

    Consumed by the runtime worker registry (``services/runtime/specs.py``),
    gated on ``settings.interop.adapters_enabled``. Runs until cancelled;
    a failed provider cycle is logged and never aborts the loop.
    """

    async def _loop() -> None:
        worker = ScanWorker(tenant_id=tenant_id)
        logger.info("Interop scan loop started (tenant=%s)", tenant_id)
        while True:
            try:
                for provider_id in list(INTEROP_PROVIDERS):
                    summary = await worker.run_cycle(provider_id)
                    if summary.get("status") == "ok":
                        logger.info(
                            "interop scan %s: %s obs, %s dead-lettered",
                            provider_id, summary["observations"], summary["dead_lettered"],
                        )
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001 — supervisor keeps polling
                logger.error("interop scan loop tick error: %s", exc)
            await asyncio.sleep(poll_interval_seconds)
        logger.info("Interop scan loop stopped")

    return _loop()
