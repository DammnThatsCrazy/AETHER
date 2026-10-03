from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/identity_staging_capture.py"
SPEC = importlib.util.spec_from_file_location("identity_staging_capture", SCRIPT)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def test_runner_emits_projection_level_jobs_and_graph_transitions():
    capture = {
        "captured_at": "2026-09-28T12:00:00+00:00",
        "tenant_ref": "tenant:hashed",
        "contract_inventory": {"required_contract_ids": ["canonical-entity"], "observed_contract_ids": ["canonical-entity"]},
        "scenario_results": [],
        "merges": [],
        "splits": [],
        "restatement_jobs": [{
            "job_id": "job:hashed", "status": "partially_succeeded",
            "source_graph_version": "g1", "resulting_graph_version": "g2",
            "completed_at": "2026-09-28T12:00:00+00:00",
            "projection_status": {"profile_360": "completed", "syndicates": "unsupported"},
        }],
        "projection_outcomes": [{"projection": "profile_360", "status": "completed"}],
        "feature_flags": {"sdk_late_binding_enabled": True},
        "evidence": {"api_metrics": {}},
    }
    data = {"deployment_id": "stage-1", "observed_at": "2026-09-28T12:00:00+00:00", "capture": capture}

    manifest, evidence = runner.build_manifest(data, commit_sha="a" * 40, branch="staging")

    jobs = manifest["restatement_jobs"]
    assert [(job["projection"], job["status"]) for job in jobs] == [
        ("profile_360", "succeeded"), ("syndicates", "failed")
    ]
    assert manifest["graph_versions"] == [{
        "tenant_id": "tenant:hashed", "graph": "canonical_graph_version",
        "before": "g1", "after": "g2",
        "observed_at": "2026-09-28T12:00:00+00:00",
        "evidence_id": "identity-graph-versions",
    }]
    assert manifest["scenarios"] == []
    assert "sdk_late_binding_enabled" in manifest["feature_flags"]["required_enabled"]
    assert evidence["restatement_job"]["restatement_jobs"] == capture["restatement_jobs"]


def test_runner_preserves_absent_job_and_scenario_evidence_as_absent():
    capture = {
        "tenant_ref": "tenant:hashed", "contract_inventory": {}, "scenario_results": [],
        "merges": [], "splits": [], "restatement_jobs": [], "projection_outcomes": [],
        "feature_flags": {}, "evidence": {},
    }
    manifest, _ = runner.build_manifest(
        {"deployment_id": "stage-1", "observed_at": "now", "capture": capture},
        commit_sha="b" * 40, branch="staging",
    )
    assert manifest["scenarios"] == []
    assert manifest["restatement_jobs"] == []
    assert manifest["feature_flags"]["required_enabled"] == list(runner.REQUIRED_STAGING_IDENTITY_FLAGS)


def _scenario_capture(tmp_path: Path, *, digest_override: str | None = None):
    tenant_ref = "tenant:hmac-reference"
    deployment_id = "stage-deployment-1"
    execution_id = "07f97f5e-6abe-4cff-8ec6-0899d8ace700"
    scenario_id = "A_import_first_sdk_later"
    artifact = {
        "scenario_id": scenario_id, "execution_id": execution_id,
        "tenant_ref": tenant_ref, "outcome": "passed",
        "assertions_passed": 4, "assertions_failed": 0,
    }
    raw = (json.dumps(artifact, sort_keys=True, separators=(",", ":")) + "\n").encode()
    digest = digest_override or hashlib.sha256(raw).hexdigest()
    directory = tmp_path / "identity-continuity-scenarios"
    directory.mkdir()
    (directory / f"{scenario_id}.json").write_bytes(raw)
    (directory / "run-summary.json").write_text(json.dumps({
        "complete": True, "execution_id": execution_id,
        "tenant_ref": tenant_ref, "deployment_id": deployment_id,
        "results": [{
            "scenario_id": scenario_id, "outcome": "passed", "recorded": True,
            "evidence_sha256": digest, "assertions_passed": 4, "assertions_failed": 0,
        }],
    }), encoding="utf-8")
    data = {
        "deployment_id": deployment_id,
        "capture": {
            "tenant_ref": tenant_ref,
            "scenario_results": [{
                "id": scenario_id, "status": "passed", "evidence_sha256": digest,
                "execution_ref": "execution:hmac-reference",
                "assertions_passed": 4, "assertions_failed": 0,
            }],
        },
    }
    return data, directory, execution_id, tenant_ref, deployment_id


def test_runner_binds_exact_scenario_bytes_to_durable_capture(tmp_path):
    data, directory, execution_id, tenant_ref, deployment_id = _scenario_capture(tmp_path)

    scenario_run, artifacts = runner._bind_scenario_artifacts(data, directory, tmp_path)

    assert scenario_run == {
        "execution_id": execution_id, "tenant_ref": tenant_ref,
        "deployment_id": deployment_id,
    }
    assert artifacts == [{
        "scenario_id": "A_import_first_sdk_later",
        "path": "identity-continuity-scenarios/A_import_first_sdk_later.json",
    }]


def test_runner_rejects_artifact_digest_that_differs_from_durable_capture(tmp_path):
    data, directory, *_ = _scenario_capture(tmp_path, digest_override="0" * 64)

    with pytest.raises(RuntimeError, match="exact-byte digest"):
        runner._bind_scenario_artifacts(data, directory, tmp_path)


def test_runner_binds_playwright_ui_artifacts_as_fixture_only_supplemental_evidence(tmp_path):
    from hashlib import sha256

    ui_root = tmp_path / "playwright-ui"
    test_output = ui_root / "test-case"
    test_output.mkdir(parents=True)
    screenshot = b"\x89PNG\r\n\x1a\nfixture-png-bytes"
    observations = {
        "schema_version": "aether.identity-ui-evidence.v1",
        "evidence_class": "ui_fixture_only", "api_mode": "playwright_route_fixture",
        "live_staging_claim": False, "test_id": "activation renders fixture state",
        "surface": "activation", "tenant_ref": "tenant_identity_e2e_a",
    }
    (test_output / "screenshot.png").write_bytes(screenshot)
    observation_bytes = (json.dumps(observations, indent=2) + "\n").encode()
    (test_output / "observations.json").write_bytes(observation_bytes)
    (test_output / "manifest.json").write_text(json.dumps({
        "schema_version": "aether.identity-ui-evidence-manifest.v1",
        "evidence_class": "ui_fixture_only", "api_mode": "playwright_route_fixture",
        "test_id": observations["test_id"], "surface": "activation",
        "tenant_ref": observations["tenant_ref"], "captured_at": "2026-09-28T12:00:00Z",
        "files": {"screenshot": "screenshot.png", "structured": "observations.json"},
    }), encoding="utf-8")

    items = runner._bind_ui_fixture_evidence(ui_root, tmp_path)

    assert len(items) == 1
    item = items[0]
    assert item["evidence_class"] == "ui_fixture_only"
    assert item["api_mode"] == "playwright_route_fixture"
    assert item["live_staging_claim"] is False
    assert (tmp_path / item["screenshot_path"]).read_bytes() == screenshot
    assert item["screenshot_sha256"] == sha256(screenshot).hexdigest()
    assert (tmp_path / item["structured_path"]).read_bytes() == observation_bytes


def test_runner_rejects_ui_artifact_that_claims_live_staging(tmp_path):
    ui_root = tmp_path / "playwright-ui"
    test_output = ui_root / "test-case"
    test_output.mkdir(parents=True)
    (test_output / "screenshot.png").write_bytes(b"\x89PNG\r\n\x1a\nimage")
    (test_output / "observations.json").write_text(json.dumps({
        "schema_version": "aether.identity-ui-evidence.v1", "evidence_class": "ui_fixture_only",
        "api_mode": "playwright_route_fixture", "live_staging_claim": True,
        "test_id": "bad", "surface": "activation", "tenant_ref": "tenant_identity_e2e_a",
    }), encoding="utf-8")
    (test_output / "manifest.json").write_text(json.dumps({
        "schema_version": "aether.identity-ui-evidence-manifest.v1", "evidence_class": "ui_fixture_only",
        "api_mode": "playwright_route_fixture", "test_id": "bad", "surface": "activation",
        "tenant_ref": "tenant_identity_e2e_a", "captured_at": "2026-09-28T12:00:00Z",
        "files": {"screenshot": "screenshot.png", "structured": "observations.json"},
    }), encoding="utf-8")

    with pytest.raises(RuntimeError, match="structured UI artifact does not match"):
        runner._bind_ui_fixture_evidence(ui_root, tmp_path)


def _write_live_ui_capture(root: Path, *, surface: str, deployment_id: str = "stage-deployment-1") -> None:
    output = root / surface
    output.mkdir(parents=True)
    tenant_ref = "tenant:hmac-reference"
    evidence_id = hashlib.sha256(f"{surface}-{deployment_id}".encode()).hexdigest()[:24]
    test_id = f"live {surface}"
    screenshot_name = f"{evidence_id}-screenshot.png"
    structured_name = f"{evidence_id}-observations.json"
    paths = {
        "activation": ["/v1/me", "/v1/capabilities", "/v1/admin/identity/activation-status"],
        "review_queue": ["/v1/me", "/v1/capabilities", "/v1/admin/identity/review-queue"],
    }[surface]
    observations = {
        "schema_version": "aether.identity-ui-evidence.v2",
        "evidence_class": "ui_live_staging",
        "api_mode": "authenticated_real_backend",
        "live_staging_claim": True,
        "deployment_id": deployment_id,
        "tenant_ref": tenant_ref,
        "test_id": test_id,
        "surface": surface,
        "page_origin": "https://app.example.test",
        "api_origin": "https://api.example.test",
        "api_observations": [{"path": path, "method": "GET", "status": 200} for path in paths],
    }
    (output / screenshot_name).write_bytes(b"\x89PNG\r\n\x1a\nreal-ui-screenshot")
    (output / structured_name).write_text(json.dumps(observations), encoding="utf-8")
    (output / f"{evidence_id}-manifest.json").write_text(json.dumps({
        "schema_version": "aether.identity-ui-live-evidence-manifest.v1",
        "id": evidence_id,
        "evidence_class": "ui_live_staging",
        "api_mode": "authenticated_real_backend",
        "tenant_ref": tenant_ref,
        "deployment_id": deployment_id,
        "test_id": test_id,
        "surface": surface,
        "captured_at": "2026-10-02T12:00:00Z",
        "files": {"screenshot": screenshot_name, "structured": structured_name},
    }), encoding="utf-8")


def test_runner_requires_and_binds_both_authenticated_live_ui_surfaces(tmp_path):
    ui_root = tmp_path / "live-ui"
    ui_root.mkdir()
    _write_live_ui_capture(ui_root, surface="activation")
    _write_live_ui_capture(ui_root, surface="review_queue")

    items = runner._bind_ui_live_evidence(
        ui_root,
        tmp_path / "capture",
        deployment_id="stage-deployment-1",
        tenant_ref="tenant:hmac-reference",
        api_base_url="https://api.example.test",
    )

    assert {item["surface"] for item in items} == {"activation", "review_queue"}
    assert all(item["evidence_class"] == "ui_live_staging" for item in items)
    assert all(item["live_staging_claim"] is True for item in items)


def test_runner_rejects_live_ui_proof_bound_to_another_deployment(tmp_path):
    ui_root = tmp_path / "live-ui"
    ui_root.mkdir()
    _write_live_ui_capture(ui_root, surface="activation", deployment_id="different-deployment")

    with pytest.raises(RuntimeError, match="authenticated staging tenant and deployment"):
        runner._bind_ui_live_evidence(
            ui_root,
            tmp_path / "capture",
            deployment_id="stage-deployment-1",
            tenant_ref="tenant:hmac-reference",
            api_base_url="https://api.example.test",
        )
