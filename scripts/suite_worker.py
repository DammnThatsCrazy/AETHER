#!/usr/bin/env python3
"""Execute one planned suite worker and emit standardized timing evidence."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.test_suites import build_command, load_suites  # noqa: E402


def _number(value: str | float | int) -> float:
    result = float(value)
    if result < 0:
        raise ValueError("timings must be non-negative")
    return result


def _resolve_command(command: list[str]) -> list[str]:
    if command and command[0] == "python":
        command[0] = sys.executable
    return command


def run_worker(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    suites = {suite.id: suite for suite in load_suites(ROOT / "config/test_suites.yaml")}
    suite_ids = json.loads(args.suite_ids)
    if not isinstance(suite_ids, list) or not suite_ids or not all(isinstance(item, str) for item in suite_ids):
        raise ValueError("--suite-ids must be a non-empty JSON array of strings")
    records: list[dict[str, Any]] = []
    worker_started = time.monotonic()
    overall_return = 0
    for suite_id in suite_ids:
        suite = suites.get(suite_id)
        if suite is None:
            raise ValueError(f"unknown suite {suite_id!r}")
        if suite.dependency_profile != args.dependency_profile or suite.runtime_class != args.runtime_class:
            raise ValueError(f"worker metadata does not match suite {suite_id!r}")
        if suite.requires.docker and shutil.which("docker") is None:
            raise OSError(f"suite {suite_id!r} requires Docker but no docker executable is available")
        started = time.monotonic()
        output = ""
        returncode = 0
        try:
            process = subprocess.run(
                _resolve_command(build_command(suite)),
                cwd=ROOT,
                env={**os.environ, "CI": os.environ.get("CI", "true")},
                text=True,
                capture_output=True,
                check=False,
                timeout=int(suite.hard_runtime_budget_seconds),
            )
            output = (process.stdout or "") + (process.stderr or "")
            returncode = process.returncode
        except subprocess.TimeoutExpired as exc:
            output = ((exc.stdout or "") if isinstance(exc.stdout, str) else "") + ((exc.stderr or "") if isinstance(exc.stderr, str) else "")
            returncode = 124
        except OSError as exc:
            output = str(exc)
            returncode = 1
        execution = time.monotonic() - started
        if returncode:
            overall_return = 1
        setup = _number(args.setup_seconds) if len(suite_ids) == 1 else (_number(args.setup_seconds) / len(suite_ids))
        record = {
            "suite": suite.id,
            "status": "PASS" if returncode == 0 else "FAILED",
            "blocking": suite.release_class != "advisory",
            "dependency_profile": suite.dependency_profile,
            "runtime_class": suite.runtime_class,
            "queue_seconds": _number(args.queue_seconds),
            "checkout_seconds": _number(args.checkout_seconds),
            "dependency_setup_seconds": setup,
            "cache_restore_seconds": _number(args.cache_restore_seconds),
            "test_seconds": execution,
            "build_seconds": 0.0,
            "artifact_upload_seconds": 0.0,
            "candidate_verification_seconds": 0.0,
            "disposition_seconds": 0.0,
            "execution_seconds": execution,
            "total_seconds": _number(args.queue_seconds) + _number(args.checkout_seconds) + setup + _number(args.cache_restore_seconds) + execution,
            "total_job_seconds": time.monotonic() - worker_started,
            "runner": args.runner,
            "commit_sha": args.commit_sha,
            "output_tail": output[-4000:],
        }
        records.append(record)
        print(output, end="")
    payload = {
        "schema_version": 1,
        "worker_id": args.worker_id,
        "worker_class": args.worker_class,
        "status": "PASS" if overall_return == 0 else "FAILED",
        "suites": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload, overall_return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--worker-class", choices=("pooled", "isolated"), required=True)
    parser.add_argument("--suite-ids", required=True, help="JSON array from the execution plan")
    parser.add_argument("--dependency-profile", required=True)
    parser.add_argument("--runtime-class", choices=("tiny", "small", "medium", "heavy"), required=True)
    parser.add_argument("--setup-seconds", default="0")
    parser.add_argument("--cache-restore-seconds", default="0")
    parser.add_argument("--queue-seconds", default="0")
    parser.add_argument("--checkout-seconds", default="0")
    parser.add_argument("--runner", default=os.environ.get("RUNNER_OS", "local"))
    parser.add_argument("--commit-sha", default=os.environ.get("GITHUB_SHA", "local"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        _, returncode = run_worker(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"suite worker blocked: {exc}", file=sys.stderr)
        return 2
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
