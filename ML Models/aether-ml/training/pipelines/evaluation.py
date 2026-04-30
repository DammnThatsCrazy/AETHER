"""Champion/challenger model evaluation, cross-validation, and bias auditing.

Provides comprehensive model evaluation capabilities for the Aether ML platform:
  - K-fold cross-validation with multiple scoring metrics
  - Champion vs challenger comparison with statistical significance testing
  - Demographic bias auditing across sensitive features
  - Human-readable evaluation report generation
"""

from __future__ import annotations

import logging
import time
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    r2_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import KFold, StratifiedKFold, cross_val_score

logger = logging.getLogger("aether.ml.training.evaluation")


# ---------------------------------------------------------------------------
# Scorer registry
# ---------------------------------------------------------------------------

_SCORER_MAP: dict[str, str] = {
    "accuracy": "accuracy",
    "f1": "f1_weighted",
    "f1_weighted": "f1_weighted",
    "f1_binary": "f1",
    "precision": "precision_weighted",
    "recall": "recall_weighted",
    "roc_auc": "roc_auc",
    "auc": "roc_auc",
    "neg_mae": "neg_mean_absolute_error",
    "mae": "neg_mean_absolute_error",
    "neg_rmse": "neg_root_mean_squared_error",
    "rmse": "neg_root_mean_squared_error",
    "r2": "r2",
}


def _resolve_scorer(name: str) -> str:
    """Map friendly metric names to sklearn scorer strings."""
    return _SCORER_MAP.get(name, name)


# ---------------------------------------------------------------------------
# Model Evaluator
# ---------------------------------------------------------------------------


class ModelEvaluator:
    """Comprehensive model evaluation with cross-validation, champion/challenger
    comparison, bias auditing, and human-readable reporting.
    """

    def __init__(self, n_folds: int = 5, random_state: int = 42) -> None:
        self.n_folds = n_folds
        self.random_state = random_state

    # ------------------------------------------------------------------
    # Cross-validation
    # ------------------------------------------------------------------

    def cross_validate(
        self,
        model: Any,
        X: pd.DataFrame | np.ndarray,
        y: pd.Series | np.ndarray,
        scoring: str | list[str] = "roc_auc",
    ) -> dict[str, Any]:
        """K-fold cross-validation with one or more scoring metrics.

        Args:
            model: An sklearn-compatible estimator (must implement fit/predict).
            X: Feature matrix.
            y: Target vector.
            scoring: A single metric name or a list of metric names.
                     Friendly aliases like ``"auc"`` are resolved automatically.

        Returns:
            Dictionary with per-metric fold scores, means, and standard deviations.
        """
        y_arr = np.asarray(y)
        is_classification = self._is_classification(y_arr)

        if is_classification:
            cv = StratifiedKFold(
                n_splits=self.n_folds,
                shuffle=True,
                random_state=self.random_state,
            )
        else:
            cv = KFold(
                n_splits=self.n_folds,
                shuffle=True,
                random_state=self.random_state,
            )

        if isinstance(scoring, str):
            scoring = [scoring]

        results: dict[str, Any] = {}
        for metric in scoring:
            sk_scorer = _resolve_scorer(metric)
            try:
                scores = cross_val_score(
                    model, X, y, cv=cv, scoring=sk_scorer, n_jobs=-1,
                )
                results[metric] = {
                    "fold_scores": scores.tolist(),
                    "mean": float(np.mean(scores)),
                    "std": float(np.std(scores)),
                    "min": float(np.min(scores)),
                    "max": float(np.max(scores)),
                }
            except Exception as e:
                logger.warning(f"Cross-validation failed for metric '{metric}': {e}")
                results[metric] = {
                    "fold_scores": [],
                    "mean": float("nan"),
                    "std": float("nan"),
                    "error": str(e),
                }

        return results

    # ------------------------------------------------------------------
    # Champion / Challenger comparison
    # ------------------------------------------------------------------

    def champion_challenger(
        self,
        champion: Any,
        challenger: Any,
        X_test: pd.DataFrame | np.ndarray,
        y_test: pd.Series | np.ndarray,
        scoring: str = "roc_auc",
    ) -> dict[str, Any]:
        """Compare a champion (production) model against a challenger candidate.

        Evaluates both models on the same test set and performs a paired t-test
        on per-sample scores to determine statistical significance.

        Args:
            champion: Currently deployed model.
            challenger: Candidate model to evaluate.
            X_test: Held-out test features.
            y_test: Held-out test targets.
            scoring: Primary metric for comparison.

        Returns:
            Dictionary containing:
              - metrics comparison for both models
              - p-value from a paired t-test
              - improvement percentage
              - recommendation (promote / keep_champion)
        """
        y_arr = np.asarray(y_test)
        is_classification = self._is_classification(y_arr)

        # Compute per-model metrics
        champion_metrics = self._compute_metrics(champion, X_test, y_arr, is_classification)
        challenger_metrics = self._compute_metrics(challenger, X_test, y_arr, is_classification)

        # Primary metric values
        champion_primary = champion_metrics.get(scoring, champion_metrics.get("accuracy", 0.0))
        challenger_primary = challenger_metrics.get(scoring, challenger_metrics.get("accuracy", 0.0))

        # Improvement
        if abs(champion_primary) > 1e-12:
            improvement_pct = (
                (challenger_primary - champion_primary) / abs(champion_primary)
            ) * 100
        else:
            improvement_pct = 100.0 if challenger_primary > 0 else 0.0

        # Paired t-test via cross-validation fold scores
        cv_champion = self.cross_validate(champion, X_test, y_arr, scoring=scoring)
        cv_challenger = self.cross_validate(challenger, X_test, y_arr, scoring=scoring)

        champion_folds = np.array(cv_champion[scoring]["fold_scores"])
        challenger_folds = np.array(cv_challenger[scoring]["fold_scores"])

        if len(champion_folds) == len(challenger_folds) and len(champion_folds) > 1:
            t_stat, p_value = stats.ttest_rel(challenger_folds, champion_folds)
        else:
            t_stat, p_value = 0.0, 1.0

        is_significant = bool(p_value < 0.05)
        challenger_wins = challenger_primary > champion_primary

        if challenger_wins and is_significant:
            recommendation = "promote"
            reason = (
                f"Challenger outperforms champion on {scoring} by "
                f"{improvement_pct:+.2f}% (p={p_value:.4f})"
            )
        elif challenger_wins and not is_significant:
            recommendation = "keep_champion"
            reason = (
                f"Challenger shows improvement ({improvement_pct:+.2f}%) but "
                f"not statistically significant (p={p_value:.4f})"
            )
        else:
            recommendation = "keep_champion"
            reason = (
                f"Champion performs equal or better on {scoring} "
                f"({improvement_pct:+.2f}%, p={p_value:.4f})"
            )

        return {
            "champion_metrics": champion_metrics,
            "challenger_metrics": challenger_metrics,
            "primary_metric": scoring,
            "champion_value": champion_primary,
            "challenger_value": challenger_primary,
            "improvement_pct": round(improvement_pct, 4),
            "t_statistic": round(float(t_stat), 4),
            "p_value": round(float(p_value), 6),
            "is_statistically_significant": is_significant,
            "recommendation": recommendation,
            "reason": reason,
        }

    # ------------------------------------------------------------------
    # Bias audit
    # ------------------------------------------------------------------

    def bias_audit(
        self,
        model: Any,
        X: pd.DataFrame,
        y: pd.Series | np.ndarray,
        sensitive_features: list[str],
    ) -> dict[str, Any]:
        """Audit model predictions for demographic bias across sensitive features.

        For each sensitive feature, computes per-group performance metrics and
        the disparate impact ratio (minimum group metric / maximum group metric).

        Args:
            model: Trained model with a ``predict`` method.
            X: Feature matrix (must be a DataFrame with named columns).
            y: True labels.
            sensitive_features: Column names in X to audit for bias.

        Returns:
            Dictionary mapping each sensitive feature to per-group metrics,
            disparate impact ratio, and whether fairness thresholds are met.
        """
        y_arr = np.asarray(y)
        predictions = model.predict(X)
        is_classification = self._is_classification(y_arr)

        audit_results: dict[str, Any] = {
            "features_audited": [],
            "overall_fairness_pass": True,
        }

        for feature in sensitive_features:
            if feature not in X.columns:
                logger.warning(f"Sensitive feature '{feature}' not found in data; skipping")
                continue

            groups = X[feature].unique()
            if len(groups) < 2:
                logger.info(f"Feature '{feature}' has only 1 group; skipping")
                continue

            group_results: dict[str, dict[str, float]] = {}
            for group_val in sorted(groups, key=str):
                mask = (X[feature] == group_val).values
                n_group = int(mask.sum())
                if n_group < 10:
                    continue

                g_preds = predictions[mask]
                g_true = y_arr[mask]

                if is_classification:
                    group_results[str(group_val)] = {
                        "n_samples": n_group,
                        "accuracy": float(accuracy_score(g_true, g_preds)),
                        "f1": float(f1_score(g_true, g_preds, average="weighted", zero_division=0)),
                        "positive_rate": float(np.mean(g_preds)),
                    }
                else:
                    group_results[str(group_val)] = {
                        "n_samples": n_group,
                        "mae": float(mean_absolute_error(g_true, g_preds)),
                        "r2": float(r2_score(g_true, g_preds)) if n_group > 1 else 0.0,
                    }

            if len(group_results) < 2:
                continue

            # Disparate impact ratio (uses accuracy for classification, 1/MAE for regression)
            if is_classification:
                metric_vals = [g["accuracy"] for g in group_results.values()]
            else:
                metric_vals = [1.0 / max(g["mae"], 1e-8) for g in group_results.values()]

            min_val = min(metric_vals)
            max_val = max(metric_vals)
            disparate_impact = min_val / max_val if max_val > 0 else 0.0

            # The four-fifths rule: ratio should be >= 0.8
            passes_threshold = disparate_impact >= 0.8

            if not passes_threshold:
                audit_results["overall_fairness_pass"] = False

            feature_report = {
                "groups": group_results,
                "disparate_impact_ratio": round(disparate_impact, 4),
                "passes_four_fifths_rule": passes_threshold,
                "max_disparity": round(max_val - min_val, 4),
            }
            audit_results["features_audited"].append(feature)
            audit_results[feature] = feature_report

        return audit_results

    # ------------------------------------------------------------------
    # Report generation
    # ------------------------------------------------------------------

    def generate_evaluation_report(self, results: dict[str, Any]) -> str:
        """Generate a human-readable evaluation report from evaluation results.

        Args:
            results: Dictionary produced by ``cross_validate``,
                     ``champion_challenger``, or ``bias_audit``.

        Returns:
            Formatted string report.
        """
        lines: list[str] = []
        lines.append("=" * 70)
        lines.append("Aether ML - MODEL EVALUATION REPORT")
        lines.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
        lines.append("=" * 70)
        lines.append("")

        # Cross-validation results
        for key, value in results.items():
            if isinstance(value, dict) and "fold_scores" in value:
                lines.append(f"Metric: {key}")
                lines.append(f"  Mean:  {value['mean']:.4f}")
                lines.append(f"  Std:   {value['std']:.4f}")
                lines.append(f"  Range: [{value.get('min', 'N/A'):.4f}, {value.get('max', 'N/A'):.4f}]")
                fold_str = ", ".join(f"{s:.4f}" for s in value["fold_scores"])
                lines.append(f"  Folds: [{fold_str}]")
                lines.append("")

        # Champion/Challenger
        if "recommendation" in results:
            lines.append("-" * 40)
            lines.append("CHAMPION vs CHALLENGER")
            lines.append("-" * 40)
            lines.append(f"  Primary metric: {results.get('primary_metric', 'N/A')}")
            lines.append(f"  Champion:       {results.get('champion_value', 'N/A'):.4f}")
            lines.append(f"  Challenger:     {results.get('challenger_value', 'N/A'):.4f}")
            lines.append(f"  Improvement:    {results.get('improvement_pct', 0):+.2f}%")
            lines.append(f"  p-value:        {results.get('p_value', 'N/A')}")
            lines.append(f"  Significant:    {results.get('is_statistically_significant', 'N/A')}")
            lines.append(f"  Recommendation: {results.get('recommendation', 'N/A')}")
            lines.append(f"  Reason:         {results.get('reason', '')}")
            lines.append("")

        # Bias audit
        if "features_audited" in results:
            lines.append("-" * 40)
            lines.append("BIAS AUDIT")
            lines.append("-" * 40)
            features = results.get("features_audited", [])
            lines.append(f"  Features audited: {features}")
            lines.append(
                f"  Overall fairness: "
                f"{'PASS' if results.get('overall_fairness_pass') else 'FAIL'}"
            )
            for feat in features:
                feat_data = results.get(feat, {})
                lines.append(f"\n  Feature: {feat}")
                lines.append(
                    f"    Disparate impact ratio: "
                    f"{feat_data.get('disparate_impact_ratio', 'N/A')}"
                )
                lines.append(
                    f"    Four-fifths rule: "
                    f"{'PASS' if feat_data.get('passes_four_fifths_rule') else 'FAIL'}"
                )
                for group_name, group_vals in feat_data.get("groups", {}).items():
                    metric_strs = ", ".join(
                        f"{k}={v:.4f}" if isinstance(v, float) else f"{k}={v}"
                        for k, v in group_vals.items()
                    )
                    lines.append(f"    [{group_name}] {metric_strs}")
            lines.append("")

        lines.append("=" * 70)
        lines.append("END OF REPORT")
        lines.append("=" * 70)

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _compute_metrics(
        self,
        model: Any,
        X: pd.DataFrame | np.ndarray,
        y: np.ndarray,
        is_classification: bool,
    ) -> dict[str, float]:
        """Compute a standard set of metrics for a fitted model."""
        predictions = model.predict(X)
        metrics: dict[str, float] = {}

        if is_classification:
            metrics["accuracy"] = float(accuracy_score(y, predictions))
            metrics["f1"] = float(f1_score(y, predictions, average="weighted", zero_division=0))
            metrics["precision"] = float(
                precision_score(y, predictions, average="weighted", zero_division=0)
            )
            metrics["recall"] = float(
                recall_score(y, predictions, average="weighted", zero_division=0)
            )
            if hasattr(model, "predict_proba"):
                proba = model.predict_proba(X)
                try:
                    if proba.shape[1] == 2:
                        metrics["roc_auc"] = float(roc_auc_score(y, proba[:, 1]))
                    else:
                        metrics["roc_auc"] = float(
                            roc_auc_score(y, proba, multi_class="ovr", average="weighted")
                        )
                except ValueError:
                    pass  # e.g. single-class fold
        else:
            metrics["mae"] = float(mean_absolute_error(y, predictions))
            metrics["rmse"] = float(np.sqrt(mean_squared_error(y, predictions)))
            metrics["r2"] = float(r2_score(y, predictions))

        return metrics

    @staticmethod
    def _is_classification(y: np.ndarray) -> bool:
        """Heuristic to determine if the target is classification or regression."""
        n_unique = len(np.unique(y))
        if n_unique <= 20:
            return True
        if y.dtype in (np.int32, np.int64, bool, np.bool_):
            return n_unique <= 50
        return False
