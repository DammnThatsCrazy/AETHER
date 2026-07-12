"""Tenant and Kyber routes for Derivatives Intelligence PR4 product surfaces."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, ForbiddenError, NotFoundError
from services.derivatives.product import product_service

router = APIRouter(prefix="/v1/derivatives", tags=["Derivatives"])
kyber_router = APIRouter(prefix="/v1/admin/kyber/derivatives", tags=["Kyber Derivatives"])


class MeterUsageRequest(BaseModel):
    meter: str
    quantity: str = Field(..., description="Fixed-precision decimal quantity")


class OperatorActionRequest(BaseModel):
    tenant_id: str
    action: str
    scope: dict[str, Any] = Field(default_factory=dict)


def _tenant_id(request: Request) -> str:
    return request.state.tenant.tenant_id


def _require_derivatives_read(request: Request) -> None:
    tenant = request.state.tenant
    if hasattr(tenant, "require_permission"):
        tenant.require_permission("derivatives:read")


def _require_derivatives_export(request: Request) -> None:
    tenant = request.state.tenant
    if hasattr(tenant, "require_permission"):
        tenant.require_permission("derivatives:export")


from services.security.request_context import is_kyber_operator as _is_kyber_operator


def _require_kyber_operator(request: Request) -> None:
    tenant = request.state.tenant
    # Canonical fail-closed operator check (replaces the never-set
    # is_platform_admin flag): only kyber:operator grant or the operator
    # tenant-id allowlist passes; Aether tenants (incl. Role.ADMIN) are denied.
    if not _is_kyber_operator(tenant):
        raise ForbiddenError("Kyber operator access required; Aether tenants may not access Kyber")
    if hasattr(tenant, "require_permission"):
        tenant.require_permission("derivatives:connector:admin")


@router.get("/overview")
async def derivatives_overview(request: Request) -> dict:
    _require_derivatives_read(request)
    return APIResponse(data=product_service.overview(_tenant_id(request))).to_dict()


@router.get("/accounts")
async def derivatives_accounts(request: Request) -> dict:
    _require_derivatives_read(request)
    return APIResponse(data={"items": product_service.accounts(_tenant_id(request))}).to_dict()


@router.get("/positions")
async def derivatives_positions(request: Request, status: str | None = Query(default=None)) -> dict:
    _require_derivatives_read(request)
    return APIResponse(data={"items": product_service.positions(_tenant_id(request), status=status)}).to_dict()


@router.get("/positions/{position_epoch_id}")
async def derivatives_position_detail(position_epoch_id: str, request: Request) -> dict:
    _require_derivatives_read(request)
    detail = product_service.position_detail(_tenant_id(request), position_epoch_id)
    if detail is None:
        raise NotFoundError("Derivatives position")
    return APIResponse(data=detail).to_dict()


@router.get("/behavior")
async def derivatives_behavior(request: Request, window: str = Query(default="lifetime")) -> dict:
    _require_derivatives_read(request)
    return APIResponse(data=product_service.behavior(_tenant_id(request), window=window)).to_dict()


@router.get("/realtime/topics")
async def derivatives_realtime_topics(request: Request) -> dict:
    _require_derivatives_read(request)
    return APIResponse(data=product_service.realtime_catalog(_tenant_id(request))).to_dict()


@router.get("/alerts/rules")
async def derivatives_alert_rules(request: Request) -> dict:
    _require_derivatives_read(request)
    return APIResponse(data=product_service.alert_catalog(_tenant_id(request))).to_dict()


@router.post("/usage")
async def derivatives_meter_usage(body: MeterUsageRequest, request: Request) -> dict:
    _require_derivatives_read(request)
    return APIResponse(data=product_service.meter_usage(_tenant_id(request), body.meter, Decimal(body.quantity))).to_dict()


@router.get("/export/evidence")
async def derivatives_export_evidence(request: Request) -> dict:
    _require_derivatives_export(request)
    tenant_id = _tenant_id(request)
    return APIResponse(data={
        "tenant_id": tenant_id,
        "export_type": "derivatives_evidence",
        "credential_material_included": False,
        "items": product_service.positions(tenant_id),
    }).to_dict()


@kyber_router.get("/fleet")
async def kyber_derivatives_fleet(request: Request) -> dict:
    _require_kyber_operator(request)
    return APIResponse(data=product_service.kyber_fleet(_tenant_id(request))).to_dict()


@kyber_router.get("/data-quality")
async def kyber_derivatives_data_quality(request: Request) -> dict:
    _require_kyber_operator(request)
    return APIResponse(data=product_service.kyber_data_quality(_tenant_id(request))).to_dict()


@kyber_router.get("/reconciliation")
async def kyber_derivatives_reconciliation(request: Request, tenant_id: str | None = Query(default=None)) -> dict:
    _require_kyber_operator(request)
    return APIResponse(data=product_service.kyber_reconciliation(_tenant_id(request), tenant_id=tenant_id)).to_dict()


@kyber_router.get("/graph-quality")
async def kyber_derivatives_graph_quality(request: Request) -> dict:
    _require_kyber_operator(request)
    return APIResponse(data=product_service.kyber_graph_quality(_tenant_id(request))).to_dict()


@kyber_router.get("/intelligence-quality")
async def kyber_derivatives_intelligence_quality(request: Request) -> dict:
    _require_kyber_operator(request)
    return APIResponse(data=product_service.kyber_intelligence_quality(_tenant_id(request))).to_dict()


@kyber_router.post("/operator-actions")
async def kyber_derivatives_operator_action(body: OperatorActionRequest, request: Request) -> dict:
    _require_kyber_operator(request)
    return APIResponse(data=product_service.record_operator_action(_tenant_id(request), body.tenant_id, body.action, body.scope)).to_dict()
