"""
Base classes for all Aether ML models.

Provides the foundational abstractions used across all 9 Aether models:
  Edge (<100ms): Intent Prediction, Bot Detection, Session Scorer
  Server: Identity Resolution, Journey Prediction, Churn Prediction,
          LTV Prediction, Anomaly Detection, Campaign Attribution

Core components:
  - AetherModel: Abstract base class every model must implement.
  - FeatureStore: Online (Redis) + offline (S3/Parquet) feature storage.
  - ModelRegistry: MLflow-backed model lifecycle management.
  - FeatureEngineer: Shared feature computation for sessions, identities,
    behavioral biometrics, Web3 wallets, journey sequences, and attribution.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import joblib
import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

logger = logging.getLogger("aether.ml")


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class DeploymentTarget(str, Enum):
    """Where a trained model will be served."""

    EDGE_TFJS = "edge_tfjs"
    EDGE_TFLITE = "edge_tflite"
    EDGE_ONNX = "edge_onnx"
    EDGE_COREML = "edge_coreml"
    SERVER_SAGEMAKER = "server_sagemaker"
    SERVER_LAMBDA = "server_lambda"
    SERVER_ECS = "server_ecs"


class ModelStage(str, Enum):
    """Lifecycle stage of a registered model."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    ARCHIVED = "archived"




class ModelType(str, Enum):
    INTENT_PREDICTION = "intent_prediction"
    BOT_DETECTION = "bot_detection"
    SESSION_SCORER = "session_scorer"
    IDENTITY_RESOLUTION = "identity_resolution"
    JOURNEY_PREDICTION = "journey_prediction"
    CHURN_PREDICTION = "churn_prediction"
    LTV_PREDICTION = "ltv_prediction"
    ANOMALY_DETECTION = "anomaly_detection"
    CAMPAIGN_ATTRIBUTION = "campaign_attribution"


# ---------------------------------------------------------------------------
# Pydantic data models
# ---------------------------------------------------------------------------

class ModelMetadata(BaseModel):
    """Immutable snapshot of model provenance and performance."""

    name: str = ""
    model_id: str = ""
    model_type: ModelType = ModelType.CHURN_PREDICTION
    version: str = "0.0.1"
    deployment_target: DeploymentTarget = DeploymentTarget.SERVER_ECS
    stage: ModelStage = ModelStage.DEVELOPMENT
    metrics: dict[str, float] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    feature_columns: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# AetherModel ABC
# ---------------------------------------------------------------------------

class AetherModel(ABC):
    """Abstract base class for every Aether ML model.

    Subclasses must implement:
      - train(X, y, **kwargs) -> dict[str, float]
      - predict(X) -> np.ndarray
      - get_feature_names() -> list[str]
      - model_type (property) -> str

    Concrete helpers provided:
      - save / load  (joblib serialisation)
      - get_metadata
      - evaluate
    """

    def __init__(self, metadata: ModelMetadata) -> None:
        self.metadata: ModelMetadata = metadata
        self.model_: Any = None
        self.is_fitted: bool = False

    # -- abstract interface --------------------------------------------------

    @abstractmethod
    def train(
        self,
        X: pd.DataFrame | np.ndarray,
        y: pd.Series | np.ndarray | None = None,
        **kwargs: Any,
    ) -> dict[str, float]:
        """Train the model and return training metrics."""
        ...

    @abstractmethod
    def predict(self, X: pd.DataFrame | np.ndarray) -> np.ndarray:
        """Return predictions for *X*."""
        ...

    @abstractmethod
    def get_feature_names(self) -> list[str]:
        """Return ordered list of feature names the model expects."""
        ...

    @property
    @abstractmethod
    def model_type(self) -> str:
        """Human-readable model type identifier (e.g. ``'churn_xgboost'``)."""
        ...

    # -- concrete helpers ----------------------------------------------------

    def save(self, path: str | Path) -> None:
        """Persist the model and metadata to *path* using joblib."""
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)

        joblib.dump(self.model_, path / "model.joblib")

        meta_path = path / "metadata.json"
        meta_path.write_text(self.metadata.model_dump_json(indent=2))

        logger.info("Saved %s v%s to %s", self.metadata.name, self.metadata.version, path)

    def load(self, path: str | Path) -> None:
        """Restore a previously saved model from *path*."""
        path = Path(path)

        self.model_ = joblib.load(path / "model.joblib")

        meta_path = path / "metadata.json"
        if meta_path.exists():
            self.metadata = ModelMetadata.model_validate_json(meta_path.read_text())

        self.is_fitted = True
        logger.info("Loaded %s v%s from %s", self.metadata.name, self.metadata.version, path)

    def get_metadata(self) -> ModelMetadata:
        """Return a copy of the current model metadata."""
        return self.metadata.model_copy()

    def evaluate(
        self,
        X: pd.DataFrame | np.ndarray,
        y: pd.Series | np.ndarray,
    ) -> dict[str, float]:
        """Run predictions and return an evaluation metrics dict.

        The default implementation delegates to sklearn helpers; subclasses
        may override for model-specific metrics.
        """
        from sklearn.metrics import (
            accuracy_score,
            f1_score,
            mean_absolute_error,
            mean_squared_error,
            precision_score,
            r2_score,
            recall_score,
        )

        y_pred = self.predict(X)
        y_true = np.asarray(y)

        # Heuristic: treat as classification if few unique values
        unique_values = np.unique(y_true)
        if len(unique_values) <= 20:
            metrics: dict[str, float] = {
                "accuracy": float(accuracy_score(y_true, y_pred)),
                "precision": float(precision_score(y_true, y_pred, average="weighted", zero_division=0)),
                "recall": float(recall_score(y_true, y_pred, average="weighted", zero_division=0)),
                "f1": float(f1_score(y_true, y_pred, average="weighted", zero_division=0)),
            }
        else:
            metrics = {
                "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
                "mae": float(mean_absolute_error(y_true, y_pred)),
                "r2": float(r2_score(y_true, y_pred)),
            }

        self.metadata.metrics.update(metrics)
        self.metadata.updated_at = datetime.now(timezone.utc)
        return metrics


# ---------------------------------------------------------------------------
# FeatureStore
# ---------------------------------------------------------------------------

class FeatureStore:
    """Unified online (Redis) and offline (S3 / Parquet) feature storage.

    Online features power real-time inference; offline features feed training
    pipelines.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        s3_bucket: str = "aether-features",
        region: str = "us-east-1",
    ) -> None:
        self.redis_url = redis_url
        self.s3_bucket = s3_bucket
        self.region = region
        self._redis_client: Any = None
        self._s3_client: Any = None

    # -- online (Redis) ------------------------------------------------------

    def get_online_features(
        self,
        entity_id: str,
        feature_group: str,
    ) -> dict[str, Any]:
        """Read features for a single entity from Redis."""
        client = self._get_redis_client()
        key = f"features:{feature_group}:{entity_id}"
        raw = client.get(key)
        if raw is None:
            return {}
        return json.loads(raw)

    def put_online_features(
        self,
        entity_id: str,
        feature_group: str,
        features: dict[str, Any],
        ttl: int = 3600,
    ) -> None:
        """Write features for a single entity into Redis with a TTL."""
        client = self._get_redis_client()
        key = f"features:{feature_group}:{entity_id}"
        client.setex(key, ttl, json.dumps(features, default=str))

    # -- offline (S3 / Parquet) ----------------------------------------------

    def get_offline_features(
        self,
        feature_group: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """Read a date-partitioned Parquet dataset from S3.

        Returns a concatenated DataFrame for all partitions between
        *start_date* and *end_date* (inclusive, ``YYYY-MM-DD``).
        """
        import pyarrow.parquet as pq

        s3 = self._get_s3_client()
        prefix = f"{feature_group}/"

        # List partition objects that fall within the date range
        paginator = s3.get_paginator("list_objects_v2")
        frames: list[pd.DataFrame] = []

        for page in paginator.paginate(Bucket=self.s3_bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                obj_key: str = obj["Key"]
                # Expect keys like  feature_group/dt=2024-01-15/part-0.parquet
                for part in obj_key.split("/"):
                    if part.startswith("dt="):
                        dt_str = part.split("=", 1)[1]
                        if start_date <= dt_str <= end_date:
                            response = s3.get_object(Bucket=self.s3_bucket, Key=obj_key)
                            buf = io.BytesIO(response["Body"].read())
                            frames.append(pq.read_table(buf).to_pandas())
                        break

        if not frames:
            logger.warning(
                "No offline features found for %s between %s and %s",
                feature_group,
                start_date,
                end_date,
            )
            return pd.DataFrame()

        return pd.concat(frames, ignore_index=True)

    def put_offline_features(
        self,
        feature_group: str,
        df: pd.DataFrame,
    ) -> None:
        """Write a DataFrame as Parquet to S3, partitioned by today's date."""
        import pyarrow as pa
        import pyarrow.parquet as pq

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        key = f"{feature_group}/dt={today}/data.parquet"

        table = pa.Table.from_pandas(df)
        buf = io.BytesIO()
        pq.write_table(table, buf)
        buf.seek(0)

        s3 = self._get_s3_client()
        s3.put_object(Bucket=self.s3_bucket, Key=key, Body=buf.getvalue())

        logger.info(
            "Wrote %d rows to s3://%s/%s",
            len(df),
            self.s3_bucket,
            key,
        )

    # -- private helpers -----------------------------------------------------

    def _get_redis_client(self) -> Any:
        """Lazy-initialise and return a Redis client."""
        if self._redis_client is None:
            import redis

            self._redis_client = redis.from_url(self.redis_url, decode_responses=True)
        return self._redis_client

    def _get_s3_client(self) -> Any:
        """Lazy-initialise and return a boto3 S3 client."""
        if self._s3_client is None:
            import boto3

            self._s3_client = boto3.client("s3", region_name=self.region)
        return self._s3_client


# ---------------------------------------------------------------------------
# ModelRegistry
# ---------------------------------------------------------------------------

class ModelRegistry:
    """MLflow-backed model registration, promotion, and retrieval."""

    def __init__(self, tracking_uri: str = "http://localhost:5000") -> None:
        self.tracking_uri = tracking_uri

    def register_model(
        self,
        model: AetherModel,
        metrics: dict[str, float],
        artifacts_path: str,
    ) -> str:
        """Register a trained model with MLflow, logging metrics and artifacts.

        Returns the MLflow run ID.
        """
        import mlflow

        mlflow.set_tracking_uri(self.tracking_uri)
        model_name = f"aether-{model.metadata.name}"

        with mlflow.start_run(run_name=f"{model_name}_v{model.metadata.version}") as run:
            mlflow.log_metrics(metrics)
            mlflow.log_params(
                {
                    "model_type": model.model_type,
                    "version": model.metadata.version,
                    "deployment_target": model.metadata.deployment_target.value,
                    "stage": model.metadata.stage.value,
                }
            )
            mlflow.log_artifact(artifacts_path)
            mlflow.register_model(
                f"runs:/{run.info.run_id}/model",
                model_name,
            )

            logger.info(
                "Registered %s v%s  run_id=%s",
                model_name,
                model.metadata.version,
                run.info.run_id,
            )
            return run.info.run_id

    def load_model(self, name: str, stage: ModelStage = ModelStage.PRODUCTION) -> AetherModel:
        """Load a model from the registry by name and stage.

        Returns a reconstituted ``AetherModel`` subclass instance.
        """
        import mlflow

        mlflow.set_tracking_uri(self.tracking_uri)
        model_name = f"aether-{name}"
        model_uri = f"models:/{model_name}/{stage.value}"

        loaded = mlflow.pyfunc.load_model(model_uri)
        logger.info("Loaded %s @ stage=%s from MLflow", model_name, stage.value)
        return loaded  # type: ignore[return-value]

    def promote_model(
        self,
        name: str,
        from_stage: ModelStage,
        to_stage: ModelStage,
    ) -> None:
        """Transition a model version from one stage to another."""
        import mlflow

        client = mlflow.tracking.MlflowClient(self.tracking_uri)
        model_name = f"aether-{name}"

        # Find the latest version in the source stage
        versions = client.get_latest_versions(model_name, stages=[from_stage.value])
        if not versions:
            raise ValueError(
                f"No version of {model_name} found in stage {from_stage.value}"
            )

        latest = versions[0]
        client.transition_model_version_stage(
            name=model_name,
            version=latest.version,
            stage=to_stage.value,
        )
        logger.info(
            "Promoted %s v%s: %s -> %s",
            model_name,
            latest.version,
            from_stage.value,
            to_stage.value,
        )

    def get_latest_version(self, name: str, stage: ModelStage = ModelStage.PRODUCTION) -> str:
        """Return the latest version string for *name* at *stage*."""
        import mlflow

        client = mlflow.tracking.MlflowClient(self.tracking_uri)
        model_name = f"aether-{name}"
        versions = client.get_latest_versions(model_name, stages=[stage.value])
        if not versions:
            raise ValueError(f"No version of {model_name} found at stage {stage.value}")
        return versions[0].version


# ---------------------------------------------------------------------------
# FeatureEngineer
# ---------------------------------------------------------------------------

class FeatureEngineer:
    """Shared feature computation functions used across all Aether models.

    Every static method accepts a raw event DataFrame and returns a
    feature DataFrame (or list of sequences) ready for model consumption.
    """

    # -- session features (edge models) --------------------------------------

    @staticmethod
    def compute_session_features(events: pd.DataFrame) -> pd.DataFrame:
        """Aggregate raw events into session-level features.

        Expected columns: ``session_id``, ``timestamp``, ``event_type``,
        ``page_url``, ``scroll_depth``.
        """
        agg = events.groupby("session_id").agg(
            event_count=("event_type", "count"),
            page_views=("event_type", lambda s: (s == "page_view").sum()),
            click_count=("event_type", lambda s: (s == "click").sum()),
            duration_s=("timestamp", lambda s: (s.max() - s.min()).total_seconds()),
            unique_pages=("page_url", "nunique"),
            max_scroll_depth=("scroll_depth", "max"),
            has_conversion=("event_type", lambda s: int((s == "conversion").any())),
            has_form_submit=("event_type", lambda s: int((s == "form_submit").any())),
        ).reset_index()

        eps = 1e-6  # avoid division by zero
        agg["pages_per_minute"] = agg["page_views"] / (agg["duration_s"] / 60.0 + eps)
        agg["events_per_minute"] = agg["event_count"] / (agg["duration_s"] / 60.0 + eps)
        agg["click_rate"] = agg["click_count"] / (agg["page_views"] + 1)
        agg["is_bounce"] = (agg["page_views"] <= 1).astype(int)

        return agg

    # -- identity features (churn / LTV) ------------------------------------

    @staticmethod
    def compute_identity_features(events: pd.DataFrame) -> pd.DataFrame:
        """Roll up session-level rows into identity-level features.

        Expected columns: ``identity_id``, ``session_id``, ``event_count``,
        ``duration_s``, ``has_conversion``, ``page_views``, ``max_scroll_depth``,
        ``started_at``.
        """
        agg = events.groupby("identity_id").agg(
            total_sessions=("session_id", "nunique"),
            total_events=("event_count", "sum"),
            avg_session_duration=("duration_s", "mean"),
            total_conversions=("has_conversion", "sum"),
            first_seen=("started_at", "min"),
            last_seen=("started_at", "max"),
            avg_pages_per_session=("page_views", "mean"),
            avg_scroll_depth=("max_scroll_depth", "mean"),
        ).reset_index()

        now = pd.Timestamp.utcnow().tz_localize(None)
        agg["days_since_first_visit"] = (now - agg["first_seen"]).dt.days
        agg["days_since_last_visit"] = (now - agg["last_seen"]).dt.days
        agg["visit_frequency"] = agg["total_sessions"] / (agg["days_since_first_visit"] + 1)
        agg["conversion_rate"] = agg["total_conversions"] / (agg["total_sessions"] + 1)

        return agg

    # -- behavioral features (bot detection) ---------------------------------

    @staticmethod
    def compute_behavioral_features(events: pd.DataFrame) -> pd.DataFrame:
        """Compute mouse-entropy and timing-variance features for bot detection.

        Expected columns: ``session_id``, ``timestamp``, ``event_type``,
        ``mouse_x``, ``mouse_y``.
        """

        def _session_features(g: pd.DataFrame) -> pd.Series:
            time_diffs = g["timestamp"].diff().dt.total_seconds().dropna()

            # Mouse trajectory entropy (approximate via displacement variance)
            dx = g["mouse_x"].diff().dropna()
            dy = g["mouse_y"].diff().dropna()
            displacement = np.sqrt(dx**2 + dy**2)

            # Action type entropy
            probs = g["event_type"].value_counts(normalize=True).values
            action_entropy = float(-np.sum(probs * np.log2(probs + 1e-12)))

            return pd.Series(
                {
                    "avg_time_between_actions": time_diffs.mean() if len(time_diffs) else 0.0,
                    "timing_variance": time_diffs.var() if len(time_diffs) > 1 else 0.0,
                    "mouse_velocity_mean": displacement.mean() if len(displacement) else 0.0,
                    "mouse_velocity_std": displacement.std() if len(displacement) > 1 else 0.0,
                    "mouse_entropy": float(displacement.std() / (displacement.mean() + 1e-12))
                    if len(displacement) > 1
                    else 0.0,
                    "action_type_entropy": action_entropy,
                    "unique_action_types": g["event_type"].nunique(),
                    "has_keyboard_input": int((g["event_type"] == "keypress").any()),
                    "has_scroll": int((g["event_type"] == "scroll").any()),
                }
            )

        features = events.groupby("session_id").apply(_session_features).reset_index()
        return features

    # -- Web3 features -------------------------------------------------------

    @staticmethod
    def compute_web3_features(events: pd.DataFrame) -> pd.DataFrame:
        """Derive wallet-level features from on-chain transaction events.

        Expected columns: ``wallet_address``, ``tx_hash``, ``chain_id``,
        ``gas_used``, ``to_address``, ``timestamp``.
        """
        agg = events.groupby("wallet_address").agg(
            tx_count=("tx_hash", "count"),
            unique_chains=("chain_id", "nunique"),
            total_gas_used=("gas_used", "sum"),
            unique_interactions=("to_address", "nunique"),
            first_tx=("timestamp", "min"),
            last_tx=("timestamp", "max"),
        ).reset_index()

        agg["wallet_age_days"] = (agg["last_tx"] - agg["first_tx"]).dt.days
        agg["tx_frequency"] = agg["tx_count"] / (agg["wallet_age_days"] + 1)
        agg["avg_gas_per_tx"] = agg["total_gas_used"] / (agg["tx_count"] + 1)

        return agg

    # -- journey sequences (LSTM + Attention) --------------------------------

    @staticmethod
    def compute_journey_sequences(events: pd.DataFrame) -> list[list[str]]:
        """Convert event streams into ordered token sequences per identity.

        Each token encodes ``event_type:page_category`` (e.g.
        ``"click:pricing"``).

        Expected columns: ``identity_id``, ``timestamp``, ``event_type``,
        ``page_category``.
        """
        events = events.sort_values(["identity_id", "timestamp"])
        sequences: list[list[str]] = []

        for _identity_id, group in events.groupby("identity_id"):
            tokens = [
                f"{row['event_type']}:{row.get('page_category', 'unknown')}"
                for _, row in group.iterrows()
            ]
            sequences.append(tokens)

        return sequences

    # -- attribution touchpoints (Shapley) -----------------------------------

    @staticmethod
    def compute_attribution_touchpoints(events: pd.DataFrame) -> pd.DataFrame:
        """Build an ordered touchpoint table for multi-touch attribution.

        Expected columns: ``conversion_id``, ``identity_id``, ``timestamp``,
        ``channel``, ``campaign_id``, ``conversion_value``.
        """
        events = events.sort_values(["conversion_id", "timestamp"])
        events["touchpoint_index"] = events.groupby("conversion_id").cumcount()

        touchpoints = events[
            [
                "conversion_id",
                "identity_id",
                "touchpoint_index",
                "channel",
                "campaign_id",
                "timestamp",
                "conversion_value",
            ]
        ].copy()

        # Time-decay weight (more recent = higher weight)
        def _time_decay(group: pd.DataFrame) -> pd.Series:
            ts = group["timestamp"]
            span = (ts.max() - ts.min()).total_seconds() + 1.0
            decay = ((ts - ts.min()).dt.total_seconds() / span).values
            return pd.Series(decay, index=group.index)

        touchpoints["time_decay_weight"] = events.groupby("conversion_id").apply(
            _time_decay
        ).reset_index(level=0, drop=True)

        return touchpoints
