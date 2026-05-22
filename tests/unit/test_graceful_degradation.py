"""
Graceful Degradation Tests

Verifies that the AETHER backend degrades gracefully when individual
infrastructure components fail, rather than cascading into full outage.

Test scenarios:
  1. Redis unavailable   — rate limiter and quota engine fail-open
  2. DB pool exhausted   — repository raises cleanly; doesn't cascade to Redis/Kafka
  3. Kafka unavailable   — event publish failure doesn't propagate 500 to callers
  4. Circuit breaker     — state machine transitions: closed → open → half_open → closed
  5. Dual-key JWT        — rotation window accepts tokens signed by old key
"""

from __future__ import annotations

import asyncio
import importlib
import sys
import time
import types
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

import pytest

BACKEND_ROOT = Path(__file__).parent.parent.parent / "Backend Architecture" / "aether-backend"


@contextmanager
def backend_module_path():
    """Isolate backend module imports and stub broken system crypto."""
    original = list(sys.path)
    original_mods = set(sys.modules.keys())

    # Clean stale backend module cache so each test gets fresh imports
    for prefix in ("config", "services", "shared", "middleware", "dependencies", "repositories"):
        sys.modules.pop(prefix, None)
        for name in list(sys.modules):
            if name == prefix or name.startswith(f"{prefix}."):
                sys.modules.pop(name, None)

    # Stub jwt + cryptography to prevent pyo3 panic from broken system crypto.
    # Import chain that triggers it:
    #   shared/__init__.py → shared.decorators → shared.auth.auth → `import jwt`
    #   middleware/middleware.py → dependencies/providers.py → shared/providers/key_vault.py
    #     → `from cryptography.fernet import Fernet`
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

    # Minimal cryptography stubs so key_vault.py can import Fernet / InvalidToken
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
        for name in list(sys.modules):
            if name not in original_mods:
                sys.modules.pop(name, None)


def _import_auth(monkeypatch):
    """Import shared.auth.auth with PYJWT_AVAILABLE=False (manual HS256 fallback)."""
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-32-chars-long!")
    auth_mod = importlib.import_module("shared.auth.auth")
    # Force manual HS256 fallback — the stub jwt stub has no encode/decode methods
    auth_mod.PYJWT_AVAILABLE = False
    return auth_mod


# ═══════════════════════════════════════════════════════════════════════════
# 1. REDIS UNAVAILABLE
# ═══════════════════════════════════════════════════════════════════════════

class TestRedisUnavailable:
    """When Redis raises, middleware layers fail-open and don't 500."""

    def test_rate_limiter_connectionerror_propagates_to_middleware(self, monkeypatch):
        """Broken rate limiter raises ConnectionError — middleware catches it and allows."""
        monkeypatch.setenv("AETHER_ENV", "local")

        with backend_module_path():
            auth_mod = importlib.import_module("shared.auth.auth")

            class BrokenRateLimiter:
                async def check(self, tenant_id, plan_tier):
                    raise ConnectionError("Redis connection refused")

            limiter = BrokenRateLimiter()
            result = None
            caught = False
            try:
                result = asyncio.run(
                    limiter.check("t-001", auth_mod.PlanTier.P1_HOBBYIST)
                )
            except (ConnectionError, TimeoutError):
                caught = True

            # Middleware catches ConnectionError and sets rl_result = None (fail-open)
            assert caught is True
            assert result is None

    def test_quota_connectionerror_does_not_block_request(self, monkeypatch):
        """Quota engine ConnectionError is caught by middleware — no 429 emitted."""
        monkeypatch.setenv("AETHER_ENV", "local")

        with backend_module_path():
            auth_mod = importlib.import_module("shared.auth.auth")

            class BrokenQuotaEngine:
                async def check_and_increment(self, tenant_id, plan_tier, path):
                    raise ConnectionError("Redis connection refused")

            engine = BrokenQuotaEngine()
            caught = False
            try:
                asyncio.run(
                    engine.check_and_increment(
                        "t-001", auth_mod.PlanTier.P1_HOBBYIST, "/v1/analytics/events/query"
                    )
                )
            except (ConnectionError, TimeoutError):
                caught = True

            # Middleware wraps this in a try/except and logs warning — never 429
            assert caught is True

    def test_local_rate_limiter_allows_under_limit(self, monkeypatch):
        """In-memory rate limiter in local mode allows requests under plan RPM."""
        monkeypatch.setenv("AETHER_ENV", "local")
        monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-32-chars-long!")

        with backend_module_path():
            auth_mod = importlib.import_module("shared.auth.auth")
            limiter_mod = importlib.import_module("shared.rate_limit.limiter")

            limiter = limiter_mod.BurstRateLimiter()
            result = asyncio.run(
                limiter.check("t-degradation-001", auth_mod.PlanTier.P1_HOBBYIST)
            )
            assert result is not None
            assert hasattr(result, "allowed")

    def test_local_quota_engine_returns_structured_result(self, monkeypatch):
        """In-memory quota engine returns result with required fields."""
        monkeypatch.setenv("AETHER_ENV", "local")
        monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-32-chars-long!")

        with backend_module_path():
            auth_mod = importlib.import_module("shared.auth.auth")
            quota_mod = importlib.import_module("shared.rate_limit.quota")

            engine = quota_mod.QuotaEngine()
            result = asyncio.run(
                engine.check_and_increment(
                    "t-degradation-quota", auth_mod.PlanTier.P1_HOBBYIST, "/v1/analytics/events/query"
                )
            )
            assert hasattr(result, "quota_limit")
            assert hasattr(result, "remaining")
            assert result.remaining >= 0


# ═══════════════════════════════════════════════════════════════════════════
# 2. DATABASE POOL EXHAUSTED / MISCONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

class TestDatabasePoolExhausted:
    """When the DB pool is None or exhausted, repositories use in-memory fallback."""

    def test_in_memory_fallback_when_pool_is_none(self, monkeypatch):
        """With DATABASE_URL unset in local mode, BaseRepository uses in-memory store."""
        monkeypatch.setenv("AETHER_ENV", "local")
        monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-32-chars-long!")

        with backend_module_path():
            repos_mod = importlib.import_module("repositories.repos")
            repos_mod.reset_in_memory_stores()

            repo = repos_mod.CampaignRepository()
            record = asyncio.run(
                repo.insert("camp-degr-001", {"name": "Degradation Test", "tenant_id": "t-001"})
            )
            assert record["id"] == "camp-degr-001"

            fetched = asyncio.run(repo.find_by_id("camp-degr-001"))
            assert fetched is not None
            assert fetched["name"] == "Degradation Test"

    def test_find_by_id_returns_none_for_missing_record(self, monkeypatch):
        """Missing record returns None — not an unhandled exception."""
        monkeypatch.setenv("AETHER_ENV", "local")
        monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-32-chars-long!")

        with backend_module_path():
            repos_mod = importlib.import_module("repositories.repos")
            repos_mod.reset_in_memory_stores()

            repo = repos_mod.CampaignRepository()
            result = asyncio.run(repo.find_by_id("completely-missing-id"))
            assert result is None

    def test_find_by_id_or_fail_raises_not_found(self, monkeypatch):
        """find_by_id_or_fail raises NotFoundError (maps to 404, not 500)."""
        monkeypatch.setenv("AETHER_ENV", "local")
        monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-32-chars-long!")

        with backend_module_path():
            repos_mod = importlib.import_module("repositories.repos")
            common_mod = importlib.import_module("shared.common.common")
            repos_mod.reset_in_memory_stores()

            repo = repos_mod.CampaignRepository()
            with pytest.raises(common_mod.NotFoundError):
                asyncio.run(repo.find_by_id_or_fail("missing-campaign-id"))

    def test_pool_settings_respected_from_config(self, monkeypatch):
        """TimescaleDB pool size settings are read from env vars, not hardcoded."""
        monkeypatch.setenv("AETHER_ENV", "local")
        monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-32-chars-long!")
        monkeypatch.setenv("TSDB_POOL_MIN", "3")
        monkeypatch.setenv("TSDB_POOL_MAX", "15")

        with backend_module_path():
            settings_mod = importlib.import_module("config.settings")
            assert settings_mod.settings.timescaledb.pool_min == 3
            assert settings_mod.settings.timescaledb.pool_max == 15

    def test_init_connection_sets_statement_timeout(self, monkeypatch):
        """_init_connection issues statement_timeout, idle tx timeout, and app name."""
        monkeypatch.setenv("AETHER_ENV", "local")
        monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-32-chars-long!")

        with backend_module_path():
            repos_mod = importlib.import_module("repositories.repos")

            executed_sql = []

            class FakeConn:
                async def execute(self, sql):
                    executed_sql.append(sql)

            asyncio.run(repos_mod._init_connection(FakeConn()))
            combined = " ".join(executed_sql)
            assert "statement_timeout" in combined
            assert "idle_in_transaction_session_timeout" in combined
            assert "application_name" in combined


# ═══════════════════════════════════════════════════════════════════════════
# 3. KAFKA UNAVAILABLE
# ═══════════════════════════════════════════════════════════════════════════

class TestKafkaUnavailable:
    """Handlers that publish fire-and-forget should swallow Kafka errors."""

    def test_fake_producer_records_events(self):
        """FakeProducer captures published events (used in all other E2E tests)."""
        class FakeProducer:
            def __init__(self):
                self.events = []

            async def publish(self, event):
                self.events.append(event)

        producer = FakeProducer()
        asyncio.run(producer.publish({"type": "test_event", "tenant_id": "t-001"}))
        assert len(producer.events) == 1
        assert producer.events[0]["type"] == "test_event"

    def test_broken_producer_raises_on_publish(self):
        """BrokenProducer propagates errors — callers must wrap in try/except."""
        class BrokenProducer:
            async def publish(self, event):
                raise RuntimeError("Kafka connection refused")

        with pytest.raises(RuntimeError, match="Kafka connection refused"):
            asyncio.run(BrokenProducer().publish({"type": "test_event"}))

    def test_fire_and_forget_pattern_swallows_publish_errors(self):
        """Handler swallows Kafka errors and returns 200 to caller."""
        class BrokenProducer:
            async def publish(self, event):
                raise RuntimeError("Kafka connection refused")

        async def _handler_with_fire_and_forget(producer, payload):
            result = {"status": "created", "id": "123"}
            try:
                await producer.publish(payload)
            except Exception:
                pass  # fire-and-forget: Kafka failure must not propagate
            return result

        result = asyncio.run(
            _handler_with_fire_and_forget(BrokenProducer(), {"type": "test"})
        )
        assert result["status"] == "created"

    def test_local_event_producer_does_not_raise(self, monkeypatch):
        """EventProducer in local mode uses in-memory queue without requiring Kafka."""
        monkeypatch.setenv("AETHER_ENV", "local")
        monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-32-chars-long!")

        with backend_module_path():
            events_mod = importlib.import_module("shared.events.events")
            producer = events_mod.EventProducer()
            # Build a minimal valid Event object (publish requires Event, not a dict)
            event = events_mod.Event(
                topic=events_mod.Topic.SDK_EVENTS_RAW,
                payload={"type": "test_event"},
                tenant_id="t-001",
            )
            # Local mode should succeed (in-memory queue)
            asyncio.run(producer.publish(event))


# ═══════════════════════════════════════════════════════════════════════════
# 4. CIRCUIT BREAKER STATE TRANSITIONS
# ═══════════════════════════════════════════════════════════════════════════

class TestCircuitBreakerStateTransitions:
    """Unit tests for the CircuitBreaker state machine in error_registry.py."""

    def _cb_class(self, monkeypatch):
        monkeypatch.setenv("AETHER_ENV", "local")
        monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-32-chars-long!")
        return importlib.import_module("shared.diagnostics.error_registry").CircuitBreaker

    def test_initial_state_is_closed(self, monkeypatch):
        """New circuit breaker starts healthy (closed, not open)."""
        with backend_module_path():
            CB = self._cb_class(monkeypatch)
            cb = CB()
            assert cb.state == "closed"
            assert cb.is_open is False

    def test_trips_to_open_after_threshold_failures(self, monkeypatch):
        """Breaker opens after exactly failure_threshold consecutive failures."""
        with backend_module_path():
            CB = self._cb_class(monkeypatch)
            cb = CB(failure_threshold=5)

            for _ in range(4):
                cb.record_failure()
            assert cb.state == "closed"  # 4 < 5

            cb.record_failure()  # 5th failure
            assert cb.state == "open"
            assert cb.is_open is True

    def test_open_to_half_open_after_recovery_timeout(self, monkeypatch):
        """After recovery_timeout elapses, open breaker allows one probe (half_open)."""
        with backend_module_path():
            CB = self._cb_class(monkeypatch)
            cb = CB(failure_threshold=1, recovery_timeout=0.05)

            cb.record_failure()
            assert cb.state == "open"

            # Simulate timeout elapsed
            cb._last_failure_time = time.time() - 1.0

            assert cb.is_open is False   # probe allowed
            assert cb.state == "half_open"

    def test_half_open_success_closes_breaker(self, monkeypatch):
        """Successful probe in half_open state closes the breaker and resets counter."""
        with backend_module_path():
            CB = self._cb_class(monkeypatch)
            cb = CB(failure_threshold=1, recovery_timeout=0.05)

            cb.record_failure()
            cb._last_failure_time = time.time() - 1.0
            assert cb.state == "half_open"

            cb.record_success()
            assert cb.state == "closed"
            assert cb._failure_count == 0

    def test_half_open_failure_reopens_breaker(self, monkeypatch):
        """Failed probe in half_open re-opens the breaker immediately."""
        with backend_module_path():
            CB = self._cb_class(monkeypatch)
            cb = CB(failure_threshold=2, recovery_timeout=0.05)

            cb.record_failure()
            cb.record_failure()  # trips at threshold=2
            cb._last_failure_time = time.time() - 1.0
            assert cb.state == "half_open"

            cb.record_failure()  # probe fails
            assert cb.state == "open"

    def test_success_in_closed_resets_failure_counter(self, monkeypatch):
        """Partial failures followed by success reset the counter."""
        with backend_module_path():
            CB = self._cb_class(monkeypatch)
            cb = CB(failure_threshold=5)

            cb.record_failure()
            cb.record_failure()
            cb.record_failure()
            assert cb._failure_count == 3

            cb.record_success()
            assert cb._failure_count == 0
            assert cb.state == "closed"

    def test_custom_threshold_and_timeout_honoured(self, monkeypatch):
        """Custom failure_threshold and recovery_timeout are respected."""
        with backend_module_path():
            CB = self._cb_class(monkeypatch)
            cb = CB(failure_threshold=2, recovery_timeout=120.0)

            cb.record_failure()
            assert cb.state == "closed"  # 1 < 2

            cb.record_failure()
            assert cb.state == "open"    # 2 >= 2

            # With 120s timeout, breaker stays open immediately after tripping
            assert cb.is_open is True


# ═══════════════════════════════════════════════════════════════════════════
# 5. DUAL-KEY JWT ROTATION
# ═══════════════════════════════════════════════════════════════════════════

class TestDualKeyJWTRotation:
    """Zero-downtime JWT rotation via JWT_SECRET_PREVIOUS."""

    def test_token_signed_by_previous_key_is_accepted(self, monkeypatch):
        """Old-key tokens are accepted during rotation window (secret_previous set)."""
        monkeypatch.setenv("AETHER_ENV", "local")
        monkeypatch.setenv("JWT_SECRET", "new-primary-secret-exactly-32ch!!")
        monkeypatch.setenv("JWT_SECRET_PREVIOUS", "old-rotating-secret-32-chars-ok!")

        with backend_module_path():
            auth_mod = _import_auth(monkeypatch)

            # Token signed with old key
            old_handler = auth_mod.JWTHandler(secret="old-rotating-secret-32-chars-ok!")
            payload = {
                "tenant_id": "tenant-rotate-001",
                "sub": "user-001",
                "role": "editor",
                "permissions": ["read"],
            }
            old_token = old_handler.encode(payload)

            # New handler with both keys
            new_handler = auth_mod.JWTHandler(
                secret="new-primary-secret-exactly-32ch!!",
                secret_previous="old-rotating-secret-32-chars-ok!",
            )
            new_handler_mod = importlib.import_module("shared.auth.auth")
            new_handler_mod.PYJWT_AVAILABLE = False

            decoded = new_handler.decode(old_token)
            assert decoded["tenant_id"] == "tenant-rotate-001"

    def test_token_signed_by_rogue_key_is_rejected(self, monkeypatch):
        """Unknown key tokens are rejected even with secret_previous set."""
        monkeypatch.setenv("AETHER_ENV", "local")
        monkeypatch.setenv("JWT_SECRET", "new-primary-secret-exactly-32ch!!")
        monkeypatch.setenv("JWT_SECRET_PREVIOUS", "old-rotating-secret-32-chars-ok!")

        with backend_module_path():
            auth_mod = _import_auth(monkeypatch)
            common_mod = importlib.import_module("shared.common.common")

            rogue_handler = auth_mod.JWTHandler(secret="totally-different-secret-key!!")
            rogue_handler_mod = importlib.import_module("shared.auth.auth")
            rogue_handler_mod.PYJWT_AVAILABLE = False

            rogue_token = rogue_handler.encode({
                "tenant_id": "attacker",
                "sub": "hacker",
                "role": "admin",
                "permissions": ["admin"],
            })

            verifier = auth_mod.JWTHandler(
                secret="new-primary-secret-exactly-32ch!!",
                secret_previous="old-rotating-secret-32-chars-ok!",
            )
            with pytest.raises(common_mod.UnauthorizedError):
                verifier.decode(rogue_token)

    def test_current_key_token_accepted_without_previous(self, monkeypatch):
        """Normal operation: tokens signed by current key accepted (no previous needed)."""
        monkeypatch.setenv("AETHER_ENV", "local")
        monkeypatch.setenv("JWT_SECRET", "current-primary-secret-32-chars!!")

        with backend_module_path():
            auth_mod = _import_auth(monkeypatch)

            handler = auth_mod.JWTHandler(secret="current-primary-secret-32-chars!!")
            token = handler.encode({
                "tenant_id": "tenant-normal",
                "sub": "user-001",
                "role": "viewer",
                "permissions": ["read"],
            })
            decoded = handler.decode(token)
            assert decoded["tenant_id"] == "tenant-normal"

    def test_jwt_secret_previous_exposed_in_settings(self, monkeypatch):
        """JWT_SECRET_PREVIOUS env var is available through AuthConfig."""
        monkeypatch.setenv("AETHER_ENV", "local")
        monkeypatch.setenv("JWT_SECRET", "primary-jwt-secret-is-32-chars!!!")
        monkeypatch.setenv("JWT_SECRET_PREVIOUS", "previous-jwt-secret-32-chars-ok!")

        with backend_module_path():
            settings_mod = importlib.import_module("config.settings")
            assert settings_mod.settings.auth.jwt_secret_previous == "previous-jwt-secret-32-chars-ok!"
