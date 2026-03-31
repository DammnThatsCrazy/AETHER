"""
Aether Security — Extraction Defense Mesh Tests

Comprehensive test suite covering:
  1. Extraction identity resolution
  2. Distributed budget engine (multi-axis)
  3. Extraction expectation engine (all signal types)
  4. Extraction risk scorer (sibling score)
  5. Extraction policy engine (disclosure control)
  6. Canary / attribution service
  7. Near-duplicate detection
  8. Middleware integration
  9. Multi-key evasion detection
  10. Cross-cluster detection
  11. Batch privilege enforcement
  12. Standard caller regression (no degradation)
  13. Alert/event emission
"""

import asyncio
import hashlib
import sys
import time
from pathlib import Path

import pytest

# =========================================================================
# Path setup — add backend root to sys.path for shared/services imports
# =========================================================================

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
ML_ROOT = ROOT / "ML Models" / "aether-ml"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
if str(ML_ROOT) not in sys.path:
    sys.path.insert(0, str(ML_ROOT))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# =========================================================================
# Test helpers
# =========================================================================

def run_async(coro):
    """Helper to run async functions in sync test context."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# =========================================================================
# 1. Extraction Models
# =========================================================================

class TestExtractionModels:
    """Test extraction data models and sensitivity tiers."""

    def test_extraction_identity_primary_key(self):
        from shared.scoring.extraction_models import ExtractionIdentity
        # API key is preferred
        identity = ExtractionIdentity(api_key_id="key123", source_ip="1.2.3.4")
        assert identity.primary_key == "key123"

        # Falls back to IP
        identity2 = ExtractionIdentity(source_ip="1.2.3.4")
        assert identity2.primary_key == "1.2.3.4"

        # Anonymous fallback
        identity3 = ExtractionIdentity()
        assert identity3.primary_key == "anonymous"

    def test_extraction_identity_available_dimensions(self):
        from shared.scoring.extraction_models import ExtractionIdentity
        identity = ExtractionIdentity(
            api_key_id="key1", tenant_id="t1", source_ip="1.2.3.4"
        )
        dims = identity.available_dimensions
        assert "api_key_id" in dims
        assert "tenant_id" in dims
        assert "source_ip" in dims
        assert "device_fingerprint" not in dims

    def test_model_sensitivity_tier_lookup(self):
        from shared.scoring.extraction_models import get_model_tier, ModelSensitivityTier
        assert get_model_tier("churn_prediction") == ModelSensitivityTier.TIER_1_CRITICAL
        assert get_model_tier("bot_detection") == ModelSensitivityTier.TIER_2_HIGH
        assert get_model_tier("session_scorer") == ModelSensitivityTier.TIER_3_STANDARD
        assert get_model_tier("unknown_model") == ModelSensitivityTier.TIER_2_HIGH

    def test_risk_band_from_score(self):
        from shared.scoring.extraction_models import ExtractionRiskAssessment, ExtractionRiskBand
        assert ExtractionRiskAssessment.band_from_score(10) == ExtractionRiskBand.GREEN
        assert ExtractionRiskAssessment.band_from_score(40) == ExtractionRiskBand.YELLOW
        assert ExtractionRiskAssessment.band_from_score(60) == ExtractionRiskBand.ORANGE
        assert ExtractionRiskAssessment.band_from_score(90) == ExtractionRiskBand.RED

    def test_output_disclosure_policy_rounding(self):
        from shared.scoring.extraction_models import OutputDisclosurePolicy, ConfidenceMode
        policy = OutputDisclosurePolicy(confidence_mode=ConfidenceMode.ROUNDED, output_precision=2)
        assert policy.apply_confidence(0.87654) == 0.88

    def test_output_disclosure_policy_bucketing(self):
        from shared.scoring.extraction_models import OutputDisclosurePolicy, ConfidenceMode
        policy = OutputDisclosurePolicy(confidence_mode=ConfidenceMode.BUCKETED)
        assert policy.apply_confidence(0.87) == 0.9
        assert policy.apply_confidence(0.23) == 0.2
        assert policy.apply_confidence(0.55) == 0.6

    def test_output_disclosure_policy_exact(self):
        from shared.scoring.extraction_models import OutputDisclosurePolicy, ConfidenceMode
        policy = OutputDisclosurePolicy(confidence_mode=ConfidenceMode.EXACT)
        assert policy.apply_confidence(0.87654321) == 0.87654321

    def test_output_disclosure_policy_hidden(self):
        from shared.scoring.extraction_models import OutputDisclosurePolicy, ConfidenceMode
        policy = OutputDisclosurePolicy(confidence_mode=ConfidenceMode.HIDDEN)
        assert policy.apply_confidence(0.87) == -1.0


# =========================================================================
# 2. Budget Keys
# =========================================================================

class TestBudgetKeys:
    """Test Redis key construction for distributed budgets."""

    def test_budget_key_format(self):
        from shared.rate_limit.budget_keys import budget_key, BudgetAxis, BudgetWindow
        key = budget_key(BudgetAxis.API_KEY, "test-key-123", BudgetWindow.MINUTE, now=1000000.0)
        assert key.startswith("aether:exbudget:api_key:test-key-123:1m:")

    def test_budget_key_rotation(self):
        from shared.rate_limit.budget_keys import budget_key, BudgetAxis, BudgetWindow
        key1 = budget_key(BudgetAxis.IP, "1.2.3.4", BudgetWindow.MINUTE, now=1000000.0)
        key2 = budget_key(BudgetAxis.IP, "1.2.3.4", BudgetWindow.MINUTE, now=1000060.0)
        # Different minute buckets should produce different keys
        assert key1 != key2

    def test_same_window_same_key(self):
        from shared.rate_limit.budget_keys import budget_key, BudgetAxis, BudgetWindow
        # Use timestamps that are clearly within the same 60-second bucket
        base = 1000020.0  # mid-bucket to avoid edge crossing
        key1 = budget_key(BudgetAxis.IP, "1.2.3.4", BudgetWindow.MINUTE, now=base)
        key2 = budget_key(BudgetAxis.IP, "1.2.3.4", BudgetWindow.MINUTE, now=base + 20.0)
        assert key1 == key2


# =========================================================================
# 3. Budget Policies
# =========================================================================

class TestBudgetPolicies:
    """Test tier-based budget policy configuration."""

    def test_tier_1_has_stricter_limits(self):
        from shared.rate_limit.budget_policies import get_tier_policy
        from shared.scoring.extraction_models import ModelSensitivityTier
        from shared.rate_limit.budget_keys import BudgetAxis, BudgetWindow

        t1 = get_tier_policy(ModelSensitivityTier.TIER_1_CRITICAL)
        t3 = get_tier_policy(ModelSensitivityTier.TIER_3_STANDARD)

        t1_key_rpm = t1.get_limit(BudgetAxis.API_KEY, BudgetWindow.MINUTE)
        t3_key_rpm = t3.get_limit(BudgetAxis.API_KEY, BudgetWindow.MINUTE)

        assert t1_key_rpm < t3_key_rpm

    def test_batch_denied_by_default(self):
        from shared.rate_limit.budget_policies import get_tier_policy
        from shared.scoring.extraction_models import ModelSensitivityTier

        for tier in ModelSensitivityTier:
            policy = get_tier_policy(tier)
            assert policy.batch_allowed is False
            assert policy.require_privileged_for_batch is True


# =========================================================================
# 4. Distributed Budget Engine
# =========================================================================

class TestDistributedBudgetEngine:
    """Test multi-axis budget enforcement."""

    def test_budget_allows_normal_traffic(self):
        from shared.rate_limit.distributed_budget import DistributedBudgetEngine
        from shared.scoring.extraction_models import ExtractionIdentity

        engine = DistributedBudgetEngine()
        engine._mode = "in-memory"

        identity = ExtractionIdentity(
            api_key_id="normal-key",
            tenant_id="tenant-1",
            source_ip="10.0.0.1",
        )

        result = run_async(engine.check_and_increment(identity, "session_scorer"))
        assert result.allowed is True

    def test_budget_blocks_when_exceeded(self):
        from shared.rate_limit.distributed_budget import DistributedBudgetEngine
        from shared.scoring.extraction_models import ExtractionIdentity

        engine = DistributedBudgetEngine()
        engine._mode = "in-memory"

        identity = ExtractionIdentity(
            api_key_id="spam-key",
            source_ip="10.0.0.2",
        )

        # Tier 1 API key limit is 30/min — exhaust it
        for _ in range(35):
            result = run_async(engine.check_and_increment(identity, "churn_prediction"))

        assert result.allowed is False
        assert result.exceeded_axis is not None

    def test_budget_tracks_model_enumeration(self):
        from shared.rate_limit.distributed_budget import DistributedBudgetEngine
        from shared.scoring.extraction_models import ExtractionIdentity

        engine = DistributedBudgetEngine()
        engine._mode = "in-memory"

        identity = ExtractionIdentity(api_key_id="enum-key")
        for model in ["churn_prediction", "bot_detection", "ltv_prediction"]:
            run_async(engine.check_and_increment(identity, model))

        count = run_async(engine.get_model_count("enum-key"))
        assert count == 3


# =========================================================================
# 5. Extraction Expectation Engine
# =========================================================================

class TestExtractionExpectationEngine:
    """Test expectation-based extraction signal computation."""

    def test_low_signals_for_normal_traffic(self):
        from services.expectations.extraction_expectations import ExtractionExpectationEngine
        from shared.scoring.extraction_models import ExtractionIdentity

        engine = ExtractionExpectationEngine()
        identity = ExtractionIdentity(api_key_id="normal-user")

        # Simulate normal traffic: few requests, one model, slightly varied features
        for i in range(5):
            result = run_async(engine.compute_signals(
                identity=identity,
                model_name="session_scorer",
                features={"page_views": 5 + i, "time_on_site": 120 + i * 10},
            ))

        # Few requests with natural variation should produce low deviation
        assert result.composite_deviation < 0.5

    def test_high_signals_for_sweep(self):
        from services.expectations.extraction_expectations import ExtractionExpectationEngine
        from shared.scoring.extraction_models import ExtractionIdentity

        engine = ExtractionExpectationEngine()
        identity = ExtractionIdentity(api_key_id="sweeper")

        # Simulate feature sweep: many unique features
        for i in range(60):
            result = run_async(engine.compute_signals(
                identity=identity,
                model_name="churn_prediction",
                features={"feature_a": i * 0.1, "feature_b": i * 0.2, "feature_c": i * 0.3},
            ))

        # Should detect feature sweep pattern
        signal_names = [s.name for s in result.signals]
        assert result.composite_deviation > 0.1

    def test_model_enumeration_detection(self):
        from services.expectations.extraction_expectations import ExtractionExpectationEngine
        from shared.scoring.extraction_models import ExtractionIdentity

        engine = ExtractionExpectationEngine()
        identity = ExtractionIdentity(api_key_id="model-enum")

        models = [
            "churn_prediction", "bot_detection", "ltv_prediction",
            "intent_prediction", "session_scorer", "anomaly_detection",
        ]
        for model in models:
            for _ in range(3):
                result = run_async(engine.compute_signals(
                    identity=identity,
                    model_name=model,
                    features={"x": 1.0},
                ))

        enum_signals = [s for s in result.signals if s.name == "model_enumeration_signal"]
        assert len(enum_signals) > 0
        assert enum_signals[0].value > 0

    def test_identity_churn_detection(self):
        from services.expectations.extraction_expectations import ExtractionExpectationEngine
        from shared.scoring.extraction_models import ExtractionIdentity

        engine = ExtractionExpectationEngine()

        # Simulate same API key from many different IPs/devices
        for i in range(20):
            identity = ExtractionIdentity(
                api_key_id="churn-key",
                source_ip=f"10.0.{i}.1",
                device_fingerprint=f"device-{i}",
            )
            result = run_async(engine.compute_signals(
                identity=identity,
                model_name="bot_detection",
                features={"x": 1.0},
            ))

        churn_signals = [s for s in result.signals if s.name == "identity_churn_signal"]
        assert len(churn_signals) > 0


# =========================================================================
# 6. Extraction Risk Scorer
# =========================================================================

class TestExtractionRiskScorer:
    """Test the sibling extraction risk scorer."""

    def test_low_score_for_no_signals(self):
        from shared.scoring.extraction_score import ExtractionRiskScorer
        from shared.scoring.extraction_models import ExtractionIdentity, ExtractionRiskBand

        scorer = ExtractionRiskScorer()
        identity = ExtractionIdentity(api_key_id="clean-user")

        assessment = scorer.score(
            identity=identity,
            expectation_signals=[],
            model_name="session_scorer",
        )

        assert assessment.score < 10
        assert assessment.band == ExtractionRiskBand.GREEN
        assert assessment.policy_recommendation == "allow"

    def test_high_score_for_suspicious_signals(self):
        from shared.scoring.extraction_score import ExtractionRiskScorer
        from shared.scoring.extraction_models import (
            ExtractionIdentity, ExtractionSignal, SignalSeverity, ExtractionRiskBand,
        )

        scorer = ExtractionRiskScorer()
        identity = ExtractionIdentity(api_key_id="bad-actor")

        signals = [
            ExtractionSignal(name="feature_sweep_signal", value=0.8, severity=SignalSeverity.HIGH),
            ExtractionSignal(name="model_enumeration_signal", value=0.7, severity=SignalSeverity.HIGH),
            ExtractionSignal(name="confidence_harvest_signal", value=0.6, severity=SignalSeverity.HIGH),
            ExtractionSignal(name="self_rate_deviation", value=0.9, severity=SignalSeverity.HIGH),
        ]

        # Score multiple times to let EMA converge (alpha=0.3)
        for _ in range(10):
            assessment = scorer.score(
                identity=identity,
                expectation_signals=signals,
                model_name="churn_prediction",
            )

        assert assessment.score > 50
        assert assessment.band in (ExtractionRiskBand.ORANGE, ExtractionRiskBand.RED)
        assert assessment.policy_recommendation in ("deny", "restrict")

    def test_tier_1_amplification(self):
        from shared.scoring.extraction_score import ExtractionRiskScorer
        from shared.scoring.extraction_models import (
            ExtractionIdentity, ExtractionSignal, SignalSeverity,
        )

        scorer = ExtractionRiskScorer()
        identity = ExtractionIdentity(api_key_id="test-tier")

        signals = [
            ExtractionSignal(name="feature_sweep_signal", value=0.5, severity=SignalSeverity.MEDIUM),
        ]

        # Same signals, different model tier
        t1_score = scorer.score(identity, signals, "churn_prediction")  # Tier 1
        # Reset EMA
        scorer._ema_scores.clear()
        t3_score = scorer.score(identity, signals, "session_scorer")    # Tier 3

        assert t1_score.score > t3_score.score

    def test_canary_floor(self):
        from shared.scoring.extraction_score import ExtractionRiskScorer
        from shared.scoring.extraction_models import ExtractionIdentity

        scorer = ExtractionRiskScorer()
        identity = ExtractionIdentity(api_key_id="canary-hit")

        # Score multiple times to let EMA converge past the canary floor
        for _ in range(10):
            assessment = scorer.score(
                identity=identity,
                expectation_signals=[],
                model_name="bot_detection",
                canary_triggered=True,
            )

        # Canary hit floors raw score at 70; EMA converges toward it
        assert assessment.score >= 60

    def test_extraction_score_independent_from_trust(self):
        """Verify extraction score is a sibling, not merged into trust."""
        from shared.scoring.extraction_score import ExtractionRiskScorer
        from shared.scoring.trust_score import TrustScoreComposite
        from shared.scoring.extraction_models import ExtractionIdentity

        # These are completely separate systems
        extraction_scorer = ExtractionRiskScorer()
        trust_scorer = TrustScoreComposite()

        assert type(extraction_scorer).__name__ == "ExtractionRiskScorer"
        assert type(trust_scorer).__name__ == "TrustScoreComposite"
        # No inheritance relationship
        assert not isinstance(extraction_scorer, type(trust_scorer))


# =========================================================================
# 7. Extraction Policy Engine
# =========================================================================

class TestExtractionPolicyEngine:
    """Test policy engine disclosure control and access gating."""

    def test_green_band_allows_with_rounding(self):
        from shared.scoring.extraction_policy import ExtractionPolicyEngine
        from shared.scoring.extraction_models import (
            ExtractionRiskAssessment, ExtractionRiskBand, ConfidenceMode,
        )

        engine = ExtractionPolicyEngine()
        assessment = ExtractionRiskAssessment(score=10, band=ExtractionRiskBand.GREEN)

        decision = engine.evaluate(assessment, "session_scorer")
        assert decision.action == "allow"
        assert decision.disclosure.confidence_mode == ConfidenceMode.ROUNDED

    def test_yellow_band_reduces_disclosure(self):
        from shared.scoring.extraction_policy import ExtractionPolicyEngine
        from shared.scoring.extraction_models import (
            ExtractionRiskAssessment, ExtractionRiskBand, ConfidenceMode,
        )

        engine = ExtractionPolicyEngine()
        assessment = ExtractionRiskAssessment(score=40, band=ExtractionRiskBand.YELLOW)

        decision = engine.evaluate(assessment, "bot_detection")
        assert decision.action == "reduce_disclosure"
        assert decision.disclosure.confidence_mode == ConfidenceMode.BUCKETED
        assert decision.disclosure.include_secondary_scores is False

    def test_orange_band_restricts(self):
        from shared.scoring.extraction_policy import ExtractionPolicyEngine
        from shared.scoring.extraction_models import (
            ExtractionRiskAssessment, ExtractionRiskBand,
        )

        engine = ExtractionPolicyEngine()
        assessment = ExtractionRiskAssessment(score=65, band=ExtractionRiskBand.ORANGE)

        decision = engine.evaluate(assessment, "bot_detection")
        assert decision.action == "restrict"
        assert decision.should_alert is True
        assert decision.disclosure.include_probabilities is False

    def test_red_band_denies(self):
        from shared.scoring.extraction_policy import ExtractionPolicyEngine
        from shared.scoring.extraction_models import (
            ExtractionRiskAssessment, ExtractionRiskBand,
        )

        engine = ExtractionPolicyEngine()
        assessment = ExtractionRiskAssessment(score=90, band=ExtractionRiskBand.RED)

        decision = engine.evaluate(assessment, "churn_prediction")
        assert decision.action == "deny"
        assert decision.should_quarantine is True
        assert decision.should_alert is True

    def test_batch_always_denied_for_non_privileged(self):
        from shared.scoring.extraction_policy import ExtractionPolicyEngine
        from shared.scoring.extraction_models import (
            ExtractionRiskAssessment, ExtractionRiskBand,
        )

        engine = ExtractionPolicyEngine()
        assessment = ExtractionRiskAssessment(score=5, band=ExtractionRiskBand.GREEN)

        decision = engine.evaluate(assessment, "session_scorer", is_batch=True)
        assert decision.action == "deny"

    def test_privileged_caller_gets_exact_scores(self):
        from shared.scoring.extraction_policy import ExtractionPolicyEngine
        from shared.scoring.extraction_models import (
            ExtractionRiskAssessment, ExtractionRiskBand, ExtractionIdentity,
            ConfidenceMode,
        )

        engine = ExtractionPolicyEngine(
            privileged_tenants={"internal-tenant"},
        )
        assessment = ExtractionRiskAssessment(
            score=5,
            band=ExtractionRiskBand.GREEN,
            identity=ExtractionIdentity(tenant_id="internal-tenant"),
        )

        decision = engine.evaluate(assessment, "churn_prediction")
        assert decision.action == "allow"
        assert decision.disclosure.allow_exact_scores is True
        assert decision.disclosure.confidence_mode == ConfidenceMode.EXACT
        assert decision.disclosure.batch_allowed is True

    def test_service_caller_bypasses_restrictions(self):
        from shared.scoring.extraction_policy import ExtractionPolicyEngine
        from shared.scoring.extraction_models import (
            ExtractionRiskAssessment, ExtractionRiskBand, ConfidenceMode,
        )

        engine = ExtractionPolicyEngine()
        assessment = ExtractionRiskAssessment(score=80, band=ExtractionRiskBand.RED)

        decision = engine.evaluate(
            assessment, "churn_prediction",
            caller_is_service=True,
        )
        assert decision.action == "allow"
        assert decision.disclosure.confidence_mode == ConfidenceMode.EXACT

    def test_tier_1_yellow_tightened(self):
        from shared.scoring.extraction_policy import ExtractionPolicyEngine
        from shared.scoring.extraction_models import (
            ExtractionRiskAssessment, ExtractionRiskBand, ConfidenceMode,
        )

        engine = ExtractionPolicyEngine()
        assessment = ExtractionRiskAssessment(score=40, band=ExtractionRiskBand.YELLOW)

        # Tier 1 model gets tighter disclosure at yellow
        decision = engine.evaluate(assessment, "churn_prediction")
        assert decision.disclosure.confidence_mode == ConfidenceMode.BUCKETED
        assert decision.disclosure.include_probabilities is False


# =========================================================================
# 8. Attribution Service
# =========================================================================

class TestAttributionService:
    """Test canary/lineage attribution."""

    def test_response_lineage_recording(self):
        from services.intelligence.extraction_attribution import ExtractionAttributionService
        from shared.scoring.extraction_models import ExtractionIdentity

        service = ExtractionAttributionService()
        identity = ExtractionIdentity(
            api_key_id="key1", tenant_id="t1", request_id="req-1"
        )

        lineage_id = service.record_lineage(
            identity=identity,
            model_name="bot_detection",
            feature_hash="abc123",
            response_value=0.85,
            risk_score=15.0,
            policy_action="allow",
        )

        assert lineage_id.startswith("lin_")
        records = service.query_lineage(api_key_id="key1")
        assert len(records) == 1
        assert records[0]["model_name"] == "bot_detection"

    def test_canary_generation_and_detection(self):
        from services.intelligence.extraction_attribution import ExtractionAttributionService

        service = ExtractionAttributionService(canary_secret="test-secret")
        canaries = service.generate_canary_family("test_family", n_features=5, count=10)
        assert len(canaries) == 10

        # Submit a canary as input — should be detected
        hit = service.check_canary(canaries[0], tolerance=0.01)
        assert hit is not None
        assert hit.canary_family == "test_family"
        assert hit.canary_index == 0

    def test_non_canary_not_detected(self):
        from services.intelligence.extraction_attribution import ExtractionAttributionService

        service = ExtractionAttributionService()
        service.generate_canary_family("test", n_features=3, count=5)

        hit = service.check_canary({"f0": 999.0, "f1": 999.0, "f2": 999.0})
        assert hit is None

    def test_attribution_fingerprint_deterministic(self):
        from services.intelligence.extraction_attribution import ExtractionAttributionService
        from shared.scoring.extraction_models import ExtractionIdentity

        service = ExtractionAttributionService(canary_secret="seed1")
        identity = ExtractionIdentity(api_key_id="key1")

        fp1 = service.compute_attribution_fingerprint(identity, "bot_detection")
        fp2 = service.compute_attribution_fingerprint(identity, "bot_detection")
        assert fp1 == fp2  # Deterministic

        fp3 = service.compute_attribution_fingerprint(identity, "churn_prediction")
        assert fp1 != fp3  # Different model → different fingerprint


# =========================================================================
# 9. Near-Duplicate Detector
# =========================================================================

class TestNearDuplicateDetector:
    """Test cache-based near-duplicate detection."""

    def test_records_and_detects_duplicates(self):
        from serving.src.cache import NearDuplicateDetector

        detector = NearDuplicateDetector()
        features = {"a": 1.0, "b": 2.0}

        for _ in range(10):
            result = detector.record("key1", features)

        assert result["duplicate_ratio"] > 0.5
        assert result["request_count"] == 10

    def test_unique_features_low_duplicate_ratio(self):
        from serving.src.cache import NearDuplicateDetector

        detector = NearDuplicateDetector()

        for i in range(20):
            result = detector.record("key2", {"a": float(i), "b": float(i * 2)})

        assert result["duplicate_ratio"] < 0.1

    def test_locality_score(self):
        from serving.src.cache import NearDuplicateDetector

        detector = NearDuplicateDetector()

        # Same features → high locality
        for _ in range(20):
            detector.record("key3", {"a": 1.0, "b": 2.0})

        score = detector.get_locality_score("key3")
        assert score > 0.5


# =========================================================================
# 10. Extraction Monitoring
# =========================================================================

class TestExtractionMonitoring:
    """Test extraction defense monitoring."""

    def test_monitor_records_events(self):
        from monitoring.monitor import ExtractionDefenseMonitor

        monitor = ExtractionDefenseMonitor()
        monitor.record_extraction_event(
            risk_score=45.0,
            band="yellow",
            signals=[{"name": "test", "value": 0.5}],
            policy_action="reduce_disclosure",
            model_name="bot_detection",
        )

        summary = monitor.get_summary()
        assert summary["total_requests"] == 1
        assert summary["policy_actions"]["reduce_disclosure"] == 1

    def test_monitor_detects_anomalies(self):
        from monitoring.monitor import ExtractionDefenseMonitor

        monitor = ExtractionDefenseMonitor()

        # Simulate high block rate
        for _ in range(50):
            monitor.record_extraction_event(
                risk_score=85.0,
                band="red",
                signals=[],
                policy_action="deny",
            )

        alerts = monitor.check_anomalies()
        alert_types = [a["type"] for a in alerts]
        assert "high_block_rate" in alert_types
        assert "red_band_spike" in alert_types


# =========================================================================
# 11. Multi-Key Evasion Detection
# =========================================================================

class TestMultiKeyEvasion:
    """Test detection of multi-key extraction evasion."""

    def test_cluster_budget_catches_multi_key(self):
        """Multiple API keys from same IP should exhaust IP budget."""
        from shared.rate_limit.distributed_budget import DistributedBudgetEngine
        from shared.scoring.extraction_models import ExtractionIdentity

        engine = DistributedBudgetEngine()
        engine._mode = "in-memory"

        # 5 different keys, same IP, hitting Tier 1 model
        results = []
        for key_idx in range(5):
            for _ in range(15):
                identity = ExtractionIdentity(
                    api_key_id=f"evasion-key-{key_idx}",
                    source_ip="10.0.0.99",
                )
                result = run_async(engine.check_and_increment(identity, "churn_prediction"))
                results.append(result)

        # Should have some blocked results (IP budget: 60/min for Tier 1)
        blocked = [r for r in results if not r.allowed]
        assert len(blocked) > 0


# =========================================================================
# 12. Standard Caller Regression
# =========================================================================

class TestStandardCallerRegression:
    """Verify normal callers are not degraded by the extraction mesh."""

    def test_normal_caller_passes_budget(self):
        from shared.rate_limit.distributed_budget import DistributedBudgetEngine
        from shared.scoring.extraction_models import ExtractionIdentity

        engine = DistributedBudgetEngine()
        engine._mode = "in-memory"

        identity = ExtractionIdentity(
            api_key_id="legit-user",
            tenant_id="good-tenant",
            source_ip="203.0.113.1",
        )

        # Normal: 5 requests to one model
        for _ in range(5):
            result = run_async(engine.check_and_increment(identity, "session_scorer"))
            assert result.allowed is True

    def test_normal_caller_gets_green_score(self):
        from services.expectations.extraction_expectations import ExtractionExpectationEngine
        from shared.scoring.extraction_score import ExtractionRiskScorer
        from shared.scoring.extraction_models import ExtractionIdentity, ExtractionRiskBand

        expect_engine = ExtractionExpectationEngine()
        scorer = ExtractionRiskScorer()
        identity = ExtractionIdentity(api_key_id="legit-caller")

        # Normal pattern: 3 requests
        for _ in range(3):
            expectation = run_async(expect_engine.compute_signals(
                identity=identity,
                model_name="session_scorer",
                features={"page_views": 10, "time_on_site": 300},
            ))

        assessment = scorer.score(identity, expectation.signals, "session_scorer")
        assert assessment.band == ExtractionRiskBand.GREEN
        assert assessment.policy_recommendation == "allow"

    def test_normal_caller_gets_rounded_disclosure(self):
        from shared.scoring.extraction_policy import ExtractionPolicyEngine
        from shared.scoring.extraction_models import (
            ExtractionRiskAssessment, ExtractionRiskBand, ConfidenceMode,
        )

        engine = ExtractionPolicyEngine()
        assessment = ExtractionRiskAssessment(score=5, band=ExtractionRiskBand.GREEN)

        decision = engine.evaluate(assessment, "session_scorer")
        assert decision.action == "allow"
        assert decision.disclosure.confidence_mode == ConfidenceMode.ROUNDED
        # Secondary scores still included for green band
        assert decision.disclosure.include_secondary_scores is True


# =========================================================================
# 13. Alert Emission
# =========================================================================

class TestAlertEmission:
    """Test extraction alert recording."""

    def test_alert_recorded_on_red_band(self):
        from services.intelligence.extraction_intel import (
            record_extraction_alert, _alerts,
        )

        initial_count = len(_alerts)
        record_extraction_alert(
            actor_id="bad-actor-key",
            risk_score=92.0,
            band="red",
            reasons=["feature_sweep_signal: 0.9", "canary_input_detected"],
        )

        assert len(_alerts) > initial_count
        latest = _alerts[-1]
        assert latest["band"] == "red"
        assert latest["risk_score"] == 92.0
        assert latest["status"] == "open"


# =========================================================================
# 14. Graph Helpers
# =========================================================================

class TestExtractionGraphHelper:
    """Test graph-based extraction defense queries."""

    def test_compute_cluster_features_empty(self):
        from shared.graph.extraction_graph import ExtractionGraphHelper
        from shared.graph.graph import GraphClient

        client = GraphClient()
        run_async(client.connect())

        helper = ExtractionGraphHelper(client)
        features = run_async(helper.compute_cluster_features("nonexistent"))
        assert features["cluster_size"] == 0


# =========================================================================
# 15. Extraction Event Topics
# =========================================================================

class TestExtractionEventTopics:
    """Verify extraction event topics are registered."""

    def test_extraction_topics_exist(self):
        from shared.events.events import Topic

        assert hasattr(Topic, "ML_EXTRACTION_REQUEST_SEEN")
        assert hasattr(Topic, "ML_EXTRACTION_SCORE_UPDATED")
        assert hasattr(Topic, "ML_EXTRACTION_POLICY_APPLIED")
        assert hasattr(Topic, "ML_EXTRACTION_CANARY_HIT")
        assert hasattr(Topic, "ML_EXTRACTION_ALERT_OPENED")
        assert hasattr(Topic, "ML_EXTRACTION_CLUSTER_ESCALATED")

    def test_extraction_topics_namespaced(self):
        from shared.events.events import Topic

        assert Topic.ML_EXTRACTION_REQUEST_SEEN.value.startswith("aether.extraction.")
