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
for the reviewed commit, waits for it to succeed, and fails unless the job
reports that exact commit (``RELEASE`` builds the branch tip, so a ``main``
that moved on since the plan is caught rather than reported as the reviewed
build). It reads only Amplify job metadata; never a token, artifact, or secret.
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
ACTIVE_JOB_STATUSES = frozenset({"CREATED", "PENDING", "PROVISIONING", "QUEUED", "RUNNING", "CANCELLING"})
# Amplify's reply when another job started between our check and start-job.
CONCURRENT_JOB_MESSAGE = "already have pending or running jobs"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
DEFAULT_BRANCH = "main"

AwsCall = Callable[[list[str]], Mapping[str, Any]]


class AwsError(RuntimeError):
    """An AWS CLI call failed; ``detail`` carries its error text."""

    def __init__(self, args: list[str], detail: str) -> None:
        super().__init__(f"AWS Amplify request failed for {args[:2]}: {detail[:300]}")
        self.detail = detail


def aws_json(args: list[str]) -> Mapping[str, Any]:
    result = subprocess.run(["aws", *args, "--output", "json"], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise AwsError(args, result.stderr.strip())
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


def _branch_busy(app_id: str, branch: str, aws: AwsCall) -> bool:
    jobs = aws(["amplify", "list-jobs", "--app-id", app_id, "--branch-name", branch, "--max-results", "50"])
    return any(_mapping(job).get("status") in ACTIVE_JOB_STATUSES for job in jobs.get("jobSummaries") or [])


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
    # Amplify runs one job per branch: let any running or cancelling job
    # finish, and retry when another starts between the check and start-job.
    while True:
        if clock() >= deadline:
            raise RuntimeError(f"{app_id}/{branch}: the branch never became free for a release")
        if _branch_busy(app_id, branch, aws):
            sleep(poll_seconds)
            continue
        try:
            started = aws([
                "amplify", "start-job", "--app-id", app_id, "--branch-name", branch,
                "--job-type", "RELEASE", "--commit-id", commit,
                "--commit-message", "Rebuild after a reviewed Terraform apply changed build inputs",
            ])
        except AwsError as exc:
            if CONCURRENT_JOB_MESSAGE not in exc.detail:
                raise
            sleep(poll_seconds)
            continue
        break
    job_id = _mapping(started.get("jobSummary")).get("jobId")
    if not isinstance(job_id, str) or not job_id:
        raise RuntimeError(f"{app_id}/{branch}: start-job returned no job id")
    print(f"{app_id}/{branch}: release job {job_id} started at {commit}")
    while True:
        job = aws(["amplify", "get-job", "--app-id", app_id, "--branch-name", branch, "--job-id", job_id])
        summary = _mapping(_mapping(job.get("job")).get("summary"))
        status = summary.get("status")
        if status == "SUCCEED":
            built = summary.get("commitId")
            if built != commit:
                raise RuntimeError(
                    f"{app_id}/{branch}: release job {job_id} built {built}, not the reviewed commit {commit}; "
                    "main moved on since the plan, so plan and apply again from the new head"
                )
            print(f"{app_id}/{branch}: release job {job_id} built {commit}")
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
