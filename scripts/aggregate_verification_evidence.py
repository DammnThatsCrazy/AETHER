#!/usr/bin/env python3
"""Aggregate suite/universal evidence without changing Impact Graph selection."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.ci_performance import build_performance_evidence, load_policy  # noqa: E402


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    plan = _read(args.plan)
    expected: dict[str, dict[str, Any]] = {
        suite_id: worker
        for worker in plan.get("suite_matrix", [])
        for suite_id in worker.get("suite_ids", [])
    }
    results: dict[str, dict[str, Any]] = {}
    jobs: list[dict[str, Any]] = []
    stage_seconds: dict[str, float] = {}
    candidate_seconds: list[float] = []
    for path in sorted(args.evidence_dir.rglob("classifier-timing.json")):
        timing = _read(path)
        stage_seconds["classifier_seconds"] = float(timing.get("classifier_seconds", 0.0))
        jobs.append({**timing, "stage": "classifier", "job": "classify-change"})
    for path in sorted(args.evidence_dir.rglob("build-timing.json")):
        timing = _read(path)
        jobs.append({**timing, "stage": "build", "job": timing.get("job", path.stem)})
    for path in sorted(args.evidence_dir.rglob("suite-evidence-*.json")):
        payload = _read(path)
        for record in payload.get("suites", []):
            results[record["suite"]] = record
            jobs.append({**record, "stage": "suite_worker", "job": payload.get("worker_id", record["suite"])})
    planned_job_ids = {str(job.get("id")) for job in plan.get("jobs", [])}
    universal_path = next(iter(sorted(args.evidence_dir.rglob("universal-fast-evidence.json"))), None)
    universal_expected = "universal-fast" in planned_job_ids
    universal = _read(universal_path) if universal_path else (
        {"status": "BLOCKED", "checks": []} if universal_expected else {"status": "PASS", "checks": [], "not_applicable": True}
    )
    if universal_path:
        jobs.append({**universal.get("timing", {}), "stage": "universal_fast", "job": "universal-fast"})
    control_path = next(iter(sorted(args.evidence_dir.rglob("control-prerequisites-evidence.json"))), None)
    control_expected = "control-prerequisites" in planned_job_ids
    control = _read(control_path) if control_path else (
        {"status": "BLOCKED", "checks": []} if control_expected else {"status": "PASS", "checks": [], "not_applicable": True}
    )
    if control_path:
        jobs.append({**control.get("timing", {}), "stage": "control_prerequisites", "job": "control-prerequisites"})
    for path in sorted(args.evidence_dir.rglob("candidate-verification.json")):
        candidate = _read(path)
        candidate_seconds.append(float(candidate.get("candidate_verification_seconds", 0.0)))
        jobs.append({
            "candidate_verification_seconds": candidate_seconds[-1],
            "stage": "candidate_verification",
            "job": "candidate-verification",
        })
    if candidate_seconds:
        stage_seconds["candidate_verification_seconds"] = max(candidate_seconds)
    universal_missing = universal_expected and universal_path is None
    control_missing = control_expected and control_path is None
    missing = sorted(set(expected) - set(results))
    blocking_failures = sorted(
        suite_id for suite_id, record in results.items()
        if record.get("blocking", True) and record.get("status") != "PASS"
    )
    control_failed = control_expected and control.get("status") != "PASS"
    universal_failed = universal_expected and universal.get("status") != "PASS"
    status = "PASS"
    if missing or universal_missing or control_missing or universal_failed or control_failed or blocking_failures:
        status = "BLOCKED" if missing or universal_missing or control_missing else "FAILED"
    elif any(record.get("status") != "PASS" for record in results.values()):
        status = "PASS_WITH_DEGRADATION"
    performance = build_performance_evidence(
        plan,
        jobs,
        policy=load_policy(),
        stage_seconds=stage_seconds,
    )
    payload = {
        "schema_version": 1,
        "authority": "verification",
        "status": status,
        "blocking_failures": blocking_failures + (["universal-fast"] if universal_failed else []) + (["control-prerequisites"] if control_failed else []),
        "missing_blocking_suites": missing,
        "suite_results": [results[key] for key in sorted(results)],
        "universal_fast": {"universal": universal, "control_prerequisites": control},
        "performance": performance,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"schema_version": 1, "status": status, "suite_count": len(results), "missing": missing, "performance_status": performance["performance_status"]}, indent=2))
    return 0 if status in {"PASS", "PASS_WITH_DEGRADATION"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
