#!/usr/bin/env python3
"""Execute only the universal-fast checks already present in a plan."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.verification_router import load_router_registry  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--job-id", default="universal-fast")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--commit-sha", default=os.environ.get("GITHUB_SHA", "local"))
    args = parser.parse_args(argv)
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    job = next((item for item in plan.get("jobs", []) if item.get("id") == args.job_id), None)
    started = time.monotonic()
    checks: list[dict[str, object]] = []
    if plan.get("status") != "READY" or job is None:
        payload = {"schema_version": 1, "stage": args.job_id, "status": "BLOCKED", "checks": [], "timing": {"total_job_seconds": 0.0}, "commit_sha": args.commit_sha}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return 2
    router = load_router_registry(ROOT / "config/verification_router.yaml")
    status = "PASS"
    for check_id in job.get("checks", []):
        check = router.checks.get(check_id)
        if check is None:
            checks.append({"check": check_id, "status": "FAILED", "returncode": 2, "seconds": 0.0})
            status = "FAILED"
            continue
        check_started = time.monotonic()
        command = list(check.command)
        if command and command[0] == "python":
            command[0] = sys.executable
        process = subprocess.run(command, cwd=ROOT, env={**os.environ, "CI": os.environ.get("CI", "true")}, text=True, capture_output=True, check=False, timeout=check.runtime_budget_seconds)
        output = (process.stdout or "") + (process.stderr or "")
        print(output, end="")
        checks.append({"check": check_id, "status": "PASS" if process.returncode == 0 else "FAILED", "returncode": process.returncode, "seconds": time.monotonic() - check_started, "output_tail": output[-2000:]})
        if process.returncode:
            status = "FAILED"
    elapsed = time.monotonic() - started
    payload = {
        "schema_version": 1,
        "stage": args.job_id,
        "status": status,
        "checks": checks,
        "timing": {"queue_seconds": 0.0, "checkout_seconds": 0.0, "dependency_setup_seconds": float(os.environ.get("CI_SETUP_SECONDS", "0")), "cache_restore_seconds": 0.0, "test_seconds": elapsed, "build_seconds": 0.0, "artifact_upload_seconds": 0.0, "candidate_verification_seconds": 0.0, "disposition_seconds": 0.0, "total_job_seconds": elapsed},
        "runner": os.environ.get("RUNNER_OS", "local"),
        "commit_sha": args.commit_sha,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
