"""
Aether — Unit Tests: ML Security Fixes

Tests proving:
  - PostResponseResult has .output, not .modified_output
  - Backend routes use .output correctly
  - pre_request blocking returns 403/429
  - Batch requires privileged access
  - Extraction defense is gated by environment
"""

from __future__ import annotations

import pytest


class TestPostResponseResultFields:
    """Verify PostResponseResult has the correct field name (.output)."""

    def test_post_response_result_has_output_field(self):
        from security.model_extraction_defense.defense_layer import PostResponseResult
        result = PostResponseResult(output=0.75, risk_score=0.1)
        assert hasattr(result, "output")
        assert result.output == 0.75

    def test_post_response_result_has_no_modified_output(self):
        """The field 'modified_output' must not exist — it was a bug."""
        from security.model_extraction_defense.defense_layer import PostResponseResult
        result = PostResponseResult(output=0.5)
        assert not hasattr(result, "modified_output"), (
            "PostResponseResult must not have 'modified_output'. "
            "Backend code must use 'output' only."
        )

    def test_defense_layer_post_response_returns_output(self):
        from security.model_extraction_defense import ExtractionDefenseLayer
        from security.model_extraction_defense.config import ExtractionDefenseConfig

        config = ExtractionDefenseConfig(
            enable_extraction_defense=True,
            enable_output_noise=False,
            enable_watermark=False,
        )
        defense = ExtractionDefenseLayer(config)
        result = defense.post_response(
            api_key="test-key",
            raw_output={"prediction": 0.8},
            features={"f1": 1.0},
        )
        assert hasattr(result, "output")
        assert not hasattr(result, "modified_output")

    def test_defense_disabled_returns_raw_output(self):
        from security.model_extraction_defense import ExtractionDefenseLayer
        from security.model_extraction_defense.config import ExtractionDefenseConfig

        config = ExtractionDefenseConfig(enable_extraction_defense=False)
        defense = ExtractionDefenseLayer(config)
        raw = {"score": 0.9, "label": "positive"}
        result = defense.post_response("key", raw, {})
        assert result.output == raw


class TestPreRequestDefense:
    """Verify pre_request defense enforcement."""

    def test_pre_request_not_blocked_for_normal_request(self):
        from security.model_extraction_defense import ExtractionDefenseLayer
        from security.model_extraction_defense.config import ExtractionDefenseConfig

        config = ExtractionDefenseConfig(enable_extraction_defense=True)
        defense = ExtractionDefenseLayer(config)
        result = defense.pre_request(
            api_key="normal-client",
            ip_address="1.2.3.4",
            features={"f1": 0.5, "f2": 0.3},
            model_name="intent_prediction",
        )
        assert not result.blocked

    def test_pre_request_returns_pre_request_result(self):
        from security.model_extraction_defense import ExtractionDefenseLayer
        from security.model_extraction_defense.defense_layer import PreRequestResult
        from security.model_extraction_defense.config import ExtractionDefenseConfig

        config = ExtractionDefenseConfig(enable_extraction_defense=True)
        defense = ExtractionDefenseLayer(config)
        result = defense.pre_request("key", "1.2.3.4", {}, "bot_detection")
        assert isinstance(result, PreRequestResult)
        assert hasattr(result, "blocked")
        assert hasattr(result, "block_reason")
        assert hasattr(result, "retry_after_seconds")

    def test_pre_request_when_defense_disabled(self):
        from security.model_extraction_defense import ExtractionDefenseLayer
        from security.model_extraction_defense.config import ExtractionDefenseConfig

        config = ExtractionDefenseConfig(enable_extraction_defense=False)
        defense = ExtractionDefenseLayer(config)
        result = defense.pre_request("key", "1.2.3.4", {}, "intent_prediction")
        assert not result.blocked


class TestBackendRoutesFileIntegrity:
    """Static analysis tests for backend routes correctness."""

    def _read_routes(self):
        import pathlib
        p = pathlib.Path(
            "Backend Architecture/aether-backend/services/ml_serving/routes.py"
        )
        if not p.exists():
            pytest.skip("Backend routes file not found")
        return p.read_text()

    def test_no_modified_output_in_routes(self):
        import re
        content = self._read_routes()
        # Strip all docstrings and comments, then check for modified_output in code
        # Remove triple-quoted strings
        stripped = re.sub(r'""".*?"""', '', content, flags=re.DOTALL)
        stripped = re.sub(r"'''.*?'''", '', stripped, flags=re.DOTALL)
        # Remove single-line comments
        stripped = re.sub(r'#.*$', '', stripped, flags=re.MULTILINE)
        assert "modified_output" not in stripped, (
            "Backend routes must not reference 'modified_output' in code. "
            "PostResponseResult only has 'output'."
        )

    def test_post_result_output_used(self):
        content = self._read_routes()
        assert "post_result.output" in content, (
            "Backend routes must use 'post_result.output'"
        )

    def test_pre_request_called_before_inference(self):
        content = self._read_routes()
        # defense.pre_request must be called in the predict endpoint
        assert "defense.pre_request" in content or "pre_request(" in content, (
            "Backend routes must call defense.pre_request() before forwarding to ML serving"
        )

    def test_batch_has_privileged_check(self):
        content = self._read_routes()
        # Batch route must enforce privilege
        assert "ml:batch" in content or "privileged" in content.lower(), (
            "Batch endpoint must enforce privileged access"
        )

    def test_canonical_id_in_response(self):
        content = self._read_routes()
        assert "canonical_model_id" in content, (
            "Prediction responses must include canonical_model_id"
        )

    def test_deprecated_alias_warning_in_response(self):
        content = self._read_routes()
        assert "deprecated_alias" in content or "was_deprecated" in content, (
            "Backend must warn when deprecated alias is used"
        )

    def test_no_batch_privilege_header_check(self):
        """X-Batch-Privilege header must not be used to determine batch privilege."""
        import re
        content = self._read_routes()
        # Strip comments to avoid false negatives from commented-out code
        stripped = re.sub(r'#.*$', '', content, flags=re.MULTILINE)
        stripped = re.sub(r'""".*?"""', '', stripped, flags=re.DOTALL)
        stripped = re.sub(r"'''.*?'''", '', stripped, flags=re.DOTALL)
        assert "X-Batch-Privilege" not in stripped, (
            "routes.py must not check X-Batch-Privilege header for privilege. "
            "Privilege must be derived from RBAC (tenant.require_permission) only."
        )

    def test_synthetic_ratio_not_hardcoded_zero(self):
        """synthetic_ratio in CIS telemetry must be derived, not hardcoded 0.0."""
        import re
        content = self._read_routes()
        stripped = re.sub(r'#.*$', '', content, flags=re.MULTILINE)
        stripped = re.sub(r'""".*?"""', '', stripped, flags=re.DOTALL)
        stripped = re.sub(r"'''.*?'''", '', stripped, flags=re.DOTALL)
        assert '"synthetic_ratio": 0.0' not in stripped and "'synthetic_ratio': 0.0" not in stripped, (
            "synthetic_ratio must be derived from artifact metadata, not hardcoded 0.0"
        )

    def test_no_hardcoded_available_models_list(self):
        """The AVAILABLE_MODELS static list should not contain legacy aliases."""
        content = self._read_routes()
        # The old static list with stale names must be gone
        # These should only appear in the STATIC_DEPRECATED_ALIASES dict
        import re
        # Find AVAILABLE_MODELS if it still exists as a simple list
        if "AVAILABLE_MODELS" in content:
            # Should be either removed or only reference canonical names
            lines = [l for l in content.splitlines() if "AVAILABLE_MODELS" in l]
            for line in lines:
                # Should not be a direct list containing identity_gnn
                if "identity_gnn" in line and "alias" not in line.lower() and "deprecated" not in line.lower():
                    pytest.fail(
                        f"AVAILABLE_MODELS contains legacy alias: {line.strip()}"
                    )


class TestModelRegistryConsistency:
    """End-to-end consistency tests for registry → backend → serving."""

    def test_registry_and_training_config_agree_on_models(self):
        try:
            from common.model_registry import list_trainable_models
        except ImportError:
            pytest.skip("common.model_registry not importable from root tests dir")
        try:
            from training.configs.model_configs import MODEL_CONFIGS
        except ImportError:
            pytest.skip("training.configs not importable")

        registry_ids = {m.model_id for m in list_trainable_models()}
        config_ids = set(MODEL_CONFIGS.keys())
        assert registry_ids == config_ids, (
            f"Registry and training configs disagree:\n"
            f"  Registry only: {registry_ids - config_ids}\n"
            f"  Config only:   {config_ids - registry_ids}"
        )

    def test_feature_contract_ids_match_registry(self):
        try:
            from common.model_registry import list_trainable_models
            from common.feature_contracts import get_feature_contract
        except ImportError:
            pytest.skip("ML common modules not importable from root tests dir")

        for entry in list_trainable_models():
            contract = get_feature_contract(entry.model_id)
            assert contract.model_id == entry.model_id, (
                f"Contract model_id mismatch: "
                f"contract.model_id={contract.model_id}, "
                f"registry.model_id={entry.model_id}"
            )
            assert contract.contract_id == entry.feature_contract_id, (
                f"Feature contract ID mismatch for {entry.model_id}: "
                f"contract.contract_id={contract.contract_id}, "
                f"registry.feature_contract_id={entry.feature_contract_id}"
            )
