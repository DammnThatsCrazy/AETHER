"""Connector ingestion routes.

* ``router`` (``/v1/integrations/connectors``) — tenant-scoped connector
  management + manual sync/test + authenticated webhook ingest.
* ``admin_router`` (``/v1/admin/kyber/connectors``) — operator-gated,
  aggregate-only connector health.

Production external webhook delivery (unauthenticated, HMAC-verified) targets a
public ``/v1/integrations/webhooks/{connector}`` endpoint; enabling that path is
a credential-gated activation step documented in WEBHOOK-INGESTION.md (it needs
a PUBLIC_PATHS entry + per-tenant routing). This module ships the authenticated
ingest path so the flow is testable and tenant-safe today.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel

from shared.common.common import APIResponse, ForbiddenError, NotFoundError
from shared.logger.logger import get_logger

from services.integrations.connectors.registry import get_connector
from services.integrations.connectors.service import connector_service

logger = get_logger("aether.service.connectors.routes")

router = APIRouter(prefix="/v1/integrations/connectors", tags=["Integrations — Connectors"])
admin_router = APIRouter(prefix="/v1/admin/kyber/connectors", tags=["Admin — Kyber Connectors"])
# Public webhook router — no API key auth, HMAC-verified inside each handler.
# Mounted under PUBLIC_PATH_PREFIXES in feature_gate.py.
webhook_public_router = APIRouter(prefix="/v1/integrations/webhooks", tags=["Integrations — Webhooks"])


def _tenant_id(request: Request, permission: str = "read") -> str:
    request.state.tenant.require_permission(permission)
    tid = getattr(request.state.tenant, "tenant_id", None)
    if not tid:
        raise ForbiddenError("Tenant context is required")
    return tid


def _actor(request: Request) -> str:
    t = getattr(request.state, "tenant", None)
    return getattr(t, "user_id", None) or getattr(t, "tenant_id", None) or "system"


def _require_operator(request: Request):
    from services.security.request_context import require_kyber_operator
    return require_kyber_operator(request)


class ConnectorConfigure(BaseModel):
    name: Optional[str] = None
    config: Optional[dict[str, Any]] = None
    enabled: Optional[bool] = None
    secret_configured: Optional[bool] = None


@router.get("")
async def list_connectors(request: Request):
    tenant_id = _tenant_id(request)
    return APIResponse(data={"items": await connector_service.list_for_tenant(tenant_id)}).to_dict()


@router.get("/{connector_type}")
async def get_connector_config(connector_type: str, request: Request):
    tenant_id = _tenant_id(request)
    if get_connector(connector_type) is None:
        raise NotFoundError("connector")
    cfg = await connector_service.get(tenant_id, connector_type)
    descriptor = get_connector(connector_type).descriptor().model_dump()  # type: ignore[union-attr]
    return APIResponse(data={"descriptor": descriptor, "config": cfg}).to_dict()


@router.put("/{connector_type}")
async def configure_connector(connector_type: str, body: ConnectorConfigure, request: Request):
    tenant_id = _tenant_id(request, "write")
    if get_connector(connector_type) is None:
        raise NotFoundError("connector")
    stored = await connector_service.configure(
        tenant_id, connector_type, name=body.name or "", config=body.config,
        enabled=body.enabled, secret_configured=body.secret_configured, actor_id=_actor(request),
    )
    return APIResponse(data=stored).to_dict()


@router.post("/{connector_type}/test")
async def test_connector(connector_type: str, request: Request):
    tenant_id = _tenant_id(request, "write")
    if get_connector(connector_type) is None:
        raise NotFoundError("connector")
    _ = tenant_id
    return APIResponse(data=(await connector_service.test(tenant_id, connector_type)).model_dump()).to_dict()


@router.post("/{connector_type}/sync")
async def sync_connector(connector_type: str, request: Request):
    tenant_id = _tenant_id(request, "write")
    if get_connector(connector_type) is None:
        raise NotFoundError("connector")
    result = await connector_service.sync(tenant_id, connector_type, actor_id=_actor(request))
    return APIResponse(data=result.model_dump()).to_dict()


@router.post("/{connector_type}/webhook")
async def ingest_connector_webhook(connector_type: str, request: Request):
    """Authenticated, tenant-scoped webhook ingest (for testing/manual delivery).
    Production external delivery uses the public endpoint described in the module
    docstring."""
    tenant_id = _tenant_id(request, "write")
    if get_connector(connector_type) is None:
        raise NotFoundError("connector")
    raw = await request.body()
    sig = request.headers.get("X-Aether-Signature")
    ts = request.headers.get("X-Aether-Timestamp")
    # Secret resolved from the vault when enabled; None in local/mocked mode.
    result = await connector_service.ingest_webhook(
        connector_type, tenant_id, raw_body=raw, signature=sig, timestamp=ts, secret=None,
    )
    return APIResponse(data=result).to_dict()


# ── Public provider webhook ingestion ─────────────────────────────────────────
# This route is UNAUTHENTICATED by API key.  It is listed in PUBLIC_PATH_PREFIXES
# so the middleware skips token auth.  Security is enforced inside the handler via
# HMAC-SHA256 signature verification.
#
# Tenant routing: the tenant is resolved by looking up the connector config whose
# stored webhook secret produces a valid HMAC for the incoming payload.  The
# caller provides X-Aether-Tenant-ID so we can scope the secret lookup efficiently.
# If X-Aether-Tenant-ID is missing or the HMAC fails, the request is rejected.
#
# Replay prevention: a 5-minute timestamp window is enforced; requests older than
# 300 s are rejected.

import hashlib as _hashlib
import hmac as _hmac
import time as _time
import json as _json

_WEBHOOK_TIMESTAMP_TOLERANCE_S = 300  # 5 minutes


def _verify_hmac(secret: str, body: bytes, timestamp: str, signature: str) -> bool:
    """Verify HMAC-SHA256 webhook signature with timestamp replay protection."""
    try:
        ts = int(timestamp)
    except (ValueError, TypeError):
        return False
    age = abs(int(_time.time()) - ts)
    if age > _WEBHOOK_TIMESTAMP_TOLERANCE_S:
        return False
    signing_payload = f"{timestamp}.".encode() + body
    expected = _hmac.new(secret.encode(), signing_payload, _hashlib.sha256).hexdigest()
    sig_hex = signature.removeprefix("v1=")
    return _hmac.compare_digest(expected, sig_hex)


@webhook_public_router.post("/{connector_type}")
async def public_webhook_ingest(connector_type: str, request: Request):
    """
    Public provider webhook ingestion.

    - No API key required.
    - HMAC-SHA256 verified using the tenant's stored connector secret.
    - Tenant resolved from X-Aether-Tenant-ID header.
    - Replay prevention: 5-minute timestamp window.
    - Idempotent: duplicate webhook event IDs are detected and skipped.

    Headers:
      X-Aether-Tenant-ID: <tenant_id>       (required — set by webhook registration)
      X-Aether-Signature: <hmac_sha256_hex>  (required)
      X-Aether-Timestamp: <unix_epoch_int>   (required)
    """
    from shared.common.common import BadRequestError, UnauthorizedError, ForbiddenError
    from shared.logger.logger import metrics as _metrics

    connector = get_connector(connector_type)
    if connector is None:
        raise NotFoundError("connector")

    tenant_id = request.headers.get("X-Aether-Tenant-ID", "").strip()
    if not tenant_id:
        raise BadRequestError("X-Aether-Tenant-ID header is required")

    signature = request.headers.get("X-Aether-Signature", "").strip()
    timestamp = request.headers.get("X-Aether-Timestamp", "").strip()
    if not signature or not timestamp:
        _metrics.increment("connector_webhook_rejected_total", labels={
            "connector": connector_type, "reason": "missing_signature",
        })
        raise BadRequestError("X-Aether-Signature and X-Aether-Timestamp are required")

    # Resolve tenant's connector secret from vault
    cfg_record = await connector_service.get(tenant_id, connector_type)
    if not cfg_record or not cfg_record.get("enabled"):
        _metrics.increment("connector_webhook_rejected_total", labels={
            "connector": connector_type, "reason": "connector_disabled",
        })
        raise ForbiddenError("Connector not enabled for this tenant")

    from services.integrations.connectors.base import ConnectorConfig
    config = ConnectorConfig(**cfg_record) if cfg_record else None
    secret: Optional[str] = None
    if config and config.secret_configured:
        secret = await connector_service._resolve_secret(config)

    if not secret:
        _metrics.increment("connector_webhook_rejected_total", labels={
            "connector": connector_type, "reason": "secret_missing",
        })
        raise ForbiddenError("Connector webhook secret not configured")

    raw_body = await request.body()

    if not _verify_hmac(secret, raw_body, timestamp, signature):
        _metrics.increment("connector_webhook_rejected_total", labels={
            "connector": connector_type, "reason": "invalid_signature",
        })
        raise BadRequestError("Webhook signature verification failed")

    # Signature verified — ingest the webhook
    result = await connector_service.ingest_webhook(
        connector_type, tenant_id,
        raw_body=raw_body, signature=signature, timestamp=timestamp, secret=secret,
    )
    _metrics.increment("connector_webhook_received_total", labels={"connector": connector_type})

    return APIResponse(data=result).to_dict()


# ── Kyber operator (aggregate-only) ────────────────────────────────────────────

@admin_router.get("/overview")
async def connectors_overview(request: Request):
    _require_operator(request)
    return APIResponse(data=await connector_service.overview()).to_dict()


@admin_router.get("/health")
async def connectors_health(request: Request):
    _require_operator(request)
    return APIResponse(data=await connector_service.overview()).to_dict()


# ── Slack outbound channel configuration ──────────────────────────────────────

slack_notify_router = APIRouter(
    prefix="/v1/integrations/slack-notify", tags=["Integrations — Slack Outbound"]
)


class SlackChannelConfigBody(BaseModel):
    default_channel: str
    bot_token_ref: Optional[str] = None
    channel_map: Optional[dict[str, str]] = None
    templates: Optional[dict[str, str]] = None
    enabled: Optional[bool] = True


@slack_notify_router.put("")
async def configure_slack_notify(body: SlackChannelConfigBody, request: Request):
    """Configure per-tenant Slack outbound channel mapping and templates."""
    tenant_id = _tenant_id(request, "write")
    from repositories.repos import BaseRepository
    repo = BaseRepository("slack_channel_configs")
    record: dict[str, Any] = {
        "tenant_id": tenant_id,
        "default_channel": body.default_channel,
        "channel_map": body.channel_map or {},
        "templates": body.templates or {},
        "enabled": body.enabled if body.enabled is not None else True,
    }
    if body.bot_token_ref:
        record["bot_token_ref"] = body.bot_token_ref
    stored = await repo.insert(tenant_id, record)
    return APIResponse(data=_strip_secrets_shallow(stored)).to_dict()


@slack_notify_router.get("")
async def get_slack_notify_config(request: Request):
    """Get the tenant's current Slack outbound configuration (no tokens)."""
    tenant_id = _tenant_id(request)
    from repositories.repos import BaseRepository
    repo = BaseRepository("slack_channel_configs")
    record = await repo.find_by_id(tenant_id)
    if not record:
        return APIResponse(data={"configured": False}).to_dict()
    return APIResponse(data={**_strip_secrets_shallow(record), "configured": True}).to_dict()


@slack_notify_router.post("/test")
async def test_slack_notify(request: Request):
    """Send a test Slack message using the tenant's configured channel."""
    tenant_id = _tenant_id(request, "write")
    from services.integrations.slack_notify import slack_notify
    ok = await slack_notify.send(
        tenant_id, "default",
        {"event_type": "test", "tenant_id": tenant_id, "message": "Aether Slack test notification"},
    )
    return APIResponse(data={"delivered": ok, "note": "local mode skips delivery" if not ok else "sent"}).to_dict()


def _strip_secrets_shallow(record: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in record.items() if "token" not in k.lower() and "secret" not in k.lower()}
