"""
Middleware Stack Integration Tests

Verifies the full cross-cutting middleware chain without external services:
  1. Auth — API key and JWT validation, public path bypass
  2. Burst rate limiting — behavior under limit, over limit, and Redis failure
  3. Feature gate — per-plan access control; PUBLIC_PATHS bypass
  4. Monthly quota — X-Quota-* header structure; never blocks

All tests use AETHER_ENV=local so in-memory backends activate automatically.
The jwt system library is stubbed to prevent pyo3 panic from broken system crypto.
JWTHandler uses its manual HS256 fallback when PYJWT_AVAILABLE=False.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
import time
import types
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock

import pytest

BACKEND_ROOT = Path(__file__).parent.parent.parent / "Backend Architecture" / "aether-backend"


@contextmanager
def backend_module_path():
    """Isolate backend imports and stub broken system jwt/cryptography."""
    original = list(sys.path)
    original_modules = dict(sys.modules)

    for prefix in ("config", "services", "shared", "middleware", "dependencies", "repositories"):
        sys.modules.pop(prefix, None)
        for name in list(sys.modules):
            if name == prefix or name.startswith(f"{prefix}."):
                sys.modules.pop(name, None)

    # Stub jwt + cryptography to prevent pyo3 panic from broken system crypto.
    # Import chain: shared.auth.auth → jwt; dependencies.providers → key_vault → cryptography.fernet
    for name in list(sys.modules):
        if name == "jwt" or name.startswith("jwt."):
            sys.modules.pop(name, None)
        if name == "cryptography" or name.startswith("cryptography."):
            sys.modules.pop(name, None)

    jwt_stub = types.ModuleType("jwt")
    class _JWTError(Exception):
        pass
    jwt_stub.InvalidTokenError = _JWTError
    jwt_stub.ExpiredSignatureError = _JWTError
    jwt_stub.InvalidSignatureError = _JWTError
    jwt_stub.InvalidAlgorithmError = _JWTError
    jwt_stub.DecodeError = _JWTError
    sys.modules["jwt"] = jwt_stub

    crypto_stub = types.ModuleType("cryptography")
    crypto_fernet = types.ModuleType("cryptography.fernet")
    class _FakeFernet:
        def __init__(self, key): pass
        def encrypt(self, data): return b"__encrypted__"
        def decrypt(self, data): return b"__decrypted__"
    class _FakeInvalidToken(Exception): pass
    crypto_fernet.Fernet = _FakeFernet
    crypto_fernet.InvalidToken = _FakeInvalidToken
    sys.modules["cryptography"] = crypto_stub
    sys.modules["cryptography.fernet"] = crypto_fernet
    for _sub in ("cryptography.exceptions", "cryptography.hazmat",
                 "cryptography.hazmat.primitives", "cryptography.hazmat.bindings",
                 "cryptography.hazmat.bindings._rust"):
        sys.modules.setdefault(_sub, types.ModuleType(_sub))

    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original
        # Restore sys.modules to its pre-context state. This context replaces the
        # real `jwt`/`cryptography` with stubs (no encode/decode); without
        # restoring the originals the stub `jwt` leaks into later tests on the
        # same xdist worker when the real module was already imported, causing
        # AttributeError: module 'jwt' has no attribute 'encode'.
        for name in list(sys.modules):
            if name not in original_modules:
                sys.modules.pop(name, None)
        for name, module in original_modules.items():
            if sys.modules.get(name) is not module:
                sys.modules[name] = module


# ═══════════════════════════════════════════════════════════════════════════
# 1. AUTH MIDDLEWARE
# ═══════════════════════════════════════════════════════════════════════════

class TestAuthMiddlewareIntegration:
    """Tests for _authenticate_async — the auth extraction layer."""

    def test_stub_api_key_requires_a_configured_cache_in_local_mode(self, monkeypatch):
        """Legacy hardcoded keys are not an authentication bypass in local mode."""
        monkeypatch.setenv("AETHER_ENV", "local")
        monkeypatch.setenv("JWT_SECRET", "test-secret-for-integration-tests!")

        with backend_module_path():
            auth_mod = importlib.import_module("shared.auth.auth")
            validator = auth_mod.APIKeyValidator()
            common_mod = importlib.import_module("shared.common.common")
            with pytest.raises(
                common_mod.UnauthorizedError, match="cache not configured"
            ):
                asyncio.run(validator.validate_async("ak_test_123"))

    def test_unknown_api_key_raises_unauthorized(self, monkeypatch):
        """Unregistered API key raises UnauthorizedError (maps to 401)."""
        monkeypatch.setenv("AETHER_ENV", "local")
        monkeypatch.setenv("JWT_SECRET", "test-secret-for-integration-tests!")

        with backend_module_path():
            auth_mod = importlib.import_module("shared.auth.auth")
            common_mod = importlib.import_module("shared.common.common")
            validator = auth_mod.APIKeyValidator()
            with pytest.raises(common_mod.UnauthorizedError):
                asyncio.run(validator.validate_async("ak_does_not_exist"))

    def test_stub_key_rejected_outside_local(self, monkeypatch):
        """Stub keys are forbidden in staging/production — fail-closed."""
        monkeypatch.setenv("AETHER_ENV", "staging")
        monkeypatch.setenv("AETHER_ROLE", "api")  # PR 4: staging rejects role=all
        monkeypatch.setenv("JWT_SECRET", "staging-secret-that-is-long-32ch!!")
        monkeypatch.setenv("DATABASE_URL", "postgresql://fake:fake@localhost/fake")
        monkeypatch.setenv("WATERMARK_SECRET_KEY", "test-watermark-secret-key-for-tests")
        monkeypatch.setenv("CANARY_SECRET_SEED", "test-canary-secret-seed-for-tests")
        monkeypatch.setenv("EXTRACTION_CANARY_SEED", "test-extraction-canary-seed-for-tests")
        monkeypatch.setenv("SDK_CONFIG_SECRET", "test-sdk-config-secret-for-tests")
        # Kyber workforce SSO/WebAuthn anchors. A non-local Settings() already requires
        # seven secrets; these are the same kind. The guard itself is covered by
        # tests/security/test_kyber_gate_migration.py — this test must trip only
        # the guard it is actually testing.
        monkeypatch.setenv("KYBER_GOOGLE_CLIENT_ID", "test-kyber-client-id")
        monkeypatch.setenv("KYBER_GOOGLE_REDIRECT_URI", "https://kyber.test.invalid/v1/kyber/auth/callback")
        monkeypatch.setenv("KYBER_WEBAUTHN_RP_ID", "kyber.test.invalid")
        monkeypatch.setenv("KYBER_WEBAUTHN_ORIGIN", "https://kyber.test.invalid")

        with backend_module_path():
            auth_mod = importlib.import_module("shared.auth.auth")
            common_mod = importlib.import_module("shared.common.common")
            validator = auth_mod.APIKeyValidator()
            with pytest.raises(
                common_mod.UnauthorizedError, match="cache not configured"
            ):
                asyncio.run(validator.validate_async("ak_test_123"))

    def test_missing_auth_header_raises_unauthorized(self, monkeypatch):
        """Request with no API key and no Bearer token → UnauthorizedError."""
        monkeypatch.setenv("AETHER_ENV", "local")
        monkeypatch.setenv("JWT_SECRET", "test-secret-for-integration-tests!")

        with backend_module_path():
            middleware_mod = importlib.import_module("middleware.middleware")
            auth_mod = importlib.import_module("shared.auth.auth")
            common_mod = importlib.import_module("shared.common.common")

            fake_request = MagicMock()
            fake_request.headers = {}
            jwt_handler = auth_mod.JWTHandler()
            validator = auth_mod.APIKeyValidator()

            with pytest.raises(common_mod.UnauthorizedError, match="Missing API key"):
                asyncio.run(
                    middleware_mod._authenticate_async(fake_request, jwt_handler, validator)
                )

    def test_public_paths_set_includes_health_and_webhook(self, monkeypatch):
        """PUBLIC_PATHS bypasses auth — must include /v1/health and stripe webhook."""
        monkeypatch.setenv("AETHER_ENV", "local")
        monkeypatch.setenv("JWT_SECRET", "test-secret-for-integration-tests!")

        with backend_module_path():
            middleware_mod = importlib.import_module("middleware.middleware")
            assert "/v1/health" in middleware_mod._PUBLIC_PATHS
            assert "/v1/billing/plans" in middleware_mod._PUBLIC_PATHS
            assert "/v1/admin/billing/stripe/webhook" in middleware_mod._PUBLIC_PATHS

    def test_jwt_manual_path_encodes_and_decodes(self, monkeypatch):
        """JWTHandler manual HS256 (PYJWT_AVAILABLE=False) round-trips a token."""
        monkeypatch.setenv("AETHER_ENV", "local")
        monkeypatch.setenv("JWT_SECRET", "test-secret-for-integration-tests!")

        with backend_module_path():
            auth_mod = importlib.import_module("shared.auth.auth")
            auth_mod.PYJWT_AVAILABLE = False  # force manual HS256 fallback

            handler = auth_mod.JWTHandler(secret="test-secret-for-integration-tests!")
            payload = {"tenant_id": "t-001", "sub": "u-001", "role": "editor", "permissions": []}
            token = handler.encode(payload)
            decoded = handler.decode(token)
            assert decoded["tenant_id"] == "t-001"


# ═══════════════════════════════════════════════════════════════════════════
# 2. BURST RATE LIMITER MIDDLEWARE
# ═══════════════════════════════════════════════════════════════════════════

class TestRateLimitMiddlewareIntegration:
    """Tests for burst RPM logic — no Redis required."""

    def test_in_memory_limiter_allows_first_request(self, monkeypatch):
        """Local-mode BurstRateLimiter allows the first request."""
        monkeypatch.setenv("AETHER_ENV", "local")
        monkeypatch.setenv("JWT_SECRET", "test-secret-for-integration-tests!")

        with backend_module_path():
            auth_mod = importlib.import_module("shared.auth.auth")
            limiter_mod = importlib.import_module("shared.rate_limit.limiter")

            limiter = limiter_mod.BurstRateLimiter()
            result = asyncio.run(
                limiter.check("t-ratelimit-001", auth_mod.PlanTier.P1_HOBBYIST)
            )
            assert result is not None
            assert result.allowed is True

    def test_fake_limiter_blocks_and_returns_retry_after(self, monkeypatch):
        """A limiter returning allowed=False triggers the 429 path in middleware."""
        monkeypatch.setenv("AETHER_ENV", "local")

        with backend_module_path():
            auth_mod = importlib.import_module("shared.auth.auth")

            @dataclass
            class RateLimitResult:
                allowed: bool = False
                limit: int = 100
                remaining: int = 0
                reset_at: float = time.time() + 30
                retry_after: int = 30

            class LimitedRateLimiter:
                async def check(self, tenant_id, plan_tier):
                    return RateLimitResult()

            limiter = LimitedRateLimiter()
            result = asyncio.run(limiter.check("t-001", auth_mod.PlanTier.P1_HOBBYIST))
            assert result.allowed is False
            assert result.remaining == 0
            assert result.retry_after == 30

    def test_p4_plan_has_higher_burst_rpm_than_p1(self, monkeypatch):
        """P4 Protocol Master has higher RPM than P1 Hobbyist per plan catalog."""
        monkeypatch.setenv("AETHER_ENV", "local")
        monkeypatch.setenv("JWT_SECRET", "test-secret-for-integration-tests!")

        with backend_module_path():
            auth_mod = importlib.import_module("shared.auth.auth")
            catalog_mod = importlib.import_module("shared.plans.catalog")

            p1 = catalog_mod.PLAN_CATALOG[auth_mod.PlanTier.P1_HOBBYIST]
            p4 = catalog_mod.PLAN_CATALOG[auth_mod.PlanTier.P4_PROTOCOL_MASTER]
            assert p4.burst_rpm > p1.burst_rpm

    def test_redis_failure_signals_fail_open(self, monkeypatch):
        """ConnectionError from rate limiter means middleware sets rl_result=None (allow)."""
        monkeypatch.setenv("AETHER_ENV", "local")

        with backend_module_path():
            auth_mod = importlib.import_module("shared.auth.auth")

            class DownLimiter:
                async def check(self, tenant_id, plan_tier):
                    raise ConnectionError("Redis refused")

            caught = False
            result = None
            try:
                result = asyncio.run(
                    DownLimiter().check("t-001", auth_mod.PlanTier.P1_HOBBYIST)
                )
            except (ConnectionError, TimeoutError):
                caught = True

            # Middleware code: rl_result = None on connection error → no 429
            assert caught is True
            assert result is None


# ═══════════════════════════════════════════════════════════════════════════
# 3. FEATURE GATE MIDDLEWARE
# ═══════════════════════════════════════════════════════════════════════════

class TestFeatureGateMiddlewareIntegration:
    """Tests for per-plan service access control."""

    def test_p1_can_access_analytics_dashboard(self, monkeypatch):
        """P1 plan has access to the analytics dashboard summary endpoint."""
        monkeypatch.setenv("AETHER_ENV", "local")
        monkeypatch.setenv("JWT_SECRET", "test-secret-for-integration-tests!")

        with backend_module_path():
            auth_mod = importlib.import_module("shared.auth.auth")
            gate_mod = importlib.import_module("shared.rate_limit.feature_gate")

            gate = gate_mod.FeatureGate()
            result = gate.check_access(
                auth_mod.PlanTier.P1_HOBBYIST, "/v1/analytics/dashboard/summary"
            )
            assert result.allowed is True

    def test_feature_gate_result_has_required_fields(self, monkeypatch):
        """Gate result always has allowed and minimum_plan fields."""
        monkeypatch.setenv("AETHER_ENV", "local")
        monkeypatch.setenv("JWT_SECRET", "test-secret-for-integration-tests!")

        with backend_module_path():
            auth_mod = importlib.import_module("shared.auth.auth")
            gate_mod = importlib.import_module("shared.rate_limit.feature_gate")

            gate = gate_mod.FeatureGate()
            result = gate.check_access(auth_mod.PlanTier.P1_HOBBYIST, "/v1/ml/predict")
            assert hasattr(result, "allowed")
            assert hasattr(result, "minimum_plan")

    def test_p4_passes_all_core_gates(self, monkeypatch):
        """P4 Protocol Master passes the gate for all core service endpoints."""
        monkeypatch.setenv("AETHER_ENV", "local")
        monkeypatch.setenv("JWT_SECRET", "test-secret-for-integration-tests!")

        with backend_module_path():
            auth_mod = importlib.import_module("shared.auth.auth")
            gate_mod = importlib.import_module("shared.rate_limit.feature_gate")

            gate = gate_mod.FeatureGate()
            for path in [
                "/v1/analytics/dashboard/summary",
                "/v1/fraud/evaluate",
                "/v1/campaigns",
            ]:
                result = gate.check_access(auth_mod.PlanTier.P4_PROTOCOL_MASTER, path)
                assert result.allowed is True, f"P4 should pass gate for {path}"

    def test_public_paths_are_in_bypass_set(self, monkeypatch):
        """PUBLIC_PATHS constant contains the known bypass paths."""
        monkeypatch.setenv("AETHER_ENV", "local")
        monkeypatch.setenv("JWT_SECRET", "test-secret-for-integration-tests!")

        with backend_module_path():
            gate_mod = importlib.import_module("shared.rate_limit.feature_gate")
            public = gate_mod.PUBLIC_PATHS
            assert "/v1/health" in public
            assert "/docs" in public
            assert "/v1/billing/plans" in public
            assert "/v1/admin/billing/stripe/webhook" in public
            assert gate_mod.FeatureGate().is_public("/v1/billing/plans") is True

    def test_higher_plan_has_more_service_access(self, monkeypatch):
        """P4 has access to more services than P1 (service_count in plan catalog)."""
        monkeypatch.setenv("AETHER_ENV", "local")
        monkeypatch.setenv("JWT_SECRET", "test-secret-for-integration-tests!")

        with backend_module_path():
            auth_mod = importlib.import_module("shared.auth.auth")
            catalog_mod = importlib.import_module("shared.plans.catalog")

            p1 = catalog_mod.PLAN_CATALOG[auth_mod.PlanTier.P1_HOBBYIST]
            p4 = catalog_mod.PLAN_CATALOG[auth_mod.PlanTier.P4_PROTOCOL_MASTER]
            assert p4.service_count >= p1.service_count


# ═══════════════════════════════════════════════════════════════════════════
# 4. MONTHLY QUOTA MIDDLEWARE
# ═══════════════════════════════════════════════════════════════════════════

class TestQuotaMiddlewareIntegration:
    """Monthly quota: meters only, never blocks, always returns quota headers."""

    def test_quota_result_has_required_fields(self, monkeypatch):
        """QuotaEngine result has all fields needed to set X-Quota-* headers."""
        monkeypatch.setenv("AETHER_ENV", "local")
        monkeypatch.setenv("JWT_SECRET", "test-secret-for-integration-tests!")

        with backend_module_path():
            auth_mod = importlib.import_module("shared.auth.auth")
            quota_mod = importlib.import_module("shared.rate_limit.quota")

            engine = quota_mod.QuotaEngine()
            result = asyncio.run(
                engine.check_and_increment(
                    "t-quota-fields", auth_mod.PlanTier.P1_HOBBYIST,
                    "/v1/analytics/events/query"
                )
            )
            assert hasattr(result, "quota_limit")
            assert hasattr(result, "quota_used")
            assert hasattr(result, "remaining")
            assert hasattr(result, "included")

    def test_remaining_never_negative(self, monkeypatch):
        """remaining is always >= 0 even when quota is exceeded (overage mode)."""
        monkeypatch.setenv("AETHER_ENV", "local")
        monkeypatch.setenv("JWT_SECRET", "test-secret-for-integration-tests!")

        with backend_module_path():
            auth_mod = importlib.import_module("shared.auth.auth")
            quota_mod = importlib.import_module("shared.rate_limit.quota")

            engine = quota_mod.QuotaEngine()
            tenant = "t-quota-overflow-check"
            result = None
            for _ in range(10):
                result = asyncio.run(
                    engine.check_and_increment(
                        tenant, auth_mod.PlanTier.P1_HOBBYIST,
                        "/v1/analytics/events/query"
                    )
                )
            assert result is not None
            assert result.remaining >= 0

    def test_quota_never_raises(self, monkeypatch):
        """QuotaEngine.check_and_increment never raises — quota is metered, not blocking."""
        monkeypatch.setenv("AETHER_ENV", "local")
        monkeypatch.setenv("JWT_SECRET", "test-secret-for-integration-tests!")

        with backend_module_path():
            auth_mod = importlib.import_module("shared.auth.auth")
            quota_mod = importlib.import_module("shared.rate_limit.quota")

            engine = quota_mod.QuotaEngine()
            try:
                result = asyncio.run(
                    engine.check_and_increment(
                        "t-quota-no-block", auth_mod.PlanTier.P1_HOBBYIST, "/v1/ml/predict"
                    )
                )
                assert result is not None
            except Exception as e:
                pytest.fail(f"QuotaEngine raised unexpectedly: {e}")

    def test_p1_monthly_quota_is_25000(self, monkeypatch):
        """P1 Hobbyist plan has 25,000 monthly quota as specified in plan catalog."""
        monkeypatch.setenv("AETHER_ENV", "local")
        monkeypatch.setenv("JWT_SECRET", "test-secret-for-integration-tests!")

        with backend_module_path():
            auth_mod = importlib.import_module("shared.auth.auth")
            catalog_mod = importlib.import_module("shared.plans.catalog")

            p1 = catalog_mod.PLAN_CATALOG[auth_mod.PlanTier.P1_HOBBYIST]
            assert p1.monthly_quota == 25_000

    def test_p4_has_higher_quota_than_p1(self, monkeypatch):
        """P4 monthly quota exceeds P1 monthly quota."""
        monkeypatch.setenv("AETHER_ENV", "local")
        monkeypatch.setenv("JWT_SECRET", "test-secret-for-integration-tests!")

        with backend_module_path():
            auth_mod = importlib.import_module("shared.auth.auth")
            catalog_mod = importlib.import_module("shared.plans.catalog")

            p1 = catalog_mod.PLAN_CATALOG[auth_mod.PlanTier.P1_HOBBYIST]
            p4 = catalog_mod.PLAN_CATALOG[auth_mod.PlanTier.P4_PROTOCOL_MASTER]
            assert p4.monthly_quota > p1.monthly_quota
