"""Fail-closed, one-time staging first-admin bootstrap tests."""

from __future__ import annotations

from dataclasses import replace
import pytest
from fastapi import Request

from config.settings import Environment, settings
from repositories.repos import (
    APIKeyRepository,
    AdminRepository,
    FirstAdminBootstrapRepository,
    UserRepository,
    reset_in_memory_stores,
)
from services.auth import routes
from shared.common.common import ConflictError, UnauthorizedError


def _request(token: str) -> Request:
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/v1/auth/bootstrap/first-admin",
        "headers": [(b"x-aether-first-admin-bootstrap-token", token.encode())],
    })


@pytest.fixture(autouse=True)
def _bootstrap_settings(monkeypatch):
    reset_in_memory_stores()
    original_env = settings.env
    original_trust = settings.trust_plane
    token = "staging-bootstrap-token-" + "x" * 32
    monkeypatch.setattr(settings, "env", Environment.STAGING)
    monkeypatch.setattr(
        settings,
        "trust_plane",
        replace(
            original_trust,
            first_admin_bootstrap_enabled=True,
            first_admin_bootstrap_token=token,
            first_admin_bootstrap_email="devgroupolympus@gmail.com",
        ),
    )
    monkeypatch.setattr(routes, "_repo", AdminRepository())
    monkeypatch.setattr(routes, "_key_repo", APIKeyRepository())
    monkeypatch.setattr(routes, "_first_admin_bootstrap_repo", FirstAdminBootstrapRepository())
    yield token
    settings.env = original_env
    settings.trust_plane = original_trust
    reset_in_memory_stores()


@pytest.mark.asyncio
async def test_first_admin_bootstrap_mints_admin_key_once(_bootstrap_settings):
    body = routes.FirstAdminBootstrapRequest(name="Olympus staging", plan_tier="P1")
    response = await routes.bootstrap_first_admin(body, _request(_bootstrap_settings))
    data = response["data"]

    assert data["api_key"].startswith("ak_")
    assert "admin" in data["permissions"]
    tenants = await routes._repo.find_many()
    users = await UserRepository().find_many()
    keys = await routes._key_repo.find_many()
    assert len(tenants) == len(users) == len(keys) == 1
    assert keys[0]["permissions"] == data["permissions"]

    with pytest.raises(ConflictError):
        await routes.bootstrap_first_admin(body, _request(_bootstrap_settings))


@pytest.mark.asyncio
async def test_first_admin_bootstrap_rejects_wrong_token(_bootstrap_settings):
    body = routes.FirstAdminBootstrapRequest(name="Olympus staging", plan_tier="P1")
    with pytest.raises(UnauthorizedError):
        await routes.bootstrap_first_admin(body, _request("wrong-token"))

    assert await routes._repo.find_many() == []
    assert await routes._key_repo.find_many() == []
