"""
Aether Service — Notification
Webhooks, email alerts, and Slack integrations.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, BadRequestError, ForbiddenError, NotFoundError, ServiceUnavailableError
from shared.logger.logger import get_logger
from repositories.repos import AlertRepository, ProvidersRepository, WebhookRepository
from services.notification_intelligence.customer_webhook_delivery import (
    CustomerWebhookDeliveryService,
    CustomerWebhookSecretStore,
    ProviderUnavailableError,
    WebhookPolicyError,
    redact_webhook_record,
    resolve_safe_destination,
)

logger = get_logger("aether.service.notification")
router = APIRouter(prefix="/v1/notifications", tags=["Notifications"])

_webhook_repo = WebhookRepository()
_alert_repo = AlertRepository()
_provider_repo = ProvidersRepository()
_webhook_secrets = CustomerWebhookSecretStore(_provider_repo)
_webhook_delivery = CustomerWebhookDeliveryService()


class WebhookConfig(BaseModel):
    url: str = Field(..., min_length=1, max_length=2048)
    events: list[str] = Field(..., min_length=1, description="Events to subscribe to")
    secret: Optional[str] = None
    active: bool = True


def _safe_webhook(record: dict) -> dict:
    """Return the customer webhook DTO without secret material."""
    safe = redact_webhook_record(record)
    safe.pop("secret_hash", None)
    return safe


class AlertRule(BaseModel):
    name: str
    condition: str = Field(..., description="e.g. 'anomaly_score > 0.9'")
    channels: list[str] = Field(..., description="e.g. ['email', 'slack', 'webhook']")
    recipients: list[str] = Field(default_factory=list)


@router.post("/webhooks")
async def create_webhook(body: WebhookConfig, request: Request):
    request.state.tenant.require_permission("write")
    try:
        resolve_safe_destination(body.url)
    except WebhookPolicyError as exc:
        raise BadRequestError(str(exc)) from exc

    wh_id = str(uuid.uuid4())
    try:
        secret_info = await _webhook_secrets.store(
            request.state.tenant.tenant_id,
            wh_id,
            body.secret,
        )
    except ProviderUnavailableError as exc:
        raise ServiceUnavailableError("webhook credential provider") from exc
    webhook = await _webhook_repo.insert(wh_id, {
        "tenant_id": request.state.tenant.tenant_id,
        "url": body.url,
        "events": body.events,
        "active": body.active,
        "secret_ref": secret_info["secret_ref"],
        "secret_hash": secret_info["secret_hash"],
        "secret_configured": True,
    })
    response = _safe_webhook(webhook)
    # A customer receives the raw signing secret exactly once, at creation.
    response["secret"] = secret_info["secret"]
    return APIResponse(data=response).to_dict()


@router.get("/webhooks")
async def list_webhooks(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    request.state.tenant.require_permission("read")
    tenant_id = request.state.tenant.tenant_id
    hooks = await _webhook_repo.find_many(
        filters={"tenant_id": tenant_id}, limit=limit, offset=offset,
        sort_by="created_at", sort_order="desc",
    )
    total = await _webhook_repo.count(filters={"tenant_id": tenant_id})
    return APIResponse(data={
        "webhooks": [_safe_webhook(hook) for hook in hooks],
        "pagination": {
            "limit": limit,
            "offset": offset,
            "total": total,
            "has_more": offset + len(hooks) < total,
        },
    }).to_dict()


@router.delete("/webhooks/{webhook_id}")
async def delete_webhook(webhook_id: str, request: Request):
    request.state.tenant.require_permission("write")
    webhook = await _webhook_repo.find_by_id(webhook_id)
    if not webhook:
        raise NotFoundError("Webhook")
    if webhook.get("tenant_id") != request.state.tenant.tenant_id:
        raise ForbiddenError("Webhook belongs to a different tenant")
    secret_ref = webhook.get("secret_ref")
    if secret_ref:
        await _provider_repo.delete(str(secret_ref))
    await _webhook_repo.delete(webhook_id)
    return APIResponse(data={"deleted": True}).to_dict()


@router.post("/webhooks/{webhook_id}/test")
async def test_webhook(webhook_id: str, request: Request):
    request.state.tenant.require_permission("write")
    webhook = await _webhook_repo.find_by_id(webhook_id)
    if not webhook:
        raise NotFoundError("Webhook")
    if webhook.get("tenant_id") != request.state.tenant.tenant_id:
        raise ForbiddenError("Webhook belongs to a different tenant")
    secret = ""
    secret_ref = webhook.get("secret_ref")
    if secret_ref:
        try:
            secret = await _webhook_secrets.resolve(
                request.state.tenant.tenant_id, str(secret_ref)
            )
        except ProviderUnavailableError as exc:
            raise ServiceUnavailableError("webhook credential provider") from exc
    elif webhook.get("secret"):
        # Migrate legacy raw-secret records on first use and remove the raw
        # value from the webhook record. New writes never take this path.
        try:
            secret_info = await _webhook_secrets.store(
                request.state.tenant.tenant_id, webhook_id, str(webhook["secret"])
            )
        except ProviderUnavailableError as exc:
            raise ServiceUnavailableError("webhook credential provider") from exc
        secret = str(webhook["secret"])
        await _webhook_repo.update(webhook_id, {
            "secret": None,
            "secret_ref": secret_info["secret_ref"],
            "secret_hash": secret_info["secret_hash"],
            "secret_configured": True,
        })

    outcome = await _webhook_delivery.test(
        tenant_id=request.state.tenant.tenant_id,
        webhook_id=webhook_id,
        url=str(webhook.get("url", "")),
        secret=secret,
    )
    return APIResponse(data=asdict(outcome)).to_dict()


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
    request.state.tenant.require_permission("read")
    tenant_id = request.state.tenant.tenant_id
    alerts = await _alert_repo.find_many(filters={"tenant_id": tenant_id})
    return APIResponse(data=alerts).to_dict()
