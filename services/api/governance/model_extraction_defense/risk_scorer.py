"""
Aether Security — Extraction Risk Scorer

Combines signals from the rate limiter, pattern detector, and canary
detector into a single risk score:

    extraction_risk ∈ [0, 1]

The risk score determines how aggressively output perturbation is applied:
  - 0.0 – 0.3  → normal (minimal noise)
  - 0.3 – 0.6  → elevated (moderate noise)
  - 0.6 – 0.8  → high (aggressive noise)
  - 0.8 – 1.0  → critical (maximum degradation, consider blocking)

Uses exponential moving average (EMA) to smooth per-client scores
over time, with decay when queries stop.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from threading import Lock
from typing import Optional

from .config import RiskScorerConfig

logger = logging.getLogger("aether.security.risk_scorer")


@dataclass
class RiskAssessment:
    """Complete risk assessment for a single request."""

    # Final risk score
    risk_score: float = 0.0

    # Risk tier
    tier: str = "normal"  # "normal", "elevated", "high", "critical"

    # Noise multiplier to apply to output perturbation
    noise_multiplier: float = 1.0

    # Individual signal contributions
    velocity_signal: float = 0.0
    pattern_signal: float = 0.0
    similarity_signal: float = 0.0
    entropy_signal: float = 0.0
    canary_signal: float = 0.0

    # Whether to block the request entirely
    should_block: bool = False


class ClientRiskState:
    """EMA-smoothed risk state for a single client."""

    def __init__(self, alpha: float = 0.2, decay_rate: float = 0.001):
        self.ema_score: float = 0.0
        self.last_update: float = time.time()
        self.alpha = alpha
        self.decay_rate = decay_rate
        self.total_queries: int = 0
        self.canary_triggers: int = 0

    def update(self, raw_score: float) -> float:
        """Update EMA with a new raw score, applying time decay."""
        now = time.time()
        elapsed = now - self.last_update

        # Decay existing score based on time elapsed
        decayed = self.ema_score * max(0.0, 1.0 - self.decay_rate * elapsed)

        # EMA update
        self.ema_score = self.alpha * raw_score + (1 - self.alpha) * decayed
        self.last_update = now
        self.total_queries += 1

        return self.ema_score


class ExtractionRiskScorer:
    """
    Aggregates signals from defense components into a per-client risk score.
    """

    def __init__(self, config: Optional[RiskScorerConfig] = None):
        self.config = config or RiskScorerConfig()
        self._states: dict[str, ClientRiskState] = {}
        self._lock = Lock()

    def assess(
        self,
        api_key: str,
        velocity: dict[str, int],
        pattern_anomaly_score: float = 0.0,
        similarity_score: float = 0.0,
        entropy_score: float = 0.0,
        canary_triggered: bool = False,
    ) -> RiskAssessment:
        """
        Compute a risk assessment for a request.

        Args:
            api_key: Client identifier.
            velocity: Query counts from rate limiter (minute/hour/day).
            pattern_anomaly_score: From pattern detector (0-1).
            similarity_score: Input similarity clustering score (0-1).
            entropy_score: Entropy probing score (0-1).
            canary_triggered: Whether this request matched a canary.

        Returns:
            RiskAssessment with score, tier, and noise multiplier.
        """
        # Compute velocity signal
        velocity_signal = self._compute_velocity_signal(velocity)

        # Compute raw weighted score
        raw_score = (
            self.config.weight_query_velocity * velocity_signal
            + self.config.weight_pattern_anomaly * pattern_anomaly_score
            + self.config.weight_input_similarity * similarity_score
            + self.config.weight_entropy_probing * entropy_score
        )

        # Canary triggers spike the score
        canary_signal = 0.0
        if canary_triggered:
            canary_signal = 1.0
            raw_score = max(raw_score, 0.9)

        # Clamp to [0, 1]
        raw_score = max(0.0, min(1.0, raw_score))

        # Update EMA
        with self._lock:
            state = self._get_state(api_key)
            if canary_triggered:
                state.canary_triggers += 1
            smoothed = state.update(raw_score)

        # Determine tier and noise multiplier
        assessment = RiskAssessment(
            risk_score=round(smoothed, 4),
            velocity_signal=round(velocity_signal, 4),
            pattern_signal=round(pattern_anomaly_score, 4),
            similarity_signal=round(similarity_score, 4),
            entropy_signal=round(entropy_score, 4),
            canary_signal=canary_signal,
        )

        if smoothed >= self.config.high_threshold:
            assessment.tier = "critical"
            assessment.noise_multiplier = self.config.noise_multiplier_critical
            assessment.should_block = smoothed >= 0.95
        elif smoothed >= self.config.medium_threshold:
            assessment.tier = "high"
            assessment.noise_multiplier = self.config.noise_multiplier_high
        elif smoothed >= self.config.low_threshold:
            assessment.tier = "elevated"
            assessment.noise_multiplier = self.config.noise_multiplier_medium
        else:
            assessment.tier = "normal"
            assessment.noise_multiplier = self.config.noise_multiplier_low

        if assessment.tier != "normal":
            logger.info(
                "Risk assessment for %s: score=%.3f tier=%s multiplier=%.1f",
                api_key[:8] + "...",
                assessment.risk_score,
                assessment.tier,
                assessment.noise_multiplier,
            )

        return assessment

    def get_risk_score(self, api_key: str) -> float:
        """Return the current EMA risk score for a client."""
        with self._lock:
            state = self._states.get(api_key)
            if state is None:
                return 0.0
            # Apply time decay
            elapsed = time.time() - state.last_update
            return state.ema_score * max(0.0, 1.0 - self.config.decay_rate_per_second * elapsed)

    def get_all_scores(self) -> dict[str, float]:
        """Return current risk scores for all tracked clients."""
        with self._lock:
            return {
                key: self.get_risk_score(key)
                for key in self._states
            }

    def cleanup_expired(self, max_age_seconds: float = 86400) -> int:
        """Remove client states that have decayed to near-zero."""
        removed = 0
        cutoff = time.time() - max_age_seconds
        with self._lock:
            expired = [
                k for k, v in self._states.items()
                if v.last_update < cutoff and v.ema_score < 0.01
            ]
            for k in expired:
                del self._states[k]
                removed += 1
        return removed

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_state(self, api_key: str) -> ClientRiskState:
        if api_key not in self._states:
            self._states[api_key] = ClientRiskState(
                alpha=self.config.ema_alpha,
                decay_rate=self.config.decay_rate_per_second,
            )
        return self._states[api_key]

    def _compute_velocity_signal(self, velocity: dict[str, int]) -> float:
        """
        Convert raw query velocity into a [0, 1] risk signal.
        Higher velocity → higher signal.
        """
        minute_rate = velocity.get("minute", 0)
        hour_rate = velocity.get("hour", 0)

        # Normalize against expected "normal" usage patterns
        # Normal user: ~5-10 queries/minute, ~100-200/hour
        minute_score = min(1.0, minute_rate / 50.0)  # 50+ rpm → max
        hour_score = min(1.0, hour_rate / 500.0)  # 500+ rph → max

        return max(minute_score, hour_score)
