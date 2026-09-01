import json
from pathlib import Path

import pytest

from scripts.change_plan import validate
from scripts.check_router import route
from scripts.validate_makefile import duplicate_targets
from scripts.lib.test_suites import is_pytest_suite, load_suites


def test_frontend_change_routes_only_relevant_pr_suites():
    result = route(["frontend/kyber/src/App.tsx"])
    ids = {item["check_id"] for item in result["checks"]}
    assert result["minimum_lane"] == "pr"
    assert result["affected_domains"] == ["frontend"]
    assert "frontend-kyber" in ids
    assert "ml" not in ids
    assert "integration" not in ids


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
