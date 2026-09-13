from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.aggregate_verification_evidence import main as aggregate_main
from scripts.lib.ci_performance import build_performance_evidence, load_policy
from scripts.validate_execution_plan import ExecutionPlanValidationError, validate_plan
from scripts.verification_disposition import _apply_evidence


def _plan(**overrides: object) -> dict:
    plan = {
        "schema_version": 1,
        "status": "READY",
        "risk": "R0",
        "lane": "pr",
        "global_scopes": [],
        "selected_components": ["application-runtime"],
        "selected_component_count": 1,
        "selected_suite_count": 1,
        "build": {"node_required": False, "backend_image": False},
        "selected_checks": ["backend-profile360"],
        "skipped": [],
        "jobs": [],
        "suite_matrix": [],
        "performance_policy": "config/ci_performance_policy.yaml",
    }
    plan.update(overrides)
    return plan


def test_critical_path_uses_parallel_slowest_stage_and_withholds_claims() -> None:
    policy = load_policy()
    evidence = build_performance_evidence(
        _plan(),
        [
            {"job": "universal-fast", "stage": "universal_fast", "total_job_seconds": 10},
            {"job": "backend", "stage": "suite_worker", "total_job_seconds": 30},
            {"job": "node-build", "stage": "build", "total_job_seconds": 20},
        ],
        policy=policy,
        stage_seconds={
            "classifier_seconds": 5,
            "candidate_verification_seconds": 3,
            "disposition_seconds": 2,
        },
    )

    assert evidence["critical_path_seconds"] == 40.0
    assert evidence["total_authority_seconds"] == 70.0
    assert evidence["universal_fast_seconds"] == 10.0
    assert evidence["test_critical_path_seconds"] == 30.0
    assert evidence["build_critical_path_seconds"] == 20.0
    assert evidence["performance_status"] == "INSUFFICIENT_SAMPLES"
    assert evidence["claims_allowed"] is False
    assert evidence["sample_threshold"] == 20


def test_performance_breach_is_visible_without_initially_blocking_merge() -> None:
    evidence = build_performance_evidence(
        _plan(risk="R5", global_scopes=["verification_control_plane"]),
        [{"job": "slow-control", "stage": "suite_worker", "total_job_seconds": 901}],
        stage_seconds={"classifier_seconds": 0, "candidate_verification_seconds": 0, "disposition_seconds": 0},
    )

    assert evidence["pr_class"] == "architecture"
    assert evidence["performance_status"] == "CI_PERFORMANCE_DEGRADED"
    assert evidence["degraded_non_blocking"] is True
    assert evidence["claims_allowed"] is False


def test_aggregation_blocks_when_a_selected_suite_artifact_is_missing(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    evidence_dir = tmp_path / "evidence"
    output_path = tmp_path / "aggregation.json"
    evidence_dir.mkdir()
    plan_path.write_text(
        json.dumps(
            _plan(
                selected_checks=["suite-a"],
                suite_matrix=[
                    {
                        "id": "suite-suite-a",
                        "suite_ids": ["suite-a"],
                        "dependency_profile": "python-root",
                        "runtime_class": "medium",
                        "worker_class": "isolated",
                        "blocking": True,
                    }
                ],
            )
        ),
        encoding="utf-8",
    )

    result = aggregate_main(
        [
            "--plan",
            str(plan_path),
            "--evidence-dir",
            str(evidence_dir),
            "--output",
            str(output_path),
        ]
    )

    assert result == 1
    aggregation = json.loads(output_path.read_text(encoding="utf-8"))
    assert aggregation["status"] == "BLOCKED"
    assert aggregation["missing_blocking_suites"] == ["suite-a"]


def test_aggregation_blocks_when_a_planned_control_artifact_is_missing(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    evidence_dir = tmp_path / "evidence"
    output_path = tmp_path / "aggregation.json"
    evidence_dir.mkdir()
    plan_path.write_text(
        json.dumps(_plan(jobs=[{"id": "control-prerequisites"}], suite_matrix=[])),
        encoding="utf-8",
    )

    result = aggregate_main(
        [
            "--plan",
            str(plan_path),
            "--evidence-dir",
            str(evidence_dir),
            "--output",
            str(output_path),
        ]
    )

    assert result == 1
    assert json.loads(output_path.read_text(encoding="utf-8"))["status"] == "BLOCKED"


def test_disposition_does_not_require_lane_skipped_aggregate_evidence(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    evidence_path = tmp_path / "aggregation.json"
    plan_path.write_text(
        json.dumps(
            _plan(
                selected_checks=["backend", "backend-profile360"],
                skipped=[{"suite": "backend", "reason": "profile_not_declared:ci"}],
            )
        ),
        encoding="utf-8",
    )
    evidence_path.write_text(
        json.dumps(
            {
                "status": "PASS",
                "universal_fast": {"universal": {"checks": []}},
                "suite_results": [{"suite": "backend-profile360", "status": "PASS"}],
                "performance": {},
            }
        ),
        encoding="utf-8",
    )

    result = _apply_evidence(
        {"checks": [{"check_id": "backend"}, {"check_id": "backend-profile360"}], "timing": {}},
        evidence_path,
        plan_path,
        None,
    )

    assert result["status"] == "PASS"
    assert result["distributed_evidence"]["missing_checks"] == []


def test_execution_plan_rejects_unknown_dependency_profile() -> None:
    plan = _plan(
        selected_checks=[],
        suite_matrix=[
            {
                "id": "suite-unknown",
                "suite_ids": ["backend-profile360"],
                "dependency_profile": "missing-profile",
                "runtime_class": "medium",
                "worker_class": "isolated",
                "blocking": True,
                "node_required": False,
                "python_required": True,
                "python_extra": "dev",
                "docker_required": False,
            }
        ],
    )

    with pytest.raises(ExecutionPlanValidationError, match="unknown profile"):
        validate_plan(plan)
