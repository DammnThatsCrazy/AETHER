#!/usr/bin/env python3
"""Rebuild the Amplify apps whose build inputs a reviewed apply changed.

Amplify builds a connected branch when a commit lands, from the build spec and
build variables it holds at that moment. A later ``terraform apply`` that
changes those inputs (for example the monorepo app root, or a ``VITE_*``
variable baked into the bundle) starts no build, so the host keeps serving a
bundle built from the old inputs until some unrelated push.

After a successful apply, this reads the reviewed plan JSON, finds every
``aws_amplify_app`` / ``aws_amplify_branch`` update whose ``build_spec`` or
``environment_variables`` changed, starts a RELEASE job for that app's branch
pinned to the reviewed commit, and waits for it to succeed. It reads only
Amplify job metadata; never a token, artifact, or secret.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

BUILD_INPUTS = {
    "aws_amplify_app": ("build_spec", "environment_variables"),
    "aws_amplify_branch": ("environment_variables",),
}
ACTIVE_JOB_STATUSES = frozenset({"CREATED", "PENDING", "PROVISIONING", "QUEUED", "RUNNING"})
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
DEFAULT_BRANCH = "main"

AwsCall = Callable[[list[str]], Mapping[str, Any]]


def aws_json(args: list[str]) -> Mapping[str, Any]:
    result = subprocess.run(["aws", *args, "--output", "json"], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"AWS Amplify request failed for {args[:2]}: {result.stderr.strip()[:300]}")
    payload = json.loads(result.stdout or "{}")
    if not isinstance(payload, Mapping):
        raise RuntimeError("AWS Amplify response was not an object")
    return payload


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def changed_branches(plan: Mapping[str, Any]) -> list[tuple[str, str]]:
    """(app id, branch name) for every Amplify update that changes build inputs."""
    targets: dict[str, str] = {}
    for change in plan.get("resource_changes") or []:
        kind = change.get("type")
        if change.get("mode") != "managed" or kind not in BUILD_INPUTS:
            continue
        detail = _mapping(change.get("change"))
        if list(detail.get("actions") or []) != ["update"]:
            continue
        before, after = _mapping(detail.get("before")), _mapping(detail.get("after"))
        if all(before.get(key) == after.get(key) for key in BUILD_INPUTS[kind]):
            continue
        if kind == "aws_amplify_app":
            app_id, branch = before.get("id"), DEFAULT_BRANCH
        else:
            app_id, branch = before.get("app_id"), before.get("branch_name")
        if not isinstance(app_id, str) or not app_id or not isinstance(branch, str) or not branch:
            raise RuntimeError(f"{change.get('address')} has no app id or branch in the reviewed plan")
        targets[app_id] = branch
    return sorted(targets.items())


def _latest_job(app_id: str, branch: str, aws: AwsCall) -> Mapping[str, Any]:
    jobs = aws(["amplify", "list-jobs", "--app-id", app_id, "--branch-name", branch, "--max-items", "1"])
    summaries = jobs.get("jobSummaries") or []
    return _mapping(summaries[0]) if summaries else {}


def release(
    app_id: str,
    branch: str,
    commit: str,
    aws: AwsCall,
    *,
    timeout_seconds: float,
    poll_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    deadline = clock() + timeout_seconds
    # Amplify runs one job per branch: let the push-triggered build finish first.
    while _latest_job(app_id, branch, aws).get("status") in ACTIVE_JOB_STATUSES:
        if clock() >= deadline:
            raise RuntimeError(f"{app_id}/{branch}: an earlier job is still running")
        sleep(poll_seconds)
    started = aws([
        "amplify", "start-job", "--app-id", app_id, "--branch-name", branch,
        "--job-type", "RELEASE", "--commit-id", commit,
        "--commit-message", "Rebuild after a reviewed Terraform apply changed build inputs",
    ])
    job_id = _mapping(started.get("jobSummary")).get("jobId")
    if not isinstance(job_id, str) or not job_id:
        raise RuntimeError(f"{app_id}/{branch}: start-job returned no job id")
    print(f"{app_id}/{branch}: release job {job_id} started at {commit}")
    while True:
        job = aws(["amplify", "get-job", "--app-id", app_id, "--branch-name", branch, "--job-id", job_id])
        status = _mapping(_mapping(job.get("job")).get("summary")).get("status")
        if status == "SUCCEED":
            print(f"{app_id}/{branch}: release job {job_id} succeeded")
            return
        if status not in ACTIVE_JOB_STATUSES:
            raise RuntimeError(f"{app_id}/{branch}: release job {job_id} ended {status}")
        if clock() >= deadline:
            raise RuntimeError(f"{app_id}/{branch}: release job {job_id} did not finish in time")
        sleep(poll_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--plan-json", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=1200.0)
    parser.add_argument("--poll-seconds", type=float, default=15.0)
    args = parser.parse_args(argv)
    if not COMMIT_RE.fullmatch(args.commit):
        print("::error::--commit must be a full 40-character commit SHA", file=sys.stderr)
        return 1
    targets = changed_branches(json.loads(args.plan_json.read_text(encoding="utf-8")))
    if not targets:
        print("No Amplify build inputs changed; no release needed.")
        return 0
    try:
        for app_id, branch in targets:
            release(app_id, branch, args.commit, aws_json,
                    timeout_seconds=args.timeout_seconds, poll_seconds=args.poll_seconds)
    except RuntimeError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
