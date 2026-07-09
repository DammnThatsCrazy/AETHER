"""Fixtures for the AI economics suite (FakeTenant/FakeRequest direct-call pattern)."""

from __future__ import annotations

import dataclasses
import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from config.settings import settings  # noqa: E402


class FakeTenant:
    def __init__(self, tenant_id: str, permissions: set[str] | None = None):
        self.tenant_id = tenant_id
        self.user_id = f"user-{tenant_id}"
        self.permissions = permissions if permissions is not None else {"read", "write", "admin"}

    def require_permission(self, permission: str) -> None:
        assert permission in self.permissions or "admin" in self.permissions

    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions


class FakeRequest:
    def __init__(self, tenant_id: str, headers: dict | None = None, body: bytes = b""):
        self.state = SimpleNamespace(tenant=FakeTenant(tenant_id), request_id="req-1")
        self.headers = headers or {}
        self._body = body

    async def body(self) -> bytes:
        return self._body


@pytest.fixture()
def ai_flags_on(monkeypatch):
    """Enable every AI economics flag for the test."""
    patched = dataclasses.replace(
        settings.ai_economics,
        enabled=True,
        execution_facts_enabled=True,
        economics_enabled=True,
        recommendations_enabled=True,
        kyber_enabled=True,
    )
    monkeypatch.setattr(settings, "ai_economics", patched)
    return patched


@pytest.fixture()
def ai_flags_off(monkeypatch):
    """Force every AI economics flag off for the test."""
    patched = dataclasses.replace(
        settings.ai_economics,
        enabled=False,
        execution_facts_enabled=False,
        economics_enabled=False,
        recommendations_enabled=False,
        kyber_enabled=False,
    )
    monkeypatch.setattr(settings, "ai_economics", patched)
    return patched
