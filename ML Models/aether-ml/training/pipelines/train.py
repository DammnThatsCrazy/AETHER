"""Unified training runner for all 9 Aether ML models.

Orchestrates end-to-end training pipelines with data loading, preprocessing,
model training, evaluation, MLflow tracking, and artifact persistence.

Usage:
    python -m training.pipelines.train --model intent_prediction --output-dir /tmp/aether-models
    python -m training.pipelines.train --model all --experiment aether-ml
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import mlflow
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

# Model imports (deferred to avoid circular dependencies during development)
# from edge.models import IntentPredictionModel, BotDetectionModel, SessionScorerModel
# from server.models import (
#     IdentityResolutionModel, ChurnPredictionModel, LTVPredictionModel,
#     AnomalyDetectionModel,
# )
# from server.journey_prediction import JourneyPredictionModel
# from server.campaign_attribution import CampaignAttributionModel

logger = logging.getLogger("aether.ml.training")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

# ---------------------------------------------------------------------------
# Model Registry — maps model name to (tier, class_name)
# ---------------------------------------------------------------------------

MODEL_REGISTRY: dict[str, tuple[str, str]] = {
    # Edge models (<100ms inference)
    "intent_prediction": ("edge", "IntentPredictionModel"),
    "bot_detection": ("edge", "BotDetectionModel"),
    "session_scorer": ("edge", "SessionScorerModel"),
    # Server models (SageMaker / ECS)
    "identity_resolution": ("server", "IdentityResolutionModel"),
    "journey_prediction": ("server", "JourneyPredictionModel"),
    "churn_prediction": ("server", "ChurnPredictionModel"),
    "ltv_prediction": ("server", "LTVPredictionModel"),
    "anomaly_detection": ("server", "AnomalyDetectionModel"),
    "campaign_attribution": ("server", "CampaignAttributionModel"),
}

# Per-model synthetic data configuration
_SYNTHETIC_SPECS: dict[str, dict[str, Any]] = {
    "intent_prediction": {
        "n_samples": 5000,
        "n_features": 14,
        "feature_names": [
            "mouse_velocity_mean", "mouse_velocity_std", "scroll_depth_max",
            "scroll_velocity_mean", "hover_duration_mean", "time_between_actions_mean",
            "time_between_actions_std", "click_to_scroll_ratio", "active_ratio",
            "page_depth", "session_duration_s", "click_count", "scroll_count",
            "keypress_count",
        ],
        "task": "classification",
        "n_classes": 4,
    },
    "bot_detection": {
        "n_samples": 10000,
        "n_features": 14,
        "feature_names": [
            "avg_time_between_actions", "time_variance", "click_to_scroll_ratio",
            "mouse_velocity_mean", "mouse_velocity_std", "mouse_entropy",
            "navigation_entropy", "interaction_diversity", "has_natural_pauses",
            "has_erratic_movement", "has_perfect_timing", "keypress_count",
            "unique_action_types", "action_rate",
        ],
        "task": "classification",
        "n_classes": 2,
    },
    "session_scorer": {
        "n_samples": 5000,
        "n_features": 9,
        "feature_names": [
            "page_count", "event_count", "session_duration_s", "max_scroll_depth",
            "form_interaction_count", "is_return_visit", "referral_source_score",
            "click_count", "active_ratio",
        ],
        "task": "regression",
    },
    "identity_resolution": {
        "n_samples": 8000,
        "n_features": 9,
        "feature_names": [
            "device_fingerprint_sim", "behavioral_sim", "temporal_overlap",
            "shared_ip_count", "session_sequence_score", "wallet_link_score",
            "geo_distance", "browser_match", "os_match",
        ],
        "task": "classification",
        "n_classes": 2,
    },
    "journey_prediction": {
        "n_samples": 10000,
        "n_features": 7,
        "feature_names": [
            "page_sequence_len", "avg_time_delta", "device_type_encoded",
            "referrer_type_encoded", "session_number", "day_of_week", "hour_of_day",
        ],
        "task": "classification",
        "n_classes": 2,
    },
    "churn_prediction": {
        "n_samples": 8000,
        "n_features": 11,
        "feature_names": [
            "days_since_last_visit", "visit_frequency_trend", "feature_usage_breadth",
            "session_duration_trend", "support_ticket_count", "billing_status",
            "engagement_percentile", "total_sessions", "avg_session_duration",
            "conversion_rate", "days_since_first_visit",
        ],
        "task": "classification",
        "n_classes": 2,
    },
    "ltv_prediction": {
        "n_samples": 5000,
        "n_features": 11,
        "feature_names": [
            "purchase_frequency", "recency_days", "monetary_mean", "monetary_total",
            "avg_session_duration", "total_sessions", "conversion_rate",
            "acquisition_channel_score", "engagement_percentile",
            "web3_tx_count", "web3_total_value",
        ],
        "task": "regression",
    },
    "anomaly_detection": {
        "n_samples": 5000,
        "n_features": 9,
        "feature_names": [
            "traffic_volume", "conversion_rate", "avg_session_duration",
            "bounce_rate", "error_rate", "api_latency_p99",
            "bot_traffic_ratio", "unique_visitors", "revenue",
        ],
        "task": "unsupervised",
    },
    "campaign_attribution": {
        "n_samples": 3000,
        "n_features": 5,
        "feature_names": [
            "touchpoint_count", "channel_diversity", "avg_time_delta",
            "conversion_value", "device_type_count",
        ],
        "task": "classification",
        "n_classes": 2,
    },
}


# ---------------------------------------------------------------------------
# Training Pipeline
# ---------------------------------------------------------------------------


class TrainingPipeline:
    """End-to-end training pipeline for a single Aether ML model.

    Steps:
        1. Load data (from S3/local or generate synthetic)
        2. Preprocess features
        3. Split into train / validation / test
        4. Train model
        5. Evaluate on holdout test set
        6. Log metrics and artifacts to MLflow
        7. Save model artifacts to disk
    """

    def __init__(
        self,
        model_name: str,
        output_dir: str = "/tmp/aether-models",
        config: dict[str, Any] | None = None,
    ) -> None:
        if model_name not in MODEL_REGISTRY:
            raise ValueError(
                f"Unknown model '{model_name}'. "
                f"Available: {sorted(MODEL_REGISTRY.keys())}"
            )
        self.model_name = model_name
        self.output_dir = Path(output_dir) / model_name
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.config = config or {}
        self.tier, self.class_name = MODEL_REGISTRY[model_name]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> dict[str, Any]:
        """Execute the full training pipeline and return a metrics dict."""
        start = time.time()
        logger.info("=" * 60)
        logger.info(f"Training pipeline: {self.model_name} (tier={self.tier})")
        logger.info("=" * 60)

        # 1. Load or generate data
        X, y = self._load_data()
        logger.info(
            f"Data loaded: {X.shape[0]} samples, {X.shape[1]} features"
            + (f", target classes={int(y.nunique())}" if y is not None else ", unsupervised")
        )

        # 2. Preprocess
        X = self._preprocess(X)

        # 3. Split
        if y is not None:
            stratify = y if y.nunique() <= 20 else None
            X_train, X_temp, y_train, y_temp = train_test_split(
                X, y,
                test_size=0.3,
                random_state=42,
                stratify=stratify,
            )
            X_val, X_test, y_val, y_test = train_test_split(
                X_temp, y_temp,
                test_size=0.5,
                random_state=42,
                stratify=stratify.iloc[X_temp.index] if stratify is not None else None,
            )
        else:
            # Unsupervised — no labels
            X_train, X_temp = train_test_split(X, test_size=0.3, random_state=42)
            X_val, X_test = train_test_split(X_temp, test_size=0.5, random_state=42)
            y_train = y_val = y_test = None

        logger.info(
            f"Split sizes: train={len(X_train)}, val={len(X_val)}, test={len(X_test)}"
        )

        # 4. Train model
        model = self._get_model_instance()
        train_metrics = self._train_model(model, X_train, y_train, X_val, y_val)
        logger.info(f"Training metrics: {train_metrics}")

        # 5. Evaluate on test set
        test_metrics = self._evaluate_model(model, X_test, y_test)
        logger.info(f"Test metrics: {test_metrics}")

        # 6. Log to MLflow
        mlflow_run_id = self._log_to_mlflow(model, train_metrics, test_metrics)

        # 7. Save artifacts
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        artifact_path = self.output_dir / f"v1_{timestamp}"
        artifact_path.mkdir(parents=True, exist_ok=True)
        self._save_artifacts(model, artifact_path, train_metrics, test_metrics)

        elapsed = time.time() - start

        result: dict[str, Any] = {
            "status": "success",
            "model": self.model_name,
            "tier": self.tier,
            "train_metrics": train_metrics,
            "test_metrics": test_metrics,
            "artifact_path": str(artifact_path),
            "mlflow_run_id": mlflow_run_id,
            "train_samples": len(X_train),
            "val_samples": len(X_val),
            "test_samples": len(X_test),
            "elapsed_seconds": round(elapsed, 2),
        }

        # Persist pipeline report alongside artifacts
        report_path = artifact_path / "pipeline_report.json"
        report_path.write_text(json.dumps(result, indent=2, default=str))

        logger.info(
            f"Pipeline complete: {self.model_name} "
            f"({elapsed:.1f}s) -> {artifact_path}"
        )
        return result

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_data(self) -> tuple[pd.DataFrame, pd.Series | None]:
        """Load training data from S3/local path or fall back to synthetic."""
        data_path = self.config.get("data_path")

        if data_path and Path(data_path).exists():
            logger.info(f"Loading data from {data_path}")
            df = pd.read_parquet(data_path)
            target_col = self.config.get("target_column", "target")
            if target_col in df.columns:
                y = df.pop(target_col)
            else:
                y = None
            return df, y

        logger.info("No data path provided; generating synthetic data")
        return self._generate_synthetic_data()

    def _generate_synthetic_data(self) -> tuple[pd.DataFrame, pd.Series | None]:
        """Generate synthetic training data for development and testing."""
        spec = _SYNTHETIC_SPECS.get(self.model_name)
        if spec is None:
            raise ValueError(f"No synthetic data spec for {self.model_name}")

        rng = np.random.default_rng(42)
        n = spec["n_samples"]
        n_feat = spec["n_features"]
        feature_names = spec["feature_names"]

        X = pd.DataFrame(
            rng.standard_normal((n, n_feat)),
            columns=feature_names[:n_feat],
        )

        # Make some features more realistic (non-negative where semantically appropriate)
        for col in X.columns:
            if any(kw in col for kw in ("count", "duration", "depth", "sessions", "volume", "revenue")):
                X[col] = np.abs(X[col])

        task = spec["task"]
        if task == "classification":
            n_classes = spec.get("n_classes", 2)
            y = pd.Series(rng.integers(0, n_classes, size=n), name="target")
        elif task == "regression":
            weights = rng.standard_normal(n_feat)
            y = pd.Series(
                X.values @ weights + rng.standard_normal(n) * 0.5,
                name="target",
            )
        else:
            # Unsupervised (anomaly detection)
            y = None

        return X, y

    # ------------------------------------------------------------------
    # Preprocessing
    # ------------------------------------------------------------------

    def _preprocess(self, X: pd.DataFrame) -> pd.DataFrame:
        """Basic preprocessing: handle NaN, clip outliers, scale."""
        # Fill NaN with column median
        X = X.fillna(X.median(numeric_only=True))

        # Clip outliers at 1st and 99th percentile for numeric columns
        numeric_cols = X.select_dtypes(include=[np.number]).columns
        for col in numeric_cols:
            q_low = X[col].quantile(0.01)
            q_high = X[col].quantile(0.99)
            X[col] = X[col].clip(lower=q_low, upper=q_high)

        return X

    # ------------------------------------------------------------------
    # Model instantiation
    # ------------------------------------------------------------------

    def _get_model_instance(self) -> Any:
        """Instantiate the correct model class based on model_name.

        During development with synthetic data, falls back to a lightweight
        scikit-learn estimator so the pipeline can run end-to-end.
        """
        from sklearn.ensemble import (
            GradientBoostingClassifier,
            GradientBoostingRegressor,
            IsolationForest,
            RandomForestClassifier,
        )
        from sklearn.linear_model import LogisticRegression

        spec = _SYNTHETIC_SPECS[self.model_name]
        task = spec["task"]

        # Map model names to reasonable stand-in estimators
        fallback_map: dict[str, Any] = {
            "intent_prediction": LogisticRegression(
                C=1.0, max_iter=1000, solver="lbfgs",
            ),
            "bot_detection": RandomForestClassifier(
                n_estimators=100, max_depth=12, min_samples_leaf=5,
                class_weight="balanced", random_state=42, n_jobs=-1,
            ),
            "session_scorer": GradientBoostingRegressor(
                n_estimators=100, max_depth=5, learning_rate=0.05, random_state=42,
            ),
            "identity_resolution": GradientBoostingClassifier(
                n_estimators=150, max_depth=6, learning_rate=0.05, random_state=42,
            ),
            "journey_prediction": GradientBoostingClassifier(
                n_estimators=200, max_depth=6, learning_rate=0.05, random_state=42,
            ),
            "churn_prediction": GradientBoostingClassifier(
                n_estimators=200, max_depth=6, learning_rate=0.05, random_state=42,
            ),
            "ltv_prediction": GradientBoostingRegressor(
                n_estimators=300, max_depth=6, learning_rate=0.05, random_state=42,
            ),
            "anomaly_detection": IsolationForest(
                n_estimators=200, contamination=0.05, random_state=42,
            ),
            "campaign_attribution": GradientBoostingClassifier(
                n_estimators=100, max_depth=5, learning_rate=0.1, random_state=42,
            ),
        }

        model = fallback_map.get(self.model_name)
        if model is None:
            if task == "classification":
                model = GradientBoostingClassifier(random_state=42)
            elif task == "regression":
                model = GradientBoostingRegressor(random_state=42)
            else:
                model = IsolationForest(random_state=42)

        return model

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def _train_model(
        self,
        model: Any,
        X_train: pd.DataFrame,
        y_train: pd.Series | None,
        X_val: pd.DataFrame,
        y_val: pd.Series | None,
    ) -> dict[str, float]:
        """Fit the model and return training metrics."""
        spec = _SYNTHETIC_SPECS[self.model_name]
        task = spec["task"]

        if task == "unsupervised":
            model.fit(X_train)
            scores = model.decision_function(X_train)
            return {
                "anomaly_rate": float(np.mean(model.predict(X_train) == -1)),
                "mean_score": float(np.mean(scores)),
                "std_score": float(np.std(scores)),
            }

        model.fit(X_train, y_train)

        if task == "classification":
            from sklearn.metrics import accuracy_score, f1_score, roc_auc_score

            train_preds = model.predict(X_train)
            metrics: dict[str, float] = {
                "train_accuracy": float(accuracy_score(y_train, train_preds)),
                "train_f1": float(
                    f1_score(y_train, train_preds, average="weighted", zero_division=0)
                ),
            }
            if hasattr(model, "predict_proba") and y_train is not None:
                proba = model.predict_proba(X_train)
                if proba.shape[1] == 2:
                    metrics["train_auc"] = float(
                        roc_auc_score(y_train, proba[:, 1])
                    )
                else:
                    metrics["train_auc"] = float(
                        roc_auc_score(
                            y_train, proba, multi_class="ovr", average="weighted",
                        )
                    )
            return metrics

        # Regression
        from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

        train_preds = model.predict(X_train)
        return {
            "train_mae": float(mean_absolute_error(y_train, train_preds)),
            "train_rmse": float(np.sqrt(mean_squared_error(y_train, train_preds))),
            "train_r2": float(r2_score(y_train, train_preds)),
        }

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def _evaluate_model(
        self, model: Any, X_test: pd.DataFrame, y_test: pd.Series | None
    ) -> dict[str, float]:
        """Evaluate the trained model on the held-out test set."""
        spec = _SYNTHETIC_SPECS[self.model_name]
        task = spec["task"]

        if task == "unsupervised":
            preds = model.predict(X_test)
            scores = model.decision_function(X_test)
            return {
                "test_anomaly_rate": float(np.mean(preds == -1)),
                "test_mean_score": float(np.mean(scores)),
                "test_std_score": float(np.std(scores)),
            }

        if y_test is None:
            return {}

        if task == "classification":
            from sklearn.metrics import (
                accuracy_score,
                f1_score,
                precision_score,
                recall_score,
                roc_auc_score,
            )

            preds = model.predict(X_test)
            metrics: dict[str, float] = {
                "test_accuracy": float(accuracy_score(y_test, preds)),
                "test_f1": float(
                    f1_score(y_test, preds, average="weighted", zero_division=0)
                ),
                "test_precision": float(
                    precision_score(y_test, preds, average="weighted", zero_division=0)
                ),
                "test_recall": float(
                    recall_score(y_test, preds, average="weighted", zero_division=0)
                ),
            }
            if hasattr(model, "predict_proba"):
                proba = model.predict_proba(X_test)
                if proba.shape[1] == 2:
                    metrics["test_auc"] = float(roc_auc_score(y_test, proba[:, 1]))
                else:
                    metrics["test_auc"] = float(
                        roc_auc_score(
                            y_test, proba, multi_class="ovr", average="weighted",
                        )
                    )
            return metrics

        # Regression
        from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

        preds = model.predict(X_test)
        y_np = y_test.values
        mape = float(
            np.mean(np.abs((y_np - preds) / np.clip(np.abs(y_np), 1e-8, None))) * 100
        )
        return {
            "test_mae": float(mean_absolute_error(y_test, preds)),
            "test_rmse": float(np.sqrt(mean_squared_error(y_test, preds))),
            "test_r2": float(r2_score(y_test, preds)),
            "test_mape": mape,
        }

    # ------------------------------------------------------------------
    # MLflow logging
    # ------------------------------------------------------------------

    def _log_to_mlflow(
        self,
        model: Any,
        train_metrics: dict[str, float],
        test_metrics: dict[str, float],
    ) -> str | None:
        """Log parameters, metrics, and model artifact to MLflow."""
        try:
            with mlflow.start_run(run_name=f"{self.model_name}_{int(time.time())}") as run:
                mlflow.log_param("model_name", self.model_name)
                mlflow.log_param("tier", self.tier)
                mlflow.log_param("class_name", self.class_name)

                # Log hyperparameters from config
                for k, v in self.config.items():
                    if isinstance(v, (str, int, float, bool)):
                        mlflow.log_param(k, v)

                # Log metrics
                for k, v in {**train_metrics, **test_metrics}.items():
                    mlflow.log_metric(k, v)

                # Log model
                mlflow.sklearn.log_model(model, artifact_path="model")

                return run.info.run_id
        except Exception as e:
            logger.warning(f"MLflow logging failed (non-fatal): {e}")
            return None

    # ------------------------------------------------------------------
    # Artifact persistence
    # ------------------------------------------------------------------

    def _save_artifacts(
        self,
        model: Any,
        artifact_path: Path,
        train_metrics: dict[str, float],
        test_metrics: dict[str, float],
    ) -> None:
        """Persist model and metadata to the output directory."""
        import joblib

        joblib.dump(model, artifact_path / "model.joblib")

        metadata = {
            "model_name": self.model_name,
            "tier": self.tier,
            "class_name": self.class_name,
            "train_metrics": train_metrics,
            "test_metrics": test_metrics,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "config": self.config,
        }
        (artifact_path / "metadata.json").write_text(
            json.dumps(metadata, indent=2, default=str)
        )
        logger.info(f"Artifacts saved to {artifact_path}")


# ---------------------------------------------------------------------------
# Train all models
# ---------------------------------------------------------------------------


def train_all(output_dir: str = "/tmp/aether-models") -> dict[str, dict[str, Any]]:
    """Train all 9 models sequentially and return aggregated results."""
    results: dict[str, dict[str, Any]] = {}

    for model_name in MODEL_REGISTRY:
        try:
            pipeline = TrainingPipeline(model_name=model_name, output_dir=output_dir)
            results[model_name] = pipeline.run()
        except Exception as e:
            logger.error(f"Failed to train {model_name}: {e}", exc_info=True)
            results[model_name] = {"status": "error", "error": str(e)}

    # Summary
    succeeded = sum(1 for r in results.values() if r.get("status") == "success")
    failed = sum(1 for r in results.values() if r.get("status") == "error")
    logger.info(
        f"\nTRAINING SUMMARY: {succeeded} succeeded, {failed} failed "
        f"out of {len(MODEL_REGISTRY)} models"
    )
    return results


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Aether ML Training Pipeline")
    parser.add_argument(
        "--model",
        type=str,
        default="all",
        help=f"Model to train, or 'all'. Choices: {sorted(MODEL_REGISTRY.keys())}",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="/tmp/aether-models",
        help="Root directory for saving model artifacts",
    )
    parser.add_argument(
        "--experiment",
        type=str,
        default="aether-ml",
        help="MLflow experiment name",
    )
    parser.add_argument(
        "--data-path",
        type=str,
        default=None,
        help="Path to training data (Parquet). Falls back to synthetic if not provided.",
    )

    args = parser.parse_args()

    # Set MLflow experiment
    mlflow.set_experiment(args.experiment)

    if args.model == "all":
        train_all(output_dir=args.output_dir)
    else:
        config: dict[str, Any] = {}
        if args.data_path:
            config["data_path"] = args.data_path

        pipeline = TrainingPipeline(
            model_name=args.model,
            output_dir=args.output_dir,
            config=config,
        )
        result = pipeline.run()
        logger.info(f"Result: {json.dumps(result, indent=2, default=str)}")


if __name__ == "__main__":
    main()
