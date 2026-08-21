"""Mobile config endpoint — GET /v1/mobile/config (M2, plan M2).

Covers: the typed config response (min/latest version, upgrade policy,
distribution profile, feature flags, service capabilities, externally-blocked
providers); the 404-when-disabled gate; app-version registration persisting and
feeding the per-version config decision; distribution-profile validation; and
snake_case wire fields.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from repositories.installation_repo import reset_installation_memory
from shared.common.common import NotFoundError
from services.mobile import routes as mobile_routes
from services.mobile.config import (
    EXTERNALLY_BLOCKED_PROVIDERS,
    LATEST_MOBILE_VERSION,
    MIN_SUPPORTED_MOBILE_VERSION,
    VERSION_FEATURE_FLAG_KEYS,
)
from services.mobile.routes import RegistrationRequest


def _run(coro):
    return asyncio.run(coro)


class _Tenant:
    tenant_id = "tenant-a"
    user_id = "user-1"

    def require_permission(self, permission):
        return None


def _req():
    return SimpleNamespace(state=SimpleNamespace(tenant=_Tenant()))


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    reset_installation_memory()
    monkeypatch.setattr(mobile_routes, "_require_enabled", lambda: None)
    yield
    reset_installation_memory()


def _reg(**over):
    base = dict(
        platform="ios",
        bundle_id="com.aether.app",
        environment="production",
        app_version="8.12.0",
        distribution_profile="app_store",
    )
    base.update(over)
    return RegistrationRequest(**base)


def _register(**over):
    return _run(mobile_routes.register_installation(_req(), _reg(**over))).data["installation"]


def test_config_returns_typed_response():
    _register(installation_id="dev-1", app_version="8.11.0", distribution_profile="testflight")
    cfg = _run(mobile_routes.get_mobile_config(_req(), installation_id="dev-1")).data

    assert cfg["app_kind"] == "aether"
    assert cfg["environment"] == "production"
    assert cfg["min_version"] == MIN_SUPPORTED_MOBILE_VERSION
    assert cfg["latest_version"] == LATEST_MOBILE_VERSION
    assert cfg["upgrade_policy"] == "suggested"  # 8.11.0 >= min and < latest
    assert cfg["distribution_profile"] == "testflight"

    # Feature flags all present, all default OFF.
    assert set(cfg["feature_flags"]) == set(VERSION_FEATURE_FLAG_KEYS)
    assert all(v is False for v in cfg["feature_flags"].values())

    # service_capabilities is a settings projection (contains the gateway key).
    assert "mobile_gateway" in cfg["service_capabilities"]
    assert isinstance(cfg["service_capabilities"]["mobile_gateway"], bool)

    # Honest externally-blocked provider list.
    assert set(cfg["externally_blocked_providers"]) == set(EXTERNALLY_BLOCKED_PROVIDERS)
    assert len(cfg["externally_blocked_providers"]) > 0


def test_config_404_when_disabled(monkeypatch):
    def _disabled():
        raise NotFoundError("mobile gateway (feature not enabled)")

    monkeypatch.setattr(mobile_routes, "_require_enabled", _disabled)
    with pytest.raises(NotFoundError):
        _run(mobile_routes.get_mobile_config(_req(), installation_id="dev-1"))


def test_config_404_when_installation_absent():
    with pytest.raises(NotFoundError):
        _run(mobile_routes.get_mobile_config(_req(), installation_id="nope"))


def test_app_version_registration_feeds_upgrade_policy():
    # Below the support floor -> required.
    _register(installation_id="old-dev", app_version="8.9.0", distribution_profile="testflight")
    cfg = _run(mobile_routes.get_mobile_config(_req(), installation_id="old-dev")).data
    assert cfg["upgrade_policy"] == "required"

    # At latest -> none.
    _register(installation_id="curr-dev", app_version="8.12.0", distribution_profile="app_store")
    cfg = _run(mobile_routes.get_mobile_config(_req(), installation_id="curr-dev")).data
    assert cfg["upgrade_policy"] == "none"

    # Registration persists the values on the installation row.
    row = _run(mobile_routes.get_installation(_req(), installation_id="curr-dev")).data
    assert row["app_version"] == "8.12.0"
    assert row["distribution_profile"] == "app_store"

    # Unknown app version is fail-safe (required), profile defaults to dev.
    _register(installation_id="no-ver", app_version=None, distribution_profile=None)
    cfg = _run(mobile_routes.get_mobile_config(_req(), installation_id="no-ver")).data
    assert cfg["upgrade_policy"] == "required"
    assert cfg["distribution_profile"] == "dev"


def test_distribution_profile_validation_rejects_unknown():
    with pytest.raises(ValidationError) as exc:
        _reg(distribution_profile="beta")
    assert "distribution_profile" in str(exc.value)

    # Case-sensitive snake_case: camel/upper-case is rejected.
    with pytest.raises(ValidationError) as exc:
        _reg(distribution_profile="TestFlight")
    assert "distribution_profile" in str(exc.value)

    # A valid android profile is accepted on the ios-registration schema.
    reg = _reg(distribution_profile="play_internal")
    assert reg.distribution_profile == "play_internal"


def test_config_wire_fields_are_snake_case():
    _register(installation_id="dev-1")
    cfg = _run(mobile_routes.get_mobile_config(_req(), installation_id="dev-1")).data
    assert set(cfg) == {
        "app_kind",
        "environment",
        "min_version",
        "latest_version",
        "upgrade_policy",
        "distribution_profile",
        "feature_flags",
        "service_capabilities",
        "externally_blocked_providers",
    }
