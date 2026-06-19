"""Unit tests for identity resolution routes.

Tests run against in-memory mocks (AETHER_ENV=local).
No database, no Redis, no HTTP server required.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

# Stub heavy optional dependencies before imports
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
# Helpers
# ---------------------------------------------------------------------------


class FakeTenant:
    def __init__(self, tenant_id: str = "tenant-test-1"):
        self.tenant_id = tenant_id
        self.user_id = "user-test-1"

    def require_permission(self, perm: str) -> None:
        return None


class PermissionedTenant(FakeTenant):
    def __init__(self, tenant_id: str = "tenant-test-1", permissions=None):
        super().__init__(tenant_id)
        self.permissions = set(permissions or {"read"})

    def require_permission(self, perm: str) -> None:
        from shared.common.common import ForbiddenError
        if perm not in self.permissions and "admin" not in self.permissions:
            raise ForbiddenError(f"Missing permission: {perm}")


class FakeRequest:
    def __init__(self, tenant_id: str = "tenant-test-1"):
        self.state = MagicMock()
        self.state.tenant = FakeTenant(tenant_id)


class PermissionedRequest(FakeRequest):
    def __init__(self, tenant_id: str = "tenant-test-1", permissions=None):
        self.state = MagicMock()
        self.state.tenant = PermissionedTenant(tenant_id, permissions)


def _make_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.ping = AsyncMock(return_value=True)
    repo.get_identity_health = AsyncMock(return_value={
        "total_subjects": 42,
        "total_aliases": 100,
        "total_clusters": 10,
        "open_conflicts": 2,
        "recent_merges": 5,
        "recent_splits": 1,
        "blocked_consent": 0,
        "blocked_cross_tenant": 0,
        "blocked_fingerprint_only": 0,
    })
    repo.get_suppressions = AsyncMock(return_value=[])
    return repo


def _make_suppress_body():
    from services.identity.schemas import IdentitySuppressRequest
    return IdentitySuppressRequest(
        identifier_type="email_hash",
        identifier_hash="abc123",
        reason="user_request",
    )


def _make_resolver() -> AsyncMock:
    resolver = AsyncMock()
    resolver.suppress_identifier = AsyncMock(return_value={
        "suppression_id": "sup-1",
        "tenant_id": "tenant-test-1",
        "identifier_type": "email_hash",
        "reason": "user_request",
        "revoked_alias_ids": [],
        "created_at": "2026-06-19T00:00:00Z",
        "expires_at": None,
    })
    resolver.unsuppress_identifier = AsyncMock(return_value={
        "revoked": True,
        "suppression_id": "sup-1",
        "revoked_by": "user-test-1",
        "error": None,
    })
    return resolver


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_identity_health_returns_healthy_status(monkeypatch):
    """GET /v1/identity/health reports healthy when db ping succeeds."""
    from services.identity import routes

    repo = _make_repo()
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
async def test_identity_health_degraded_when_ping_fails(monkeypatch):
    """Health endpoint reports degraded when db ping returns False."""
    from services.identity import routes

    repo = _make_repo()
    repo.ping = AsyncMock(return_value=False)
    monkeypatch.setattr(routes, "_get_resolution_repo", lambda: repo)

    request = FakeRequest()
    response = await routes.identity_health(request)

    assert response["data"]["status"] == "degraded"
    assert response["data"]["resolver_enabled"] is False


@pytest.mark.asyncio
async def test_identity_health_is_tenant_scoped(monkeypatch):
    """Health endpoint scopes response to the requesting tenant."""
    from services.identity import routes

    repo = _make_repo()
    monkeypatch.setattr(routes, "_get_resolution_repo", lambda: repo)

    request = FakeRequest(tenant_id="tenant-xyz")
    response = await routes.identity_health(request)

    assert response["data"]["tenant_id"] == "tenant-xyz"


# ---------------------------------------------------------------------------
# Suppress endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suppress_identifier_returns_suppression_id(monkeypatch):
    """POST /v1/identity/suppress returns suppression_id."""
    from services.identity import routes

    resolver = _make_resolver()
    monkeypatch.setattr(routes, "_get_resolver", lambda: resolver)

    request = FakeRequest()
    body = _make_suppress_body()
    response = await routes.suppress_identifier(body, request)

    assert "data" in response
    assert response["data"]["suppression_id"] == "sup-1"
    assert response["data"]["identifier_type"] == "email_hash"


@pytest.mark.asyncio
async def test_suppress_requires_write_permission():
    """POST /v1/identity/suppress enforces write permission."""
    from services.identity import routes
    from shared.common.common import ForbiddenError

    read_only = PermissionedRequest(permissions={"read"})
    body = _make_suppress_body()
    with pytest.raises(ForbiddenError):
        await routes.suppress_identifier(body, read_only)


@pytest.mark.asyncio
async def test_suppress_allowed_with_write_permission(monkeypatch):
    """POST /v1/identity/suppress succeeds with write permission."""
    from services.identity import routes

    resolver = _make_resolver()
    monkeypatch.setattr(routes, "_get_resolver", lambda: resolver)

    write_request = PermissionedRequest(permissions={"read", "write"})
    body = _make_suppress_body()
    response = await routes.suppress_identifier(body, write_request)

    assert response["data"]["suppression_id"] == "sup-1"


# ---------------------------------------------------------------------------
# Unsuppress endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unsuppress_identifier_returns_revoked(monkeypatch):
    """DELETE /v1/identity/suppress/{id} returns revoked=True."""
    from services.identity import routes

    resolver = _make_resolver()
    monkeypatch.setattr(routes, "_get_resolver", lambda: resolver)

    request = FakeRequest()
    response = await routes.unsuppress_identifier("sup-1", request)

    assert response["data"]["revoked"] is True
    assert response["data"]["suppression_id"] == "sup-1"


@pytest.mark.asyncio
async def test_unsuppress_requires_write_permission():
    """DELETE /v1/identity/suppress/{id} enforces write permission."""
    from services.identity import routes
    from shared.common.common import ForbiddenError

    read_only = PermissionedRequest(permissions={"read"})
    with pytest.raises(ForbiddenError):
        await routes.unsuppress_identifier("sup-1", read_only)


# ---------------------------------------------------------------------------
# List suppressions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_suppressions_returns_empty_list(monkeypatch):
    """GET /v1/identity/suppressions returns suppression list."""
    from services.identity import routes

    repo = _make_repo()
    monkeypatch.setattr(routes, "_get_resolution_repo", lambda: repo)

    request = FakeRequest()
    response = await routes.list_suppressions(request, limit=50)

    assert "data" in response
    assert "suppressions" in response["data"]
    assert isinstance(response["data"]["suppressions"], list)


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def cleanup_stubs():
    yield
    for mod in _STUBBED:
        sys.modules.pop(mod, None)
