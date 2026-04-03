"""
Tests for the cache abstraction layer.

Covers:
  - CacheKey format and namespacing conventions
  - _InMemoryBackend basic operations (get, set, delete)
  - TTL expiration (entries expire after their TTL)
  - CacheClient auto-connect and JSON helpers
  - delete_pattern, exists, incr operations
  - hash_query determinism
"""

from __future__ import annotations

import asyncio
import importlib
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"


@contextmanager
def backend_module_path():
    """Temporarily put the backend root on sys.path and clean up afterwards."""
    original = list(sys.path)
    for prefix in (
        "config", "services", "shared", "middleware", "dependencies", "repositories",
    ):
        sys.modules.pop(prefix, None)
        for name in list(sys.modules):
            if name == prefix or name.startswith(f"{prefix}."):
                sys.modules.pop(name, None)
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original
        for prefix in (
            "config", "services", "shared", "middleware", "dependencies", "repositories",
        ):
            sys.modules.pop(prefix, None)
            for name in list(sys.modules):
                if name == prefix or name.startswith(f"{prefix}."):
                    sys.modules.pop(name, None)


@pytest.fixture()
def cache_module(monkeypatch):
    """Import shared.cache.cache in local mode."""
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.delenv("REDIS_HOST", raising=False)

    with backend_module_path():
        mod = importlib.import_module("shared.cache.cache")
        importlib.reload(mod)
        yield mod


# ═══════════════════════════════════════════════════════════════════════════
# CACHE KEY FORMAT AND NAMESPACING
# ═══════════════════════════════════════════════════════════════════════════


class TestCacheKeyNamespacing:
    """Verify CacheKey static methods produce correctly namespaced keys."""

    def test_profile_key_format(self, cache_module):
        key = cache_module.CacheKey.profile("tenant-1", "user-42")
        assert key == "aether:identity:profile:tenant-1:user-42"

    def test_session_key_format(self, cache_module):
        key = cache_module.CacheKey.session("sess-abc123")
        assert key == "aether:session:sess-abc123"

    def test_prediction_key_format(self, cache_module):
        key = cache_module.CacheKey.prediction("churn_model", "entity-99")
        assert key == "aether:ml:prediction:churn_model:entity-99"

    def test_analytics_query_key_format(self, cache_module):
        key = cache_module.CacheKey.analytics_query("tenant-1", "abc123")
        assert key == "aether:analytics:query:tenant-1:abc123"

    def test_rate_limit_key_format(self, cache_module):
        key = cache_module.CacheKey.rate_limit("ak_test_key")
        assert key == "aether:ratelimit:ak_test_key"

    def test_consent_key_format(self, cache_module):
        key = cache_module.CacheKey.consent("tenant-1", "user-42")
        assert key == "aether:consent:tenant-1:user-42"

    def test_webhook_key_format(self, cache_module):
        key = cache_module.CacheKey.webhook("tenant-1", "wh-001")
        assert key == "aether:notification:webhook:tenant-1:wh-001"

    def test_custom_key_format(self, cache_module):
        key = cache_module.CacheKey.custom("my-special-key")
        assert key == "aether:custom:my-special-key"

    def test_api_key_cache_format(self, cache_module):
        key = cache_module.CacheKey.api_key("deadbeef1234")
        assert key == "aether:auth:apikey:deadbeef1234"

    def test_all_keys_start_with_aether_prefix(self, cache_module):
        """Every key method should produce a key starting with 'aether:'."""
        CK = cache_module.CacheKey
        keys = [
            CK.profile("t", "u"),
            CK.session("s"),
            CK.prediction("m", "e"),
            CK.analytics_query("t", "q"),
            CK.rate_limit("k"),
            CK.consent("t", "u"),
            CK.webhook("t", "w"),
            CK.custom("x"),
            CK.api_key("h"),
        ]
        for key in keys:
            assert key.startswith("aether:"), f"Key does not start with 'aether:': {key}"


# ═══════════════════════════════════════════════════════════════════════════
# CACHE KEY — HASH QUERY
# ═══════════════════════════════════════════════════════════════════════════


class TestCacheKeyHashQuery:
    """Verify hash_query is deterministic and appropriately truncated."""

    def test_hash_query_deterministic(self, cache_module):
        h1 = cache_module.CacheKey.hash_query("SELECT * FROM events WHERE tenant_id='t1'")
        h2 = cache_module.CacheKey.hash_query("SELECT * FROM events WHERE tenant_id='t1'")
        assert h1 == h2

    def test_hash_query_length(self, cache_module):
        h = cache_module.CacheKey.hash_query("some query")
        assert len(h) == 16  # truncated to first 16 hex chars

    def test_different_queries_different_hashes(self, cache_module):
        h1 = cache_module.CacheKey.hash_query("query A")
        h2 = cache_module.CacheKey.hash_query("query B")
        assert h1 != h2

    def test_hash_query_is_hex(self, cache_module):
        h = cache_module.CacheKey.hash_query("test")
        int(h, 16)  # should not raise — valid hex


# ═══════════════════════════════════════════════════════════════════════════
# TTL PRESETS
# ═══════════════════════════════════════════════════════════════════════════


class TestTTLPresets:
    """Verify TTL enum values are sensible durations in seconds."""

    def test_ttl_short(self, cache_module):
        assert cache_module.TTL.SHORT == 60

    def test_ttl_medium(self, cache_module):
        assert cache_module.TTL.MEDIUM == 300

    def test_ttl_long(self, cache_module):
        assert cache_module.TTL.LONG == 3600

    def test_ttl_session(self, cache_module):
        assert cache_module.TTL.SESSION == 1800

    def test_ttl_prediction(self, cache_module):
        assert cache_module.TTL.PREDICTION == 900

    def test_ttl_profile(self, cache_module):
        assert cache_module.TTL.PROFILE == 600

    def test_ttl_day(self, cache_module):
        assert cache_module.TTL.DAY == 86400

    def test_ttl_values_are_positive_integers(self, cache_module):
        for member in cache_module.TTL:
            assert isinstance(int(member), int)
            assert int(member) > 0


# ═══════════════════════════════════════════════════════════════════════════
# IN-MEMORY BACKEND — BASIC OPERATIONS
# ═══════════════════════════════════════════════════════════════════════════


class TestInMemoryBackendBasicOps:
    """Test _InMemoryBackend get/set/delete cycle."""

    def test_set_and_get(self, cache_module):
        backend = cache_module._InMemoryBackend()
        asyncio.run(backend.set("key1", "value1"))
        result = asyncio.run(backend.get("key1"))
        assert result == "value1"

    def test_get_missing_key_returns_none(self, cache_module):
        backend = cache_module._InMemoryBackend()
        result = asyncio.run(backend.get("nonexistent"))
        assert result is None

    def test_delete_removes_key(self, cache_module):
        backend = cache_module._InMemoryBackend()
        asyncio.run(backend.set("key1", "value1"))
        asyncio.run(backend.delete("key1"))
        result = asyncio.run(backend.get("key1"))
        assert result is None

    def test_delete_nonexistent_key_does_not_raise(self, cache_module):
        backend = cache_module._InMemoryBackend()
        asyncio.run(backend.delete("nonexistent"))  # should not raise

    def test_overwrite_existing_key(self, cache_module):
        backend = cache_module._InMemoryBackend()
        asyncio.run(backend.set("key1", "old"))
        asyncio.run(backend.set("key1", "new"))
        result = asyncio.run(backend.get("key1"))
        assert result == "new"

    def test_exists_returns_true_for_set_key(self, cache_module):
        backend = cache_module._InMemoryBackend()
        asyncio.run(backend.set("key1", "val"))
        assert asyncio.run(backend.exists("key1")) is True

    def test_exists_returns_false_for_missing_key(self, cache_module):
        backend = cache_module._InMemoryBackend()
        assert asyncio.run(backend.exists("missing")) is False

    def test_ping_returns_true(self, cache_module):
        backend = cache_module._InMemoryBackend()
        assert asyncio.run(backend.ping()) is True

    def test_close_clears_store(self, cache_module):
        backend = cache_module._InMemoryBackend()
        asyncio.run(backend.set("key1", "val"))
        asyncio.run(backend.close())
        result = asyncio.run(backend.get("key1"))
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════
# IN-MEMORY BACKEND — TTL EXPIRATION
# ═══════════════════════════════════════════════════════════════════════════


class TestInMemoryBackendTTL:
    """Verify that entries expire after their TTL."""

    def test_entry_expires_after_ttl(self, cache_module):
        backend = cache_module._InMemoryBackend()
        # Set with a TTL of 1 second
        asyncio.run(backend.set("ephemeral", "data", ttl=1))

        # Immediately available
        assert asyncio.run(backend.get("ephemeral")) == "data"

        # Simulate time passing by manipulating the stored expiry
        key_entry = backend._store["ephemeral"]
        backend._store["ephemeral"] = (key_entry[0], time.time() - 1)

        # Now should be expired
        result = asyncio.run(backend.get("ephemeral"))
        assert result is None

    def test_entry_with_zero_ttl_does_not_expire(self, cache_module):
        backend = cache_module._InMemoryBackend()
        asyncio.run(backend.set("permanent", "data", ttl=0))
        result = asyncio.run(backend.get("permanent"))
        assert result == "data"

    def test_exists_returns_false_for_expired_key(self, cache_module):
        backend = cache_module._InMemoryBackend()
        asyncio.run(backend.set("temp", "val", ttl=1))

        # Expire it manually
        entry = backend._store["temp"]
        backend._store["temp"] = (entry[0], time.time() - 1)

        assert asyncio.run(backend.exists("temp")) is False

    def test_expired_key_is_removed_from_store(self, cache_module):
        backend = cache_module._InMemoryBackend()
        asyncio.run(backend.set("temp", "val", ttl=1))

        # Expire it
        entry = backend._store["temp"]
        backend._store["temp"] = (entry[0], time.time() - 1)

        # Access triggers cleanup
        asyncio.run(backend.get("temp"))
        assert "temp" not in backend._store


# ═══════════════════════════════════════════════════════════════════════════
# IN-MEMORY BACKEND — DELETE PATTERN
# ═══════════════════════════════════════════════════════════════════════════


class TestInMemoryBackendDeletePattern:
    """Verify delete_pattern removes matching keys."""

    def test_delete_pattern_removes_matching_keys(self, cache_module):
        backend = cache_module._InMemoryBackend()
        asyncio.run(backend.set("aether:cache:a", "1"))
        asyncio.run(backend.set("aether:cache:b", "2"))
        asyncio.run(backend.set("aether:other:c", "3"))

        deleted = asyncio.run(backend.delete_pattern("aether:cache:*"))
        assert deleted == 2
        assert asyncio.run(backend.get("aether:cache:a")) is None
        assert asyncio.run(backend.get("aether:cache:b")) is None
        assert asyncio.run(backend.get("aether:other:c")) == "3"

    def test_delete_pattern_returns_zero_for_no_match(self, cache_module):
        backend = cache_module._InMemoryBackend()
        asyncio.run(backend.set("aether:x", "1"))
        deleted = asyncio.run(backend.delete_pattern("nonexistent:*"))
        assert deleted == 0


# ═══════════════════════════════════════════════════════════════════════════
# IN-MEMORY BACKEND — INCREMENT
# ═══════════════════════════════════════════════════════════════════════════


class TestInMemoryBackendIncr:
    """Verify the incr (atomic increment) operation."""

    def test_incr_creates_key_with_value_1(self, cache_module):
        backend = cache_module._InMemoryBackend()
        result = asyncio.run(backend.incr("counter"))
        assert result == 1

    def test_incr_increments_existing(self, cache_module):
        backend = cache_module._InMemoryBackend()
        asyncio.run(backend.incr("counter"))
        asyncio.run(backend.incr("counter"))
        result = asyncio.run(backend.incr("counter"))
        assert result == 3

    def test_incr_resets_expired_key(self, cache_module):
        backend = cache_module._InMemoryBackend()
        asyncio.run(backend.incr("counter", ttl=1))

        # Expire it
        entry = backend._store["counter"]
        backend._store["counter"] = (entry[0], time.time() - 1)

        # Incr should treat it as new
        result = asyncio.run(backend.incr("counter", ttl=60))
        assert result == 1


# ═══════════════════════════════════════════════════════════════════════════
# CACHE CLIENT — AUTO-CONNECT AND JSON HELPERS
# ═══════════════════════════════════════════════════════════════════════════


class TestCacheClientOperations:
    """Test CacheClient high-level operations in local (in-memory) mode."""

    def test_auto_connect_on_first_get(self, cache_module):
        client = cache_module.CacheClient()
        # Should not raise — auto-connects in local mode
        result = asyncio.run(client.get("nonexistent"))
        assert result is None
        assert client.mode == "in-memory"

    def test_set_and_get_string(self, cache_module):
        client = cache_module.CacheClient()
        asyncio.run(client.connect())
        asyncio.run(client.set("hello", "world"))
        result = asyncio.run(client.get("hello"))
        assert result == "world"

    def test_set_json_and_get_json(self, cache_module):
        client = cache_module.CacheClient()
        asyncio.run(client.connect())
        data = {"users": [1, 2, 3], "count": 3}
        asyncio.run(client.set_json("my-data", data))
        result = asyncio.run(client.get_json("my-data"))
        assert result == data

    def test_get_json_returns_none_for_missing(self, cache_module):
        client = cache_module.CacheClient()
        asyncio.run(client.connect())
        result = asyncio.run(client.get_json("missing"))
        assert result is None

    def test_delete_key(self, cache_module):
        client = cache_module.CacheClient()
        asyncio.run(client.connect())
        asyncio.run(client.set("temp", "val"))
        asyncio.run(client.delete("temp"))
        assert asyncio.run(client.get("temp")) is None

    def test_delete_pattern(self, cache_module):
        client = cache_module.CacheClient()
        asyncio.run(client.connect())
        asyncio.run(client.set("prefix:a", "1"))
        asyncio.run(client.set("prefix:b", "2"))
        asyncio.run(client.set("other:c", "3"))

        deleted = asyncio.run(client.delete_pattern("prefix:*"))
        assert deleted == 2
        assert asyncio.run(client.get("other:c")) == "3"

    def test_exists(self, cache_module):
        client = cache_module.CacheClient()
        asyncio.run(client.connect())
        asyncio.run(client.set("present", "yes"))
        assert asyncio.run(client.exists("present")) is True
        assert asyncio.run(client.exists("absent")) is False

    def test_incr(self, cache_module):
        client = cache_module.CacheClient()
        asyncio.run(client.connect())
        v1 = asyncio.run(client.incr("ctr"))
        v2 = asyncio.run(client.incr("ctr"))
        assert v1 == 1
        assert v2 == 2

    def test_health_check_returns_true_when_connected(self, cache_module):
        client = cache_module.CacheClient()
        asyncio.run(client.connect())
        assert asyncio.run(client.health_check()) is True

    def test_health_check_returns_false_before_connect(self, cache_module):
        client = cache_module.CacheClient()
        assert asyncio.run(client.health_check()) is False

    def test_close_marks_disconnected(self, cache_module):
        client = cache_module.CacheClient()
        asyncio.run(client.connect())
        asyncio.run(client.close())
        assert client._connected is False

    def test_mode_is_inmemory_in_local_env(self, cache_module):
        client = cache_module.CacheClient()
        asyncio.run(client.connect())
        assert client.mode == "in-memory"


# ═══════════════════════════════════════════════════════════════════════════
# FEATURE STORE OPERATIONS (via CacheClient)
# ═══════════════════════════════════════════════════════════════════════════


class TestFeatureStoreViaCache:
    """Test the pattern used by ml_serving for feature caching."""

    def test_store_and_retrieve_features(self, cache_module):
        client = cache_module.CacheClient()
        asyncio.run(client.connect())

        entity_id = "entity-42"
        cache_key = cache_module.CacheKey.custom(f"features:{entity_id}")
        features_payload = {
            "features": {"page_views": 100, "session_duration": 320.5},
            "computed_at": "2026-04-03T00:00:00+00:00",
        }
        asyncio.run(client.set_json(cache_key, features_payload, ttl=cache_module.TTL.PREDICTION))

        cached = asyncio.run(client.get_json(cache_key))
        assert cached is not None
        assert cached["features"]["page_views"] == 100
        assert cached["features"]["session_duration"] == 320.5
        assert cached["computed_at"] == "2026-04-03T00:00:00+00:00"

    def test_feature_cache_miss_returns_none(self, cache_module):
        client = cache_module.CacheClient()
        asyncio.run(client.connect())

        cache_key = cache_module.CacheKey.custom("features:nonexistent-entity")
        cached = asyncio.run(client.get_json(cache_key))
        assert cached is None

    def test_feature_cache_key_uses_correct_namespace(self, cache_module):
        entity_id = "ent-99"
        key = cache_module.CacheKey.custom(f"features:{entity_id}")
        assert key == "aether:custom:features:ent-99"

    def test_prediction_cache_roundtrip(self, cache_module):
        """Store and retrieve a prediction result using the prediction key."""
        client = cache_module.CacheClient()
        asyncio.run(client.connect())

        key = cache_module.CacheKey.prediction("churn_v2", "user-123")
        prediction = {"score": 0.87, "label": "high_risk"}
        asyncio.run(client.set_json(key, prediction, ttl=cache_module.TTL.PREDICTION))

        result = asyncio.run(client.get_json(key))
        assert result["score"] == 0.87
        assert result["label"] == "high_risk"
