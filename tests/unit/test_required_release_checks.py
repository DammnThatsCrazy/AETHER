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


def _fake_github_api(sha: str = "expected", *, conclusion: str = "success",
                     job_conclusion: str | None = None,
                     workflow_path: str | None = None,
                     artifact_expired: bool = False,
                     drop_artifacts: bool = False):
    """Build a _github_api double serving run/jobs/artifacts for every check."""
    catalog = yaml.safe_load((ROOT / "config/required_release_checks.yaml").read_text())
    jobs = [{"name": row["job"], "conclusion": job_conclusion or conclusion}
            for row in catalog["checks"]]
    artifacts = [] if drop_artifacts else [
        {"name": row["evidence_artifact"], "expired": artifact_expired}
        for row in catalog["checks"]
    ]
    workflow = workflow_path or catalog["checks"][0]["workflow"]

    def api(repo: str, path: str, token: str) -> dict:
        assert repo and token
        if path.endswith("/jobs?per_page=100"):
            return {"jobs": jobs}
        if path.endswith("/artifacts?per_page=100"):
            return {"artifacts": artifacts}
        return {"head_sha": sha, "path": workflow, "conclusion": conclusion}

    return api


def test_hosted_evidence_local_json_alone_is_never_authoritative(tmp_path):
    # Structurally perfect local JSON without GitHub API verification must
    # fail closed: no token/repository => non-authoritative.
    path = _hosted_file(tmp_path, "expected")
    result = collect_evidence.hosted_checks_section(
        str(path), "expected", repo="", token=""
    )
    assert result["authoritative"] is False
    assert result["passed"] is False
    assert any("GITHUB_TOKEN" in failure for failure in result["failures"])


def test_hosted_evidence_accepts_api_verified_exact_sha_results(tmp_path, monkeypatch):
    path = _hosted_file(tmp_path, "expected")
    monkeypatch.setattr(collect_evidence, "_github_api", _fake_github_api("expected"))
    result = collect_evidence.hosted_checks_section(
        str(path), "expected", repo="acme/aether", token="test-token"
    )
    assert result["authoritative"] is True
    assert result["passed"] is True
    assert result["github_verified"] is True


def test_hosted_evidence_rejects_api_head_sha_mismatch(tmp_path, monkeypatch):
    path = _hosted_file(tmp_path, "expected")
    monkeypatch.setattr(collect_evidence, "_github_api", _fake_github_api("other-sha"))
    result = collect_evidence.hosted_checks_section(
        str(path), "expected", repo="acme/aether", token="test-token"
    )
    assert result["passed"] is False
    assert any("head SHA mismatch" in failure for failure in result["failures"])


def test_hosted_evidence_rejects_api_workflow_path_mismatch(tmp_path, monkeypatch):
    path = _hosted_file(tmp_path, "expected")
    monkeypatch.setattr(
        collect_evidence, "_github_api",
        _fake_github_api("expected", workflow_path=".github/workflows/other.yml"),
    )
    result = collect_evidence.hosted_checks_section(
        str(path), "expected", repo="acme/aether", token="test-token"
    )
    assert result["passed"] is False
    assert any("belongs to" in failure for failure in result["failures"])


def test_hosted_evidence_rejects_api_unsuccessful_job(tmp_path, monkeypatch):
    path = _hosted_file(tmp_path, "expected")
    monkeypatch.setattr(
        collect_evidence, "_github_api",
        _fake_github_api("expected", job_conclusion="failure"),
    )
    result = collect_evidence.hosted_checks_section(
        str(path), "expected", repo="acme/aether", token="test-token"
    )
    assert result["passed"] is False
    assert any("job conclusion" in failure for failure in result["failures"])


def test_hosted_evidence_rejects_missing_hosted_artifact(tmp_path, monkeypatch):
    path = _hosted_file(tmp_path, "expected")
    monkeypatch.setattr(
        collect_evidence, "_github_api",
        _fake_github_api("expected", drop_artifacts=True),
    )
    result = collect_evidence.hosted_checks_section(
        str(path), "expected", repo="acme/aether", token="test-token"
    )
    assert result["passed"] is False
    assert any("missing from hosted run" in failure for failure in result["failures"])


def test_hosted_evidence_rejects_api_errors_fail_closed(tmp_path, monkeypatch):
    path = _hosted_file(tmp_path, "expected")

    def broken(repo, api_path, token):
        raise OSError("network unreachable")

    monkeypatch.setattr(collect_evidence, "_github_api", broken)
    result = collect_evidence.hosted_checks_section(
        str(path), "expected", repo="acme/aether", token="test-token"
    )
    assert result["authoritative"] is False
    assert any("GitHub API verification failed" in f for f in result["failures"])


def test_hosted_evidence_recomputes_local_artifact_checksums(tmp_path, monkeypatch):
    import hashlib

    artifact = tmp_path / "evidence.zip"
    artifact.write_bytes(b"evidence-bytes")
    digest = hashlib.sha256(b"evidence-bytes").hexdigest()

    path = _hosted_file(tmp_path, "expected")
    payload = json.loads(path.read_text())
    for row in payload["checks"]:
        row["artifact_path"] = str(artifact)
        row["artifact_sha256"] = digest
    path.write_text(json.dumps(payload))

    monkeypatch.setattr(collect_evidence, "_github_api", _fake_github_api("expected"))
    result = collect_evidence.hosted_checks_section(
        str(path), "expected", repo="acme/aether", token="test-token"
    )
    assert result["passed"] is True

    # A claimed digest that does not match the recomputed one must fail.
    for row in payload["checks"]:
        row["artifact_sha256"] = "b" * 64
    path.write_text(json.dumps(payload))
    result = collect_evidence.hosted_checks_section(
        str(path), "expected", repo="acme/aether", token="test-token"
    )
    assert result["passed"] is False
    assert any("checksum mismatch" in failure for failure in result["failures"])


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


# ── Path-scoped merge-blocker semantics ────────────────────────────────────


_FAKE_WORKFLOW = """name: Fake SDK Validation
on:
  pull_request:
    paths:
      - 'packages/shared/**'
jobs:
  sdk-js:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/upload-artifact@v4
        with:
          name: sdk-js-release-evidence
"""

_FAKE_UNFILTERED_WORKFLOW = """name: Fake SDK Validation
on:
  pull_request:
jobs:
  sdk-js:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/upload-artifact@v4
        with:
          name: sdk-js-release-evidence
"""


def _fixture_root(tmp_path: Path, merge_flag: str, workflow_text: str) -> Path:
    catalog = {
        "version": 1,
        "allowed_terminal_conclusions": ["success"],
        "branch_protection": {
            "repository": "origin", "branch": "main",
            "verification_required_for_release": True,
            "unavailable_action": "admin must export ruleset evidence",
        },
        "checks": [{
            "id": "sdk-js",
            "workflow": ".github/workflows/fake.yml",
            "job": "sdk-js",
            "applicability": ["shared_contracts"],
            merge_flag: True,
            "blocks_sdk_release": True,
            "blocks_founding_tenant_release": True,
            "runner_class": "ubuntu",
            "evidence_artifact": "sdk-js-release-evidence",
        }],
    }
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config/required_release_checks.yaml").write_text(
        yaml.safe_dump(catalog), encoding="utf-8"
    )
    wf = tmp_path / ".github/workflows/fake.yml"
    wf.parent.mkdir(parents=True, exist_ok=True)
    wf.write_text(workflow_text, encoding="utf-8")
    return tmp_path


def test_catalog_marks_path_filtered_sdk_checks_as_path_scoped_blockers():
    catalog = yaml.safe_load((ROOT / "config/required_release_checks.yaml").read_text())
    for row in catalog["checks"]:
        assert row.get("blocks_pr_merge") is not True, (
            f"{row['id']}: path-filtered workflow must not claim a universal "
            "merge block"
        )
        assert row.get("blocks_pr_merge_when_paths_touched") is True


def test_validator_rejects_universal_merge_block_on_path_filtered_workflow(tmp_path):
    root = _fixture_root(tmp_path, "blocks_pr_merge", _FAKE_WORKFLOW)
    errors = check_required_checks.validate(root)
    assert any("blocks_pr_merge_when_paths_touched" in e for e in errors)


def test_validator_accepts_path_scoped_block_on_path_filtered_workflow(tmp_path):
    root = _fixture_root(tmp_path, "blocks_pr_merge_when_paths_touched", _FAKE_WORKFLOW)
    assert check_required_checks.validate(root) == []


def test_validator_rejects_path_scoped_block_on_unfiltered_workflow(tmp_path):
    root = _fixture_root(
        tmp_path, "blocks_pr_merge_when_paths_touched", _FAKE_UNFILTERED_WORKFLOW
    )
    errors = check_required_checks.validate(root)
    assert any("requires a" in e and "paths-filtered" in e for e in errors)
