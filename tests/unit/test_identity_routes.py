"""Unit tests for identity routes including the /suppress endpoint stub.

Tests cover:
- GET /v1/identity/health — returns operational metrics
- POST /v1/identity/suppress — stub returns 200 OK with suppressed status
- POST /v1/identity/suppress requires write permission
- suppress endpoint returns expected JSON shape

All tests run against in-memory mocks (AETHER_ENV=local).
No database, no Redis, no HTTP server required.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

# Stub out heavy optional dependencies so imports resolve without native libs
_STUBBED: list[str] = []
for _mod in (
    "jwt",
    "cryptography",
    "cryptography.hazmat",
    "cryptography.hazmat.primitives",
    "cryptography.hazmat.primitives.asymmetric",
    "cryptography.hazmat.primitives.asymmetric.ec",
    "cryptography.hazmat.bindings",
    "cryptography.hazmat.bindings._rust",
    "cryptography.hazmat._oid",
):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()
        _STUBBED.append(_mod)

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import os

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")


# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------


class FakeTenant:
    def __init__(self, tenant_id: str = "tenant-identity-1"):
        self.tenant_id = tenant_id
        self.user_id = "user-test-1"

    def require_permission(self, perm: str) -> None:  # noqa: D401
        return None


class PermissionedTenant(FakeTenant):
    def __init__(self, tenant_id: str = "tenant-identity-1", permissions=None):
        super().__init__(tenant_id)
        self.permissions = set(permissions or {"read"})

    def require_permission(self, perm: str) -> None:
        from shared.common.common import ForbiddenError

        if perm not in self.permissions and "admin" not in self.permissions:
            raise ForbiddenError(f"Missing permission: {perm}")


class FakeRequest:
    def __init__(self, tenant_id: str = "tenant-identity-1"):
        self.state = MagicMock()
        self.state.tenant = FakeTenant(tenant_id)


class PermissionedRequest(FakeRequest):
    def __init__(self, tenant_id: str = "tenant-identity-1", permissions=None):
        self.state = MagicMock()
        self.state.tenant = PermissionedTenant(tenant_id, permissions)


def _make_health_repo(tenant_id: str = "tenant-identity-1") -> AsyncMock:
    """Return a mock IdentityResolutionRepository for health checks."""
    repo = AsyncMock()
    repo.get_identity_health = AsyncMock(
        return_value={
            "total_subjects": 42,
            "total_aliases": 100,
            "total_clusters": 10,
            "open_conflicts": 2,
            "recent_merges": 5,
            "recent_splits": 1,
        }
    )
    return repo


# ---------------------------------------------------------------------------
# /suppress endpoint tests
# ---------------------------------------------------------------------------


def _make_suppress_body(
    identifier_type: str = "email_hash",
    identifier_hash: str = "abc123hash",
    reason: str = "test suppression",
    subject_id: str | None = None,
    expires_at: str | None = None,
) -> MagicMock:
    """Build a minimal IdentitySuppressRequest-like mock."""
    body = MagicMock()
    body.identifier_type = identifier_type
    body.identifier_hash = identifier_hash
    body.reason = reason
    body.subject_id = subject_id
    body.expires_at = expires_at
    return body


def _make_suppress_resolver(tenant_id: str = "tenant-identity-1") -> AsyncMock:
    """Return a mock resolver whose suppress_identifier returns a valid result dict."""
    resolver = AsyncMock()
    resolver.suppress_identifier = AsyncMock(
        return_value={
            "suppression_id": "sup-test-1",
            "tenant_id": tenant_id,
            "identifier_type": "email_hash",
            "reason": "test suppression",
            "revoked_alias_ids": [],
            "created_at": "2026-06-19T00:00:00+00:00",
            "expires_at": None,
        }
    )
    return resolver


@pytest.mark.asyncio
async def test_suppress_requires_write_permission():
    """suppress endpoint enforces write permission."""
    import unittest.mock as mock
    from services.identity import routes
    from shared.common.common import ForbiddenError

    read_only_request = PermissionedRequest(permissions={"read"})
    body = _make_suppress_body()
    resolver = _make_suppress_resolver()
    with mock.patch.object(routes, "_get_resolver", return_value=resolver):
        with pytest.raises(ForbiddenError):
            await routes.suppress_identifier(body, read_only_request)


@pytest.mark.asyncio
async def test_suppress_allowed_with_write_permission():
    """suppress endpoint succeeds when caller has write permission."""
    import unittest.mock as mock
    from services.identity import routes

    write_request = PermissionedRequest(permissions={"read", "write"})
    body = _make_suppress_body()
    resolver = _make_suppress_resolver()
    with mock.patch.object(routes, "_get_resolver", return_value=resolver):
        response = await routes.suppress_identifier(body, write_request)

    assert "data" in response
    assert response["data"]["suppression_id"] == "sup-test-1"


# ---------------------------------------------------------------------------
# /health endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_identity_health_returns_healthy_status(monkeypatch):
    """GET /v1/identity/health reports healthy with repo metrics."""
    from services.identity import routes

    repo = _make_health_repo()
    monkeypatch.setattr(routes, "_get_resolution_repo", lambda: repo)

    request = FakeRequest()
    response = await routes.identity_health(request)

    assert "data" in response
    data = response["data"]
    assert data["status"] == "healthy"
    assert data["resolver_enabled"] is True
    assert data["total_entities"] == 42
    assert data["total_aliases"] == 100


@pytest.mark.asyncio
async def test_identity_health_is_tenant_scoped(monkeypatch):
    """Health endpoint scopes data to the requesting tenant."""
    from services.identity import routes

    repo = _make_health_repo()
    monkeypatch.setattr(routes, "_get_resolution_repo", lambda: repo)

    request = FakeRequest(tenant_id="tenant-xyz")
    response = await routes.identity_health(request)

    assert response["data"]["tenant_id"] == "tenant-xyz"


# ---------------------------------------------------------------------------
# Cleanup stubbed modules
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def cleanup_stubs():
    yield
    for mod in _STUBBED:
        sys.modules.pop(mod, None)
