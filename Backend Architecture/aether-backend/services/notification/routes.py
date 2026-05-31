"""
Aether Service — Notification
Webhooks, email alerts, and Slack integrations.
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, ForbiddenError, NotFoundError
from shared.logger.logger import get_logger
from repositories.repos import WebhookRepository, AlertRepository

logger = get_logger("aether.service.notification")
router = APIRouter(prefix="/v1/notifications", tags=["Notifications"])

_webhook_repo = WebhookRepository()
_alert_repo = AlertRepository()


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


@router.post("/webhooks")
async def create_webhook(body: WebhookConfig, request: Request):
    request.state.tenant.require_permission("write")
    wh_id = str(uuid.uuid4())
    webhook = await _webhook_repo.insert(wh_id, {
        "tenant_id": request.state.tenant.tenant_id,
        **body.model_dump(),
    })
    return APIResponse(data=webhook).to_dict()


@router.get("/webhooks")
async def list_webhooks(request: Request):
    tenant_id = request.state.tenant.tenant_id
    hooks = await _webhook_repo.find_many(filters={"tenant_id": tenant_id})
    return APIResponse(data=hooks).to_dict()


@router.delete("/webhooks/{webhook_id}")
async def delete_webhook(webhook_id: str, request: Request):
    request.state.tenant.require_permission("write")
    webhook = await _webhook_repo.find_by_id(webhook_id)
    if not webhook:
        raise NotFoundError("Webhook")
    if webhook.get("tenant_id") != request.state.tenant.tenant_id:
        raise ForbiddenError("Webhook belongs to a different tenant")
    await _webhook_repo.delete(webhook_id)
    return APIResponse(data={"deleted": True}).to_dict()


@router.post("/alerts")
async def create_alert(body: AlertRule, request: Request):
    request.state.tenant.require_permission("write")
    alert_id = str(uuid.uuid4())
    alert = await _alert_repo.insert(alert_id, {
        "tenant_id": request.state.tenant.tenant_id,
        **body.model_dump(),
    })
    return APIResponse(data=alert).to_dict()


@router.get("/alerts")
async def list_alerts(request: Request):
    tenant_id = request.state.tenant.tenant_id
    alerts = await _alert_repo.find_many(filters={"tenant_id": tenant_id})
    return APIResponse(data=alerts).to_dict()
