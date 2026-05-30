"""
Aether Security — Model Extraction Defense Configuration

All defense parameters in one place. Override via environment variables
or by passing a custom ExtractionDefenseConfig to the middleware.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RateLimiterConfig:
    """Per-key and per-IP sliding window rate limits."""

    # Per-API-key limits
    key_max_per_minute: int = 60
    key_max_per_hour: int = 1_000
    key_max_per_day: int = 10_000

    # Per-IP limits (stricter — single IP shouldn't need as many)
    ip_max_per_minute: int = 120
    ip_max_per_hour: int = 3_000
    ip_max_per_day: int = 30_000

    # Batch endpoint multiplier (each instance counts this many tokens)
    batch_instance_cost: int = 1

    # Window precision (seconds per bucket for sliding window)
    bucket_width_seconds: int = 1


@dataclass(frozen=True)
class PatternDetectorConfig:
    """Query pattern anomaly detection thresholds."""

    # Sliding window for pattern analysis (seconds)
    analysis_window_seconds: int = 300  # 5 minutes

    # Minimum queries before analysis activates
    min_queries_for_analysis: int = 10

    # Input similarity — flag when >N% of recent queries have cosine
    # similarity > threshold (indicates systematic sweeps)
    similarity_threshold: float = 0.92
    similarity_ratio_alert: float = 0.5  # 50% of queries suspiciously similar

    # Sequential feature sweep detection
    # Flag if a single feature varies while others stay constant
    sweep_variance_ratio: float = 0.95  # 95% of variance in 1-2 features

    # High-entropy sampling (uniform random probing)
    entropy_uniformity_threshold: float = 0.85  # near-uniform → suspicious

    # Inter-query timing regularity (bots query at fixed intervals)
    timing_regularity_threshold: float = 0.90  # coefficient of variation < 0.10


@dataclass(frozen=True)
class OutputPerturbationConfig:
    """Stochastic noise added to model outputs."""

    # Gaussian noise standard deviation added to probabilities
    logit_noise_std: float = 0.02

    # Top-k clipping: zero out all but top-k class probabilities
    top_k_classes: int = 5

    # Precision rounding (decimal places)
    output_precision: int = 2

    # Entropy smoothing — blend prediction toward uniform by this factor
    entropy_smoothing_alpha: float = 0.01

    # Minimum perturbation to apply even at risk_score=0
    base_noise_floor: float = 0.005


@dataclass(frozen=True)
class WatermarkConfig:
    """Probabilistic watermark embedded in model outputs."""

    # Secret key for watermark generation (MUST be set in production)
    secret_key: str = "aether-wm-default-change-me"

    # Bias strength: how much to shift probabilities toward watermark pattern
    bias_strength: float = 0.015

    # Minimum number of output classes for watermark to activate
    min_classes: int = 3

    # Watermark verification confidence threshold
    verification_threshold: float = 0.65


@dataclass(frozen=True)
class CanaryConfig:
    """Hidden trap inputs that indicate automated scraping."""

    # Secret seed for generating canary feature vectors
    secret_seed: str = "aether-canary-seed-change-me"

    # Number of canary patterns to generate
    num_canaries: int = 50

    # Feature-space tolerance for canary matching (L2 distance)
    match_tolerance: float = 0.05

    # Action on canary detection
    action: str = "throttle"  # "throttle", "block", "alert"

    # Cooldown after canary trigger (seconds)
    cooldown_seconds: int = 3600


@dataclass(frozen=True)
class RiskScorerConfig:
    """Extraction risk score computation."""

    # Weight for each signal in final risk score
    weight_query_velocity: float = 0.25
    weight_pattern_anomaly: float = 0.30
    weight_input_similarity: float = 0.25
    weight_entropy_probing: float = 0.20

    # Risk thresholds for response degradation
    low_threshold: float = 0.3
    medium_threshold: float = 0.6
    high_threshold: float = 0.8

    # Noise multiplier per risk tier (multiplied against base noise)
    noise_multiplier_low: float = 1.0
    noise_multiplier_medium: float = 3.0
    noise_multiplier_high: float = 8.0
    noise_multiplier_critical: float = 15.0

    # Exponential moving average decay for risk score smoothing
    ema_alpha: float = 0.2

    # Risk score decay rate (per second) when queries stop
    decay_rate_per_second: float = 0.001


@dataclass
class ExtractionDefenseConfig:
    """Top-level configuration for the model extraction defense layer."""

    # Master switches
    enable_extraction_defense: bool = True
    enable_output_noise: bool = True
    enable_watermark: bool = True
    enable_query_analysis: bool = True

    # Sub-configs
    rate_limiter: RateLimiterConfig = field(default_factory=RateLimiterConfig)
    pattern_detector: PatternDetectorConfig = field(default_factory=PatternDetectorConfig)
    output_perturbation: OutputPerturbationConfig = field(default_factory=OutputPerturbationConfig)
    watermark: WatermarkConfig = field(default_factory=WatermarkConfig)
    canary: CanaryConfig = field(default_factory=CanaryConfig)
    risk_scorer: RiskScorerConfig = field(default_factory=RiskScorerConfig)

    @classmethod
    def from_env(cls) -> ExtractionDefenseConfig:
        """Load configuration from environment variables with sensible defaults."""
        wm_key = os.getenv("WATERMARK_SECRET_KEY", "aether-wm-default-change-me")
        canary_seed = os.getenv("CANARY_SECRET_SEED", "aether-canary-seed-change-me")
        is_local = os.getenv("AETHER_ENV", "local").lower() == "local"
        if not is_local:
            if wm_key == "aether-wm-default-change-me":
                raise RuntimeError(
                    "WATERMARK_SECRET_KEY must be set to a non-default value in "
                    "non-local environments."
                )
            if canary_seed == "aether-canary-seed-change-me":
                raise RuntimeError(
                    "CANARY_SECRET_SEED must be set to a non-default value in "
                    "non-local environments."
                )
        return cls(
            enable_extraction_defense=os.getenv(
                "ENABLE_EXTRACTION_DEFENSE", "true"
            ).lower() == "true",
            enable_output_noise=os.getenv(
                "ENABLE_OUTPUT_NOISE", "true"
            ).lower() == "true",
            enable_watermark=os.getenv(
                "ENABLE_WATERMARK", "true"
            ).lower() == "true",
            enable_query_analysis=os.getenv(
                "ENABLE_QUERY_ANALYSIS", "true"
            ).lower() == "true",
            watermark=WatermarkConfig(secret_key=wm_key),
            canary=CanaryConfig(secret_seed=canary_seed),
        )
