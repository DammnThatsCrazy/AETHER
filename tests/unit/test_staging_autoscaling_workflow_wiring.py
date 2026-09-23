"""Workflow wiring for staging autoscaling target ownership-tag reconciliation."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
TAG_RECONCILER = "scripts/release/ensure_staging_autoscaling_target_tags.py"


def _workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOW_DIR / name).read_text(encoding="utf-8"))


def _steps(document: dict, job: str) -> list[dict]:
    return list(document["jobs"][job].get("steps") or [])


def _named_step(steps: list[dict], name: str) -> tuple[int, dict]:
    matches = [(index, step) for index, step in enumerate(steps) if step.get("name") == name]
    assert len(matches) == 1, f"expected exactly one step named {name!r}"
    return matches[0]


def test_terraform_promotion_preflights_awake_staging_and_reconciles_after_apply():
    steps = _steps(_workflow("terraform-promote.yml"), "apply")
    preflight_index, preflight = _named_step(
        steps, "Preflight staging autoscaling target ownership tags"
    )
    dependency_index, dependencies = _named_step(steps, "Install plan-validation dependencies")
    service_role_index, _ = _named_step(
        steps, "Ensure the ECS service-linked role exists before capacity providers"
    )
    apply_index, apply = _named_step(steps, "Apply the exact approved plan (never re-plan)")
    reconcile_index, reconcile = _named_step(
        steps, "Apply missing staging autoscaling target ownership tags"
    )
    verify_index, verify = _named_step(
        steps, "Verify staging autoscaling target ownership tags"
    )
    artifact_index = next(
        index
        for index, step in enumerate(steps)
        if str(step.get("uses", "")).startswith("actions/upload-artifact")
    )

    assert preflight["if"] == (
        "inputs.profile == 'staging' && "
        "steps.reviewed.outputs.staging_state != 'asleep'"
    )
    assert TAG_RECONCILER in preflight["run"]
    assert "--apply-missing-tags" not in preflight["run"]
    assert "--allow-missing-tags" in preflight["run"]
    assert "pyyaml" in dependencies["run"]
    assert "boto3" in dependencies["run"]
    assert dependency_index < preflight_index
    assert "terraform apply -input=false reviewed.tfplan" in apply["run"]
    assert preflight_index < service_role_index < apply_index

    assert reconcile["if"] == "inputs.profile == 'staging'"
    assert TAG_RECONCILER in reconcile["run"]
    assert "--apply-missing-tags" in reconcile["run"]
    assert verify["if"] == "inputs.profile == 'staging'"
    assert TAG_RECONCILER in verify["run"]
    assert "--apply-missing-tags" not in verify["run"]
    assert apply_index < reconcile_index < verify_index < artifact_index


def test_lifecycle_preflights_before_wake_lease_and_full_rehearsal_mutation():
    document = _workflow("staging-lifecycle.yml")
    events = document.get("on", document.get(True))
    lifecycle_actions = events["workflow_dispatch"]["inputs"]["action"]["options"]
    assert "apply-wake" in lifecycle_actions
    assert "full-rehearsal" in lifecycle_actions
    assert "needs.select-profile.outputs.apply_wake == 'true'" in str(
        document["jobs"]["wake-apply"]["if"]
    )
    assert "needs.select-profile.outputs.rehearse == 'true'" in str(
        document["jobs"]["rehearse"]["if"]
    )
    assert "needs.wake-apply.result == 'success'" in str(
        document["jobs"]["rehearse"]["if"]
    )

    wake_steps = _steps(document, "wake-apply")
    setup_index = next(
        index
        for index, step in enumerate(wake_steps)
        if step.get("uses") == "actions/setup-python@v5"
    )
    dependency_index, dependencies = _named_step(
        wake_steps, "Install autoscaling preflight dependencies"
    )
    credentials_index = next(
        index
        for index, step in enumerate(wake_steps)
        if str(step.get("uses", "")).startswith("aws-actions/configure-aws-credentials")
    )
    wake_preflight_index, wake_preflight = _named_step(
        wake_steps, "Preflight staging autoscaling target ownership tags before wake"
    )
    lease_index, _ = _named_step(wake_steps, "Open the bounded awake lease before apply")
    dispatch_index, _ = _named_step(
        wake_steps, "Dispatch the reviewed apply for the verified wake plan"
    )
    assert TAG_RECONCILER in wake_preflight["run"]
    assert "--apply-missing-tags" not in wake_preflight["run"]
    assert "--allow-missing-tags" in wake_preflight["run"]
    assert "pyyaml" in dependencies["run"]
    assert "boto3" in dependencies["run"]
    assert setup_index < dependency_index < credentials_index < wake_preflight_index
    assert credentials_index < wake_preflight_index < lease_index < dispatch_index

    rehearsal_steps = _steps(document, "rehearse")
    rehearsal_dependencies_index, rehearsal_dependencies = _named_step(
        rehearsal_steps, "Install rehearsal dependencies"
    )
    rehearsal_preflight_index, rehearsal_preflight = _named_step(
        rehearsal_steps,
        "Preflight staging autoscaling target ownership tags before rehearsal",
    )
    publication_index, _ = _named_step(
        rehearsal_steps, "Publish and verify the approved static SPA artifacts"
    )
    migration_index, _ = _named_step(
        rehearsal_steps, "Run migrations and verify the resulting revision"
    )
    assert TAG_RECONCILER in rehearsal_preflight["run"]
    assert "--apply-missing-tags" not in rehearsal_preflight["run"]
    assert "pyyaml" in rehearsal_dependencies["run"]
    assert "boto3" in rehearsal_dependencies["run"]
    assert rehearsal_dependencies_index < rehearsal_preflight_index
    assert rehearsal_preflight_index < publication_index < migration_index


def test_ttl_preflight_failure_cannot_block_emergency_scale_to_zero():
    document = _workflow("staging-ttl-guard.yml")
    steps = _steps(document, "guard")
    dependency_index, dependencies = _named_step(steps, "Install guard dependencies")
    enforce_index, enforce = _named_step(steps, "Return staging to sleep (TTL exceeded)")
    condition = str(enforce["if"])
    run = enforce["run"]

    assert "steps.config.outputs.mode == 'enforce'" in condition
    assert "steps.state.outputs.ttl_expired == 'true'" in condition
    assert "steps.state.outputs.awake_tasks != '0'" in condition
    assert "pyyaml" in dependencies["run"]
    assert "boto3" in dependencies["run"]
    assert dependency_index < enforce_index
    assert "if ! python scripts/release/ensure_staging_autoscaling_target_tags.py; then" in run
    assert "continuing TTL scale-to-zero cleanup" in run
    preflight_index = run.index(TAG_RECONCILER)
    service_scale_index = run.index("aws ecs update-service")
    target_floor_index = run.index("aws application-autoscaling register-scalable-target")
    assert preflight_index < service_scale_index < target_floor_index
    assert "--desired-count 0" in run
    assert "--min-capacity 0" in run
    assert "--apply-missing-tags" not in run
    assert enforce_index < next(
        index for index, step in enumerate(steps) if step.get("id") == "verify"
    )
