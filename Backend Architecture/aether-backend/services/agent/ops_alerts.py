"""
Aether Service — One-Person Ops Alerts

Alert compression + routing for a single operator: identical alerts (same
``dedupe_key``) within the compression window increment a counter instead of
producing a new row, and notification routing is throttled per dedupe key so
one incident produces one page, not one page per raw event.

Stores (migration 20260712_ops_runtime):
  - ops_alerts               compressed alert records
  - ops_notification_state   per-dedupe-key last-routed markers

Routing goes through the existing notification-intelligence delivery seam
when it is importable/configured, and FAILS OPEN (log only) otherwise —
alerting must never take the control plane down.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from config.settings import settings
from shared.common.common import BadRequestError
from shared.logger.logger import get_logger, metrics
from shared.store import get_store
from services.agent.runtime_repository import (
    _age_seconds,
    new_id,
    sanitize_error,
    sanitize_payload,
    utc_now,
)

logger = get_logger("aether.service.agent.ops_alerts")

ALERT_SEVERITIES = {"P0", "P1", "P2", "P3", "P4"}
# Same dedupe_key inside this window compresses onto the open alert instead
# of creating a duplicate; notification routing is throttled on the same key.
ALERT_COMPRESSION_WINDOW_SECONDS = int(os.getenv("OPS_ALERT_COMPRESSION_WINDOW_SECONDS", "900"))

_alerts = get_store("ops_alerts")
_notification_state = get_store("ops_notification_state")


def _severity_rank(severity: str) -> int:
    return {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4}.get(severity, 4)


async def record_alert(
    tenant_id: str,
    severity: str,
    kind: str,
    message: str,
    dedupe_key: str,
    request_id: str = "",
) -> dict[str, Any]:
    """Record (or compress onto) an operator alert.

    Same tenant + dedupe_key with an open alert inside the compression window
    increments ``count`` and refreshes ``last_seen_at`` — no duplicate row and
    no duplicate notification. Severity only ever escalates on compression.
    """
    if severity not in ALERT_SEVERITIES:
        raise BadRequestError(f"Invalid alert severity: {severity}. Valid: {sorted(ALERT_SEVERITIES)}")
    if not dedupe_key:
        raise BadRequestError("dedupe_key is required for alert compression")

    now = utc_now()
    existing = [
        a for a in await _alerts.find(tenant_id=tenant_id, dedupe_key=dedupe_key, status="open")
        if _age_seconds(a.get("last_seen_at")) <= ALERT_COMPRESSION_WINDOW_SECONDS
    ]
    if existing:
        alert = existing[0]
        alert["count"] = int(alert.get("count", 1) or 1) + 1
        alert["last_seen_at"] = now
        alert["updated_at"] = now
        if _severity_rank(severity) < _severity_rank(alert.get("severity", "P4")):
            alert["severity"] = severity  # escalate, never downgrade
        await _alerts.set(alert["alert_id"], alert)
        metrics.increment("agent_ops_alerts_compressed", labels={"severity": alert["severity"]})
        return {**alert, "compressed": True}

    alert = {
        "alert_id": new_id("alert"),
        "tenant_id": tenant_id,
        "severity": severity,
        "kind": kind,
        "message": sanitize_error(message),
        "dedupe_key": dedupe_key,
        "status": "open",
        "count": 1,
        "request_id": request_id,
        "created_at": now,
        "last_seen_at": now,
        "updated_at": now,
    }
    await _alerts.set(alert["alert_id"], alert)
    metrics.increment("agent_ops_alerts_recorded", labels={"severity": severity, "kind": kind})
    routing = await route_notification(alert)
    alert["notification"] = routing
    await _alerts.set(alert["alert_id"], alert)
    return {**alert, "compressed": False}


async def list_alerts(
    tenant_id: str,
    status: str | None = None,
    severity: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    filters: dict[str, Any] = {"tenant_id": tenant_id}
    if status:
        filters["status"] = status
    if severity:
        filters["severity"] = severity
    rows = await _alerts.find(**filters)
    rows.sort(key=lambda row: (_severity_rank(row.get("severity", "P4")), row.get("last_seen_at", "")))
    return rows[:limit]


async def resolve_alert(tenant_id: str, alert_id: str, actor: str = "operator") -> dict[str, Any] | None:
    alert = await _alerts.get(alert_id)
    if not alert or alert.get("tenant_id") != tenant_id:
        return None
    alert["status"] = "resolved"
    alert["resolved_by"] = actor
    alert["resolved_at"] = utc_now()
    alert["updated_at"] = alert["resolved_at"]
    await _alerts.set(alert_id, alert)
    return alert


async def route_notification(alert: dict[str, Any]) -> dict[str, Any]:
    """Route an alert to configured notification channels — fail-open.

    Throttled per (tenant, dedupe_key): a key that was routed inside the
    compression window is not routed again. Uses the notification
    intelligence delivery seam when importable; otherwise logs and moves on.
    Nothing sensitive is passed — the alert message is already sanitized.
    """
    tenant_id = alert.get("tenant_id", "")
    dedupe_key = alert.get("dedupe_key", "")
    state_key = f"{tenant_id}:{dedupe_key}"
    state = await _notification_state.get(state_key) or {}
    if state.get("last_routed_at") and _age_seconds(state["last_routed_at"]) <= ALERT_COMPRESSION_WINDOW_SECONDS:
        return {"routed": False, "reason": "throttled"}

    outcome: dict[str, Any]
    try:
        from repositories.repos import UserNotificationChannelRepository
        from services.notification_intelligence.delivery_router import DeliveryRouter

        notification = SimpleNamespace(
            tenant_id=tenant_id,
            severity=alert.get("severity", "P4"),
            source_topic="ops.alert",
            title=f"[{alert.get('severity')}] {alert.get('kind', 'ops alert')}",
            body=alert.get("message", ""),
            summary=alert.get("message", ""),
            alert_id=alert.get("alert_id"),
        )
        # Route through the tenant's ACTUALLY configured channels (same repo the
        # notification consumer uses) — never a bare, unconfigured router.
        results = await DeliveryRouter(
            channel_repo=UserNotificationChannelRepository()
        ).route(notification)
        channels = [
            {"channel_type": r.channel_type, "success": r.success}
            for r in results
        ]
        # No zero-channel false success: an alert with no configured channels is
        # NOT "routed". The alert record itself remains the durable signal.
        outcome = {
            "routed": bool(channels),
            "reason": None if channels else "no_channels_configured",
            "channels": channels,
        }
    except Exception as exc:
        # Fail-open: the alert record itself is the durable signal; channel
        # delivery is best-effort.
        logger.warning(
            "Alert notification routing unavailable (fail-open): tenant=%s kind=%s error=%s",
            tenant_id, alert.get("kind"), exc,
        )
        outcome = {"routed": False, "reason": f"routing_unavailable: {type(exc).__name__}"}

    await _notification_state.set(state_key, sanitize_payload({
        "id": state_key,
        "tenant_id": tenant_id,
        "dedupe_key": dedupe_key,
        "status": "routed" if outcome.get("routed") else "skipped",
        "last_routed_at": utc_now(),
        "last_outcome": outcome,
        "updated_at": utc_now(),
    }))
    return outcome


# ── Routes ────────────────────────────────────────────────────────────────

ops_router = APIRouter(prefix="/v1/agent/ops", tags=["Agent Ops"])


def _require_ops_enabled() -> None:
    flags = settings.one_person_ops
    if not (flags.one_person_ops_enabled or flags.command_center_enabled):
        raise BadRequestError("One-person ops is not enabled")


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "") or request.headers.get("X-Correlation-ID", "")


class AlertSubmission(BaseModel):
    severity: str = Field(..., pattern="^(P0|P1|P2|P3|P4)$")
    kind: str = Field(..., min_length=1, max_length=128)
    message: str = Field(default="", max_length=4000)
    dedupe_key: str = Field(..., min_length=1, max_length=256)


@ops_router.get("/alerts")
async def get_ops_alerts(
    request: Request,
    status: str | None = None,
    severity: str | None = None,
    limit: int = 100,
):
    _require_ops_enabled()
    tenant = request.state.tenant
    tenant.require_permission("agent:manage")
    rows = await list_alerts(tenant.tenant_id, status=status, severity=severity, limit=limit)
    return {
        "data": {"alerts": rows, "total": len(rows)},
        "status": "success",
        "timestamp": utc_now(),
        "meta": {"request_id": _request_id(request)},
    }


@ops_router.post("/alerts")
async def post_ops_alert(body: AlertSubmission, request: Request):
    _require_ops_enabled()
    tenant = request.state.tenant
    tenant.require_permission("agent:manage")
    alert = await record_alert(
        tenant.tenant_id, body.severity, body.kind, body.message, body.dedupe_key,
        request_id=_request_id(request),
    )
    return {
        "data": alert,
        "status": "success",
        "timestamp": utc_now(),
        "meta": {"request_id": _request_id(request)},
    }
