"""Connector ingestion routes.

* ``router`` (``/v1/integrations/connectors``) — tenant-scoped connector
  management + manual sync/test + authenticated webhook ingest.
* ``admin_router`` (``/v1/admin/kyber/connectors``) — operator-gated,
  aggregate-only connector health.

Production external webhook delivery (unauthenticated, signature-verified)
targets a public ``/v1/integrations/webhooks/{connector}`` endpoint. Provider
adapters use their native scheme when declared; generic webhooks use Aether's
timestamped HMAC scheme.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel

from shared.common.common import APIResponse, ForbiddenError, NotFoundError
from shared.logger.logger import get_logger

from services.integrations.connectors.registry import descriptor_for, get_connector
from services.integrations.connectors.service import connector_service

logger = get_logger("aether.service.connectors.routes")

router = APIRouter(prefix="/v1/integrations/connectors", tags=["Integrations — Connectors"])
admin_router = APIRouter(prefix="/v1/admin/kyber/connectors", tags=["Admin — Kyber Connectors"])
# Public webhook router — no API key auth, signature-verified in the handler.
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
    credential: Optional[str] = None  # raw credential stored inline to vault; sets secret_ref


class IntegrationManifestApproval(BaseModel):
    approved_purposes: list[str]
    processing_basis: str
    allowed_fields: list[str]
    provider_admin_installed: bool = False


@router.get("")
async def list_connectors(request: Request):
    tenant_id = _tenant_id(request)
    return APIResponse(data={"items": await connector_service.list_for_tenant(tenant_id)}).to_dict()


@router.post("/discovery/scan")
async def scan_configured_integrations(request: Request):
    tenant_id = _tenant_id(request, "write")
    from services.integrations.discovery import discover_configured_integrations

    configured = await connector_service.repo.find_many(
        filters={"tenant_id": tenant_id},
        limit=1000,
    )
    items = await discover_configured_integrations(tenant_id, configured)
    return APIResponse(data={"items": items, "count": len(items)}).to_dict()


@router.get("/discovery/detections")
async def get_detected_integrations(request: Request):
    tenant_id = _tenant_id(request)
    from services.integrations.discovery import list_detections

    items = await list_detections(tenant_id)
    return APIResponse(data={"items": items, "count": len(items)}).to_dict()


@router.get("/manifests")
async def get_integration_manifests(request: Request):
    tenant_id = _tenant_id(request)
    from services.integrations.discovery import list_manifests

    items = await list_manifests(tenant_id)
    return APIResponse(data={"items": items, "count": len(items)}).to_dict()


@router.post("/manifests/{connector_type}/draft")
async def draft_integration_manifest(
    connector_type: str,
    request: Request,
):
    tenant_id = _tenant_id(request, "admin")
    if get_connector(connector_type) is None:
        raise NotFoundError("connector")
    from services.integrations.discovery import create_draft_manifest

    stored = await create_draft_manifest(
        tenant_id,
        connector_type,
        actor_id=_actor(request),
    )
    return APIResponse(data=stored).to_dict()


@router.put("/manifests/{connector_type}")
async def approve_integration_manifest(
    connector_type: str,
    body: IntegrationManifestApproval,
    request: Request,
):
    tenant_id = _tenant_id(request, "admin")
    if get_connector(connector_type) is None:
        raise NotFoundError("connector")
    from services.integrations.discovery import approve_manifest

    stored = await approve_manifest(
        tenant_id,
        connector_type,
        approved_purposes=body.approved_purposes,
        processing_basis=body.processing_basis,
        allowed_fields=body.allowed_fields,
        provider_admin_installed=body.provider_admin_installed,
        actor_id=_actor(request),
    )
    return APIResponse(data=stored).to_dict()


@router.get("/{connector_type}")
async def get_connector_config(connector_type: str, request: Request):
    tenant_id = _tenant_id(request)
    if get_connector(connector_type) is None:
        raise NotFoundError("connector")
    cfg = await connector_service.get(tenant_id, connector_type)
    descriptor = descriptor_for(connector_type)
    return APIResponse(data={"descriptor": descriptor, "config": cfg}).to_dict()


@router.put("/{connector_type}")
async def configure_connector(connector_type: str, body: ConnectorConfigure, request: Request):
    tenant_id = _tenant_id(request, "write")
    if get_connector(connector_type) is None:
        raise NotFoundError("connector")
    # Comms connectors are plan-gated (§20): enforce entitlement on enable, with
    # an explicit upgrade_required / quota_reached reason (never a silent drop).
    if body.enabled:
        from services.comms.entitlements import CommsEntitlementPolicy, is_comms_connector
        if is_comms_connector(connector_type):
            from shared.auth.auth import PlanTier
            from shared.common.common import ForbiddenError
            plan = getattr(getattr(request.state, "tenant", None), "plan_tier",
                           PlanTier.P1_HOBBYIST)
            existing = await connector_service.list_for_tenant(tenant_id)
            current = sum(
                1 for c in existing
                if c.get("enabled") and c.get("connector_type") != connector_type
                and is_comms_connector(c.get("connector_type", ""))
            )
            decision = CommsEntitlementPolicy().evaluate_connection(
                plan, current_connections=current,
            )
            if not decision.allowed:
                raise ForbiddenError(
                    f"comms entitlement {decision.state}: {decision.reason}"
                )
    stored = await connector_service.configure(
        tenant_id, connector_type, name=body.name or "", config=body.config,
        enabled=body.enabled, secret_configured=body.secret_configured,
        credential=body.credential, actor_id=_actor(request),
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
async def sync_connector(connector_type: str, request: Request, since: Optional[str] = None):
    """Trigger a sync. ``since`` (ISO-8601) selects a historical backfill window;
    omit it for an incremental sync from the connector's last cursor."""
    tenant_id = _tenant_id(request, "write")
    if get_connector(connector_type) is None:
        raise NotFoundError("connector")
    result = await connector_service.sync(
        tenant_id, connector_type, actor_id=_actor(request), since=since,
    )
    return APIResponse(data=result.model_dump()).to_dict()


@router.get("/{connector_type}/sync-runs")
async def list_connector_sync_runs(connector_type: str, request: Request, limit: int = 50):
    """Durable sync-run history — the customer-visible sync progress surface."""
    tenant_id = _tenant_id(request, "read")
    if get_connector(connector_type) is None:
        raise NotFoundError("connector")
    runs = await connector_service.list_sync_runs(
        tenant_id, connector_type, limit=max(1, min(limit, 200))
    )
    return APIResponse(data={"items": runs}).to_dict()


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
    # Secret resolved from the vault when enabled; None means unavailable.
    result = await connector_service.ingest_webhook(
        connector_type, tenant_id, raw_body=raw, signature=sig, timestamp=ts,
        secret=None, headers=dict(request.headers),
    )
    return APIResponse(data=result).to_dict()


# ── Public provider webhook ingestion ─────────────────────────────────────────
# This route is UNAUTHENTICATED by API key.  It is listed in PUBLIC_PATH_PREFIXES
# so the middleware skips token auth.  Security is enforced inside the handler via
# provider-native or Aether HMAC signature verification.
#
# Tenant routing: the tenant is resolved by looking up the connector config whose
# stored webhook secret produces a valid signature for the incoming payload. The
# caller provides X-Aether-Tenant-ID so we can scope the secret lookup efficiently.
# If X-Aether-Tenant-ID is missing or verification fails, the request is rejected.
#
# Generic Aether HMAC delivery also enforces a five-minute replay window.

@webhook_public_router.post("/{connector_type}")
async def public_webhook_ingest(connector_type: str, request: Request):
    """
    Public provider webhook ingestion.

    - No API key required.
    - Provider-native or Aether HMAC signature verification.
    - Tenant resolved from X-Aether-Tenant-ID header.
    - Generic HMAC replay prevention: 5-minute timestamp window.
    - Idempotent: duplicate webhook event IDs are detected and skipped.

    Headers:
      X-Aether-Tenant-ID: <tenant_id>       (required — set by webhook registration)
      X-Aether-Signature: <hmac_sha256_hex>  (generic webhook only)
      X-Aether-Timestamp: <unix_epoch_int>   (generic webhook only)
      Provider-native signature headers     (declared adapter schemes)
    """
    from shared.common.common import BadRequestError, ForbiddenError
    from shared.logger.logger import metrics as _metrics

    connector = get_connector(connector_type)
    if connector is None:
        raise NotFoundError("connector")

    tenant_id = request.headers.get("X-Aether-Tenant-ID", "").strip()
    if not tenant_id:
        raise BadRequestError("X-Aether-Tenant-ID header is required")

    signature = request.headers.get("X-Aether-Signature", "").strip()
    timestamp = request.headers.get("X-Aether-Timestamp", "").strip()
    uses_native_signature = callable(
        getattr(connector, "verify_webhook_signature", None)
    )
    if not uses_native_signature and (not signature or not timestamp):
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

    from services.integrations.webhook_policy import (
        verify_provider_webhook_signature,
    )

    if not verify_provider_webhook_signature(
        connector,
        raw_body=raw_body,
        headers=dict(request.headers),
        secret=secret,
        signature=signature,
        timestamp=timestamp,
    ):
        _metrics.increment("connector_webhook_rejected_total", labels={
            "connector": connector_type, "reason": "invalid_signature",
        })
        raise BadRequestError("Webhook signature verification failed")

    # Signature verified — ingest the webhook
    result = await connector_service.ingest_webhook(
        connector_type, tenant_id,
        raw_body=raw_body, signature=signature, timestamp=timestamp,
        secret=secret, headers=dict(request.headers),
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


@admin_router.get("/feeders")
async def feeders_health(request: Request, tenant_id: Optional[str] = None, limit: int = 100):
    """Kyber feeder health — recent Dune feeder run records across all tenants
    (or scoped to a single tenant via ?tenant_id=).

    Returns rows_ingested, rows_promoted, rows_rejected, promotion_rate, and
    status per run so operators can diagnose freshness/quality gate failures.
    """
    _require_operator(request)
    from services.integrations.dune_feeder.service import get_feeder_health
    items = await get_feeder_health(tenant_id=tenant_id, limit=max(1, min(limit, 500)))
    return APIResponse(data={"items": items, "count": len(items)}).to_dict()


@admin_router.get("/tenants/{tenant_id}")
async def connectors_health_for_tenant(tenant_id: str, request: Request):
    """Per-connector health drill-down for a single tenant (Kyber operator view).

    Returns sync status, last sync time, error count, and last error message for
    every connector type — including unconfigured ones so the operator sees the
    full connector surface for that tenant.
    """
    _require_operator(request)
    items = await connector_service.health_for_tenant(tenant_id)
    return APIResponse(data={"tenant_id": tenant_id, "items": items}).to_dict()


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
