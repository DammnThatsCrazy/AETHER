"""The webhook-test endpoint migrated from the retired legacy notification router
into notification_intelligence, now with SSRF protection the legacy handler lacked.

Drives the handler directly (stub tenant + fake WebhookRepository), asserting the
new fail-closed SSRF behaviour and the tenant-isolation guards.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import repositories.repos as repos_mod
from services.notification_intelligence import routes as ni_routes
from shared.common.common import ForbiddenError, NotFoundError


def _run(coro):
    return asyncio.run(coro)


class _Tenant:
    tenant_id = "tenant-a"

    def require_permission(self, permission):
        return None


def _req():
    return SimpleNamespace(state=SimpleNamespace(tenant=_Tenant()))


def _fake_repo(webhook):
    class _Repo:
        async def find_by_id(self, wid):
            return webhook

    return lambda: _Repo()


def test_absent_webhook_404(monkeypatch):
    monkeypatch.setattr(repos_mod, "WebhookRepository", _fake_repo(None))
    with pytest.raises(NotFoundError):
        _run(ni_routes.test_webhook("wh-x", _req()))


def test_cross_tenant_forbidden(monkeypatch):
    monkeypatch.setattr(
        repos_mod, "WebhookRepository",
        _fake_repo({"tenant_id": "other", "url": "https://example.com/hook"}),
    )
    with pytest.raises(ForbiddenError):
        _run(ni_routes.test_webhook("wh-1", _req()))


def test_ssrf_loopback_blocked(monkeypatch):
    # A loopback target must fail closed BEFORE any request is made.
    monkeypatch.setattr(
        repos_mod, "WebhookRepository",
        _fake_repo({"tenant_id": "tenant-a", "url": "http://127.0.0.1:8080/hook"}),
    )
    out = _run(ni_routes.test_webhook("wh-1", _req()))
    assert out["data"]["success"] is False
    assert out["data"]["error"].startswith("blocked")


def test_private_range_blocked(monkeypatch):
    monkeypatch.setattr(
        repos_mod, "WebhookRepository",
        _fake_repo({"tenant_id": "tenant-a", "url": "http://10.0.0.5/hook"}),
    )
    out = _run(ni_routes.test_webhook("wh-1", _req()))
    assert out["data"]["success"] is False
    assert out["data"]["error"].startswith("blocked")
