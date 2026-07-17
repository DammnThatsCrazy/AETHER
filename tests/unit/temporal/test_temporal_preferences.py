"""Temporal preference models + routes: validation, versioning, flag gating."""
from __future__ import annotations

import pytest

from services.temporal_preferences.models import (
    TenantTemporalDefaults,
    ViewerTemporalPreferences,
)


def test_viewer_defaults_are_automatic_display_only():
    prefs = ViewerTemporalPreferences()
    assert prefs.mode == "automatic"
    assert prefs.manual_time_zone is None


def test_viewer_manual_zone_must_be_iana():
    ok = ViewerTemporalPreferences(mode="manual", manual_time_zone="America/New_York")
    assert ok.manual_time_zone == "America/New_York"
    with pytest.raises(Exception):
        ViewerTemporalPreferences(mode="manual", manual_time_zone="EST")


def test_viewer_week_start_bounds():
    assert ViewerTemporalPreferences(week_start=6).week_start == 6
    with pytest.raises(Exception):
        ViewerTemporalPreferences(week_start=7)


def test_tenant_defaults_validate_all_zones_and_policies():
    defaults = TenantTemporalDefaults(
        business_time_zone="Europe/Berlin",
        billing_time_zone="UTC",
        retention_policy_time_zone="Etc/UTC",
        default_dst_gap_policy="reject",
        default_dst_overlap_policy="later_offset",
        fiscal_year_start_month=4,
    )
    assert defaults.business_time_zone == "Europe/Berlin"
    with pytest.raises(Exception):
        TenantTemporalDefaults(billing_time_zone="PST")
    with pytest.raises(Exception):
        TenantTemporalDefaults(fiscal_year_start_month=13)
    with pytest.raises(Exception):
        TenantTemporalDefaults(default_dst_gap_policy="ignore")


@pytest.mark.asyncio
async def test_routes_flag_gated_and_roundtrip(monkeypatch):
    """Flag off → NotFoundError; flag on → viewer prefs roundtrip + tenant
    defaults versioning through the in-memory repository."""
    import config.settings as settings_module
    from config.settings import TemporalIntegrityConfig
    from services.temporal_preferences import routes
    from shared.auth.auth import TenantContext
    from shared.common.common import NotFoundError

    class _Req:
        def __init__(self, tenant: TenantContext) -> None:
            class _State:  # noqa: D401 - simple namespace
                pass

            self.state = _State()
            self.state.tenant = tenant

    admin = TenantContext(tenant_id="t-tempprefs", user_id="user-1", permissions=["read", "write", "admin"])
    request = _Req(admin)

    # Flag off (default): honest not-enabled failure, zero side effects.
    with pytest.raises(NotFoundError):
        await routes.get_viewer_preferences(request)

    monkeypatch.setattr(
        settings_module.settings,
        "temporal_integrity",
        TemporalIntegrityConfig(
            enforcement_mode="off", canary_tenants=[], viewer_preferences_enabled=True
        ),
    )

    initial = await routes.get_viewer_preferences(request)
    assert initial.data["mode"] == "automatic"
    assert initial.meta["persisted"] is False
    assert initial.meta["resolution_order"][0] == "manual_preference"

    saved = await routes.put_viewer_preferences(
        request,
        ViewerTemporalPreferences(mode="manual", manual_time_zone="Asia/Kolkata"),
    )
    assert saved.data["manual_time_zone"] == "Asia/Kolkata"

    fetched = await routes.get_viewer_preferences(request)
    assert fetched.data["manual_time_zone"] == "Asia/Kolkata"
    assert fetched.meta["persisted"] is True

    v1 = await routes.put_tenant_defaults(
        request, TenantTemporalDefaults(business_time_zone="America/Chicago")
    )
    assert v1.data["version"] == 1
    v2 = await routes.put_tenant_defaults(
        request, TenantTemporalDefaults(business_time_zone="Europe/London")
    )
    assert v2.data["version"] == 2  # versioned additively, never overwritten silently

    current = await routes.get_tenant_defaults(request)
    assert current.data["business_time_zone"] == "Europe/London"
