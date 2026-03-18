"""
Aether Security — Extraction Defense Layer (Facade)

Orchestrates all defense components into a single entry point for
pre-request and post-response processing. Designed to wrap the existing
inference pipeline as middleware without modifying core model code.

Usage:
    defense = ExtractionDefenseLayer.from_env()

    # Before inference:
    pre_result = defense.pre_request(api_key, ip, features, model_name)
    if pre_result.blocked:
        return 429  # or 403

    # Run inference normally:
    raw_output = model.predict(features)

    # After inference:
    safe_output = defense.post_response(api_key, raw_output, features)
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Optional, Union

import numpy as np

from .config import ExtractionDefenseConfig
from .rate_limiter import QueryRateLimiter, RateLimitCheck
from .pattern_detector import QueryPatternDetector, PatternAnalysis
from .output_perturbation import OutputPerturbationLayer
from .watermark import ModelWatermark
from .canary_detector import CanaryInputDetector
from .risk_scorer import ExtractionRiskScorer, RiskAssessment
from .metrics import DefenseMetrics

logger = logging.getLogger("aether.security.defense_layer")


@dataclass
class PreRequestResult:
    """Result of pre-request defense processing."""

    blocked: bool = False
    block_reason: str = ""
    rate_limit: Optional[RateLimitCheck] = None
    risk_assessment: Optional[RiskAssessment] = None
    retry_after_seconds: int = 0


@dataclass
class PostResponseResult:
    """Result of post-response defense processing."""

    output: Any = None
    risk_score: float = 0.0
    noise_applied: bool = False
    watermark_applied: bool = False


class ExtractionDefenseLayer:
    """
    Facade that orchestrates all extraction defense components.

    This class is the primary integration point. Attach it as middleware
    or call pre_request / post_response around inference calls.
    """

    # Common feature dimensionalities observed — canaries are lazily
    # generated on the first request so we can infer dimensionality.
    _CANARY_DIMS_INITIALIZED: set[int] = set()

    def __init__(self, config: Optional[ExtractionDefenseConfig] = None):
        self.config = config or ExtractionDefenseConfig()

        # Initialize components
        self.rate_limiter = QueryRateLimiter(self.config.rate_limiter)
        self.pattern_detector = QueryPatternDetector(self.config.pattern_detector)
        self.perturbation = OutputPerturbationLayer(self.config.output_perturbation)
        self.watermark = ModelWatermark(self.config.watermark)
        self.canary_detector = CanaryInputDetector(self.config.canary)
        self.risk_scorer = ExtractionRiskScorer(self.config.risk_scorer)
        self.metrics = DefenseMetrics()

        self._canary_init_lock = threading.Lock()

        logger.info(
            "Extraction defense initialized: "
            "defense=%s noise=%s watermark=%s analysis=%s",
            self.config.enable_extraction_defense,
            self.config.enable_output_noise,
            self.config.enable_watermark,
            self.config.enable_query_analysis,
        )

    @classmethod
    def from_env(cls) -> ExtractionDefenseLayer:
        """Create a defense layer with config from environment variables."""
        return cls(ExtractionDefenseConfig.from_env())

    # ------------------------------------------------------------------
    # Canary lazy initialization
    # ------------------------------------------------------------------

    def _ensure_canaries(self, n_features: int) -> None:
        """
        Lazily generate canary inputs on the first request that has
        enough features. Thread-safe — only initialises once per
        dimensionality.
        """
        if n_features < 2:
            return
        if n_features in self._CANARY_DIMS_INITIALIZED:
            return
        with self._canary_init_lock:
            if n_features in self._CANARY_DIMS_INITIALIZED:
                return  # double-check after acquiring lock
            self.canary_detector.generate_canaries(n_features)
            self._CANARY_DIMS_INITIALIZED.add(n_features)
            logger.info(
                "Canary inputs lazily generated for %d-dimensional feature space",
                n_features,
            )

    # ------------------------------------------------------------------
    # Pre-request processing
    # ------------------------------------------------------------------

    def pre_request(
        self,
        api_key: str,
        ip_address: str,
        features: dict[str, Any],
        model_name: str = "",
        batch_size: int = 1,
    ) -> PreRequestResult:
        """
        Process a request BEFORE inference.

        Checks rate limits, records query for pattern analysis, checks canaries,
        and computes the extraction risk score.

        Args:
            api_key: Client API key.
            ip_address: Client IP address.
            features: Input feature dictionary.
            model_name: Name of the target model.
            batch_size: Number of instances in batch requests.

        Returns:
            PreRequestResult — check .blocked to decide whether to proceed.
        """
        if not self.config.enable_extraction_defense:
            return PreRequestResult()

        self.metrics.record_request(api_key, model_name)
        result = PreRequestResult()

        # 1. Rate limiting
        cost = max(1, batch_size * self.config.rate_limiter.batch_instance_cost)
        rl_check = self.rate_limiter.check(api_key, ip_address, cost)
        result.rate_limit = rl_check

        if not rl_check.allowed:
            result.blocked = True
            result.block_reason = f"Rate limit exceeded ({rl_check.source}/{rl_check.window})"
            result.retry_after_seconds = rl_check.retry_after_seconds
            self.metrics.record_block(api_key, "rate_limit", rl_check.window)
            return result

        # 2. Check canary cooldown first (cheap check before canary matching)
        if self.canary_detector.is_in_cooldown(api_key):
            result.blocked = True
            result.block_reason = "Client in security cooldown"
            result.retry_after_seconds = self.config.canary.cooldown_seconds
            self.metrics.record_block(api_key, "canary_cooldown")
            return result

        # 3. Canary check — lazy-init canaries from observed feature dimensionality
        float_features = {k: float(v) for k, v in features.items() if isinstance(v, (int, float))}
        self._ensure_canaries(len(float_features))

        canary_result = self.canary_detector.check(float_features, api_key, ip_address)
        if canary_result.is_canary:
            self.metrics.record_canary_trigger(api_key, canary_result.canary_id)
            if canary_result.action == "block":
                result.blocked = True
                result.block_reason = "Request blocked by security policy"
                self.metrics.record_block(api_key, "canary_block")
                return result
            elif canary_result.action == "throttle":
                # Throttle: client enters cooldown and this request proceeds
                # but with an inflated risk score (handled below via
                # canary_triggered=True in risk_scorer.assess).
                logger.warning(
                    "Canary throttle for %s — request proceeds with elevated risk",
                    api_key[:8] + "...",
                )
            # "alert": log only, no blocking or throttling — risk scorer
            # still sees canary_triggered=True so noise increases.

        # 4. Record query for pattern analysis
        if self.config.enable_query_analysis:
            self.pattern_detector.record_query(api_key, float_features, model_name)

        # 5. Compute risk score
        velocity = self.rate_limiter.get_query_velocity(api_key)
        pattern_analysis = PatternAnalysis()

        if self.config.enable_query_analysis:
            pattern_analysis = self.pattern_detector.analyze(api_key)

        risk = self.risk_scorer.assess(
            api_key=api_key,
            velocity=velocity,
            pattern_anomaly_score=pattern_analysis.anomaly_score,
            similarity_score=pattern_analysis.similarity_score,
            entropy_score=pattern_analysis.entropy_score,
            canary_triggered=canary_result.is_canary,
        )
        result.risk_assessment = risk
        self.metrics.record_risk_score(api_key, risk.risk_score, risk.tier)

        if risk.should_block:
            result.blocked = True
            result.block_reason = "Extraction risk score exceeds threshold"
            self.metrics.record_block(api_key, "risk_score")
            return result

        return result

    # ------------------------------------------------------------------
    # Post-response processing
    # ------------------------------------------------------------------

    def post_response(
        self,
        api_key: str,
        raw_output: Any,
        features: dict[str, Any],
        risk_score: Optional[float] = None,
    ) -> PostResponseResult:
        """
        Process a response AFTER inference.

        Applies output perturbation and watermarking based on the
        client's risk score.

        Args:
            api_key: Client API key.
            raw_output: Raw model output (scalar, vector, or dict).
            features: Input features (for watermark fingerprinting).
            risk_score: Override risk score (uses stored score if None).

        Returns:
            PostResponseResult with the perturbed/watermarked output.
        """
        if not self.config.enable_extraction_defense:
            return PostResponseResult(output=raw_output)

        # Get risk score
        if risk_score is None:
            risk_score = self.risk_scorer.get_risk_score(api_key)

        result = PostResponseResult(output=raw_output, risk_score=risk_score)

        # 1. Output perturbation
        if self.config.enable_output_noise:
            result.output = self.perturbation.perturb(result.output, risk_score)
            result.noise_applied = True

        # 2. Watermark embedding
        if self.config.enable_watermark:
            fingerprint = ModelWatermark.fingerprint_features(features)
            output = result.output

            if isinstance(output, (list, np.ndarray)):
                arr = np.asarray(output, dtype=float)
                if arr.ndim == 1 and len(arr) >= self.watermark.config.min_classes:
                    result.output = self.watermark.embed(arr, fingerprint).tolist()
                    result.watermark_applied = True
            elif isinstance(output, dict):
                # Watermark all probability-like arrays and scalar numerics
                for key, value in output.items():
                    if isinstance(value, (list, np.ndarray)):
                        arr = np.asarray(value, dtype=float)
                        if arr.ndim == 1 and len(arr) >= self.watermark.config.min_classes:
                            output[key] = self.watermark.embed(arr, fingerprint).tolist()
                            result.watermark_applied = True
                    elif isinstance(value, (int, float)) and not isinstance(value, bool):
                        output[key] = self.watermark.embed_scalar(float(value), fingerprint)
                        result.watermark_applied = True
                result.output = output
            elif isinstance(output, (int, float)) and not isinstance(output, bool):
                result.output = self.watermark.embed_scalar(float(output), fingerprint)
                result.watermark_applied = True

        return result

    # ------------------------------------------------------------------
    # Monitoring & management
    # ------------------------------------------------------------------

    def get_client_risk(self, api_key: str) -> float:
        """Return the current risk score for a client."""
        return self.risk_scorer.get_risk_score(api_key)

    def get_all_risk_scores(self) -> dict[str, float]:
        """Return risk scores for all tracked clients."""
        return self.risk_scorer.get_all_scores()

    def get_canary_triggers(self) -> list:
        """Return all canary trigger events."""
        return self.canary_detector.get_all_triggers()

    def get_metrics_snapshot(self) -> dict:
        """Return a snapshot of all defense metrics for monitoring."""
        return self.metrics.snapshot()

    def cleanup(self) -> dict[str, int]:
        """Run periodic cleanup across all components."""
        return {
            "rate_limiter": self.rate_limiter.cleanup_expired(),
            "pattern_detector": self.pattern_detector.cleanup_expired(),
            "risk_scorer": self.risk_scorer.cleanup_expired(),
        }
