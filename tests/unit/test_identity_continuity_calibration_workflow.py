from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/identity-continuity-gates.yml"


def test_feature_gate_runs_calibration_evaluator_rules_and_cli_contract():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["gate3-merge-safety"]["steps"]
    step = next(
        item for item in steps
        if item.get("name") == "Gate 3 — exercise confidence evaluation evidence rules"
    )
    command = step["run"]

    assert "services/backend/tests/identity/test_confidence_calibration_evaluation.py" in command
    assert "tests/unit/test_identity_continuity_calibration_workflow.py" in command
    assert "scripts/identity_confidence_calibration_evaluation.py --help" in command
    # The feature gate exercises rules with test inputs but never invents a
    # representative dataset or claims production calibration from fixtures.
    assert "--labels" not in command
    assert "representative label data is fabricated" in command


def test_identity_match_score_runtime_calibration_stays_disabled():
    confidence_source = (ROOT / "services/backend/services/identity/confidence.py").read_text(encoding="utf-8")
    assert "CALIBRATED: bool = False" in confidence_source
    assert "identity_match_score" in confidence_source
    assert "not a calibrated probability" in confidence_source


def test_routing_gate_exercises_sdk_identify_trace_and_pii_safe_observability():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["gate2-routing"]["steps"]
    step = next(item for item in steps if item.get("name") == "Gate 2 — exercise import, SDK, and commerce identity routing")
    command = step["run"]

    assert "services/backend/tests/identity/test_sdk_identify_route_resolution.py" in command
    assert "services/backend/tests/identity/test_identity_observability_export.py" in command
    assert "identity.trace" in (ROOT / "services/backend/tests/identity/test_identity_observability_export.py").read_text(encoding="utf-8")


def test_identity_continuity_gate_remains_supplementary_ready_for_review_only():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    triggers = workflow["on"] if "on" in workflow else workflow[True]
    assert triggers["pull_request"]["types"] == ["ready_for_review"]
