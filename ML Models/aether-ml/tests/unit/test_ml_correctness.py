"""
Aether ML — Unit Tests: training/serving correctness remediation.

Proves:
  - No train/test leakage: preprocessing statistics (clip quantiles, scaler
    stats) are computed from the TRAINING split only — holdout extrema can no
    longer move them. (Under the old order — preprocess full dataset, then
    split — these assertions fail: a 30% holdout poisoned at 1e9 drags the
    full-data 0.99-quantile and scaler mean to ~1e9/3e8.)
  - Fail-closed threshold gate: missing / NaN / inf metrics -> threshold_passed False.
  - Anomaly-rate threshold is evaluated as a CAP (contamination=0.05 passes 0.1).
  - Stratified re-split works on non-RangeIndex data.
  - Dataset manifest self-hash is canonical and verifiable.
  - metadata.json is written once with canonical + pipeline fields merged.
  - Serving parity: preprocessing.joblib is loaded and applied at predict time,
    with feature-schema-hash verification at load.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pd = pytest.importorskip("pandas")

from sklearn.model_selection import train_test_split


# =============================================================================
# Helpers / fixtures
# =============================================================================


@pytest.fixture(scope="module")
def trained_intent(tmp_path_factory) -> dict:
    """Train intent_prediction once (fast LogisticRegression) for reuse."""
    from training.pipelines.train import TrainingPipeline

    out = tmp_path_factory.mktemp("intent_artifacts")
    pipeline = TrainingPipeline(
        model_name="intent_prediction",
        output_dir=str(out),
        synthetic_data=True,
    )
    result = pipeline.run()
    assert result["status"] == "success"
    return {"pipeline": pipeline, "result": result, "artifact_path": Path(result["artifact_path"])}


# =============================================================================
# 1. Leakage: preprocessing fitted on the training split ONLY
# =============================================================================


class TestNoPreprocessingLeakage:
    def _poisoned_pipeline(self, tmp_path: Path):
        """Pipeline whose holdout (temp) rows carry extreme values.

        Replicates run()'s first split (test_size=0.3, random_state=42,
        no stratify for regression with >20 unique targets) to know exactly
        which rows land in the val/test partitions, then poisons ONLY those.
        """
        from training.pipelines.train import TrainingPipeline

        rng = np.random.default_rng(7)
        n = 400
        X = pd.DataFrame(
            {
                "f0": rng.standard_normal(n),
                "f1": rng.standard_normal(n),
                "f2": rng.standard_normal(n),
            }
        )
        y = pd.Series(rng.standard_normal(n), name="target")  # regression, no stratify

        # Same partition run() will produce for this n / seed / test_size.
        _train_idx, temp_idx = train_test_split(
            np.arange(n), test_size=0.3, random_state=42
        )
        X.loc[temp_idx, "f0"] = 1e9  # poison ONLY the holdout rows

        pipeline = TrainingPipeline(
            model_name="session_scorer",
            output_dir=str(tmp_path),
            synthetic_data=True,
        )
        pipeline._load_data_with_flag = lambda: (X, y, True)  # type: ignore[method-assign]
        return pipeline, X, np.asarray(_train_idx)

    def test_holdout_extrema_cannot_move_clip_bounds(self, tmp_path: Path):
        pipeline, X, train_idx = self._poisoned_pipeline(tmp_path)
        result = pipeline.run()
        assert result["status"] == "success"

        lo, hi = pipeline._clip_bounds["f0"]
        # Train-only 0.99-quantile of a standard normal is ~2.3. Under the OLD
        # order (preprocess before split) the full-data quantile is 1e9.
        assert hi < 1e3, (
            f"clip upper bound {hi} was influenced by holdout extrema — "
            "preprocessing leaked test data"
        )
        expected_hi = float(X.loc[train_idx, "f0"].quantile(0.99))
        assert hi == pytest.approx(expected_hi)

    def test_holdout_extrema_cannot_move_scaler_stats(self, tmp_path: Path):
        pipeline, _X, _train_idx = self._poisoned_pipeline(tmp_path)
        pipeline.run()

        scaler = (
            pipeline._preprocessing_pipeline
            .named_transformers_["num"]
            .named_steps["scaler"]
        )
        f0_pos = pipeline._numeric_cols.index("f0")
        # Old order: mean over full data ≈ 0.3 * 1e9 = 3e8.
        assert abs(scaler.mean_[f0_pos]) < 1e3, (
            "scaler mean was influenced by holdout extrema — preprocessing leaked"
        )

    def test_transform_clips_to_train_bounds(self, tmp_path: Path):
        from training.pipelines.train import TrainingPipeline

        pipeline = TrainingPipeline(
            model_name="session_scorer", output_dir=str(tmp_path), synthetic_data=True
        )
        rng = np.random.default_rng(0)
        X_train = pd.DataFrame({"a": rng.standard_normal(200)})
        X_test = pd.DataFrame({"a": [1e12, -1e12, 0.0]})

        pipeline._fit_preprocess(X_train)
        lo, hi = pipeline._clip_bounds["a"]
        transformed = pipeline._transform(X_test)

        scaler = (
            pipeline._preprocessing_pipeline
            .named_transformers_["num"].named_steps["scaler"]
        )
        max_scaled = (hi - scaler.mean_[0]) / scaler.scale_[0]
        min_scaled = (lo - scaler.mean_[0]) / scaler.scale_[0]
        assert transformed["a"].max() <= max_scaled + 1e-9
        assert transformed["a"].min() >= min_scaled - 1e-9

    def test_transform_before_fit_raises(self, tmp_path: Path):
        from training.pipelines.train import TrainingPipeline

        pipeline = TrainingPipeline(
            model_name="session_scorer", output_dir=str(tmp_path), synthetic_data=True
        )
        with pytest.raises(RuntimeError, match="not fitted"):
            pipeline._transform(pd.DataFrame({"a": [1.0]}))


# =============================================================================
# 2. Stratified re-split works on non-RangeIndex data
# =============================================================================


class TestStratifySplitIndexSafety:
    def test_run_with_non_range_index(self, tmp_path: Path):
        from training.pipelines.train import TrainingPipeline

        rng = np.random.default_rng(3)
        n = 400
        X = pd.DataFrame(
            rng.standard_normal((n, 5)),
            columns=[f"c{i}" for i in range(5)],
            index=[f"row-{i}" for i in range(n)],  # string index — .iloc on labels breaks
        )
        y = pd.Series(np.tile(np.arange(4), n // 4), index=X.index, name="target")

        pipeline = TrainingPipeline(
            model_name="intent_prediction",
            output_dir=str(tmp_path),
            synthetic_data=True,
        )
        pipeline._load_data_with_flag = lambda: (X, y, True)  # type: ignore[method-assign]
        result = pipeline.run()
        assert result["status"] == "success"
        assert result["train_samples"] + result["val_samples"] + result["test_samples"] == n


# =============================================================================
# 3. Fail-closed threshold gate
# =============================================================================


class TestFailClosedThresholds:
    def _pipeline(self, tmp_path: Path, model: str):
        from training.pipelines.train import TrainingPipeline

        return TrainingPipeline(model_name=model, output_dir=str(tmp_path), synthetic_data=True)

    def test_zero_metrics_fails(self, tmp_path: Path):
        pipeline = self._pipeline(tmp_path, "bot_detection")
        passed, results = pipeline._check_thresholds({})
        assert passed is False
        assert set(results) == {"test_accuracy", "test_auc"}

    def test_partially_missing_metric_fails(self, tmp_path: Path):
        pipeline = self._pipeline(tmp_path, "bot_detection")
        passed, _ = pipeline._check_thresholds({"test_accuracy": 0.95})  # no test_auc
        assert passed is False

    def test_nan_metric_fails(self, tmp_path: Path):
        pipeline = self._pipeline(tmp_path, "bot_detection")
        passed, _ = pipeline._check_thresholds(
            {"test_accuracy": float("nan"), "test_auc": 0.95}
        )
        assert passed is False

    def test_inf_metric_fails(self, tmp_path: Path):
        pipeline = self._pipeline(tmp_path, "bot_detection")
        passed, _ = pipeline._check_thresholds(
            {"test_accuracy": float("inf"), "test_auc": 0.95}
        )
        assert passed is False

    def test_non_numeric_metric_fails(self, tmp_path: Path):
        pipeline = self._pipeline(tmp_path, "bot_detection")
        passed, _ = pipeline._check_thresholds(
            {"test_accuracy": "0.9", "test_auc": 0.95}  # type: ignore[dict-item]
        )
        assert passed is False

    def test_all_metrics_present_and_passing(self, tmp_path: Path):
        pipeline = self._pipeline(tmp_path, "bot_detection")
        passed, _ = pipeline._check_thresholds({"test_accuracy": 0.9, "test_auc": 0.95})
        assert passed is True

    def test_anomaly_rate_is_a_cap_not_a_floor(self, tmp_path: Path):
        pipeline = self._pipeline(tmp_path, "anomaly_detection")
        # contamination=0.05 -> healthy runs report ~0.05; the 0.1 threshold is
        # a maximum acceptable anomaly rate. As a floor this gate was unpassable.
        passed, _ = pipeline._check_thresholds({"test_anomaly_rate": 0.05})
        assert passed is True

        passed, _ = pipeline._check_thresholds({"test_anomaly_rate": 0.2})
        assert passed is False


# =============================================================================
# 4. Dataset manifest self-hash + single metadata write
# =============================================================================


class TestArtifactMetadataIntegrity:
    def test_manifest_checksum_is_verifiable(self, trained_intent: dict):
        from training.pipelines.train import compute_manifest_checksum

        manifest_path = trained_intent["artifact_path"] / "dataset_manifest.json"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text())
        stored = manifest.get("checksum")
        assert stored, "manifest missing checksum"
        assert compute_manifest_checksum(manifest) == stored, (
            "manifest checksum does not verify against canonical recomputation"
        )

    def test_metadata_contains_canonical_and_pipeline_fields(self, trained_intent: dict):
        meta = json.loads((trained_intent["artifact_path"] / "metadata.json").read_text())
        # canonical registry fields
        for field in (
            "model_id", "artifact_version", "promotion_state", "checksum_sha256",
            "created_at", "threshold_passed", "synthetic_data", "production_allowed",
        ):
            assert field in meta, f"canonical field missing: {field}"
        # pipeline fields previously discarded by the second write
        for field in ("tier", "class_name", "config", "train_metrics", "test_metrics"):
            assert field in meta, f"pipeline field missing: {field}"
        assert meta["tier"] == "edge"
        assert meta["synthetic_data"] is True
        assert meta["production_allowed"] is False

    def test_metadata_loads_as_registry_record(self, trained_intent: dict):
        from common.artifact_registry import ArtifactMetadata

        meta = ArtifactMetadata.load(trained_intent["artifact_path"] / "metadata.json")
        assert meta.model_id == "intent_prediction"
        assert meta.checksum_sha256


# =============================================================================
# 5. Serving parity: trained preprocessing loaded + applied, hash verified
# =============================================================================


class TestServingParity:
    def test_preprocessing_artifact_written_and_loadable(self, trained_intent: dict):
        from common.src.artifact_preprocessing import load_artifact_preprocessing

        artifact_dir = trained_intent["artifact_path"]
        assert (artifact_dir / "preprocessing.joblib").exists()

        pp = load_artifact_preprocessing(artifact_dir, model_id="intent_prediction")
        assert pp is not None
        assert pp.feature_order  # training feature order recovered
        assert pp.clip_bounds

    def test_transform_matches_training_transform(self, trained_intent: dict):
        from common.src.artifact_preprocessing import load_artifact_preprocessing

        pipeline = trained_intent["pipeline"]
        pp = load_artifact_preprocessing(
            trained_intent["artifact_path"], model_id="intent_prediction"
        )
        rng = np.random.default_rng(11)
        raw = pd.DataFrame(
            rng.standard_normal((5, len(pp.feature_order))), columns=pp.feature_order
        )
        served = pp.transform(raw)
        trained = pipeline._transform(raw)
        np.testing.assert_allclose(served.values, trained.values, rtol=1e-10)

    def test_edge_model_load_applies_trained_preprocessing(self, trained_intent: dict):
        import joblib
        from edge.models import IntentPrediction

        artifact_dir = trained_intent["artifact_path"]
        model = IntentPrediction()
        model.load(artifact_dir)
        assert model._preprocessing is not None, (
            "edge model did not load the trained preprocessing bundle"
        )

        rng = np.random.default_rng(13)
        feats = model._preprocessing.feature_order
        raw = pd.DataFrame(rng.standard_normal((8, len(feats))) * 5.0, columns=feats)

        estimator = joblib.load(artifact_dir / "model.joblib")
        expected = estimator.predict_proba(model._preprocessing.transform(raw))
        np.testing.assert_allclose(model.predict_proba(raw), expected, rtol=1e-10)

        # And it is NOT serving on the raw feature scale.
        raw_scale = estimator.predict_proba(raw)
        assert not np.allclose(model.predict_proba(raw), raw_scale), (
            "model is still serving on raw (untransformed) features"
        )

    def test_feature_schema_hash_mismatch_fails_load(self, trained_intent: dict, tmp_path: Path):
        from common.feature_contracts import compute_schema_hash
        from common.src.artifact_preprocessing import (
            FeatureSchemaMismatch,
            load_artifact_preprocessing,
        )

        # A mismatch only triggers when the contract hash is available.
        assert compute_schema_hash("intent_prediction")

        tampered = tmp_path / "tampered"
        shutil.copytree(trained_intent["artifact_path"], tampered)
        meta_path = tampered / "metadata.json"
        meta = json.loads(meta_path.read_text())
        meta["feature_schema_hash"] = "deadbeef" * 8
        meta_path.write_text(json.dumps(meta))

        with pytest.raises(FeatureSchemaMismatch):
            load_artifact_preprocessing(tampered, model_id="intent_prediction")

    def test_legacy_artifact_without_preprocessing_falls_back(self, tmp_path: Path):
        import joblib
        from sklearn.linear_model import LogisticRegression
        from edge.models import SessionScorer

        rng = np.random.default_rng(5)
        X = pd.DataFrame(
            rng.standard_normal((100, len(SessionScorer.FEATURE_NAMES))),
            columns=SessionScorer.FEATURE_NAMES,
        )
        y = (rng.random(100) > 0.5).astype(int)
        est = LogisticRegression(max_iter=200).fit(X, y)

        legacy_dir = tmp_path / "legacy"
        legacy_dir.mkdir()
        joblib.dump(est, legacy_dir / "session_scorer.pkl")

        model = SessionScorer()
        model.load(legacy_dir)
        assert model._preprocessing is None
        scores = model.predict(X.head(3))
        assert len(scores) == 3
