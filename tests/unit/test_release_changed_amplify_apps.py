"""Post-apply Amplify rebuild: only build-input changes trigger a pinned release."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "release_changed_amplify_apps", ROOT / "scripts/release/release_changed_amplify_apps.py"
)
assert _SPEC and _SPEC.loader
rel = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = rel
_SPEC.loader.exec_module(rel)

COMMIT = "a" * 40


def _change(kind: str, before: dict[str, Any], after: dict[str, Any], actions=("update",)) -> dict[str, Any]:
    return {
        "address": f"{kind}.x",
        "mode": "managed",
        "type": kind,
        "change": {"actions": list(actions), "before": before, "after": after},
    }


def test_selects_only_updates_that_change_build_inputs() -> None:
    plan = {
        "resource_changes": [
            # App root moved: build spec changed.
            _change("aws_amplify_app", {"id": "app1", "build_spec": "old", "tags": {}},
                    {"id": "app1", "build_spec": "new", "tags": {}}),
            # Branch build variable changed.
            _change("aws_amplify_branch", {"app_id": "app2", "branch_name": "main", "environment_variables": {"A": "1"}},
                    {"app_id": "app2", "branch_name": "main", "environment_variables": {"A": "2"}}),
            # Tags or rewrite rules only: served config, no rebuild needed.
            _change("aws_amplify_app", {"id": "app3", "build_spec": "same", "custom_rule": [1]},
                    {"id": "app3", "build_spec": "same", "custom_rule": [2]}),
            # Creation builds on its own from the connected repository.
            _change("aws_amplify_app", {}, {"build_spec": "x"}, actions=("create",)),
            _change("aws_route53_record", {"id": "r"}, {"id": "r2"}),
        ]
    }
    assert rel.changed_branches(plan) == [("app1", "staging"), ("app2", "main")]  # app-level updates default to the staging branch; branch updates keep theirs


class FakeAmplify:
    """list-jobs statuses, start-job outcomes and get-job summaries, in order."""

    def __init__(self, busy: list[str], starts: list[Any], results: list[dict[str, Any]]) -> None:
        self.busy, self.starts, self.results = iter(busy), iter(starts), iter(results)
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> dict[str, Any]:
        self.calls.append(args)
        if args[1] == "list-jobs":
            return {"jobSummaries": [{"status": next(self.busy)}, {"status": "SUCCEED"}]}
        if args[1] == "start-job":
            outcome = next(self.starts)
            if isinstance(outcome, Exception):
                raise outcome
            return {"jobSummary": {"jobId": outcome}}
        return {"job": {"summary": next(self.results)}}


def _release(aws: FakeAmplify) -> None:
    rel.release("app1", "main", COMMIT, aws, timeout_seconds=60, poll_seconds=0, sleep=lambda _: None)


def test_waits_for_running_and_cancelling_jobs_then_releases_the_reviewed_commit() -> None:
    aws = FakeAmplify(
        busy=["RUNNING", "CANCELLING", "SUCCEED"],
        starts=["7"],
        results=[{"status": "RUNNING"}, {"status": "SUCCEED", "commitId": COMMIT}],
    )
    _release(aws)
    starts = [call for call in aws.calls if call[1] == "start-job"]
    assert len(starts) == 1
    assert starts[0][starts[0].index("--job-type") + 1] == "RELEASE"
    assert starts[0][starts[0].index("--commit-id") + 1] == COMMIT


def test_retries_when_a_job_starts_between_the_check_and_start_job() -> None:
    race = rel.AwsError(["amplify", "start-job"], "BadRequestException: You already have pending or running jobs")
    aws = FakeAmplify(
        busy=["SUCCEED", "SUCCEED"],
        starts=[race, "8"],
        results=[{"status": "SUCCEED", "commitId": COMMIT}],
    )
    _release(aws)
    assert sum(call[1] == "start-job" for call in aws.calls) == 2


def test_other_start_errors_are_not_retried() -> None:
    aws = FakeAmplify(busy=["SUCCEED"], starts=[rel.AwsError(["amplify", "start-job"], "AccessDenied")], results=[])
    with pytest.raises(rel.AwsError, match="AccessDenied"):
        _release(aws)


def test_a_build_of_another_commit_fails_the_step() -> None:
    aws = FakeAmplify(busy=["SUCCEED"], starts=["7"], results=[{"status": "SUCCEED", "commitId": "b" * 40}])
    with pytest.raises(RuntimeError, match="not the reviewed commit"):
        _release(aws)


def test_a_failed_release_fails_the_step() -> None:
    aws = FakeAmplify(busy=["SUCCEED"], starts=["7"], results=[{"status": "FAILED"}])
    with pytest.raises(RuntimeError, match="ended FAILED"):
        _release(aws)


def test_rejects_a_short_commit(tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    plan.write_text("{}", encoding="utf-8")
    assert rel.main(["--plan-json", str(plan), "--commit", "abc123"]) == 1
    assert rel.main(["--plan-json", str(plan), "--commit", COMMIT]) == 0
