"""
Aether ML — Unified Optimization Pipeline

Orchestrates Quantization → Distillation → Pruning in a single pass.
Configurable per-model optimization profiles ensure each model gets
the right combination of techniques for its deployment target.

Usage:
    pipeline = OptimizationPipeline()
    result = pipeline.optimize(
        model=trained_model,
        X_train=X_train, y_train=y_train,
        X_val=X_val, y_val=y_val,
    )
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from optimization.quantization import ModelQuantizer, QuantizationConfig, QuantizationStrategy, QuantizationResult
from optimization.distillation import ModelDistiller, DistillationConfig, DistillationResult
from optimization.pruning import ModelPruner, PruningConfig, PruningStrategy, PruningResult

logger = logging.getLogger("aether.ml.optimization.pipeline")


# ---------------------------------------------------------------------------
# Optimization Result
# ---------------------------------------------------------------------------

@dataclass
class OptimizationResult:
    """Combined result from the full optimization pipeline."""
    model_name: str
    quantization: QuantizationResult | None = None
    distillation: DistillationResult | None = None
    pruning: PruningResult | None = None
    original_size_bytes: int = 0
    optimized_size_bytes: int = 0
    total_compression: float = 1.0
    original_metrics: dict[str, float] = field(default_factory=dict)
    optimized_metrics: dict[str, float] = field(default_factory=dict)
    accuracy_retention: float = 1.0
    total_duration_ms: float = 0.0
    steps_applied: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"=== Optimization: {self.model_name} ===",
            f"  Steps: {', '.join(self.steps_applied) or 'none'}",
            f"  Size: {self.original_size_bytes:,} → {self.optimized_size_bytes:,} bytes ({self.total_compression:.1f}x)",
            f"  Accuracy retention: {self.accuracy_retention:.2%}",
            f"  Duration: {self.total_duration_ms:.0f}ms",
        ]
        if self.quantization:
            lines.append(f"  Quantization: {self.quantization.strategy} {self.quantization.target_bits}-bit, "
                        f"{self.quantization.compression_ratio:.1f}x compression")
        if self.distillation:
            lines.append(f"  Distillation: {self.distillation.mode}, "
                        f"retention={self.distillation.accuracy_retention:.2%}")
        if self.pruning:
            lines.append(f"  Pruning: {self.pruning.strategy}, "
                        f"sparsity={self.pruning.sparsity_achieved:.1%}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Pre-built Optimization Profiles
# ---------------------------------------------------------------------------

EDGE_PROFILE = {
    "quantization": QuantizationConfig(
        strategy=QuantizationStrategy.DYNAMIC,
        target_bits=8,
        accuracy_tolerance=0.02,
    ),
    "pruning": PruningConfig(
        strategy=PruningStrategy.MAGNITUDE,
        target_sparsity=0.3,
        accuracy_tolerance=0.02,
    ),
}

SERVER_PROFILE = {
    "quantization": QuantizationConfig(
        strategy=QuantizationStrategy.FP16,
        target_bits=16,
        accuracy_tolerance=0.01,
    ),
    "pruning": PruningConfig(
        strategy=PruningStrategy.STRUCTURED,
        target_sparsity=0.2,
        accuracy_tolerance=0.01,
    ),
}

AGGRESSIVE_PROFILE = {
    "quantization": QuantizationConfig(
        strategy=QuantizationStrategy.STATIC,
        target_bits=8,
        accuracy_tolerance=0.03,
    ),
    "pruning": PruningConfig(
        strategy=PruningStrategy.ITERATIVE,
        target_sparsity=0.5,
        accuracy_tolerance=0.03,
        iterative_rounds=5,
    ),
}


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class OptimizationPipeline:
    """
    Unified optimization pipeline: Prune → Quantize → (optional) Distill.

    Order matters: pruning first removes dead weights, then quantization
    compresses the remaining weights. Distillation is an optional step
    when transferring from server to edge models.
    """

    def __init__(
        self,
        quantization: QuantizationConfig | None = None,
        distillation: DistillationConfig | None = None,
        pruning: PruningConfig | None = None,
        profile: str | None = None,
    ) -> None:
        # Load profile defaults if specified
        if profile == "edge":
            defaults = EDGE_PROFILE
        elif profile == "server":
            defaults = SERVER_PROFILE
        elif profile == "aggressive":
            defaults = AGGRESSIVE_PROFILE
        else:
            defaults = {}

        self.quantization_config = quantization or defaults.get("quantization")
        self.distillation_config = distillation or defaults.get("distillation")
        self.pruning_config = pruning or defaults.get("pruning")

    def optimize(
        self,
        model: Any,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: pd.DataFrame,
        y_val: pd.Series,
        model_name: str = "unknown",
        teacher: Any | None = None,
        feature_names: list[str] | None = None,
    ) -> OptimizationResult:
        """
        Run the full optimization pipeline.

        Args:
            model: Trained model to optimize.
            X_train: Training data (for fine-tuning and distillation).
            y_train: Training labels.
            X_val: Validation data (for accuracy measurement).
            y_val: Validation labels.
            model_name: Human-readable model name for logging.
            teacher: Optional teacher model for distillation.
            feature_names: Optional feature names for pruning reports.

        Returns:
            OptimizationResult with combined stats.
        """
        start = time.monotonic()
        logger.info("Starting optimization pipeline for '%s'", model_name)

        result = OptimizationResult(model_name=model_name)

        # Measure baseline
        baseline_predictions = model.predict(X_val)
        result.original_metrics = self._compute_metrics(y_val, baseline_predictions)
        result.original_size_bytes = self._estimate_size(model)

        # Step 1: Pruning (remove dead weights first)
        if self.pruning_config:
            logger.info("[1/3] Pruning...")
            pruner = ModelPruner(self.pruning_config)
            result.pruning = pruner.prune(
                model, X_train, y_train, X_val, y_val, feature_names,
            )
            result.steps_applied.append("pruning")

        # Step 2: Quantization (compress remaining weights)
        if self.quantization_config:
            logger.info("[2/3] Quantizing...")
            quantizer = ModelQuantizer(self.quantization_config)
            result.quantization = quantizer.quantize(model, X_val, y_val)
            result.steps_applied.append("quantization")

        # Step 3: Distillation (optional, requires teacher)
        if self.distillation_config and teacher is not None:
            logger.info("[3/3] Distilling from teacher...")
            distiller = ModelDistiller(self.distillation_config)
            result.distillation = distiller.distill(
                teacher, model, X_train, y_train, X_val, y_val,
            )
            result.steps_applied.append("distillation")

        # Measure final
        final_predictions = model.predict(X_val)
        result.optimized_metrics = self._compute_metrics(y_val, final_predictions)
        result.optimized_size_bytes = self._estimate_size(model)
        result.total_compression = round(
            result.original_size_bytes / max(result.optimized_size_bytes, 1), 2,
        )

        # Accuracy retention
        primary = list(result.original_metrics.keys())[0] if result.original_metrics else "accuracy"
        orig_acc = result.original_metrics.get(primary, 1.0)
        opt_acc = result.optimized_metrics.get(primary, 0.0)
        result.accuracy_retention = round(opt_acc / max(orig_acc, 1e-9), 4)

        result.total_duration_ms = round((time.monotonic() - start) * 1000, 1)

        logger.info(result.summary())
        return result

    def _compute_metrics(self, y_true: pd.Series, y_pred) -> dict[str, float]:
        import numpy as np
        from sklearn.metrics import accuracy_score, f1_score
        y_p = y_pred if hasattr(y_pred, 'ndim') and y_pred.ndim == 1 else np.array(y_pred)
        return {
            "accuracy": accuracy_score(y_true, y_p),
            "f1_weighted": f1_score(y_true, y_p, average="weighted", zero_division=0),
        }

    def _estimate_size(self, model: Any) -> int:
        import io
        import pickle
        buf = io.BytesIO()
        try:
            internal = getattr(model, '_model', model)
            pickle.dump(internal, buf)
            return buf.tell()
        except Exception:
            return 0
