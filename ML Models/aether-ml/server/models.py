"""
Server-side ML models for SageMaker/ECS deployment.

Models:
  - IdentityResolution: Merges fragmented user identities (neural net + GAT phases)
  - ChurnPrediction: Predicts 30-day inactivity via XGBClassifier
  - LTVPrediction: Lifetime value estimation via XGBRegressor + BG/NBD ensemble
  - AnomalyDetection: Hybrid IsolationForest + Autoencoder anomaly scoring
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional, Union

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    roc_auc_score,
)

from common.src.base import AetherModel, DeploymentTarget, ModelMetadata, ModelType

logger = logging.getLogger("aether.ml.server")


# =============================================================================
# MODEL 1: IDENTITY RESOLUTION (Neural Network + Graph Attention)
# =============================================================================


class IdentityResolution(AetherModel):
    """
    Merges fragmented user identities using a two-phase approach:

    Phase 1 -- Feed-forward neural network (PyTorch MLP) trained on pairwise
               identity features to produce match probabilities.
    Phase 2 -- Graph Attention Network operating on the identity graph to refine
               cluster assignments (future extension point).

    The MLP architecture is:  input -> 64 -> 32 -> 1 (sigmoid).
    """

    FEATURE_COLS: list[str] = [
        "feature_similarity_score",
        "email_hash_match",
        "device_fingerprint_similarity",
        "ip_proximity",
        "session_overlap_ratio",
        "behavioral_similarity",
        "cookie_match",
    ]

    model_type_name: str = "identity_resolution"

    def __init__(self, version: str = "1.0.0") -> None:
        super().__init__(ModelType.IDENTITY_RESOLUTION, version)
        self._model: Any = None
        self._optimizer: Any = None

    # --------------------------------------------------------------------- #
    # Training
    # --------------------------------------------------------------------- #

    def train(
        self,
        X: pd.DataFrame,
        y: Optional[pd.Series] = None,
        *,
        epochs: int = 30,
        lr: float = 1e-3,
        batch_size: int = 256,
        **kwargs: Any,
    ) -> dict[str, float]:
        """
        Train a small PyTorch MLP for pairwise identity matching.

        Parameters
        ----------
        X : pd.DataFrame
            DataFrame containing pairwise identity features (see ``FEATURE_COLS``).
        y : pd.Series
            Binary labels -- 1 means the pair belongs to the same identity.
        epochs : int
            Number of training epochs (default 30).
        lr : float
            Learning rate for Adam optimizer.
        batch_size : int
            Mini-batch size.

        Returns
        -------
        dict[str, float]
            Training metrics including AUC and accuracy.
        """
        import torch
        import torch.nn as nn
        from torch.utils.data import DataLoader, TensorDataset

        if y is None:
            raise ValueError("Identity resolution requires pairwise labels (y).")

        X_features = X[self.FEATURE_COLS].fillna(0).values.astype(np.float32)
        y_values = y.values.astype(np.float32)

        X_tensor = torch.FloatTensor(X_features)
        y_tensor = torch.FloatTensor(y_values)

        # ---- MLP definition ------------------------------------------------
        input_dim = len(self.FEATURE_COLS)

        class _IdentityMLP(nn.Module):
            def __init__(self, in_dim: int) -> None:
                super().__init__()
                self.net = nn.Sequential(
                    nn.Linear(in_dim, 64),
                    nn.ReLU(),
                    nn.Dropout(0.3),
                    nn.Linear(64, 32),
                    nn.ReLU(),
                    nn.Dropout(0.2),
                    nn.Linear(32, 1),
                    nn.Sigmoid(),
                )

            def forward(self, x: torch.Tensor) -> torch.Tensor:
                return self.net(x).squeeze(-1)

        self._model = _IdentityMLP(input_dim)
        optimizer = torch.optim.Adam(self._model.parameters(), lr=lr)
        criterion = nn.BCELoss()

        dataset = TensorDataset(X_tensor, y_tensor)
        loader = DataLoader(dataset, batch_size=batch_size, shuffle=True)

        # ---- Training loop --------------------------------------------------
        self._model.train()
        for epoch in range(epochs):
            epoch_loss = 0.0
            for batch_X, batch_y in loader:
                optimizer.zero_grad()
                preds = self._model(batch_X)
                loss = criterion(preds, batch_y)
                loss.backward()
                optimizer.step()
                epoch_loss += loss.item()

        # ---- Evaluation -----------------------------------------------------
        self._model.eval()
        with torch.no_grad():
            predictions = self._model(X_tensor).numpy()

        metrics: dict[str, float] = {
            "auc": float(roc_auc_score(y_values, predictions)),
            "accuracy": float(accuracy_score(y_values, (predictions > 0.5).astype(int))),
            "f1": float(f1_score(y_values, (predictions > 0.5).astype(int))),
        }

        self.is_trained = True
        self.metadata = ModelMetadata(
            model_id=f"identity-resolution-v{self.version}",
            model_type=self.model_type,
            version=self.version,
            deployment_target=DeploymentTarget.SERVER_SAGEMAKER,
            metrics=metrics,
            feature_columns=self.FEATURE_COLS,
            training_data_hash=self._hash_data(X),
            hyperparameters={"epochs": epochs, "lr": lr, "batch_size": batch_size},
        )
        return metrics

    # --------------------------------------------------------------------- #
    # Prediction
    # --------------------------------------------------------------------- #

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Return match probability for each identity pair in *X*."""
        import torch

        if not self.is_trained or self._model is None:
            raise RuntimeError("Model has not been trained yet.")

        X_tensor = torch.FloatTensor(
            X[self.FEATURE_COLS].fillna(0).values.astype(np.float32)
        )
        self._model.eval()
        with torch.no_grad():
            return self._model(X_tensor).numpy()

    def resolve_identities(
        self,
        pairs_df: pd.DataFrame,
        threshold: float = 0.7,
    ) -> dict[int, list[str]]:
        """
        Cluster identities based on pairwise match probabilities.

        Parameters
        ----------
        pairs_df : pd.DataFrame
            Must contain columns ``id_a``, ``id_b``, plus all ``FEATURE_COLS``.
        threshold : float
            Minimum match probability to consider a pair as belonging to the
            same cluster.

        Returns
        -------
        dict[int, list[str]]
            Mapping from ``cluster_id`` to a list of ``identity_id`` strings.
        """
        import networkx as nx

        probabilities = self.predict(pairs_df)

        # Build a graph where edges connect pairs whose probability exceeds
        # the threshold, then extract connected components as clusters.
        G = nx.Graph()
        for idx, prob in enumerate(probabilities):
            if prob >= threshold:
                id_a = str(pairs_df.iloc[idx]["id_a"])
                id_b = str(pairs_df.iloc[idx]["id_b"])
                G.add_edge(id_a, id_b, weight=float(prob))

        # Add isolated nodes that appear in the data but never cross threshold.
        all_ids = set(pairs_df["id_a"].astype(str)) | set(pairs_df["id_b"].astype(str))
        for node in all_ids:
            if node not in G:
                G.add_node(node)

        clusters: dict[int, list[str]] = {}
        for cluster_id, component in enumerate(nx.connected_components(G)):
            clusters[cluster_id] = sorted(component)

        return clusters

    # --------------------------------------------------------------------- #
    # Persistence
    # --------------------------------------------------------------------- #

    def save(self, path: Path) -> None:
        import torch

        path.mkdir(parents=True, exist_ok=True)
        torch.save(self._model.state_dict(), path / "identity_mlp.pt")
        if self.metadata:
            (path / "metadata.json").write_text(self.metadata.model_dump_json(indent=2))

    def load(self, path: Path) -> None:
        import torch

        self.metadata = ModelMetadata.model_validate_json(
            (path / "metadata.json").read_text()
        )
        # NOTE: Caller must rebuild the architecture and load state_dict
        # externally because the inner class is not accessible here.
        self.is_trained = True

    def _compute_metrics(
        self, y_true: np.ndarray, y_pred: np.ndarray
    ) -> dict[str, float]:
        return {
            "auc": float(roc_auc_score(y_true, y_pred)),
            "accuracy": float(accuracy_score(y_true, (y_pred > 0.5).astype(int))),
        }


# =============================================================================
# MODEL 2: CHURN PREDICTION (XGBoost)
# =============================================================================


class ChurnPrediction(AetherModel):
    """
    Predicts 30-day user inactivity using an XGBClassifier.

    The model is retrained bi-weekly on confirmed churn events and exposes
    feature importance via ``get_feature_importance()`` and SHAP-based
    explanations via ``get_shap_values()``.
    """

    FEATURE_COLS: list[str] = [
        "days_since_last_visit",
        "visit_frequency_30d",
        "session_count_30d",
        "avg_session_duration",
        "page_views_trend",
        "conversion_count_30d",
        "support_tickets",
        "email_open_rate",
        "days_since_signup",
        "lifetime_value",
    ]

    model_type_name: str = "churn_prediction"

    def __init__(self, version: str = "1.0.0") -> None:
        super().__init__(ModelType.CHURN_PREDICTION, version)
        self._model: Any = None

    # --------------------------------------------------------------------- #
    # Training
    # --------------------------------------------------------------------- #

    def train(
        self,
        X: pd.DataFrame,
        y: Optional[pd.Series] = None,
        **kwargs: Any,
    ) -> dict[str, float]:
        """
        Fit an XGBClassifier on churn labels.

        Parameters
        ----------
        X : pd.DataFrame
            Feature matrix with columns listed in ``FEATURE_COLS``.
        y : pd.Series
            Binary labels (1 = churned within 30 days, 0 = retained).

        Returns
        -------
        dict[str, float]
            Training metrics including AUC, accuracy, and F1.
        """
        import xgboost as xgb

        if y is None:
            raise ValueError("Churn prediction requires labels (y).")

        X_features = X[self.FEATURE_COLS].fillna(0)

        # Compute class-balance weight
        n_neg = int((y == 0).sum())
        n_pos = int((y == 1).sum())
        scale_pos_weight = n_neg / max(n_pos, 1)

        self._model = xgb.XGBClassifier(
            n_estimators=200,
            max_depth=6,
            learning_rate=0.1,
            subsample=0.8,
            colsample_bytree=0.8,
            scale_pos_weight=scale_pos_weight,
            eval_metric="auc",
            random_state=42,
            use_label_encoder=False,
        )
        self._model.fit(X_features, y, eval_set=[(X_features, y)], verbose=False)

        predictions = self._model.predict_proba(X_features)[:, 1]
        metrics: dict[str, float] = {
            "auc": float(roc_auc_score(y, predictions)),
            "accuracy": float(accuracy_score(y, (predictions > 0.5).astype(int))),
            "f1": float(f1_score(y, (predictions > 0.5).astype(int))),
        }

        self.is_trained = True
        self.metadata = ModelMetadata(
            model_id=f"churn-v{self.version}",
            model_type=self.model_type,
            version=self.version,
            deployment_target=DeploymentTarget.SERVER_SAGEMAKER,
            metrics=metrics,
            feature_columns=self.FEATURE_COLS,
            training_data_hash=self._hash_data(X),
            hyperparameters={
                "n_estimators": 200,
                "max_depth": 6,
                "learning_rate": 0.1,
                "scale_pos_weight": scale_pos_weight,
            },
        )
        return metrics

    # --------------------------------------------------------------------- #
    # Prediction
    # --------------------------------------------------------------------- #

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Return churn probability in the range ``[0.0, 1.0]``."""
        if not self.is_trained or self._model is None:
            raise RuntimeError("Model has not been trained yet.")
        return self._model.predict_proba(X[self.FEATURE_COLS].fillna(0))[:, 1]

    # --------------------------------------------------------------------- #
    # Explainability
    # --------------------------------------------------------------------- #

    def get_feature_importance(self) -> dict[str, float]:
        """Return a mapping of feature name to its importance score."""
        if not self.is_trained or self._model is None:
            raise RuntimeError("Model has not been trained yet.")
        importances = self._model.feature_importances_
        return {
            col: float(imp)
            for col, imp in zip(self.FEATURE_COLS, importances)
        }

    def get_shap_values(self, X: pd.DataFrame) -> np.ndarray:
        """
        Compute SHAP values for each sample in *X* using TreeExplainer.

        Parameters
        ----------
        X : pd.DataFrame
            Feature matrix with columns listed in ``FEATURE_COLS``.

        Returns
        -------
        np.ndarray
            Array of shape ``(n_samples, n_features)`` with SHAP values.
        """
        import shap  # type: ignore[import-untyped]

        if not self.is_trained or self._model is None:
            raise RuntimeError("Model has not been trained yet.")

        explainer = shap.TreeExplainer(self._model)
        shap_values = explainer.shap_values(X[self.FEATURE_COLS].fillna(0))
        return np.asarray(shap_values)

    # --------------------------------------------------------------------- #
    # Persistence
    # --------------------------------------------------------------------- #

    def save(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        self._model.save_model(str(path / "churn_xgb.json"))
        if self.metadata:
            (path / "metadata.json").write_text(self.metadata.model_dump_json(indent=2))

    def load(self, path: Path) -> None:
        import xgboost as xgb

        self._model = xgb.XGBClassifier()
        self._model.load_model(str(path / "churn_xgb.json"))
        if (path / "metadata.json").exists():
            self.metadata = ModelMetadata.model_validate_json(
                (path / "metadata.json").read_text()
            )
        self.is_trained = True

    def _compute_metrics(
        self, y_true: np.ndarray, y_pred: np.ndarray
    ) -> dict[str, float]:
        return {
            "auc": float(roc_auc_score(y_true, y_pred)),
            "accuracy": float(accuracy_score(y_true, (y_pred > 0.5).astype(int))),
            "f1": float(f1_score(y_true, (y_pred > 0.5).astype(int))),
        }


# =============================================================================
# MODEL 3: LIFETIME VALUE PREDICTION (XGBRegressor + BG/NBD)
# =============================================================================


class LTVPrediction(AetherModel):
    """
    Lifetime value estimation using an ensemble of:

    * **XGBRegressor** -- captures non-linear feature interactions.
    * **BG/NBD probabilistic model** (from the *lifetimes* library) -- models
      repeat-purchase behaviour and expected transactions.

    When both sub-models are fitted the final prediction is a weighted blend.
    """

    FEATURE_COLS: list[str] = [
        "monetary_value",
        "frequency",
        "recency",
        "T",
        "avg_order_value",
        "purchase_count_90d",
        "days_since_first_purchase",
        "product_categories_count",
        "discount_usage_rate",
        "referral_count",
    ]

    model_type_name: str = "ltv_prediction"

    def __init__(self, version: str = "1.0.0") -> None:
        super().__init__(ModelType.LTV_PREDICTION, version)
        self._model: Any = None  # XGBRegressor
        self._bgf: Any = None  # BetaGeoFitter (BG/NBD)
        self._ggf: Any = None  # GammaGammaFitter

    # --------------------------------------------------------------------- #
    # Training
    # --------------------------------------------------------------------- #

    def train(
        self,
        X: pd.DataFrame,
        y: Optional[pd.Series] = None,
        *,
        fit_bgf: bool = True,
        **kwargs: Any,
    ) -> dict[str, float]:
        """
        Fit XGBRegressor and (optionally) BG/NBD + Gamma-Gamma from *lifetimes*.

        Parameters
        ----------
        X : pd.DataFrame
            Feature matrix.  Must include ``frequency``, ``recency``, ``T``,
            and ``monetary_value`` columns for the probabilistic model.
        y : pd.Series
            Target LTV values in dollars.
        fit_bgf : bool
            Whether to fit the BG/NBD model (requires ``frequency``,
            ``recency``, ``T``, ``monetary_value`` columns).

        Returns
        -------
        dict[str, float]
            Training metrics (MAE, RMSE, MAPE).
        """
        import xgboost as xgb

        if y is None:
            raise ValueError("LTV prediction requires target values (y).")

        X_features = X[self.FEATURE_COLS].fillna(0)

        # ---- XGBRegressor ---------------------------------------------------
        self._model = xgb.XGBRegressor(
            n_estimators=300,
            max_depth=6,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
        )
        self._model.fit(X_features, y, verbose=False)

        xgb_predictions = self._model.predict(X_features)

        # ---- BG/NBD (optional) ----------------------------------------------
        if fit_bgf:
            try:
                from lifetimes import BetaGeoFitter, GammaGammaFitter  # type: ignore[import-untyped]

                rfm = X[["frequency", "recency", "T"]].fillna(0)
                rfm = rfm[rfm["frequency"] > 0]

                if len(rfm) > 10:
                    self._bgf = BetaGeoFitter(penalizer_coef=0.01)
                    self._bgf.fit(rfm["frequency"], rfm["recency"], rfm["T"])

                    monetary = X.loc[rfm.index, "monetary_value"].fillna(0)
                    monetary = monetary[monetary > 0]
                    if len(monetary) > 10:
                        self._ggf = GammaGammaFitter(penalizer_coef=0.01)
                        self._ggf.fit(
                            rfm.loc[monetary.index, "frequency"],
                            monetary,
                        )
                    logger.info("BG/NBD + Gamma-Gamma models fitted successfully.")
                else:
                    logger.warning(
                        "Insufficient repeat-purchase data for BG/NBD -- skipping."
                    )
            except ImportError:
                logger.warning(
                    "lifetimes library not available -- BG/NBD model skipped."
                )

        # ---- Metrics --------------------------------------------------------
        metrics: dict[str, float] = {
            "mae": float(mean_absolute_error(y, xgb_predictions)),
            "rmse": float(np.sqrt(mean_squared_error(y, xgb_predictions))),
            "mape": float(
                np.mean(np.abs((y - xgb_predictions) / (y + 1))) * 100
            ),
        }

        self.is_trained = True
        self.metadata = ModelMetadata(
            model_id=f"ltv-v{self.version}",
            model_type=self.model_type,
            version=self.version,
            deployment_target=DeploymentTarget.SERVER_SAGEMAKER,
            metrics=metrics,
            feature_columns=self.FEATURE_COLS,
            training_data_hash=self._hash_data(X),
            hyperparameters={
                "n_estimators": 300,
                "max_depth": 6,
                "learning_rate": 0.05,
                "bgf_fitted": self._bgf is not None,
            },
        )
        return metrics

    # --------------------------------------------------------------------- #
    # Prediction
    # --------------------------------------------------------------------- #

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Return predicted LTV in dollars for each row in *X*."""
        if not self.is_trained or self._model is None:
            raise RuntimeError("Model has not been trained yet.")
        return self._model.predict(X[self.FEATURE_COLS].fillna(0))

    def predict_clv(
        self,
        frequency: float,
        recency: float,
        T: float,
        monetary_value: float,
        periods: int = 12,
    ) -> float:
        """
        Predict customer lifetime value using the BG/NBD + Gamma-Gamma model.

        Parameters
        ----------
        frequency : float
            Number of repeat purchases.
        recency : float
            Time between first and last purchase.
        T : float
            Customer tenure (age).
        monetary_value : float
            Average monetary value of purchases.
        periods : int
            Number of future periods to predict (default 12 months).

        Returns
        -------
        float
            Predicted CLV in dollars.
        """
        if self._bgf is None or self._ggf is None:
            raise RuntimeError(
                "BG/NBD model is not fitted. Train with fit_bgf=True first."
            )

        expected_transactions = self._bgf.conditional_expected_number_of_purchases_up_to_time(
            periods, frequency, recency, T
        )
        expected_avg_profit = self._ggf.conditional_expected_average_profit(
            frequency, monetary_value
        )
        return float(expected_transactions * expected_avg_profit)

    # --------------------------------------------------------------------- #
    # Persistence
    # --------------------------------------------------------------------- #

    def save(self, path: Path) -> None:
        import joblib

        path.mkdir(parents=True, exist_ok=True)
        self._model.save_model(str(path / "ltv_xgb.json"))
        if self._bgf is not None:
            joblib.dump(self._bgf, path / "bgf.pkl")
        if self._ggf is not None:
            joblib.dump(self._ggf, path / "ggf.pkl")
        if self.metadata:
            (path / "metadata.json").write_text(self.metadata.model_dump_json(indent=2))

    def load(self, path: Path) -> None:
        import joblib
        import xgboost as xgb

        self._model = xgb.XGBRegressor()
        self._model.load_model(str(path / "ltv_xgb.json"))
        if (path / "bgf.pkl").exists():
            self._bgf = joblib.load(path / "bgf.pkl")
        if (path / "ggf.pkl").exists():
            self._ggf = joblib.load(path / "ggf.pkl")
        if (path / "metadata.json").exists():
            self.metadata = ModelMetadata.model_validate_json(
                (path / "metadata.json").read_text()
            )
        self.is_trained = True

    def _compute_metrics(
        self, y_true: np.ndarray, y_pred: np.ndarray
    ) -> dict[str, float]:
        return {
            "mae": float(mean_absolute_error(y_true, y_pred)),
            "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        }


# =============================================================================
# MODEL 4: ANOMALY DETECTION (Isolation Forest + Autoencoder)
# =============================================================================


class AnomalyDetection(AetherModel):
    """
    Hybrid anomaly detection combining:

    * **IsolationForest** -- tree-based outlier scoring on structured metrics.
    * **Autoencoder** (PyTorch) -- reconstruction-error scoring on the same
      feature space, capturing non-linear anomaly patterns.

    The final anomaly score is a normalised blend of both sub-model scores,
    mapped to the ``[0.0, 1.0]`` range where ``0.0`` = normal and ``1.0`` =
    anomaly.
    """

    FEATURE_COLS: list[str] = [
        "requests_per_minute",
        "error_rate",
        "avg_response_time",
        "unique_ips",
        "unique_user_agents",
        "payload_size_mean",
        "geographic_entropy",
        "new_endpoints_accessed",
        "failed_auth_rate",
        "time_since_last_spike",
    ]

    model_type_name: str = "anomaly_detection"

    def __init__(self, version: str = "1.0.0") -> None:
        super().__init__(ModelType.ANOMALY_DETECTION, version)
        self._iforest: Any = None
        self._autoencoder: Any = None
        self._ae_mean: Optional[np.ndarray] = None
        self._ae_std: Optional[np.ndarray] = None

    # --------------------------------------------------------------------- #
    # Training
    # --------------------------------------------------------------------- #

    def train(
        self,
        X: pd.DataFrame,
        y: Optional[pd.Series] = None,
        *,
        ae_epochs: int = 50,
        ae_lr: float = 1e-3,
        ae_batch_size: int = 256,
        **kwargs: Any,
    ) -> dict[str, float]:
        """
        Fit both IsolationForest and a small autoencoder.

        Parameters
        ----------
        X : pd.DataFrame
            Feature matrix with columns listed in ``FEATURE_COLS``.
        y : pd.Series, optional
            Not required (unsupervised).  If supplied, it is ignored.
        ae_epochs : int
            Training epochs for the autoencoder.
        ae_lr : float
            Learning rate for the autoencoder.
        ae_batch_size : int
            Batch size for the autoencoder.

        Returns
        -------
        dict[str, float]
            Anomaly count, rate, and score statistics.
        """
        import torch
        import torch.nn as nn
        from sklearn.ensemble import IsolationForest
        from torch.utils.data import DataLoader, TensorDataset

        X_features = X[self.FEATURE_COLS].fillna(0).values.astype(np.float32)

        # ---- Isolation Forest -----------------------------------------------
        self._iforest = IsolationForest(
            n_estimators=200,
            contamination=0.01,
            max_samples="auto",
            random_state=42,
            n_jobs=-1,
        )
        self._iforest.fit(X_features)

        # ---- Autoencoder (input -> 32 -> 16 -> 32 -> input) ----------------
        input_dim = len(self.FEATURE_COLS)

        # Normalise input for better autoencoder training
        self._ae_mean = X_features.mean(axis=0)
        self._ae_std = X_features.std(axis=0) + 1e-8
        X_norm = (X_features - self._ae_mean) / self._ae_std

        class _Autoencoder(nn.Module):
            def __init__(self, dim: int) -> None:
                super().__init__()
                self.encoder = nn.Sequential(
                    nn.Linear(dim, 32),
                    nn.ReLU(),
                    nn.Linear(32, 16),
                    nn.ReLU(),
                )
                self.decoder = nn.Sequential(
                    nn.Linear(16, 32),
                    nn.ReLU(),
                    nn.Linear(32, dim),
                )

            def forward(self, x: torch.Tensor) -> torch.Tensor:
                z = self.encoder(x)
                return self.decoder(z)

        self._autoencoder = _Autoencoder(input_dim)
        optimizer = torch.optim.Adam(self._autoencoder.parameters(), lr=ae_lr)
        criterion = nn.MSELoss()

        X_tensor = torch.FloatTensor(X_norm)
        dataset = TensorDataset(X_tensor)
        loader = DataLoader(dataset, batch_size=ae_batch_size, shuffle=True)

        self._autoencoder.train()
        for epoch in range(ae_epochs):
            for (batch,) in loader:
                optimizer.zero_grad()
                recon = self._autoencoder(batch)
                loss = criterion(recon, batch)
                loss.backward()
                optimizer.step()

        self._autoencoder.eval()

        # ---- Combined metrics -----------------------------------------------
        if_scores = self._iforest.decision_function(X_features)
        if_predictions = self._iforest.predict(X_features)
        n_anomalies = int((if_predictions == -1).sum())

        metrics: dict[str, float] = {
            "anomaly_count": float(n_anomalies),
            "anomaly_rate": float(n_anomalies / len(X)),
            "mean_if_score": float(if_scores.mean()),
            "if_score_std": float(if_scores.std()),
        }

        self.is_trained = True
        self.metadata = ModelMetadata(
            model_id=f"anomaly-v{self.version}",
            model_type=self.model_type,
            version=self.version,
            deployment_target=DeploymentTarget.SERVER_ECS,
            metrics=metrics,
            feature_columns=self.FEATURE_COLS,
            training_data_hash=self._hash_data(X),
            hyperparameters={
                "if_n_estimators": 200,
                "if_contamination": 0.01,
                "ae_epochs": ae_epochs,
                "ae_lr": ae_lr,
            },
        )
        return metrics

    # --------------------------------------------------------------------- #
    # Prediction
    # --------------------------------------------------------------------- #

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """
        Return a combined anomaly score in ``[0.0, 1.0]``.

        ``0.0`` indicates a perfectly normal observation; ``1.0`` indicates a
        strong anomaly.  The score blends the IsolationForest decision function
        with the autoencoder reconstruction error (50/50 by default).
        """
        import torch

        if self._iforest is None or self._autoencoder is None:
            raise RuntimeError("Model has not been trained yet.")

        X_features = X[self.FEATURE_COLS].fillna(0).values.astype(np.float32)

        # -- Isolation Forest score (lower = more anomalous) --
        if_raw = self._iforest.decision_function(X_features)
        # Normalise to [0, 1] where 1 = anomaly
        if_min, if_max = if_raw.min(), if_raw.max()
        if if_max - if_min > 0:
            if_score = 1.0 - (if_raw - if_min) / (if_max - if_min)
        else:
            if_score = np.zeros_like(if_raw)

        # -- Autoencoder reconstruction error --
        assert self._ae_mean is not None and self._ae_std is not None
        X_norm = (X_features - self._ae_mean) / self._ae_std
        X_tensor = torch.FloatTensor(X_norm)

        self._autoencoder.eval()
        with torch.no_grad():
            recon = self._autoencoder(X_tensor).numpy()
        recon_error = np.mean((X_norm - recon) ** 2, axis=1)

        # Normalise reconstruction error to [0, 1]
        re_min, re_max = recon_error.min(), recon_error.max()
        if re_max - re_min > 0:
            ae_score = (recon_error - re_min) / (re_max - re_min)
        else:
            ae_score = np.zeros_like(recon_error)

        # -- Blend --
        combined = 0.5 * if_score + 0.5 * ae_score
        return np.clip(combined, 0.0, 1.0)

    # --------------------------------------------------------------------- #
    # Persistence
    # --------------------------------------------------------------------- #

    def save(self, path: Path) -> None:
        import joblib
        import torch

        path.mkdir(parents=True, exist_ok=True)
        joblib.dump(self._iforest, path / "iforest.pkl")
        if self._autoencoder is not None:
            torch.save(self._autoencoder.state_dict(), path / "autoencoder.pt")
        if self._ae_mean is not None:
            np.save(path / "ae_mean.npy", self._ae_mean)
        if self._ae_std is not None:
            np.save(path / "ae_std.npy", self._ae_std)
        if self.metadata:
            (path / "metadata.json").write_text(self.metadata.model_dump_json(indent=2))

    def load(self, path: Path) -> None:
        import joblib

        self._iforest = joblib.load(path / "iforest.pkl")
        if (path / "ae_mean.npy").exists():
            self._ae_mean = np.load(path / "ae_mean.npy")
        if (path / "ae_std.npy").exists():
            self._ae_std = np.load(path / "ae_std.npy")
        if (path / "metadata.json").exists():
            self.metadata = ModelMetadata.model_validate_json(
                (path / "metadata.json").read_text()
            )
        # NOTE: Autoencoder state_dict requires architecture rebuild externally.
        self.is_trained = True

    def _compute_metrics(
        self, y_true: np.ndarray, y_pred: np.ndarray
    ) -> dict[str, float]:
        return {
            "mean_score": float(y_pred.mean()),
            "anomaly_rate": float((y_pred > 0.5).mean()),
        }
