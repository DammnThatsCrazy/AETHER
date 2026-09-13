#!/usr/bin/env python3
"""Validate a classified execution plan and expose its worker matrix.

This command consumes the plan produced by the existing Impact Graph-backed
planner.  It never selects suites itself and therefore cannot become a second
selection authority.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import jsonschema

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.test_suites import load_dependency_profiles, load_suites  # noqa: E402
from scripts.lib.verification_router import load_router_registry  # noqa: E402


class ExecutionPlanValidationError(ValueError):
    """The plan is not safe to hand to hosted workers."""


def load_plan(path: Path) -> dict[str, Any]:
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
        schema = json.loads((ROOT / "contracts/delivery/verification-execution-plan.schema.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(plan)
    except (OSError, json.JSONDecodeError, jsonschema.ValidationError) as exc:
        raise ExecutionPlanValidationError(str(exc)) from exc
    if plan.get("status") != "READY":
        raise ExecutionPlanValidationError("execution plan is not READY")
    return plan


def validate_plan(plan: dict[str, Any]) -> list[dict[str, Any]]:
    suites = {suite.id: suite for suite in load_suites(ROOT / "config/test_suites.yaml")}
    profiles = load_dependency_profiles(ROOT)
    router = load_router_registry(ROOT / "config/verification_router.yaml")
    known_checks = set(suites) | set(router.checks)
    selected_checks = set(plan.get("selected_checks", []))
    unknown_selected = sorted(selected_checks - known_checks)
    if unknown_selected:
        raise ExecutionPlanValidationError(
            "plan selects unknown check(s): " + ", ".join(unknown_selected)
        )
    planned_checks: set[str] = set()
    for job in plan.get("jobs", []):
        unknown_job_checks = sorted(set(job.get("checks", [])) - known_checks)
        if unknown_job_checks:
            raise ExecutionPlanValidationError(
                f"worker {job['id']!r} selects unknown check(s): " + ", ".join(unknown_job_checks)
            )
        planned_checks.update(job.get("checks", []))
    skipped_checks = {str(item.get("suite")) for item in plan.get("skipped", [])}
    if not skipped_checks <= selected_checks:
        raise ExecutionPlanValidationError(
            "plan skips checks that were not selected: " + ", ".join(sorted(skipped_checks - selected_checks))
        )
    if planned_checks | skipped_checks != selected_checks:
        raise ExecutionPlanValidationError(
            "execution jobs do not cover selected checks: "
            f"missing={sorted(selected_checks - planned_checks - skipped_checks)}, "
            f"extra={sorted(planned_checks - selected_checks)}"
        )
    matrix = plan.get("suite_matrix", [])
    seen: set[str] = set()
    for worker in matrix:
        profile_id = worker["dependency_profile"]
        profile = profiles.get(profile_id)
        if profile is None:
            raise ExecutionPlanValidationError(f"worker {worker['id']!r} has unknown profile {profile_id!r}")
        expected_python = bool(profile.get("python_extra")) and profile_id != "ci-control"
        if (
            bool(profile.get("node")) != worker["node_required"]
            or bool(profile.get("docker")) != worker["docker_required"]
            or expected_python != worker["python_required"]
        ):
            raise ExecutionPlanValidationError(f"worker {worker['id']!r} disagrees with profile {profile_id!r}")
        if profile.get("python_extra") != worker["python_extra"]:
            raise ExecutionPlanValidationError(f"worker {worker['id']!r} has an incorrect Python profile")
        for suite_id in worker["suite_ids"]:
            if suite_id in seen:
                raise ExecutionPlanValidationError(f"suite {suite_id!r} appears in multiple worker entries")
            seen.add(suite_id)
            suite = suites.get(suite_id)
            if suite is None:
                raise ExecutionPlanValidationError(f"worker references unknown suite {suite_id!r}")
            if suite.dependency_profile != profile_id or suite.runtime_class != worker["runtime_class"]:
                raise ExecutionPlanValidationError(f"worker metadata disagrees with suite {suite_id!r}")
    skipped = {row["suite"] for row in plan.get("skipped", [])}
    expected = set(plan.get("selected_checks", [])) & set(suites)
    if seen | skipped != expected:
        raise ExecutionPlanValidationError(
            f"worker matrix does not cover selected suites: missing={sorted(expected - seen - skipped)}"
        )
    return matrix


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--matrix-output", type=Path)
    args = parser.parse_args(argv)
    try:
        plan = load_plan(args.plan)
        matrix = validate_plan(plan)
    except (ExecutionPlanValidationError, OSError, ValueError) as exc:
        print(json.dumps({"schema_version": 1, "status": "BLOCKED", "reason": str(exc)}, indent=2))
        return 2
    if args.matrix_output:
        args.matrix_output.parent.mkdir(parents=True, exist_ok=True)
        args.matrix_output.write_text(json.dumps(matrix, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps({"schema_version": 1, "status": "PASS", "suite_count": sum(len(item["suite_ids"]) for item in matrix), "worker_count": len(matrix)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
