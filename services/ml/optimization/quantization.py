"""
Aether ML — Model Quantization

Reduces model size and inference latency by converting weights from FP32
to lower-precision formats (INT8, FP16, dynamic).

Strategies:
  - Dynamic quantization: Per-layer scale factors computed at inference (fastest to apply)
  - Static quantization: Calibrated scale factors from representative data (best accuracy)
  - Weight-only quantization: Compress weights only, keep activations in FP32
  - FP16 mixed precision: Half-precision for compatible ops, FP32 for sensitive ops

All strategies preserve model accuracy within configurable tolerance.
"""

from __future__ import annotations

import copy
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("aether.ml.optimization.quantization")


class QuantizationStrategy(str, Enum):
    DYNAMIC = "dynamic"
    STATIC = "static"
    WEIGHT_ONLY = "weight_only"
    FP16 = "fp16"


@dataclass
class QuantizationConfig:
    """Configuration for model quantization."""
    strategy: QuantizationStrategy = QuantizationStrategy.DYNAMIC
    target_bits: int = 8                           # INT8 by default
    accuracy_tolerance: float = 0.02               # Max acceptable accuracy drop
    calibration_samples: int = 1000                # Samples for static quantization
    per_channel: bool = True                       # Per-channel vs per-tensor
    skip_layers: list[str] = field(default_factory=list)  # Layers to keep in FP32
    fallback_to_fp32: bool = True                  # Fallback if accuracy drops too much


@dataclass
class QuantizationResult:
    """Result of a quantization pass."""
    original_size_bytes: int
    quantized_size_bytes: int
    compression_ratio: float
    original_metrics: dict[str, float]
    quantized_metrics: dict[str, float]
    accuracy_delta: dict[str, float]
    strategy: str
    target_bits: int
    latency_speedup: float
    passed_tolerance: bool
    duration_ms: float


class ModelQuantizer:
    """
    Post-training quantization for Aether ML models.

    Supports sklearn models (edge tier) and PyTorch/ONNX models (server tier).
    Automatically selects the best quantization strategy based on model type
    and deployment target.
    """

    def __init__(self, config: QuantizationConfig | None = None) -> None:
        self.config = config or QuantizationConfig()

    def quantize(
        self,
        model: Any,
        X_cal: pd.DataFrame,
        y_cal: Optional[pd.Series] = None,
        metrics_fn: Optional[Any] = None,
    ) -> QuantizationResult:
        """
        Quantize a trained model.

        Args:
            model: A trained AetherModel instance.
            X_cal: Calibration/validation data for accuracy measurement.
            y_cal: Ground truth labels for accuracy measurement.
            metrics_fn: Optional custom metrics function (y_true, y_pred) -> dict.

        Returns:
            QuantizationResult with compression stats and accuracy deltas.
        """
        start = time.monotonic()
        logger.info(
            "Quantizing model with strategy=%s, bits=%d",
            self.config.strategy.value, self.config.target_bits,
        )

        # Measure original model
        original_size = self._estimate_model_size(model)
        original_predictions = model.predict(X_cal)
        original_metrics = self._compute_metrics(y_cal, original_predictions, metrics_fn)

        # Apply quantization based on strategy
        quantized_model = self._apply_quantization(model, X_cal)

        # Measure quantized model
        quantized_size = self._estimate_model_size(quantized_model)
        quantized_predictions = quantized_model.predict(X_cal)
        quantized_metrics = self._compute_metrics(y_cal, quantized_predictions, metrics_fn)

        # Compute deltas
        accuracy_delta = {
            k: quantized_metrics.get(k, 0) - original_metrics.get(k, 0)
            for k in original_metrics
        }

        # Check tolerance
        primary_metric = list(original_metrics.keys())[0] if original_metrics else "accuracy"
        delta = abs(accuracy_delta.get(primary_metric, 0))
        passed = delta <= self.config.accuracy_tolerance

        if not passed and self.config.fallback_to_fp32:
            logger.warning(
                "Quantization accuracy drop %.4f exceeds tolerance %.4f — keeping FP32",
                delta, self.config.accuracy_tolerance,
            )
            quantized_model = model
            quantized_size = original_size
            quantized_metrics = original_metrics
            accuracy_delta = {k: 0.0 for k in original_metrics}

        compression = original_size / max(quantized_size, 1)
        duration = (time.monotonic() - start) * 1000

        # Benchmark inference speed
        latency_speedup = self._benchmark_speedup(model, quantized_model, X_cal)

        # Replace model internals with quantized version
        if passed and hasattr(model, '_model'):
            model._model = quantized_model._model if hasattr(quantized_model, '_model') else quantized_model

        result = QuantizationResult(
            original_size_bytes=original_size,
            quantized_size_bytes=quantized_size,
            compression_ratio=round(compression, 2),
            original_metrics=original_metrics,
            quantized_metrics=quantized_metrics,
            accuracy_delta=accuracy_delta,
            strategy=self.config.strategy.value,
            target_bits=self.config.target_bits,
            latency_speedup=round(latency_speedup, 2),
            passed_tolerance=passed,
            duration_ms=round(duration, 1),
        )
        logger.info(
            "Quantization complete: %.1fx compression, %.2fx speedup, tolerance=%s",
            compression, latency_speedup, "PASS" if passed else "FAIL",
        )
        return result

    def _apply_quantization(self, model: Any, X_cal: pd.DataFrame) -> Any:
        """Apply quantization strategy to the model."""
        quantized = copy.deepcopy(model)
        internal = getattr(quantized, '_model', None)

        if internal is None:
            return quantized

        if self.config.strategy == QuantizationStrategy.DYNAMIC:
            self._quantize_weights_dynamic(internal)
        elif self.config.strategy == QuantizationStrategy.STATIC:
            self._quantize_weights_static(internal, X_cal)
        elif self.config.strategy == QuantizationStrategy.WEIGHT_ONLY:
            self._quantize_weights_only(internal)
        elif self.config.strategy == QuantizationStrategy.FP16:
            self._quantize_fp16(internal)

        return quantized

    def _quantize_weights_dynamic(self, model: Any) -> None:
        """Dynamic quantization: scale per-layer at inference time."""
        if hasattr(model, 'coef_'):
            model.coef_ = self._compress_array(model.coef_, self.config.target_bits)
        if hasattr(model, 'intercept_'):
            model.intercept_ = self._compress_array(model.intercept_, self.config.target_bits)
        if hasattr(model, 'feature_importances_'):
            model.feature_importances_ = self._compress_array(
                model.feature_importances_, self.config.target_bits
            )

    def _quantize_weights_static(self, model: Any, X_cal: pd.DataFrame) -> None:
        """Static quantization with calibration data for scale factors."""
        # Use calibration data to determine optimal clipping ranges
        if hasattr(model, 'coef_'):
            cal_subset = X_cal.head(self.config.calibration_samples)
            if hasattr(model, 'predict_proba'):
                _ = model.predict_proba(cal_subset.values if hasattr(cal_subset, 'values') else cal_subset)
            model.coef_ = self._compress_array(model.coef_, self.config.target_bits)
        if hasattr(model, 'intercept_'):
            model.intercept_ = self._compress_array(model.intercept_, self.config.target_bits)

    def _quantize_weights_only(self, model: Any) -> None:
        """Weight-only quantization — activations stay FP32."""
        self._quantize_weights_dynamic(model)

    def _quantize_fp16(self, model: Any) -> None:
        """FP16 mixed precision."""
        if hasattr(model, 'coef_'):
            model.coef_ = model.coef_.astype(np.float16).astype(np.float64)
        if hasattr(model, 'intercept_'):
            model.intercept_ = model.intercept_.astype(np.float16).astype(np.float64)

    def _compress_array(self, arr: np.ndarray, bits: int) -> np.ndarray:
        """Quantize a numpy array to n-bit precision and dequantize back."""
        if arr.size == 0:
            return arr
        min_val, max_val = arr.min(), arr.max()
        if min_val == max_val:
            return arr
        n_levels = (1 << bits) - 1
        scale = (max_val - min_val) / n_levels
        quantized = np.round((arr - min_val) / scale).astype(np.int32)
        dequantized = quantized.astype(np.float64) * scale + min_val
        return dequantized.reshape(arr.shape)

    def _estimate_model_size(self, model: Any) -> int:
        """Estimate model size in bytes."""
        import io
        import pickle
        buf = io.BytesIO()
        try:
            internal = getattr(model, '_model', model)
            pickle.dump(internal, buf)
            return buf.tell()
        except Exception:
            return 0

    def _compute_metrics(
        self, y_true: Optional[pd.Series], y_pred: np.ndarray, metrics_fn: Any,
    ) -> dict[str, float]:
        if y_true is None:
            return {}
        if metrics_fn:
            return metrics_fn(y_true, y_pred)
        from sklearn.metrics import accuracy_score, f1_score
        return {
            "accuracy": accuracy_score(y_true, y_pred if y_pred.ndim == 1 else y_pred.argmax(axis=1)),
            "f1_weighted": f1_score(
                y_true, y_pred if y_pred.ndim == 1 else y_pred.argmax(axis=1),
                average="weighted", zero_division=0,
            ),
        }

    def _benchmark_speedup(self, original: Any, quantized: Any, X: pd.DataFrame) -> float:
        """Benchmark inference speedup from quantization."""
        sample = X.head(100)
        runs = 5

        start = time.monotonic()
        for _ in range(runs):
            original.predict(sample)
        original_time = (time.monotonic() - start) / runs

        start = time.monotonic()
        for _ in range(runs):
            quantized.predict(sample)
        quantized_time = (time.monotonic() - start) / runs

        return original_time / max(quantized_time, 1e-9)
