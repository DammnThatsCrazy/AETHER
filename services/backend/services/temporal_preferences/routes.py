"""Temporal preference routes.

Tenant-scoped, flag-gated (``AETHER_VIEWER_TIMEZONE_ENABLED``, default off —
zero cost while disabled). Viewer preferences are per-principal display
settings; tenant defaults require admin permission. Every zone is validated
against the temporal kernel; responses include the resolution order so
clients render honestly.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from config.settings import settings
from shared.common.common import APIResponse, NotFoundError
from shared.temporal.zones import tzdb_version

from services.temporal_preferences.models import (
    TenantTemporalDefaults,
    ViewerTemporalPreferences,
)

router = APIRouter(prefix="/v1/preferences/temporal", tags=["temporal-preferences"])
tenant_router = APIRouter(prefix="/v1/tenants/temporal-defaults", tags=["temporal-preferences"])

_VIEWER_TABLE = "viewer_temporal_preferences"
_TENANT_TABLE = "tenant_temporal_defaults"

# Viewer timezone resolution order (documented for clients; display only).
_RESOLUTION_ORDER = (
    "manual_preference",
    "device_automatic",
    "tenant_display_default",
    "utc",
)


def _require_enabled() -> None:
    if not settings.temporal_integrity.viewer_preferences_enabled:
        raise NotFoundError("temporal preferences (feature not enabled)")


def _viewer_repo():
    from repositories.repos import BaseRepository

    class _ViewerPrefsRepository(BaseRepository):
        def __init__(self) -> None:
            super().__init__(_VIEWER_TABLE)

    return _ViewerPrefsRepository()


def _tenant_repo():
    from repositories.repos import BaseRepository

    class _TenantDefaultsRepository(BaseRepository):
        def __init__(self) -> None:
            super().__init__(_TENANT_TABLE)

    return _TenantDefaultsRepository()


def _principal(request: Request) -> str:
    tenant = request.state.tenant
    return tenant.user_id or "tenant-default"


@router.get("")
async def get_viewer_preferences(request: Request) -> APIResponse:
    """The caller's display preferences (defaults when never set)."""
    _require_enabled()
    tenant = request.state.tenant
    tenant.require_permission("read")
    record_id = f"{tenant.tenant_id}:{_principal(request)}"
    stored = await _viewer_repo().find_by_id(record_id)
    prefs = (
        ViewerTemporalPreferences.model_validate(stored.get("preferences", {}))
        if stored
        else ViewerTemporalPreferences()
    )
    return APIResponse(
        data=prefs.model_dump(mode="json"),
        meta={
            "resolution_order": list(_RESOLUTION_ORDER),
            "tzdb_version": tzdb_version(),
            "persisted": stored is not None,
        },
    )


@router.put("")
async def put_viewer_preferences(
    request: Request, preferences: ViewerTemporalPreferences
) -> APIResponse:
    """Set the caller's display preferences (display only, never authority)."""
    _require_enabled()
    tenant = request.state.tenant
    tenant.require_permission("read")  # own display prefs: any authenticated principal
    record_id = f"{tenant.tenant_id}:{_principal(request)}"
    await _viewer_repo().insert(
        record_id,
        {
            "tenant_id": tenant.tenant_id,
            "principal_id": _principal(request),
            "preferences": preferences.model_dump(mode="json"),
        },
    )
    return APIResponse(
        data=preferences.model_dump(mode="json"),
        meta={"resolution_order": list(_RESOLUTION_ORDER), "tzdb_version": tzdb_version()},
    )


@tenant_router.get("")
async def get_tenant_defaults(request: Request) -> APIResponse:
    """The tenant's business-calendar defaults (admin-visible config)."""
    _require_enabled()
    tenant = request.state.tenant
    tenant.require_permission("read")
    stored = await _tenant_repo().find_by_id(tenant.tenant_id)
    defaults = (
        TenantTemporalDefaults.model_validate(stored.get("defaults", {}))
        if stored
        else TenantTemporalDefaults()
    )
    return APIResponse(
        data=defaults.model_dump(mode="json"),
        meta={"tzdb_version": tzdb_version(), "persisted": stored is not None},
    )


@tenant_router.put("")
async def put_tenant_defaults(
    request: Request, defaults: TenantTemporalDefaults
) -> APIResponse:
    """Set tenant business-calendar defaults (admin only; versioned additively)."""
    _require_enabled()
    tenant = request.state.tenant
    tenant.require_permission("admin")
    stored = await _tenant_repo().find_by_id(tenant.tenant_id)
    previous_version = (
        TenantTemporalDefaults.model_validate(stored.get("defaults", {})).version
        if stored
        else 0
    )
    versioned = defaults.model_copy(update={"version": previous_version + 1})
    await _tenant_repo().insert(
        tenant.tenant_id,
        {
            "tenant_id": tenant.tenant_id,
            "defaults": versioned.model_dump(mode="json"),
        },
    )
    return APIResponse(
        data=versioned.model_dump(mode="json"),
        meta={"tzdb_version": tzdb_version()},
    )
