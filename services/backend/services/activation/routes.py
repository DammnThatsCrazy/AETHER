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

WS-3 (intent-driven activation, additive): goals → recommended connect steps
over the shared connect contracts (connector_service runtime):

    GET  /v1/activation/intents           Intent picker + experience-category order
    POST /v1/activation/intents           Save the tenant's chosen intents (durable)
    GET  /v1/activation/plan              Recommended connect plan per experience
    POST /v1/activation/connect-action    Run one connect step (create/credential/
                                          enable/first_sync) via connector_service

Reads require ``read`` permission; state-changing writes require ``write``.
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from shared.auth.auth import Permissions
from shared.common.common import APIResponse
from shared.logger.logger import get_logger

from .models import (
    ActivationConnectActionRequest,
    ActivationIntentsRequest,
    CreateSdkKeysRequest,
    SdkSelectionRequest,
    SelectPlanRequest,
    TestEventRequest,
)
from .service import ActivationService

logger = get_logger("aether.activation.routes")

router = APIRouter(prefix="/v1/activation", tags=["Activation"])

_service = ActivationService()

# The planner pulls the connectors runtime (catalog + connector_service), so it
# is imported lazily to keep this module's import surface light (matching the
# lazy-import pattern used across the connectors routes).
_planner_instance = None


def _get_planner():
    """Process-level ActivationPlanner singleton (created on first use)."""
    global _planner_instance
    if _planner_instance is None:
        from services.activation.planner import ActivationPlanner

        _planner_instance = ActivationPlanner()
    return _planner_instance


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


# ── WS-3 intent-driven activation (additive) ────────────────────────────────


@router.get("/intents")
async def activation_intents(request: Request) -> dict:
    """The intent picker: customer goals + their recommended experience
    categories, plus the canonical experience-category order/labels."""
    tenant = request.state.tenant
    tenant.require_permission(Permissions.READ)
    planner = _get_planner()
    data = await planner.intent_catalog_view()
    return APIResponse(data=data).to_dict()


@router.post("/intents")
async def save_activation_intents(
    request: Request, body: ActivationIntentsRequest
) -> dict:
    """Save the tenant's chosen ActivationIntent tokens (durable save/resume)."""
    tenant = request.state.tenant
    tenant.require_permission(Permissions.WRITE)
    planner = _get_planner()
    data = await planner.select_intents(tenant.tenant_id, body.intents)
    return APIResponse(data=data).to_dict()


@router.get("/plan")
async def activation_plan(request: Request) -> dict:
    """The recommended connect plan for the tenant's selected intents.

    Reads real tenant connector state and proposes the next connect step per
    experience — never fabricates a step or a readiness claim. Empty until the
    tenant has selected intents (``needs_selection``).
    """
    tenant = request.state.tenant
    tenant.require_permission(Permissions.READ)
    planner = _get_planner()
    data = await planner.build_plan(tenant.tenant_id)
    return APIResponse(data=data).to_dict()


@router.post("/connect-action")
async def activation_connect_action(
    request: Request, body: ActivationConnectActionRequest
) -> dict:
    """Run ONE activation connect step, delegating to connector_service.

    Actions: ``create_tenant_integration`` | ``configure_credential`` |
    ``enable_connection`` | ``first_sync``. Credentials flow through the
    credential service; enablement through the consent policy — the same
    runtime as PUT /v1/integrations/connectors/{type}.
    """
    tenant = request.state.tenant
    tenant.require_permission(Permissions.WRITE)
    planner = _get_planner()
    data = await planner.run_connect_action(
        tenant.tenant_id,
        body.family,
        body.action,
        name=body.name,
        credential=body.credential,
        since=body.since,
    )
    return APIResponse(data=data).to_dict()
