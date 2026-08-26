"""Regression guards for the staging apply contract.

These assertions cover failure modes that provider-mocked Terraform plans do
not prove: same-name ALB replacement, unstructured metric filters, workflow
ordering, and parity between the reviewed IAM manifest and its checker.
"""

from __future__ import annotations

import subprocess
import sys
import re
import importlib.util
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
TF = ROOT / "AWS Deployment/aether-aws/terraform"
ALB = TF / "modules/alb/main.tf"
MONITORING = TF / "modules/monitoring/main.tf"
PROMOTE = ROOT / ".github/workflows/terraform-promote.yml"
STATE_MIGRATION_WORKFLOW = ROOT / ".github/workflows/terraform-state-migrate.yml"
STATE_MIGRATION = ROOT / "scripts/release/migrate_alb_target_group_state.sh"
STATE_POLICY = ROOT / "config/terraform_state_access_policy.yaml"
STATE_POLICY_CHECKER = ROOT / "scripts/release/check_terraform_state_access_policy.py"
STATE_ROLE_CHECKER = ROOT / "scripts/release/verify_terraform_state_role.py"
POLICY = ROOT / "config/staging_apply_iam_policy.yaml"
POLICY_CHECKER = ROOT / "scripts/release/check_staging_apply_policy.py"


def test_staging_target_group_replacement_is_name_safe() -> None:
    text = ALB.read_text(encoding="utf-8")
    backend = re.search(
        r'resource "aws_lb_target_group" "backend"\s*\{(?P<body>.*?)(?=\nresource "aws_lb_target_group"|\nmoved \{)',
        text,
        flags=re.DOTALL,
    )
    replacement = re.search(
        r'resource "aws_lb_target_group" "backend_replacement"\s*\{(?P<body>.*?)(?=\n(?:locals \{|resource "|moved \{))',
        text,
        flags=re.DOTALL,
    )
    assert backend and replacement
    assert 'name        = "${lower(var.project)}-${var.environment}-backend"' in backend.group("body")
    assert 'count = var.environment == "staging" ? 1 : 0' in backend.group("body")
    assert 'create_before_destroy = false' in backend.group("body")
    assert 'name        = "${lower(var.project)}-${var.environment}-backend"' in replacement.group("body")
    assert 'count = var.environment != "staging" ? 1 : 0' in replacement.group("body")
    assert 'create_before_destroy = true' in replacement.group("body")
    migration = STATE_MIGRATION.read_text(encoding="utf-8")
    assert "legacy='module.alb.aws_lb_target_group.backend'" in migration
    assert "staging) target='module.alb.aws_lb_target_group.backend[0]'" in migration
    assert "production-lean|production-scale|enterprise-isolated|demo|preview)" in migration
    assert "backend_replacement[0]" in migration
    assert 'terraform state mv -lock-timeout=5m "$legacy" "$target"' in migration
    migration_workflow = STATE_MIGRATION_WORKFLOW.read_text(encoding="utf-8")
    assert "MIGRATE-TARGET-GROUP" in migration_workflow
    assert "group: terraform-${{ inputs.profile }}" in migration_workflow
    assert "terraform-promote.yml" not in migration

    promote = PROMOTE.read_text(encoding="utf-8")
    plan_job = promote[promote.index("  plan:"):promote.index("  apply:")]
    init_end = plan_job.index('-backend-config="encrypt=true"')
    legacy_check = plan_job.index("legacy backend target-group state address remains")
    plan_command = plan_job.index("terraform plan -input=false")
    assert init_end < legacy_check < plan_command
    assert "terraform-state-migrate workflow" in plan_job
    assert "Validate reviewed staging maintenance target group" in PROMOTE.read_text(encoding="utf-8")
    assert "aether-staging-maintenance" in PROMOTE.read_text(encoding="utf-8")
    assert "describe-target-groups" in PROMOTE.read_text(encoding="utf-8")
    assert "Require live listener detachment before target-group replacement" in PROMOTE.read_text(encoding="utf-8")
    assert "describe-listeners" in PROMOTE.read_text(encoding="utf-8")


def test_unstructured_runtime_metric_filter_has_no_dimensions() -> None:
    text = MONITORING.read_text(encoding="utf-8")
    start = text.index('resource "aws_cloudwatch_log_metric_filter" "runtime_role_unhealthy"')
    end = text.index('resource "aws_cloudwatch_metric_alarm" "runtime_role_unhealthy"', start)
    block = text[start:end]
    assert not re.search(r"^\s*dimensions\s*=", block, re.MULTILINE)


def test_ecs_service_linked_role_precedes_reviewed_apply() -> None:
    text = PROMOTE.read_text(encoding="utf-8")
    create = text.index("aws iam create-service-linked-role --aws-service-name ecs.amazonaws.com")
    wait = text.index("aws iam get-role --role-name AWSServiceRoleForECS", create)
    apply = text.index("terraform apply", wait)
    assert create < wait < apply
    assert "iam:CreateServiceLinkedRole" in POLICY.read_text(encoding="utf-8")
    manifest = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    get_role = next(s for s in manifest["statements"] if "iam:GetRole" in s["actions"])
    assert get_role["resource"].endswith(
        "role/aws-service-role/ecs.amazonaws.com/AWSServiceRoleForECS"
    )
    assert "has been taken" in text
    role_step = text[text.index("Ensure the ECS service-linked role"):text.index("Apply the exact approved plan")]
    assert "Every selectable profile provisions the ECS capacity-provider" in role_step
    assert "if: inputs.profile == 'staging'" not in role_step


def test_external_provider_validation_precedes_service_linked_role() -> None:
    text = PROMOTE.read_text(encoding="utf-8")
    provider = text.index("Validate AWS and external-provider apply inputs")
    service_role = text.index("Ensure the ECS service-linked role")
    assert provider < service_role
    assert "check_provider_apply_inputs.py" in text[provider:service_role]


def test_state_access_contract_is_explicit_and_checked() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(STATE_POLICY_CHECKER),
            "--manifest",
            str(STATE_POLICY),
            "--terraform-root",
            str(TF),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    manifest = yaml.safe_load(STATE_POLICY.read_text(encoding="utf-8"))
    actions = {action for statement in manifest["statements"] for action in statement["actions"]}
    assert {"s3:ListBucket", "s3:GetObject", "s3:PutObject", "dynamodb:DeleteItem"} <= actions
    assert manifest["state_lock_table"] == "aether-terraform-locks"
    assert "aether-terraform-locks" in STATE_POLICY.read_text(encoding="utf-8")
    list_bucket = next(s for s in manifest["statements"] if "s3:ListBucket" in s["actions"])
    assert list_bucket["conditions"] == {"StringLike": {"s3:prefix": ["profiles/*"]}}
    assert "--terraform-root" in PROMOTE.read_text(encoding="utf-8")
    assert STATE_ROLE_CHECKER.exists()
    assert "verify_terraform_state_role.py" in PROMOTE.read_text(encoding="utf-8")
    verifier = STATE_ROLE_CHECKER.read_text(encoding="utf-8")
    assert "s3:GetBucketVersioning" in verifier
    assert "s3:GetBucketLocation" in verifier


def test_state_role_checker_accepts_the_reviewed_staging_backend_alias() -> None:
    spec = importlib.util.spec_from_file_location("verify_state_role", STATE_ROLE_CHECKER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.validate_backend_names(
        "aether-staging-terraform-state-olympus", "aether-staging-terraform-lock"
    ) == []
    assert module.validate_backend_names("unreviewed-state", "unreviewed-lock")
    assert module.validate_state_key("profiles/staging/terraform.tfstate") == []
    assert module.validate_state_key("profiles/access-probe")
    assert "--state-key" in PROMOTE.read_text(encoding="utf-8")
    migration_workflow = STATE_MIGRATION_WORKFLOW.read_text(encoding="utf-8")
    assert "TF_STATE_KEY: profiles/${{ inputs.profile }}/terraform.tfstate" in migration_workflow
    assert "--state-key \"$TF_STATE_KEY\"" in migration_workflow


def test_apply_revalidates_before_service_linked_role_mutation() -> None:
    text = PROMOTE.read_text(encoding="utf-8")
    revalidate = text.index("Re-validate the reviewed plan against policy and cost model")
    bootstrap = text.index("Ensure the ECS service-linked role exists before capacity providers")
    assert revalidate < bootstrap


def test_target_group_lookup_fails_closed_on_non_not_found_errors() -> None:
    text = PROMOTE.read_text(encoding="utf-8")
    start = text.index("existing_tg=")
    end = text.index("terraform apply", start)
    block = text[start:end]
    assert "TargetGroupNotFound" in block
    assert "unable to verify aether-staging-backend" in block
    assert "2>/dev/null || true" not in block


def test_apply_uses_reviewed_listener_artifact_when_dispatch_input_is_omitted() -> None:
    """Lifecycle apply must not reject a valid plan because an optional input is blank."""
    text = PROMOTE.read_text(encoding="utf-8")
    start = text.index("      - name: Verify reviewed plan metadata, profile and 24h expiry")
    end = text.index("      # Bind the apply to the plan's OWN commit", start)
    verify = text[start:end]
    assert "listener_target_group_arn=%s\\n" in verify
    assert 'if [ -n "${STAGING_LISTENER_TARGET_GROUP_ARN:-}" ]' in verify
    assert "steps.reviewed.outputs.listener_target_group_arn" in text
    assert "maintenance listener ARN differs between reviewed plan and apply dispatch" in verify


def test_maintenance_target_validation_is_only_for_replacements() -> None:
    """An existing backend target group must not be mistaken for a maintenance target."""
    text = PROMOTE.read_text(encoding="utf-8")
    start = text.index("      - name: Validate reviewed staging maintenance target group")
    end = text.index("      - name: Require live listener detachment before target-group replacement", start)
    validation = text[start:end]
    replacement_guard = validation.index("reviewed.tfplan.json")
    name_guard = validation.index("aether-staging-maintenance")
    assert replacement_guard < name_guard
    assert "index(\"delete\") != null and index(\"create\") != null" in validation


def test_reviewed_iam_manifest_matches_checker() -> None:
    result = subprocess.run(
        [sys.executable, str(POLICY_CHECKER), "--manifest", str(POLICY), "--profile", "staging"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout

    manifest = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    statements = manifest["statements"]
    flow_logs = next(s for s in statements if s["sid"] == "PassOnlyStagingFlowLogsRole")
    assert flow_logs["resource"].endswith("AETHER-staging-vpc-flow-logs-role")
    assert flow_logs["conditions"]["iam:PassedToService"] == ["vpc-flow-logs.amazonaws.com"]
    notifications = next(s for s in statements if s["sid"] == "ConfigureStagingNotifications")
    assert "sns:DeleteTopic" in notifications["actions"]
    assert "elasticloadbalancing:DescribeTargetGroups" in {
        action for statement in statements for action in statement["actions"]
    }
    assert "elasticloadbalancing:DescribeLoadBalancers" in {
        action for statement in statements for action in statement["actions"]
    }
    assert "elasticloadbalancing:DescribeListeners" in {
        action for statement in statements for action in statement["actions"]
    }


def test_passrole_resource_principal_pairs_are_not_swappable(tmp_path: Path) -> None:
    manifest = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    task = next(s for s in manifest["statements"] if s["sid"] == "PassOnlyStagingEcsTaskRole")
    flow = next(s for s in manifest["statements"] if s["sid"] == "PassOnlyStagingFlowLogsRole")
    task["conditions"], flow["conditions"] = flow["conditions"], task["conditions"]
    mutated = tmp_path / "policy.yaml"
    mutated.write_text(yaml.safe_dump(manifest), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(POLICY_CHECKER), "--manifest", str(mutated), "--profile", "staging"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "resource and service-principal" in result.stderr


def test_kms_permissions_remain_staging_constrained() -> None:
    manifest = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    for sid in ("ReadStagingKeyRotation", "ScheduleDeletionForReviewedStagingKeys"):
        statement = next(s for s in manifest["statements"] if s["sid"] == sid)
        assert statement["resource"] == "*"
        assert statement["conditions"]["aws:ResourceTag/Environment"] == "staging"
    deletion = next(
        s for s in manifest["statements"] if s["sid"] == "ScheduleDeletionForReviewedStagingKeys"
    )
    assert deletion["conditions"]["kms:ScheduleKeyDeletionPendingWindowInDays"] == "30"
