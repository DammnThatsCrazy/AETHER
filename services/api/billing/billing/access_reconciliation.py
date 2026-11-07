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
