"""
Aether ML — Edge Models
Lightweight models for browser/mobile deployment.
All models target <100ms latency and <1MB artifact size.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

from common.src.base import AetherModel, DeploymentTarget, ModelMetadata, ModelType

logger = logging.getLogger("aether.ml.edge")


# =============================================================================
# MODEL 1: INTENT PREDICTION
# =============================================================================

class IntentPrediction(AetherModel):
    """
    Predict user's next action from clickstream data.

    Phase 1 algorithm: LogisticRegression (class_weight='balanced', max_iter=1000).
    Phase 2 algorithm: GRU (planned upgrade).

    Export target: TensorFlow.js for browser deployment.
    Constraints: <100ms latency, <1MB model size.
    """

    FEATURE_NAMES: list[str] = [
        "click_count",
        "scroll_depth",
        "time_on_page",
        "pages_viewed",
        "last_action_encoded",  # one-hot encoded
        "session_duration",
        "device_type_encoded",
    ]

    model_type_str: str = "intent_prediction"

    def __init__(self, version: str = "1.0.0") -> None:
        super().__init__(ModelType.INTENT_PREDICTION, version)
        self._model: Optional[LogisticRegression] = None

    def train(
        self,
        X: pd.DataFrame,
        y: Optional[pd.Series] = None,
        **kwargs: Any,
    ) -> dict[str, float]:
        """
        Train the intent prediction model.

        Args:
            X: DataFrame with columns matching FEATURE_NAMES.
            y: Series of target action class labels.
            **kwargs: Additional keyword arguments (unused).

        Returns:
            Dictionary of training metrics.
        """
        if y is None:
            raise ValueError("IntentPrediction requires labels (y).")

        X_features = X[self.FEATURE_NAMES].fillna(0)

        self._model = LogisticRegression(
            class_weight="balanced",
            max_iter=1000,
            multi_class="multinomial",
            solver="lbfgs",
        )
        self._model.fit(X_features, y)
        self.is_trained = True

        y_pred = self._model.predict(X_features)
        metrics = self._compute_metrics(y.values, y_pred)

        # Add AUC if binary or multiclass probabilities are available
        try:
            y_proba = self._model.predict_proba(X_features)
            if y_proba.shape[1] == 2:
                metrics["auc"] = roc_auc_score(y, y_proba[:, 1])
            else:
                metrics["auc"] = roc_auc_score(
                    y, y_proba, multi_class="ovr", average="weighted"
                )
        except (ValueError, TypeError):
            pass

        self.metadata = ModelMetadata(
            model_id=f"intent-prediction-v{self.version}",
            model_type=self.model_type,
            version=self.version,
            deployment_target=DeploymentTarget.EDGE_TFJS,
            metrics=metrics,
            feature_columns=self.FEATURE_NAMES,
            training_data_hash=self._hash_data(X),
            hyperparameters={
                "class_weight": "balanced",
                "max_iter": 1000,
                "solver": "lbfgs",
            },
        )
        logger.info(
            "IntentPrediction trained — accuracy=%.4f", metrics.get("accuracy", 0.0)
        )
        return metrics

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """
        Predict the next user action (class label).

        Args:
            X: DataFrame with columns matching FEATURE_NAMES.

        Returns:
            Array of predicted class labels.
        """
        if self._model is None:
            raise RuntimeError("Model not trained. Call train() first.")
        X_features = X[self.FEATURE_NAMES].fillna(0)
        return self._model.predict(X_features)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """
        Return probability distribution over action classes.

        Args:
            X: DataFrame with columns matching FEATURE_NAMES.

        Returns:
            Array of shape (n_samples, n_classes) with class probabilities.
        """
        if self._model is None:
            raise RuntimeError("Model not trained. Call train() first.")
        X_features = X[self.FEATURE_NAMES].fillna(0)
        return self._model.predict_proba(X_features)

    def get_feature_names(self) -> list[str]:
        """Return the list of feature names used by this model."""
        return list(self.FEATURE_NAMES)

    def save(self, path: Path) -> None:
        """Save model artifacts to disk via joblib."""
        import joblib

        path.mkdir(parents=True, exist_ok=True)
        joblib.dump(self._model, path / "intent_model.pkl")
        if self.metadata:
            (path / "metadata.json").write_text(
                self.metadata.model_dump_json(indent=2)
            )
        logger.info("IntentPrediction saved to %s", path)

    def load(self, path: Path) -> None:
        """Load model artifacts from disk."""
        import joblib

        self._model = joblib.load(path / "intent_model.pkl")
        self.is_trained = True
        if (path / "metadata.json").exists():
            self.metadata = ModelMetadata.model_validate_json(
                (path / "metadata.json").read_text()
            )
        logger.info("IntentPrediction loaded from %s", path)

    def _compute_metrics(
        self, y_true: np.ndarray, y_pred: np.ndarray
    ) -> dict[str, float]:
        return {
            "accuracy": accuracy_score(y_true, y_pred),
            "f1_weighted": f1_score(y_true, y_pred, average="weighted", zero_division=0),
        }


# =============================================================================
# MODEL 2: BOT DETECTION
# =============================================================================

class BotDetection(AetherModel):
    """
    Classify sessions as human (0) or bot (1) using behavioral biometrics.

    Algorithm: RandomForestClassifier with 100 trees, max_depth=10.
    Export target: ONNX for cross-platform edge deployment.
    Constraints: <100ms latency, <1MB model size.
    """

    FEATURE_NAMES: list[str] = [
        "mouse_speed_mean",
        "mouse_speed_std",
        "click_interval_mean",
        "click_interval_std",
        "scroll_pattern_entropy",
        "keystroke_timing_variance",
        "session_duration",
        "page_views",
        "unique_pages",
        "js_execution_time",
        "has_webdriver",
        "user_agent_anomaly_score",
    ]

    model_type_str: str = "bot_detection"

    def __init__(self, version: str = "1.0.0") -> None:
        super().__init__(ModelType.BOT_DETECTION, version)
        self._model: Optional[RandomForestClassifier] = None

    def train(
        self,
        X: pd.DataFrame,
        y: Optional[pd.Series] = None,
        **kwargs: Any,
    ) -> dict[str, float]:
        """
        Train the bot detection model.

        Args:
            X: DataFrame with columns matching FEATURE_NAMES.
            y: Binary series (0 = human, 1 = bot).
            **kwargs: Additional keyword arguments (unused).

        Returns:
            Dictionary of training metrics.
        """
        if y is None:
            raise ValueError("BotDetection requires labels (y).")

        X_features = X[self.FEATURE_NAMES].fillna(0)

        self._model = RandomForestClassifier(
            n_estimators=100,
            max_depth=10,
            class_weight="balanced",
            random_state=42,
            n_jobs=-1,
        )
        self._model.fit(X_features, y)
        self.is_trained = True

        y_pred = self._model.predict(X_features)
        metrics = self._compute_metrics(y.values, y_pred)

        y_proba = self._model.predict_proba(X_features)[:, 1]
        metrics["auc"] = roc_auc_score(y, y_proba)

        self.metadata = ModelMetadata(
            model_id=f"bot-detection-v{self.version}",
            model_type=self.model_type,
            version=self.version,
            deployment_target=DeploymentTarget.EDGE_ONNX,
            metrics=metrics,
            feature_columns=self.FEATURE_NAMES,
            training_data_hash=self._hash_data(X),
            hyperparameters={
                "n_estimators": 100,
                "max_depth": 10,
                "class_weight": "balanced",
            },
        )
        logger.info(
            "BotDetection trained — auc=%.4f, f1=%.4f",
            metrics.get("auc", 0.0),
            metrics.get("f1", 0.0),
        )
        return metrics

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """
        Classify sessions as human (0) or bot (1).

        Args:
            X: DataFrame with columns matching FEATURE_NAMES.

        Returns:
            Array of 0s (human) and 1s (bot).
        """
        if self._model is None:
            raise RuntimeError("Model not trained. Call train() first.")
        X_features = X[self.FEATURE_NAMES].fillna(0)
        return self._model.predict(X_features)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """
        Return [p_human, p_bot] for each session.

        Args:
            X: DataFrame with columns matching FEATURE_NAMES.

        Returns:
            Array of shape (n_samples, 2) with [p_human, p_bot].
        """
        if self._model is None:
            raise RuntimeError("Model not trained. Call train() first.")
        X_features = X[self.FEATURE_NAMES].fillna(0)
        return self._model.predict_proba(X_features)

    def get_feature_importance(self) -> dict[str, float]:
        """
        Return a mapping of feature names to their importance scores.

        Returns:
            Dictionary mapping feature name to importance (sums to 1.0).
        """
        if self._model is None:
            raise RuntimeError("Model not trained. Call train() first.")
        importances = self._model.feature_importances_
        return {
            name: float(importance)
            for name, importance in zip(self.FEATURE_NAMES, importances)
        }

    def save(self, path: Path) -> None:
        """Save model artifacts to disk via joblib."""
        import joblib

        path.mkdir(parents=True, exist_ok=True)
        joblib.dump(self._model, path / "bot_model.pkl")
        if self.metadata:
            (path / "metadata.json").write_text(
                self.metadata.model_dump_json(indent=2)
            )
        logger.info("BotDetection saved to %s", path)

    def load(self, path: Path) -> None:
        """Load model artifacts from disk."""
        import joblib

        self._model = joblib.load(path / "bot_model.pkl")
        self.is_trained = True
        if (path / "metadata.json").exists():
            self.metadata = ModelMetadata.model_validate_json(
                (path / "metadata.json").read_text()
            )
        logger.info("BotDetection loaded from %s", path)

    def export_onnx(self, output_path: Path) -> None:
        """
        Export the model to ONNX format for cross-platform edge deployment.

        Args:
            output_path: Directory to write the .onnx file into.
        """
        from skl2onnx import convert_sklearn
        from skl2onnx.common.data_types import FloatTensorType

        if self._model is None:
            raise RuntimeError("Model not trained. Call train() first.")

        initial_type = [
            ("features", FloatTensorType([None, len(self.FEATURE_NAMES)]))
        ]
        onnx_model = convert_sklearn(self._model, initial_types=initial_type)
        output_path.mkdir(parents=True, exist_ok=True)
        with open(output_path / "bot_model.onnx", "wb") as f:
            f.write(onnx_model.SerializeToString())
        logger.info("BotDetection exported to ONNX: %s", output_path)

    def _compute_metrics(
        self, y_true: np.ndarray, y_pred: np.ndarray
    ) -> dict[str, float]:
        return {
            "accuracy": accuracy_score(y_true, y_pred),
            "precision": precision_score(y_true, y_pred, zero_division=0),
            "recall": recall_score(y_true, y_pred, zero_division=0),
            "f1": f1_score(y_true, y_pred, zero_division=0),
        }


# =============================================================================
# MODEL 3: SESSION SCORER
# =============================================================================

class SessionScorer(AetherModel):
    """
    Score session engagement and conversion likelihood.

    Algorithm: LogisticRegression (C=1.0).
    predict() returns a continuous engagement score in [0.0, 1.0],
    representing the probability of conversion.

    Export target: TensorFlow.js for browser deployment.
    Constraints: <100ms latency, <1MB model size.
    """

    FEATURE_NAMES: list[str] = [
        "page_views",
        "unique_pages",
        "session_duration",
        "scroll_depth_mean",
        "click_count",
        "form_interactions",
        "search_queries",
        "product_views",
        "add_to_cart_count",
        "time_to_first_interaction",
    ]

    model_type_str: str = "session_scorer"

    def __init__(self, version: str = "1.0.0") -> None:
        super().__init__(ModelType.SESSION_SCORER, version)
        self._model: Optional[LogisticRegression] = None

    def train(
        self,
        X: pd.DataFrame,
        y: Optional[pd.Series] = None,
        **kwargs: Any,
    ) -> dict[str, float]:
        """
        Train the session scorer.

        Args:
            X: DataFrame with columns matching FEATURE_NAMES.
            y: Binary series (1 = converted, 0 = did not convert).
            **kwargs: Additional keyword arguments (unused).

        Returns:
            Dictionary of training metrics.
        """
        if y is None:
            raise ValueError("SessionScorer requires labels (y).")

        X_features = X[self.FEATURE_NAMES].fillna(0)

        self._model = LogisticRegression(C=1.0, max_iter=1000, solver="lbfgs")
        self._model.fit(X_features, y)
        self.is_trained = True

        y_proba = self._model.predict_proba(X_features)[:, 1]
        metrics: dict[str, float] = {
            "auc": roc_auc_score(y, y_proba),
            "accuracy": accuracy_score(y, (y_proba >= 0.5).astype(int)),
        }

        self.metadata = ModelMetadata(
            model_id=f"session-scorer-v{self.version}",
            model_type=self.model_type,
            version=self.version,
            deployment_target=DeploymentTarget.EDGE_TFJS,
            metrics=metrics,
            feature_columns=self.FEATURE_NAMES,
            training_data_hash=self._hash_data(X),
            hyperparameters={"C": 1.0, "max_iter": 1000, "solver": "lbfgs"},
        )
        logger.info(
            "SessionScorer trained — auc=%.4f", metrics.get("auc", 0.0)
        )
        return metrics

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """
        Return engagement score in [0.0, 1.0] (probability of conversion).

        Args:
            X: DataFrame with columns matching FEATURE_NAMES.

        Returns:
            Array of float scores between 0.0 and 1.0.
        """
        if self._model is None:
            raise RuntimeError("Model not trained. Call train() first.")
        X_features = X[self.FEATURE_NAMES].fillna(0)
        return self._model.predict_proba(X_features)[:, 1]

    def save(self, path: Path) -> None:
        """Save model artifacts to disk via joblib."""
        import joblib

        path.mkdir(parents=True, exist_ok=True)
        joblib.dump(self._model, path / "session_scorer.pkl")
        if self.metadata:
            (path / "metadata.json").write_text(
                self.metadata.model_dump_json(indent=2)
            )
        logger.info("SessionScorer saved to %s", path)

    def load(self, path: Path) -> None:
        """Load model artifacts from disk."""
        import joblib

        self._model = joblib.load(path / "session_scorer.pkl")
        self.is_trained = True
        if (path / "metadata.json").exists():
            self.metadata = ModelMetadata.model_validate_json(
                (path / "metadata.json").read_text()
            )
        logger.info("SessionScorer loaded from %s", path)

    def _compute_metrics(
        self, y_true: np.ndarray, y_pred: np.ndarray
    ) -> dict[str, float]:
        return {
            "auc": roc_auc_score(y_true, y_pred),
            "accuracy": accuracy_score(y_true, (y_pred >= 0.5).astype(int)),
        }
