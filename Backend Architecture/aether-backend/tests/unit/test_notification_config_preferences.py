"""M3c — notification preferences persistence on the existing tenant config.

The notification center / preferences work extends the EXISTING
``/v1/notifications/config`` surface (``TenantNotificationConfig`` +
``UpdateConfigRequest``) rather than introducing a second preferences system.

These tests pin the contract:
  * quiet_hours / timezone / digest all live on the single config model.
  * UpdateConfigRequest accepts the preference fields (partial-update shape).
  * A model round-trip preserves the preference fields.
  * GET /inbox forwards the ``include_archived`` filter to the inbox list fn
    so the notification center can filter by read/archived state.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from services.notification_intelligence.models import (
    TenantNotificationConfig,
    UpdateConfigRequest,
)
from services.notification_intelligence import routes as ni_routes


def _run(coro):
    return asyncio.run(coro)


class _Tenant:
    tenant_id = "tenant-a"

    def require_permission(self, permission):
        return None


def _req():
    return SimpleNamespace(state=SimpleNamespace(tenant=_Tenant()))


PREFERENCE_FIELDS = ("quiet_hours", "timezone", "digest")


def _preference_values():
    return {
        "quiet_hours": {"start": "22:00", "end": "07:00", "timezone": "America/New_York"},
        "timezone": "America/New_York",
        "digest": {"enabled": True, "frequency": "daily", "send_time": "08:00"},
    }


# ── Model contract ───────────────────────────────────────────────────────────


def test_config_model_carries_preference_fields():
    config = TenantNotificationConfig(tenant_id="tenant-a")
    for field in PREFERENCE_FIELDS:
        assert field in config.model_fields, f"missing preference field: {field}"
    assert config.quiet_hours is None
    assert config.timezone is None
    assert config.digest is None


def test_update_config_request_accepts_preference_fields():
    values = _preference_values()
    body = UpdateConfigRequest(**values)
    assert body.quiet_hours == values["quiet_hours"]
    assert body.timezone == values["timezone"]
    assert body.digest == values["digest"]
    # Every update field is optional (partial-update shape).
    assert UpdateConfigRequest() is not None


def test_config_preference_round_trip_preserves_fields():
    values = _preference_values()
    # Mimic the update_config flow: load existing (or default) config, merge
    # exclude_none update payload, re-persist.
    existing = TenantNotificationConfig(tenant_id="tenant-a").model_dump()
    update_data = UpdateConfigRequest(**values).model_dump(exclude_none=True)
    merged = {**existing, **update_data}
    reloaded = TenantNotificationConfig(**merged)
    for field in PREFERENCE_FIELDS:
        assert reloaded.model_dump()[field] == values[field]


# ── Inbox route forwards include_archived ────────────────────────────────────


def test_inbox_route_forwards_include_archived(monkeypatch):
    captured = {}

    async def fake_list(tenant_id, *, unread_only=False, include_archived=False,
                        limit=50, offset=0):
        captured["tenant_id"] = tenant_id
        captured["unread_only"] = unread_only
        captured["include_archived"] = include_archived
        captured["limit"] = limit
        captured["offset"] = offset
        return []

    monkeypatch.setattr(ni_routes, "_inbox_list", fake_list)

    result = _run(ni_routes.list_inbox(
        request=_req(),
        unread=True,
        include_archived=True,
        limit=25,
        offset=5,
    ))
    assert captured == {
        "tenant_id": "tenant-a",
        "unread_only": True,
        "include_archived": True,
        "limit": 25,
        "offset": 5,
    }
    assert result["data"] == []


def test_inbox_route_default_excludes_archived():
    """Without include_archived the route's FastAPI default is ``False`` (so
    archived rows stay out of the listing unless the caller opts in)."""
    import inspect

    sig = inspect.signature(ni_routes.list_inbox)
    param = sig.parameters["include_archived"]
    default = param.default
    # FastAPI Query(False) — compare via the resolved default.
    resolved = default.default if hasattr(default, "default") else default
    assert resolved is False
