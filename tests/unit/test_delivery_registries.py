from pathlib import Path

import yaml

from scripts.validate_delivery_registries import validate_fallback_registry, validate_journey_registry

ROOT = Path(__file__).resolve().parents[2]


def test_committed_fallback_registry_is_fail_closed_and_traceable():
    registry = yaml.safe_load((ROOT / "config/runtime_fallbacks.yaml").read_text())
    assert validate_fallback_registry(registry) == []


def test_fallback_registry_rejects_deployable_allowance_and_missing_implementation(tmp_path):
    registry = {"fallbacks": [{"fallback_id": "unsafe", "owner": "platform", "surfaces": ["queue"],
                               "allowed_profiles": ["staging"], "readiness_effect": "blocking",
                               "implementation_paths": ["missing.py"]}]}
    errors = validate_fallback_registry(registry, tmp_path)
    assert any("allowed in deployable profiles" in error for error in errors)
    assert any("implementation does not exist" in error for error in errors)


def test_committed_golden_journeys_are_honestly_blocked_until_executable():
    registry = yaml.safe_load((ROOT / "config/golden_journeys.yaml").read_text())
    assert validate_journey_registry(registry) == []
    assert {item["implementation_status"] for item in registry["journeys"].values()} == {"BLOCKED"}


def test_golden_journey_registry_rejects_metadata_only_entries(tmp_path):
    registry = {"required_assertion_classes": ["evidence"], "journeys": {
        name: {"owner": "x", "assertions": [], "implementation_status": "IMPLEMENTED"} for name in
        ["tenant_activation", "first_graph", "first_insight", "investigation", "recovery"]
    }}
    errors = validate_journey_registry(registry, tmp_path)
    assert len([error for error in errors if "lacks assertion classes" in error]) == 5
    assert len([error for error in errors if "command must use" in error]) == 5
