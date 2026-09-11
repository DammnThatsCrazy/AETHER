#!/usr/bin/env python3
"""Run the single blocking PR verification authority.

The impact graph and the test-suite registry are the inputs to this command;
the command does not maintain a second selection list. It always executes the
universal-fast lane, then runs the checks and suites selected for the affected
lane in parallel. The resulting JSON is the one artifact consumed by the PR
disposition workflow.

Execution is opt-in so local callers can inspect a deterministic plan without
running tests. Commands are executed from the repository root and Python
commands are resolved to this process' interpreter, which keeps local and CI
selection behavior identical.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.impact_graph import (  # noqa: E402
    ImpactGraphConfigError,
    build_impact_index,
    load_impact_graph,
)
from scripts.lib.build_selection import select_builds  # noqa: E402
from scripts.lib.test_suites import TestSuite, build_command, load_suites  # noqa: E402
from scripts.lib.verification_router import (  # noqa: E402
    CheckDefinition,
    VerificationRouterConfig,
    load_router_registry,
)


class DispositionError(ValueError):
    """The blocking verification disposition cannot be produced safely."""


@dataclass(frozen=True)
class PlannedCheck:
    check_id: str
    command: tuple[str, ...]
    timeout_seconds: int
    lane: str
    blocking: bool = True
    release_class: str = "pr_gate"


@dataclass(frozen=True)
class CommandResult:
    check_id: str
    lane: str
    command: tuple[str, ...]
    status: str
    returncode: int | None
    duration_seconds: float
    output: str
    blocking: bool = True
    release_class: str = "pr_gate"

    def as_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "lane": self.lane,
            "command": list(self.command),
            "status": self.status,
            "returncode": self.returncode,
            "duration_seconds": round(self.duration_seconds, 3),
            "blocking": self.blocking,
            "release_class": self.release_class,
            # Keep GitHub artifacts useful without allowing an accidental
            # command to produce an unbounded evidence file.
            "output_tail": self.output[-4000:],
        }


def _changed_files(base: str | None, explicit: Sequence[str]) -> list[str]:
    if explicit:
        return sorted(set(explicit))
    proc = subprocess.run(
        ["git", "diff", "--name-only", base or "HEAD", "--"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode:
        raise DispositionError(proc.stderr.strip() or "cannot discover changed files")
    return sorted(line for line in proc.stdout.splitlines() if line)


def _resolve_command(command: Iterable[str]) -> list[str]:
    argv = list(command)
    if argv and argv[0] == "python":
        argv[0] = sys.executable
    return argv


def _suite_budget(suite: TestSuite) -> int:
    budget = getattr(suite, "hard_runtime_budget_seconds", None)
    if isinstance(budget, (int, float)) and budget > 0:
        return int(budget)
    return 3600


_LANE_ORDER = {lane: rank for rank, lane in enumerate(("fast", "pr", "integration", "regression", "release"))}


def _suite_skip_reason(suite: TestSuite, *, lane: str, profile: str) -> str | None:
    """Return why a registry suite is out of scope for this execution lane."""
    if suite.skip_policy == "documented_quarantine":
        return "documented_quarantine"
    if profile not in suite.profiles:
        return f"profile_not_declared:{profile}"
    environment = "release" if profile == "release" else "ci"
    if environment not in suite.environments:
        return f"environment_not_declared:{environment}"
    if suite.lane == "release" and lane != "release":
        return "release_lane_only"
    if _LANE_ORDER[suite.lane] > _LANE_ORDER[lane]:
        return f"suite_lane_exceeds_selected_lane:{suite.lane}"
    return None


def _planned_checks(
    router: VerificationRouterConfig,
    suites: dict[str, TestSuite],
    selected_ids: Iterable[str],
    lane: str,
    *,
    profile: str | None = None,
) -> tuple[list[PlannedCheck], list[dict[str, str]]]:
    planned: list[PlannedCheck] = []
    skipped: list[dict[str, str]] = []
    profile = profile or ("release" if lane == "release" else "ci")
    for check_id in sorted(set(selected_ids)):
        definition: CheckDefinition | None = router.checks.get(check_id)
        if definition is not None:
            planned.append(
                PlannedCheck(
                    check_id=check_id,
                    command=definition.command,
                    timeout_seconds=definition.runtime_budget_seconds,
                    lane=lane,
                )
            )
            continue
        suite = suites.get(check_id)
        if suite is None:
            raise DispositionError(f"selected check {check_id!r} has no command definition")
        skip_reason = _suite_skip_reason(suite, lane=lane, profile=profile)
        if skip_reason is not None:
            skipped.append({"suite": suite.id, "reason": skip_reason, "lane": lane, "profile": profile})
            continue
        planned.append(
            PlannedCheck(
                check_id=check_id,
                command=tuple(build_command(suite)),
                timeout_seconds=_suite_budget(suite),
                lane=lane,
                blocking=suite.release_class != "advisory",
                release_class=suite.release_class,
            )
        )
    return planned, skipped


def _run_one(check: PlannedCheck, *, execute: bool) -> CommandResult:
    if not execute:
        return CommandResult(
            check_id=check.check_id,
            lane=check.lane,
            command=check.command,
            status="PLANNED",
            returncode=None,
            duration_seconds=0.0,
            output="",
            blocking=check.blocking,
            release_class=check.release_class,
        )
    started = time.monotonic()
    try:
        proc = subprocess.run(
            _resolve_command(check.command),
            cwd=ROOT,
            env={**os.environ, "CI": os.environ.get("CI", "true")},
            text=True,
            capture_output=True,
            check=False,
            timeout=check.timeout_seconds,
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        status = "PASS" if proc.returncode == 0 else "FAILED"
        return CommandResult(
            check_id=check.check_id,
            lane=check.lane,
            command=check.command,
            status=status,
            returncode=proc.returncode,
            duration_seconds=time.monotonic() - started,
            output=output,
            blocking=check.blocking,
            release_class=check.release_class,
        )
    except subprocess.TimeoutExpired as exc:
        output = ((exc.stdout or "") if isinstance(exc.stdout, str) else "") + (
            (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        )
        return CommandResult(
            check_id=check.check_id,
            lane=check.lane,
            command=check.command,
            status="TIMEOUT",
            returncode=None,
            duration_seconds=time.monotonic() - started,
            output=output,
            blocking=check.blocking,
            release_class=check.release_class,
        )
    except OSError as exc:
        return CommandResult(
            check_id=check.check_id,
            lane=check.lane,
            command=check.command,
            status="RUNNER_FAILURE",
            returncode=None,
            duration_seconds=time.monotonic() - started,
            output=str(exc),
            blocking=check.blocking,
            release_class=check.release_class,
        )


def _run_parallel(checks: Sequence[PlannedCheck], *, execute: bool) -> list[CommandResult]:
    if not checks:
        return []
    # Several registry commands already parallelize internally (the root and
    # backend suites in particular). Four outer workers preserve overlap while
    # preventing a global integration selection from exhausting a hosted
    # runner and turning otherwise healthy suites into budget timeouts.
    workers = min(4, len(checks))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_run_one, check, execute=execute) for check in checks]
        results = [future.result() for future in futures]
    return sorted(results, key=lambda result: result.check_id)


def _risk_lanes() -> dict[str, str]:
    policy_path = ROOT / "config" / "verification_policy.yaml"
    try:
        policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise DispositionError(f"cannot load verification risk policy: {exc}") from exc
    mapping = policy.get("risk_lanes") if isinstance(policy, dict) else None
    if not isinstance(mapping, dict) or set(mapping) != {f"R{i}" for i in range(6)}:
        raise DispositionError("verification policy risk_lanes must define R0 through R5")
    if not all(isinstance(risk, str) and isinstance(lane, str) for risk, lane in mapping.items()):
        raise DispositionError("verification policy risk_lanes entries must be strings")
    return mapping


def _risk(index: dict[str, Any], risk_lanes: dict[str, str]) -> str:
    lane = index["router"]["selected_lane"]
    # The policy contains risk bands (for example R1/R2 both map to PR).
    # Choose the least escalated risk that names the selected lane so a
    # global/integration selection cannot be mislabeled as release risk. The
    # registry has no distinct regression risk lane, so its highest lower-lane
    # risk is the conservative fallback for an explicit regression run.
    lane_order = {name: rank for rank, name in enumerate(("fast", "pr", "integration", "regression", "release"))}
    selected_rank = lane_order.get(lane)
    if selected_rank is None:
        raise DispositionError(f"verification policy selected an unknown lane {lane!r}")
    matches = sorted(
        risk for risk, mapped_lane in risk_lanes.items() if mapped_lane == lane
    )
    if not matches:
        matches = sorted(
            (
                risk
                for risk, mapped_lane in risk_lanes.items()
                if lane_order.get(mapped_lane, -1) < selected_rank
            ),
            key=lambda risk: int(risk[1:]),
            reverse=True,
        )
    if not matches:
        raise DispositionError(f"verification policy has no risk mapped to lane {lane!r}")
    return matches[0]


def build_disposition(
    changed_files: Sequence[str],
    *,
    requested_lane: str | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    router = load_router_registry(ROOT / "config" / "verification_router.yaml")
    suites_list = load_suites(ROOT / "config" / "test_suites.yaml")
    suites = {suite.id: suite for suite in suites_list}
    risk_lanes = _risk_lanes()
    graph = load_impact_graph(router=router, suites=suites_list)
    index = build_impact_index(changed_files, graph, requested_lane=requested_lane, router=router)
    if index["unresolved_paths"]:
        return {
            "schema_version": 1,
            "authority": "verification",
            "blocking": True,
            "status": "BLOCKED",
            "reason": "unresolved executable or delivery paths",
            "sha": os.environ.get("GITHUB_SHA"),
            "impact": {
                "risk": _risk(index, risk_lanes),
                "components": index["impacted_components"],
                "contracts": index["impacted_contracts"],
            },
            "unresolved_paths": index["unresolved_paths"],
        }

    universal_ids = set(router.lanes["fast"])
    selected_ids = set(index["router"]["selected_checks"])
    affected_ids = selected_ids - universal_ids
    universal, universal_skipped = _planned_checks(router, suites, universal_ids, "fast")
    affected, affected_skipped = _planned_checks(
        router, suites, affected_ids, index["router"]["selected_lane"]
    )
    results = _run_parallel([*universal, *affected], execute=execute)
    failed = [
        result for result in results
        if result.blocking and result.status not in {"PASS", "PLANNED"}
    ]
    advisory_failures = [
        result for result in results
        if not result.blocking and result.status not in {"PASS", "PLANNED"}
    ]
    selected_suites = sorted(set(index["router"]["selected_test_suites"]))
    disposition = "FAILED" if failed else ("PASS" if execute else "PLANNED")
    selected_by = index["router"]["selected_lane"]
    runtime_runs = [
        {
            "suite": result.check_id,
            "runtime_seconds": result.duration_seconds,
            "selected_by": [selected_by],
            "outcome": result.status.lower(),
            "components": index["impacted_components"],
            "retry": False,
            "cache": False,
            "blocking": result.blocking,
        }
        for result in results
        if result.check_id in suites
    ]
    critical_path = max((result.duration_seconds for result in results), default=0.0)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "authority": "verification",
        "blocking": True,
        "status": disposition,
        "sha": os.environ.get("GITHUB_SHA"),
        "impact": {
            "risk": _risk(index, risk_lanes),
            "components": index["impacted_components"],
            "contracts": index["impacted_contracts"],
            "domains": index["router"]["affected_domains"],
            "minimum_lane": index["router"]["minimum_lane"],
            "selected_lane": index["router"]["selected_lane"],
        },
        "suites": {
            "selected": len(selected_suites),
            "selected_ids": selected_suites,
            "planned_ids": sorted(result.check_id for result in results if result.check_id in suites),
            "skipped": [*universal_skipped, *affected_skipped],
            "registered": len(suites_list),
        },
        "build_selection": select_builds(
            changed_files, global_change=index["router"]["global_change"]
        ),
        "checks": [result.as_dict() for result in results],
        "advisory_failures": [result.as_dict() for result in advisory_failures],
        "runs": runtime_runs,
        "unresolved_paths": index["unresolved_paths"],
        "timing": {
            "critical_path_seconds": round(critical_path, 3),
            "sum_seconds": round(sum(result.duration_seconds for result in results), 3),
        },
        "disposition": disposition,
    }
    identity = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload["event_id"] = "verification_" + hashlib.sha256(identity.encode()).hexdigest()[:24]
    return payload


def _hosted_runtime_evidence(result: dict[str, Any], elapsed_seconds: float) -> dict[str, Any]:
    """Produce one durable record per hosted verification execution.

    These records are intentionally self-contained so artifacts from a
    representative PR window can be aggregated into p50/p95 without scraping
    logs or inferring selection from workflow names.
    """
    return {
        "schema_version": 1,
        "authority": "verification",
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "repository": os.environ.get("GITHUB_REPOSITORY"),
        "sha": os.environ.get("GITHUB_SHA"),
        "pr_number": os.environ.get("GITHUB_EVENT_NUMBER"),
        "status": result.get("status"),
        "execution_elapsed_seconds": round(elapsed_seconds, 3),
        "timing": result.get("timing", {}),
        "impact": result.get("impact", {}),
        "suites": result.get("suites", {}),
        "runs": result.get("runs", []),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="git revision used for changed-path discovery")
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--lane", choices=("fast", "pr", "integration", "regression", "release"))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--runtime-output",
        type=Path,
        help="write self-contained hosted runtime evidence for p50/p95 aggregation",
    )
    args = parser.parse_args(argv)
    started = time.monotonic()
    try:
        result = build_disposition(
            _changed_files(args.base, args.changed_file),
            requested_lane=args.lane,
            execute=args.execute,
        )
    except (DispositionError, ImpactGraphConfigError, OSError, ValueError) as exc:
        result = {
            "schema_version": 1,
            "authority": "verification",
            "blocking": True,
            "status": "BLOCKED",
            "reason": str(exc),
        }
    elapsed_seconds = time.monotonic() - started
    rendered = json.dumps(result, indent=2) + "\n"
    print(rendered, end="")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    if args.runtime_output:
        args.runtime_output.parent.mkdir(parents=True, exist_ok=True)
        args.runtime_output.write_text(
            json.dumps(_hosted_runtime_evidence(result, elapsed_seconds), indent=2) + "\n",
            encoding="utf-8",
        )
    return 0 if result["status"] in {"PASS", "PLANNED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
