"""
Aether ML — Unit Tests: Common Modules
Tests for metrics engine, preprocessing pipeline, validation, and feature engineering.
"""

import numpy as np
import pandas as pd
import pytest
from pathlib import Path
import tempfile

from common.src.metrics import (
    MetricsEngine, ClassificationReport, RegressionReport,
    StatisticalTests, BusinessMetrics,
)
from common.src.preprocessing import (
    Preprocessor, PreprocessingConfig, PreprocessingState,
    DataProfiler, ClassBalancer,
)
from common.src.base import (
    ModelType, ModelStage, DeploymentTarget, ModelMetadata,
    FeatureEngineer, AetherModel,
)


# =============================================================================
# METRICS ENGINE TESTS
# =============================================================================

class TestClassificationMetrics:
    """Test classification metrics computation."""

    def test_binary_classification_report(self):
        rng = np.random.default_rng(42)
        y_true = rng.choice([0, 1], 200, p=[0.7, 0.3])
        y_pred_proba = rng.uniform(0, 1, 200)
        # Bias toward correct predictions
        y_pred_proba[y_true == 1] += 0.3
        y_pred_proba = np.clip(y_pred_proba, 0, 1)

        report = MetricsEngine.classification_report(y_true, y_pred_proba)

        assert isinstance(report, ClassificationReport)
        assert 0 <= report.accuracy <= 1
        assert 0 <= report.auc_roc <= 1
        assert 0 <= report.optimal_threshold <= 1
        assert report.confusion_matrix.shape == (2, 2)

    def test_optimal_threshold_selection(self):
        y_true = np.array([0, 0, 0, 1, 1, 1, 0, 1])
        y_pred_proba = np.array([0.1, 0.2, 0.3, 0.7, 0.8, 0.9, 0.4, 0.6])

        report = MetricsEngine.classification_report(y_true, y_pred_proba)
        assert 0.3 < report.optimal_threshold < 0.8

    def test_calibration_error(self):
        y_true = np.array([0, 0, 1, 1, 0, 1, 0, 1] * 25)
        y_pred_proba = np.array([0.1, 0.2, 0.8, 0.9, 0.3, 0.7, 0.2, 0.8] * 25)

        ece = MetricsEngine._expected_calibration_error(y_true, y_pred_proba)
        assert 0 <= ece <= 1

    def test_classification_report_to_dict(self):
        rng = np.random.default_rng(42)
        y_true = rng.choice([0, 1], 100)
        y_pred_proba = rng.uniform(0, 1, 100)

        report = MetricsEngine.classification_report(y_true, y_pred_proba)
        d = report.to_dict()

        assert "accuracy" in d
        assert "auc_roc" in d
        assert "optimal_threshold" in d


class TestRegressionMetrics:
    """Test regression metrics computation."""

    def test_regression_report(self):
        rng = np.random.default_rng(42)
        y_true = rng.uniform(10, 100, 200)
        y_pred = y_true + rng.normal(0, 5, 200)

        report = MetricsEngine.regression_report(y_true, y_pred)

        assert isinstance(report, RegressionReport)
        assert report.mae > 0
        assert report.rmse > 0
        assert report.r2 > 0.5  # Should be well correlated
        assert "p50_error" in report.percentile_errors
        assert "p95_error" in report.percentile_errors

    def test_regression_with_zeros(self):
        y_true = np.array([0, 0, 10, 20, 0, 30])
        y_pred = np.array([1, -1, 12, 18, 2, 28])

        report = MetricsEngine.regression_report(y_true, y_pred)
        assert report.mae > 0


class TestStatisticalTests:
    """Test statistical significance tests."""

    def test_compare_proportions(self):
        result = StatisticalTests.compare_proportions(
            successes_a=50, total_a=1000,
            successes_b=80, total_b=1000,
        )
        assert result.test_name == "two_proportion_z_test"
        assert result.p_value < 0.05  # Significant difference
        assert result.effect_size != 0

    def test_compare_means(self):
        rng = np.random.default_rng(42)
        a = rng.normal(10, 2, 100)
        b = rng.normal(12, 2, 100)

        result = StatisticalTests.compare_means(a, b)
        assert result.significant
        assert result.effect_size > 0

    def test_minimum_sample_size(self):
        n = StatisticalTests.compute_minimum_sample_size(
            baseline_rate=0.05,
            mde=0.01,
            alpha=0.05,
            power=0.80,
        )
        assert n > 100  # Should need substantial sample
        assert isinstance(n, int)


class TestBusinessMetrics:
    """Test business-specific metrics."""

    def test_lift_over_random(self):
        rng = np.random.default_rng(42)
        y_true = rng.choice([0, 1], 1000, p=[0.9, 0.1])
        y_pred = rng.uniform(0, 1, 1000)
        y_pred[y_true == 1] += 0.5
        y_pred = np.clip(y_pred, 0, 1)

        lift = BusinessMetrics.lift_over_random(y_true, y_pred, top_fraction=0.1)
        assert lift > 1  # Model should beat random

    def test_cumulative_gains(self):
        rng = np.random.default_rng(42)
        y_true = rng.choice([0, 1], 500, p=[0.8, 0.2])
        y_pred = rng.uniform(0, 1, 500)

        gains = BusinessMetrics.cumulative_gains(y_true, y_pred)
        assert isinstance(gains, pd.DataFrame)
        assert len(gains) == 10
        assert "captured_pct" in gains.columns


# =============================================================================
# PREPROCESSING TESTS
# =============================================================================

class TestPreprocessor:
    """Test preprocessing pipeline."""

    def test_fit_transform_basic(self):
        rng = np.random.default_rng(42)
        df = pd.DataFrame({
            "age": rng.integers(18, 80, 100).astype(float),
            "income": rng.exponential(50000, 100),
            "category": rng.choice(["A", "B", "C"], 100),
        })
        # Add some nulls
        df.loc[5, "age"] = np.nan
        df.loc[10, "income"] = np.nan

        prep = Preprocessor(PreprocessingConfig(scale_method="standard"))
        result = prep.fit_transform(df)

        assert result.isna().sum().sum() == 0  # No nulls after preprocessing
        assert prep.is_fitted

    def test_scaling_standard(self):
        df = pd.DataFrame({"x": [10, 20, 30, 40, 50]})
        prep = Preprocessor(PreprocessingConfig(scale_method="standard"))
        result = prep.fit_transform(df)

        assert abs(result["x"].mean()) < 0.01
        assert abs(result["x"].std() - 1.0) < 0.3

    def test_scaling_minmax(self):
        df = pd.DataFrame({"x": [10, 20, 30, 40, 50]})
        prep = Preprocessor(PreprocessingConfig(scale_method="minmax"))
        result = prep.fit_transform(df)

        assert result["x"].min() >= -0.01
        assert result["x"].max() <= 1.01

    def test_outlier_clipping(self):
        df = pd.DataFrame({"x": [1, 2, 3, 4, 5, 6, 7, 8, 9, 100]})
        prep = Preprocessor(PreprocessingConfig(outlier_method="iqr", outlier_threshold=1.5))
        result = prep.fit_transform(df)

        # 100 should be clipped
        assert result["x"].max() < 100

    def test_state_serialization(self):
        df = pd.DataFrame({
            "num": [1, 2, 3, 4, 5],
            "cat": ["a", "b", "a", "c", "b"],
        })
        prep = Preprocessor()
        prep.fit(df)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "state.json"
            prep.save(path)

            prep2 = Preprocessor()
            prep2.load(path)

            assert prep2.is_fitted
            assert prep2.state.numeric_columns == prep.state.numeric_columns

    def test_high_null_column_dropped(self):
        df = pd.DataFrame({
            "good": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
            "bad": [None, None, None, None, None, None, None, None, 1, 2],
        })
        config = PreprocessingConfig(drop_high_null_threshold=0.7)
        prep = Preprocessor(config)
        result = prep.fit_transform(df)

        assert "bad" not in result.columns


class TestDataProfiler:
    """Test data profiling."""

    def test_profile_mixed_data(self):
        df = pd.DataFrame({
            "num": [1.0, 2.0, 3.0, np.nan, 5.0],
            "cat": ["a", "b", "a", "c", None],
            "flag": [True, False, True, True, False],
        })

        profiles = DataProfiler.profile(df)
        assert len(profiles) == 3

        num_profile = [p for p in profiles if p.name == "num"][0]
        assert num_profile.is_numeric
        assert num_profile.null_count == 1

    def test_generate_report(self):
        rng = np.random.default_rng(42)
        df = pd.DataFrame({
            "a": rng.normal(0, 1, 100),
            "b": rng.choice(["x", "y"], 100),
        })
        report = DataProfiler.generate_report(df)

        assert "shape" in report
        assert report["shape"] == [100, 2]


class TestClassBalancer:
    """Test class balancing utilities."""

    def test_undersample(self):
        X = pd.DataFrame({"f": range(100)})
        y = pd.Series([0] * 90 + [1] * 10)

        X_bal, y_bal = ClassBalancer.undersample(X, y)
        assert abs(y_bal.value_counts()[0] - y_bal.value_counts()[1]) < 2

    def test_class_weights(self):
        y = pd.Series([0] * 900 + [1] * 100)
        weights = ClassBalancer.compute_class_weights(y)

        assert weights[1] > weights[0]  # Minority gets higher weight

    def test_oversample(self):
        X = pd.DataFrame({"f": range(100)})
        y = pd.Series([0] * 90 + [1] * 10)

        X_bal, y_bal = ClassBalancer.oversample_minority(X, y)
        assert y_bal.value_counts()[0] == y_bal.value_counts()[1]


# =============================================================================
# FEATURE ENGINEERING TESTS
# =============================================================================

class TestFeatureEngineer:
    """Test feature engineering functions."""

    def test_compute_session_features(self):
        from tests.conftest import SyntheticDataFactory

        events = SyntheticDataFactory.session_events(n_sessions=10, seed=42)
        features = FeatureEngineer.compute_session_features(events)

        assert len(features) == 10  # One row per session
        assert "event_count" in features.columns
        assert "pages_per_minute" in features.columns
        assert "is_bounce" in features.columns


# =============================================================================
# BASE MODEL TESTS
# =============================================================================

class TestModelMetadata:
    """Test model metadata."""

    def test_model_types_exist(self):
        assert len(ModelType) == 9

    def test_metadata_creation(self):
        meta = ModelMetadata(
            model_id="test-001",
            model_type=ModelType.BOT_DETECTION,
            version="1.0.0",
            deployment_target=DeploymentTarget.EDGE_ONNX,
            metrics={"auc": 0.98, "recall": 0.99},
            feature_columns=["f1", "f2", "f3"],
        )
        assert meta.stage == ModelStage.DEVELOPMENT
        assert meta.metrics["auc"] == 0.98
