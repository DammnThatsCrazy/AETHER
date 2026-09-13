"""Slot-aware, write-only credential/connection API (tenant-admin).

Exposes the durable, multi-slot :class:`CredentialAuthority` under
``/v1/providers/credentials``. Every mutation requires tenant-admin authority,
validates the slot against the server-owned registry (unknown slot → 400), and
never returns a secret value. Optimistic concurrency and idempotency guard
rotation; uniform not-found hides tenant/provider existence.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from services.providers.credentials.authority import SlotError, credential_authority
from services.providers.credentials.models import (
    SlotActivateRequest,
    SlotRotateRequest,
    SlotValueWrite,
)
from services.providers.credentials.slot_registry import known_providers
from shared.common.common import BadRequestError, NotFoundError
from shared.decorators import api_response
from shared.logger.logger import get_logger

logger = get_logger("aether.service.provider_credentials")

router = APIRouter(prefix="/v1/providers/credentials", tags=["provider-credentials"])


def _tenant_admin(request: Request) -> str:
    request.state.tenant.require_permission("admin")
    return request.state.tenant.tenant_id


def _actor(request: Request) -> str:
    tenant = request.state.tenant
    return (
        getattr(tenant, "principal_id", None)
        or getattr(tenant, "tenant_id", None)
        or "tenant-admin"
    )


def _require_known(provider: str) -> None:
    if provider not in known_providers():
        raise NotFoundError("provider")


# ── read ──────────────────────────────────────────────────────────────────
@router.get("/connections")
@api_response
async def list_connections(request: Request, environment: str = "sandbox"):
    tenant_id = _tenant_admin(request)
    try:
        return await credential_authority.get_connections(tenant_id, environment=environment)
    except SlotError as exc:
        raise BadRequestError(str(exc))


@router.get("/{provider}/preflight")
@api_response
async def provider_preflight(provider: str, request: Request, environment: str = "sandbox"):
    tenant_id = _tenant_admin(request)
    _require_known(provider)
    try:
        return await credential_authority.preflight(tenant_id, provider, environment)
    except SlotError as exc:
        raise BadRequestError(str(exc))


# ── slot lifecycle (write-only secrets) ────────────────────────────────────
@router.put("/{provider}/slots/{slot}")
@api_response
async def create_or_replace_slot(
    provider: str, slot: str, body: SlotValueWrite, request: Request, environment: str = "sandbox"
):
    tenant_id = _tenant_admin(request)
    _require_known(provider)
    try:
        return await credential_authority.create_pending(
            tenant_id, provider, environment, slot, body.value,
            created_by=_actor(request), endpoint=body.endpoint,
            idempotency_key=body.idempotency_key,
        )
    except SlotError as exc:
        raise BadRequestError(str(exc))


@router.post("/{provider}/slots/{slot}/test")
@api_response
async def test_slot(provider: str, slot: str, request: Request, environment: str = "sandbox"):
    tenant_id = _tenant_admin(request)
    _require_known(provider)
    try:
        return await credential_authority.test_slot(
            tenant_id, provider, environment, slot, actor=_actor(request)
        )
    except SlotError as exc:
        raise BadRequestError(str(exc))


@router.post("/{provider}/slots/{slot}/activate")
@api_response
async def activate_slot(
    provider: str, slot: str, body: SlotActivateRequest, request: Request, environment: str = "sandbox"
):
    tenant_id = _tenant_admin(request)
    _require_known(provider)
    try:
        return await credential_authority.activate(
            tenant_id, provider, environment, slot,
            credential_version=body.credential_version,
            expected_active_version=body.expected_active_version,
            actor=_actor(request),
        )
    except SlotError as exc:
        raise BadRequestError(str(exc))


@router.post("/{provider}/slots/{slot}/rotate")
@api_response
async def rotate_slot(
    provider: str, slot: str, body: SlotRotateRequest, request: Request, environment: str = "sandbox"
):
    tenant_id = _tenant_admin(request)
    _require_known(provider)
    try:
        return await credential_authority.rotate(
            tenant_id, provider, environment, slot, body.value,
            actor=_actor(request),
            expected_active_version=body.expected_active_version,
            idempotency_key=body.idempotency_key,
        )
    except SlotError as exc:
        raise BadRequestError(str(exc))


@router.post("/{provider}/slots/{slot}/revoke")
@api_response
async def revoke_slot(provider: str, slot: str, request: Request, environment: str = "sandbox"):
    tenant_id = _tenant_admin(request)
    _require_known(provider)
    try:
        return await credential_authority.revoke(
            tenant_id, provider, environment, slot, actor=_actor(request)
        )
    except SlotError as exc:
        raise BadRequestError(str(exc))


@router.delete("/{provider}/slots/{slot}")
@api_response
async def delete_slot(provider: str, slot: str, request: Request, environment: str = "sandbox"):
    tenant_id = _tenant_admin(request)
    _require_known(provider)
    try:
        return await credential_authority.delete(
            tenant_id, provider, environment, slot, actor=_actor(request)
        )
    except SlotError as exc:
        raise BadRequestError(str(exc))


# ── provider enablement ────────────────────────────────────────────────────
@router.post("/{provider}/enable")
@api_response
async def enable_provider(provider: str, request: Request, environment: str = "sandbox"):
    tenant_id = _tenant_admin(request)
    _require_known(provider)
    return await credential_authority.enable_provider(
        tenant_id, provider, environment, actor=_actor(request)
    )


@router.post("/{provider}/disable")
@api_response
async def disable_provider(provider: str, request: Request, environment: str = "sandbox"):
    tenant_id = _tenant_admin(request)
    _require_known(provider)
    return await credential_authority.disable_provider(
        tenant_id, provider, environment, actor=_actor(request)
    )


__all__ = ["router"]
