#!/usr/bin/env python3
"""Validate the reviewed IAM action contract for staging lifecycle jobs.

The contract is intentionally checked in next to the workflows. A static
check catches drift in the action inventory before a role is edited; when AWS
credentials are available, the same inventory can be passed to IAM simulation
by the operator or workflow without granting broad permissions.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
EXPECTED = {
    "ecs:DescribeClusters", "ecs:ListServices", "ecs:ListTasks", "ecs:DescribeServices",
    "ecs:DescribeTaskDefinition", "ecs:DescribeTasks", "ecs:StopTask", "ecs:UpdateService", "ecs:RunTask", "iam:PassRole",
    "ssm:GetParameter", "ssm:PutParameter", "ssm:DeleteParameter",
    "s3:ListBucket", "s3:GetObject", "s3:PutObject", "s3:DeleteObject",
    "logs:DescribeLogGroups", "logs:GetLogEvents", "cloudwatch:ListMetrics",
    "application-autoscaling:DescribeScalableTargets",
    "application-autoscaling:ListTagsForResource",
    "application-autoscaling:RegisterScalableTarget", "sts:GetCallerIdentity",
    "secretsmanager:GetSecretValue", "kms:Decrypt",
}

# AWS evaluates these read/namespace APIs against `*`, even when the request
# names a staging object. Keeping a resource ARN here creates a policy that
# looks least-privilege on paper but produces AccessDenied at runtime. This is
# the same resource semantics used by the reviewed staging-apply contract.
GLOBAL_RESOURCE_ACTIONS = {
    "ecs:ListServices",
    "ecs:ListTasks",
    "ecs:DescribeTaskDefinition",
    "logs:DescribeLogGroups",
    "cloudwatch:ListMetrics",
    "application-autoscaling:DescribeScalableTargets",
    "sts:GetCallerIdentity",
}

STAGING_SCALABLE_TARGET_ARN = (
    "arn:aws:application-autoscaling:us-east-1:${account_id}:scalable-target/*"
)
REGISTER_SCALABLE_TARGET_CONDITION_KEYS = {
    "application-autoscaling:service-namespace",
    "application-autoscaling:scalable-dimension",
    "aws:ResourceTag/Environment",
    "aws:ResourceTag/Project",
}
FIRST_ADMIN_BOOTSTRAP_SECRET_ARN_PATTERN = (
    "arn:aws:secretsmanager:us-east-1:544471417928:secret:"
    "aether/first-admin-bootstrap-token-*"
)
FIRST_ADMIN_BOOTSTRAP_KMS_KEY_ARN = (
    "arn:aws:kms:us-east-1:544471417928:key/"
    "91753780-d694-4e5a-9e80-7123af974554"
)
FIRST_ADMIN_BOOTSTRAP_KMS_CONDITIONS = {
    "StringEquals": {
        "kms:ViaService": "secretsmanager.us-east-1.amazonaws.com",
    },
    "StringLike": {
        "kms:EncryptionContext:SecretARN": FIRST_ADMIN_BOOTSTRAP_SECRET_ARN_PATTERN,
    },
}
ALLOWED_ACTION_EXCEPTION_CONTRACTS = {
    "ReadFirstAdminBootstrapToken": {
        "action": "secretsmanager:GetSecretValue",
        "resource": FIRST_ADMIN_BOOTSTRAP_SECRET_ARN_PATTERN,
        "conditions": None,
    },
    "DecryptFirstAdminBootstrapToken": {
        "action": "kms:Decrypt",
        "resource": FIRST_ADMIN_BOOTSTRAP_KMS_KEY_ARN,
        "conditions": FIRST_ADMIN_BOOTSTRAP_KMS_CONDITIONS,
    },
}
REQUIRED_FORBIDDEN_ACTION_PATTERNS = {"secretsmanager:*", "kms:*"}

CONDITION_OPERATORS = {
    "ArnEquals",
    "ArnLike",
    "Bool",
    "ForAllValues:StringEquals",
    "ForAnyValue:StringEquals",
    "StringEquals",
    "StringLike",
}


def _resolve_account_id(value: object, account_id: str) -> object:
    """Resolve the manifest account placeholder in nested policy values."""
    if isinstance(value, str):
        return value.replace("${account_id}", account_id)
    if isinstance(value, list):
        return [_resolve_account_id(item, account_id) for item in value]
    if isinstance(value, dict):
        return {key: _resolve_account_id(item, account_id) for key, item in value.items()}
    return value


def render_policy_document(document: dict, account_id: str) -> dict:
    """Render the reviewed YAML contract as an AWS inline policy document."""
    if not re.fullmatch(r"\d{12}", account_id):
        raise ValueError("account_id must be a 12-digit AWS account id")
    rendered: list[dict] = []
    for statement in document.get("statements", []):
        actions = statement.get("actions", [])
        item = {
            "Sid": statement["sid"],
            "Effect": "Allow",
            "Action": actions[0] if len(actions) == 1 else actions,
            "Resource": _resolve_account_id(statement["resource"], account_id),
        }
        if statement.get("conditions"):
            item["Condition"] = _resolve_account_id(statement["conditions"], account_id)
        rendered.append(item)
    return {"Version": "2012-10-17", "Statement": rendered}

# The lifecycle role is consumed by shell workflows. Keep this translation
# table next to the validator so adding an AWS CLI call is a deliberate,
# reviewable contract change rather than a silent AccessDenied at runtime.
CLI_TO_IAM = {
    ("ecs", "describe-clusters"): {"ecs:DescribeClusters"},
    ("ecs", "list-services"): {"ecs:ListServices"},
    ("ecs", "list-tasks"): {"ecs:ListTasks"},
    ("ecs", "describe-services"): {"ecs:DescribeServices"},
    ("ecs", "describe-task-definition"): {"ecs:DescribeTaskDefinition"},
    ("ecs", "describe-tasks"): {"ecs:DescribeTasks"},
    ("ecs", "stop-task"): {"ecs:StopTask"},
    ("ecs", "update-service"): {"ecs:UpdateService"},
    ("ecs", "run-task"): {"ecs:RunTask"},
    # Waiters poll the preceding Describe operation and do not add an IAM
    # action of their own.
    ("ecs", "wait"): set(),
    ("ssm", "get-parameter"): {"ssm:GetParameter"},
    ("ssm", "put-parameter"): {"ssm:PutParameter"},
    ("ssm", "delete-parameter"): {"ssm:DeleteParameter"},
    ("s3", "sync"): {"s3:ListBucket", "s3:GetObject", "s3:PutObject", "s3:DeleteObject"},
    ("s3", "cp"): {"s3:PutObject"},
    ("s3api", "head-object"): {"s3:GetObject"},
    ("logs", "describe-log-groups"): {"logs:DescribeLogGroups"},
    ("logs", "get-log-events"): {"logs:GetLogEvents"},
    ("cloudwatch", "list-metrics"): {"cloudwatch:ListMetrics"},
    ("application-autoscaling", "describe-scalable-targets"):
        {"application-autoscaling:DescribeScalableTargets"},
    ("application-autoscaling", "list-tags-for-resource"):
        {"application-autoscaling:ListTagsForResource"},
    ("application-autoscaling", "register-scalable-target"):
        {"application-autoscaling:RegisterScalableTarget"},
    ("secretsmanager", "get-secret-value"): {"secretsmanager:GetSecretValue"},
    ("sts", "get-caller-identity"): {"sts:GetCallerIdentity"},
}


def workflow_actions(paths: list[Path]) -> set[str]:
    """Extract and translate every executable AWS CLI operation in workflows."""
    found: set[str] = set()
    unknown: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            for service, operation in re.findall(r"\baws\s+([a-z0-9-]+)\s+([a-z0-9-]+)\b", line):
                key = (service, operation)
                if key not in CLI_TO_IAM:
                    unknown.append(f"{path}:{line_number}: aws {service} {operation}")
                found.update(CLI_TO_IAM.get(key, set()))
    if unknown:
        raise SystemExit("unmapped AWS CLI operations in lifecycle workflows: " + "; ".join(unknown))
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=ROOT / "config/staging_lifecycle_iam_policy.yaml")
    parser.add_argument(
        "--workflow", type=Path, action="append",
        default=[ROOT / ".github/workflows/staging-lifecycle.yml", ROOT / ".github/workflows/staging-ttl-guard.yml"],
        help="workflow to inventory (repeatable; defaults to both staging lifecycle workflows)",
    )
    parser.add_argument("--account-id", help="12-digit AWS account id used for policy rendering")
    parser.add_argument(
        "--render-output",
        type=Path,
        help="write the validated manifest as an AWS inline policy JSON document",
    )
    args = parser.parse_args(argv)
    doc = yaml.safe_load(args.manifest.read_text(encoding="utf-8"))
    if doc.get("profile") != "staging" or doc.get("role") != "AetherStagingLifecycle":
        raise SystemExit("lifecycle IAM manifest must target staging/AetherStagingLifecycle")
    actions = {a for statement in doc.get("statements", []) for a in statement.get("actions", [])}
    resource_by_action: dict[str, list[object]] = {}
    for statement in doc.get("statements", []):
        resource = statement.get("resource")
        for action in statement.get("actions", []):
            resource_by_action.setdefault(action, []).append(resource)
        conditions = statement.get("conditions")
        if conditions is not None:
            if not isinstance(conditions, dict) or not conditions:
                raise SystemExit(f"{statement.get('sid', '<unknown>')} has an invalid empty conditions block")
            unknown_operators = sorted(set(conditions) - CONDITION_OPERATORS)
            malformed_operators = sorted(
                operator for operator, values in conditions.items()
                if not isinstance(values, dict) or not values
            )
            if unknown_operators or malformed_operators:
                detail = []
                if unknown_operators:
                    detail.append("unknown operators: " + ", ".join(unknown_operators))
                if malformed_operators:
                    detail.append("operators without condition maps: " + ", ".join(malformed_operators))
                raise SystemExit(
                    f"{statement.get('sid', '<unknown>')} has malformed conditions (" + "; ".join(detail) + ")"
                )
    missing = sorted(EXPECTED - actions)
    forbidden_patterns = doc.get("forbidden_actions", [])
    if not isinstance(forbidden_patterns, list) or not all(
        isinstance(pattern, str) for pattern in forbidden_patterns
    ):
        raise SystemExit("forbidden_actions must be a list of action patterns")
    if not REQUIRED_FORBIDDEN_ACTION_PATTERNS <= set(forbidden_patterns):
        raise SystemExit(
            "forbidden_actions must keep Secrets Manager and KMS service-wide patterns forbidden"
        )
    wildcard = sorted(a for a in actions if a.endswith(":*"))
    if missing:
        raise SystemExit("missing lifecycle actions: " + ", ".join(missing))
    workflow_missing = sorted(workflow_actions(args.workflow) - actions)
    if workflow_missing:
        raise SystemExit("workflow actions missing from lifecycle IAM manifest: " + ", ".join(workflow_missing))
    global_scope_errors = sorted(
        action
        for action in GLOBAL_RESOURCE_ACTIONS
        if resource_by_action.get(action) != ["*"]
    )
    if global_scope_errors:
        raise SystemExit(
            "lifecycle actions requiring Resource '*' have incorrect scopes: "
            + ", ".join(global_scope_errors)
        )
    statements = doc.get("statements", [])
    statements_by_sid = {statement.get("sid"): statement for statement in statements}
    if len(statements_by_sid) != len(statements):
        raise SystemExit("lifecycle IAM statement SIDs must be unique")
    autoscaling_statement = statements_by_sid.get("PreventAutoscalingRevival", {})
    register_action = "application-autoscaling:RegisterScalableTarget"
    if autoscaling_statement.get("resource") != STAGING_SCALABLE_TARGET_ARN:
        raise SystemExit(
            "PreventAutoscalingRevival must scope RegisterScalableTarget to scalable-target resources"
        )
    if autoscaling_statement.get("actions") != [register_action]:
        raise SystemExit("PreventAutoscalingRevival must grant only RegisterScalableTarget")
    if resource_by_action.get(register_action) != [STAGING_SCALABLE_TARGET_ARN]:
        raise SystemExit("RegisterScalableTarget must be granted only on staging scalable-target ARNs")
    condition_keys = {
        f"{operator}:{key}"
        for operator, values in (autoscaling_statement.get("conditions") or {}).items()
        for key in values
    }
    unsupported = sorted(
        key.split(":", 1)[1]
        for key in condition_keys
        if key.split(":", 1)[1] not in REGISTER_SCALABLE_TARGET_CONDITION_KEYS
    )
    expected_conditions = {
        "StringEquals": {
            "application-autoscaling:service-namespace": ["ecs"],
            "application-autoscaling:scalable-dimension": ["ecs:service:DesiredCount"],
            "aws:ResourceTag/Environment": ["staging"],
            "aws:ResourceTag/Project": ["AETHER"],
        }
    }
    actual_conditions = autoscaling_statement.get("conditions")
    if unsupported or actual_conditions != expected_conditions:
        detail = []
        if unsupported:
            detail.append("unsupported RegisterScalableTarget condition keys: " + ", ".join(unsupported))
        if actual_conditions != expected_conditions:
            detail.append("RegisterScalableTarget conditions must exactly match the staging namespace, dimension, and ownership tags")
        raise SystemExit("invalid PreventAutoscalingRevival contract (" + "; ".join(detail) + ")")
    tag_read = statements_by_sid.get("ReadStagingAutoscalingTargetTags", {})
    list_tags_action = "application-autoscaling:ListTagsForResource"
    if (
        tag_read.get("actions") != [list_tags_action]
        or tag_read.get("resource") != STAGING_SCALABLE_TARGET_ARN
        or resource_by_action.get(list_tags_action) != [STAGING_SCALABLE_TARGET_ARN]
    ):
        raise SystemExit("ListTagsForResource must be scoped only to staging scalable-target ARNs")
    declared_exceptions = doc.get("allowed_action_exceptions", [])
    if (
        not isinstance(declared_exceptions, list)
        or not all(isinstance(sid, str) for sid in declared_exceptions)
        or len(declared_exceptions) != len(set(declared_exceptions))
        or set(declared_exceptions) != set(ALLOWED_ACTION_EXCEPTION_CONTRACTS)
    ):
        raise SystemExit(
            "allowed_action_exceptions must name only the reviewed first-admin bootstrap statements"
        )
    for sid, contract in ALLOWED_ACTION_EXCEPTION_CONTRACTS.items():
        statement = statements_by_sid.get(sid)
        if (
            statement is None
            or statement.get("actions") != [contract["action"]]
            or statement.get("resource") != contract["resource"]
            or statement.get("conditions") != contract["conditions"]
        ):
            raise SystemExit(
                f"{sid} must exactly match its reviewed first-admin bootstrap action, resource, and conditions"
            )
    forbidden = sorted(
        f"{statement.get('sid', '<unknown>')}:{action}"
        for statement in statements
        for action in statement.get("actions", [])
        if any(fnmatch.fnmatchcase(action, pattern) for pattern in forbidden_patterns)
        and not (
            statement.get("sid") in ALLOWED_ACTION_EXCEPTION_CONTRACTS
            and action == ALLOWED_ACTION_EXCEPTION_CONTRACTS[statement["sid"]]["action"]
        )
    )
    if forbidden or wildcard:
        raise SystemExit("wildcard/forbidden lifecycle actions: " + ", ".join(forbidden + wildcard))
    if args.render_output:
        if not args.account_id:
            raise SystemExit("--account-id is required with --render-output")
        args.render_output.write_text(
            json.dumps(render_policy_document(doc, args.account_id), indent=2) + "\n",
            encoding="utf-8",
        )
    print(f"staging lifecycle IAM contract valid ({len(actions)} explicit actions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
