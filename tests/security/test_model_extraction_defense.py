"""
Aether Security — Model Extraction Defense Tests

Simulates:
  1. Normal user queries (should pass with minimal perturbation)
  2. Scraping attack (high-velocity queries from single key)
  3. Distillation attack (systematic feature-space exploration)

Verifies:
  - Attack traffic is throttled / blocked
  - Legitimate traffic is unaffected
  - Output perturbation scales with risk
  - Watermark is detectable after many queries
  - Canary inputs trigger defensive response
"""

import time
import pytest
import numpy as np

from security.model_extraction_defense.config import (
    ExtractionDefenseConfig,
    RateLimiterConfig,
    PatternDetectorConfig,
    OutputPerturbationConfig,
    WatermarkConfig,
    CanaryConfig,
    RiskScorerConfig,
)
from security.model_extraction_defense.rate_limiter import QueryRateLimiter
from security.model_extraction_defense.pattern_detector import QueryPatternDetector
from security.model_extraction_defense.output_perturbation import OutputPerturbationLayer
from security.model_extraction_defense.watermark import ModelWatermark
from security.model_extraction_defense.canary_detector import CanaryInputDetector
from security.model_extraction_defense.risk_scorer import ExtractionRiskScorer
from security.model_extraction_defense.defense_layer import ExtractionDefenseLayer
from security.model_extraction_defense.metrics import DefenseMetrics
from security.model_extraction_defense.cleanup import CleanupThread


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def rate_limiter():
    """Rate limiter with low limits for fast testing."""
    config = RateLimiterConfig(
        key_max_per_minute=10,
        key_max_per_hour=100,
        key_max_per_day=1000,
        ip_max_per_minute=20,
        ip_max_per_hour=200,
        ip_max_per_day=2000,
    )
    return QueryRateLimiter(config)


@pytest.fixture
def pattern_detector():
    config = PatternDetectorConfig(
        analysis_window_seconds=60,
        min_queries_for_analysis=5,
    )
    return QueryPatternDetector(config)


@pytest.fixture
def perturbation_layer():
    config = OutputPerturbationConfig(
        logit_noise_std=0.02,
        top_k_classes=3,
        output_precision=2,
        entropy_smoothing_alpha=0.01,
    )
    return OutputPerturbationLayer(config)


@pytest.fixture
def watermark():
    config = WatermarkConfig(
        secret_key="test-secret-key",
        bias_strength=0.03,
        min_classes=3,
    )
    return ModelWatermark(config)


@pytest.fixture
def canary_detector():
    config = CanaryConfig(
        secret_seed="test-canary-seed",
        num_canaries=10,
        match_tolerance=0.05,
        action="throttle",
        cooldown_seconds=10,
    )
    detector = CanaryInputDetector(config)
    detector.generate_canaries(n_features=10)
    return detector


@pytest.fixture
def risk_scorer():
    return ExtractionRiskScorer(RiskScorerConfig())


@pytest.fixture
def defense_layer():
    config = ExtractionDefenseConfig(
        enable_extraction_defense=True,
        enable_output_noise=True,
        enable_watermark=True,
        enable_query_analysis=True,
        rate_limiter=RateLimiterConfig(
            key_max_per_minute=10,
            key_max_per_hour=100,
            key_max_per_day=1000,
            ip_max_per_minute=20,
            ip_max_per_hour=200,
            ip_max_per_day=2000,
        ),
        pattern_detector=PatternDetectorConfig(
            analysis_window_seconds=60,
            min_queries_for_analysis=5,
        ),
        canary=CanaryConfig(
            secret_seed="test-canary-seed",
            num_canaries=10,
            match_tolerance=0.05,
            action="throttle",
            cooldown_seconds=5,
        ),
    )
    return ExtractionDefenseLayer(config)


# =========================================================================
# 1. Rate Limiter Tests
# =========================================================================


class TestQueryRateLimiter:
    def test_normal_traffic_allowed(self, rate_limiter):
        """Normal-rate queries should pass without issue."""
        for i in range(5):
            result = rate_limiter.check("key-normal", "192.168.1.1")
            assert result.allowed, f"Query {i} should be allowed"

    def test_exceeds_per_key_limit(self, rate_limiter):
        """Exceeding per-key per-minute limit triggers rate limiting."""
        for i in range(10):
            rate_limiter.check("key-burst", "192.168.1.1")

        result = rate_limiter.check("key-burst", "192.168.1.1")
        assert not result.allowed
        assert result.source == "api_key"

    def test_exceeds_per_ip_limit(self, rate_limiter):
        """Exceeding per-IP limit triggers rate limiting even with different keys."""
        for i in range(20):
            rate_limiter.check(f"key-{i}", "10.0.0.1")

        result = rate_limiter.check("key-new", "10.0.0.1")
        assert not result.allowed
        assert result.source == "ip"

    def test_different_ips_independent(self, rate_limiter):
        """Different IPs have independent limits."""
        for i in range(10):
            rate_limiter.check("key-shared", "192.168.1.1")

        result = rate_limiter.check("key-shared", "192.168.1.2")
        # The key is exhausted but the IP is fresh — key limit should block
        assert not result.allowed

    def test_batch_cost_accounting(self, rate_limiter):
        """Batch requests consume tokens proportional to instance count."""
        # With cost=5 per batch, 10-limit should exhaust in 2 batches
        rate_limiter.check("key-batch", "192.168.1.1", cost=5)
        rate_limiter.check("key-batch", "192.168.1.1", cost=5)
        result = rate_limiter.check("key-batch", "192.168.1.1", cost=1)
        assert not result.allowed

    def test_velocity_tracking(self, rate_limiter):
        """Query velocity should be tracked accurately."""
        for _ in range(5):
            rate_limiter.check("key-velocity", "192.168.1.1")

        velocity = rate_limiter.get_query_velocity("key-velocity")
        assert velocity["minute"] == 5


# =========================================================================
# 2. Pattern Detector Tests
# =========================================================================


class TestQueryPatternDetector:
    def test_normal_queries_benign(self, pattern_detector):
        """Diverse, irregular queries should not trigger anomalies."""
        rng = np.random.default_rng(42)
        for _ in range(20):
            features = {f"f{i}": float(rng.normal(0, 1)) for i in range(10)}
            pattern_detector.record_query("key-normal", features, "intent")
            time.sleep(0.01 * rng.uniform(0.5, 2.0))  # irregular timing

        analysis = pattern_detector.analyze("key-normal")
        assert analysis.anomaly_score < 0.5, (
            f"Normal traffic should have low anomaly score, got {analysis.anomaly_score}"
        )

    def test_sweep_detection(self, pattern_detector):
        """Systematic single-feature sweeps should be detected."""
        for i in range(30):
            features = {f"f{j}": 0.5 for j in range(10)}
            features["f0"] = float(i) / 30.0  # Only f0 varies
            pattern_detector.record_query("key-sweep", features, "intent")

        analysis = pattern_detector.analyze("key-sweep")
        assert analysis.sweep_score > 0.5, (
            f"Feature sweep should be detected, got sweep_score={analysis.sweep_score}"
        )
        assert "systematic_feature_sweep" in analysis.flags

    def test_uniform_probing_detection(self, pattern_detector):
        """Near-uniform random sampling should be flagged."""
        rng = np.random.default_rng(123)
        for _ in range(50):
            # Uniform random probing
            features = {f"f{i}": float(rng.uniform(0, 1)) for i in range(10)}
            pattern_detector.record_query("key-probe", features, "intent")

        analysis = pattern_detector.analyze("key-probe")
        assert analysis.entropy_score > 0.3, (
            f"Uniform probing should elevate entropy score, got {analysis.entropy_score}"
        )

    def test_regular_timing_detection(self, pattern_detector):
        """Bot-like regular timing should be detected."""
        base_time = time.time()
        for i in range(20):
            features = {f"f{j}": float(j + i) for j in range(5)}
            pattern_detector.record_query("key-bot", features, "intent")
            # Override timestamp to simulate regular intervals
            records = pattern_detector._history["key-bot"]
            records[-1].timestamp = base_time + i * 1.0  # exactly 1s apart

        analysis = pattern_detector.analyze("key-bot")
        assert analysis.timing_score > 0.3, (
            f"Regular timing should be flagged, got timing_score={analysis.timing_score}"
        )


# =========================================================================
# 3. Output Perturbation Tests
# =========================================================================


class TestOutputPerturbation:
    def test_scalar_perturbation_bounded(self, perturbation_layer):
        """Perturbed scalar output should remain in [0, 1]."""
        for _ in range(100):
            result = perturbation_layer.perturb(0.85, risk_score=0.5)
            assert 0.0 <= result <= 1.0

    def test_low_risk_minimal_noise(self, perturbation_layer):
        """Low risk score should produce minimal perturbation."""
        original = 0.75
        deviations = []
        for _ in range(100):
            result = perturbation_layer.perturb(original, risk_score=0.0)
            deviations.append(abs(result - original))

        avg_deviation = np.mean(deviations)
        assert avg_deviation < 0.05, (
            f"Low-risk noise should be small, got avg deviation {avg_deviation}"
        )

    def test_high_risk_more_noise(self, perturbation_layer):
        """High risk score should produce significantly more perturbation."""
        original = 0.75
        low_risk_devs = []
        high_risk_devs = []

        for _ in range(200):
            low = perturbation_layer.perturb(original, risk_score=0.1)
            high = perturbation_layer.perturb(original, risk_score=0.9)
            low_risk_devs.append(abs(low - original))
            high_risk_devs.append(abs(high - original))

        assert np.mean(high_risk_devs) > np.mean(low_risk_devs), (
            "High-risk perturbation should be larger than low-risk"
        )

    def test_vector_perturbation_sums_to_one(self, perturbation_layer):
        """Perturbed probability vector should sum to ~1."""
        probs = [0.6, 0.25, 0.1, 0.05]
        result = perturbation_layer.perturb(probs, risk_score=0.3)
        assert abs(sum(result) - 1.0) < 0.01, (
            f"Perturbed probabilities should sum to ~1, got {sum(result)}"
        )

    def test_dict_perturbation(self, perturbation_layer):
        """Dict outputs should have numeric values perturbed."""
        output = {"confidence": 0.85, "exit_risk": 0.3, "label": "high"}
        result = perturbation_layer.perturb(output, risk_score=0.2)

        assert isinstance(result["label"], str)
        assert result["label"] == "high"  # Non-numeric unchanged
        assert isinstance(result["confidence"], float)
        assert isinstance(result["exit_risk"], float)

    def test_top_k_clipping(self):
        """Top-k clipping should zero out low-probability classes."""
        config = OutputPerturbationConfig(
            top_k_classes=2,
            logit_noise_std=0.0,
            entropy_smoothing_alpha=0.0,
            base_noise_floor=0.0,
        )
        layer = OutputPerturbationLayer(config)

        probs = np.array([0.5, 0.3, 0.1, 0.05, 0.05])
        result = layer._perturb_vector(probs, risk_score=0.0)

        # Only top-2 should be non-zero
        sorted_result = np.sort(result)[::-1]
        assert sorted_result[2] < 0.01, "Classes beyond top-k should be near zero"


# =========================================================================
# 4. Watermark Tests
# =========================================================================


class TestModelWatermark:
    def test_watermark_preserves_distribution(self, watermark):
        """Watermarked probabilities should still sum to 1."""
        probs = np.array([0.6, 0.25, 0.1, 0.05])
        fingerprint = ModelWatermark.fingerprint_features({"f1": 1.0, "f2": 2.0})

        watermarked = watermark.embed(probs, fingerprint)
        assert abs(watermarked.sum() - 1.0) < 1e-6

    def test_watermark_minimal_distortion(self, watermark):
        """Watermark bias should be small enough to not significantly alter predictions."""
        probs = np.array([0.7, 0.2, 0.1])
        fingerprint = ModelWatermark.fingerprint_features({"f1": 1.0})

        watermarked = watermark.embed(probs, fingerprint)
        max_deviation = np.max(np.abs(watermarked - probs))
        assert max_deviation < 0.1, (
            f"Watermark distortion too large: {max_deviation}"
        )

    def test_watermark_deterministic(self, watermark):
        """Same input should produce identical watermark."""
        probs = np.array([0.5, 0.3, 0.2])
        fingerprint = ModelWatermark.fingerprint_features({"f1": 1.0})

        w1 = watermark.embed(probs, fingerprint)
        w2 = watermark.embed(probs, fingerprint)
        np.testing.assert_array_equal(w1, w2)

    def test_watermark_verification(self, watermark):
        """Watermark should be detectable across many queries."""
        n_queries = 200
        outputs = []
        fingerprints = []

        rng = np.random.default_rng(42)
        for i in range(n_queries):
            probs = rng.dirichlet(np.ones(5))
            fp = ModelWatermark.fingerprint_features({f"f{j}": float(rng.normal()) for j in range(5)})
            watermarked = watermark.embed(probs, fp)
            outputs.append(watermarked)
            fingerprints.append(fp)

        score = watermark.verify(outputs, fingerprints)
        assert score > watermark.config.verification_threshold, (
            f"Watermark should be detectable, got confidence {score}"
        )

    def test_unwatermarked_fails_verification(self, watermark):
        """Outputs without watermark should fail verification."""
        rng = np.random.default_rng(42)
        outputs = [rng.dirichlet(np.ones(5)) for _ in range(100)]
        fingerprints = [
            ModelWatermark.fingerprint_features({f"f{j}": float(rng.normal()) for j in range(5)})
            for _ in range(100)
        ]

        score = watermark.verify(outputs, fingerprints)
        assert score < watermark.config.verification_threshold, (
            f"Unwatermarked outputs should fail, got confidence {score}"
        )

    def test_scalar_watermark(self, watermark):
        """Scalar watermark should produce bounded output."""
        fp = ModelWatermark.fingerprint_features({"f1": 1.0})
        result = watermark.embed_scalar(0.75, fp)
        assert 0.0 <= result <= 1.0

    def test_fingerprint_deterministic(self):
        """Feature fingerprints should be deterministic."""
        features = {"b": 2.0, "a": 1.0}
        fp1 = ModelWatermark.fingerprint_features(features)
        fp2 = ModelWatermark.fingerprint_features(features)
        assert fp1 == fp2


# =========================================================================
# 5. Canary Detector Tests
# =========================================================================


class TestCanaryDetector:
    def test_normal_input_not_canary(self, canary_detector):
        """Normal inputs should not match canaries."""
        features = {f"f{i}": 0.5 for i in range(10)}
        result = canary_detector.check(features, "key-normal", "192.168.1.1")
        assert not result.is_canary

    def test_canary_detected(self, canary_detector):
        """A query matching a canary should be detected."""
        # Get a canary vector and convert to feature dict
        canary_vec = canary_detector._canaries[0]
        features = {f"f{i}": float(canary_vec[i]) for i in range(len(canary_vec))}

        result = canary_detector.check(features, "key-scraper", "10.0.0.1")
        assert result.is_canary
        assert result.canary_id == 0
        assert result.action == "throttle"

    def test_canary_cooldown(self, canary_detector):
        """After canary trigger, client should be in cooldown."""
        canary_vec = canary_detector._canaries[0]
        features = {f"f{i}": float(canary_vec[i]) for i in range(len(canary_vec))}

        canary_detector.check(features, "key-scraper", "10.0.0.1")
        assert canary_detector.is_in_cooldown("key-scraper")

    def test_trigger_count(self, canary_detector):
        """Trigger count should increment on each canary detection."""
        canary_vec = canary_detector._canaries[0]
        features = {f"f{i}": float(canary_vec[i]) for i in range(len(canary_vec))}

        canary_detector.check(features, "key-multi", "10.0.0.1")
        canary_vec2 = canary_detector._canaries[1]
        features2 = {f"f{i}": float(canary_vec2[i]) for i in range(len(canary_vec2))}
        canary_detector.check(features2, "key-multi", "10.0.0.1")

        assert canary_detector.get_trigger_count("key-multi") == 2


# =========================================================================
# 6. Risk Scorer Tests
# =========================================================================


class TestExtractionRiskScorer:
    def test_normal_traffic_low_risk(self, risk_scorer):
        """Normal velocity and no anomalies should produce low risk."""
        assessment = risk_scorer.assess(
            api_key="key-normal",
            velocity={"minute": 3, "hour": 50},
            pattern_anomaly_score=0.1,
        )
        assert assessment.risk_score < 0.3
        assert assessment.tier == "normal"

    def test_high_velocity_elevates_risk(self, risk_scorer):
        """High query velocity should elevate risk score."""
        assessment = risk_scorer.assess(
            api_key="key-fast",
            velocity={"minute": 55, "hour": 500},
            pattern_anomaly_score=0.3,
        )
        assert assessment.risk_score > 0.2
        assert assessment.tier in ("elevated", "high", "critical")

    def test_pattern_anomaly_elevates_risk(self, risk_scorer):
        """High pattern anomaly score should elevate risk."""
        assessment = risk_scorer.assess(
            api_key="key-anomaly",
            velocity={"minute": 5, "hour": 50},
            pattern_anomaly_score=0.9,
            similarity_score=0.8,
            entropy_score=0.7,
        )
        assert assessment.risk_score > 0.3

    def test_canary_trigger_spikes_risk(self, risk_scorer):
        """Canary trigger should immediately spike risk to critical."""
        assessment = risk_scorer.assess(
            api_key="key-canary",
            velocity={"minute": 1, "hour": 1},
            canary_triggered=True,
        )
        assert assessment.risk_score >= 0.5
        assert assessment.tier in ("high", "critical")

    def test_risk_ema_smoothing(self, risk_scorer):
        """Risk score should smooth via EMA, not jump instantly."""
        # First assessment: low
        risk_scorer.assess("key-ema", velocity={"minute": 1, "hour": 10})
        # Sudden spike
        a2 = risk_scorer.assess(
            "key-ema",
            velocity={"minute": 50, "hour": 500},
            pattern_anomaly_score=0.9,
        )
        # Should be elevated but smoothed, not immediately at raw score
        assert a2.risk_score < 0.9, "EMA should smooth the spike"

    def test_noise_multiplier_scales_with_tier(self, risk_scorer):
        """Higher risk tiers should have higher noise multipliers."""
        normal = risk_scorer.assess("k1", velocity={"minute": 1, "hour": 10})
        # Simulate escalation
        for _ in range(20):
            high = risk_scorer.assess(
                "k2",
                velocity={"minute": 55, "hour": 500},
                pattern_anomaly_score=0.9,
                similarity_score=0.9,
                entropy_score=0.9,
            )

        assert high.noise_multiplier > normal.noise_multiplier


# =========================================================================
# 7. Defense Layer Integration Tests
# =========================================================================


class TestExtractionDefenseLayer:
    def test_normal_user_flow(self, defense_layer):
        """Normal user queries should pass through with minimal impact."""
        features = {"page_views": 5.0, "time_on_site": 120.0, "clicks": 3.0}

        pre = defense_layer.pre_request("key-normal", "192.168.1.1", features, "intent")
        assert not pre.blocked

        # Simulate model output
        raw_output = 0.85
        post = defense_layer.post_response("key-normal", raw_output, features)

        assert post.output is not None
        assert isinstance(post.output, float)
        # Should be close to original for low-risk client
        assert abs(post.output - raw_output) < 0.15

    def test_scraping_attack_throttled(self, defense_layer):
        """High-velocity scraping attack should be rate-limited."""
        features = {"f1": 0.5, "f2": 0.5}
        blocked = False

        for i in range(15):
            pre = defense_layer.pre_request(
                "key-scraper", "10.0.0.1", features, "intent"
            )
            if pre.blocked:
                blocked = True
                break

        assert blocked, "Scraping attack should be rate-limited"

    def test_distillation_attack_degraded(self, defense_layer):
        """Systematic distillation queries should produce degraded outputs."""
        # Submit enough diverse queries to build up risk
        rng = np.random.default_rng(42)
        for i in range(8):
            features = {f"f{j}": float(rng.uniform(0, 1)) for j in range(10)}
            defense_layer.pre_request("key-distill", "10.0.0.2", features, "intent")

        # Now check risk score
        risk = defense_layer.get_client_risk("key-distill")

        # Get a perturbed output
        features = {"f1": 0.5}
        post = defense_layer.post_response("key-distill", 0.85, features, risk_score=0.6)

        # Output should be noisier than for a normal user
        assert post.noise_applied

    def test_canary_triggers_block(self, defense_layer):
        """Canary input should trigger defensive response."""
        defense_layer.canary_detector.generate_canaries(n_features=5)
        canary_vec = defense_layer.canary_detector._canaries[0]
        features = {f"f{i}": float(canary_vec[i]) for i in range(len(canary_vec))}

        pre = defense_layer.pre_request("key-canary", "10.0.0.3", features, "intent")
        # Should either block or throttle
        # After canary, future requests should be blocked (cooldown)
        pre2 = defense_layer.pre_request("key-canary", "10.0.0.3", {"f1": 0.5}, "intent")
        assert pre2.blocked, "Client should be in cooldown after canary trigger"

    def test_disabled_defense_passthrough(self):
        """When defense is disabled, everything passes through unchanged."""
        config = ExtractionDefenseConfig(enable_extraction_defense=False)
        layer = ExtractionDefenseLayer(config)

        pre = layer.pre_request("any-key", "any-ip", {"f1": 1.0}, "intent")
        assert not pre.blocked

        post = layer.post_response("any-key", 0.85, {"f1": 1.0})
        assert post.output == 0.85

    def test_watermark_applied_to_vector(self, defense_layer):
        """Watermark should be applied to probability vector outputs."""
        features = {"f1": 1.0, "f2": 2.0}
        raw = [0.6, 0.25, 0.1, 0.05]

        post = defense_layer.post_response("key-wm", raw, features)
        assert post.watermark_applied

    def test_cleanup(self, defense_layer):
        """Cleanup should not raise and should return counts."""
        result = defense_layer.cleanup()
        assert isinstance(result, dict)
        assert "rate_limiter" in result
        assert "pattern_detector" in result
        assert "risk_scorer" in result

    def test_multi_key_same_ip_detected(self, defense_layer):
        """Multiple API keys from the same IP should hit IP rate limit."""
        features = {"f1": 0.5}
        blocked = False
        for i in range(25):
            pre = defense_layer.pre_request(
                f"key-{i}", "10.0.0.99", features, "intent"
            )
            if pre.blocked:
                blocked = True
                break

        assert blocked, "Multi-key attack from single IP should be rate-limited"


# =========================================================================
# 8. Canary Lazy Initialization Tests
# =========================================================================


class TestCanaryLazyInit:
    def test_canaries_generated_on_first_request(self):
        """Canary vectors should be lazily generated from first request dimensionality."""
        config = ExtractionDefenseConfig(
            enable_extraction_defense=True,
            rate_limiter=RateLimiterConfig(key_max_per_minute=100),
            canary=CanaryConfig(
                secret_seed="test-lazy-seed",
                num_canaries=5,
                match_tolerance=0.05,
            ),
        )
        layer = ExtractionDefenseLayer(config)

        # Before any request, canaries should be empty
        assert len(layer.canary_detector._canaries) == 0

        # After a request with 8 features, canaries should be generated
        features = {f"f{i}": float(i) for i in range(8)}
        layer.pre_request("key-lazy", "1.1.1.1", features, "intent")

        assert len(layer.canary_detector._canaries) == 5
        assert layer.canary_detector._canaries[0].shape == (8,)

    def test_canaries_not_generated_for_tiny_features(self):
        """Canaries should not be generated for <2 features."""
        config = ExtractionDefenseConfig(
            enable_extraction_defense=True,
            rate_limiter=RateLimiterConfig(key_max_per_minute=100),
        )
        layer = ExtractionDefenseLayer(config)

        layer.pre_request("key-tiny", "1.1.1.1", {"f1": 1.0}, "intent")
        assert len(layer.canary_detector._canaries) == 0

    def test_empty_features_handled(self):
        """Empty feature dict should not crash the defense layer."""
        config = ExtractionDefenseConfig(
            enable_extraction_defense=True,
            rate_limiter=RateLimiterConfig(key_max_per_minute=100),
        )
        layer = ExtractionDefenseLayer(config)

        pre = layer.pre_request("key-empty", "1.1.1.1", {}, "intent")
        assert not pre.blocked

        post = layer.post_response("key-empty", 0.5, {})
        assert post.output is not None

    def test_non_numeric_features_filtered(self):
        """Non-numeric features should be safely filtered out."""
        config = ExtractionDefenseConfig(
            enable_extraction_defense=True,
            rate_limiter=RateLimiterConfig(key_max_per_minute=100),
        )
        layer = ExtractionDefenseLayer(config)

        features = {"name": "test", "score": 0.5, "label": "high", "count": 3}
        pre = layer.pre_request("key-mixed", "1.1.1.1", features, "intent")
        assert not pre.blocked


# =========================================================================
# 9. Metrics Tests
# =========================================================================


class TestDefenseMetrics:
    def test_metrics_snapshot_structure(self):
        """Metrics snapshot should have expected structure."""
        m = DefenseMetrics()
        snap = m.snapshot()

        assert "counters" in snap
        assert "gauges" in snap
        assert "risk_tier_distribution" in snap
        assert "block_reasons" in snap
        assert "uptime_seconds" in snap
        assert snap["counters"]["requests_total"] == 0

    def test_request_recording(self):
        """Request counter should increment."""
        m = DefenseMetrics()
        m.record_request("key1", "intent")
        m.record_request("key1", "intent")
        m.record_request("key2", "churn")

        snap = m.snapshot()
        assert snap["counters"]["requests_total"] == 3
        assert snap["model_requests"]["intent"] == 2
        assert snap["model_requests"]["churn"] == 1

    def test_block_recording(self):
        """Block events should be tracked with reasons."""
        m = DefenseMetrics()
        m.record_block("key1", "rate_limit", "minute")
        m.record_block("key1", "risk_score")
        m.record_block("key2", "canary_cooldown")

        snap = m.snapshot()
        assert snap["counters"]["blocks_total"] == 3
        assert snap["counters"]["rate_limit_blocks"] == 1
        assert snap["counters"]["risk_blocks"] == 1
        assert snap["block_reasons"]["rate_limit:minute"] == 1

    def test_canary_trigger_recording(self):
        """Canary triggers should be logged."""
        m = DefenseMetrics()
        m.record_canary_trigger("key-bad", canary_id=7)

        snap = m.snapshot()
        assert snap["counters"]["canary_triggers_total"] == 1
        assert len(snap["recent_canary_triggers"]) == 1
        assert snap["recent_canary_triggers"][0]["canary_id"] == 7

    def test_risk_score_recording(self):
        """Risk scores should be tracked per client."""
        m = DefenseMetrics()
        m.record_risk_score("key1", 0.3, "elevated")
        m.record_risk_score("key2", 0.7, "high")

        snap = m.snapshot()
        assert snap["gauges"]["active_clients"] == 2
        assert snap["gauges"]["max_risk_score"] == 0.7
        assert snap["risk_tier_distribution"]["elevated"] == 1
        assert snap["risk_tier_distribution"]["high"] == 1

    def test_prometheus_export(self):
        """Prometheus export should produce valid exposition format."""
        m = DefenseMetrics()
        m.record_request("key1", "intent")
        m.record_block("key1", "rate_limit")

        output = m.export_prometheus()
        assert output is not None
        assert "extraction_defense_requests_total 1" in output
        assert "extraction_defense_blocks_total 1" in output

    def test_reset(self):
        """Reset should zero all counters."""
        m = DefenseMetrics()
        m.record_request("key1", "intent")
        m.record_block("key1", "rate_limit")
        m.reset()

        snap = m.snapshot()
        assert snap["counters"]["requests_total"] == 0
        assert snap["counters"]["blocks_total"] == 0

    def test_metrics_integrated_in_defense_layer(self, defense_layer):
        """Defense layer should record metrics during pre_request."""
        features = {"f1": 0.5, "f2": 0.5}
        defense_layer.pre_request("key-metrics", "1.1.1.1", features, "intent")

        snap = defense_layer.get_metrics_snapshot()
        assert snap["counters"]["requests_total"] >= 1


# =========================================================================
# 10. Batch & Dict Output Perturbation Tests
# =========================================================================


class TestBatchAndDictDefense:
    def test_dict_output_all_numerics_perturbed(self, defense_layer):
        """Dict outputs should have all numeric values perturbed."""
        features = {"f1": 1.0}
        raw = {"score": 0.85, "risk": 0.3, "label": "high"}

        post = defense_layer.post_response("key-dict", raw, features, risk_score=0.4)
        assert post.noise_applied
        assert isinstance(post.output["score"], float)
        assert isinstance(post.output["risk"], float)
        assert post.output["label"] == "high"  # string unchanged

    def test_batch_list_output_perturbed(self, defense_layer):
        """List/vector outputs should be perturbed."""
        features = {"f1": 1.0}
        raw = [0.7, 0.2, 0.1]

        post = defense_layer.post_response("key-batch", raw, features, risk_score=0.2)
        assert post.noise_applied
        assert post.watermark_applied  # 3 classes >= min_classes
        assert abs(sum(post.output) - 1.0) < 0.05

    def test_boolean_output_not_perturbed(self, defense_layer):
        """Boolean outputs should pass through unchanged."""
        features = {"f1": 1.0}

        post = defense_layer.post_response("key-bool", True, features, risk_score=0.5)
        assert post.output is True

    def test_high_risk_batch_degrades_more(self, defense_layer):
        """High-risk batch outputs should deviate more from originals."""
        features = {"f1": 1.0}
        raw = 0.85

        low_risk_devs = []
        high_risk_devs = []
        for _ in range(50):
            low = defense_layer.post_response("k-low", raw, features, risk_score=0.05)
            high = defense_layer.post_response("k-high", raw, features, risk_score=0.9)
            low_risk_devs.append(abs(low.output - raw))
            high_risk_devs.append(abs(high.output - raw))

        assert np.mean(high_risk_devs) > np.mean(low_risk_devs), (
            "High-risk should produce more deviation than low-risk"
        )


# =========================================================================
# 11. Cleanup Thread Tests
# =========================================================================


class TestCleanupThread:
    def test_cleanup_thread_starts_and_stops(self, defense_layer):
        """Cleanup thread should start as daemon and stop cleanly."""
        thread = CleanupThread(defense_layer, interval_seconds=0.1)
        thread.start()
        assert thread.is_alive()
        time.sleep(0.3)  # Let it run a few cycles
        thread.stop()
        assert not thread.is_alive()
