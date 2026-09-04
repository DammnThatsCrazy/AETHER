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
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
EXPECTED = {
    "ecs:DescribeClusters", "ecs:ListServices", "ecs:DescribeServices",
    "ecs:DescribeTaskDefinition", "ecs:DescribeTasks", "ecs:UpdateService", "ecs:RunTask", "iam:PassRole",
    "ssm:GetParameter", "ssm:PutParameter", "ssm:DeleteParameter",
    "s3:ListBucket", "s3:GetObject", "s3:PutObject", "s3:DeleteObject",
    "logs:DescribeLogGroups", "cloudwatch:ListMetrics",
    "application-autoscaling:DescribeScalableTargets",
    "application-autoscaling:RegisterScalableTarget", "sts:GetCallerIdentity",
}

# The lifecycle role is consumed by shell workflows. Keep this translation
# table next to the validator so adding an AWS CLI call is a deliberate,
# reviewable contract change rather than a silent AccessDenied at runtime.
CLI_TO_IAM = {
    ("ecs", "describe-clusters"): {"ecs:DescribeClusters"},
    ("ecs", "list-services"): {"ecs:ListServices"},
    ("ecs", "describe-services"): {"ecs:DescribeServices"},
    ("ecs", "describe-task-definition"): {"ecs:DescribeTaskDefinition"},
    ("ecs", "describe-tasks"): {"ecs:DescribeTasks"},
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
    ("cloudwatch", "list-metrics"): {"cloudwatch:ListMetrics"},
    ("application-autoscaling", "describe-scalable-targets"):
        {"application-autoscaling:DescribeScalableTargets"},
    ("application-autoscaling", "register-scalable-target"):
        {"application-autoscaling:RegisterScalableTarget"},
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
    args = parser.parse_args(argv)
    doc = yaml.safe_load(args.manifest.read_text(encoding="utf-8"))
    if doc.get("profile") != "staging" or doc.get("role") != "AetherStagingLifecycle":
        raise SystemExit("lifecycle IAM manifest must target staging/AetherStagingLifecycle")
    actions = {a for statement in doc.get("statements", []) for a in statement.get("actions", [])}
    missing = sorted(EXPECTED - actions)
    forbidden_patterns = doc.get("forbidden_actions", [])
    forbidden = sorted(
        action
        for action in actions
        if any(fnmatch.fnmatchcase(action, pattern) for pattern in forbidden_patterns)
    )
    wildcard = sorted(a for a in actions if a.endswith(":*"))
    if missing:
        raise SystemExit("missing lifecycle actions: " + ", ".join(missing))
    workflow_missing = sorted(workflow_actions(args.workflow) - actions)
    if workflow_missing:
        raise SystemExit("workflow actions missing from lifecycle IAM manifest: " + ", ".join(workflow_missing))
    if forbidden or wildcard:
        raise SystemExit("wildcard/forbidden lifecycle actions: " + ", ".join(forbidden or wildcard))
    print(f"staging lifecycle IAM contract valid ({len(actions)} explicit actions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
