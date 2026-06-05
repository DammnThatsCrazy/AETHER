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


# ── Kyber operator (aggregate-only) ────────────────────────────────────────────

@admin_router.get("/overview")
async def connectors_overview(request: Request):
    _require_operator(request)
    return APIResponse(data=await connector_service.overview()).to_dict()


@admin_router.get("/health")
async def connectors_health(request: Request):
    _require_operator(request)
    return APIResponse(data=await connector_service.overview()).to_dict()
