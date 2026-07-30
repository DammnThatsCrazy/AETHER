"""Tests for scripts/validate_model_consent_purposes.py.

The validator gates every model's ``allowed_training_purposes`` /
``required_inference_purposes`` and every feature contract's
``required_purposes`` against the canonical consent registry, and rejects
empty purpose scopes (fail closed).

Positive case runs the real script as a subprocess against the repo state.
Negative cases exercise the validator's pure ``collect_errors`` core with
mutated copies of real entries, so no repo files are touched.
"""
from __future__ import annotations

import dataclasses
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = REPO_ROOT / "scripts" / "validate_model_consent_purposes.py"


@pytest.fixture(scope="module")
def validator():
    """The validator script imported as a module (for its pure core)."""
    spec = importlib.util.spec_from_file_location(
        "validate_model_consent_purposes", VALIDATOR
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def registry_keys(validator):
    return validator.load_registry_keys()


def test_validator_exits_zero_on_current_repo_state():
    result = subprocess.run(
        [sys.executable, str(VALIDATOR)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"validator failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "OK" in result.stdout


def test_bogus_purpose_on_model_is_rejected_naming_model_and_key(
    validator, registry_keys
):
    from common.model_registry import get_model

    entry = get_model("bot_detection")
    mutated = dataclasses.replace(
        entry, allowed_training_purposes=["not_a_real_purpose"]
    )

    errors = validator.collect_errors([mutated], [], registry_keys)

    assert len(errors) == 1
    assert "bot_detection" in errors[0]
    assert "not_a_real_purpose" in errors[0]
    assert "allowed_training_purposes" in errors[0]


def test_empty_purpose_list_on_model_is_rejected(validator, registry_keys):
    from common.model_registry import get_model

    entry = get_model("churn_prediction")
    mutated = dataclasses.replace(entry, required_inference_purposes=[])

    errors = validator.collect_errors([mutated], [], registry_keys)

    assert len(errors) == 1
    assert "churn_prediction" in errors[0]
    assert "required_inference_purposes" in errors[0]
    assert "empty" in errors[0]


def test_bogus_purpose_on_feature_contract_is_rejected(validator, registry_keys):
    from common.feature_contracts import get_feature_contract

    contract = get_feature_contract("session_scorer")
    mutated = dataclasses.replace(
        contract, required_purposes=["analytics", "bogus_feature_purpose"]
    )

    errors = validator.collect_errors([], [mutated], registry_keys)

    assert len(errors) == 1
    assert "session_scorer_v1" in errors[0]
    assert "bogus_feature_purpose" in errors[0]


def test_empty_purpose_list_on_feature_contract_is_rejected(
    validator, registry_keys
):
    from common.feature_contracts import get_feature_contract

    contract = get_feature_contract("trust_score")
    mutated = dataclasses.replace(contract, required_purposes=[])

    errors = validator.collect_errors([], [mutated], registry_keys)

    assert len(errors) == 1
    assert "trust_score_v1" in errors[0]
    assert "empty" in errors[0]


def test_current_registry_state_is_clean_in_process(validator, registry_keys):
    """The real registry + contracts produce zero errors via the pure core."""
    from common.feature_contracts import list_feature_contracts
    from common.model_registry import list_models

    assert validator.collect_errors(
        list_models(), list_feature_contracts(), registry_keys
    ) == []
