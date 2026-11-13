"""Behavioural tests for the shared workflow dispatch and run-status helpers.

scripts/ci/dispatch_workflow.sh and scripts/ci/run_status.sh replace copies
that were pasted into the lifecycle, pilot wrapper and business-hours
workflows. These run the real scripts against a fake `gh` on PATH.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DISPATCH = ROOT / "scripts/ci/dispatch_workflow.sh"
STATUS = ROOT / "scripts/ci/run_status.sh"

FAKE_GH = """#!/bin/bash
echo "$*" >> "$SIM/calls"
n=$(cat "$SIM/n" 2>/dev/null || echo 0); echo $((n+1)) > "$SIM/n"
case "$MODE" in
  404then) [ "$n" -lt 2 ] && { echo "gh: Not Found (HTTP 404)" >&2; exit 1; }; echo in_progress;;
  404) echo "gh: Not Found (HTTP 404)" >&2; exit 1;;
  403) echo "gh: Resource not accessible by integration (HTTP 403)" >&2; exit 1;;
  dispatch_fail) echo "HTTP 502: Bad Gateway" >&2; exit 1;;
  dispatch_ok) echo "https://github.com/o/r/actions/runs/77";;
esac
"""


def _run(tmp_path: Path, mode: str, *argv: str) -> subprocess.CompletedProcess:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "SIM": str(tmp_path),
           "RUNNER_TEMP": str(tmp_path), "MODE": mode}
    return subprocess.run(list(argv), capture_output=True, text=True, env=env, check=False)


def test_dispatch_prints_the_created_run_on_success(tmp_path):
    result = _run(tmp_path, "dispatch_ok", str(DISPATCH), "x.yml", "--ref", "staging")
    assert result.returncode == 0
    assert "actions/runs/77" in result.stdout
    assert (tmp_path / "calls").read_text().strip() == "workflow run x.yml --ref staging"


def test_dispatch_failure_is_reported_and_never_retried(tmp_path):
    result = _run(tmp_path, "dispatch_fail", str(DISPATCH), "x.yml", "--ref", "staging")
    assert result.returncode == 1
    assert result.stdout == ""
    assert "HTTP 502: Bad Gateway" in result.stderr
    assert "::error::workflow dispatch failed" in result.stderr
    assert len((tmp_path / "calls").read_text().splitlines()) == 1


def test_status_tolerates_a_just_dispatched_404_then_reads_the_run(tmp_path):
    outputs = [_run(tmp_path, "404then", str(STATUS), "o/r", "5") for _ in range(3)]
    assert [o.returncode for o in outputs] == [0, 0, 0]
    assert [o.stdout.strip() for o in outputs] == ["lookup_pending", "lookup_pending", "in_progress"]


def test_status_fails_a_404_once_the_grace_window_has_passed(tmp_path):
    result = _run(tmp_path, "404", str(STATUS), "o/r", "6", "0")
    assert result.returncode == 1
    assert "HTTP 404" in result.stderr and "::error::could not read run 6 status" in result.stderr


def test_status_fails_any_other_error_immediately(tmp_path):
    result = _run(tmp_path, "403", str(STATUS), "o/r", "7")
    assert result.returncode == 1
    assert result.stdout == ""
    assert "HTTP 403" in result.stderr
