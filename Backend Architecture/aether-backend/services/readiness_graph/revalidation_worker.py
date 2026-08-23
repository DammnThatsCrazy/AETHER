"""Supervised capability-readiness revalidation worker.

:func:`build_readiness_revalidation_worker` returns a *fresh* coroutine object
on every call, shaped for :class:`~services.runtime.supervisor.WorkerSupervisor`
registration::

    WorkerSpec(
        name="readiness_revalidation",
        factory=lambda: build_readiness_revalidation_worker(),
        role="readiness",
    )

The loop is supervised-loop-shaped: ``while True`` with a heartbeat, per-iteration
exception isolation, and exponential backoff on iteration-level failures so a
bad iteration can never take the process down or spin hot. Each iteration:

* re-resolves the dependency graph for each (tenant, capability);
* when any blocking node reports invalid evidence (credential expired/revoked,
  provider silence, failed/stale probe), AUTO-DEMOTES the persisted capability
  readiness to the matching off-ramp token — strictly monotonic (never promotes;
  promotion is the job of explicit evidence paths);
* leaves unseeded capabilities untouched (revalidation observes, it does not
  invent state).

Heartbeat: ``heartbeat`` is invoked once per iteration (defaults to ``None``,
which the supervisor's watchdog re-stamps independently).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from shared.certification.readiness import CredentialReadiness, readiness_rank
from shared.common.common import ConflictError
from shared.logger.logger import get_logger, metrics
from shared.integration_contracts.identity import CANONICAL_CAPABILITY_KEYS

from services.readiness_graph.graph import (
    CapabilityReadinessAdapter,
    NodeStatus,
    ReadinessGraphEngine,
    build_default_engine,
    worst_blocking_status,
)

logger = get_logger("aether.readiness_revalidation")

# Actor identity recorded on every auto-demotion in the audit ledger.
_REVALIDATION_ACTOR = "readiness_revalidation_worker"

#: Module-level default store (rows live in the shared store; reset by the
#: test harness's ``reset_in_memory_stores``).
capability_readiness_service: CapabilityReadinessAdapter = CapabilityReadinessAdapter()

# Default capability universe: the canonical integration-contract capability
# keys. Operators can scope the loop down with ``capabilities``.
_DEFAULT_CAPABILITIES: tuple[str, ...] = tuple(sorted(CANONICAL_CAPABILITY_KEYS))

# Worst blocking node status -> persisted demotion target. Only *blocking*
# statuses drive a demotion (NOT_CONFIGURED is non-blocking — a dependency that
# is simply not configured in this deployment must not pull a live capability
# down). Credential trouble maps to REVOKED (main's credential off-ramp);
# operational silence/failure maps to DEGRADED; a hard-disable maps to DISABLED.
_BLOCKER_TO_TARGET: dict[NodeStatus, CredentialReadiness] = {
    NodeStatus.CREDENTIAL_MISSING: CredentialReadiness.REVOKED,
    NodeStatus.CREDENTIAL_INVALID: CredentialReadiness.REVOKED,
    NodeStatus.DISABLED: CredentialReadiness.DISABLED,
    NodeStatus.PROVIDER_UNREACHABLE: CredentialReadiness.DEGRADED,
    NodeStatus.WORKER_UNHEALTHY: CredentialReadiness.DEGRADED,
    NodeStatus.LIVE_EVIDENCE_ABSENT: CredentialReadiness.DEGRADED,
    NodeStatus.UNAVAILABLE: CredentialReadiness.DEGRADED,
}


@dataclass(frozen=True)
class ReadinessRevalidationConfig:
    """Tuning knobs for the revalidation loop."""

    interval_s: float = 60.0
    iteration_backoff_base_s: float = 2.0
    iteration_backoff_max_s: float = 300.0
    #: Optional bound for tests: stop after N successful iterations.
    max_iterations: Optional[int] = None
    #: Optional cooperative stop signal (tests / shutdown).
    stop_event: Optional[asyncio.Event] = field(default=None, repr=False)


def _demotion_target(status: NodeStatus) -> CredentialReadiness:
    """Map a blocking node status onto the persisted demotion token."""
    return _BLOCKER_TO_TARGET.get(status, CredentialReadiness.DEGRADED)


async def _revalidate_one(
    engine: ReadinessGraphEngine,
    store: CapabilityReadinessAdapter,
    tenant_id: str,
    capability: str,
    config: ReadinessRevalidationConfig,
) -> None:
    """Re-resolve one (tenant, capability); auto-demote when evidence invalid."""
    try:
        result = await engine.resolve(capability, tenant_id)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(
            "readiness_revalidation resolve failed capability=%s tenant=%s error=%s",
            capability, tenant_id, exc,
        )
        return
    blockers = [n for n in result.nodes if n.status in _BLOCKER_TO_TARGET]
    if not blockers:
        return  # every node is READY / NOT_CONFIGURED — nothing to demote
    snapshot = await store.snapshot(tenant_id, capability)
    if snapshot is None:
        # Revalidation observes; a capability with no persisted state is not
        # auto-created. Seeding is an explicit evidence path.
        return
    current = snapshot.get("state")
    try:
        current_state = CredentialReadiness(current)
    except (ValueError, KeyError, TypeError):
        logger.warning(
            "readiness_revalidation skipping unparseable state=%r capability=%s tenant=%s",
            current, capability, tenant_id,
        )
        return

    worst = worst_blocking_status([n.status for n in blockers])
    if worst is None:
        return
    target = _demotion_target(worst)
    if readiness_rank(target) >= readiness_rank(current_state):
        # Already at/below the target — a demotion would violate monotonicity
        # (or be a no-op), so there is nothing to move.
        return
    evidence = {
        "blocking_node": next(
            (n.node for n in blockers if n.status == worst), "unknown"
        ),
        "blocker": next(
            (n.blocker for n in blockers if n.status == worst), ""
        ),
    }
    try:
        await store.demote(
            tenant_id,
            capability,
            target=target,
            evidence=evidence,
            reason=f"revalidation: {worst.value} evidence invalid",
            actor=_REVALIDATION_ACTOR,
        )
        metrics.increment(
            "readiness_revalidation_demotion_total",
            labels={
                "capability": capability,
                "from": current_state.value,
                "to": target.value,
            },
        )
    except ConflictError:  # pragma: no cover - race with an explicit change
        return


async def build_readiness_revalidation_worker(
    *,
    engine: Optional[ReadinessGraphEngine] = None,
    store: Optional[CapabilityReadinessAdapter] = None,
    config: ReadinessRevalidationConfig = ReadinessRevalidationConfig(),
    capabilities: Optional[list[str]] = None,
    tenants: Optional[list[str]] = None,
    heartbeat: Optional[Callable[[], None]] = None,
) -> None:
    """The supervised readiness-revalidation loop coroutine.

    Call once per supervised run: the factory MUST return a fresh coroutine
    object (this function is a coroutine function, so ``factory=lambda:
    build_readiness_revalidation_worker(...)`` satisfies the supervisor).

    ``capabilities`` / ``tenants`` scope the revalidated universe (defaults:
    the canonical capability keys; tenant ``""`` = global/unscoped state).
    When ``tenants`` is omitted the loop discovers the tenants that have
    persisted readiness rows (``store.all_tenants()``) rather than silently
    defaulting to unscoped ``""`` — otherwise real tenants' expired/revoked
    credentials could never auto-demote. Pass ``tenants=[""]`` explicitly to
    revalidate only global/unscoped state.
    ``heartbeat`` is invoked at the top of each iteration for liveness.
    """
    engine = engine or build_default_engine()
    store = store or capability_readiness_service
    loop = asyncio.get_running_loop()
    universe = capabilities or list(_DEFAULT_CAPABILITIES)
    tenant_scope = list(tenants) if tenants is not None else await store.all_tenants()
    iterations = 0
    consecutive_failures = 0
    stop_event = config.stop_event

    while True:
        if stop_event is not None and stop_event.is_set():
            logger.info("readiness_revalidation stopped via stop_event")
            return
        if heartbeat is not None:
            try:
                heartbeat()
            except Exception:  # pragma: no cover - heartbeat is best-effort
                pass
        started = loop.time()
        try:
            for tenant_id in tenant_scope:
                for capability in universe:
                    await _revalidate_one(engine, store, tenant_id, capability, config)
            consecutive_failures = 0
            iterations += 1
            if (
                config.max_iterations is not None
                and iterations >= config.max_iterations
            ):
                logger.info(
                    "readiness_revalidation completed max_iterations=%d", iterations
                )
                return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Per-iteration exception isolation: one bad iteration backs off and
            # retries; it never crashes the supervised task.
            consecutive_failures += 1
            delay = min(
                config.iteration_backoff_base_s * (2 ** (consecutive_failures - 1)),
                config.iteration_backoff_max_s,
            )
            logger.error(
                "readiness_revalidation iteration failed attempt=%d delay=%.1fs "
                "uptime_s=%.1f error=%s",
                consecutive_failures, delay, loop.time() - started, exc,
            )
            await _sleep_or_stop(delay, stop_event)
            continue
        await _sleep_or_stop(config.interval_s, stop_event)


async def _sleep_or_stop(
    delay: float, stop_event: Optional[asyncio.Event]
) -> None:
    """Sleep ``delay``, waking early if ``stop_event`` is set (cancel-safe)."""
    if stop_event is None:
        await asyncio.sleep(delay)
        return
    waiter = asyncio.create_task(stop_event.wait())
    try:
        done, _ = await asyncio.wait({waiter}, timeout=delay)
        if not done:
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)
    except asyncio.CancelledError:
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)
        raise


__all__ = [
    "_REVALIDATION_ACTOR",
    "ReadinessRevalidationConfig",
    "build_readiness_revalidation_worker",
    "capability_readiness_service",
]
