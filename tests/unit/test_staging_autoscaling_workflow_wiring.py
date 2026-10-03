"""Workflow wiring for staging autoscaling target ownership-tag reconciliation."""

import os
from pathlib import Path
import subprocess
import sys

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
    publication_index, publication = _named_step(
        rehearsal_steps, "Verify canonical delivery published the approved static SPA artifacts"
    )
    migration_index, _ = _named_step(
        rehearsal_steps, "Verify delivered migration and resulting database revision"
    )
    assert TAG_RECONCILER in rehearsal_preflight["run"]
    assert "--apply-missing-tags" not in rehearsal_preflight["run"]
    assert "pyyaml" in rehearsal_dependencies["run"]
    assert "boto3" in rehearsal_dependencies["run"]
    assert rehearsal_dependencies_index < rehearsal_preflight_index
    assert rehearsal_preflight_index < publication_index < migration_index
    assert 'aws s3 sync "s3://${bucket}" "$verify" --delete' in publication["run"]
    assert 'aws s3 sync "$dist" "s3://${bucket}"' not in publication["run"]


def test_ttl_preflight_failure_cannot_block_emergency_scale_to_zero():
    document = _workflow("staging-ttl-guard.yml")
    steps = _steps(document, "guard")
    dependency_index, dependencies = _named_step(steps, "Install guard dependencies")
    enforce_index, enforce = _named_step(steps, "Return staging to sleep (TTL exceeded)")
    condition = str(enforce["if"])
    run = enforce["run"]

    assert "steps.config.outputs.mode == 'enforce'" in condition
    assert "steps.state.outputs.ttl_expired == 'true'" in condition
    assert "steps.state.outputs.awake_tasks != '0'" not in condition
    assert "pyyaml" in dependencies["run"]
    assert "boto3" in dependencies["run"]
    assert dependency_index < enforce_index
    assert "if ! python scripts/release/ensure_staging_autoscaling_target_tags.py; then" in run
    assert "continuing TTL scale-to-zero cleanup" in run
    preflight_index = run.index(TAG_RECONCILER)
    target_floor_index = run.index("aws application-autoscaling register-scalable-target")
    service_scale_index = run.index("aws ecs update-service")
    assert preflight_index < target_floor_index < service_scale_index
    assert "--desired-count 0" in run
    assert "--min-capacity 0" in run
    assert "--max-capacity 0" in run
    assert "600" in run and "sleep 10" in run
    assert "for target in sorted(actual)" in run, (
        "an unexpected target inside the exact staging cluster could revive resources"
    )
    assert "--apply-missing-tags" not in run
    assert enforce_index < next(
        index for index, step in enumerate(steps) if step.get("id") == "verify"
    )


def _ttl_shell(tmp_path: Path, *, describe_failure: bool = False, zero_bounds: bool = False):
    """Run the workflow's shell against deterministic AWS CLI responses, never live AWS."""
    (tmp_path / "config").symlink_to(ROOT / "config", target_is_directory=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    aws = bin_dir / "aws"
    aws.write_text(
        """#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
log = pathlib.Path(os.environ['MOCK_AWS_LOG'])
with log.open('a') as out:
    out.write(' '.join(args) + '\\n')
cluster = 'AETHER-staging'
names = [cluster + '-backend', cluster + '-lean-worker']
arns = ['arn:aws:ecs:us-east-1:123456789012:service/' + cluster + '/' + name for name in names]
if os.environ.get('MOCK_DESCRIBE_FAILURE') == '1':
    arns.append('arn:aws:ecs:us-east-1:123456789012:service/' + cluster + '/ghost')
if args[:2] == ['application-autoscaling', 'describe-scalable-targets']:
    clamped = sum('register-scalable-target' in line for line in log.read_text().splitlines())
    bounds = 0 if os.environ.get('MOCK_ZERO_BOUNDS') == '1' or clamped >= 2 else 2
    print(json.dumps([{'id': 'service/' + cluster + '/' + name, 'min': 0, 'max': bounds} for name in names]))
elif args[:2] == ['application-autoscaling', 'register-scalable-target']:
    print('{}')
elif args[:2] == ['ecs', 'list-services']:
    print('\\t'.join(arns) if 'text' in args else json.dumps(arns))
elif args[:2] == ['ecs', 'describe-services']:
    rows = [{'arn': arn, 'name': name, 'desired': 0, 'running': 0, 'pending': 0} for arn, name in zip(arns, names)]
    print(json.dumps({'services': rows, 'failures': [{'arn': arns[-1], 'reason': 'MISSING'}] if len(arns) > 2 else []}))
elif args[:2] == ['ecs', 'list-tasks']:
    print('[]')
elif args[:2] == ['ssm', 'get-parameter']:
    print('ParameterNotFound', file=sys.stderr)
    sys.exit(255)
else:
    raise SystemExit('unexpected mock AWS call: ' + ' '.join(args))
""",
        encoding="utf-8",
    )
    aws.chmod(0o755)
    python = bin_dir / "python"
    python.write_text(
        '#!/bin/sh\nif [ "$1" = scripts/release/ensure_staging_autoscaling_target_tags.py ]; then exit 1; fi\nexec "$REAL_PYTHON" "$@"\n',
        encoding="utf-8",
    )
    python.chmod(0o755)
    env = os.environ.copy()
    env.update(
        PATH=f"{bin_dir}:{env['PATH']}",
        REAL_PYTHON=sys.executable,
        MOCK_AWS_LOG=str(tmp_path / "aws.log"),
        MOCK_DESCRIBE_FAILURE="1" if describe_failure else "0",
        MOCK_ZERO_BOUNDS="1" if zero_bounds else "0",
        RUNNER_TEMP=str(tmp_path),
        GITHUB_OUTPUT=str(tmp_path / "outputs"),
        GITHUB_STEP_SUMMARY=str(tmp_path / "summary"),
        STAGING_CLUSTER="AETHER-staging",
        AWAKE_LEASE_PARAM="/aether/staging/lifecycle/awake-until",
        LEASE="none",
        AWAKE_TASKS="0",
    )
    return env


def _run_ttl_step(tmp_path: Path, name: str, env: dict[str, str]):
    step = _named_step(_steps(_workflow("staging-ttl-guard.yml"), "guard"), name)[1]
    # macOS ships Bash 3.2 without mapfile; Actions' Ubuntu Bash has it.
    mapfile_compat = """if ! type mapfile >/dev/null 2>&1; then
mapfile() {
  local name="$2" data
  data="$(cat)"
  if [ -z "$data" ]; then
    eval "$name=()"
  else
    IFS=$'\\n' read -r -d '' -a "$name" <<< "$data" || true
  fi
}
fi
"""
    return subprocess.run(
        ["bash", "-e", "-c", mapfile_compat + step["run"]],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


def test_ttl_clamps_open_targets_with_no_current_tasks(tmp_path):
    env = _ttl_shell(tmp_path)
    result = _run_ttl_step(tmp_path, "Return staging to sleep (TTL exceeded)", env)
    assert result.returncode == 0, result.stdout + result.stderr
    calls = (tmp_path / "aws.log").read_text().splitlines()
    clamps = [call for call in calls if "register-scalable-target" in call]
    assert len(clamps) == 2
    assert all("--min-capacity 0 --max-capacity 0" in call for call in clamps)
    assert not any("ecs update-service" in call or "ecs stop-task" in call for call in calls)
    assert "changed=2" in (tmp_path / "outputs").read_text()
    assert "converged=true" in (tmp_path / "outputs").read_text()


def test_ttl_verify_rejects_partial_describe_services_response(tmp_path):
    env = _ttl_shell(tmp_path, describe_failure=True, zero_bounds=True)
    result = _run_ttl_step(tmp_path, "Verify staging is back at zero", env)
    assert result.returncode == 0, result.stdout + result.stderr
    outputs = (tmp_path / "outputs").read_text()
    assert "asleep=unknown" in outputs
    assert "asleep=true" not in outputs


def test_ttl_state_counts_task_arns_not_response_fields(tmp_path):
    env = _ttl_shell(tmp_path, zero_bounds=True)
    env.update(MAX_AWAKE_HOURS_CAP="8", MAX_TOTAL_AWAKE_HOURS="12", DEFAULT_MAX_AWAKE_HOURS="4")
    result = _run_ttl_step(tmp_path, "Read the awake lease and the live staging state", env)
    assert result.returncode == 0, result.stdout + result.stderr
    outputs = (tmp_path / "outputs").read_text()
    assert "awake_tasks=0" in outputs
    assert "ttl_expired=true" in outputs


def test_ttl_alert_never_calls_open_envelope_asleep(tmp_path):
    env = _ttl_shell(tmp_path)
    env.update(
        ARMED="true", MODE="enforce", STATE_KNOWN="true", TTL_EXPIRED="false",
        AWAKE_TASKS="0", RESIDUAL_TASKS="0", ASLEEP="false", REMAINING_MINUTES="30",
    )
    result = _run_ttl_step(tmp_path, "Blocking alert on an unaccountable staging environment", env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "open capacity envelope" in result.stdout
    assert "staging is asleep" not in result.stdout
    env["ASLEEP"] = "unknown"
    result = _run_ttl_step(tmp_path, "Blocking alert on an unaccountable staging environment", env)
    assert result.returncode != 0
    assert "exact asleep state could not be verified" in result.stdout
