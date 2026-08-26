"""Regression guards for the staging apply contract.

These assertions cover failure modes that provider-mocked Terraform plans do
not prove: same-name ALB replacement, unstructured metric filters, workflow
ordering, and parity between the reviewed IAM manifest and its checker.
"""

from __future__ import annotations

import subprocess
import sys
import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
TF = ROOT / "AWS Deployment/aether-aws/terraform"
ALB = TF / "modules/alb/main.tf"
MONITORING = TF / "modules/monitoring/main.tf"
PROMOTE = ROOT / ".github/workflows/terraform-promote.yml"
POLICY = ROOT / "config/staging_apply_iam_policy.yaml"
POLICY_CHECKER = ROOT / "scripts/release/check_staging_apply_policy.py"


def test_staging_target_group_replacement_is_name_safe() -> None:
    text = ALB.read_text(encoding="utf-8")
    assert 'name = "${lower(var.project)}-${var.environment}-backend"' in text
    assert 'create_before_destroy = var.environment != "staging"' in text


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
