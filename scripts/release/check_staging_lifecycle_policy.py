#!/usr/bin/env python3
"""Validate the reviewed IAM action contract for staging lifecycle jobs.

The contract is intentionally checked in next to the workflows. A static
check catches drift in the action inventory before a role is edited; when AWS
credentials are available, the same inventory can be passed to IAM simulation
by the operator or workflow without granting broad permissions.
"""
from __future__ import annotations

import argparse
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=ROOT / "config/staging_lifecycle_iam_policy.yaml")
    args = parser.parse_args(argv)
    doc = yaml.safe_load(args.manifest.read_text(encoding="utf-8"))
    if doc.get("profile") != "staging" or doc.get("role") != "AetherStagingLifecycle":
        raise SystemExit("lifecycle IAM manifest must target staging/AetherStagingLifecycle")
    actions = {a for statement in doc.get("statements", []) for a in statement.get("actions", [])}
    missing = sorted(EXPECTED - actions)
    forbidden = sorted(actions & {a for a in doc.get("forbidden_actions", [])})
    wildcard = sorted(a for a in actions if a.endswith(":*"))
    if missing:
        raise SystemExit("missing lifecycle actions: " + ", ".join(missing))
    if forbidden or wildcard:
        raise SystemExit("wildcard/forbidden lifecycle actions: " + ", ".join(forbidden or wildcard))
    print(f"staging lifecycle IAM contract valid ({len(actions)} explicit actions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
