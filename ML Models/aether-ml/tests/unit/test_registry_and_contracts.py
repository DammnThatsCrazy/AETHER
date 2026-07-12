"""
Aether ML — Unit Tests: Canonical Model Registry and Feature Contracts

Tests proving:
  - One canonical registry exists
  - All model IDs are unique
  - Deprecated aliases resolve correctly
  - Unknown names fail cleanly
  - Feature contracts exist for every trainable model
  - Generated example features validate
  - Missing required features fail
  - Type mismatches fail
  - Aliases normalize correctly
  - Registry exports are consistent
"""

from __future__ import annotations

import warnings

import pytest


# ---------------------------------------------------------------------------
# Model Registry Tests
# ---------------------------------------------------------------------------


class TestModelRegistry:
    """Tests for the canonical ML model registry."""

    def test_registry_importable(self):
        from common.model_registry import list_models
        models = list_models()
        assert len(models) > 0

    def test_all_model_ids_unique(self):
        from common.model_registry import list_models
        ids = [m.model_id for m in list_models()]
        assert len(ids) == len(set(ids)), f"Duplicate model IDs: {ids}"

    def test_nine_trainable_models(self):
        from common.model_registry import list_trainable_models
        trainable = list_trainable_models()
        assert len(trainable) == 9, (
            f"Expected 9 trainable models, got {len(trainable)}: "
            f"{[m.model_id for m in trainable]}"
        )

    def test_trainable_model_ids(self):
        from common.model_registry import list_trainable_models
        expected = {
            "intent_prediction", "bot_detection", "session_scorer",
            "identity_resolution", "journey_prediction", "churn_prediction",
            "ltv_prediction", "anomaly_detection", "campaign_attribution",
        }
        actual = {m.model_id for m in list_trainable_models()}
        assert actual == expected

    def test_eleven_total_models(self):
        from common.model_registry import list_models
        assert len(list_models()) == 11

    def test_bytecode_risk_is_deterministic(self):
        from common.model_registry import get_model, ImplementationType
        entry = get_model("bytecode_risk")
        assert entry is not None
        assert entry.implementation_type == ImplementationType.DETERMINISTIC_RULE_BASED
        assert not entry.training_supported

    def test_trust_score_is_composite(self):
        from common.model_registry import get_model, ImplementationType
        entry = get_model("trust_score")
        assert entry is not None
        assert entry.implementation_type == ImplementationType.COMPOSITE_SCORE
        assert not entry.training_supported

    def test_canonical_id_resolves_to_itself(self):
        from common.model_registry import resolve_model_id
        assert resolve_model_id("intent_prediction") == "intent_prediction"
        assert resolve_model_id("churn_prediction") == "churn_prediction"

    def test_deprecated_alias_identity_gnn_resolves(self):
        from common.model_registry import resolve_model_id
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            canonical = resolve_model_id("identity_gnn")
        assert canonical == "identity_resolution"
        assert any(issubclass(w.category, DeprecationWarning) for w in caught)

    def test_deprecated_alias_journey_tft_resolves(self):
        from common.model_registry import resolve_model_id
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            canonical = resolve_model_id("journey_tft")
        assert canonical == "journey_prediction"
        assert any(issubclass(w.category, DeprecationWarning) for w in caught)

    def test_unknown_name_returns_none(self):
        from common.model_registry import resolve_model_id
        assert resolve_model_id("definitely_not_a_model") is None
        assert resolve_model_id("") is None
        assert resolve_model_id("identity_gnn_typo") is None

    def test_require_model_raises_for_unknown(self):
        from common.model_registry import require_model
        with pytest.raises(ValueError, match="Unknown model"):
            require_model("not_a_real_model")

    def test_require_model_returns_entry_for_known(self):
        from common.model_registry import require_model
        entry = require_model("churn_prediction")
        assert entry.model_id == "churn_prediction"

    def test_require_model_resolves_deprecated_alias(self):
        from common.model_registry import require_model
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            entry = require_model("identity_gnn")
        assert entry.model_id == "identity_resolution"

    def test_batch_allowed_for_non_privileged(self):
        from common.model_registry import is_batch_allowed
        # intent_prediction does not require privileged for batch (batch not supported)
        assert not is_batch_allowed("intent_prediction", {"is_privileged": False})

    def test_batch_allowed_for_privileged_critical_model(self):
        from common.model_registry import is_batch_allowed
        # churn_prediction requires privileged
        assert is_batch_allowed("churn_prediction", {"is_privileged": True})
        assert not is_batch_allowed("churn_prediction", {"is_privileged": False})

    def test_model_stub_not_allowed_in_production(self):
        from common.model_registry import model_is_stub_allowed
        assert not model_is_stub_allowed("production", "intent_prediction")
        assert not model_is_stub_allowed("staging", "bot_detection")

    def test_model_stub_allowed_in_local(self):
        from common.model_registry import model_is_stub_allowed
        assert model_is_stub_allowed("local", "intent_prediction")
        assert model_is_stub_allowed("development", "churn_prediction")

    def test_model_stub_not_allowed_for_deterministic(self):
        from common.model_registry import model_is_stub_allowed
        # bytecode_risk is deterministic — stubs don't apply
        assert not model_is_stub_allowed("local", "bytecode_risk")

    def test_export_registry_for_docs_returns_all_models(self):
        from common.model_registry import export_registry_for_docs, list_models
        docs = export_registry_for_docs()
        all_models = list_models()
        assert len(docs) == len(all_models)
        for row in docs:
            assert "model_id" in row
            assert "display_name" in row
            assert "implementation_type" in row

    def test_export_registry_for_backend_has_canonical_ids(self):
        from common.model_registry import export_registry_for_backend
        backend = export_registry_for_backend()
        assert "canonical_ids" in backend
        assert "deprecated_aliases" in backend
        assert "identity_gnn" in backend["deprecated_aliases"]
        assert backend["deprecated_aliases"]["identity_gnn"] == "identity_resolution"
        assert "journey_tft" in backend["deprecated_aliases"]

    def test_export_registry_for_serving_includes_artifact_info(self):
        from common.model_registry import export_registry_for_serving
        serving = export_registry_for_serving()
        assert "intent_prediction" in serving
        assert "artifact_name" in serving["intent_prediction"]
        assert "fail_closed_required" in serving["intent_prediction"]

    def test_every_trainable_model_has_artifact_info(self):
        from common.model_registry import list_trainable_models
        for entry in list_trainable_models():
            assert entry.artifact_format is not None
            assert entry.artifact_name, f"{entry.model_id} missing artifact_name"
            assert entry.serving_endpoint, f"{entry.model_id} missing serving_endpoint"

    def test_no_duplicate_serving_endpoints_for_trainable(self):
        """Trainable models should not share serving endpoints (except batch)."""
        from common.model_registry import list_trainable_models
        endpoints = [
            m.serving_endpoint for m in list_trainable_models()
            if m.serving_endpoint != "/v1/predict/batch"
        ]
        assert len(endpoints) == len(set(endpoints)), (
            f"Duplicate serving endpoints: {endpoints}"
        )

    def test_every_model_has_owner(self):
        from common.model_registry import list_models
        for entry in list_models():
            assert entry.owner, f"{entry.model_id} missing owner"


# ---------------------------------------------------------------------------
# Feature Contract Tests
# ---------------------------------------------------------------------------


class TestFeatureContracts:
    """Tests for ML feature contracts."""

    def test_all_trainable_models_have_contracts(self):
        from common.model_registry import list_trainable_models
        from common.feature_contracts import get_feature_contract
        for entry in list_trainable_models():
            contract = get_feature_contract(entry.model_id)
            assert contract is not None, f"No feature contract for {entry.model_id}"

    def test_unknown_model_raises_key_error(self):
        from common.feature_contracts import get_feature_contract
        with pytest.raises(KeyError, match="No feature contract"):
            get_feature_contract("not_a_real_model_xyz")

    def test_every_contract_has_stable_schema_hash(self):
        from common.model_registry import list_trainable_models
        from common.feature_contracts import compute_schema_hash
        hashes = {}
        for entry in list_trainable_models():
            h = compute_schema_hash(entry.model_id)
            assert h, f"{entry.model_id} schema hash is empty"
            assert len(h) == 16, f"{entry.model_id} schema hash wrong length: {h}"
            # Compute again to verify stability
            h2 = compute_schema_hash(entry.model_id)
            assert h == h2, f"{entry.model_id} schema hash not stable"
            hashes[entry.model_id] = h

        # All hashes must be unique
        assert len(set(hashes.values())) == len(hashes), (
            f"Duplicate schema hashes: {hashes}"
        )

    def test_generated_example_validates(self):
        from common.model_registry import list_trainable_models
        from common.feature_contracts import generate_example_features, validate_features
        for entry in list_trainable_models():
            example = generate_example_features(entry.model_id)
            assert example, f"Empty example for {entry.model_id}"
            # Should not raise
            validate_features(entry.model_id, example)

    def test_missing_required_feature_fails(self):
        from common.feature_contracts import (
            validate_features, FeatureValidationError, get_feature_contract
        )
        # Remove one required feature from intent_prediction
        contract = get_feature_contract("intent_prediction")
        features = {f: 0.5 for f in contract.required_features[1:]}  # Skip first
        with pytest.raises(FeatureValidationError) as exc_info:
            validate_features("intent_prediction", features, allow_defaults=False)
        assert "missing_required" in str(exc_info.value).lower() or exc_info.value.missing

    def test_type_mismatch_fails(self):
        from common.feature_contracts import (
            validate_features, FeatureValidationError, generate_example_features
        )
        # bot_detection has int fields
        features = generate_example_features("bot_detection")
        features["keypress_count"] = "not_an_int"  # Type mismatch
        with pytest.raises(FeatureValidationError) as exc_info:
            validate_features("bot_detection", features)
        assert exc_info.value.type_errors

    def test_alias_normalises_correctly(self):
        from common.feature_contracts import normalize_features
        # session_scorer: page_count has alias "pages_viewed"
        features = {
            "pages_viewed": 5,  # alias for page_count
            "event_count": 10,
            "session_duration_s": 300.0,
            "max_scroll_depth": 0.7,
            "click_count": 8,
            "active_ratio": 0.6,
        }
        normalised = normalize_features("session_scorer", features)
        assert "page_count" in normalised, "Alias 'pages_viewed' should resolve to 'page_count'"
        assert normalised["page_count"] == 5

    def test_intent_prediction_alias_session_duration(self):
        from common.feature_contracts import normalize_features, generate_example_features
        features = generate_example_features("intent_prediction")
        # Replace canonical name with alias
        features["session_duration"] = features.pop("session_duration_s", 100.0)
        normalised = normalize_features("intent_prediction", features)
        assert "session_duration_s" in normalised

    def test_defaults_applied_for_optional_features(self):
        from common.feature_contracts import normalize_features
        # session_scorer: form_interaction_count is optional with default 0
        features = {
            "page_count": 3,
            "event_count": 10,
            "session_duration_s": 300.0,
            "max_scroll_depth": 0.5,
            "click_count": 5,
            "active_ratio": 0.8,
        }
        normalised = normalize_features("session_scorer", features, apply_defaults=True)
        assert "form_interaction_count" in normalised
        assert normalised["form_interaction_count"] == 0

    def test_explain_missing_features(self):
        from common.feature_contracts import explain_missing_features
        features = {"click_count": 10}  # Missing most intent_prediction features
        explanation = explain_missing_features("intent_prediction", features)
        assert "missing_required" in explanation
        assert len(explanation["missing_required"]) > 0
        assert "schema_hash" in explanation
        assert "model_id" in explanation

    def test_churn_contract_has_correct_features(self):
        from common.feature_contracts import get_feature_contract
        contract = get_feature_contract("churn_prediction")
        required = set(contract.required_features)
        assert "days_since_last_visit" in required
        assert "churned_30d" not in required  # target column is not a feature

    def test_journey_prediction_alias_page_sequence(self):
        from common.feature_contracts import normalize_features
        features = {
            "page_sequence": 5,  # alias for page_sequence_len
            "time_deltas": 30.0,  # alias for avg_time_delta
            "device_type": 1.0,  # alias for device_type_encoded
            "session_number": 2,
            "day_of_week": 3,
            "hour_of_day": 14,
        }
        normalised = normalize_features("journey_prediction", features)
        assert "page_sequence_len" in normalised
        assert "avg_time_delta" in normalised
        assert "device_type_encoded" in normalised

    def test_ltv_optional_web3_features_have_defaults(self):
        from common.feature_contracts import normalize_features
        features = {
            "purchase_frequency": 2.0,
            "recency_days": 30.0,
            "monetary_mean": 50.0,
            "monetary_total": 300.0,
            "avg_session_duration": 200.0,
            "total_sessions": 15,
            "conversion_rate": 0.05,
            "acquisition_channel_score": 0.6,
            "engagement_percentile": 0.7,
            # web3_tx_count and web3_total_value not provided
        }
        normalised = normalize_features("ltv_prediction", features)
        assert normalised.get("web3_tx_count") == 0
        assert normalised.get("web3_total_value") == 0.0


# ---------------------------------------------------------------------------
# Backend Registry Alignment Tests
# ---------------------------------------------------------------------------


class TestBackendRegistryAlignment:
    """Tests proving backend and serving registries match canonical registry."""

    def test_backend_does_not_use_identity_gnn(self):
        """Backend routes must not have hardcoded identity_gnn."""
        import pathlib
        routes_file = pathlib.Path(
            "Backend Architecture/aether-backend/services/ml_serving/routes.py"
        )
        if not routes_file.exists():
            pytest.skip("Backend routes not found at expected path")
        content = routes_file.read_text()
        # The only valid occurrence is in the deprecated aliases map
        lines = [l for l in content.splitlines() if "identity_gnn" in l]
        # Should only appear in the static deprecated alias dict
        for line in lines:
            assert "deprecated" in line.lower() or "alias" in line.lower() or "#" in line, (
                f"identity_gnn used outside deprecated alias context: {line!r}"
            )

    def test_backend_does_not_use_journey_tft(self):
        """Backend routes must not have hardcoded journey_tft."""
        import pathlib
        routes_file = pathlib.Path(
            "Backend Architecture/aether-backend/services/ml_serving/routes.py"
        )
        if not routes_file.exists():
            pytest.skip("Backend routes not found at expected path")
        content = routes_file.read_text()
        lines = [l for l in content.splitlines() if "journey_tft" in l]
        for line in lines:
            assert "deprecated" in line.lower() or "alias" in line.lower() or "#" in line, (
                f"journey_tft used outside deprecated alias context: {line!r}"
            )

    def test_backend_uses_post_result_output_not_modified_output(self):
        """Backend must use post_result.output, not post_result.modified_output."""
        import pathlib
        routes_file = pathlib.Path(
            "Backend Architecture/aether-backend/services/ml_serving/routes.py"
        )
        if not routes_file.exists():
            pytest.skip("Backend routes not found at expected path")
        content = routes_file.read_text()
        assert "modified_output" not in content, (
            "Backend routes still references the nonexistent 'modified_output' field. "
            "PostResponseResult only has 'output'."
        )

    def test_serving_model_names_match_canonical_registry(self):
        """Serving API MODEL_NAMES must match canonical trainable models."""
        from common.model_registry import list_trainable_models
        canonical_trainable = {m.model_id for m in list_trainable_models()}

        # Import MODEL_NAMES directly — registry-derived, not a static list.
        from serving.src.api import MODEL_NAMES
        serving_names = set(MODEL_NAMES)

        assert serving_names == canonical_trainable, (
            f"Serving MODEL_NAMES {sorted(serving_names)} != "
            f"canonical trainable {sorted(canonical_trainable)}"
        )

    def test_training_registry_matches_canonical(self):
        """Training pipeline MODEL_REGISTRY must match canonical trainable models."""
        import pathlib
        train_file = pathlib.Path("ML Models/aether-ml/training/pipelines/train.py")
        if not train_file.exists():
            pytest.skip("Training pipeline not found at expected path")

        from common.model_registry import list_trainable_models
        canonical_trainable = {m.model_id for m in list_trainable_models()}

        content = train_file.read_text()
        import re
        # Find MODEL_REGISTRY dict keys
        keys = set(re.findall(r'"(intent_prediction|bot_detection|session_scorer|'
                              r'identity_resolution|journey_prediction|churn_prediction|'
                              r'ltv_prediction|anomaly_detection|campaign_attribution)"',
                              content))
        # At minimum these 9 should appear
        assert canonical_trainable.issubset(keys), (
            f"Training pipeline missing models: {canonical_trainable - keys}"
        )


# ---------------------------------------------------------------------------
# Artifact Registry Tests
# ---------------------------------------------------------------------------


class TestArtifactRegistry:
    """Tests for the artifact registry lifecycle."""

    def test_artifact_registry_importable(self):
        from common.artifact_registry import (
            save_artifact, load_artifact, validate_artifact,
            list_artifacts, promote_artifact, disable_artifact,
        )

    def test_save_load_artifact(self, tmp_path):
        from common.artifact_registry import save_artifact, load_artifact
        import joblib

        model_dir = tmp_path / "intent_prediction" / "v1_20240601_120000"
        model_dir.mkdir(parents=True)
        artifact_file = model_dir / "model.joblib"

        # Create a tiny artifact
        from sklearn.linear_model import LogisticRegression
        model = LogisticRegression()
        joblib.dump(model, artifact_file)

        meta = save_artifact(
            model_id="intent_prediction",
            artifact_path=artifact_file,
            artifact_version="v1_20240601_120000",
            synthetic_data=True,
        )
        assert meta.model_id == "intent_prediction"
        assert meta.synthetic_data is True
        assert meta.production_allowed is False  # synthetic can never be production

        # Load it back
        loaded_path, loaded_meta = load_artifact(model_dir, env="local")
        assert loaded_path == artifact_file
        assert loaded_meta.model_id == "intent_prediction"

    def test_missing_metadata_raises(self, tmp_path):
        from common.artifact_registry import load_artifact, ArtifactNotFound

        model_dir = tmp_path / "no_metadata"
        model_dir.mkdir()
        with pytest.raises(ArtifactNotFound, match="metadata"):
            load_artifact(model_dir)

    def test_checksum_mismatch_raises(self, tmp_path):
        from common.artifact_registry import save_artifact, load_artifact, ArtifactChecksumMismatch
        import joblib

        model_dir = tmp_path / "churn" / "v1_test"
        model_dir.mkdir(parents=True)
        artifact_file = model_dir / "model.joblib"

        from sklearn.ensemble import GradientBoostingClassifier
        joblib.dump(GradientBoostingClassifier(), artifact_file)

        save_artifact(
            model_id="churn_prediction",
            artifact_path=artifact_file,
            artifact_version="v1_test",
            synthetic_data=True,
        )

        # Corrupt the artifact
        artifact_file.write_bytes(b"corrupted_data")

        with pytest.raises(ArtifactChecksumMismatch):
            load_artifact(model_dir)

    def test_synthetic_artifact_cannot_be_loaded_in_production(self, tmp_path):
        from common.artifact_registry import save_artifact, load_artifact, ArtifactLoadingPolicyError
        import joblib

        model_dir = tmp_path / "churn" / "v1_synthetic"
        model_dir.mkdir(parents=True)
        artifact_file = model_dir / "model.joblib"
        joblib.dump({"stub": True}, artifact_file)

        save_artifact(
            model_id="churn_prediction",
            artifact_path=artifact_file,
            artifact_version="v1_synthetic",
            promotion_state="promoted",
            synthetic_data=True,
            threshold_passed=True,
        )

        with pytest.raises(ArtifactLoadingPolicyError, match="synthetic"):
            load_artifact(model_dir, env="production")

    def test_synthetic_artifact_cannot_promote_to_production(self, tmp_path):
        from common.artifact_registry import save_artifact, promote_artifact, ArtifactPromotionError
        import joblib

        model_dir = tmp_path / "churn" / "v1_synthetic_prom"
        model_dir.mkdir(parents=True)
        artifact_file = model_dir / "model.joblib"
        joblib.dump({"stub": True}, artifact_file)

        save_artifact(
            model_id="churn_prediction",
            artifact_path=artifact_file,
            artifact_version="v1_synthetic_prom",
            promotion_state="trained",
            synthetic_data=True,
        )

        with pytest.raises(ArtifactPromotionError, match="synthetic"):
            promote_artifact(model_dir, "promoted")

    def test_disabled_artifact_cannot_load(self, tmp_path):
        from common.artifact_registry import save_artifact, disable_artifact, load_artifact, ArtifactLoadingPolicyError
        import joblib

        model_dir = tmp_path / "bot" / "v1_disabled"
        model_dir.mkdir(parents=True)
        artifact_file = model_dir / "model.joblib"
        joblib.dump({"stub": True}, artifact_file)

        save_artifact(
            model_id="bot_detection",
            artifact_path=artifact_file,
            artifact_version="v1_disabled",
            promotion_state="trained",
        )

        disable_artifact(model_dir, reason="test")

        with pytest.raises(ArtifactLoadingPolicyError, match="disabled"):
            load_artifact(model_dir)

    def test_production_loading_fails_closed_without_promoted_state(self, tmp_path):
        from common.artifact_registry import save_artifact, load_artifact, ArtifactLoadingPolicyError
        import joblib

        model_dir = tmp_path / "ltv" / "v1_candidate"
        model_dir.mkdir(parents=True)
        artifact_file = model_dir / "model.joblib"
        joblib.dump({"stub": True}, artifact_file)

        save_artifact(
            model_id="ltv_prediction",
            artifact_path=artifact_file,
            artifact_version="v1_candidate",
            promotion_state="candidate",
            synthetic_data=False,
        )

        with pytest.raises(ArtifactLoadingPolicyError, match="not allowed"):
            load_artifact(model_dir, env="production")

    def test_threshold_failure_prevents_promotion(self, tmp_path):
        from common.artifact_registry import save_artifact, promote_artifact, ArtifactPromotionError
        import joblib

        model_dir = tmp_path / "intent" / "v1_no_threshold"
        model_dir.mkdir(parents=True)
        artifact_file = model_dir / "model.joblib"
        joblib.dump({"stub": True}, artifact_file)

        save_artifact(
            model_id="intent_prediction",
            artifact_path=artifact_file,
            artifact_version="v1_no_threshold",
            promotion_state="staged",
            synthetic_data=False,
            threshold_passed=False,  # Did not pass thresholds
        )

        with pytest.raises(ArtifactPromotionError, match="threshold"):
            promote_artifact(model_dir, "promoted")


# ---------------------------------------------------------------------------
# Model Governance Metadata Tests
# ---------------------------------------------------------------------------


class TestModelGovernanceMetadata:
    """Every ModelEntry carries governance metadata with safe defaults."""

    GOVERNANCE_FIELDS = (
        "allowed_training_purposes",
        "forbidden_feature_tags",
        "requires_privacy_review",
        "requires_bias_audit",
        "requires_model_card",
        "requires_dataset_card",
        "requires_training_manifest",
        "requires_human_review",
        "requires_dsr_invalidation",
        "production_promotion_allowed",
        "governance_notes",
    )

    def test_every_model_has_governance_fields(self):
        from common.model_registry import list_models
        for entry in list_models():
            for field_name in self.GOVERNANCE_FIELDS:
                assert hasattr(entry, field_name), (
                    f"{entry.model_id} missing governance field '{field_name}'"
                )

    def test_governance_defaults_are_safe(self):
        """Purpose/tag fields are lists; card/promotion flags are bools."""
        from common.model_registry import list_models
        for entry in list_models():
            assert isinstance(entry.allowed_training_purposes, list)
            assert isinstance(entry.forbidden_feature_tags, list)
            assert isinstance(entry.requires_model_card, bool)
            assert isinstance(entry.production_promotion_allowed, bool)

    def test_sensitive_trainable_models_require_privacy_review(self):
        from common.model_registry import get_model
        for model_id in (
            "churn_prediction", "ltv_prediction", "anomaly_detection",
            "bot_detection", "campaign_attribution", "identity_resolution",
        ):
            entry = get_model(model_id)
            assert entry.requires_privacy_review, (
                f"{model_id} should require a privacy review"
            )
            assert entry.requires_model_card
            assert entry.requires_training_manifest

    def test_identity_resolution_governance(self):
        from common.model_registry import get_model
        entry = get_model("identity_resolution")
        assert entry.requires_bias_audit
        assert entry.requires_human_review
        assert entry.requires_dsr_invalidation

    def test_deterministic_models_not_over_restricted(self):
        from common.model_registry import get_model
        for model_id in ("bytecode_risk", "trust_score"):
            entry = get_model(model_id)
            # No trained artifact -> no model card / dataset card / manifest.
            assert not entry.requires_model_card
            assert not entry.requires_dataset_card
            assert not entry.requires_training_manifest
            assert not entry.requires_privacy_review
            # But the omission must be documented.
            assert entry.governance_notes.strip()


# ---------------------------------------------------------------------------
# Feature Policy Metadata Tests
# ---------------------------------------------------------------------------


class TestFeaturePolicyMetadata:
    """FeatureDefinition exposes policy fields that default to a safe posture."""

    def test_feature_policy_fields_default_safely(self):
        from features.registry import FeatureDefinition
        f = FeatureDefinition(name="probe_feature", description="test")
        assert f.data_categories == []
        assert f.required_consent_purposes == []
        assert f.explicit_opt_in_required is False
        assert f.allow_model_training is True
        assert f.allow_inference is True
        assert f.allow_profile360 is True
        assert f.pii_state == "none"
        assert f.retention_class == "standard"
        assert f.policy_version == "1.0"

    def test_sensitive_features_carry_policy(self):
        from features.registry import FeatureRegistry
        import tempfile, os
        reg = FeatureRegistry.create_default_registry(
            registry_path=os.path.join(tempfile.mkdtemp(), "registry.json")
        )
        monetary = next(
            f for f in reg.get_group("identity_features").features
            if f.name == "monetary_value"
        )
        assert monetary.pii_state == "pseudonymous"
        assert "financial" in monetary.data_categories
        assert monetary.required_consent_purposes

        tx = next(
            f for f in reg.get_group("web3_features").features
            if f.name == "tx_count"
        )
        assert tx.pii_state == "pseudonymous"
        assert tx.explicit_opt_in_required is True


# ---------------------------------------------------------------------------
# Promotion Governance Artifact Tests
# ---------------------------------------------------------------------------


class TestPromotionGovernanceArtifacts:
    """promote_artifact enforces the model's required governance artifacts."""

    def _make_real_candidate(self, tmp_path, model_id):
        from common.artifact_registry import save_artifact
        import joblib
        model_dir = tmp_path / model_id / "v1_real"
        model_dir.mkdir(parents=True)
        artifact_file = model_dir / "model.joblib"
        joblib.dump({"stub": True}, artifact_file)
        save_artifact(
            model_id=model_id,
            artifact_path=artifact_file,
            artifact_version="v1_real",
            promotion_state="candidate",
            synthetic_data=False,
            threshold_passed=True,
        )
        return model_dir

    def test_required_promotion_artifacts_from_registry(self):
        from common.artifact_registry import required_promotion_artifacts
        churn = set(required_promotion_artifacts("churn_prediction"))
        assert {"model_card.json", "dataset_card.json",
                "privacy_review.json", "training_manifest.json"} <= churn
        # Deterministic model has no governance artifact requirements.
        assert required_promotion_artifacts("bytecode_risk") == []

    def test_promotion_blocked_when_governance_artifact_missing(self, tmp_path):
        from common.artifact_registry import promote_artifact, ArtifactPromotionError
        model_dir = self._make_real_candidate(tmp_path, "churn_prediction")
        with pytest.raises(ArtifactPromotionError, match="governance artifact"):
            promote_artifact(model_dir, "staged")

    def test_promotion_blocked_when_only_model_card_missing(self, tmp_path):
        from common.artifact_registry import (
            promote_artifact, write_promotion_artifacts, ArtifactPromotionError,
        )
        model_dir = self._make_real_candidate(tmp_path, "churn_prediction")
        write_promotion_artifacts(model_dir, "churn_prediction",
                                  training_manifest={"rows": 10})
        # Remove one required artifact to prove the gate is per-file.
        (model_dir / "model_card.json").unlink()
        with pytest.raises(ArtifactPromotionError, match="model_card.json"):
            promote_artifact(model_dir, "staged")

    def test_promotion_succeeds_when_governance_artifacts_present(self, tmp_path):
        from common.artifact_registry import (
            promote_artifact, write_promotion_artifacts,
        )
        model_dir = self._make_real_candidate(tmp_path, "churn_prediction")
        written = write_promotion_artifacts(model_dir, "churn_prediction",
                                            training_manifest={"rows": 10})
        assert "model_card.json" in written
        staged = promote_artifact(model_dir, "staged")
        assert staged.promotion_state == "staged"
        promoted = promote_artifact(model_dir, "promoted")
        assert promoted.promotion_state == "promoted"
        assert promoted.production_allowed is True

    def test_dataset_manifest_satisfies_training_manifest(self, tmp_path):
        """A dataset_manifest.json (written by train.py) satisfies the gate."""
        import json
        from common.artifact_registry import (
            promote_artifact, write_promotion_artifacts,
        )
        model_dir = self._make_real_candidate(tmp_path, "churn_prediction")
        # Write cards + privacy review but NOT training_manifest.json.
        write_promotion_artifacts(model_dir, "churn_prediction")
        assert not (model_dir / "training_manifest.json").exists()
        # dataset_manifest.json stands in for the training manifest.
        (model_dir / "dataset_manifest.json").write_text(json.dumps({"rows": 5}))
        staged = promote_artifact(model_dir, "staged")
        assert staged.promotion_state == "staged"

    def test_model_without_requirements_promotes_freely(self, tmp_path):
        """Deterministic models have no governance-artifact gate on staging."""
        from common.artifact_registry import save_artifact, promote_artifact
        import joblib
        model_dir = tmp_path / "bytecode_risk" / "v1_real"
        model_dir.mkdir(parents=True)
        artifact_file = model_dir / "model.joblib"
        joblib.dump({"stub": True}, artifact_file)
        save_artifact(
            model_id="bytecode_risk",
            artifact_path=artifact_file,
            artifact_version="v1_real",
            promotion_state="candidate",
            synthetic_data=False,
            threshold_passed=True,
        )
        staged = promote_artifact(model_dir, "staged")
        assert staged.promotion_state == "staged"


class TestServingModelListsDerivedFromRegistry:
    """MODEL_NAMES and MODEL_TYPES in serving/src/api.py must match the registry."""

    def test_serving_model_names_match_registry(self):
        from common.model_registry import list_trainable_models
        from serving.src.api import MODEL_NAMES
        registry_ids = {m.model_id for m in list_trainable_models()}
        serving_ids = set(MODEL_NAMES)
        assert serving_ids == registry_ids, (
            f"Serving MODEL_NAMES {sorted(serving_ids)} != "
            f"registry trainable models {sorted(registry_ids)}"
        )

    def test_serving_model_types_match_registry(self):
        from common.model_registry import list_trainable_models
        from serving.src.api import MODEL_TYPES
        for entry in list_trainable_models():
            assert entry.model_id in MODEL_TYPES, (
                f"{entry.model_id} missing from serving MODEL_TYPES"
            )
            assert MODEL_TYPES[entry.model_id] == entry.tier.value, (
                f"Tier mismatch for {entry.model_id}: "
                f"serving={MODEL_TYPES[entry.model_id]}, registry={entry.tier.value}"
            )

    def test_no_authored_model_names_list_in_serving(self):
        """Serving API must not define MODEL_NAMES as a literal list constant."""
        import ast
        from pathlib import Path
        src = (
            Path(__file__).parent.parent.parent
            / "serving" / "src" / "api.py"
        )
        if not src.exists():
            pytest.skip("serving/src/api.py not found")
        tree = ast.parse(src.read_text())
        # Only check top-level assignments — except-block fallbacks are intentional.
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.List):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "MODEL_NAMES":
                        pytest.fail(
                            "MODEL_NAMES is a literal list in serving/src/api.py. "
                            "It must be derived from common.model_registry."
                        )


class TestModelTypeEnumCompleteness:
    """ModelType enum in common/src/base.py must cover all 11 registry models."""

    def test_model_type_enum_covers_all_registry_models(self):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "common" / "src"))
        from base import ModelType
        from common.model_registry import list_models
        enum_values = {e.value for e in ModelType}
        registry_ids = {m.model_id for m in list_models()}
        missing = registry_ids - enum_values
        assert not missing, (
            f"ModelType enum is missing entries for: {sorted(missing)}. "
            "Add them to common/src/base.py."
        )
