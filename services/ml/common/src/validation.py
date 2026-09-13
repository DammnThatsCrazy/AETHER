"""
Data validation and schema enforcement.

Provides ``FeatureSchema`` definitions and a ``DataValidator`` that checks
column presence, types, nullability, value ranges, statistical anomalies,
and duplicate rows before data enters the training or serving pipeline.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd
from pydantic import BaseModel

logger = logging.getLogger("aether.ml.validation")


# ---------------------------------------------------------------------------
# Schema definition
# ---------------------------------------------------------------------------

class FeatureSchema(BaseModel):
    """Declarative schema for a single feature column."""

    name: str
    dtype: str = "float64"
    nullable: bool = False
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    allowed_values: Optional[list[str]] = None


# ---------------------------------------------------------------------------
# Validation result container
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    """Collects errors and warnings produced by ``DataValidator``."""

    is_valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.is_valid = False

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)

    def summary(self) -> str:
        """Return a human-readable summary of the validation outcome."""
        status = "PASS" if self.is_valid else "FAIL"
        parts = [f"Validation {status}: {len(self.errors)} error(s), {len(self.warnings)} warning(s)"]
        for err in self.errors:
            parts.append(f"  [ERROR] {err}")
        for warn in self.warnings:
            parts.append(f"  [WARN]  {warn}")
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# DataValidator
# ---------------------------------------------------------------------------

class DataValidator:
    """Validates a DataFrame against a list of ``FeatureSchema`` rules.

    Usage::

        schema = [
            FeatureSchema(name="duration_s", dtype="float64", min_value=0),
            FeatureSchema(name="channel", dtype="object", allowed_values=["organic", "paid"]),
        ]
        validator = DataValidator(schema=schema)
        result = validator.validate(df)
        if not result.is_valid:
            raise ValueError(result.summary())
    """

    def __init__(self, schema: list[FeatureSchema]) -> None:
        self.schema = {fs.name: fs for fs in schema}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate(self, df: pd.DataFrame) -> ValidationResult:
        """Run all validation checks and return a ``ValidationResult``."""
        result = ValidationResult()

        self.check_schema(df, result)
        self.check_statistics(df, result)
        self.check_duplicates(df, result)

        result.stats = {
            "row_count": len(df),
            "column_count": len(df.columns),
            "memory_mb": round(df.memory_usage(deep=True).sum() / 1e6, 2),
            "null_pct_by_column": {
                col: round(df[col].isna().mean() * 100, 2) for col in df.columns
            },
        }

        if result.is_valid:
            logger.info("Validation passed for DataFrame with %d rows", len(df))
        else:
            logger.warning(
                "Validation failed with %d error(s): %s",
                len(result.errors),
                "; ".join(result.errors[:5]),
            )

        return result

    def check_schema(self, df: pd.DataFrame, result: Optional[ValidationResult] = None) -> ValidationResult:
        """Check column presence, dtype compatibility, and nullability."""
        if result is None:
            result = ValidationResult()

        for name, fs in self.schema.items():
            # Column existence
            if name not in df.columns:
                result.add_error(f"Missing required column: '{name}'")
                continue

            series = df[name]

            # Nullability
            null_count = int(series.isna().sum())
            if not fs.nullable and null_count > 0:
                result.add_error(
                    f"Column '{name}' has {null_count} null value(s) but is not nullable"
                )

            # Dtype compatibility
            expected = fs.dtype.lower()
            actual = str(series.dtype).lower()

            if expected in ("float64", "float32", "int64", "int32", "numeric"):
                if not pd.api.types.is_numeric_dtype(series):
                    result.add_error(
                        f"Column '{name}' expected numeric dtype, got '{actual}'"
                    )
            elif expected in ("object", "string", "str", "category"):
                if not (
                    pd.api.types.is_object_dtype(series)
                    or pd.api.types.is_categorical_dtype(series)
                    or pd.api.types.is_string_dtype(series)
                ):
                    result.add_warning(
                        f"Column '{name}' expected string/categorical dtype, got '{actual}'"
                    )
            elif expected in ("bool", "boolean"):
                if not pd.api.types.is_bool_dtype(series):
                    result.add_warning(
                        f"Column '{name}' expected boolean dtype, got '{actual}'"
                    )

        return result

    def check_statistics(self, df: pd.DataFrame, result: Optional[ValidationResult] = None) -> ValidationResult:
        """Check value ranges and allowed-value constraints."""
        if result is None:
            result = ValidationResult()

        for name, fs in self.schema.items():
            if name not in df.columns:
                continue

            series = df[name].dropna()
            if series.empty:
                continue

            # Min / max range checks (numeric columns)
            if pd.api.types.is_numeric_dtype(series):
                col_min = float(series.min())
                col_max = float(series.max())

                if fs.min_value is not None and col_min < fs.min_value:
                    result.add_error(
                        f"Column '{name}' min value {col_min:.4g} is below "
                        f"allowed minimum {fs.min_value}"
                    )
                if fs.max_value is not None and col_max > fs.max_value:
                    result.add_error(
                        f"Column '{name}' max value {col_max:.4g} exceeds "
                        f"allowed maximum {fs.max_value}"
                    )

                # Warn on infinite values
                inf_count = int(np.isinf(series.values.astype(float)).sum())
                if inf_count > 0:
                    result.add_warning(
                        f"Column '{name}' contains {inf_count} infinite value(s)"
                    )

                # Distribution anomaly: flag extreme skewness
                if len(series) >= 30:
                    skew = float(series.skew())
                    if abs(skew) > 10.0:
                        result.add_warning(
                            f"Column '{name}' has extreme skewness ({skew:.2f}); "
                            f"consider a log transform"
                        )

            # Allowed values check (categorical columns)
            if fs.allowed_values is not None:
                invalid = set(series.astype(str).unique()) - set(fs.allowed_values)
                if invalid:
                    result.add_warning(
                        f"Column '{name}' contains {len(invalid)} unexpected value(s): "
                        f"{sorted(invalid)[:5]}"
                    )

        return result

    def check_duplicates(self, df: pd.DataFrame, result: Optional[ValidationResult] = None) -> ValidationResult:
        """Detect fully duplicated rows."""
        if result is None:
            result = ValidationResult()

        n_dups = int(df.duplicated().sum())
        if n_dups > 0:
            dup_pct = n_dups / len(df) * 100
            if dup_pct > 10.0:
                result.add_error(
                    f"DataFrame has {n_dups} duplicate row(s) ({dup_pct:.1f}%)"
                )
            else:
                result.add_warning(
                    f"DataFrame has {n_dups} duplicate row(s) ({dup_pct:.1f}%)"
                )

        return result

    # ------------------------------------------------------------------
    # Anomaly detection on individual columns
    # ------------------------------------------------------------------

    @staticmethod
    def detect_anomalies(
        df: pd.DataFrame,
        column: str,
        method: str = "zscore",
        threshold: float = 3.0,
    ) -> pd.Series:
        """Return a boolean Series flagging anomalous rows in *column*.

        Parameters
        ----------
        method : ``"zscore"`` | ``"iqr"``
            Detection strategy.
        threshold : float
            For z-score: number of standard deviations.
            For IQR: multiplier on the inter-quartile range.
        """
        series = df[column]

        if method == "zscore":
            mean = series.mean()
            std = series.std()
            if std == 0 or pd.isna(std):
                return pd.Series(False, index=df.index)
            z = (series - mean).abs() / std
            return z > threshold

        elif method == "iqr":
            q1 = series.quantile(0.25)
            q3 = series.quantile(0.75)
            iqr = q3 - q1
            lower = q1 - threshold * iqr
            upper = q3 + threshold * iqr
            return (series < lower) | (series > upper)

        else:
            raise ValueError(f"Unknown anomaly detection method: '{method}'. Use 'zscore' or 'iqr'.")
