"""
Unit tests for feature engineering pipeline.

Tests cover:
  - FeaturePipeline: session, behavioral, identity, journey,
    attribution, anomaly, web3 feature computation
  - PreprocessingPipeline: fit_transform, save/load persistence
  - DataValidator: schema checks, statistics checks, anomaly detection
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest


# =============================================================================
# RAW EVENTS FIXTURE (local to this file for independence)
# =============================================================================


@pytest.fixture
def raw_events() -> pd.DataFrame:
    """Generate synthetic raw event data for feature pipeline tests."""
    rng = np.random.default_rng(42)
    n_sessions = 50
    records: list[dict[str, Any]] = []
    base_time = datetime(2025, 1, 1)

    event_types = ["page", "click", "scroll", "keypress", "form_submit", "conversion"]
    event_probs = [0.25, 0.25, 0.2, 0.15, 0.1, 0.05]

    for s_idx in range(n_sessions):
        session_id = f"sess_{s_idx:04d}"
        user_id = f"user_{s_idx % 20:04d}"
        device = rng.choice(["desktop", "mobile", "tablet"])
        n_events = int(rng.integers(5, 30))
        session_start = base_time + timedelta(hours=s_idx)

        for e_idx in range(n_events):
            etype = str(rng.choice(event_types, p=event_probs))
            ts = session_start + timedelta(seconds=int(e_idx * rng.integers(1, 30)))
            records.append(
                {
                    "session_id": session_id,
                    "identity_id": user_id,
                    "type": etype,
                    "timestamp": ts,
                    "page_url": f"/page-{rng.integers(1, 20)}",
                    "scroll_depth": float(rng.uniform(0, 100)) if etype == "scroll" else None,
                    "mouse_x": float(rng.integers(0, 1920)),
                    "mouse_y": float(rng.integers(0, 1080)),
                    "device_type": device,
                    "ip_address": f"192.168.{rng.integers(0,256)}.{rng.integers(0,256)}",
                }
            )

    return pd.DataFrame(records)


# =============================================================================
# FEATURE PIPELINE TESTS
# =============================================================================


class TestFeaturePipeline:
    """Test the batch FeaturePipeline from features.pipeline."""

    def test_session_features(self, raw_events: pd.DataFrame) -> None:
        from features.pipeline import FeaturePipeline, FeaturePipelineConfig

        config = FeaturePipelineConfig(
            input_path="/dev/null",
            output_path="/tmp/aether-test-features",
            feature_groups=["session_features"],
            write_offline=False,
        )
        pipeline = FeaturePipeline(config)
        result = pipeline.compute_session_features(raw_events)

        assert not result.empty
        assert "session_id" in result.columns
        assert "event_count" in result.columns or "click_count" in result.columns
        # One row per session
        assert result["session_id"].nunique() == len(result)

    def test_behavioral_features(self, raw_events: pd.DataFrame) -> None:
        from features.pipeline import FeaturePipeline, FeaturePipelineConfig

        config = FeaturePipelineConfig(
            input_path="/dev/null",
            output_path="/tmp/aether-test-features",
            feature_groups=["behavioral_features"],
            write_offline=False,
        )
        pipeline = FeaturePipeline(config)
        result = pipeline.compute_behavioral_features(raw_events)

        assert not result.empty
        assert "session_id" in result.columns
        # Should have biometric features
        expected_cols = {"mouse_speed_mean", "click_interval_mean", "action_type_entropy"}
        assert expected_cols.issubset(set(result.columns))

    def test_identity_features(self, raw_events: pd.DataFrame) -> None:
        from features.pipeline import FeaturePipeline, FeaturePipelineConfig

        config = FeaturePipelineConfig(
            input_path="/dev/null",
            output_path="/tmp/aether-test-features",
            feature_groups=["identity_features"],
            write_offline=False,
        )
        pipeline = FeaturePipeline(config)
        result = pipeline.compute_identity_features(raw_events)

        assert not result.empty
        assert "identity_id" in result.columns
        assert "total_sessions" in result.columns
        assert "total_events" in result.columns
        # One row per identity
        assert result["identity_id"].nunique() == len(result)
        # All numeric derived columns should be non-negative
        if "tenure_days" in result.columns:
            assert (result["tenure_days"] >= 0).all()

    def test_journey_features(self, raw_events: pd.DataFrame) -> None:
        from features.pipeline import FeaturePipeline, FeaturePipelineConfig

        config = FeaturePipelineConfig(
            input_path="/dev/null",
            output_path="/tmp/aether-test-features",
            feature_groups=["journey_features"],
            write_offline=False,
        )
        pipeline = FeaturePipeline(config)
        result = pipeline.compute_journey_features(raw_events)

        assert not result.empty
        assert "identity_id" in result.columns
        assert "event_type" in result.columns
        assert "timestamp" in result.columns

    def test_anomaly_features(self, raw_events: pd.DataFrame) -> None:
        from features.pipeline import FeaturePipeline, FeaturePipelineConfig

        config = FeaturePipelineConfig(
            input_path="/dev/null",
            output_path="/tmp/aether-test-features",
            feature_groups=["anomaly_features"],
            write_offline=False,
        )
        pipeline = FeaturePipeline(config)
        result = pipeline.compute_anomaly_features(raw_events)

        assert not result.empty
        assert "requests_per_minute" in result.columns

    def test_empty_events_returns_empty(self) -> None:
        from features.pipeline import FeaturePipeline, FeaturePipelineConfig

        config = FeaturePipelineConfig(
            input_path="/dev/null",
            output_path="/tmp/aether-test-features",
            write_offline=False,
        )
        pipeline = FeaturePipeline(config)
        result = pipeline.compute_session_features(pd.DataFrame())

        assert result.empty

    def test_missing_column_handled(self) -> None:
        from features.pipeline import FeaturePipeline, FeaturePipelineConfig

        config = FeaturePipelineConfig(
            input_path="/dev/null",
            output_path="/tmp/aether-test-features",
            write_offline=False,
        )
        pipeline = FeaturePipeline(config)
        df = pd.DataFrame({"random_col": [1, 2, 3]})
        result = pipeline.compute_session_features(df)

        # Should return empty since session_id is missing
        assert result.empty


# =============================================================================
# PREPROCESSING PIPELINE TESTS
# =============================================================================


class TestPreprocessingPipeline:
    """Test the PreprocessingPipeline from common.src.preprocessing."""

    def test_fit_transform(self) -> None:
        from common.src.preprocessing import PreprocessingPipeline

        df = pd.DataFrame(
            {
                "duration_s": [10.0, 20.0, np.nan, 40.0, 50.0],
                "click_count": [1.0, 2.0, 3.0, 4.0, 5.0],
                "channel": ["organic", "paid", "organic", "email", "paid"],
            }
        )

        pipe = PreprocessingPipeline(
            numeric_features=["duration_s", "click_count"],
            categorical_features=["channel"],
        )
        X_out = pipe.fit_transform(df)

        assert X_out.shape[0] == 5
        # Numeric (2) + categorical one-hot (3 categories, minus 0 for non-binary)
        assert X_out.shape[1] >= 2
        # No NaN values after transformation
        assert not np.isnan(X_out).any()

    def test_transform_without_fit_raises(self) -> None:
        from common.src.preprocessing import PreprocessingPipeline

        pipe = PreprocessingPipeline(
            numeric_features=["a"],
            categorical_features=[],
        )
        with pytest.raises(RuntimeError, match="not been fitted"):
            pipe.transform(pd.DataFrame({"a": [1, 2, 3]}))

    def test_save_load(self, tmp_path: Path) -> None:
        from common.src.preprocessing import PreprocessingPipeline

        df = pd.DataFrame(
            {
                "duration_s": [10.0, 20.0, 30.0, 40.0, 50.0],
                "click_count": [1.0, 2.0, 3.0, 4.0, 5.0],
            }
        )

        pipe = PreprocessingPipeline(
            numeric_features=["duration_s", "click_count"],
            categorical_features=[],
        )
        pipe.fit(df)

        save_path = tmp_path / "preprocessor.joblib"
        pipe.save(save_path)
        assert save_path.exists()

        loaded = PreprocessingPipeline.load(save_path)
        original_result = pipe.transform(df)
        loaded_result = loaded.transform(df)

        np.testing.assert_array_almost_equal(original_result, loaded_result)

    def test_feature_names_out(self) -> None:
        from common.src.preprocessing import PreprocessingPipeline

        df = pd.DataFrame(
            {
                "duration_s": [10.0, 20.0, 30.0],
                "channel": ["organic", "paid", "email"],
            }
        )

        pipe = PreprocessingPipeline(
            numeric_features=["duration_s"],
            categorical_features=["channel"],
        )
        pipe.fit(df)
        names = pipe.feature_names_out

        assert isinstance(names, list)
        assert len(names) > 0
        assert "duration_s" in names

    def test_target_column_excluded(self) -> None:
        from common.src.preprocessing import PreprocessingPipeline

        df = pd.DataFrame(
            {
                "duration_s": [10.0, 20.0, 30.0],
                "target": [0, 1, 0],
            }
        )

        pipe = PreprocessingPipeline(
            numeric_features=["duration_s"],
            categorical_features=[],
            target_column="target",
        )
        X_out = pipe.fit_transform(df)

        # Target column should not be included
        assert X_out.shape[1] == 1


# =============================================================================
# DATA VALIDATOR TESTS
# =============================================================================


class TestDataValidator:
    """Test the DataValidator from common.src.validation."""

    def test_valid_data(self) -> None:
        from common.src.validation import DataValidator, FeatureSchema

        schema = [
            FeatureSchema(name="duration_s", dtype="float64", min_value=0),
            FeatureSchema(name="clicks", dtype="float64", min_value=0, max_value=1000),
        ]
        validator = DataValidator(schema=schema)

        df = pd.DataFrame(
            {
                "duration_s": [10.0, 20.0, 30.0],
                "clicks": [5.0, 10.0, 15.0],
            }
        )
        result = validator.validate(df)

        assert result.is_valid
        assert len(result.errors) == 0

    def test_invalid_schema_missing_column(self) -> None:
        from common.src.validation import DataValidator, FeatureSchema

        schema = [
            FeatureSchema(name="required_column", dtype="float64"),
        ]
        validator = DataValidator(schema=schema)

        df = pd.DataFrame({"wrong_column": [1, 2, 3]})
        result = validator.validate(df)

        assert not result.is_valid
        assert any("required_column" in e for e in result.errors)

    def test_value_range_violation(self) -> None:
        from common.src.validation import DataValidator, FeatureSchema

        schema = [
            FeatureSchema(name="score", dtype="float64", min_value=0, max_value=1),
        ]
        validator = DataValidator(schema=schema)

        df = pd.DataFrame({"score": [0.5, 1.5, -0.1]})
        result = validator.validate(df)

        assert not result.is_valid

    def test_nullability_check(self) -> None:
        from common.src.validation import DataValidator, FeatureSchema

        schema = [
            FeatureSchema(name="required_val", dtype="float64", nullable=False),
        ]
        validator = DataValidator(schema=schema)

        df = pd.DataFrame({"required_val": [1.0, np.nan, 3.0]})
        result = validator.validate(df)

        assert not result.is_valid
        assert any("null" in e.lower() for e in result.errors)

    def test_anomaly_detection_zscore(self) -> None:
        from common.src.validation import DataValidator

        rng = np.random.default_rng(42)
        values = rng.normal(100, 10, 200)
        # Inject outliers
        values = np.concatenate([values, [500.0, -200.0]])
        df = pd.DataFrame({"metric": values})

        anomalies = DataValidator.detect_anomalies(df, "metric", method="zscore", threshold=3.0)

        assert isinstance(anomalies, pd.Series)
        assert anomalies.dtype == bool
        # Should flag at least the extreme outliers
        assert anomalies.sum() >= 2

    def test_anomaly_detection_iqr(self) -> None:
        from common.src.validation import DataValidator

        rng = np.random.default_rng(42)
        values = rng.normal(100, 10, 200)
        values = np.concatenate([values, [500.0, -200.0]])
        df = pd.DataFrame({"metric": values})

        anomalies = DataValidator.detect_anomalies(df, "metric", method="iqr", threshold=1.5)

        assert isinstance(anomalies, pd.Series)
        assert anomalies.sum() >= 2

    def test_anomaly_detection_invalid_method(self) -> None:
        from common.src.validation import DataValidator

        df = pd.DataFrame({"metric": [1, 2, 3]})

        with pytest.raises(ValueError, match="Unknown anomaly detection method"):
            DataValidator.detect_anomalies(df, "metric", method="invalid")

    def test_duplicate_detection(self) -> None:
        from common.src.validation import DataValidator, FeatureSchema

        schema = [FeatureSchema(name="a", dtype="float64")]
        validator = DataValidator(schema=schema)

        # Create data with many duplicates
        df = pd.DataFrame({"a": [1.0] * 100})
        result = validator.validate(df)

        # Should detect duplicates as a warning or error
        has_dup_message = any("duplicate" in m.lower() for m in result.errors + result.warnings)
        assert has_dup_message

    def test_validation_result_summary(self) -> None:
        from common.src.validation import ValidationResult

        result = ValidationResult()
        result.add_error("Missing column X")
        result.add_warning("Skew detected in Y")

        summary = result.summary()
        assert "FAIL" in summary
        assert "Missing column X" in summary
        assert "Skew" in summary


# =============================================================================
# FEATURE ENGINEER (from common.src.base) TESTS
# =============================================================================


class TestFeatureEngineer:
    """Test FeatureEngineer static methods from common.src.base."""

    def test_compute_session_features(self) -> None:
        from common.src.base import FeatureEngineer

        rng = np.random.default_rng(42)
        n = 100
        events = pd.DataFrame(
            {
                "session_id": [f"s{i // 10}" for i in range(n)],
                "timestamp": pd.date_range("2025-01-01", periods=n, freq="10s"),
                "event_type": rng.choice(
                    ["page_view", "click", "scroll", "conversion", "form_submit"],
                    n,
                ),
                "page_url": [f"/page-{rng.integers(1, 5)}" for _ in range(n)],
                "scroll_depth": rng.uniform(0, 1, n),
            }
        )

        result = FeatureEngineer.compute_session_features(events)

        assert not result.empty
        assert "session_id" in result.columns
        assert "event_count" in result.columns
        assert "click_count" in result.columns
        assert "pages_per_minute" in result.columns
        assert "is_bounce" in result.columns
        # 10 unique sessions
        assert len(result) == 10

    def test_compute_behavioral_features(self) -> None:
        from common.src.base import FeatureEngineer

        rng = np.random.default_rng(42)
        n = 100
        events = pd.DataFrame(
            {
                "session_id": [f"s{i // 20}" for i in range(n)],
                "timestamp": pd.date_range("2025-01-01", periods=n, freq="5s"),
                "event_type": rng.choice(
                    ["click", "scroll", "keypress", "mousemove"],
                    n,
                ),
                "mouse_x": rng.integers(0, 1920, n).astype(float),
                "mouse_y": rng.integers(0, 1080, n).astype(float),
            }
        )

        result = FeatureEngineer.compute_behavioral_features(events)

        assert not result.empty
        assert "session_id" in result.columns
        assert "avg_time_between_actions" in result.columns
        assert "mouse_velocity_mean" in result.columns
        assert "action_type_entropy" in result.columns

    def test_compute_identity_features(self) -> None:
        from common.src.base import FeatureEngineer

        rng = np.random.default_rng(42)
        n = 50
        events = pd.DataFrame(
            {
                "identity_id": [f"u{i // 10}" for i in range(n)],
                "session_id": [f"s{i // 5}" for i in range(n)],
                "event_count": rng.integers(1, 50, n),
                "duration_s": rng.exponential(120, n),
                "has_conversion": rng.choice([0, 1], n, p=[0.85, 0.15]),
                "page_views": rng.integers(1, 20, n),
                "max_scroll_depth": rng.uniform(0, 1, n),
                "started_at": pd.date_range("2025-01-01", periods=n, freq="6h"),
            }
        )

        result = FeatureEngineer.compute_identity_features(events)

        assert not result.empty
        assert "identity_id" in result.columns
        assert "total_sessions" in result.columns
        assert "visit_frequency" in result.columns
        assert "conversion_rate" in result.columns

    def test_compute_journey_sequences(self) -> None:
        from common.src.base import FeatureEngineer

        events = pd.DataFrame(
            {
                "identity_id": ["u1", "u1", "u1", "u2", "u2"],
                "timestamp": pd.date_range("2025-01-01", periods=5, freq="1min"),
                "event_type": ["page_view", "click", "conversion", "page_view", "click"],
                "page_category": ["home", "product", "checkout", "home", "pricing"],
            }
        )

        sequences = FeatureEngineer.compute_journey_sequences(events)

        assert isinstance(sequences, list)
        assert len(sequences) == 2  # 2 identities
        assert all(isinstance(seq, list) for seq in sequences)
        # Each token should be "event_type:page_category"
        assert "page_view:home" in sequences[0]

    def test_compute_attribution_touchpoints(self) -> None:
        from common.src.base import FeatureEngineer

        events = pd.DataFrame(
            {
                "conversion_id": ["c1", "c1", "c1", "c2", "c2"],
                "identity_id": ["u1", "u1", "u1", "u2", "u2"],
                "timestamp": pd.date_range("2025-01-01", periods=5, freq="1D"),
                "channel": ["organic", "email", "paid", "social", "direct"],
                "campaign_id": ["camp1", "camp2", "camp3", "camp4", "camp5"],
                "conversion_value": [0, 0, 100, 0, 50],
            }
        )

        result = FeatureEngineer.compute_attribution_touchpoints(events)

        assert not result.empty
        assert "conversion_id" in result.columns
        assert "touchpoint_index" in result.columns
        assert "time_decay_weight" in result.columns
        # Decay weights should be in [0, 1]
        assert (result["time_decay_weight"] >= 0).all()
        assert (result["time_decay_weight"] <= 1.0 + 1e-6).all()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
