"""
Aether Security — Model Watermarking

Embeds a detectable probabilistic signature in model outputs using
deterministic token biasing. The watermark is:
  - Invisible to individual queries (noise-level bias)
  - Statistically detectable across many queries
  - Tied to a secret key (only Aether can verify)
  - Robust to moderate post-processing by the attacker

The approach: for each query, a deterministic pseudo-random bias pattern
is generated from the secret key + query fingerprint. Output probabilities
are shifted slightly toward the bias pattern. An extracted model trained
on these biased outputs will inherit the watermark.

Verification: given a suspect model and a set of probe inputs, compute
the expected bias pattern and measure correlation with the model's outputs.
High correlation → watermark detected → model was extracted from Aether.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Optional

import numpy as np

from .config import WatermarkConfig

logger = logging.getLogger("aether.security.watermark")


class ModelWatermark:
    """
    Probabilistic watermark embedder and verifier.

    The watermark is a subtle bias pattern derived from a keyed hash of
    the input features. It shifts output probabilities by a small amount
    that is undetectable per-query but statistically significant over
    thousands of queries.
    """

    def __init__(self, config: Optional[WatermarkConfig] = None):
        self.config = config or WatermarkConfig()
        self._key_bytes = self.config.secret_key.encode("utf-8")

    def embed(
        self,
        output_probs: np.ndarray,
        query_fingerprint: str,
    ) -> np.ndarray:
        """
        Embed watermark into a probability distribution.

        Args:
            output_probs: Raw model output probabilities (1D array).
            query_fingerprint: Deterministic fingerprint of the input
                (e.g., hash of sorted feature dict).

        Returns:
            Watermarked probability distribution (same shape).
        """
        if len(output_probs) < self.config.min_classes:
            return output_probs

        # Generate bias pattern from secret key + query fingerprint
        bias = self._generate_bias(query_fingerprint, len(output_probs))

        # Apply bias
        watermarked = output_probs + bias * self.config.bias_strength

        # Clamp and re-normalize
        watermarked = np.maximum(watermarked, 0.0)
        total = watermarked.sum()
        if total > 0:
            watermarked = watermarked / total
        else:
            watermarked = np.ones_like(output_probs) / len(output_probs)

        return watermarked

    def embed_scalar(
        self,
        value: float,
        query_fingerprint: str,
    ) -> float:
        """
        Embed watermark into a scalar output (e.g., single probability).
        Uses a directional bias: shifts value slightly up or down based
        on the keyed hash.
        """
        direction = self._generate_scalar_direction(query_fingerprint)
        biased = value + direction * self.config.bias_strength
        return max(0.0, min(1.0, biased))

    def verify(
        self,
        suspect_outputs: list[np.ndarray],
        query_fingerprints: list[str],
    ) -> float:
        """
        Verify whether a set of model outputs contain the watermark.

        Args:
            suspect_outputs: List of probability distributions from the
                suspect model, one per probe query.
            query_fingerprints: Corresponding query fingerprints.

        Returns:
            Watermark confidence score in [0, 1].
            > verification_threshold → watermark detected.
        """
        if len(suspect_outputs) != len(query_fingerprints):
            raise ValueError("Outputs and fingerprints must have equal length")

        if not suspect_outputs:
            return 0.0

        correlations = []
        for output, fingerprint in zip(suspect_outputs, query_fingerprints):
            if len(output) < self.config.min_classes:
                continue
            bias = self._generate_bias(fingerprint, len(output))
            # Correlation between expected bias and actual deviation from uniform
            uniform = np.ones_like(output) / len(output)
            deviation = output - uniform
            corr = np.corrcoef(bias, deviation)[0, 1]
            if not np.isnan(corr):
                correlations.append(corr)

        if not correlations:
            return 0.0

        avg_correlation = np.mean(correlations)
        # Map correlation to a [0, 1] confidence
        confidence = max(0.0, min(1.0, (avg_correlation + 1) / 2))
        return confidence

    def is_watermarked(
        self,
        suspect_outputs: list[np.ndarray],
        query_fingerprints: list[str],
    ) -> bool:
        """Check if outputs contain the watermark above the confidence threshold."""
        score = self.verify(suspect_outputs, query_fingerprints)
        return score >= self.config.verification_threshold

    # ------------------------------------------------------------------
    # Internal methods
    # ------------------------------------------------------------------

    def _generate_bias(self, fingerprint: str, n_classes: int) -> np.ndarray:
        """
        Generate a deterministic bias vector from the secret key
        and query fingerprint.

        The bias vector sums to zero (so it doesn't change the expected
        probability mass) and has controlled magnitude.
        """
        # HMAC-SHA256 gives us a deterministic 256-bit seed per query
        mac = hmac.new(self._key_bytes, fingerprint.encode("utf-8"), hashlib.sha256)
        seed_int = int.from_bytes(mac.digest()[:8], "big")

        rng = np.random.default_rng(seed_int)
        raw = rng.standard_normal(n_classes)

        # Zero-center so bias sums to zero
        raw = raw - raw.mean()

        # Normalize to unit L2 norm
        norm = np.linalg.norm(raw)
        if norm > 0:
            raw = raw / norm

        return raw

    def _generate_scalar_direction(self, fingerprint: str) -> float:
        """Generate a +1 or -1 direction for scalar watermarking."""
        mac = hmac.new(self._key_bytes, fingerprint.encode("utf-8"), hashlib.sha256)
        # Use first byte to determine direction
        return 1.0 if mac.digest()[0] > 127 else -1.0

    @staticmethod
    def fingerprint_features(features: dict) -> str:
        """Generate a deterministic fingerprint from a feature dictionary."""
        sorted_items = sorted(features.items())
        canonical = "|".join(f"{k}={v}" for k, v in sorted_items)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
