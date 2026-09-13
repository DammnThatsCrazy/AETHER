"""
Integration tests for the full prediction pipeline.

These tests exercise end-to-end workflows:
  - Train a model with synthetic data
  - Save to disk
  - Load from disk
  - Predict on new data
  - Validate outputs

Marked with @pytest.mark.integration so they can be selectively run:
  pytest -m integration
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


@pytest.mark.integration
class TestPredictionPipeline:
    """End-to-end prediction pipeline tests using sklearn models."""

    def test_end_to_end_intent(
        self, intent_data: tuple[pd.DataFrame, pd.Series]
    ) -> None:
        """Train -> Save -> Load -> Predict for intent prediction."""
        import joblib
        from sklearn.linear_model import LogisticRegression

        X, y = intent_data

        # Train
        model = LogisticRegression(
            class_weight="balanced",
            max_iter=1000,
            solver="lbfgs",
        )
        model.fit(X, y)

        with tempfile.TemporaryDirectory() as tmpdir:
            model_path = Path(tmpdir) / "intent_model.pkl"
            meta_path = Path(tmpdir) / "metadata.json"

            # Save
            joblib.dump(model, model_path)
            meta_path.write_text('{"name": "intent_prediction", "version": "1.0.0"}')

            assert model_path.exists()
            assert meta_path.exists()

            # Load
            loaded_model = joblib.load(model_path)

            # Predict
            X_test = X.head(50)
            original_preds = model.predict(X_test)
            loaded_preds = loaded_model.predict(X_test)

            np.testing.assert_array_equal(original_preds, loaded_preds)

            # Validate shapes and types
            assert original_preds.shape == (50,)
            assert set(original_preds).issubset(set(y.unique()))

    def test_end_to_end_churn(
        self, churn_data: tuple[pd.DataFrame, pd.Series]
    ) -> None:
        """Train -> Save -> Load -> Predict for churn prediction."""
        xgb = pytest.importorskip("xgboost")

        X, y = churn_data

        # Train
        model = xgb.XGBClassifier(
            n_estimators=50,
            max_depth=4,
            learning_rate=0.1,
            eval_metric="auc",
            random_state=42,
        )
        model.fit(X, y, verbose=False)

        with tempfile.TemporaryDirectory() as tmpdir:
            model_path = Path(tmpdir) / "churn_xgb.json"

            # Save
            model.save_model(str(model_path))
            assert model_path.exists()

            # Load
            loaded_model = xgb.XGBClassifier()
            loaded_model.load_model(str(model_path))

            # Predict
            X_test = X.head(50)
            original_proba = model.predict_proba(X_test)[:, 1]
            loaded_proba = loaded_model.predict_proba(X_test)[:, 1]

            np.testing.assert_array_almost_equal(
                original_proba, loaded_proba, decimal=5
            )

            # Validate probability bounds
            assert (loaded_proba >= 0.0).all()
            assert (loaded_proba <= 1.0).all()

    def test_end_to_end_ltv(
        self, ltv_data: tuple[pd.DataFrame, pd.Series]
    ) -> None:
        """Train -> Save -> Load -> Predict for LTV prediction."""
        xgb = pytest.importorskip("xgboost")

        X, y = ltv_data

        # Train
        model = xgb.XGBRegressor(
            n_estimators=100,
            max_depth=6,
            learning_rate=0.05,
            random_state=42,
        )
        model.fit(X, y, verbose=False)

        with tempfile.TemporaryDirectory() as tmpdir:
            model_path = Path(tmpdir) / "ltv_xgb.json"

            # Save
            model.save_model(str(model_path))

            # Load
            loaded_model = xgb.XGBRegressor()
            loaded_model.load_model(str(model_path))

            # Predict
            X_test = X.head(50)
            original_preds = model.predict(X_test)
            loaded_preds = loaded_model.predict(X_test)

            np.testing.assert_array_almost_equal(
                original_preds, loaded_preds, decimal=5
            )
            assert np.isfinite(loaded_preds).all()

    def test_end_to_end_bot_detection(
        self, bot_data: tuple[pd.DataFrame, pd.Series]
    ) -> None:
        """Train -> Save -> Load -> Predict for bot detection."""
        import joblib
        from sklearn.ensemble import RandomForestClassifier

        X, y = bot_data

        # Train
        model = RandomForestClassifier(
            n_estimators=100,
            max_depth=10,
            class_weight="balanced",
            random_state=42,
        )
        model.fit(X, y)

        with tempfile.TemporaryDirectory() as tmpdir:
            model_path = Path(tmpdir) / "bot_model.pkl"

            # Save
            joblib.dump(model, model_path)

            # Load
            loaded_model = joblib.load(model_path)

            # Predict
            X_test = X.head(50)
            original_preds = model.predict(X_test)
            loaded_preds = loaded_model.predict(X_test)

            np.testing.assert_array_equal(original_preds, loaded_preds)
            assert set(loaded_preds).issubset({0, 1})

    def test_end_to_end_session_scorer(
        self, session_data: tuple[pd.DataFrame, pd.Series]
    ) -> None:
        """Train -> Save -> Load -> Predict for session scoring."""
        import joblib
        from sklearn.linear_model import LogisticRegression

        X, y = session_data

        # Train
        model = LogisticRegression(C=1.0, max_iter=1000, solver="lbfgs")
        model.fit(X, y)

        with tempfile.TemporaryDirectory() as tmpdir:
            model_path = Path(tmpdir) / "session_scorer.pkl"

            # Save
            joblib.dump(model, model_path)

            # Load
            loaded_model = joblib.load(model_path)

            # Predict (SessionScorer returns probabilities)
            X_test = X.head(50)
            original_scores = model.predict_proba(X_test)[:, 1]
            loaded_scores = loaded_model.predict_proba(X_test)[:, 1]

            np.testing.assert_array_almost_equal(original_scores, loaded_scores)
            assert (loaded_scores >= 0.0).all()
            assert (loaded_scores <= 1.0).all()

    def test_end_to_end_anomaly_detection(
        self, anomaly_data: pd.DataFrame
    ) -> None:
        """Train -> Save -> Load -> Predict for anomaly detection."""
        import joblib
        from sklearn.ensemble import IsolationForest

        # Train
        model = IsolationForest(
            n_estimators=200,
            contamination=0.01,
            random_state=42,
        )
        model.fit(anomaly_data)

        with tempfile.TemporaryDirectory() as tmpdir:
            model_path = Path(tmpdir) / "iforest.pkl"

            # Save
            joblib.dump(model, model_path)

            # Load
            loaded_model = joblib.load(model_path)

            # Predict
            X_test = anomaly_data.head(50)
            original_preds = model.predict(X_test)
            loaded_preds = loaded_model.predict(X_test)

            np.testing.assert_array_equal(original_preds, loaded_preds)

    def test_batch_prediction(
        self, churn_data: tuple[pd.DataFrame, pd.Series]
    ) -> None:
        """Test batch prediction (multiple instances at once)."""
        xgb = pytest.importorskip("xgboost")

        X, y = churn_data

        model = xgb.XGBClassifier(n_estimators=50, random_state=42)
        model.fit(X, y, verbose=False)

        # Batch of 100 instances
        batch = X.head(100)
        predictions = model.predict_proba(batch)[:, 1]

        assert predictions.shape == (100,)
        assert (predictions >= 0.0).all()
        assert (predictions <= 1.0).all()
        # All predictions should be finite
        assert np.isfinite(predictions).all()


@pytest.mark.integration
class TestFeaturePipelineIntegration:
    """Integration tests for the feature computation pipeline."""

    def test_full_pipeline_run(self, raw_events: pd.DataFrame) -> None:
        """Run the full feature pipeline on synthetic events."""
        from features.pipeline import FeaturePipeline, FeaturePipelineConfig

        with tempfile.TemporaryDirectory() as tmpdir:
            config = FeaturePipelineConfig(
                input_path="/dev/null",
                output_path=tmpdir,
                feature_groups=[
                    "session_features",
                    "behavioral_features",
                    "identity_features",
                ],
                write_offline=False,
            )
            pipeline = FeaturePipeline(config)

            # Run individual feature groups
            session_features = pipeline.compute_session_features(raw_events)
            behavioral_features = pipeline.compute_behavioral_features(raw_events)
            identity_features = pipeline.compute_identity_features(raw_events)

            # Validate all returned non-empty DataFrames
            assert not session_features.empty
            assert not behavioral_features.empty
            assert not identity_features.empty

            # Validate session features have expected columns
            assert "session_id" in session_features.columns
            assert "session_id" in behavioral_features.columns
            assert "identity_id" in identity_features.columns

    def test_feature_pipeline_save_local(self, raw_events: pd.DataFrame) -> None:
        """Test saving computed features to local filesystem."""
        from features.pipeline import FeaturePipeline, FeaturePipelineConfig

        with tempfile.TemporaryDirectory() as tmpdir:
            config = FeaturePipelineConfig(
                input_path="/dev/null",
                output_path=tmpdir,
                feature_groups=["session_features"],
                write_offline=True,
            )
            pipeline = FeaturePipeline(config)
            session_features = pipeline.compute_session_features(raw_events)

            if not session_features.empty:
                saved_path = pipeline._save_features("session_features", session_features)
                assert Path(saved_path).exists()


@pytest.mark.integration
class TestPreprocessingIntegration:
    """Integration tests for the preprocessing pipeline."""

    def test_preprocess_then_train(
        self, churn_data: tuple[pd.DataFrame, pd.Series]
    ) -> None:
        """Preprocess data, then train a model on the transformed features."""
        xgb = pytest.importorskip("xgboost")
        from common.src.preprocessing import PreprocessingPipeline

        X, y = churn_data

        # Preprocessing
        pipe = PreprocessingPipeline(
            numeric_features=list(X.columns),
            categorical_features=[],
            target_column=None,
        )
        X_transformed = pipe.fit_transform(X)

        # Train
        model = xgb.XGBClassifier(n_estimators=50, random_state=42)
        model.fit(X_transformed, y, verbose=False)

        # Predict
        predictions = model.predict_proba(X_transformed)[:, 1]
        assert predictions.shape == (len(X),)
        assert (predictions >= 0.0).all()
        assert (predictions <= 1.0).all()

    def test_preprocess_save_load_then_predict(
        self, churn_data: tuple[pd.DataFrame, pd.Series]
    ) -> None:
        """Full round-trip: preprocess, save pipeline, load, transform new data."""
        from common.src.preprocessing import PreprocessingPipeline

        X, y = churn_data

        pipe = PreprocessingPipeline(
            numeric_features=list(X.columns),
            categorical_features=[],
        )
        X_train = pipe.fit_transform(X)

        with tempfile.TemporaryDirectory() as tmpdir:
            pipe_path = Path(tmpdir) / "preprocessor.joblib"
            pipe.save(pipe_path)

            loaded_pipe = PreprocessingPipeline.load(pipe_path)
            X_test = loaded_pipe.transform(X.head(50))

            np.testing.assert_array_almost_equal(X_train[:50], X_test)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "-m", "integration"])
