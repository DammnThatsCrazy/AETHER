"""
Aether Security — Output Perturbation Layer

Wraps model outputs with configurable stochastic policies to degrade
the quality of extracted models while preserving utility for legitimate users.

Perturbation strategies:
  1. Logit noise — additive Gaussian noise to probabilities
  2. Top-k clipping — zero out all but top-k class probabilities
  3. Precision rounding — reduce decimal precision
  4. Entropy smoothing — blend predictions toward uniform distribution

All perturbations scale with the extraction risk score: low risk → minimal
noise, high risk → aggressive degradation.
"""

from __future__ import annotations

import logging
from typing import Optional, Union

import numpy as np

from .config import OutputPerturbationConfig

logger = logging.getLogger("aether.security.perturbation")


class OutputPerturbationLayer:
    """
    Applies stochastic perturbation to model outputs.

    Usage:
        layer = OutputPerturbationLayer(config)
        perturbed = layer.perturb(raw_output, risk_score=0.3)
    """

    def __init__(self, config: Optional[OutputPerturbationConfig] = None):
        self.config = config or OutputPerturbationConfig()
        self._rng = np.random.default_rng()

    def perturb(
        self,
        output: Union[float, list[float], np.ndarray, dict],
        risk_score: float = 0.0,
    ) -> Union[float, list[float], dict]:
        """
        Apply perturbation to a model output.

        Args:
            output: Raw model output (scalar probability, probability vector,
                    or dict of named outputs).
            risk_score: Extraction risk score in [0, 1]. Higher risk → more noise.

        Returns:
            Perturbed output in the same format as input.
        """
        if isinstance(output, bool):
            return output  # booleans pass through unchanged
        if isinstance(output, dict):
            return self._perturb_dict(output, risk_score)
        elif isinstance(output, (list, np.ndarray)):
            return self._perturb_vector(np.asarray(output, dtype=float), risk_score).tolist()
        elif isinstance(output, (int, float)):
            return self._perturb_scalar(float(output), risk_score)
        return output

    def _perturb_scalar(self, value: float, risk_score: float) -> float:
        """Perturb a single probability/score value."""
        noise_std = self._effective_noise(risk_score)
        noised = value + self._rng.normal(0, noise_std)

        # Entropy smoothing: blend toward 0.5
        alpha = self.config.entropy_smoothing_alpha * (1 + risk_score * 5)
        smoothed = (1 - alpha) * noised + alpha * 0.5

        # Clamp to [0, 1] for probabilities
        clamped = max(0.0, min(1.0, smoothed))

        return round(clamped, self.config.output_precision)

    def _perturb_vector(self, probs: np.ndarray, risk_score: float) -> np.ndarray:
        """Perturb a probability distribution vector."""
        if probs.ndim == 0:
            return np.array(self._perturb_scalar(float(probs), risk_score))

        # 1. Top-k clipping
        if len(probs) > self.config.top_k_classes:
            sorted_idx = np.argsort(probs)[::-1]
            clipped = np.zeros_like(probs)
            top_k_idx = sorted_idx[: self.config.top_k_classes]
            clipped[top_k_idx] = probs[top_k_idx]
            probs = clipped

        # 2. Additive Gaussian noise
        noise_std = self._effective_noise(risk_score)
        noise = self._rng.normal(0, noise_std, size=probs.shape)
        noised = probs + noise

        # 3. Entropy smoothing
        alpha = self.config.entropy_smoothing_alpha * (1 + risk_score * 5)
        uniform = np.ones_like(noised) / len(noised)
        smoothed = (1 - alpha) * noised + alpha * uniform

        # 4. Clamp and re-normalize
        smoothed = np.maximum(smoothed, 0.0)
        total = smoothed.sum()
        if total > 0:
            smoothed = smoothed / total
        else:
            smoothed = uniform

        # 5. Precision rounding
        rounded = np.round(smoothed, self.config.output_precision)

        # Re-normalize after rounding to ensure sum ≈ 1
        total = rounded.sum()
        if total > 0:
            rounded = rounded / total

        return rounded

    def _perturb_dict(self, output: dict, risk_score: float) -> dict:
        """Perturb all numeric values in a dict output."""
        result = {}
        for key, value in output.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                result[key] = self._perturb_scalar(float(value), risk_score)
            elif isinstance(value, (list, np.ndarray)):
                arr = np.asarray(value, dtype=float)
                result[key] = self._perturb_vector(arr, risk_score).tolist()
            else:
                result[key] = value
        return result

    def _effective_noise(self, risk_score: float) -> float:
        """Compute effective noise std based on risk score."""
        base = max(self.config.base_noise_floor, self.config.logit_noise_std)
        # Scale noise with risk: low risk → base noise, high risk → 5x base
        multiplier = 1.0 + risk_score * 4.0
        return base * multiplier
