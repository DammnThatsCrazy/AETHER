"""Regression tests for exact-source staging release acquisition."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
DEPLOY_WORKFLOW = ROOT / ".github" / "workflows" / "deploy.yml"


def _deploy_document() -> dict:
    return yaml.safe_load(DEPLOY_WORKFLOW.read_text(encoding="utf-8"))


def _step(job: dict, name: str) -> dict:
    return next(step for step in job["steps"] if step.get("name") == name)


def test_staging_source_run_is_the_successful_exact_main_sha_build():
    document = _deploy_document()
    acquire = document["jobs"]["acquire-release"]
    identity = _step(acquire, "Verify source run identity before trusting its artifacts")
    script = identity["run"]

    assert "github.event_name == 'workflow_dispatch'" in acquire["if"]
    assert "inputs.source_run_id != ''" in acquire["if"]
    assert "repos/${GITHUB_REPOSITORY}/actions/runs/${SOURCE_RUN_ID}" in script
    assert "test \"$run_path\" = '.github/workflows/deploy.yml'" in script
    assert "test \"$run_conclusion\" = 'success'" in script
    assert 'if [ "$TARGET_ENV" = staging ]; then' in script
    assert 'test "$run_head_branch" = main' in script
    assert 'test "$run_head_sha" = "$GITHUB_SHA"' in script
    assert (
        'select(.name == "Build immutable release once" and .conclusion == "success")'
        in script
    )
    assert 'test "$build_ok" -ge 1' in script

    identity_index = acquire["steps"].index(identity)
    artifact_download = next(
        index
        for index, step in enumerate(acquire["steps"])
        if step.get("uses") == "actions/download-artifact@v4"
    )
    assert identity_index < artifact_download
    assert (
        acquire["steps"][artifact_download]["with"]["run-id"]
        == "${{ inputs.source_run_id }}"
    )


def test_release_manifest_sha_is_bound_to_source_run_and_approved_checksum():
    acquire = _deploy_document()["jobs"]["acquire-release"]
    manifest = _step(acquire, "Verify approved manifest and every artifact")
    script = manifest["run"]

    assert manifest["env"]["SOURCE_RUN_ID"] == "${{ inputs.source_run_id }}"
    assert "actions/runs/${SOURCE_RUN_ID}" in script
    assert "--jq '.head_sha'" in script
    assert 'test "$SHA" = "$SOURCE_RUN_SHA"' in script
    assert (
        'python scripts/release/release_manifest.py release.json '
        '--expected-sha "$SHA" --checksum "$RELEASE_MANIFEST_CHECKSUM"'
    ) in script
    assert manifest["env"]["TARGET_ENV"] == "${{ inputs.environment }}"
    assert "environment=staging" in script
    assert "deployment_lane=full" in script
    assert "release_manifest_checksum=${RELEASE_MANIFEST_CHECKSUM}" in script
    assert "backend_image_digest=${digest}" in script


def test_deployment_evidence_binds_environment_lane_commit_manifest_and_image():
    deploy = _deploy_document()["jobs"]["deploy"]
    evidence = _step(deploy, "Initialize exact deployment provenance evidence")

    assert evidence["env"]["TARGET_ENV"] == "${{ github.event_name == 'push' && 'staging' || inputs.environment }}"
    assert evidence["env"]["DEPLOYMENT_LANE"] == (
        "${{ github.event_name == 'push' && 'pilot' || inputs.deployment_lane || 'full' }}"
    )
    for marker in (
        "environment=%s\\n",
        "deployment_lane=%s\\n",
        "commit_sha=%s\\n",
        "release_manifest_checksum=%s\\n",
        "backend_image_digest=%s\\n",
    ):
        assert marker in evidence["run"]
    upload = next(
        step for step in deploy["steps"]
        if step.get("uses") == "actions/upload-artifact@v4"
        and step.get("with", {}).get("name") == "deployment-evidence-${{ github.run_id }}"
    )
    assert upload["with"]["path"] == "deployment-evidence.txt"


def test_acquiring_source_release_skips_rebuild_and_deploy_uses_acquired_artifact():
    jobs = _deploy_document()["jobs"]
    acquire = jobs["acquire-release"]
    build = jobs["build"]
    deploy = jobs["deploy"]

    assert "inputs.source_run_id != ''" in acquire["if"]
    assert "acquire-release" in build["needs"]
    assert "needs.acquire-release.result == 'skipped'" in build["if"]

    deploy_condition = " ".join(deploy["if"].split())
    assert (
        "needs.build.result == 'success' && needs.acquire-release.result == 'skipped'"
        in deploy_condition
    )
    assert (
        "needs.acquire-release.result == 'success' && needs.build.result == 'skipped'"
        in deploy_condition
    )

    artifact_download = next(
        step for step in deploy["steps"] if step.get("uses") == "actions/download-artifact@v4"
    )
    expected_artifact = (
        "${{ needs.acquire-release.result == 'success' && 'approved-release' || "
        "format('release-{0}', github.sha) }}"
    )
    assert (
        artifact_download["with"]["name"]
        == expected_artifact
    )


def test_deploy_job_uses_a_stable_actions_api_identity():
    deploy = _deploy_document()["jobs"]["deploy"]

    assert deploy["name"] == "Deploy exact release"
