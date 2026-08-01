"""ONNX inference wrappers for in-process server-side models (M6, M7, M9).

These wrappers implement the same method signatures as the native model classes
in ``server/`` so that the prediction endpoints are unaffected by the underlying
runtime. They require only ``onnxruntime`` (part of the ``[serving]`` extras),
not the full training stack (XGBoost, torch, tensorflow, etc.).

Loading order in ModelServer._load_churn / _load_ltv:
  1. Check for an ONNX artifact (model.onnx, {name}.onnx, onnx/{name}.onnx).
  2. If found → use the wrapper here (onnxruntime only).
  3. If not  → fall back to the native loader which lazy-imports XGBoost.

This ensures the slim serving image (``pip install .[serving]``) works for
the common case (ONNX artifact present) without ever importing XGBoost.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from common.src.artifact_preprocessing import load_artifact_preprocessing


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_onnx(model_dir: Path, model_name: str) -> Path | None:
    """Return path to first ONNX artifact found in *model_dir*, else None."""
    for candidate in (
        model_dir / "model.onnx",
        model_dir / f"{model_name}.onnx",
        model_dir / "onnx" / f"{model_name}.onnx",
    ):
        if candidate.is_file():
            return candidate
    return None


def _ort_session(onnx_path: Path):
    import onnxruntime as ort  # in [serving] extras
    return ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])


# ---------------------------------------------------------------------------
# M6 — Churn Prediction (XGBClassifier → ONNX)
# ---------------------------------------------------------------------------

# Ordered by typical feature importance for churn models; used when ONNX
# inference cannot return per-sample SHAP values at prediction time.
_CHURN_TOP_FACTORS = [
    "days_since_last_visit",
    "visit_frequency_30d",
    "email_open_rate",
    "session_count_30d",
    "lifetime_value",
]


class OnnxChurnModel:
    """ONNX-backed churn probability scorer (M6).

    Provides the same interface as ``server.models.ChurnPrediction`` so the
    ``/v1/predict/churn`` endpoint works unchanged.
    """

    version = "onnx"

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

    def __init__(self, onnx_path: Path, preprocessing: Any = None) -> None:
        self._session = _ort_session(onnx_path)
        self._input_name: str = self._session.get_inputs()[0].name
        self._output_names: list[str] = [o.name for o in self._session.get_outputs()]
        self._preprocessing = preprocessing

    @classmethod
    def load(cls, model_dir: Path, model_name: str = "churn_prediction") -> "OnnxChurnModel | None":
        """Return an instance if an ONNX artifact exists, else None.

        Also loads the trained preprocessing bundle (preprocessing.joblib) when
        present, verifying the feature schema hash (fail closed on mismatch).
        """
        onnx_path = _find_onnx(model_dir, model_name)
        if not onnx_path:
            return None
        preprocessing = load_artifact_preprocessing(model_dir, model_id=model_name)
        return cls(onnx_path, preprocessing=preprocessing)

    def _prepare(self, X: pd.DataFrame) -> pd.DataFrame:
        """Apply the trained preprocessing when present, else legacy fillna(0)."""
        if self._preprocessing is not None:
            return self._preprocessing.transform(X)
        return X[self.FEATURE_COLS].fillna(0)

    def _run(self, X: pd.DataFrame) -> np.ndarray:
        arr = self._prepare(X).values.astype(np.float32)
        raw = self._session.run(self._output_names, {self._input_name: arr})
        # XGBClassifier ONNX: output[1] is a list of dicts {class: prob}
        proba_out = raw[1] if len(raw) > 1 else raw[0]
        if isinstance(proba_out[0], dict):
            return np.array([d.get(1, d.get("1", 0.0)) for d in proba_out], dtype=float)
        return np.asarray(proba_out)[:, 1] if np.asarray(proba_out).ndim == 2 else np.asarray(proba_out)

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self._run(X)

    def predict_with_factors(self, X: pd.DataFrame) -> pd.DataFrame:
        probas = self._run(X)
        # Static top-3 factors from pre-computed feature importance ordering.
        factors = _CHURN_TOP_FACTORS[:3]
        return pd.DataFrame({
            "churn_probability": probas,
            "top_factor_1": [factors[0]] * len(probas),
            "top_factor_2": [factors[1]] * len(probas),
            "top_factor_3": [factors[2]] * len(probas),
        })


# ---------------------------------------------------------------------------
# M7 — LTV Prediction (XGBRegressor → ONNX)
# ---------------------------------------------------------------------------


class OnnxLTVModel:
    """ONNX-backed lifetime value estimator (M7).

    Provides the same interface as ``server.models.LTVPrediction`` so the
    ``/v1/predict/ltv`` endpoint works unchanged.
    """

    version = "onnx"

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

    def __init__(self, onnx_path: Path, preprocessing: Any = None) -> None:
        self._session = _ort_session(onnx_path)
        self._input_name: str = self._session.get_inputs()[0].name
        self._output_names: list[str] = [o.name for o in self._session.get_outputs()]
        self._preprocessing = preprocessing

    @classmethod
    def load(cls, model_dir: Path, model_name: str = "ltv_prediction") -> "OnnxLTVModel | None":
        """Return an instance if an ONNX artifact exists, else None.

        Also loads the trained preprocessing bundle (preprocessing.joblib) when
        present, verifying the feature schema hash (fail closed on mismatch).
        """
        onnx_path = _find_onnx(model_dir, model_name)
        if not onnx_path:
            return None
        preprocessing = load_artifact_preprocessing(model_dir, model_id=model_name)
        return cls(onnx_path, preprocessing=preprocessing)

    def _prepare(self, X: pd.DataFrame) -> pd.DataFrame:
        """Apply the trained preprocessing when present, else legacy fillna(0)."""
        if self._preprocessing is not None:
            return self._preprocessing.transform(X)
        return X[self.FEATURE_COLS].fillna(0)

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        arr = self._prepare(X).values.astype(np.float32)
        raw = self._session.run(self._output_names, {self._input_name: arr})
        return np.asarray(raw[0]).ravel()
