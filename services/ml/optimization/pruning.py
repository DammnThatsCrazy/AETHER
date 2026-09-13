"""
Aether ML — Model Pruning

Removes redundant weights, neurons, and branches to reduce model complexity
while maintaining prediction accuracy.

Strategies:
  - Magnitude pruning: Zero out weights below a threshold (unstructured)
  - Structured pruning: Remove entire neurons/features based on importance
  - Iterative pruning: Gradually increase sparsity with fine-tuning between rounds
  - Sensitivity-aware: Per-layer pruning ratios based on layer sensitivity analysis

Pruning is applied post-training and followed by optional fine-tuning to
recover any accuracy loss.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger("aether.ml.optimization.pruning")


class PruningStrategy(str, Enum):
    MAGNITUDE = "magnitude"
    STRUCTURED = "structured"
    ITERATIVE = "iterative"
    SENSITIVITY = "sensitivity"


@dataclass
class PruningConfig:
    """Configuration for model pruning."""
    strategy: PruningStrategy = PruningStrategy.MAGNITUDE
    target_sparsity: float = 0.3           # Fraction of weights to prune (0-1)
    accuracy_tolerance: float = 0.02       # Max acceptable accuracy drop
    iterative_rounds: int = 5              # Rounds for iterative pruning
    fine_tune_epochs: int = 100            # Fine-tuning iterations after pruning
    min_feature_importance: float = 0.01   # Min importance to keep (structured)
    sensitivity_samples: int = 500         # Samples for sensitivity analysis


@dataclass
class PruningResult:
    """Result of a pruning pass."""
    original_metrics: dict[str, float]
    pruned_metrics: dict[str, float]
    accuracy_delta: dict[str, float]
    original_params: int
    pruned_params: int
    sparsity_achieved: float
    features_removed: list[str]
    strategy: str
    passed_tolerance: bool
    duration_ms: float


class ModelPruner:
    """
    Post-training pruning for Aether ML models.

    Removes low-importance weights and features from trained models
    to reduce inference cost while preserving accuracy within tolerance.
    """

    def __init__(self, config: PruningConfig | None = None) -> None:
        self.config = config or PruningConfig()

    def prune(
        self,
        model: Any,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: pd.DataFrame,
        y_val: pd.Series,
        feature_names: list[str] | None = None,
    ) -> PruningResult:
        """
        Prune a trained model.

        Args:
            model: A trained AetherModel instance.
            X_train: Training data for fine-tuning after pruning.
            y_train: Training labels.
            X_val: Validation data for accuracy measurement.
            y_val: Validation labels.
            feature_names: Optional feature names for structured pruning reports.

        Returns:
            PruningResult with sparsity stats and accuracy deltas.
        """
        start = time.monotonic()
        logger.info(
            "Pruning model: strategy=%s, target_sparsity=%.2f",
            self.config.strategy.value, self.config.target_sparsity,
        )

        # Baseline metrics
        original_predictions = model.predict(X_val)
        original_metrics = self._compute_metrics(y_val, original_predictions)
        original_params = self._count_params(model)

        # Apply pruning strategy
        features_removed: list[str] = []
        if self.config.strategy == PruningStrategy.MAGNITUDE:
            features_removed = self._prune_magnitude(model)
        elif self.config.strategy == PruningStrategy.STRUCTURED:
            features_removed = self._prune_structured(model, X_train, y_train, feature_names)
        elif self.config.strategy == PruningStrategy.ITERATIVE:
            features_removed = self._prune_iterative(model, X_train, y_train, X_val, y_val)
        elif self.config.strategy == PruningStrategy.SENSITIVITY:
            features_removed = self._prune_sensitivity(model, X_val, y_val, feature_names)

        # Fine-tune if accuracy dropped
        pruned_predictions = model.predict(X_val)
        pruned_metrics = self._compute_metrics(y_val, pruned_predictions)
        primary = list(original_metrics.keys())[0]
        delta = original_metrics[primary] - pruned_metrics[primary]

        if delta > self.config.accuracy_tolerance * 0.5:
            logger.info("Fine-tuning after pruning to recover accuracy...")
            self._fine_tune(model, X_train, y_train)
            pruned_predictions = model.predict(X_val)
            pruned_metrics = self._compute_metrics(y_val, pruned_predictions)

        # Final delta
        accuracy_delta = {
            k: pruned_metrics.get(k, 0) - original_metrics.get(k, 0)
            for k in original_metrics
        }
        passed = abs(accuracy_delta.get(primary, 0)) <= self.config.accuracy_tolerance

        pruned_params = self._count_params(model)
        sparsity = 1.0 - (pruned_params / max(original_params, 1))

        duration = (time.monotonic() - start) * 1000

        result = PruningResult(
            original_metrics=original_metrics,
            pruned_metrics=pruned_metrics,
            accuracy_delta=accuracy_delta,
            original_params=original_params,
            pruned_params=pruned_params,
            sparsity_achieved=round(sparsity, 4),
            features_removed=features_removed,
            strategy=self.config.strategy.value,
            passed_tolerance=passed,
            duration_ms=round(duration, 1),
        )
        logger.info(
            "Pruning complete: sparsity=%.1f%%, removed=%d features, tolerance=%s",
            sparsity * 100, len(features_removed), "PASS" if passed else "FAIL",
        )
        return result

    # =========================================================================
    # STRATEGIES
    # =========================================================================

    def _prune_magnitude(self, model: Any) -> list[str]:
        """Zero out weights below magnitude threshold."""
        internal = getattr(model, '_model', None)
        if internal is None:
            return []

        if hasattr(internal, 'coef_'):
            coef = internal.coef_
            threshold = np.percentile(np.abs(coef), self.config.target_sparsity * 100)
            mask = np.abs(coef) >= threshold
            internal.coef_ = coef * mask
            n_pruned = (~mask).sum()
            logger.info("Magnitude pruning: zeroed %d / %d weights", n_pruned, coef.size)

        if hasattr(internal, 'feature_importances_'):
            importances = internal.feature_importances_
            threshold = np.percentile(importances, self.config.target_sparsity * 100)
            removed_indices = np.where(importances < threshold)[0]
            return [f"feature_{i}" for i in removed_indices]

        return []

    def _prune_structured(
        self, model: Any, X_train: pd.DataFrame, y_train: pd.Series,
        feature_names: list[str] | None,
    ) -> list[str]:
        """Remove entire features/neurons based on importance scores."""
        internal = getattr(model, '_model', None)
        if internal is None:
            return []

        names = feature_names or [f"feature_{i}" for i in range(X_train.shape[1])]
        importances = self._get_feature_importances(internal, X_train, y_train)

        if importances is None:
            return []

        # Identify features to remove
        to_remove = []
        for idx, (name, imp) in enumerate(zip(names, importances)):
            if imp < self.config.min_feature_importance:
                to_remove.append(name)

        # Cap removals at target_sparsity
        max_remove = int(len(names) * self.config.target_sparsity)
        sorted_by_importance = sorted(zip(names, importances), key=lambda x: x[1])
        to_remove = [name for name, _ in sorted_by_importance[:max_remove]]

        logger.info("Structured pruning: removing %d / %d features", len(to_remove), len(names))

        # Zero out columns for removed features in weight matrix
        if hasattr(internal, 'coef_'):
            remove_indices = [names.index(n) for n in to_remove if n in names]
            for idx in remove_indices:
                if idx < internal.coef_.shape[-1]:
                    internal.coef_[..., idx] = 0.0

        return to_remove

    def _prune_iterative(
        self, model: Any, X_train: pd.DataFrame, y_train: pd.Series,
        X_val: pd.DataFrame, y_val: pd.Series,
    ) -> list[str]:
        """Gradually increase sparsity with fine-tuning between rounds."""
        all_removed: list[str] = []
        per_round = self.config.target_sparsity / self.config.iterative_rounds

        for round_idx in range(self.config.iterative_rounds):
            target = per_round * (round_idx + 1)
            logger.info(
                "Iterative pruning round %d/%d (cumulative target=%.2f)",
                round_idx + 1, self.config.iterative_rounds, target,
            )

            internal = getattr(model, '_model', None)
            if internal and hasattr(internal, 'coef_'):
                coef = internal.coef_
                threshold = np.percentile(np.abs(coef[coef != 0]), per_round * 100)
                mask = np.abs(coef) >= threshold
                internal.coef_ = coef * mask

            # Fine-tune between rounds
            self._fine_tune(model, X_train, y_train)

            # Check accuracy
            preds = model.predict(X_val)
            metrics = self._compute_metrics(y_val, preds)
            primary = list(metrics.keys())[0]
            logger.info("  Round %d accuracy: %.4f", round_idx + 1, metrics[primary])

        return all_removed

    def _prune_sensitivity(
        self, model: Any, X_val: pd.DataFrame, y_val: pd.Series,
        feature_names: list[str] | None,
    ) -> list[str]:
        """Per-feature sensitivity analysis for targeted pruning."""
        internal = getattr(model, '_model', None)
        if internal is None:
            return []

        names = feature_names or [f"feature_{i}" for i in range(X_val.shape[1])]
        baseline_preds = model.predict(X_val)
        baseline_metrics = self._compute_metrics(y_val, baseline_preds)
        primary = list(baseline_metrics.keys())[0]
        baseline_score = baseline_metrics[primary]

        sensitivities = {}
        sample = X_val.head(self.config.sensitivity_samples)
        y_sample = y_val.head(self.config.sensitivity_samples)

        for idx, name in enumerate(names):
            # Permute feature and measure accuracy drop
            X_permuted = sample.copy()
            col = X_permuted.columns[idx] if hasattr(X_permuted, 'columns') else idx
            X_permuted.iloc[:, idx] = np.random.permutation(X_permuted.iloc[:, idx].values)
            preds = model.predict(X_permuted)
            score = self._compute_metrics(y_sample, preds)[primary]
            sensitivities[name] = baseline_score - score  # Higher = more important

        # Prune least sensitive features
        sorted_features = sorted(sensitivities.items(), key=lambda x: x[1])
        max_remove = int(len(names) * self.config.target_sparsity)
        to_remove = [name for name, sens in sorted_features[:max_remove] if sens < self.config.accuracy_tolerance]

        # Zero out in weight matrix
        if hasattr(internal, 'coef_') and to_remove:
            for name in to_remove:
                if name in names:
                    idx = names.index(name)
                    if idx < internal.coef_.shape[-1]:
                        internal.coef_[..., idx] = 0.0

        return to_remove

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _fine_tune(self, model: Any, X: pd.DataFrame, y: pd.Series) -> None:
        """Re-fit model on training data after pruning (warm start if supported)."""
        internal = getattr(model, '_model', None)
        if internal is None:
            return
        try:
            if hasattr(internal, 'warm_start'):
                internal.warm_start = True
            if hasattr(internal, 'max_iter'):
                internal.max_iter = self.config.fine_tune_epochs
            features = X.values if hasattr(X, 'values') else X
            internal.fit(features, y)
        except Exception as e:
            logger.warning("Fine-tuning failed: %s", e)

    def _get_feature_importances(
        self, model: Any, X: pd.DataFrame, y: pd.Series,
    ) -> np.ndarray | None:
        if hasattr(model, 'feature_importances_'):
            return model.feature_importances_
        if hasattr(model, 'coef_'):
            return np.abs(model.coef_).mean(axis=0) if model.coef_.ndim > 1 else np.abs(model.coef_)
        return None

    def _count_params(self, model: Any) -> int:
        internal = getattr(model, '_model', None)
        if internal is None:
            return 0
        total = 0
        if hasattr(internal, 'coef_'):
            total += np.count_nonzero(internal.coef_)
        if hasattr(internal, 'intercept_'):
            total += np.count_nonzero(internal.intercept_)
        if hasattr(internal, 'feature_importances_'):
            total += np.count_nonzero(internal.feature_importances_)
        if hasattr(internal, 'estimators_'):
            total += sum(
                e.tree_.node_count for e in internal.estimators_
                if hasattr(e, 'tree_')
            )
        return max(total, 1)

    def _compute_metrics(self, y_true: pd.Series, y_pred: np.ndarray) -> dict[str, float]:
        from sklearn.metrics import accuracy_score, f1_score
        y_p = y_pred if y_pred.ndim == 1 else y_pred.argmax(axis=1)
        return {
            "accuracy": accuracy_score(y_true, y_p),
            "f1_weighted": f1_score(y_true, y_p, average="weighted", zero_division=0),
        }
