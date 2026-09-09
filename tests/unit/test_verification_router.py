import json
from pathlib import Path

import pytest

from scripts.change_plan import validate
from scripts.check_router import route
from scripts.validate_makefile import duplicate_targets
from scripts.lib.test_suites import is_pytest_suite, load_suites
from scripts.lib.verification_router import (
    VerificationRouterConfigError,
    classify_impact,
    load_router_registry,
    validate_router_registry,
)


def test_frontend_change_routes_only_relevant_pr_suites():
    result = route(["frontend/kyber/src/App.tsx"])
    ids = {item["check_id"] for item in result["checks"]}
    assert result["minimum_lane"] == "pr"
    assert result["affected_domains"] == ["frontend"]
    assert "frontend-kyber" in ids
    assert "ml" not in ids
    assert "integration" not in ids


def test_unregistered_path_escalates_to_integration_with_explicit_unknown_domain():
    result = route(["new-runtime-surface/worker.py"])
    assert result["affected_domains"] == ["unknown_component"]
    assert result["minimum_lane"] == "integration"
    assert result["selected_lane"] == "integration"
    assert "integration" in {item["check_id"] for item in result["checks"]}


def test_fast_local_evidence_does_not_replace_required_integration_lane():
    result = route(["deploy/integration/docker-compose.durable.yml"], "fast")
    assert result["selected_lane"] == "fast"
    assert result["minimum_lane"] == "integration"
    assert result["followup_required"] is True


def test_pr_lane_cannot_replace_required_integration_lane():
    with pytest.raises(ValueError, match="below required minimum"):
        route(["deploy/integration/docker-compose.durable.yml"], "pr")


def test_global_change_expands_to_registered_domains():
    result = route(["package-lock.json"])
    assert "backend" in result["affected_domains"]
    assert "sdk" in result["affected_domains"]


def test_change_plan_validator_reports_required_fields():
    errors = validate({"schema_version": 1})
    assert any("missing fields" in error for error in errors)


def test_delivery_contract_schemas_are_json():
    for path in Path("contracts/delivery").glob("*.schema.json"):
        assert json.loads(path.read_text())["type"] == "object"


def test_duplicate_make_targets_are_detected():
    assert duplicate_targets("ok:\n\techo ok\nother:\n\ttrue\n") == []
    assert duplicate_targets("same:\n\ttrue\nsame:\n\tfalse\n") == ["same"]


def test_isolated_file_runner_remains_a_repo_doctor_python_suite():
    root = next(suite for suite in load_suites("config/test_suites.yaml") if suite.id == "root")
    assert is_pytest_suite(root)


def test_router_registry_loads_into_typed_definitions():
    registry = load_router_registry("config/verification_router.yaml")
    assert registry.default_lane == "pr"
    assert registry.checks["toolchain"].runtime_budget_seconds == 15
    assert registry.domains["infrastructure"].minimum_lane == "integration"


def test_router_registry_rejects_unknown_keys_and_unresolved_checks():
    raw = {
        "schema_version": 1,
        "default_lane": "pr",
        "lanes": {lane: ["toolchain"] for lane in ("fast", "pr", "integration", "regression", "release")},
        "checks": {
            "toolchain": {
                "owner": "platform",
                "risk": "critical",
                "command": ["python", "scripts/validate_toolchain.py"],
                "runtime_budget_seconds": 15,
            }
        },
        "domains": {
            "delivery": {
                "owner": "platform",
                "paths": ["scripts/**"],
                "checks": ["missing-suite"],
                "minimum_lane": "fast",
            }
        },
        "global_paths": ["package.json"],
        "unexpected": True,
    }
    with pytest.raises(VerificationRouterConfigError, match="unknown key"):
        validate_router_registry(raw, known_check_ids=set())

    raw.pop("unexpected")
    with pytest.raises(VerificationRouterConfigError, match="unknown check"):
        validate_router_registry(raw, known_check_ids=set())


def test_classify_impact_is_deterministic_and_preserves_fast_followup():
    registry = load_router_registry("config/verification_router.yaml")
    impact = classify_impact(
        ["deploy/integration/docker-compose.durable.yml", "deploy/integration/docker-compose.durable.yml"],
        registry,
        "fast",
    )
    assert impact.changed_files == ("deploy/integration/docker-compose.durable.yml",)
    assert impact.affected_domains == ("infrastructure",)
    assert impact.minimum_lane == "integration"
    assert impact.selected_lane == "fast"
    assert impact.followup_required is True
    assert "delivery_metadata" in impact.selected_checks
    assert "integration" not in impact.selected_checks


def test_route_exposes_inventory_impact_without_narrowing_suite_commands():
    result = route(["scripts/check_router.py"])
    assert result["impact"]["global_change"] is False
    assert result["impact"]["affected_tests"]
    assert {item["check_id"] for item in result["checks"]} >= {"toolchain", "test_inventory"}
