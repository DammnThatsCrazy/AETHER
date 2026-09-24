"""Regression checks for staging's exact immutable-delivery handoff.

These tests inspect workflow YAML and embedded shell only. They never dispatch
GitHub workflows or invoke AWS commands.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


def _workflow_text(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def _workflow(name: str) -> dict:
    return yaml.safe_load(_workflow_text(name))


def _workflow_dispatch_inputs(document: dict) -> dict:
    # PyYAML's YAML 1.1 resolver parses GitHub's bare `on` key as True.
    triggers = document.get("on", document.get(True)) or {}
    return triggers["workflow_dispatch"]["inputs"]


def _steps(document: dict, job: str) -> list[dict]:
    return list(document["jobs"][job].get("steps") or [])


def _named_step(document: dict, job: str, name: str) -> dict:
    matches = [step for step in _steps(document, job) if step.get("name") == name]
    assert len(matches) == 1, f"expected one {job!r} step named {name!r}, got {len(matches)}"
    return matches[0]


def test_rehearsal_hands_the_exact_release_inputs_to_canonical_deploy() -> None:
    lifecycle = _workflow("staging-lifecycle.yml")
    deploy = _workflow("deploy.yml")
    handoff = _named_step(
        lifecycle,
        "wake-apply",
        "Dispatch canonical immutable delivery for the exact release",
    )
    script = re.sub(r"\\\n\s*", " ", handoff["run"])

    assert handoff["id"] == "delivery"
    assert str(handoff["if"]).strip() == "needs.select-profile.outputs.rehearse == 'true'"
    assert handoff["env"]["RELEASE_RUN_ID"] == "${{ inputs.release_run_id }}"
    assert handoff["env"]["RELEASE_MANIFEST_CHECKSUM"] == "${{ inputs.release_manifest_checksum }}"
    assert "gh workflow run deploy.yml --ref \"$REF_NAME\"" in script
    assert '-f environment=staging' in script
    assert '-f deployment_lane="$DEPLOYMENT_LANE"' in script
    assert "-f delivery_mode=deploy" in script
    assert '-f source_run_id="$RELEASE_RUN_ID"' in script
    assert '-f release_manifest_checksum="$RELEASE_MANIFEST_CHECKSUM"' in script

    deploy_inputs = _workflow_dispatch_inputs(deploy)
    assert {
        "environment",
        "deployment_lane",
        "delivery_mode",
        "source_run_id",
        "release_manifest_checksum",
    } <= set(deploy_inputs)


def test_handoff_correlates_the_returned_run_and_requires_exact_success_outcomes() -> None:
    lifecycle = _workflow("staging-lifecycle.yml")
    handoff = _named_step(
        lifecycle,
        "wake-apply",
        "Dispatch canonical immutable delivery for the exact release",
    )
    script = handoff["run"]

    assert "actions/runs/([0-9]+)" in script
    assert 'test -n "$delivery_run_id"' in script
    assert '"repos/${GITHUB_REPOSITORY}/actions/runs/${delivery_run_id}"' in script
    assert '"repos/${GITHUB_REPOSITORY}/actions/runs/${delivery_run_id}/jobs?per_page=100"' in script
    assert 'test "$run_path" = \'.github/workflows/deploy.yml\'' in script
    assert 'test "$run_branch" = main && test "$run_sha" = "$INTENDED_RELEASE_SHA"' in script
    assert 'test "$conclusion" = success' in script
    assert 'select(.name == "Acquire approved staged release" and .conclusion == "success")' in script
    assert 'select(.name == "Build immutable release once" and .conclusion == "skipped")' in script
    assert 'select(.name == "Deploy exact release" and .conclusion == "success")' in script
    assert script.count('conclusion == "success"') >= 2
    assert 'test "$conclusion" = success' in script
    assert 'printf \'delivery_run_id=%s\\n\' "$delivery_run_id" >> "$GITHUB_OUTPUT"' in script
    assert "gh run list" not in script, "handoff must not guess the newest workflow run"

    wake_apply = lifecycle["jobs"]["wake-apply"]
    assert wake_apply["outputs"]["delivery_run_id"] == "${{ steps.delivery.outputs.delivery_run_id }}"


def test_rehearsal_downloads_deployment_evidence_from_that_exact_delivery_run() -> None:
    lifecycle = _workflow("staging-lifecycle.yml")
    wake_apply = lifecycle["jobs"]["wake-apply"]
    downloads = [
        step
        for step in _steps(lifecycle, "rehearse")
        if step.get("uses") == "actions/download-artifact@v4"
        and step.get("with", {}).get("name")
        == "deployment-evidence-${{ needs.wake-apply.outputs.delivery_run_id }}"
    ]

    assert len(downloads) == 1
    artifact = downloads[0]["with"]
    assert artifact["github-token"] == "${{ github.token }}"
    assert artifact["run-id"] == "${{ needs.wake-apply.outputs.delivery_run_id }}"
    assert artifact["path"] == "artifacts/rehearsal/delivery"
    assert wake_apply["outputs"]["delivery_run_id"] == "${{ steps.delivery.outputs.delivery_run_id }}"


def test_rehearsal_verifies_delivery_provenance_before_accepting_the_image() -> None:
    lifecycle = _workflow("staging-lifecycle.yml")
    step = _named_step(
        lifecycle,
        "rehearse",
        "Verify the exact immutable application artifact is what staging runs",
    )
    script = step["run"]

    for provenance in (
        "environment=staging",
        "deployment_lane=${DEPLOYMENT_LANE}",
        "commit_sha=${INTENDED_RELEASE_SHA}",
        "release_manifest_checksum=${RELEASE_MANIFEST_CHECKSUM}",
        "backend_image_digest=${digest}",
    ):
        assert provenance in script


def test_static_origin_verification_reads_s3_and_compares_without_remote_writes() -> None:
    lifecycle = _workflow("staging-lifecycle.yml")
    step = _named_step(
        lifecycle,
        "rehearse",
        "Verify canonical delivery published the approved static SPA artifacts",
    )
    script = step["run"]
    s3_commands = [
        line.strip()
        for line in script.splitlines()
        if re.search(r"\baws s3 (?:sync|cp|rm|mv)\b", line)
    ]

    assert len(s3_commands) == 1
    assert re.fullmatch(r'aws s3 sync "s3://\$\{bucket\}" "\$verify" --delete', s3_commands[0])
    assert 'diff -qr "$dist" "$verify"' in script
    assert not re.search(r"\baws s3 (?:cp|rm|mv)\b", script)
    assert not re.search(r'aws s3 sync [^\n]*\s+s3://', script), (
        "static verification must not use an S3 destination"
    )


def test_rehearsal_reuses_deploy_migration_evidence_without_a_second_run_task() -> None:
    lifecycle = _workflow("staging-lifecycle.yml")
    deploy = _workflow("deploy.yml")
    migration_check = _named_step(
        lifecycle,
        "rehearse",
        "Verify delivered migration and resulting database revision",
    )
    migration_script = migration_check["run"]
    rehearsal_scripts = [step.get("run", "") for step in _steps(lifecycle, "rehearse")]
    deploy_scripts = [step.get("run", "") for step in _steps(deploy, "deploy")]

    assert 'evidence="artifacts/rehearsal/delivery/deployment-evidence.txt"' in migration_script
    assert "grep -E '^migrations ' \"$evidence\"" in migration_script
    assert 'test "$(wc -l < artifacts/rehearsal/migrations.txt | tr -d \' \')" = 1' in migration_script
    assert '"https://${ALB_DNS_NAME}/v1/ready"' in migration_script
    assert "aws ecs run-task" not in migration_script
    assert "alembic upgrade head" not in migration_script
    assert not any("aws ecs run-task" in script for script in rehearsal_scripts), (
        "the rehearsal must not launch a second ECS task for migration"
    )

    migration_producers = [script for script in deploy_scripts if "aws ecs run-task" in script]
    assert len(migration_producers) == 1
    assert r'\"alembic\",\"upgrade\",\"head\"' in migration_producers[0]
    assert "printf 'migrations %s %s\\n' \"$migration_task\" \"$IMAGE\" >> deployment-evidence.txt" in migration_producers[0]
    assert any(
        step.get("uses") == "actions/upload-artifact@v4"
        and step.get("with", {}).get("name") == "deployment-evidence-${{ github.run_id }}"
        and step.get("with", {}).get("path") == "deployment-evidence.txt"
        for step in _steps(deploy, "deploy")
    )
