#!/usr/bin/env python3
"""Validate the reviewed, least-privilege staging apply IAM contract."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import NoReturn

import yaml


REQUIRED_ACTIONS = {
    "s3:GetEncryptionConfiguration",
    "s3:GetReplicationConfiguration",
    "ec2:GetSecurityGroupsForVpc",
    "kms:GetKeyRotationStatus",
    "kms:ScheduleKeyDeletion",
    "sns:SetTopicAttributes",
    "sns:DeleteTopic",
    "elasticloadbalancing:ModifyTargetGroupAttributes",
    "elasticloadbalancing:ModifyLoadBalancerAttributes",
    "dynamodb:ListTagsOfResource",
    "iam:CreateServiceLinkedRole",
    "iam:PassRole",
}
ALLOWED_GLOBAL_ACTIONS = {
    "ec2:GetSecurityGroupsForVpc",
    "iam:CreateServiceLinkedRole",
    "kms:GetKeyRotationStatus",
    "kms:ScheduleKeyDeletion",
}
REQUIRED_AUTH0_SCOPES = {
    "create:resource_servers",
    "read:resource_servers",
    "update:resource_servers",
    "delete:resource_servers",
    "create:connections",
    "create:clients",
    "create:client_grants",
    "read:client_grants",
    "update:client_grants",
    "delete:client_grants",
    "read:clients",
    "read:connections",
    "update:connections",
    "update:clients",
    "delete:clients",
    "delete:connections",
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
        if resource == "*" and not (
            statement.get("scope", "").endswith("required-by-api")
            or sid in {"EnsureEcsServiceLinkedRole", "ReadStagingKeyRotation", "ScheduleDeletionForReviewedStagingKeys"}
        ):
            fail(f"unqualified global resource scope in {sid}")
        if "iam:PassRole" in statement_actions:
            passed_to = (statement.get("conditions") or {}).get("iam:PassedToService")
            if set(passed_to or []) not in (
                {"ecs-tasks.amazonaws.com", "ecs.amazonaws.com"},
                {"vpc-flow-logs.amazonaws.com"},
            ):
                fail("iam:PassRole must be limited to the approved ECS or VPC flow-logs service principals")
        if "kms:ScheduleKeyDeletion" in statement_actions:
            if resource != "*" or (statement.get("conditions") or {}).get("aws:ResourceTag/Environment") != "staging":
                fail("kms:ScheduleKeyDeletion must use an enforceable staging KMS tag condition")
            pending_window = (statement.get("conditions") or {}).get("kms:ScheduleKeyDeletionPendingWindowInDays")
            if str(pending_window) != "30":
                fail("kms:ScheduleKeyDeletion must require a 30-day pending window")
        if "kms:GetKeyRotationStatus" in statement_actions:
            if resource != "*" or (statement.get("conditions") or {}).get("aws:ResourceTag/Environment") != "staging":
                fail("kms:GetKeyRotationStatus must use an enforceable staging KMS tag condition")
        if "iam:CreateServiceLinkedRole" in statement_actions:
            if (statement.get("conditions") or {}).get("iam:AWSServiceName") != "ecs.amazonaws.com":
                fail("iam:CreateServiceLinkedRole must be restricted to ECS")

    expected_resources = {
        "s3:GetEncryptionConfiguration": "arn:aws:s3:::aether-staging-*",
        "s3:GetReplicationConfiguration": "arn:aws:s3:::aether-staging-*",
        "ec2:GetSecurityGroupsForVpc": "*",
        "kms:GetKeyRotationStatus": "*",
        "kms:ScheduleKeyDeletion": "*",
        "sns:SetTopicAttributes": "arn:aws:sns:us-east-1:${account_id}:AETHER-staging-*",
        "sns:DeleteTopic": "arn:aws:sns:us-east-1:${account_id}:AETHER-staging-*",
        "elasticloadbalancing:ModifyTargetGroupAttributes": "arn:aws:elasticloadbalancing:us-east-1:${account_id}:targetgroup/aether-staging-*",
        "elasticloadbalancing:ModifyLoadBalancerAttributes": "arn:aws:elasticloadbalancing:us-east-1:${account_id}:loadbalancer/app/aether-staging-*",
        "dynamodb:ListTagsOfResource": "arn:aws:dynamodb:us-east-1:${account_id}:table/AETHER-staging-*",
        "iam:CreateServiceLinkedRole": "*",
        "iam:PassRole": "arn:aws:iam::${account_id}:role/AETHER-staging-*",
    }
    for action, expected in expected_resources.items():
        matching = [s for s in statements if action in (s.get("actions") or [])]
        if action == "iam:PassRole":
            expected_scopes = {
                "arn:aws:iam::${account_id}:role/AETHER-staging-*",
                "arn:aws:iam::${account_id}:role/AETHER-staging-vpc-flow-logs-role",
            }
            if {s.get("resource") for s in matching} != expected_scopes:
                fail("iam:PassRole has an unexpected resource scope")
        elif len(matching) != 1 or matching[0].get("resource") != expected:
            fail(f"{action} has an unexpected resource scope")

    missing = REQUIRED_ACTIONS - actions
    if missing:
        fail(f"staging apply IAM contract is missing: {', '.join(sorted(missing))}")
    unexpected = actions - REQUIRED_ACTIONS
    if unexpected:
        fail(f"staging apply IAM contract contains unreviewed actions: {', '.join(sorted(unexpected))}")

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
