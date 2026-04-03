"""
Tests for authentication and authorization middleware.

Covers:
  - API key validation (valid accepted, invalid rejected)
  - JWT token validation (valid, expired, malformed)
  - Permission checks (admin vs read-only vs write)
  - Missing Authorization header returns 401
"""

from __future__ import annotations

import importlib
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"


_BACKEND_PREFIXES = ("config", "services", "shared", "middleware", "dependencies", "repositories")


@contextmanager
def backend_module_path():
    """Temporarily put the backend root on sys.path and clean up afterwards."""
    original_path = list(sys.path)
    original_mods = set(sys.modules.keys())
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original_path
        # Remove any modules loaded during the context
        for name in list(sys.modules):
            if name not in original_mods:
                sys.modules.pop(name, None)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def auth_modules(monkeypatch):
    """Import auth and common modules with a safe local env."""
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret-for-unit-tests")

    with backend_module_path():
        common_mod = importlib.import_module("shared.common.common")
        auth_mod = importlib.import_module("shared.auth.auth")
        yield auth_mod, common_mod


@pytest.fixture()
def decorator_modules(monkeypatch):
    """Import the decorators module."""
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret-for-unit-tests")

    with backend_module_path():
        common_mod = importlib.import_module("shared.common.common")
        dec_mod = importlib.import_module("shared.decorators")
        yield dec_mod, common_mod


# ═══════════════════════════════════════════════════════════════════════════
# API KEY VALIDATION
# ═══════════════════════════════════════════════════════════════════════════


class TestAPIKeyValidation:
    """Tests for APIKeyValidator.validate (synchronous, local mode)."""

    def test_valid_stub_key_accepted(self, auth_modules):
        auth_mod, _ = auth_modules
        validator = auth_mod.APIKeyValidator()
        ctx = validator.validate("ak_test_123")
        assert ctx.tenant_id == "tenant_001"
        assert ctx.role == auth_mod.Role.EDITOR
        assert "read" in ctx.permissions
        assert "write" in ctx.permissions

    def test_invalid_key_rejected(self, auth_modules):
        auth_mod, common_mod = auth_modules
        validator = auth_mod.APIKeyValidator()
        with pytest.raises(common_mod.UnauthorizedError):
            validator.validate("ak_totally_invalid_key")

    def test_empty_key_rejected(self, auth_modules):
        auth_mod, common_mod = auth_modules
        validator = auth_mod.APIKeyValidator()
        with pytest.raises(common_mod.UnauthorizedError):
            validator.validate("")

    def test_stub_key_rejected_in_production(self, auth_modules, monkeypatch):
        auth_mod, common_mod = auth_modules
        monkeypatch.setenv("AETHER_ENV", "production")

        with backend_module_path():
            common_mod2 = importlib.import_module("shared.common.common")
            settings_mod = importlib.import_module("config.settings")
            auth_mod2 = importlib.import_module("shared.auth.auth")

            validator = auth_mod2.APIKeyValidator(
                environment=settings_mod.Environment.PRODUCTION
            )
            with pytest.raises(common_mod2.UnauthorizedError, match="Stub API keys"):
                validator.validate("ak_test_123")

    def test_api_key_hash_is_deterministic(self, auth_modules):
        auth_mod, _ = auth_modules
        h1 = auth_mod.APIKeyValidator.hash_key("some-key")
        h2 = auth_mod.APIKeyValidator.hash_key("some-key")
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex digest

    def test_different_keys_produce_different_hashes(self, auth_modules):
        auth_mod, _ = auth_modules
        h1 = auth_mod.APIKeyValidator.hash_key("key-a")
        h2 = auth_mod.APIKeyValidator.hash_key("key-b")
        assert h1 != h2


# ═══════════════════════════════════════════════════════════════════════════
# JWT TOKEN VALIDATION
# ═══════════════════════════════════════════════════════════════════════════


class TestJWTValidation:
    """Tests for JWTHandler encode/decode cycle."""

    def test_valid_token_roundtrip(self, auth_modules):
        auth_mod, _ = auth_modules
        handler = auth_mod.JWTHandler(secret="unit-test-secret")
        payload = {
            "tenant_id": "t-001",
            "sub": "user-42",
            "role": "editor",
            "permissions": ["read", "write"],
        }
        token = handler.encode(payload)
        decoded = handler.decode(token)

        assert decoded["tenant_id"] == "t-001"
        assert decoded["sub"] == "user-42"
        assert decoded["role"] == "editor"
        assert "exp" in decoded
        assert "iat" in decoded

    def test_expired_token_rejected(self, auth_modules):
        auth_mod, common_mod = auth_modules
        handler = auth_mod.JWTHandler(secret="unit-test-secret")
        payload = {
            "tenant_id": "t-001",
            "sub": "user-42",
            "role": "viewer",
            "exp": int(time.time()) - 3600,  # expired 1 hour ago
            "iat": int(time.time()) - 7200,
        }
        token = handler.encode(payload)

        with pytest.raises(common_mod.UnauthorizedError, match="[Ee]xpired|[Ii]nvalid"):
            handler.decode(token)

    def test_malformed_token_rejected(self, auth_modules):
        auth_mod, common_mod = auth_modules
        handler = auth_mod.JWTHandler(secret="unit-test-secret")

        with pytest.raises(common_mod.UnauthorizedError):
            handler.decode("not-a-jwt-at-all")

    def test_wrong_secret_rejected(self, auth_modules):
        auth_mod, common_mod = auth_modules
        handler_a = auth_mod.JWTHandler(secret="secret-a")
        handler_b = auth_mod.JWTHandler(secret="secret-b", allow_hs256_fallback=False)
        payload = {"tenant_id": "t-001", "sub": "u-1", "role": "viewer"}
        token = handler_a.encode(payload)

        with pytest.raises(common_mod.UnauthorizedError):
            handler_b.decode(token)

    def test_extract_context_from_payload(self, auth_modules):
        auth_mod, _ = auth_modules
        handler = auth_mod.JWTHandler(secret="unit-test-secret")
        payload = {
            "tenant_id": "t-xyz",
            "sub": "user-99",
            "role": "admin",
            "permissions": ["read", "write", "admin"],
        }
        token = handler.encode(payload)
        decoded = handler.decode(token)
        ctx = handler.extract_context(decoded)

        assert ctx.tenant_id == "t-xyz"
        assert ctx.user_id == "user-99"
        assert ctx.role == auth_mod.Role.ADMIN
        assert "admin" in ctx.permissions

    def test_token_with_three_dot_segments(self, auth_modules):
        """A token with only 2 segments (missing signature) should fail."""
        auth_mod, common_mod = auth_modules
        handler = auth_mod.JWTHandler(secret="unit-test-secret")

        with pytest.raises(common_mod.UnauthorizedError):
            handler.decode("header.payload")


# ═══════════════════════════════════════════════════════════════════════════
# PERMISSION CHECKS
# ═══════════════════════════════════════════════════════════════════════════


class TestPermissionChecks:
    """Tests for TenantContext permission enforcement."""

    def test_admin_has_all_permissions(self, auth_modules):
        auth_mod, _ = auth_modules
        ctx = auth_mod.TenantContext(
            tenant_id="t-001",
            role=auth_mod.Role.ADMIN,
            permissions=[],
        )
        assert ctx.has_permission("read") is True
        assert ctx.has_permission("write") is True
        assert ctx.has_permission("admin") is True
        assert ctx.has_permission("anything") is True

    def test_viewer_only_has_granted_permissions(self, auth_modules):
        auth_mod, _ = auth_modules
        ctx = auth_mod.TenantContext(
            tenant_id="t-001",
            role=auth_mod.Role.VIEWER,
            permissions=["read"],
        )
        assert ctx.has_permission("read") is True
        assert ctx.has_permission("write") is False
        assert ctx.has_permission("admin") is False

    def test_require_permission_raises_on_missing(self, auth_modules):
        auth_mod, common_mod = auth_modules
        ctx = auth_mod.TenantContext(
            tenant_id="t-001",
            role=auth_mod.Role.VIEWER,
            permissions=["read"],
        )
        with pytest.raises(common_mod.ForbiddenError, match="Missing permission"):
            ctx.require_permission("write")

    def test_require_permission_passes_for_admin(self, auth_modules):
        auth_mod, _ = auth_modules
        ctx = auth_mod.TenantContext(
            tenant_id="t-001",
            role=auth_mod.Role.ADMIN,
            permissions=[],
        )
        # Should not raise
        ctx.require_permission("write")
        ctx.require_permission("admin")
        ctx.require_permission("delete")

    def test_editor_with_write_permission(self, auth_modules):
        auth_mod, _ = auth_modules
        ctx = auth_mod.TenantContext(
            tenant_id="t-001",
            role=auth_mod.Role.EDITOR,
            permissions=["read", "write"],
        )
        assert ctx.has_permission("read") is True
        assert ctx.has_permission("write") is True
        assert ctx.has_permission("admin") is False

    def test_require_any_permission_passes_with_one_match(self, auth_modules):
        auth_mod, _ = auth_modules
        ctx = auth_mod.TenantContext(
            tenant_id="t-001",
            role=auth_mod.Role.VIEWER,
            permissions=["analytics"],
        )
        # Should not raise — "analytics" is in the list
        ctx.require_any_permission("read", "analytics")

    def test_require_any_permission_fails_with_no_match(self, auth_modules):
        auth_mod, common_mod = auth_modules
        ctx = auth_mod.TenantContext(
            tenant_id="t-001",
            role=auth_mod.Role.VIEWER,
            permissions=["analytics"],
        )
        with pytest.raises(common_mod.ForbiddenError, match="Requires one of"):
            ctx.require_any_permission("admin", "write")


# ═══════════════════════════════════════════════════════════════════════════
# MISSING AUTHORIZATION
# ═══════════════════════════════════════════════════════════════════════════


class TestMissingAuthorization:
    """Verify that the middleware auth function raises on missing headers."""

    def test_authenticate_async_raises_without_headers(self, monkeypatch):
        monkeypatch.setenv("AETHER_ENV", "local")
        monkeypatch.setenv("JWT_SECRET", "test-secret-for-unit-tests")

        with backend_module_path():
            common_mod = importlib.import_module("shared.common.common")
            auth_mod = importlib.import_module("shared.auth.auth")
            mw_mod = importlib.import_module("middleware.middleware")

            class FakeHeaders(dict):
                def get(self, key, default=None):
                    return super().get(key, default)

            class FakeRequest:
                headers = FakeHeaders()

            jwt_handler = auth_mod.JWTHandler(secret="test")
            api_key_validator = auth_mod.APIKeyValidator()

            import asyncio
            with pytest.raises(common_mod.UnauthorizedError, match="Missing"):
                asyncio.run(
                    mw_mod._authenticate_async(
                        FakeRequest(), jwt_handler, api_key_validator
                    )
                )
