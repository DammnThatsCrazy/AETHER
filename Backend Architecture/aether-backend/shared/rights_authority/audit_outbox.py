"""Delivery worker for the durable rights-decision audit outbox."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from shared.rights_authority.service import RightsAuthority, rights_authority


async def flush_audit_outbox(
    *,
    authority: RightsAuthority = rights_authority,
    tenant_id: Optional[str] = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Project pending audit envelopes and retain failures for retry.

    Delivery is idempotent because each envelope carries a deterministic audit
    event id derived from its decision id. A projection failure never removes
    or marks the authorization receipt delivered.
    """
    if limit < 1:
        raise ValueError("limit must be positive")
    rows = await authority.repository.list_audit_outbox(tenant_id)
    pending = [row for row in rows if row.get("status") in {"pending", "failed"}][:limit]
    delivered = 0
    failed = 0
    for row in pending:
        outbox_id = str(row.get("outbox_id") or row.get("id") or "")
        audit_event = row.get("event")
        if not outbox_id or not isinstance(audit_event, dict):
            failed += 1
            if outbox_id:
                await authority.repository.update_audit_outbox(
                    outbox_id,
                    status="failed",
                    last_error="invalid_audit_event_envelope",
                    attempts=int(row.get("attempts") or 0) + 1,
                )
            continue
        try:
            from services.security.audit_ledger import audit_ledger

            await audit_ledger.record(**{
                key: value for key, value in audit_event.items()
                if key in {
                    "audit_event_id", "actor_id", "actor_type", "event_type",
                    "resource_type", "resource_id", "action", "outcome",
                    "tenant_id", "policy_decision_id", "metadata",
                }
            })
            await authority.repository.update_audit_outbox(
                outbox_id,
                status="delivered",
                delivered_at=datetime.now(timezone.utc).isoformat(),
                attempts=int(row.get("attempts") or 0) + 1,
                last_error=None,
            )
            delivered += 1
        except Exception as exc:  # noqa: BLE001 — persist the retry state
            await authority.repository.update_audit_outbox(
                outbox_id,
                status="failed",
                attempts=int(row.get("attempts") or 0) + 1,
                last_error=type(exc).__name__,
            )
            failed += 1
    return {
        "tenant_id": tenant_id,
        "scanned": len(pending),
        "delivered": delivered,
        "failed": failed,
        "remaining": max(0, len(pending) - delivered),
    }


__all__ = ["flush_audit_outbox"]
