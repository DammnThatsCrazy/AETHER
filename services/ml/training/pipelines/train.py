"""Unified training runner for all 9 Aether ML models.

Orchestrates end-to-end training pipelines with data loading, preprocessing,
model training, evaluation, MLflow tracking, and artifact persistence.

Usage:
    python -m training.pipelines.train --model intent_prediction --output-dir /tmp/aether-models
    python -m training.pipelines.train --model all --experiment aether-ml
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import mlflow
    _MLFLOW_AVAILABLE = True
except ImportError:
    mlflow = None  # type: ignore[assignment]
    _MLFLOW_AVAILABLE = False

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer

logger = logging.getLogger("aether.ml.training")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

# ---------------------------------------------------------------------------
# Canonical registry — single source of truth for model identity.
# Do not add a duplicate hardcoded MODEL_REGISTRY here.
# ---------------------------------------------------------------------------
try:
    from common.model_registry import list_trainable_models as _list_trainable_models, get_model as _get_model_entry
    _CANONICAL_MODELS: dict[str, Any] = {m.model_id: m for m in _list_trainable_models()}
except Exception as _reg_err:  # registry unavailable during isolated test runs
    logger.warning("Canonical model registry unavailable: %s — using fallback", _reg_err)
    _CANONICAL_MODELS = {}

# Derive flat name→tier map for backwards-compat references and CLI help text.
# Tier is taken from the canonical registry; falls back to "server" if registry failed.
MODEL_REGISTRY: dict[str, tuple[str, str]] = {
    mid: (entry.tier.value, entry.algorithm)
    for mid, entry in _CANONICAL_MODELS.items()
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
# Manifest checksum helper
# ---------------------------------------------------------------------------


def compute_manifest_checksum(manifest: dict[str, Any]) -> str:
    """Return the canonical SHA-256 self-hash of a dataset manifest.

    Computed over a canonical JSON serialization (sorted keys, compact
    separators) of the manifest EXCLUDING the ``checksum`` field itself, so
    the stored checksum can always be verified by re-deriving it from the
    stored manifest.
    """
    import hashlib

    body = {k: v for k, v in manifest.items() if k != "checksum"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Training Pipeline
# ---------------------------------------------------------------------------


class TrainingPipeline:
    """End-to-end training pipeline for a single Aether ML model.

    Steps:
        1. Load data (from S3/local or generate synthetic)
        2. Split RAW data into train / validation / test
        3. Fit preprocessing on the TRAINING split only, then transform
           validation and test with the frozen training-time statistics
           (prevents leakage of holdout quantiles/medians/scale into training)
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
        synthetic_data: bool | None = None,
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
        # Pull tier and algorithm from canonical registry entry when available.
        _entry = _CANONICAL_MODELS.get(model_name)
        self.tier = _entry.tier.value if _entry else MODEL_REGISTRY[model_name][0]
        self.class_name = _entry.algorithm if _entry else MODEL_REGISTRY[model_name][1]
        self._registry_entry = _entry
        # synthetic_data: None means auto-detect (True if no data_path)
        self._synthetic_data_override = synthetic_data

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
        X, y, is_synthetic = self._load_data_with_flag()
        logger.info(
            f"Data loaded: {X.shape[0]} samples, {X.shape[1]} features"
            + (f", target classes={int(y.nunique())}" if y is not None else ", unsupervised")
            + (f" [SYNTHETIC]" if is_synthetic else " [REAL]")
        )

        # 2. Split RAW data BEFORE any preprocessing is fitted, so that
        #    holdout rows can never influence clip bounds, imputation medians,
        #    or scaler statistics.
        if y is not None:
            stratify = y if y.nunique() <= 20 else None
            X_train, X_temp, y_train, y_temp = train_test_split(
                X, y,
                test_size=0.3,
                random_state=42,
                stratify=stratify,
            )
            # y_temp is exactly the label vector aligned with X_temp — safe for
            # any index type (a positional .iloc on label indices is not).
            X_val, X_test, y_val, y_test = train_test_split(
                X_temp, y_temp,
                test_size=0.5,
                random_state=42,
                stratify=y_temp if stratify is not None else None,
            )
        else:
            # Unsupervised — no labels
            X_train, X_temp = train_test_split(X, test_size=0.3, random_state=42)
            X_val, X_test = train_test_split(X_temp, test_size=0.5, random_state=42)
            y_train = y_val = y_test = None

        logger.info(
            f"Split sizes: train={len(X_train)}, val={len(X_val)}, test={len(X_test)}"
        )

        # 3. Fit preprocessing on the training split ONLY, then apply the
        #    frozen transform to validation and test.
        X_train = self._fit_preprocess(X_train)
        X_val = self._transform(X_val)
        X_test = self._transform(X_test)

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
        self._save_artifacts(
            model, artifact_path, train_metrics, test_metrics,
            synthetic_data=is_synthetic,
            training_run_id=mlflow_run_id or "",
            X_train=X_train,
            y_train=y_train,
        )

        # 7.5. Save drift detection baseline sample alongside model artifact
        self._save_baseline(X_train, artifact_path)

        elapsed = time.time() - start

        threshold_passed, _ = self._check_thresholds(test_metrics)

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
            "synthetic_data": is_synthetic,
            "threshold_passed": threshold_passed,
            "production_allowed": False,  # Synthetic artifacts are never production-allowed
            "feature_schema_hash": self._get_feature_schema_hash(),
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
        X, y, _ = self._load_data_with_flag()
        return X, y

    def _load_data_with_flag(self) -> tuple[pd.DataFrame, pd.Series | None, bool]:
        """Load data and return (X, y, is_synthetic) flag."""
        data_source = self.config.get("data_source", "synthetic")
        data_path = self.config.get("data_path")

        if data_source == "s3":
            return self._load_from_s3()

        if data_source == "postgresql":
            return self._load_from_postgresql()

        if data_path and Path(data_path).exists():
            logger.info(f"Loading data from {data_path}")
            df = pd.read_parquet(data_path)
            target_col = self.config.get("target_column", "target")
            if target_col in df.columns:
                y = df.pop(target_col)
            else:
                y = None
            # Respect explicit override, otherwise real data = not synthetic
            is_synthetic = self._synthetic_data_override if self._synthetic_data_override is not None else False
            return df, y, is_synthetic

        logger.info("No data path provided; generating synthetic data")
        X, y = self._generate_synthetic_data()
        return X, y, True

    def _load_from_s3(self) -> tuple[pd.DataFrame, pd.Series | None, bool]:
        """Load training data from S3 (Parquet). Fails closed if credentials absent."""
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError(
                "boto3 is required for S3 data loading: pip install boto3"
            ) from exc

        bucket = self.config.get("s3_bucket") or os.environ.get("TRAINING_S3_BUCKET")
        key = self.config.get("s3_key") or os.environ.get("TRAINING_S3_KEY")
        if not bucket or not key:
            raise ValueError(
                "S3 data source requires s3_bucket and s3_key "
                "(via config or TRAINING_S3_BUCKET / TRAINING_S3_KEY env vars)"
            )

        logger.info("Loading training data from s3://%s/%s", bucket, key)
        s3 = boto3.client("s3")
        try:
            obj = s3.get_object(Bucket=bucket, Key=key)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to fetch s3://{bucket}/{key}: {exc}. "
                "Check credentials and bucket permissions."
            ) from exc

        df = pd.read_parquet(io.BytesIO(obj["Body"].read()))
        target_col = self.config.get("target_column", "target")
        y = df.pop(target_col) if target_col in df.columns else None
        is_synthetic = self._synthetic_data_override if self._synthetic_data_override is not None else False
        logger.info("S3 load complete: %d rows, %d features", len(df), len(df.columns))
        return df, y, is_synthetic

    def _load_from_postgresql(self) -> tuple[pd.DataFrame, pd.Series | None, bool]:
        """Load training data from PostgreSQL. Fails closed if DATABASE_URL absent."""
        try:
            import psycopg2
        except ImportError as exc:
            raise RuntimeError(
                "psycopg2 is required for PostgreSQL data loading: pip install psycopg2-binary"
            ) from exc

        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise RuntimeError(
                "PostgreSQL data source requires DATABASE_URL environment variable"
            )

        sql_query = self.config.get("sql_query")
        if not sql_query:
            raise ValueError(
                "PostgreSQL data source requires sql_query in config"
            )

        logger.info("Loading training data from PostgreSQL for model=%s", self.model_name)
        try:
            conn = psycopg2.connect(database_url)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to connect to PostgreSQL: {exc}. Check DATABASE_URL."
            ) from exc

        try:
            df = pd.read_sql(sql_query, conn, params={"model_id": self.model_name})
        finally:
            conn.close()

        target_col = self.config.get("target_column", "target")
        y = df.pop(target_col) if target_col in df.columns else None
        is_synthetic = self._synthetic_data_override if self._synthetic_data_override is not None else False
        logger.info("PostgreSQL load complete: %d rows, %d features", len(df), len(df.columns))
        return df, y, is_synthetic

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

    def _fit_preprocess(self, X_train: pd.DataFrame) -> pd.DataFrame:
        """Fit the preprocessing pipeline on the TRAINING split only, then transform it.

        Clip quantiles, imputation medians, and scaler statistics are computed
        exclusively from ``X_train``. Validation/test data must be transformed
        with :meth:`_transform` so holdout rows can never influence these
        statistics (no train/test leakage).

        The fitted pipeline is stored on ``self._preprocessing_pipeline`` so it can
        be persisted alongside the model artifact — ensuring training and serving use
        identical preprocessing without manual reconstruction.
        """
        from sklearn.compose import ColumnTransformer

        numeric_cols = list(X_train.select_dtypes(include=[np.number]).columns)
        self._numeric_cols: list[str] = numeric_cols

        # Clip outliers before fitting the scaler — bounds come from TRAIN quantiles.
        X_clipped = X_train.copy()
        self._clip_bounds: dict[str, tuple[float, float]] = {}
        for col in numeric_cols:
            q_low = float(X_train[col].quantile(0.01))
            q_high = float(X_train[col].quantile(0.99))
            X_clipped[col] = X_train[col].clip(lower=q_low, upper=q_high)
            self._clip_bounds[col] = (q_low, q_high)

        num_pipeline = Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
        ])

        self._preprocessing_pipeline = ColumnTransformer(
            transformers=[("num", num_pipeline, numeric_cols)],
            remainder="drop",
            verbose_feature_names_out=False,
        )

        X_transformed = self._preprocessing_pipeline.fit_transform(X_clipped)
        return pd.DataFrame(X_transformed, columns=numeric_cols, index=X_train.index)

    def _transform(self, X: pd.DataFrame) -> pd.DataFrame:
        """Apply the already-fitted preprocessing (train-time statistics) to ``X``.

        Raises RuntimeError if :meth:`_fit_preprocess` has not been called yet.
        """
        pipeline = getattr(self, "_preprocessing_pipeline", None)
        if pipeline is None:
            raise RuntimeError(
                "Preprocessing pipeline is not fitted. Call _fit_preprocess "
                "on the training split before transforming holdout data."
            )

        X_clipped = X.copy()
        for col, (q_low, q_high) in self._clip_bounds.items():
            if col in X_clipped.columns:
                X_clipped[col] = X_clipped[col].clip(lower=q_low, upper=q_high)

        X_transformed = pipeline.transform(X_clipped)
        return pd.DataFrame(X_transformed, columns=self._numeric_cols, index=X.index)

    # ------------------------------------------------------------------
    # Model instantiation
    # ------------------------------------------------------------------

    def _get_model_instance(self) -> Any:
        """Instantiate the estimator declared by the canonical registry.

        Estimator choices are derived from the registry's ``algorithm`` field so
        training and registry stay in sync.  XGBoost is used for churn/LTV per the
        registry; GradientBoosting is used for models whose registry entry says so.
        """
        from sklearn.ensemble import (
            GradientBoostingClassifier,
            GradientBoostingRegressor,
            IsolationForest,
            RandomForestClassifier,
        )
        from sklearn.linear_model import LogisticRegression

        # Try XGBoost (listed in optional [ml] extras)
        try:
            from xgboost import XGBClassifier, XGBRegressor
            _xgb_available = True
        except ImportError:
            _xgb_available = False
            XGBClassifier = GradientBoostingClassifier  # type: ignore[assignment,misc]
            XGBRegressor = GradientBoostingRegressor  # type: ignore[assignment,misc]

        # Estimator per canonical registry algorithm name
        estimator_map: dict[str, Any] = {
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
            # Churn/LTV use XGBoost per registry; fall back to GBM if not installed
            "churn_prediction": (
                XGBClassifier(
                    n_estimators=200, max_depth=6, learning_rate=0.05,
                    random_state=42, eval_metric="logloss", use_label_encoder=False,
                ) if _xgb_available else GradientBoostingClassifier(
                    n_estimators=200, max_depth=6, learning_rate=0.05, random_state=42,
                )
            ),
            "ltv_prediction": (
                XGBRegressor(
                    n_estimators=300, max_depth=6, learning_rate=0.05,
                    random_state=42, eval_metric="rmse",
                ) if _xgb_available else GradientBoostingRegressor(
                    n_estimators=300, max_depth=6, learning_rate=0.05, random_state=42,
                )
            ),
            "anomaly_detection": IsolationForest(
                n_estimators=200, contamination=0.05, random_state=42,
            ),
            # campaign_attribution uses a GBM trained on touchpoint features;
            # Shapley credit allocation is applied post-prediction at serve time.
            "campaign_attribution": GradientBoostingClassifier(
                n_estimators=100, max_depth=5, learning_rate=0.1, random_state=42,
            ),
        }

        spec = _SYNTHETIC_SPECS[self.model_name]
        task = spec["task"]
        model = estimator_map.get(self.model_name)
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
        """Log parameters, metrics, and model artifact to MLflow (optional)."""
        if not _MLFLOW_AVAILABLE:
            logger.debug("mlflow not installed — skipping experiment tracking")
            return None
        try:
            with mlflow.start_run(run_name=f"{self.model_name}_{int(time.time())}") as run:
                mlflow.log_param("model_name", self.model_name)
                mlflow.log_param("tier", self.tier)
                mlflow.log_param("class_name", self.class_name)

                for k, v in self.config.items():
                    if isinstance(v, (str, int, float, bool)):
                        mlflow.log_param(k, v)

                for k, v in {**train_metrics, **test_metrics}.items():
                    mlflow.log_metric(k, v)

                mlflow.sklearn.log_model(model, artifact_path="model")
                return run.info.run_id
        except Exception as e:
            logger.warning("MLflow logging failed (non-fatal): %s", e)
            return None

    # ------------------------------------------------------------------
    # Artifact persistence
    # ------------------------------------------------------------------

    def _check_thresholds(self, test_metrics: dict[str, float]) -> tuple[bool, dict[str, float]]:
        """Check test metrics against minimum thresholds from the registry.

        FAIL-CLOSED: every threshold metric declared by the registry must be
        present and finite in ``test_metrics``. A missing, NaN, or infinite
        metric fails the gate — a run producing zero test metrics can never
        report ``threshold_passed=True``.

        Direction: metrics listed in
        ``training.configs.model_configs.THRESHOLD_CAP_METRICS`` are CAPS
        (actual <= threshold passes, e.g. test_mae, test_anomaly_rate); all
        other metrics are floors (actual >= threshold passes).
        """
        import math

        try:
            from common.model_registry import get_model
            entry = get_model(self.model_name)
            thresholds = entry.minimum_metrics if entry else {}
        except ImportError:
            thresholds = {}

        if not thresholds:
            return True, {}

        try:
            from training.configs.model_configs import THRESHOLD_CAP_METRICS as _cap_metrics
        except ImportError:
            # Keep train.py importable in isolated test runs — must stay in
            # sync with training/configs/model_configs.py.
            _cap_metrics = frozenset({"test_mae", "test_rmse", "test_mape", "test_anomaly_rate"})

        passed = True
        results: dict[str, float] = {}
        for metric, threshold in thresholds.items():
            actual = test_metrics.get(metric)
            is_cap = metric in _cap_metrics
            direction = "≤" if is_cap else "≥"
            if (
                actual is None
                or isinstance(actual, bool)
                or not isinstance(actual, (int, float))
                or not math.isfinite(float(actual))
            ):
                passed = False
                results[metric] = float("nan")
                logger.warning(
                    "Threshold FAIL-CLOSED: %s.%s is missing or non-finite (%r); "
                    "required %s %.4f",
                    self.model_name, metric, actual, direction, threshold,
                )
                continue

            actual = float(actual)
            ok = actual <= threshold if is_cap else actual >= threshold
            results[metric] = actual
            if not ok:
                passed = False
                logger.warning(
                    "Threshold NOT met: %s.%s = %.4f (threshold %.4f, direction=%s)",
                    self.model_name, metric, actual, threshold, direction,
                )
            else:
                logger.info(
                    "Threshold met: %s.%s = %.4f ✓",
                    self.model_name, metric, actual,
                )

        return passed, results

    def _get_feature_schema_hash(self) -> str:
        """Return the feature schema hash from the feature contract."""
        try:
            from common.feature_contracts import compute_schema_hash
            return compute_schema_hash(self.model_name)
        except (ImportError, KeyError):
            return ""

    def _save_dataset_manifest(
        self,
        X: "pd.DataFrame",
        y: "pd.Series | None",
        artifact_path: Path,
        is_synthetic: bool,
        data_source: str = "synthetic",
    ) -> None:
        """Produce dataset_manifest.json alongside the artifact."""
        import hashlib
        import subprocess

        try:
            git_sha = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
            ).decode().strip()
        except Exception:
            git_sha = "unknown"

        manifest = {
            "dataset_id": f"{self.model_name}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
            "source": data_source,
            "synthetic_data": is_synthetic,
            "row_count": int(len(X)),
            "feature_count": int(X.shape[1]),
            "feature_names": list(X.columns),
            "target_distribution": (
                y.value_counts(normalize=True).to_dict() if y is not None and hasattr(y, "value_counts") else {}
            ),
            "missing_rate": float(X.isnull().mean().mean()),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "git_sha": git_sha,
            "model_id": self.model_name,
            "feature_schema_hash": self._get_feature_schema_hash(),
            "consent_policy": "synthetic" if is_synthetic else "tenant_scoped",
        }

        manifest_path = artifact_path / "dataset_manifest.json"
        # Canonical self-hash: computed over the manifest EXCLUDING the checksum
        # field, so verifiers can recompute it from the stored file and match.
        manifest["checksum"] = compute_manifest_checksum(manifest)
        manifest_path.write_text(json.dumps(manifest, indent=2, default=str))
        logger.info("Dataset manifest saved: %s rows -> %s", len(X), manifest_path)

    def _save_artifacts(
        self,
        model: Any,
        artifact_path: Path,
        train_metrics: dict[str, float],
        test_metrics: dict[str, float],
        synthetic_data: bool = True,
        training_run_id: str = "",
        X_train: "pd.DataFrame | None" = None,
        y_train: "pd.Series | None" = None,
    ) -> None:
        """Persist model, preprocessing pipeline, canonical metadata, and artifact registry entry."""
        import joblib

        artifact_file = artifact_path / "model.joblib"
        joblib.dump(model, artifact_file)

        # Persist fitted preprocessing pipeline so serving uses identical transforms.
        preprocessing_pipeline = getattr(self, "_preprocessing_pipeline", None)
        if preprocessing_pipeline is not None:
            preprocessing_path = artifact_path / "preprocessing.joblib"
            joblib.dump(preprocessing_pipeline, preprocessing_path)
            # Also persist clip bounds for documentation
            clip_bounds = getattr(self, "_clip_bounds", {})
            if clip_bounds:
                (artifact_path / "preprocessing_meta.json").write_text(
                    json.dumps({
                        "clip_bounds": clip_bounds,
                        "feature_order": list(clip_bounds.keys()),
                        "scaler": "StandardScaler",
                        "imputer_strategy": "median",
                    }, indent=2)
                )

        # Dataset manifest (if raw data available)
        if X_train is not None:
            self._save_dataset_manifest(X_train, y_train, artifact_path, synthetic_data)

        threshold_passed, _ = self._check_thresholds(test_metrics)
        feature_schema_hash = self._get_feature_schema_hash()

        # Pipeline-specific fields NOT covered by the canonical ArtifactMetadata
        # schema. These are merged ON TOP of the canonical record so a single
        # metadata.json carries both (previously the registry write discarded
        # tier/class_name/config/train_metrics/test_metrics).
        rich_fields = {
            "model_name": self.model_name,
            "tier": self.tier,
            "class_name": self.class_name,
            "train_metrics": train_metrics,
            "test_metrics": test_metrics,
            "config": self.config,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }

        # Canonical artifact-registry record (checksum, HMAC, provenance).
        canonical: dict[str, Any]
        try:
            from common.artifact_registry import save_artifact
            registry_meta = save_artifact(
                model_id=self.model_name,
                artifact_path=artifact_file,
                artifact_version=artifact_path.name,
                promotion_state="trained",
                artifact_format="joblib",
                training_run_id=training_run_id or "",
                feature_schema_hash=feature_schema_hash,
                metrics={**train_metrics, **test_metrics},
                thresholds={},
                threshold_passed=threshold_passed,
                synthetic_data=synthetic_data,
            )
            canonical = registry_meta.to_dict()
        except Exception as exc:
            logger.debug("artifact_registry.save_artifact unavailable: %s", exc)
            # Fallback for isolated environments: build an equivalent canonical
            # record locally so metadata.json still carries checksum/provenance.
            import hashlib as _hashlib

            _h = _hashlib.sha256()
            with open(artifact_file, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    _h.update(chunk)
            canonical = {
                "model_id": self.model_name,
                "artifact_version": artifact_path.name,
                "promotion_state": "trained",
                "artifact_format": "joblib",
                "artifact_path": str(artifact_file),
                "checksum_sha256": _h.hexdigest(),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "created_by": "training-pipeline",
                "training_run_id": training_run_id or "",
                "feature_schema_hash": feature_schema_hash,
                "metrics": {**train_metrics, **test_metrics},
                "thresholds": {},
                "threshold_passed": threshold_passed,
                "synthetic_data": synthetic_data,
                "production_allowed": False,  # Never allow production for training output
                "disabled": False,
                "rollback_from": None,
                "notes": "",
                "hmac_signature": None,
            }

        # Single final metadata.json write: canonical fields win on conflict,
        # rich pipeline fields are additive (ArtifactMetadata.from_dict filters
        # unknown keys, so registry loads are unaffected).
        metadata = {**rich_fields, **canonical}
        (artifact_path / "metadata.json").write_text(
            json.dumps(metadata, indent=2, default=str)
        )

        if synthetic_data:
            logger.warning(
                "Artifact saved with synthetic_data=True — NOT production-allowed: model=%s",
                self.model_name,
            )
        else:
            logger.info(
                "Artifact saved: model=%s threshold_passed=%s",
                self.model_name, threshold_passed,
            )
        logger.info("Artifacts saved to %s", artifact_path)

    def _save_baseline(self, X_train: "pd.DataFrame", artifact_path: Path) -> None:
        """Save a random sample of training features as the drift detection baseline.

        The baseline is used by the serving API to detect distribution shift
        between training-time features and live production inputs.
        """
        import joblib

        n_sample = min(1000, len(X_train))
        baseline = X_train.sample(n=n_sample, random_state=42).reset_index(drop=True)
        baseline_path = artifact_path / "baseline.joblib"
        joblib.dump(baseline, baseline_path)

        baseline_meta = {
            "model_id": self.model_name,
            "n_samples": n_sample,
            "numeric_features": list(baseline.select_dtypes(include="number").columns),
            "categorical_features": list(baseline.select_dtypes(exclude="number").columns),
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        (artifact_path / "baseline_meta.json").write_text(
            json.dumps(baseline_meta, indent=2)
        )
        logger.info("Drift baseline saved: %d rows -> %s", n_sample, baseline_path)


# ---------------------------------------------------------------------------
# Train all models
# ---------------------------------------------------------------------------


def train_all(output_dir: str = "/tmp/aether-models") -> dict[str, dict[str, Any]]:
    """Train all registered trainable models and return aggregated results.

    Iterates the canonical model registry (``list_trainable_models()``) rather than
    a hardcoded list.  Exits nonzero (raises SystemExit) when any model fails.
    """
    results: dict[str, dict[str, Any]] = {}

    # Use canonical registry; fall back to MODULE-level MODEL_REGISTRY if import failed.
    model_names = list(_CANONICAL_MODELS.keys()) if _CANONICAL_MODELS else list(MODEL_REGISTRY.keys())

    for model_name in model_names:
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
        f"out of {len(model_names)} models"
    )

    if failed:
        raise SystemExit(
            f"Training completed with {failed} failure(s). "
            "See logs above for details."
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
        "--input-path",
        type=str,
        default=None,
        dest="data_path",
        help="Path to training data (Parquet or CSV). Falls back to synthetic if not provided.",
    )
    parser.add_argument(
        "--data",
        "--data-source",
        type=str,
        default="synthetic",
        dest="data_source",
        choices=["synthetic", "local", "s3", "postgresql"],
        help="Data source type (synthetic|local|s3|postgresql).",
    )
    parser.add_argument(
        "--env",
        type=str,
        default=None,
        help="Environment (local|staging|production). Overrides AETHER_ENV.",
    )
    parser.add_argument(
        "--tenant-id",
        type=str,
        default=None,
        help="Tenant ID for multi-tenant training.",
    )
    parser.add_argument(
        "--tracking",
        type=str,
        default="mlflow",
        choices=["mlflow", "none"],
        help="Experiment tracking backend.",
    )
    parser.add_argument(
        "--s3-bucket",
        type=str,
        default=None,
        dest="s3_bucket",
        help="S3 bucket name (used when --data=s3).",
    )
    parser.add_argument(
        "--s3-key",
        type=str,
        default=None,
        dest="s3_key",
        help="S3 object key for training data (used when --data=s3).",
    )
    parser.add_argument(
        "--sql-query",
        type=str,
        default=None,
        dest="sql_query",
        help="SQL SELECT query for training data (used when --data=postgresql).",
    )

    args = parser.parse_args()

    if args.env:
        os.environ["AETHER_ENV"] = args.env

    if args.tracking == "mlflow" and _MLFLOW_AVAILABLE:
        try:
            mlflow.set_experiment(args.experiment)
        except Exception as e:
            logger.warning("MLflow experiment setup failed (continuing): %s", e)
    elif args.tracking == "mlflow" and not _MLFLOW_AVAILABLE:
        logger.warning("mlflow not installed — experiment tracking disabled")

    if args.model == "all":
        train_all(output_dir=args.output_dir)
    else:
        config: dict[str, Any] = {}
        if args.data_path:
            config["data_path"] = args.data_path
        if args.tenant_id:
            config["tenant_id"] = args.tenant_id
        if args.data_source and args.data_source != "synthetic":
            config["data_source"] = args.data_source
        if args.s3_bucket:
            config["s3_bucket"] = args.s3_bucket
        if args.s3_key:
            config["s3_key"] = args.s3_key
        if args.sql_query:
            config["sql_query"] = args.sql_query

        is_synthetic = args.data_source == "synthetic" and not args.data_path

        pipeline = TrainingPipeline(
            model_name=args.model,
            output_dir=args.output_dir,
            config=config,
            synthetic_data=is_synthetic,
        )
        result = pipeline.run()
        logger.info(f"Result: {json.dumps(result, indent=2, default=str)}")


if __name__ == "__main__":
    main()
