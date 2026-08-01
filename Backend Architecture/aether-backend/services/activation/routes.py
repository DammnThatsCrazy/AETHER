"""Self-serve activation API routes.

Tenant surface (all authenticated via standard API-key middleware, so the
tenant is read from ``request.state.tenant`` — never from the body):

    GET  /v1/activation/status            Current activation state + evidence
    POST /v1/activation/select-plan       Choose a plan tier (P1..P4)
    POST /v1/activation/sdk-selection     Choose SDK platforms
    POST /v1/activation/create-sdk-keys   Mint API keys (raw key returned once)
    POST /v1/activation/test-event        Send one event through real ingestion
    GET  /v1/activation/first-value       Evaluate first value from Bronze rows
    POST /v1/activation/complete          Finish (only when first_value_ready)

Reads require ``read`` permission; state-changing writes require ``write``.
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from shared.auth.auth import Permissions
from shared.common.common import APIResponse
from shared.logger.logger import get_logger

from .models import (
    CreateSdkKeysRequest,
    SdkSelectionRequest,
    SelectPlanRequest,
    TestEventRequest,
)
from .service import ActivationService

logger = get_logger("aether.activation.routes")

router = APIRouter(prefix="/v1/activation", tags=["Activation"])

_service = ActivationService()


@router.get("/status")
async def activation_status(request: Request) -> dict:
    """Return the tenant's current activation state, evidence, and history."""
    tenant = request.state.tenant
    tenant.require_permission(Permissions.READ)
    data = await _service.get_status(tenant.tenant_id)
    return APIResponse(data=data).to_dict()


@router.post("/select-plan")
async def select_plan(request: Request, body: SelectPlanRequest) -> dict:
    tenant = request.state.tenant
    tenant.require_permission(Permissions.WRITE)
    data = await _service.select_plan(tenant.tenant_id, body.plan_tier)
    return APIResponse(data=data).to_dict()


@router.post("/sdk-selection")
async def sdk_selection(request: Request, body: SdkSelectionRequest) -> dict:
    tenant = request.state.tenant
    tenant.require_permission(Permissions.WRITE)
    data = await _service.select_sdks(tenant.tenant_id, body.platforms)
    return APIResponse(data=data).to_dict()


@router.post("/create-sdk-keys")
async def create_sdk_keys(request: Request, body: CreateSdkKeysRequest) -> dict:
    """Mint SDK API keys. The raw key value is returned ONCE and never stored."""
    tenant = request.state.tenant
    tenant.require_permission(Permissions.WRITE)
    data = await _service.create_sdk_keys(tenant.tenant_id, body.count, body.label)
    return APIResponse(data=data).to_dict()


@router.post("/test-event")
async def test_event(request: Request, body: TestEventRequest) -> dict:
    """Send one event through the canonical in-process ingestion path."""
    tenant = request.state.tenant
    tenant.require_permission(Permissions.WRITE)
    data = await _service.run_test_event(request, tenant.tenant_id, body)
    return APIResponse(data=data).to_dict()


@router.get("/first-value")
async def first_value(request: Request) -> dict:
    """Evaluate first value from durable Bronze ``sdk_events`` rows."""
    tenant = request.state.tenant
    tenant.require_permission(Permissions.READ)
    data = await _service.evaluate_first_value(tenant.tenant_id)
    return APIResponse(data=data).to_dict()


@router.post("/complete")
async def complete(request: Request) -> dict:
    """Complete activation. Allowed only when state == first_value_ready."""
    tenant = request.state.tenant
    tenant.require_permission(Permissions.WRITE)
    data = await _service.complete(tenant.tenant_id)
    return APIResponse(data=data).to_dict()
