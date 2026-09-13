"""
Aether Service — Notification
Webhooks, email alerts, and Slack integrations.
Tech: Node.js (Fastify) + SQS. Scaling: Queue-based autoscaling.
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from shared.common.common import APIResponse, utc_now
from shared.logger.logger import get_logger

logger = get_logger("aether.service.notification")
router = APIRouter(prefix="/v1/notifications", tags=["Notifications"])


class WebhookConfig(BaseModel):
    url: str
    events: list[str] = Field(..., description="Events to subscribe to")
    secret: Optional[str] = None
    active: bool = True


class AlertRule(BaseModel):
    name: str
    condition: str = Field(..., description="e.g. 'anomaly_score > 0.9'")
    channels: list[str] = Field(..., description="e.g. ['email', 'slack', 'webhook']")
    recipients: list[str] = Field(default_factory=list)


# Stub stores
_webhooks: dict[str, dict] = {}
_alerts: dict[str, dict] = {}


# ── Webhook Management ────────────────────────────────────────────────

@router.post("/webhooks")
async def create_webhook(body: WebhookConfig, request: Request):
    request.state.tenant.require_permission("write")
    wh_id = str(uuid.uuid4())
    _webhooks[wh_id] = {
        "id": wh_id,
        "tenant_id": request.state.tenant.tenant_id,
        **body.model_dump(),
        "created_at": utc_now().isoformat(),
    }
    return APIResponse(data=_webhooks[wh_id]).to_dict()


@router.get("/webhooks")
async def list_webhooks(request: Request):
    tenant_id = request.state.tenant.tenant_id
    hooks = [w for w in _webhooks.values() if w["tenant_id"] == tenant_id]
    return APIResponse(data=hooks).to_dict()


@router.delete("/webhooks/{webhook_id}")
async def delete_webhook(webhook_id: str, request: Request):
    _webhooks.pop(webhook_id, None)
    return APIResponse(data={"deleted": True}).to_dict()


# ── Alert Rules ───────────────────────────────────────────────────────

@router.post("/alerts")
async def create_alert(body: AlertRule, request: Request):
    request.state.tenant.require_permission("write")
    alert_id = str(uuid.uuid4())
    _alerts[alert_id] = {
        "id": alert_id,
        "tenant_id": request.state.tenant.tenant_id,
        **body.model_dump(),
        "created_at": utc_now().isoformat(),
    }
    return APIResponse(data=_alerts[alert_id]).to_dict()


@router.get("/alerts")
async def list_alerts(request: Request):
    tenant_id = request.state.tenant.tenant_id
    alerts = [a for a in _alerts.values() if a["tenant_id"] == tenant_id]
    return APIResponse(data=alerts).to_dict()
