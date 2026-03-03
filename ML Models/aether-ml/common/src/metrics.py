"""
Unified metric computation and MLflow tracking.

Provides ``MetricsCollector`` with methods for classification, regression,
and ranking metrics, plus MLflow logging helpers and model comparison
utilities used across all 9 Aether ML models.
"""

from __future__ import annotations

import io
import logging
import tempfile
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
