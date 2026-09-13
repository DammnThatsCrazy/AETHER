"""
Aether ML — Unit Tests: Features, Edge Runtime, Serving
Tests for feature registry, streaming pipeline, edge inference, batch predictor, and cache.
"""

import json
from pathlib import Path
import tempfile

from features.registry import (
    FeatureRegistry, FeatureDefinition, FeatureGroup, FeatureValueType,
    FeatureSource, FeatureGranularity, create_default_registry,
)
from features.streaming import (
    SessionFeatureProcessor, IdentityFeatureProcessor,
    WalletFeatureProcessor, WindowedAggregator,
)
from edge.runtime import (
    EdgePrediction,
    PredictionCache,
)
from serving.src.cache import (
    CacheKeyBuilder, DEFAULT_MODEL_TTLS,
)
from common.src.base import ModelType


# =============================================================================
# FEATURE REGISTRY TESTS
# =============================================================================

class TestFeatureRegistry:
    """Test feature registry operations."""

    def test_register_and_retrieve(self):
        registry = FeatureRegistry()
        feat = FeatureDefinition(
            name="test_feature",
            display_name="Test Feature",
            description="A test feature",
            value_type=FeatureValueType.FLOAT,
            source=FeatureSource.AGGREGATED,
            granularity=FeatureGranularity.SESSION,
        )
        registry.register_feature(feat)

        retrieved = registry.get_feature("test_feature")
        assert retrieved is not None
        assert retrieved.name == "test_feature"


    def test_default_registry_path_avoids_repo_root_artifacts(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("AETHER_FEATURE_REGISTRY_PATH", raising=False)
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))

        registry = FeatureRegistry()
        feat = FeatureDefinition(
            name="cache_safe_feature",
            display_name="Cache Safe Feature",
            description="Ensures default registry writes outside the repo root",
            value_type=FeatureValueType.FLOAT,
            source=FeatureSource.AGGREGATED,
            granularity=FeatureGranularity.SESSION,
        )
        registry.register_feature(feat)

        assert Path(registry.registry_path) == tmp_path / "cache" / "aether" / "feature_registry.json"
        assert not (tmp_path / "feature_registry.json").exists()

    def test_register_group(self):
        registry = FeatureRegistry()
        group = FeatureGroup(
            name="test_group",
            description="Test group",
            entity_key="session_id",
            granularity=FeatureGranularity.SESSION,
            features=[
                FeatureDefinition(
                    name="f1", display_name="F1", description="Feature 1",
                    value_type=FeatureValueType.FLOAT, source=FeatureSource.RAW_EVENT,
                    granularity=FeatureGranularity.SESSION,
                ),
                FeatureDefinition(
                    name="f2", display_name="F2", description="Feature 2",
                    value_type=FeatureValueType.INT, source=FeatureSource.AGGREGATED,
                    granularity=FeatureGranularity.SESSION,
                ),
            ],
        )
        registry.register_group(group)

        assert registry.get_feature("f1") is not None
        assert registry.get_feature("f2") is not None
        assert "test_group" in registry.list_all_groups()

    def test_search_features(self):
        registry = create_default_registry()

        # Search by tag
        bot_features = registry.search_features(tags=["bot_detection"])
        assert len(bot_features) > 0

        # Search by granularity
        session_features = registry.search_features(granularity=FeatureGranularity.SESSION)
        assert len(session_features) > 0

        # Search by text query
        velocity_features = registry.search_features(query="velocity")
        assert len(velocity_features) > 0

    def test_model_feature_mapping(self):
        registry = create_default_registry()

        churn_features = registry.get_model_features("churn_prediction")
        assert len(churn_features) > 0

    def test_downstream_models(self):
        registry = create_default_registry()

        models = registry.get_downstream_models("mouse_velocity_mean")
        assert "intent_prediction" in models

    def test_feature_validation(self):
        registry = FeatureRegistry()
        feat = FeatureDefinition(
            name="bounded",
            display_name="Bounded Feature",
            description="Feature with bounds",
            value_type=FeatureValueType.FLOAT,
            source=FeatureSource.DERIVED,
            granularity=FeatureGranularity.SESSION,
            min_value=0.0,
            max_value=1.0,
            nullable=False,
        )
        registry.register_feature(feat)

        valid, msg = feat.validate_value(0.5)
        assert valid

        valid, msg = feat.validate_value(1.5)
        assert not valid

        valid, msg = feat.validate_value(None)
        assert not valid

    def test_deprecation(self):
        registry = create_default_registry()
        registry.register_model_features("test_model", ["mouse_velocity_mean"])

        registry.deprecate_feature("mouse_velocity_mean", "Replaced by v2")

        feat = registry.get_feature("mouse_velocity_mean")
        assert feat is not None
        assert feat.is_deprecated

    def test_save_registry(self):
        registry = create_default_registry()

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "registry.json"
            registry.save(path)

            assert path.exists()
            with open(path) as f:
                data = json.load(f)
            assert "features" in data
            assert "model_feature_map" in data

    def test_stats(self):
        registry = create_default_registry()
        stats = registry.stats()

        assert stats["total_features"] > 0
        assert stats["feature_groups"] > 0
        assert stats["registered_models"] > 0


# =============================================================================
# STREAMING FEATURE PROCESSOR TESTS
# =============================================================================

class TestSessionFeatureProcessor:
    """Test real-time session feature computation."""

    def test_process_page_event(self):
        proc = SessionFeatureProcessor()
        event = {
            "type": "page",
            "timestamp": "2025-03-01T10:00:00Z",
            "sessionId": "sess_001",
            "anonymousId": "anon_001",
            "properties": {"url": "https://example.com/page1"},
        }

        features = proc.process_event(event)
        assert features["page_count"] == 1
        assert features["event_count"] == 1

    def test_accumulate_events(self):
        proc = SessionFeatureProcessor()
        events = [
            {"type": "page", "timestamp": "2025-03-01T10:00:00Z", "sessionId": "s1", "anonymousId": "a1", "properties": {"url": "/p1"}},
            {"type": "track", "timestamp": "2025-03-01T10:00:10Z", "sessionId": "s1", "anonymousId": "a1", "properties": {"event": "click"}},
            {"type": "track", "timestamp": "2025-03-01T10:00:15Z", "sessionId": "s1", "anonymousId": "a1", "properties": {"event": "scroll_depth", "depth": 75}},
            {"type": "page", "timestamp": "2025-03-01T10:00:30Z", "sessionId": "s1", "anonymousId": "a1", "properties": {"url": "/p2"}},
        ]

        for e in events:
            features = proc.process_event(e)

        assert features["event_count"] == 4
        assert features["page_count"] == 2
        assert features["click_count"] == 1
        assert features["max_scroll_depth"] == 0.75

    def test_multiple_sessions(self):
        proc = SessionFeatureProcessor()

        for i in range(5):
            proc.process_event({
                "type": "page", "timestamp": "2025-03-01T10:00:00Z",
                "sessionId": f"s{i}", "anonymousId": f"a{i}",
                "properties": {"url": f"/p{i}"},
            })

        assert len(proc._sessions) == 5


class TestIdentityFeatureProcessor:
    """Test real-time identity feature computation."""

    def test_process_events(self):
        proc = IdentityFeatureProcessor()

        for i in range(5):
            features = proc.process_event({
                "type": "page", "timestamp": "2025-03-01T10:00:00Z",
                "sessionId": f"s{i % 2}", "anonymousId": "anon_1",
                "properties": {},
            })

        assert features["total_sessions"] == 2
        assert features["total_events"] == 5


class TestWalletFeatureProcessor:
    """Test Web3 wallet feature computation."""

    def test_process_wallet_event(self):
        proc = WalletFeatureProcessor()

        features = proc.process_event({
            "type": "transaction",
            "timestamp": "2025-03-01T10:00:00Z",
            "sessionId": "s1",
            "anonymousId": "a1",
            "properties": {
                "address": "0xABC123",
                "chainId": 1,
                "to": "0xDEF456",
                "gasUsed": 21000,
            },
        })

        assert features is not None
        assert features["tx_count"] == 1
        assert features["unique_chains"] == 1

    def test_ignore_non_wallet_events(self):
        proc = WalletFeatureProcessor()

        result = proc.process_event({
            "type": "page",
            "timestamp": "2025-03-01T10:00:00Z",
            "sessionId": "s1",
            "anonymousId": "a1",
            "properties": {"url": "/home"},
        })

        assert result is None


class TestWindowedAggregator:
    """Test windowed aggregation."""

    def test_basic_aggregation(self):
        agg = WindowedAggregator(window_seconds=3600)

        for i in range(10):
            agg.update("entity_1", "clicks", float(i))

        features = agg.get_features("entity_1")
        assert "clicks_count" in features
        assert features["clicks_count"] == 10
        assert features["clicks_sum"] == 45

    def test_expire_stale(self):
        agg = WindowedAggregator()
        agg.update("old_entity", "metric", 1.0)
        # Manually set old timestamp
        agg._states["old_entity"]["metric"].last_updated = 0

        expired = agg.expire_stale(max_idle_seconds=1)
        assert expired == 1
        assert agg.entity_count == 0


# =============================================================================
# EDGE RUNTIME TESTS
# =============================================================================

class TestPredictionCache:
    """Test edge prediction cache."""

    def test_cache_put_get(self):
        cache = PredictionCache(max_size=100, ttl_seconds=60)

        features = {"f1": 1.0, "f2": 2.0}
        key = PredictionCache.hash_features(features)

        cache.put(key, {"prediction": 0.75})
        result = cache.get(key)

        assert result is not None
        assert result["prediction"] == 0.75

    def test_cache_miss(self):
        cache = PredictionCache()
        result = cache.get("nonexistent")
        assert result is None

    def test_cache_eviction(self):
        cache = PredictionCache(max_size=3)

        for i in range(5):
            cache.put(str(i), {"v": i})

        assert cache.size <= 3

    def test_deterministic_hashing(self):
        features = {"b": 2.0, "a": 1.0}
        h1 = PredictionCache.hash_features(features)
        h2 = PredictionCache.hash_features({"a": 1.0, "b": 2.0})
        assert h1 == h2


# =============================================================================
# CACHE KEY BUILDER TESTS
# =============================================================================

class TestCacheKeyBuilder:
    """Test server-side cache key building."""

    def test_build_key(self):
        key = CacheKeyBuilder.build(
            "churn_prediction", "1.0.0",
            {"f1": 1.0, "f2": 2.0},
        )
        assert key.startswith("aether:pred:")
        assert "churn_prediction" in key

    def test_deterministic_keys(self):
        k1 = CacheKeyBuilder.build("bot_detection", "1.0.0", {"a": 1, "b": 2})
        k2 = CacheKeyBuilder.build("bot_detection", "1.0.0", {"b": 2, "a": 1})
        assert k1 == k2

    def test_different_versions_different_keys(self):
        k1 = CacheKeyBuilder.build("bot_detection", "1.0.0", {"a": 1})
        k2 = CacheKeyBuilder.build("bot_detection", "2.0.0", {"a": 1})
        assert k1 != k2

    def test_entity_key(self):
        key = CacheKeyBuilder.build_entity(
            "churn_prediction", "1.0.0", "user", "user_123",
        )
        assert "user_123" in key

    def test_invalidation_pattern(self):
        pattern = CacheKeyBuilder.invalidation_pattern("churn_prediction")
        assert pattern.endswith("*")

    def test_default_model_ttls(self):
        assert DEFAULT_MODEL_TTLS[ModelType.BOT_DETECTION.value] == 60
        assert DEFAULT_MODEL_TTLS[ModelType.CHURN_PREDICTION.value] == 86400


# =============================================================================
# EDGE MODEL PREDICTION TESTS
# =============================================================================

class TestEdgePrediction:
    """Test EdgePrediction dataclass."""

    def test_valid_prediction(self):
        pred = EdgePrediction(
            outputs={"score": 0.85},
            latency_ms=5.2,
            model_format="onnx",
        )
        assert pred.is_valid
        assert pred.error is None

    def test_slow_prediction_invalid(self):
        pred = EdgePrediction(
            outputs={"score": 0.5},
            latency_ms=250,
            model_format="onnx",
        )
        assert not pred.is_valid

    def test_error_prediction(self):
        pred = EdgePrediction(
            outputs={},
            latency_ms=0,
            model_format="onnx",
            error="Model not loaded",
        )
        assert not pred.is_valid
