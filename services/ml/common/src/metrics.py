"""
Unified metric computation and MLflow tracking.

Provides ``MetricsCollector`` with methods for classification, regression,
and ranking metrics, plus MLflow logging helpers and model comparison
utilities used across all 9 Aether ML models.
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger("aether.ml.metrics")


class MetricsCollector:
    """Compute, log, and compare evaluation metrics for Aether models.

    All ``compute_*`` methods are stateless and return plain ``dict``
    objects.  The ``log_*`` methods delegate to MLflow for experiment
    tracking.
    """

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    @staticmethod
    def compute_classification_metrics(
        y_true: np.ndarray,
        y_pred: np.ndarray,
        y_proba: Optional[np.ndarray] = None,
    ) -> dict[str, float]:
        """Return a comprehensive classification metrics dictionary.

        Parameters
        ----------
        y_true : array-like
            Ground-truth labels.
        y_pred : array-like
            Predicted labels (hard predictions).
        y_proba : array-like, optional
            Predicted probabilities for the positive class (binary) or
            all classes (multi-class).  Required for AUC and log-loss.

        Returns
        -------
        dict with keys: accuracy, precision, recall, f1, and optionally
        auc_roc, auc_pr, log_loss.
        """
        from sklearn.metrics import (
            accuracy_score,
            average_precision_score,
            f1_score,
            log_loss,
            precision_score,
            recall_score,
            roc_auc_score,
        )

        y_true = np.asarray(y_true)
        y_pred = np.asarray(y_pred)

        metrics: dict[str, float] = {
            "accuracy": float(accuracy_score(y_true, y_pred)),
            "precision": float(
                precision_score(y_true, y_pred, average="weighted", zero_division=0)
            ),
            "recall": float(
                recall_score(y_true, y_pred, average="weighted", zero_division=0)
            ),
            "f1": float(
                f1_score(y_true, y_pred, average="weighted", zero_division=0)
            ),
        }

        if y_proba is not None:
            y_proba = np.asarray(y_proba)
            try:
                if y_proba.ndim == 1:
                    metrics["auc_roc"] = float(roc_auc_score(y_true, y_proba))
                    metrics["auc_pr"] = float(average_precision_score(y_true, y_proba))
                    metrics["log_loss"] = float(log_loss(y_true, y_proba))
                else:
                    metrics["auc_roc"] = float(
                        roc_auc_score(y_true, y_proba, multi_class="ovr", average="weighted")
                    )
                    metrics["log_loss"] = float(log_loss(y_true, y_proba))
            except ValueError as exc:
                logger.warning("Could not compute probability-based metrics: %s", exc)

        return metrics

    # ------------------------------------------------------------------
    # Regression
    # ------------------------------------------------------------------

    @staticmethod
    def compute_regression_metrics(
        y_true: np.ndarray,
        y_pred: np.ndarray,
    ) -> dict[str, float]:
        """Return standard regression metrics.

        Returns
        -------
        dict with keys: rmse, mae, mape, r2, explained_variance.
        """
        from sklearn.metrics import (
            explained_variance_score,
            mean_absolute_error,
            mean_squared_error,
            r2_score,
        )

        y_true = np.asarray(y_true, dtype=float)
        y_pred = np.asarray(y_pred, dtype=float)

        # MAPE -- guard against zero-valued actuals
        nonzero = y_true != 0
        if nonzero.any():
            mape = float(
                np.mean(np.abs((y_true[nonzero] - y_pred[nonzero]) / y_true[nonzero])) * 100
            )
        else:
            mape = float("inf")

        return {
            "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
            "mae": float(mean_absolute_error(y_true, y_pred)),
            "mape": mape,
            "r2": float(r2_score(y_true, y_pred)),
            "explained_variance": float(explained_variance_score(y_true, y_pred)),
        }

    # ------------------------------------------------------------------
    # Ranking
    # ------------------------------------------------------------------

    @staticmethod
    def compute_ranking_metrics(
        y_true: np.ndarray,
        y_pred: np.ndarray,
        k: int = 10,
    ) -> dict[str, float]:
        """Compute ranking-quality metrics at cut-off *k*.

        Parameters
        ----------
        y_true : array-like of shape (n_queries, n_items)
            Relevance scores (binary or graded).
        y_pred : array-like of shape (n_queries, n_items)
            Predicted scores used to rank items.
        k : int
            Cut-off for top-k evaluation.

        Returns
        -------
        dict with keys: ndcg_at_k, precision_at_k, map_at_k.
        """
        y_true = np.atleast_2d(np.asarray(y_true, dtype=float))
        y_pred = np.atleast_2d(np.asarray(y_pred, dtype=float))

        ndcg_scores: list[float] = []
        precision_scores: list[float] = []
        ap_scores: list[float] = []

        for true_row, pred_row in zip(y_true, y_pred):
            ranked_idx = np.argsort(-pred_row)[:k]
            ranked_relevance = true_row[ranked_idx]

            # NDCG@k
            dcg = float(np.sum(ranked_relevance / np.log2(np.arange(2, k + 2))))
            ideal_relevance = np.sort(true_row)[::-1][:k]
            idcg = float(np.sum(ideal_relevance / np.log2(np.arange(2, k + 2))))
            ndcg_scores.append(dcg / idcg if idcg > 0 else 0.0)

            # Precision@k
            precision_scores.append(float(np.sum(ranked_relevance > 0) / k))

            # Average Precision@k
            hits = 0.0
            score = 0.0
            for i, rel in enumerate(ranked_relevance, start=1):
                if rel > 0:
                    hits += 1
                    score += hits / i
            ap_scores.append(score / min(k, float(np.sum(true_row > 0))) if np.sum(true_row > 0) > 0 else 0.0)

        return {
            f"ndcg@{k}": float(np.mean(ndcg_scores)),
            f"precision@{k}": float(np.mean(precision_scores)),
            f"map@{k}": float(np.mean(ap_scores)),
        }

    # ------------------------------------------------------------------
    # MLflow logging
    # ------------------------------------------------------------------

    @staticmethod
    def log_metrics(metrics: dict[str, float], step: int = 0) -> None:
        """Log a metrics dictionary to the active MLflow run.

        If no MLflow run is active the call is a no-op (with a warning).
        """
        try:
            import mlflow

            if mlflow.active_run() is None:
                logger.warning("No active MLflow run -- metrics not logged.")
                return

            mlflow.log_metrics(metrics, step=step)
            logger.info("Logged %d metric(s) at step %d", len(metrics), step)
        except ImportError:
            logger.warning("mlflow not installed -- metrics not logged.")

    @staticmethod
    def log_confusion_matrix(
        y_true: np.ndarray,
        y_pred: np.ndarray,
        labels: Optional[list[str]] = None,
    ) -> None:
        """Compute a confusion matrix and log it as an MLflow artifact.

        The matrix is saved as a PNG image and as a CSV file.
        """
        try:
            import mlflow
            from sklearn.metrics import confusion_matrix

            if mlflow.active_run() is None:
                logger.warning("No active MLflow run -- confusion matrix not logged.")
                return

            cm = confusion_matrix(y_true, y_pred)

            # Save as CSV
            import pandas as pd

            label_names = labels or [str(i) for i in range(cm.shape[0])]
            cm_df = pd.DataFrame(cm, index=label_names, columns=label_names)

            with tempfile.TemporaryDirectory() as tmpdir:
                csv_path = Path(tmpdir) / "confusion_matrix.csv"
                cm_df.to_csv(csv_path)
                mlflow.log_artifact(str(csv_path))

                # Attempt to save a PNG via matplotlib (optional dependency)
                try:
                    import matplotlib
                    matplotlib.use("Agg")
                    import matplotlib.pyplot as plt

                    fig, ax = plt.subplots(figsize=(8, 6))
                    im = ax.imshow(cm, interpolation="nearest", cmap="Blues")
                    ax.set_title("Confusion Matrix")
                    ax.set_xlabel("Predicted")
                    ax.set_ylabel("Actual")
                    ax.set_xticks(range(len(label_names)))
                    ax.set_yticks(range(len(label_names)))
                    ax.set_xticklabels(label_names, rotation=45, ha="right")
                    ax.set_yticklabels(label_names)
                    fig.colorbar(im, ax=ax)

                    # Annotate cells
                    for i in range(cm.shape[0]):
                        for j in range(cm.shape[1]):
                            ax.text(
                                j, i, str(cm[i, j]),
                                ha="center", va="center",
                                color="white" if cm[i, j] > cm.max() / 2 else "black",
                            )

                    fig.tight_layout()
                    png_path = Path(tmpdir) / "confusion_matrix.png"
                    fig.savefig(png_path, dpi=150)
                    plt.close(fig)
                    mlflow.log_artifact(str(png_path))
                except ImportError:
                    logger.info("matplotlib not available -- only CSV artifact logged.")

            logger.info("Confusion matrix logged to MLflow")

        except ImportError:
            logger.warning("mlflow not installed -- confusion matrix not logged.")

    # ------------------------------------------------------------------
    # Model comparison
    # ------------------------------------------------------------------

    @staticmethod
    def compare_models(
        baseline_metrics: dict[str, float],
        challenger_metrics: dict[str, float],
    ) -> dict[str, float]:
        """Compare two sets of metrics and return percentage improvements.

        Returns a dict mapping each metric name to the relative change
        (positive = challenger is better).
        """
        comparison: dict[str, float] = {}

        all_keys = set(baseline_metrics) | set(challenger_metrics)
        for key in sorted(all_keys):
            base_val = baseline_metrics.get(key)
            chal_val = challenger_metrics.get(key)

            if base_val is None or chal_val is None:
                continue

            if abs(base_val) < 1e-12:
                # Avoid division by zero -- report absolute difference
                comparison[f"{key}_abs_change"] = round(chal_val - base_val, 6)
            else:
                pct = ((chal_val - base_val) / abs(base_val)) * 100
                comparison[f"{key}_pct_change"] = round(pct, 4)

        # Summary verdict
        improvements = sum(1 for v in comparison.values() if v > 0)
        regressions = sum(1 for v in comparison.values() if v < 0)
        comparison["improvements"] = float(improvements)
        comparison["regressions"] = float(regressions)

        logger.info(
            "Model comparison: %d improvement(s), %d regression(s)",
            improvements,
            regressions,
        )
        return comparison


# ------------------------------------------------------------------
# Backwards-compatible report API used by the ML unit suite
# ------------------------------------------------------------------


@dataclass
class ClassificationReport:
    accuracy: float
    precision: float
    recall: float
    f1: float
    auc_roc: float
    optimal_threshold: float
    confusion_matrix: np.ndarray
    calibration_error: float

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["confusion_matrix"] = self.confusion_matrix.tolist()
        return data


@dataclass
class RegressionReport:
    mae: float
    rmse: float
    r2: float
    mape: float
    percentile_errors: dict[str, float]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class StatisticalTestResult:
    test_name: str
    statistic: float
    p_value: float
    effect_size: float
    significant: bool


class StatisticalTests:
    @staticmethod
    def compare_proportions(successes_a: int, total_a: int, successes_b: int, total_b: int) -> StatisticalTestResult:
        from math import erf, sqrt

        p1 = successes_a / total_a
        p2 = successes_b / total_b
        pooled = (successes_a + successes_b) / (total_a + total_b)
        se = np.sqrt(max(pooled * (1 - pooled) * ((1 / total_a) + (1 / total_b)), 1e-12))
        z_score = (p2 - p1) / se
        cdf = 0.5 * (1 + erf(abs(z_score) / sqrt(2)))
        p_value = 2 * (1 - cdf)
        return StatisticalTestResult(
            test_name='two_proportion_z_test',
            statistic=float(z_score),
            p_value=float(p_value),
            effect_size=float(p2 - p1),
            significant=bool(p_value < 0.05),
        )

    @staticmethod
    def compare_means(sample_a: np.ndarray, sample_b: np.ndarray) -> StatisticalTestResult:
        from math import erf, sqrt

        a = np.asarray(sample_a, dtype=float)
        b = np.asarray(sample_b, dtype=float)
        mean_diff = float(b.mean() - a.mean())
        variance = (a.var(ddof=1) / len(a)) + (b.var(ddof=1) / len(b))
        t_stat = mean_diff / np.sqrt(max(variance, 1e-12))
        cdf = 0.5 * (1 + erf(abs(t_stat) / sqrt(2)))
        p_value = 2 * (1 - cdf)
        pooled_sd = np.sqrt(max((((len(a) - 1) * a.var(ddof=1)) + ((len(b) - 1) * b.var(ddof=1))) / max(len(a) + len(b) - 2, 1), 1e-12))
        return StatisticalTestResult(
            test_name='welch_t_test',
            statistic=float(t_stat),
            p_value=float(p_value),
            effect_size=float(mean_diff / pooled_sd),
            significant=bool(p_value < 0.05),
        )

    @staticmethod
    def compute_minimum_sample_size(baseline_rate: float, mde: float, alpha: float = 0.05, power: float = 0.8) -> int:
        z_alpha = 1.96 if alpha <= 0.05 else 1.64
        z_beta = 0.84 if power >= 0.8 else 0.52
        pooled = max(baseline_rate * (1 - baseline_rate), 1e-9)
        n = 2 * pooled * ((z_alpha + z_beta) ** 2) / max(mde ** 2, 1e-9)
        return int(np.ceil(n))


class BusinessMetrics:
    @staticmethod
    def lift_over_random(y_true: np.ndarray, y_pred: np.ndarray, top_fraction: float = 0.1) -> float:
        y_true = np.asarray(y_true)
        y_pred = np.asarray(y_pred, dtype=float)
        cutoff = max(1, int(np.ceil(len(y_true) * top_fraction)))
        ranked = y_true[np.argsort(-y_pred)][:cutoff]
        return float(ranked.mean() / max(float(y_true.mean()), 1e-12))

    @staticmethod
    def cumulative_gains(y_true: np.ndarray, y_pred: np.ndarray, bins: int = 10):
        import pandas as pd

        y_true = np.asarray(y_true)
        y_pred = np.asarray(y_pred, dtype=float)
        ranked = y_true[np.argsort(-y_pred)]
        total_positive = max(float(ranked.sum()), 1.0)
        rows: list[dict[str, float]] = []
        for pct in np.linspace(0.1, 1.0, bins):
            cutoff = max(1, int(np.ceil(len(ranked) * pct)))
            rows.append({
                'population_pct': float(pct),
                'captured_pct': float(ranked[:cutoff].sum() / total_positive),
            })
        return pd.DataFrame(rows)


class MetricsEngine:
    @staticmethod
    def _expected_calibration_error(y_true: np.ndarray, y_pred_proba: np.ndarray, bins: int = 10) -> float:
        y_true = np.asarray(y_true)
        y_pred_proba = np.asarray(y_pred_proba, dtype=float)
        edges = np.linspace(0.0, 1.0, bins + 1)
        total = len(y_true)
        ece = 0.0
        for start, end in zip(edges[:-1], edges[1:]):
            mask = (y_pred_proba >= start) & ((y_pred_proba < end) if end < 1.0 else (y_pred_proba <= end))
            if not mask.any():
                continue
            confidence = float(y_pred_proba[mask].mean())
            accuracy = float(y_true[mask].mean())
            ece += abs(accuracy - confidence) * (mask.sum() / total)
        return float(ece)

    @classmethod
    def classification_report(cls, y_true: np.ndarray, y_pred_proba: np.ndarray) -> ClassificationReport:
        from sklearn.metrics import confusion_matrix

        y_true = np.asarray(y_true)
        y_pred_proba = np.asarray(y_pred_proba, dtype=float)
        best_metrics: dict[str, float] | None = None
        best_threshold = 0.5
        best_pred = (y_pred_proba >= 0.5).astype(int)
        best_f1 = -1.0
        for threshold in np.linspace(0.05, 0.95, 19):
            pred = (y_pred_proba >= threshold).astype(int)
            metrics = MetricsCollector.compute_classification_metrics(y_true, pred, y_pred_proba)
            if metrics['f1'] > best_f1:
                best_f1 = metrics['f1']
                best_threshold = float(threshold)
                best_pred = pred
                best_metrics = metrics
        assert best_metrics is not None
        return ClassificationReport(
            accuracy=float(best_metrics['accuracy']),
            precision=float(best_metrics['precision']),
            recall=float(best_metrics['recall']),
            f1=float(best_metrics['f1']),
            auc_roc=float(best_metrics.get('auc_roc', 0.0)),
            optimal_threshold=best_threshold,
            confusion_matrix=confusion_matrix(y_true, best_pred),
            calibration_error=cls._expected_calibration_error(y_true, y_pred_proba),
        )

    @staticmethod
    def regression_report(y_true: np.ndarray, y_pred: np.ndarray) -> RegressionReport:
        metrics = MetricsCollector.compute_regression_metrics(y_true, y_pred)
        abs_error = np.abs(np.asarray(y_true, dtype=float) - np.asarray(y_pred, dtype=float))
        return RegressionReport(
            mae=float(metrics['mae']),
            rmse=float(metrics['rmse']),
            r2=float(metrics['r2']),
            mape=float(metrics['mape']),
            percentile_errors={
                'p50_error': float(np.percentile(abs_error, 50)),
                'p95_error': float(np.percentile(abs_error, 95)),
            },
        )
