"""Shared fakes and flag helpers for the one-person ops suite.

FakeTenant mirrors shared/auth TenantContext semantics: require_permission
raises ForbiddenError when the permission is missing (unlike the permissive
asserts in older suites) so worker-credential boundaries are actually tested.
"""

from __future__ import annotations

import dataclasses
import os
import uuid
from types import SimpleNamespace

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from config.settings import settings  # noqa: E402
from shared.common.common import ForbiddenError  # noqa: E402

OPERATOR_PERMISSIONS = {"agent:manage", "agent:dispatch", "agent:pause", "agent:approve", "admin"}
WORKER_PERMISSIONS = {"agent:heartbeat", "agent:run_update"}


class FakeTenant:
    def __init__(self, tenant_id: str, permissions: set[str] | None = None):
        self.tenant_id = tenant_id
        self.user_id = f"user-{tenant_id}"
        self.permissions = set(permissions) if permissions is not None else set(OPERATOR_PERMISSIONS)

    def require_permission(self, permission: str) -> None:
        if permission not in self.permissions and "admin" not in self.permissions:
            raise ForbiddenError(f"Missing permission: {permission}")

    def require_any_permission(self, *perms: str) -> None:
        if "admin" in self.permissions:
            return
        if not any(p in self.permissions for p in perms):
            raise ForbiddenError(f"Requires one of: {', '.join(perms)}")

    def has_permission(self, permission: str) -> bool:
        return "admin" in self.permissions or permission in self.permissions


class FakeRequest:
    def __init__(self, tenant_id: str, permissions: set[str] | None = None):
        self.state = SimpleNamespace(
            tenant=FakeTenant(tenant_id, permissions), request_id=f"req-{tenant_id}"
        )
        self.headers = {}


def tenant_id() -> str:
    return f"t-{uuid.uuid4().hex[:10]}"


def set_ops_flags(monkeypatch, **overrides) -> None:
    patched = dataclasses.replace(settings.one_person_ops, **overrides)
    monkeypatch.setattr(settings, "one_person_ops", patched)


@pytest.fixture()
def bridge_enabled(monkeypatch):
    set_ops_flags(monkeypatch, worker_bridge_enabled=True)


@pytest.fixture()
def review_commit_enabled(monkeypatch):
    set_ops_flags(monkeypatch, staged_mutation_review_enabled=True)


@pytest.fixture()
def ops_enabled(monkeypatch):
    set_ops_flags(monkeypatch, one_person_ops_enabled=True)
