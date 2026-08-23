"""
Aether Service — Supervised Commerce Worker Builders

Builders for the supervised background workers that keep the commerce control
plane convergent. Each builder returns an async loop coroutine that the
integration pass registers as an ``asyncio.Task`` (see wiringNeeds in the
delivery note for the exact main.py registration).

Workers:
    settlement_sweeper
        Retries non-terminal settlements (PENDING / VERIFYING / FAILED) through
        the settlement tracker, bounded by each settlement's retry budget.
    approval_sweeper
        Expires stale PENDING / ASSIGNED approvals past their expiry.
    stale_entitlement_sweeper
        Revokes entitlements that are expired but still ACTIVE.
    reconciliation_loop
        Runs :func:`services.commerce.reconciliation.reconcile_commerce`
        periodically and logs drift (read-only).

Every worker is idempotent, tenant-isolated, and fault-tolerant: a single
iteration failure is logged and the loop continues. Workers never mutate Silver
and never bypass the control plane services.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional

from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.service.commerce.workers")

# Sentinel allowing every tenant (used when the worker is tenant-agnostic).
ALL_TENANTS = "__all__"


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Settlement sweeper ──────────────────────────────────────────────────

async def _settlement_sweep_iteration(tenant_id: str) -> dict[str, int]:
    from services.x402.settlement import get_settlement_tracker
    from services.x402.commerce_models import SettlementState

    tracker = get_settlement_tracker()
    retried = 0
    failed = 0
    for s in await tracker.list_pending(tenant_id):
        if s.state == SettlementState.PENDING and s.attempts < s.max_attempts:
            try:
                await tracker.retry(tenant_id, s.settlement_id)
                retried += 1
            except Exception as exc:  # noqa: BLE001 - worker must not die
                logger.warning("settlement retry failed sid=%s: %s", s.settlement_id, exc)
                failed += 1
    for s in await tracker.list_failed(tenant_id):
        if s.attempts < s.max_attempts:
            try:
                await tracker.retry(tenant_id, s.settlement_id)
                retried += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("failed-settlement retry failed sid=%s: %s", s.settlement_id, exc)
                failed += 1
    if retried or failed:
        metrics.increment("commerce_settlement_sweeps", labels={"tenant_id": tenant_id})
    return {"retried": retried, "failed": failed}


def build_settlement_sweeper(
    tenant_id: str = ALL_TENANTS, interval_s: float = 30.0
) -> Callable[[], Awaitable[None]]:
    """Return an async loop coroutine that retries non-terminal settlements."""

    async def _loop() -> None:
        logger.info("settlement_sweeper started interval=%ss tenant=%s", interval_s, tenant_id)
        while True:
            try:
                if tenant_id == ALL_TENANTS:
                    # Tenant-agnostic sweep: operate per-tenant via the store's
                    # known tenant list (best-effort; store exposes all_tenants
                    # on in-memory collections and no-ops otherwise).
                    from services.x402.commerce_store import get_commerce_store
                    store = get_commerce_store()
                    tenants = getattr(store.receipts, "all_tenants", lambda: [])()
                    for tid in tenants or []:
                        try:
                            await _settlement_sweep_iteration(tid)
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("settlement sweep tenant=%s failed: %s", tid, exc)
                else:
                    await _settlement_sweep_iteration(tenant_id)
            except Exception as exc:  # noqa: BLE001 - loop survives
                logger.error("settlement_sweeper iteration failed: %s", exc)
            await asyncio.sleep(interval_s)

    return _loop


# ── Approval sweeper ────────────────────────────────────────────────────

def build_approval_sweeper(
    tenant_id: str = ALL_TENANTS, interval_s: float = 60.0
) -> Callable[[], Awaitable[None]]:
    """Return an async loop that expires stale PENDING/ASSIGNED approvals."""

    async def _loop() -> None:
        logger.info("approval_sweeper started interval=%ss tenant=%s", interval_s, tenant_id)
        from services.x402.approvals import get_approval_service
        from services.x402.commerce_store import get_commerce_store

        while True:
            try:
                if tenant_id == ALL_TENANTS:
                    store = get_commerce_store()
                    tenants = getattr(store.receipts, "all_tenants", lambda: [])()
                    for tid in tenants or []:
                        try:
                            await get_approval_service().sweep_expired(tid)
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("approval sweep tenant=%s failed: %s", tid, exc)
                else:
                    await get_approval_service().sweep_expired(tenant_id)
            except Exception as exc:  # noqa: BLE001
                logger.error("approval_sweeper iteration failed: %s", exc)
            await asyncio.sleep(interval_s)

    return _loop


# ── Stale entitlement sweeper ───────────────────────────────────────────

def build_stale_entitlement_sweeper(
    tenant_id: str = ALL_TENANTS, interval_s: float = 120.0
) -> Callable[[], Awaitable[None]]:
    """Return an async loop that revokes ACTIVE-but-expired entitlements."""

    async def _loop() -> None:
        logger.info("stale_entitlement_sweeper started interval=%ss tenant=%s", interval_s, tenant_id)
        from services.x402.entitlements import get_entitlement_service
        from services.x402.commerce_models import EntitlementStatus
        from services.x402.commerce_store import get_commerce_store

        while True:
            try:
                store = get_commerce_store()
                tenants = (
                    [tenant_id] if tenant_id != ALL_TENANTS
                    else getattr(store.receipts, "all_tenants", lambda: [])() or []
                )
                for tid in tenants:
                    try:
                        now = _now()
                        for e in await store.list_entitlements(
                            tid, status=EntitlementStatus.ACTIVE
                        ):
                            if e.expires_at and datetime.fromisoformat(
                                e.expires_at.replace("Z", "+00:00")
                            ) < now:
                                await get_entitlement_service().revoke(
                                    tid, e.entitlement_id,
                                    revoked_by="commerce_entitlement_sweeper",
                                    reason="expired_sweeper",
                                )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("entitlement sweep tenant=%s failed: %s", tid, exc)
            except Exception as exc:  # noqa: BLE001
                logger.error("stale_entitlement_sweeper iteration failed: %s", exc)
            await asyncio.sleep(interval_s)

    return _loop


# ── Reconciliation loop ─────────────────────────────────────────────────

def build_reconciliation_loop(
    tenant_id: str = ALL_TENANTS, interval_s: float = 300.0
) -> Callable[[], Awaitable[None]]:
    """Return an async loop that runs commerce reconciliation (read-only)."""

    async def _loop() -> None:
        logger.info("reconciliation_loop started interval=%ss tenant=%s", interval_s, tenant_id)
        from services.commerce.reconciliation import get_commerce_reconciler

        while True:
            try:
                if tenant_id == ALL_TENANTS:
                    from services.x402.commerce_store import get_commerce_store
                    store = get_commerce_store()
                    tenants = getattr(store.receipts, "all_tenants", lambda: [])()
                    for tid in tenants or []:
                        try:
                            report = await get_commerce_reconciler().reconcile_commerce(tid)
                            _log_reconciliation_report(tid, report)
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("reconciliation tenant=%s failed: %s", tid, exc)
                else:
                    report = await get_commerce_reconciler().reconcile_commerce(tenant_id)
                    _log_reconciliation_report(tenant_id, report)
            except Exception as exc:  # noqa: BLE001
                logger.error("reconciliation_loop iteration failed: %s", exc)
            await asyncio.sleep(interval_s)

    return _loop


def _log_reconciliation_report(tenant_id: str, report: dict[str, Any]) -> None:
    drift_count = report.get("drift_count", 0)
    verified = report.get("graph_consistency", {}).get("verified", True)
    metrics.increment(
        "commerce_reconciliation_runs",
        labels={"tenant_id": tenant_id, "drift": str(drift_count)},
    )
    if drift_count or not verified:
        logger.warning(
            "commerce reconciliation found issues tenant=%s drift=%s verified=%s",
            tenant_id, drift_count, verified,
        )


# ── Convenience launcher ────────────────────────────────────────────────

def launch_commerce_workers(
    *,
    tenant_id: str = ALL_TENANTS,
    settlement_interval_s: float = 30.0,
    approval_interval_s: float = 60.0,
    entitlement_interval_s: float = 120.0,
    reconciliation_interval_s: float = 300.0,
) -> list[asyncio.Task]:
    """Schedule all supervised commerce workers as asyncio tasks.

    Returns the created tasks so the integration pass can keep references and
    cancel them on shutdown. Idempotent per call site: each call schedules a
    fresh set of loops (call once at startup).
    """
    builders = [
        build_settlement_sweeper(tenant_id, settlement_interval_s),
        build_approval_sweeper(tenant_id, approval_interval_s),
        build_stale_entitlement_sweeper(tenant_id, entitlement_interval_s),
        build_reconciliation_loop(tenant_id, reconciliation_interval_s),
    ]
    return [asyncio.create_task(builder()) for builder in builders]


__all__ = [
    "build_settlement_sweeper",
    "build_approval_sweeper",
    "build_stale_entitlement_sweeper",
    "build_reconciliation_loop",
    "launch_commerce_workers",
    "ALL_TENANTS",
]
