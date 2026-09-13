"""
Aether Shared — Extraction Risk Scorer (Sibling Score)

Independent from TrustScore. Computes extraction risk from:
    - Identity fabric dimensions
    - Distributed budget state
    - Fraud signals adapted to ML inference
    - Expectation engine signals
    - Cache similarity signals
    - Graph / cluster features
    - Endpoint and model sensitivity tier

Output: 0–100 score with band (green/yellow/orange/red), reasons, and
policy recommendation. Consumed by the ExtractionPolicyEngine.
"""

from __future__ import annotations


from shared.logger.logger import get_logger, metrics
from shared.scoring.extraction_models import (
    ExtractionIdentity,
    ExtractionRiskAssessment,
    ExtractionRiskBand,
    ExtractionSignal,
    ModelSensitivityTier,
    get_model_tier,
)

logger = get_logger("aether.scoring.extraction")


# ═══════════════════════════════════════════════════════════════════════════
# SIGNAL WEIGHTS
# ═══════════════════════════════════════════════════════════════════════════

# Weight each signal category in the composite extraction score.
# These sum to ~1.0 but are normalized so exact sum doesn't matter.
SIGNAL_WEIGHTS: dict[str, float] = {
    "self_rate_deviation": 0.12,
    "model_enumeration_signal": 0.10,
    "feature_sweep_signal": 0.15,
    "boundary_probe_signal": 0.12,
    "near_duplicate_burst_signal": 0.05,
    "batch_usage_deviation": 0.08,
    "unique_coverage_expansion_signal": 0.12,
    "confidence_harvest_signal": 0.10,
    "identity_churn_signal": 0.08,
    "device_geo_contradiction_signal": 0.05,
    "budget_pressure": 0.03,
}

# Tier multipliers — Tier 1 models produce higher risk scores for same behavior
TIER_MULTIPLIERS: dict[ModelSensitivityTier, float] = {
    ModelSensitivityTier.TIER_1_CRITICAL: 1.3,
    ModelSensitivityTier.TIER_2_HIGH: 1.0,
    ModelSensitivityTier.TIER_3_STANDARD: 0.8,
}


# ═══════════════════════════════════════════════════════════════════════════
# EXTRACTION RISK SCORER
# ═══════════════════════════════════════════════════════════════════════════

class ExtractionRiskScorer:
    """
    Sibling score to TrustScore — independent extraction risk assessment.

    Does NOT merge into TrustScore. Both may consume overlapping signals
    but the scoring, thresholds, and policy engine are completely separate.
    """

    def __init__(self) -> None:
        self._ema_scores: dict[str, float] = {}  # actor_key → smoothed score
        self._ema_alpha = 0.3  # Higher = more responsive to recent behavior

    def score(
        self,
        identity: ExtractionIdentity,
        expectation_signals: list[ExtractionSignal],
        model_name: str = "",
        budget_utilization: float = 0.0,
        canary_triggered: bool = False,
        fraud_score: float = 0.0,
    ) -> ExtractionRiskAssessment:
        """
        Compute extraction risk assessment.

        Args:
            identity: Normalized caller identity.
            expectation_signals: Signals from the ExtractionExpectationEngine.
            model_name: Target model name.
            budget_utilization: 0–1 fraction of budget consumed.
            canary_triggered: Whether a canary input was detected.
            fraud_score: Existing fraud composite score (0–100) for cross-signal.

        Returns:
            ExtractionRiskAssessment with score 0–100, band, reasons, and
            policy recommendation.
        """
        tier = get_model_tier(model_name)
        tier_mult = TIER_MULTIPLIERS.get(tier, 1.0)
        actor_key = identity.primary_key

        # ── Aggregate expectation signals ────────────────────────────
        signal_map: dict[str, float] = {}
        for sig in expectation_signals:
            signal_map[sig.name] = sig.value

        # ── Add budget pressure as a signal ──────────────────────────
        signal_map["budget_pressure"] = budget_utilization

        # ── Compute weighted raw score ───────────────────────────────
        total_weight = sum(SIGNAL_WEIGHTS.get(name, 0.05) for name in signal_map)
        weighted_sum = sum(
            signal_map[name] * SIGNAL_WEIGHTS.get(name, 0.05)
            for name in signal_map
        )
        raw_score = (weighted_sum / max(total_weight, 0.01)) * 100.0

        # ── Apply tier multiplier ────────────────────────────────────
        raw_score *= tier_mult

        # ── Canary trigger escalation ────────────────────────────────
        if canary_triggered:
            raw_score = max(raw_score, 70.0)  # Floor at orange band

        # ── Cross-signal from fraud engine ───────────────────────────
        if fraud_score > 50:
            raw_score += (fraud_score - 50) * 0.2  # Mild boost from fraud

        # ── Clamp to 0–100 ───────────────────────────────────────────
        raw_score = max(0.0, min(100.0, raw_score))

        # ── EMA smoothing ────────────────────────────────────────────
        prev = self._ema_scores.get(actor_key, 0.0)
        smoothed = self._ema_alpha * raw_score + (1 - self._ema_alpha) * prev
        self._ema_scores[actor_key] = smoothed

        # ── Determine band ───────────────────────────────────────────
        band = ExtractionRiskAssessment.band_from_score(smoothed)

        # ── Build reasons list ───────────────────────────────────────
        reasons = _build_reasons(expectation_signals, canary_triggered, budget_utilization)

        # ── Policy recommendation ────────────────────────────────────
        policy = _recommend_policy(band, tier)

        assessment = ExtractionRiskAssessment(
            score=smoothed,
            band=band,
            reasons=reasons,
            signals=expectation_signals,
            policy_recommendation=policy,
            identity=identity,
        )

        metrics.increment(
            "extraction_risk_scored",
            labels={"band": band.value, "tier": tier.value},
        )

        if band in (ExtractionRiskBand.ORANGE, ExtractionRiskBand.RED):
            logger.warning(
                "Extraction risk %s for %s: score=%.1f band=%s model=%s",
                "ELEVATED" if band == ExtractionRiskBand.ORANGE else "CRITICAL",
                actor_key[:12] + "...",
                smoothed,
                band.value,
                model_name,
            )

        return assessment


# ═══════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _build_reasons(
    signals: list[ExtractionSignal],
    canary_triggered: bool,
    budget_utilization: float,
) -> list[str]:
    """Build human-readable reason strings from signals."""
    reasons = []
    for sig in sorted(signals, key=lambda s: -s.value):
        if sig.value > 0.3:
            reasons.append(f"{sig.name}: {sig.value:.2f} ({sig.severity.value})")
    if canary_triggered:
        reasons.insert(0, "canary_input_detected")
    if budget_utilization > 0.8:
        reasons.append(f"budget_pressure: {budget_utilization:.0%}")
    return reasons[:10]  # Cap at 10 reasons


def _recommend_policy(
    band: ExtractionRiskBand,
    tier: ModelSensitivityTier,
) -> str:
    """Map risk band + tier to a policy recommendation string."""
    if band == ExtractionRiskBand.RED:
        return "deny"
    if band == ExtractionRiskBand.ORANGE:
        if tier == ModelSensitivityTier.TIER_1_CRITICAL:
            return "deny"
        return "restrict"
    if band == ExtractionRiskBand.YELLOW:
        if tier == ModelSensitivityTier.TIER_1_CRITICAL:
            return "restrict"
        return "reduce_disclosure"
    return "allow"
