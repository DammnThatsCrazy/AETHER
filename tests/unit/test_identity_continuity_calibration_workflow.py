"""Identity continuity: calibration stays disabled and the V2 check keeps the gate commands.

The standalone identity-continuity-gates workflow was retired in the CI V2
cutover; its unique gates run as check `identity-continuity` in
config/ci/ownership.yaml, and its remaining tests are registry suites.
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _check(check_id: str) -> dict:
    rules = yaml.safe_load((ROOT / "config/ci/ownership.yaml").read_text(encoding="utf-8"))
    return next(c for c in rules["checks"] if c["id"] == check_id)


def test_v2_check_runs_calibration_evaluator_rules_and_cli_contract():
    commands = "\n".join(_check("identity-continuity")["run"])
    assert "tests/unit/test_identity_continuity_calibration_workflow.py" in commands
    assert "scripts/identity_confidence_calibration_evaluation.py --help" in commands
    # The gate exercises rules with test inputs but never invents a
    # representative dataset or claims production calibration from fixtures.
    assert "--labels" not in commands


def test_identity_match_score_runtime_calibration_stays_disabled():
    confidence_source = (ROOT / "services/api/identity/identity/confidence.py").read_text(encoding="utf-8")
    assert "CALIBRATED: bool = False" in confidence_source
    assert "identity_match_score" in confidence_source
    assert "not a calibrated probability" in confidence_source


def test_routing_and_calibration_tests_are_in_a_pr_lane_suite():
    suites = yaml.safe_load((ROOT / "config/test_suites.yaml").read_text(encoding="utf-8"))["suites"]
    identity = next(s for s in suites if s["id"] == "backend-identity")
    assert identity["lane"] == "pr"
    assert any("services/api/tests/identity" in p for p in identity["paths"])
    for name in ("test_sdk_identify_route_resolution.py", "test_identity_observability_export.py",
                 "test_confidence_calibration_evaluation.py"):
        assert (ROOT / "services/api/tests/identity" / name).is_file()
    assert "identity.trace" in (
        ROOT / "services/api/tests/identity/test_identity_observability_export.py"
    ).read_text(encoding="utf-8")


def test_identity_check_is_path_selected_by_the_identity_surface():
    include = " ".join(_check("identity-continuity")["include"])
    assert "services/api/identity" in include and "packages/shared/contracts/identity" in include
