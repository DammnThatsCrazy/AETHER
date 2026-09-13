"""
Reproducible, serializable preprocessing pipelines.

Wraps scikit-learn ColumnTransformer with numeric imputation + scaling,
categorical one-hot encoding, and optional SMOTE class balancing.  The
entire fitted pipeline is persisted via joblib so training and serving
share identical transformations.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

logger = logging.getLogger("aether.ml.preprocessing")


class PreprocessingPipeline:
    """Declarative, serializable preprocessing for tabular data.

    Usage::

        pipe = PreprocessingPipeline(
            numeric_features=["duration_s", "click_count"],
            categorical_features=["channel", "device_type"],
            target_column="is_churned",
        )
        X_train = pipe.fit_transform(df_train)
        X_test  = pipe.transform(df_test)
        pipe.save("artifacts/preprocessor.joblib")

    Parameters
    ----------
    numeric_features : list[str]
        Columns to impute (median) then standard-scale.
    categorical_features : list[str]
        Columns to impute (most-frequent) then one-hot encode.
    target_column : str | None
        Name of the label column (excluded from feature matrix).
    """

    def __init__(
        self,
        numeric_features: list[str],
        categorical_features: list[str],
        target_column: Optional[str] = None,
    ) -> None:
        self.numeric_features = list(numeric_features)
        self.categorical_features = list(categorical_features)
        self.target_column = target_column

        self._preprocessor: Optional[ColumnTransformer] = None
        self._is_fitted: bool = False
        self._feature_names_out: list[str] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fit(self, df: pd.DataFrame) -> "PreprocessingPipeline":
        """Fit imputers, scalers, and encoders on *df*.

        Returns ``self`` so calls can be chained.
        """
        X = self._drop_target(df)
        self._preprocessor = self._build_preprocessor()
        self._preprocessor.fit(X)
        self._is_fitted = True

        # Resolve output feature names
        self._feature_names_out = self._resolve_feature_names()

        logger.info(
            "PreprocessingPipeline fitted: %d numeric, %d categorical -> %d output features",
            len(self.numeric_features),
            len(self.categorical_features),
            len(self._feature_names_out),
        )
        return self

    def transform(self, df: pd.DataFrame) -> np.ndarray:
        """Apply the fitted transformations and return a NumPy array."""
        self._check_fitted()
        X = self._drop_target(df)
        return self._preprocessor.transform(X)  # type: ignore[union-attr]

    def fit_transform(
        self,
        df: pd.DataFrame,
        balance: bool = False,
        random_state: int = 42,
    ) -> np.ndarray:
        """Fit on *df* and return the transformed array.

        If *balance* is ``True`` and the ``imblearn`` package is available,
        SMOTE is applied to the transformed features together with the
        target column (which must be present in *df*).
        """
        self.fit(df)
        X_out = self.transform(df)

        if balance and self.target_column and self.target_column in df.columns:
            X_out, _ = self._apply_smote(
                X_out,
                df[self.target_column].values,
                random_state=random_state,
            )

        return X_out

    def save(self, path: str | Path) -> None:
        """Persist the fitted pipeline to disk."""
        self._check_fitted()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "preprocessor": self._preprocessor,
                "numeric_features": self.numeric_features,
                "categorical_features": self.categorical_features,
                "target_column": self.target_column,
                "feature_names_out": self._feature_names_out,
            },
            path,
        )
        logger.info("PreprocessingPipeline saved to %s", path)

    @classmethod
    def load(cls, path: str | Path) -> "PreprocessingPipeline":
        """Restore a previously saved pipeline."""
        path = Path(path)
        state = joblib.load(path)

        instance = cls(
            numeric_features=state["numeric_features"],
            categorical_features=state["categorical_features"],
            target_column=state.get("target_column"),
        )
        instance._preprocessor = state["preprocessor"]
        instance._feature_names_out = state.get("feature_names_out", [])
        instance._is_fitted = True

        logger.info("PreprocessingPipeline loaded from %s", path)
        return instance

    @property
    def feature_names_out(self) -> list[str]:
        """Names of the output columns after transformation."""
        self._check_fitted()
        return list(self._feature_names_out)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_preprocessor(self) -> ColumnTransformer:
        """Construct the sklearn ColumnTransformer."""
        transformers: list[tuple] = []

        if self.numeric_features:
            numeric_pipeline = Pipeline(
                steps=[
                    ("imputer", SimpleImputer(strategy="median")),
                    ("scaler", StandardScaler()),
                ]
            )
            transformers.append(("numeric", numeric_pipeline, self.numeric_features))

        if self.categorical_features:
            categorical_pipeline = Pipeline(
                steps=[
                    ("imputer", SimpleImputer(strategy="most_frequent")),
                    (
                        "encoder",
                        OneHotEncoder(
                            handle_unknown="ignore",
                            sparse_output=False,
                            drop="if_binary",
                        ),
                    ),
                ]
            )
            transformers.append(("categorical", categorical_pipeline, self.categorical_features))

        return ColumnTransformer(
            transformers=transformers,
            remainder="drop",
            verbose_feature_names_out=False,
        )

    def _resolve_feature_names(self) -> list[str]:
        """Extract output feature names from the fitted ColumnTransformer."""
        assert self._preprocessor is not None
        try:
            names = list(self._preprocessor.get_feature_names_out())
        except AttributeError:
            # Fallback for older sklearn versions
            names = list(self.numeric_features)
            if self.categorical_features:
                encoder = (
                    self._preprocessor.named_transformers_["categorical"]
                    .named_steps["encoder"]
                )
                cat_names = list(encoder.get_feature_names_out(self.categorical_features))
                names.extend(cat_names)
        return names

    def _drop_target(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return the DataFrame without the target column (if set)."""
        if self.target_column and self.target_column in df.columns:
            return df.drop(columns=[self.target_column])
        return df

    def _check_fitted(self) -> None:
        if not self._is_fitted:
            raise RuntimeError(
                "PreprocessingPipeline has not been fitted. Call fit() first."
            )

    @staticmethod
    def _apply_smote(
        X: np.ndarray,
        y: np.ndarray,
        random_state: int = 42,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Apply SMOTE over-sampling if ``imblearn`` is installed."""
        try:
            from imblearn.over_sampling import SMOTE

            smote = SMOTE(random_state=random_state)
            X_res, y_res = smote.fit_resample(X, y)
            logger.info(
                "SMOTE applied: %d -> %d samples",
                len(y),
                len(y_res),
            )
            return X_res, y_res
        except ImportError:
            logger.warning(
                "imblearn not installed -- skipping SMOTE. "
                "Install with: pip install imbalanced-learn"
            )
            return X, y


# ------------------------------------------------------------------
# Lightweight dataframe-first preprocessing API used by legacy tests
# ------------------------------------------------------------------


@dataclass
class PreprocessingConfig:
    scale_method: str = 'standard'
    outlier_method: str | None = None
    outlier_threshold: float = 1.5
    drop_high_null_threshold: float = 0.95


@dataclass
class PreprocessingState:
    numeric_columns: list[str] = field(default_factory=list)
    categorical_columns: list[str] = field(default_factory=list)
    medians: dict[str, float] = field(default_factory=dict)
    modes: dict[str, object] = field(default_factory=dict)
    means: dict[str, float] = field(default_factory=dict)
    stds: dict[str, float] = field(default_factory=dict)
    mins: dict[str, float] = field(default_factory=dict)
    maxs: dict[str, float] = field(default_factory=dict)
    dropped_columns: list[str] = field(default_factory=list)


class Preprocessor:
    def __init__(self, config: PreprocessingConfig | None = None) -> None:
        self.config = config or PreprocessingConfig()
        self.state = PreprocessingState()
        self.is_fitted = False

    def fit(self, df: pd.DataFrame) -> 'Preprocessor':
        working = df.copy()
        null_fraction = working.isna().mean()
        self.state.dropped_columns = [c for c, frac in null_fraction.items() if frac > self.config.drop_high_null_threshold]
        working = working.drop(columns=self.state.dropped_columns, errors='ignore')
        self.state.numeric_columns = list(working.select_dtypes(include=[np.number]).columns)
        self.state.categorical_columns = [c for c in working.columns if c not in self.state.numeric_columns]
        for col in self.state.numeric_columns:
            series = working[col].astype(float)
            self.state.medians[col] = float(series.median()) if not series.dropna().empty else 0.0
            self.state.means[col] = float(series.mean()) if not series.dropna().empty else 0.0
            std = float(series.std(ddof=1)) if len(series.dropna()) > 1 else 1.0
            self.state.stds[col] = std if std > 0 else 1.0
            self.state.mins[col] = float(series.min()) if not series.dropna().empty else 0.0
            self.state.maxs[col] = float(series.max()) if not series.dropna().empty else 1.0
        for col in self.state.categorical_columns:
            mode = working[col].mode(dropna=True)
            self.state.modes[col] = mode.iloc[0] if not mode.empty else 'unknown'
        self.is_fitted = True
        return self

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        if not self.is_fitted:
            raise RuntimeError('Preprocessor has not been fitted. Call fit() first.')
        working = df.copy().drop(columns=self.state.dropped_columns, errors='ignore')
        for col in self.state.numeric_columns:
            if col not in working:
                continue
            series = working[col].astype(float).fillna(self.state.medians[col])
            if self.config.outlier_method == 'iqr':
                q1 = series.quantile(0.25)
                q3 = series.quantile(0.75)
                iqr = q3 - q1
                lower = q1 - self.config.outlier_threshold * iqr
                upper = q3 + self.config.outlier_threshold * iqr
                series = series.clip(lower=lower, upper=upper)
            if self.config.scale_method == 'standard':
                series = (series - self.state.means[col]) / self.state.stds[col]
            elif self.config.scale_method == 'minmax':
                denom = max(self.state.maxs[col] - self.state.mins[col], 1e-9)
                series = (series - self.state.mins[col]) / denom
            working[col] = series
        for col in self.state.categorical_columns:
            if col in working:
                working[col] = working[col].fillna(self.state.modes[col])
        return working

    def fit_transform(self, df: pd.DataFrame) -> pd.DataFrame:
        return self.fit(df).transform(df)

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.write_text(json.dumps(asdict(self.state), indent=2, default=str))

    def load(self, path: str | Path) -> None:
        data = json.loads(Path(path).read_text())
        self.state = PreprocessingState(**data)
        self.is_fitted = True


@dataclass
class ColumnProfile:
    name: str
    dtype: str
    null_count: int
    is_numeric: bool


class DataProfiler:
    @staticmethod
    def profile(df: pd.DataFrame) -> list[ColumnProfile]:
        profiles: list[ColumnProfile] = []
        for col in df.columns:
            profiles.append(ColumnProfile(
                name=col,
                dtype=str(df[col].dtype),
                null_count=int(df[col].isna().sum()),
                is_numeric=bool(pd.api.types.is_numeric_dtype(df[col])),
            ))
        return profiles

    @staticmethod
    def generate_report(df: pd.DataFrame) -> dict[str, object]:
        return {
            'shape': list(df.shape),
            'columns': list(df.columns),
            'profiles': [asdict(profile) for profile in DataProfiler.profile(df)],
        }


class ClassBalancer:
    @staticmethod
    def undersample(X: pd.DataFrame, y: pd.Series, random_state: int = 42) -> tuple[pd.DataFrame, pd.Series]:
        rng = np.random.default_rng(random_state)
        counts = y.value_counts()
        target = int(counts.min())
        indices = []
        for label in counts.index:
            label_idx = y[y == label].index.to_numpy()
            indices.extend(rng.choice(label_idx, size=target, replace=False).tolist())
        indices = sorted(indices)
        return X.loc[indices].reset_index(drop=True), y.loc[indices].reset_index(drop=True)

    @staticmethod
    def oversample_minority(X: pd.DataFrame, y: pd.Series, random_state: int = 42) -> tuple[pd.DataFrame, pd.Series]:
        rng = np.random.default_rng(random_state)
        counts = y.value_counts()
        target = int(counts.max())
        parts_x = []
        parts_y = []
        for label in counts.index:
            label_idx = y[y == label].index.to_numpy()
            sampled = rng.choice(label_idx, size=target, replace=len(label_idx) < target)
            parts_x.append(X.loc[sampled])
            parts_y.append(y.loc[sampled])
        return pd.concat(parts_x, ignore_index=True), pd.concat(parts_y, ignore_index=True)

    @staticmethod
    def compute_class_weights(y: pd.Series) -> dict[object, float]:
        counts = y.value_counts()
        total = counts.sum()
        return {label: float(total / (len(counts) * count)) for label, count in counts.items()}
