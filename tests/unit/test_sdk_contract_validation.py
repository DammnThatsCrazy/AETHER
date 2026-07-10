"""Gates for scripts/validate_sdk_contracts.py and scripts/check_version_consistency.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from check_version_consistency import check_workspace_coverage  # noqa: E402


def _run(script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / script), *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )


def test_validate_sdk_contracts_passes_against_repo():
    proc = _run("validate_sdk_contracts.py")
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_validate_sdk_contracts_json_output_shape():
    proc = _run("validate_sdk_contracts.py", "--json")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["passed"] is True
    names = {check["name"] for check in payload["checks"]}
    assert "shared contract pins /v1/batch" in names
    assert "backend batch route exists" in names
    assert "idempotency key fields aligned" in names


def test_check_version_consistency_passes_against_repo():
    proc = _run("check_version_consistency.py")
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_workspace_coverage_detects_uncovered_member(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps({"workspaces": ["packages/shared"]})
    )
    member = tmp_path / "frontend" / "aether"
    member.mkdir(parents=True)
    (member / "package.json").write_text("{}")
    uncovered = check_workspace_coverage(tmp_path)
    assert uncovered == ["frontend/aether"]


def test_workspace_coverage_honors_glob_patterns(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps({"workspaces": ["packages/*", "frontend/*"]})
    )
    for member in ("packages/shared", "frontend/aether"):
        d = tmp_path / member
        d.mkdir(parents=True)
        (d / "package.json").write_text("{}")
    assert check_workspace_coverage(tmp_path) == []
