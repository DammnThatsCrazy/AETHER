"""
Aether Service — SDK Remote Config Routes

Endpoints:
    GET  /v1/config/sdk/manifest           SDK clients — fetch signed manifest
    PUT  /v1/config/sdk/manifest           Admin — publish new manifest version
    GET  /v1/config/sdk/rollout            Admin — rollout adoption status
    POST /v1/config/sdk/rollout/rollback   Admin — rollback to previous manifest version
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, BadRequestError
from shared.logger.logger import get_logger
from shared.observability import trace_request, emit_latency

from services.sdk_config.service import get_sdk_config_service

logger = get_logger("aether.service.sdk_config.routes")
router = APIRouter(
    prefix="/v1/config/sdk",
    tags=["SDK — Remote Config"],
)


class PublishManifestRequest(BaseModel):
    min_sdk_version: str = Field(default="6.0.0", min_length=1, max_length=32)
    schema_version: str = Field(default="7.0.0", min_length=1, max_length=32)
    rollout_percentage: int = Field(default=100, ge=0, le=100)
    features: dict[str, bool] = Field(default_factory=dict)
    endpoints: dict[str, str] = Field(default_factory=dict)
    flags: dict[str, Any] = Field(default_factory=dict)


@router.get("/manifest")
async def get_manifest(
    request: Request,
    sdk_id: str = "",
    sdk_version: str = "",
    cohort: str = "default",
):
    """
    Return the active signed manifest for this SDK instance.

    SDK clients call this endpoint on startup and after re-initialization.
    The manifest includes feature flags, endpoint overrides, schema version,
    and the minimum supported SDK version.
    """
    ctx = trace_request(request, service="sdk_config")
    tenant = request.state.tenant

    svc = get_sdk_config_service()
    manifest = await svc.get_manifest(
        tenant_id=tenant.tenant_id,
        sdk_id=sdk_id,
        sdk_version=sdk_version,
        cohort=cohort,
    )

    if manifest is None:
        return APIResponse(data={"manifest": None}).to_dict()

    emit_latency("sdk_manifest_fetch", ctx.elapsed_ms())
    return APIResponse(data=manifest.to_dict()).to_dict()


@router.put("/manifest")
async def publish_manifest(body: PublishManifestRequest, request: Request):
    """Admin: publish a new signed manifest version with optional staged rollout."""
    ctx = trace_request(request, service="sdk_config")
    caller = request.state.tenant
    caller.require_permission("admin")

    svc = get_sdk_config_service()
    manifest = await svc.publish_manifest(
        tenant_id=caller.tenant_id,
        min_sdk_version=body.min_sdk_version,
        schema_version=body.schema_version,
        features=body.features,
        endpoints=body.endpoints,
        flags=body.flags,
        rollout_percentage=body.rollout_percentage,
    )

    emit_latency("sdk_manifest_publish", ctx.elapsed_ms())
    return APIResponse(data={
        "manifest_version": manifest.manifest_version,
        "rollout_percentage": manifest.rollout_percentage,
        "signature": manifest.signature[:16] + "...",  # truncated for safety
        "published_at": manifest.published_at,
    }).to_dict()


@router.get("/rollout")
async def get_rollout_status(request: Request):
    """Admin: return rollout adoption status and manifest versioning metadata."""
    ctx = trace_request(request, service="sdk_config")
    caller = request.state.tenant
    caller.require_permission("admin")

    svc = get_sdk_config_service()
    status = await svc.get_rollout_status(caller.tenant_id)

    emit_latency("sdk_rollout_status", ctx.elapsed_ms())
    return APIResponse(data=status).to_dict()


@router.post("/rollout/rollback")
async def rollback_manifest(request: Request):
    """Admin: rollback to the previous manifest version."""
    ctx = trace_request(request, service="sdk_config")
    caller = request.state.tenant
    caller.require_permission("admin")

    svc = get_sdk_config_service()
    manifest = await svc.rollback_manifest(caller.tenant_id)

    if manifest is None:
        return APIResponse(data={
            "rolled_back": False,
            "message": "No previous manifest available for rollback.",
        }).to_dict()

    emit_latency("sdk_manifest_rollback", ctx.elapsed_ms())
    return APIResponse(data={
        "rolled_back": True,
        "restored_version": manifest.manifest_version,
        "published_at": manifest.published_at,
    }).to_dict()
