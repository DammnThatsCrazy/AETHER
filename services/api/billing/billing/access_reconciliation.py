"""Reconcile Access Kit interaction audit rows against non-billable usage events.

Every authorized Access Kit call writes one ``access.interaction`` audit row and,
except for the usage-summary read, one ``access_interaction`` metering event that
shares the audit row's ``request_id`` as its ``source_id``. Both writes are best
effort, so either can be missing. This reports the gaps instead of hiding them.
It reads only; it never writes or repairs anything.
"""

from __future__ import annotations

from typing import Any, Optional

from billing.billing.revops import in_period

UNMETERED_CAPABILITIES = frozenset({"billing.usage.summary.read"})
_READ_LIMIT = 10_000


async def reconcile_access_interactions(
    tenant_id: str,
    start: str,
    end: str,
    *,
    audit_repo: Optional[Any] = None,
    metering_repo: Optional[Any] = None,
) -> dict[str, Any]:
    """Compare audit rows and metering events for ``[start, end)``.

    Returns counts plus the request IDs on each side that lack a counterpart.
    ``truncated`` is true when either read hit its bound, in which case the counts
    are a lower bound and the gaps may be false.
    """
    if audit_repo is None:
        from governance.security.repositories import SecurityAuditEventRepository

        audit_repo = SecurityAuditEventRepository()
    if metering_repo is None:
        from billing.billing.revops import UsageMeteringEventRepository

        metering_repo = UsageMeteringEventRepository()

    audit_rows = await audit_repo.list_for_tenant(tenant_id, limit=_READ_LIMIT)
    meter_rows, meter_truncated = await metering_repo.list_for_tenant_period(
        tenant_id, start, end, limit=_READ_LIMIT,
    )

    expected: dict[str, str] = {}
    for row in audit_rows:
        if row.get("event_type") != "access.interaction" or row.get("tenant_id") != tenant_id:
            continue
        if not in_period(row, start, end, field="created_at"):
            continue
        metadata = row.get("metadata") or {}
        request_id = metadata.get("request_id")
        capability = metadata.get("capability_id") or row.get("resource_id")
        if request_id and capability not in UNMETERED_CAPABILITIES:
            expected[request_id] = capability or ""

    metered = {
        row.get("source_id")
        for row in meter_rows
        if row.get("source_type") == "access_kit"
        and row.get("event_type") == "access_interaction"
        and row.get("tenant_id") == tenant_id
        and row.get("source_id")
    }

    missing_usage = sorted(set(expected) - metered)
    orphan_usage = sorted(metered - set(expected))
    return {
        "tenant_id": tenant_id,
        "start": start,
        "end": end,
        "audited_meterable": len(expected),
        "metered": len(metered),
        "matched": len(set(expected) & metered),
        "audit_without_usage": missing_usage,
        "usage_without_audit": orphan_usage,
        "billable_events_seen": sum(1 for r in meter_rows if r.get("source_type") == "access_kit" and r.get("billable")),
        "truncated": bool(meter_truncated or len(audit_rows) >= _READ_LIMIT),
        "consistent": not missing_usage and not orphan_usage,
    }


_RUN_AT_UTC = (2, 10)  # hour, minute; after the previous UTC day has closed


def previous_utc_day(now: Optional[Any] = None) -> tuple[str, str]:
    """Return ``[start, end)`` for the last complete UTC day."""
    from datetime import datetime, timedelta, timezone

    now = now or datetime.now(timezone.utc)
    end = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return (end - timedelta(days=1)).isoformat(), end.isoformat()


async def _tenant_ids() -> list[str]:
    from repositories.repos import AdminRepository

    rows = await AdminRepository().find_many(limit=10_000)
    return [r.get("id") or r.get("tenant_id") for r in rows if (r.get("id") or r.get("tenant_id"))]


async def run_access_reconciliation_cycle(
    now: Optional[Any] = None,
    *,
    tenant_ids: Optional[list[str]] = None,
    audit_repo: Optional[Any] = None,
    metering_repo: Optional[Any] = None,
) -> dict[str, Any]:
    """Reconcile the previous UTC day for every tenant; one tenant's failure never stops the rest.

    Inconsistent tenants are logged at warning level with their gap counts and
    counted in the ``access_reconciliation_inconsistent`` metric. Nothing is
    written or repaired.
    """
    from shared.logger.logger import get_logger, metrics

    log = get_logger("aether.billing.access_reconciliation")
    start, end = previous_utc_day(now)
    tenants = tenant_ids if tenant_ids is not None else await _tenant_ids()
    summary: dict[str, Any] = {
        "start": start, "end": end, "tenants": len(tenants),
        "consistent": 0, "inconsistent": 0, "failed": 0, "truncated": 0,
    }
    for tenant_id in tenants:
        try:
            report = await reconcile_access_interactions(
                tenant_id, start, end, audit_repo=audit_repo, metering_repo=metering_repo,
            )
        except Exception as exc:  # noqa: BLE001 - isolate per tenant
            summary["failed"] += 1
            log.warning(f"Access reconciliation failed for tenant={tenant_id}: {type(exc).__name__}")
            continue
        if report["truncated"]:
            summary["truncated"] += 1
        if report["consistent"]:
            summary["consistent"] += 1
            continue
        summary["inconsistent"] += 1
        metrics.increment("access_reconciliation_inconsistent")
        log.warning(
            "Access reconciliation gap tenant=%s audit_without_usage=%d usage_without_audit=%d window=%s..%s",
            tenant_id, len(report["audit_without_usage"]), len(report["usage_without_audit"]), start, end,
        )
    return summary


def _seconds_until_next_run(now: Optional[Any] = None) -> float:
    from datetime import datetime, timedelta, timezone

    now = now or datetime.now(timezone.utc)
    run = now.replace(hour=_RUN_AT_UTC[0], minute=_RUN_AT_UTC[1], second=0, microsecond=0)
    if run <= now:
        run += timedelta(days=1)
    return (run - now).total_seconds()


async def run_access_reconciliation_cron() -> None:
    """Supervised daily loop: reconcile yesterday's Access Kit interactions."""
    import asyncio

    from shared.logger.logger import get_logger

    log = get_logger("aether.billing.access_reconciliation")
    while True:
        await asyncio.sleep(_seconds_until_next_run())
        try:
            log.info(f"Access reconciliation cycle complete: {await run_access_reconciliation_cycle()}")
        except Exception as exc:  # noqa: BLE001 - the loop must survive one bad cycle
            log.error(f"Access reconciliation cycle failed: {exc}")
        await asyncio.sleep(600)
