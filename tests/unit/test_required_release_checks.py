from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "release"))

import check_required_checks  # noqa: E402
import collect_evidence  # noqa: E402


def test_required_check_catalog_matches_workflow():
    assert check_required_checks.validate(ROOT) == []


def _hosted_file(tmp_path: Path, sha: str, conclusion: str = "success") -> Path:
    catalog = yaml.safe_load((ROOT / "config/required_release_checks.yaml").read_text())
    checks = []
    for index, definition in enumerate(catalog["checks"], 1):
        checks.append({
            "id": definition["id"], "commit_sha": sha,
            "workflow_run_id": index, "job_name": definition["job"],
            "conclusion": conclusion, "completed_at": "2026-07-16T12:00:00Z",
            "artifact_name": definition["evidence_artifact"],
            "artifact_sha256": "a" * 64,
        })
    path = tmp_path / "checks.json"
    path.write_text(json.dumps({"checks": checks}), encoding="utf-8")
    return path


def test_hosted_evidence_accepts_complete_exact_sha_results(tmp_path):
    path = _hosted_file(tmp_path, "expected")
    result = collect_evidence.hosted_checks_section(str(path), "expected")
    assert result["authoritative"] is True
    assert result["passed"] is True


def test_hosted_evidence_rejects_missing_input():
    result = collect_evidence.hosted_checks_section(None, "expected")
    assert result["passed"] is False
    assert result["reason"] == "github_check_evidence_missing"


def test_hosted_evidence_rejects_sha_mismatch(tmp_path):
    path = _hosted_file(tmp_path, "other")
    result = collect_evidence.hosted_checks_section(str(path), "expected")
    assert result["passed"] is False
    assert all("SHA mismatch" in failure for failure in result["failures"])


def test_hosted_evidence_rejects_failed_cancelled_and_skipped(tmp_path):
    for conclusion in ("failure", "cancelled", "skipped"):
        path = _hosted_file(tmp_path, "expected", conclusion)
        result = collect_evidence.hosted_checks_section(str(path), "expected")
        assert result["passed"] is False
        assert any(conclusion in failure for failure in result["failures"])


def test_hosted_evidence_rejects_missing_required_check(tmp_path):
    path = _hosted_file(tmp_path, "expected")
    payload = json.loads(path.read_text())
    payload["checks"].pop()
    path.write_text(json.dumps(payload))
    result = collect_evidence.hosted_checks_section(str(path), "expected")
    assert result["passed"] is False
    assert any("missing" in failure for failure in result["failures"])


def test_hosted_evidence_rejects_unproven_timestamp(tmp_path):
    path = _hosted_file(tmp_path, "expected")
    payload = json.loads(path.read_text())
    payload["checks"][0]["completed_at"] = "sometime"
    path.write_text(json.dumps(payload))
    result = collect_evidence.hosted_checks_section(str(path), "expected")
    assert result["passed"] is False
    assert any("timestamp" in failure for failure in result["failures"])
