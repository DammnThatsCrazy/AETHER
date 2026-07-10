"""Interoperability Intelligence tenant API — /v1/interoperability.

Read-only intelligence plus canonical observation intake. INVARIANT: no
endpoint relays, routes, retries, or recovers messages. Reads return the
tenant's rows plus public-scope rows; tenant-scoped rows never cross tenants.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from config.settings import settings
from repositories.interop_repos import (
    DeliveryAttemptRepo,
    InteropApplicationRepo,
    InteropAssetLegRepo,
    InteropGatewayRepo,
    InteropIntentRepo,
    InteropMessageEventRepo,
    InteropMessageRepo,
    InteropPathRepo,
    InteropReconciliationRepo,
    SecurityPolicySnapshotRepo,
)
from shared.auth.auth import Permissions
from services.interop.correlation import CorrelationEngine
from services.interop.foundation import (
    PUBLIC_TENANT,
    active_tenant_id as _tenant_id,
    check_no_execution as _check_no_execution,
    require_flag,
    require_permission as _require_perm,
)
from services.interop.providers import INTEROP_PROVIDERS

router = APIRouter(prefix="/v1/interoperability", tags=["interoperability"])


class InteropObservationIn(BaseModel):
    """POST /v1/interoperability/observations — canonical phase observation."""

    model_config = ConfigDict(extra="forbid")

    provider_kind: str
    provider_id: Optional[str] = None
    correlation_key: str = Field(min_length=1)
    phase: str
    endpoint_ref: Optional[dict[str, Any]] = None
    source_network_id: Optional[str] = None
    destination_network_id: Optional[str] = None
    path_id: Optional[str] = None
    sequence: Optional[str] = None
    payload_hash: Optional[str] = None
    payload_type: Optional[str] = None
    provider_native_stage: Optional[str] = None
    provider_message_refs: list[dict[str, Any]] = Field(default_factory=list)
    provider_extension: Optional[dict[str, Any]] = None
    observed_at: Optional[str] = None
    tenant_id: Optional[str] = None
    execution_by_aether: Literal[False] = False


def _gate(request: Request, permission: str = Permissions.INTEROP_READ) -> str:
    require_flag(settings.interop.api_enabled, "Interoperability Intelligence")
    _require_perm(request, permission)
    return _tenant_id(request)


def _meter(name: str) -> None:
    try:
        from shared.logger.logger import metrics
        metrics.increment(name)
    except Exception:
        pass


def _stringify(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        out.append({
            key: str(value) if isinstance(value, Decimal) else value
            for key, value in row.items()
        })
    return out


async def _scoped(repo, tenant_id: str, filters: Optional[dict], limit: int, offset: int):
    """Tenant rows + public rows, never other tenants' rows."""
    own = await repo.find_many({"tenant_id": tenant_id, **(filters or {})}, limit=limit, offset=offset)
    if tenant_id == PUBLIC_TENANT:
        return own
    public = await repo.find_many(
        {"tenant_id": PUBLIC_TENANT, **(filters or {})}, limit=limit, offset=offset,
    )
    return (own + public)[:limit]


@router.get("/providers")
async def list_providers(request: Request):
    """Adapter descriptors with honest implementation statuses."""
    _gate(request)
    return {
        "items": [adapter.descriptor() for adapter in INTEROP_PROVIDERS.values()],
        "count": len(INTEROP_PROVIDERS),
    }


@router.get("/messages")
async def list_messages(
    request: Request,
    status: Optional[str] = None,
    provider_id: Optional[str] = None,
    path_id: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = 0,
):
    tenant_id = _gate(request)
    filters: dict = {}
    if status:
        filters["status"] = status
    if provider_id:
        filters["provider_id"] = provider_id
    if path_id:
        filters["path_id"] = path_id
    rows = await _scoped(InteropMessageRepo(), tenant_id, filters, limit, offset)
    return {"items": _stringify(rows), "count": len(rows)}


@router.get("/messages/{interop_message_id}")
async def message_detail(interop_message_id: str, request: Request):
    """Message + lifecycle timeline + delivery attempts + asset legs —
    the evidence view."""
    tenant_id = _gate(request)
    message = None
    for scope in (tenant_id, PUBLIC_TENANT):
        message = await InteropMessageRepo().find_one(
            {"tenant_id": scope, "interop_message_id": interop_message_id},
        )
        if message:
            break
    if message is None:
        raise HTTPException(status_code=404, detail="message not found")
    scope = message["tenant_id"]
    transitions = await InteropMessageEventRepo().find_many(
        {"tenant_id": scope, "interop_message_id": interop_message_id},
        limit=200, order_by="observed_at", descending=False,
    )
    attempts = await DeliveryAttemptRepo().find_many(
        {"tenant_id": scope, "interop_message_id": interop_message_id}, limit=100,
    )
    legs = await InteropAssetLegRepo().find_many(
        {"tenant_id": scope, "interop_message_id": interop_message_id}, limit=100,
    )
    return {
        "message": _stringify([message])[0],
        "transitions": _stringify(transitions),
        "delivery_attempts": _stringify(attempts),
        "asset_legs": _stringify(legs),
    }


@router.get("/paths")
async def list_paths(request: Request, limit: int = Query(default=50, ge=1, le=200), offset: int = 0):
    _gate(request)
    rows = await InteropPathRepo().find_many(limit=limit, offset=offset)
    return {"items": rows, "count": len(rows)}


@router.get("/gateways")
async def list_gateways(request: Request, limit: int = Query(default=50, ge=1, le=200), offset: int = 0):
    _gate(request)
    rows = await InteropGatewayRepo().find_many(limit=limit, offset=offset)
    return {"items": rows, "count": len(rows)}


@router.get("/applications")
async def list_applications(request: Request, limit: int = Query(default=50, ge=1, le=200), offset: int = 0):
    _gate(request)
    rows = await InteropApplicationRepo().find_many(limit=limit, offset=offset)
    return {"items": rows, "count": len(rows)}


@router.get("/intents")
async def list_intents(request: Request, limit: int = Query(default=50, ge=1, le=200), offset: int = 0):
    tenant_id = _gate(request)
    rows = await _scoped(InteropIntentRepo(), tenant_id, None, limit, offset)
    return {"items": _stringify(rows), "count": len(rows)}


@router.get("/asset-legs")
async def list_asset_legs(
    request: Request, interop_message_id: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200), offset: int = 0,
):
    tenant_id = _gate(request)
    filters = {"interop_message_id": interop_message_id} if interop_message_id else None
    rows = await _scoped(InteropAssetLegRepo(), tenant_id, filters, limit, offset)
    return {"items": _stringify(rows), "count": len(rows)}


@router.get("/security-policies")
async def list_security_policies(
    request: Request, path_id: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200), offset: int = 0,
):
    tenant_id = _gate(request)
    filters = {"path_id": path_id} if path_id else None
    rows = await _scoped(SecurityPolicySnapshotRepo(), tenant_id, filters, limit, offset)
    return {"items": _stringify(rows), "count": len(rows)}


@router.get("/reconciliation")
async def list_reconciliation(
    request: Request, status: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200), offset: int = 0,
):
    tenant_id = _gate(request)
    filters = {"status": status} if status else None
    rows = await _scoped(InteropReconciliationRepo(), tenant_id, filters, limit, offset)
    return {"items": _stringify(rows), "count": len(rows)}


@router.post("/observations", status_code=201)
async def ingest_observation(payload: InteropObservationIn, request: Request):
    tenant_id = _gate(request)
    require_flag(settings.interop.ingestion_enabled, "Interop ingestion")
    if payload.tenant_id and payload.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="payload tenant mismatch")
    _check_no_execution(payload)
    result = await CorrelationEngine().ingest_observation(
        tenant_id, payload.model_dump(exclude_none=True),
    )
    if not result.get("accepted"):
        raise HTTPException(status_code=422, detail=result.get("reason", "rejected"))
    _meter("interop_observation_ingested")
    if any(e["event_name"] == "interop_message_correlated"
           for e in result.get("emitted_events", [])):
        _meter("interop_message_correlated")
    return result
