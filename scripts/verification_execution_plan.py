#!/usr/bin/env python3
"""Build the canonical dependency-aware execution plan for a change.

This command is planning-only.  It consumes the existing Impact Graph and
verification router and emits one deterministic contract for hosted workers.
It never narrows an unresolved change: unresolved paths produce ``BLOCKED``.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.impact_graph import (  # noqa: E402
    ImpactGraphConfigError,
    build_impact_index,
    load_impact_graph,
)
from scripts.lib.test_suites import (  # noqa: E402
    RUNTIME_CLASSES,
    TestSuite,
    load_dependency_profiles,
    load_suites,
)
from scripts.lib.verification_router import (  # noqa: E402
    LANE_ORDER,
    load_router_registry,
)


class ExecutionPlanError(ValueError):
    """The plan cannot be produced without weakening selection."""


def _changed_files(base: str | None, explicit: Sequence[str]) -> list[str]:
    if explicit:
        return sorted(set(explicit))
    process = subprocess.run(
        ["git", "diff", "--name-only", base or "HEAD", "--"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if process.returncode:
        raise ExecutionPlanError(process.stderr.strip() or "changed-file discovery failed")
    return sorted(line for line in process.stdout.splitlines() if line)


def _worker_class(runtime_class: str) -> str:
    return "pooled" if runtime_class in {"tiny", "small"} else "isolated"


_LANE_RANK = {lane: rank for rank, lane in enumerate(LANE_ORDER)}
_RISK_RANK = {f"R{index}": index for index in range(6)}


def _risk(*, lane: str, global_scopes: Sequence[str]) -> str:
    """Classify change risk, not the intrinsic severity of universal checks.

    Universal controls deliberately include critical validators on every plan.
    Letting those check labels define the PR risk would classify every ordinary
    frontend or backend change as architecture work and would make the latency
    policy meaningless. The lane remains the change-impact authority; typed
    control-plane scope escalation is the one explicit cross-cutting override.
    """
    bands = {"fast": "R0", "pr": "R2", "integration": "R3", "regression": "R4", "release": "R5"}
    risk = bands[lane]
    if "verification_control_plane" in set(global_scopes):
        risk = "R4"
    return risk


def _suite_skip_reason(suite: TestSuite, *, lane: str) -> str | None:
    """Mirror the disposition lane/profile skip policy without executing it."""
    if suite.skip_policy == "documented_quarantine":
        return "documented_quarantine"
    if "ci" not in suite.profiles:
        return "profile_not_declared:ci"
    if "ci" not in suite.environments:
        return "environment_not_declared:ci"
    if suite.lane == "release" and lane != "release":
        return "release_lane_only"
    if _LANE_RANK[suite.lane] > _LANE_RANK[lane]:
        return f"suite_lane_exceeds_selected_lane:{suite.lane}"
    return None


def _job(
    job_id: str,
    *,
    dependency_profile: str,
    runtime_class: str,
    checks: Sequence[str],
    suite_ids: Sequence[str] = (),
    blocking: bool = True,
) -> dict[str, Any]:
    if runtime_class not in RUNTIME_CLASSES:
        raise ExecutionPlanError(f"unknown runtime class {runtime_class!r}")
    return {
        "id": job_id,
        "worker_class": _worker_class(runtime_class),
        "dependency_profile": dependency_profile,
        "runtime_class": runtime_class,
        "checks": sorted(set(checks)),
        "suite_ids": sorted(set(suite_ids)),
        "blocking": blocking,
    }


def build_execution_plan(changed_files: Sequence[str], requested_lane: str | None = None) -> dict[str, Any]:
    router = load_router_registry(ROOT / "config/verification_router.yaml")
    suites = load_suites(ROOT / "config/test_suites.yaml")
    profiles = load_dependency_profiles(ROOT)
    suite_by_id = {suite.id: suite for suite in suites}
    graph = load_impact_graph(router=router, suites=suites)
    index = build_impact_index(
        changed_files,
        graph,
        requested_lane=requested_lane,
        router=router,
    )
    lane = index["router"]["selected_lane"]
    scopes = index["router"].get("global_scopes", [])
    if index["unresolved_paths"]:
        return {
            "schema_version": 1,
            "status": "BLOCKED",
            "reason": "unresolved executable or delivery paths",
            "risk": "R5",
            "lane": lane,
            "domains": list(index["router"]["affected_domains"]),
            "global_scopes": scopes,
            "jobs": [],
            "suite_matrix": [],
            "build": index["build_selection"],
            "performance_policy": "config/ci_performance_policy.yaml",
            "selected_suite_count": 0,
            "runnable_suite_count": 0,
            "selected_component_count": len(index["impacted_components"]),
            "selected_components": list(index["impacted_components"]),
            "skipped": [],
            "unresolved_paths": index["unresolved_paths"],
        }

    # Universal-fast is an invariant of every READY ordinary/integration plan,
    # not a property inherited from whichever lane happened to classify the
    # changed file. Keeping it in this same selected-check set means the
    # validator and the final disposition can prove that it actually ran.
    universal_checks = set(router.lanes["fast"])
    selected_checks = set(index["router"]["selected_checks"]) | universal_checks
    jobs: list[dict[str, Any]] = []
    if universal_checks:
        jobs.append(
            _job(
                "universal-fast",
                dependency_profile="ci-control",
                runtime_class="tiny",
                checks=universal_checks,
            )
        )

    selected_suite_ids = sorted(selected_checks & set(suite_by_id))
    other_checks = sorted(selected_checks - set(selected_suite_ids) - universal_checks)
    if other_checks:
        raise ExecutionPlanError(
            "selected checks lack a dependency-aware suite execution contract: "
            + ", ".join(other_checks)
        )

    pooled: dict[tuple[str, str], list[TestSuite]] = {}
    skipped: list[dict[str, str]] = []
    for suite_id in selected_suite_ids:
        suite = suite_by_id[suite_id]
        skip_reason = _suite_skip_reason(suite, lane=lane)
        if skip_reason is not None:
            skipped.append({"suite": suite.id, "reason": skip_reason})
            continue
        key = (suite.dependency_profile, suite.runtime_class)
        if _worker_class(suite.runtime_class) == "pooled":
            pooled.setdefault(key, []).append(suite)
        else:
            jobs.append(
                _job(
                    f"suite-{suite.id}",
                    dependency_profile=suite.dependency_profile,
                    runtime_class=suite.runtime_class,
                    checks=[suite.id],
                    suite_ids=[suite.id],
                    blocking=suite.release_class != "advisory",
                )
            )
    for (profile, runtime_class), grouped in sorted(pooled.items()):
        jobs.append(
            _job(
                "suite-pool-" + profile.replace("_", "-"),
                dependency_profile=profile,
                runtime_class=runtime_class,
                checks=[suite.id for suite in grouped],
                suite_ids=[suite.id for suite in grouped],
                blocking=any(suite.release_class != "advisory" for suite in grouped),
            )
        )

    suite_matrix: list[dict[str, Any]] = []
    for job in jobs:
        suite_ids = job.get("suite_ids", [])
        if not suite_ids:
            continue
        profile = profiles.get(job["dependency_profile"])
        if profile is None:
            raise ExecutionPlanError(
                f"suite job {job['id']!r} references unknown dependency profile "
                f"{job['dependency_profile']!r}"
            )
        suite_matrix.append(
            {
                "id": job["id"],
                "suite_ids": suite_ids,
                "dependency_profile": job["dependency_profile"],
                "runtime_class": job["runtime_class"],
                "worker_class": job["worker_class"],
                "blocking": job["blocking"],
                "node_required": bool(profile.get("node")),
                # bootstrap-ci-control already provides this exact profile
                # with --no-deps. Reinstalling the editable project here would
                # pull its application runtime dependencies back into the
                # minimal control worker.
                "python_required": bool(profile.get("python_extra")) and job["dependency_profile"] != "ci-control",
                "python_extra": profile.get("python_extra"),
                "docker_required": bool(profile.get("docker")),
            }
        )

    return {
        "schema_version": 1,
        "status": "READY",
        "risk": _risk(lane=lane, global_scopes=scopes),
        "lane": lane,
        "domains": list(index["router"]["affected_domains"]),
        "global_scopes": scopes,
        "jobs": sorted(jobs, key=lambda job: job["id"]),
        "suite_matrix": sorted(suite_matrix, key=lambda job: job["id"]),
        "build": index["build_selection"],
        "performance_policy": "config/ci_performance_policy.yaml",
        "selected_suite_count": len(selected_suite_ids),
        "runnable_suite_count": sum(
            1 for suite_id in selected_suite_ids if not any(row["suite"] == suite_id for row in skipped)
        ),
        "selected_component_count": len(index["impacted_components"]),
        "selected_components": list(index["impacted_components"]),
        "skipped": skipped,
        "selected_checks": sorted(selected_checks),
        "changed_files": list(index["changed_files"]),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="git revision used for changed-path discovery")
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--lane", choices=LANE_ORDER)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        plan = build_execution_plan(_changed_files(args.base, args.changed_file), args.lane)
    except (ExecutionPlanError, ImpactGraphConfigError, OSError, ValueError) as exc:
        plan = {
            "schema_version": 1,
            "status": "BLOCKED",
            "reason": str(exc),
            "risk": "R5",
            "lane": "integration",
            "domains": [],
            "global_scopes": [],
            "jobs": [],
            "suite_matrix": [],
            "build": {},
            "performance_policy": "config/ci_performance_policy.yaml",
            "selected_suite_count": 0,
            "runnable_suite_count": 0,
            "selected_component_count": 0,
            "skipped": [],
        }
    rendered = json.dumps(plan, indent=2) + "\n"
    print(rendered, end="")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    return 0 if plan["status"] == "READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
