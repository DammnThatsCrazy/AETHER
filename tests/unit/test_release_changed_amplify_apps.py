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
    assert rel.changed_branches(plan) == [("app1", "main"), ("app2", "main")]


def test_waits_for_the_running_build_then_releases_the_reviewed_commit() -> None:
    calls: list[list[str]] = []
    list_statuses = iter(["RUNNING", "SUCCEED"])
    get_statuses = iter(["RUNNING", "SUCCEED"])

    def aws(args: list[str]) -> dict[str, Any]:
        calls.append(args)
        if args[1] == "list-jobs":
            return {"jobSummaries": [{"status": next(list_statuses)}]}
        if args[1] == "start-job":
            return {"jobSummary": {"jobId": "7"}}
        return {"job": {"summary": {"status": next(get_statuses)}}}

    rel.release("app1", "main", COMMIT, aws, timeout_seconds=60, poll_seconds=0, sleep=lambda _: None)
    start = next(call for call in calls if call[1] == "start-job")
    assert start[start.index("--job-type") + 1] == "RELEASE"
    assert start[start.index("--commit-id") + 1] == COMMIT


def test_a_failed_release_fails_the_step() -> None:
    def aws(args: list[str]) -> dict[str, Any]:
        if args[1] == "list-jobs":
            return {"jobSummaries": []}
        if args[1] == "start-job":
            return {"jobSummary": {"jobId": "7"}}
        return {"job": {"summary": {"status": "FAILED"}}}

    with pytest.raises(RuntimeError, match="ended FAILED"):
        rel.release("app1", "main", COMMIT, aws, timeout_seconds=60, poll_seconds=0, sleep=lambda _: None)


def test_rejects_a_short_commit(tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    plan.write_text("{}", encoding="utf-8")
    assert rel.main(["--plan-json", str(plan), "--commit", "abc123"]) == 1
    assert rel.main(["--plan-json", str(plan), "--commit", COMMIT]) == 0
