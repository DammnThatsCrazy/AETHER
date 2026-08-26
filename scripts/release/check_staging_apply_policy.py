#!/usr/bin/env python3
"""Validate the reviewed, least-privilege staging apply IAM contract."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml


REQUIRED_ACTIONS = {
    "s3:GetEncryptionConfiguration",
    "s3:GetReplicationConfiguration",
    "ec2:GetSecurityGroupsForVpc",
    "kms:GetKeyRotationStatus",
    "kms:ScheduleKeyDeletion",
    "sns:SetTopicAttributes",
    "elasticloadbalancing:ModifyTargetGroupAttributes",
    "dynamodb:ListTagsOfResource",
    "iam:CreateServiceLinkedRole",
    "iam:PassRole",
}
ALLOWED_GLOBAL_ACTIONS = {
    "ec2:GetSecurityGroupsForVpc",
    "iam:CreateServiceLinkedRole",
}
REQUIRED_AUTH0_SCOPES = {
    "create:resource_servers",
    "create:connections",
    "create:clients",
}


def fail(message: str) -> "NoReturn":
    print(f"::error::{message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()

    manifest = yaml.safe_load(Path(args.manifest).read_text()) or {}
    if manifest.get("version") != 1:
        fail("staging apply IAM contract version must be 1")
    if manifest.get("profile") != args.profile:
        fail(f"IAM contract is for {manifest.get('profile')!r}, not {args.profile!r}")
    if manifest.get("role") != "AetherStagingDeploy":
        fail("IAM contract must target AetherStagingDeploy")

    statements = manifest.get("statements")
    if not isinstance(statements, list) or not statements:
        fail("IAM contract has no statements")

    actions: set[str] = set()
    for statement in statements:
        if not isinstance(statement, dict):
            fail("IAM statement is not an object")
        sid = statement.get("sid")
        statement_actions = statement.get("actions")
        resource = statement.get("resource")
        if not sid or not isinstance(statement_actions, list) or not statement_actions:
            fail(f"IAM statement {sid or '<unnamed>'} is missing actions")
        if not resource:
            fail(f"IAM statement {sid} is missing resource scope")
        if any("*" in action for action in statement_actions):
            fail(f"IAM statement {sid} contains a wildcard action")
        for action in statement_actions:
            actions.add(action)
            if resource == "*" and action not in ALLOWED_GLOBAL_ACTIONS:
                fail(f"global resource scope is not allowed for {action}")
        if resource == "*" and not statement.get("scope", "").endswith("required-by-api") and sid != "EnsureEcsServiceLinkedRole":
            fail(f"unqualified global resource scope in {sid}")
        if "iam:PassRole" in statement_actions:
            passed_to = (statement.get("conditions") or {}).get("iam:PassedToService")
            if set(passed_to or []) != {"ecs-tasks.amazonaws.com", "ecs.amazonaws.com"}:
                fail("iam:PassRole must be limited to the ECS service principals")
        if "kms:ScheduleKeyDeletion" in statement_actions:
            pending_window = (statement.get("conditions") or {}).get("kms:ScheduleKeyDeletionPendingWindowInDays")
            if str(pending_window) != "30":
                fail("kms:ScheduleKeyDeletion must require a 30-day pending window")

    missing = REQUIRED_ACTIONS - actions
    if missing:
        fail(f"staging apply IAM contract is missing: {', '.join(sorted(missing))}")

    scopes = manifest.get("external_provider_requirements") or []
    auth0_scopes = {
        scope
        for item in scopes
        if item.get("provider") == "auth0"
        for scope in item.get("required_scopes", [])
    }
    if not REQUIRED_AUTH0_SCOPES <= auth0_scopes:
        fail("Auth0 apply contract is missing required management scopes")

    print(f"staging apply IAM contract valid: {len(actions)} explicit actions")
    return 0


if __name__ == "__main__":
    main()
