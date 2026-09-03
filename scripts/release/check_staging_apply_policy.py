#!/usr/bin/env python3
"""Validate the reviewed, least-privilege staging apply IAM contract."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import NoReturn

import yaml


REQUIRED_ACTIONS = {
    "s3:PutEncryptionConfiguration",
    "s3:PutLifecycleConfiguration",
    "s3:GetEncryptionConfiguration",
    "s3:GetReplicationConfiguration",
    "ecr:TagResource",
    "ecr:ListTagsForResource",
    "ecr:DescribeRepositories",
    "ecr:PutImageScanningConfiguration",
    "ecr:GetLifecyclePolicy",
    "ecr:PutLifecyclePolicy",
    "ecr:GetRepositoryPolicy",
    "ecr:SetRepositoryPolicy",
    "ecr:DeleteRepositoryPolicy",
    "secretsmanager:TagResource",
    "secretsmanager:DescribeSecret",
    "secretsmanager:CreateSecret",
    "secretsmanager:UpdateSecret",
    "secretsmanager:DeleteSecret",
    "secretsmanager:RotateSecret",
    "ssm:AddTagsToResource",
    "ssm:ListTagsForResource",
    "kms:CreateKey",
    "kms:TagResource",
    "kms:CreateAlias",
    "kms:ListAliases",
    "kms:DescribeKey",
    "kms:GetKeyPolicy",
    "kms:ListResourceTags",
    "kms:CreateGrant",
    "kms:PutKeyPolicy",
    "kms:GenerateDataKey",
    "kms:Decrypt",
    "ec2:GetSecurityGroupsForVpc",
    "freetier:GetAccountPlanState",
    "kms:GetKeyRotationStatus",
    "kms:ScheduleKeyDeletion",
    "sns:SetTopicAttributes",
    "sns:DeleteTopic",
    "sns:Subscribe",
    "elasticloadbalancing:ModifyTargetGroupAttributes",
    "elasticloadbalancing:ModifyLoadBalancerAttributes",
    "dynamodb:ListTagsOfResource",
    "iam:CreateServiceLinkedRole",
    "iam:GetRole",
    "iam:PassRole",
    "iam:CreateRole",
    "iam:DeleteRole",
    "iam:TagRole",
    "iam:PutRolePolicy",
    "iam:GetRolePolicy",
    "iam:DeleteRolePolicy",
    "iam:AttachRolePolicy",
    "iam:DetachRolePolicy",
    "iam:ListAttachedRolePolicies",
    "iam:ListRolePolicies",
    "iam:ListInstanceProfilesForRole",
    "lambda:TagResource",
    "lambda:CreateFunction",
    "lambda:GetFunction",
    "lambda:UpdateFunctionCode",
    "lambda:UpdateFunctionConfiguration",
    "lambda:DeleteFunction",
    "lambda:AddPermission",
    "lambda:RemovePermission",
    "lambda:GetPolicy",
    "lambda:ListTags",
    "events:ListTargetsByRule",
    "events:PutRule",
    "events:DeleteRule",
    "events:DescribeRule",
    "events:PutTargets",
    "events:RemoveTargets",
    "events:TagResource",
    "logs:CreateLogGroup",
    "logs:TagResource",
    "logs:DescribeLogGroups",
    "logs:PutRetentionPolicy",
    "logs:DeleteLogGroup",
    "elasticloadbalancing:DescribeTargetGroups",
    "elasticloadbalancing:DescribeLoadBalancers",
    "elasticloadbalancing:DescribeListeners",
    "iam:SimulatePrincipalPolicy",
}
_LAMBDA_MANAGEMENT_ACTIONS = {
    "lambda:CreateFunction",
    "lambda:GetFunction",
    "lambda:UpdateFunctionCode",
    "lambda:UpdateFunctionConfiguration",
    "lambda:DeleteFunction",
    "lambda:AddPermission",
    "lambda:RemovePermission",
    "lambda:GetPolicy",
    "lambda:ListTags",
}
_IAM_ROLE_MANAGEMENT_ACTIONS = {
    "iam:CreateRole",
    "iam:DeleteRole",
    "iam:TagRole",
    "iam:PutRolePolicy",
    "iam:GetRolePolicy",
    "iam:DeleteRolePolicy",
    "iam:AttachRolePolicy",
    "iam:DetachRolePolicy",
    "iam:ListAttachedRolePolicies",
    "iam:ListRolePolicies",
    "iam:ListInstanceProfilesForRole",
}
ALLOWED_GLOBAL_ACTIONS = {
    "ec2:GetSecurityGroupsForVpc",
    "freetier:GetAccountPlanState",
    "iam:CreateServiceLinkedRole",
    "elasticloadbalancing:DescribeTargetGroups",
    "elasticloadbalancing:DescribeLoadBalancers",
    "elasticloadbalancing:DescribeListeners",
    "iam:SimulatePrincipalPolicy",
    "kms:GetKeyRotationStatus",
    "kms:ScheduleKeyDeletion",
    "kms:CreateKey",
    "kms:ListAliases",
    "logs:DescribeLogGroups",
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
            or sid in {"EnsureEcsServiceLinkedRole", "ReadEcsServiceLinkedRole", "ReadStagingKeyRotation", "ScheduleDeletionForReviewedStagingKeys", "DiscoverStagingTargetGroups", "VerifyTerraformStateAccess", "CreateStagingKmsKeys"}
        ):
            fail(f"unqualified global resource scope in {sid}")
        if "iam:PassRole" in statement_actions:
            passed_to = (statement.get("conditions") or {}).get("iam:PassedToService")
            if passed_to not in (["ecs-tasks.amazonaws.com"], ["vpc-flow-logs.amazonaws.com"], ["lambda.amazonaws.com"]):
                fail("iam:PassRole must be limited to the approved ECS, VPC flow-logs, or Lambda service principals")
        if "kms:ScheduleKeyDeletion" in statement_actions:
            if resource != "*" or (statement.get("conditions") or {}).get("aws:ResourceTag/Environment") != "staging":
                fail("kms:ScheduleKeyDeletion must use an enforceable staging KMS tag condition")
            pending_window = (statement.get("conditions") or {}).get("kms:ScheduleKeyDeletionPendingWindowInDays")
            if str(pending_window) != "30":
                fail("kms:ScheduleKeyDeletion must require a 30-day pending window")
        if "kms:GetKeyRotationStatus" in statement_actions:
            if resource != "*" or (statement.get("conditions") or {}).get("aws:ResourceTag/Environment") != "staging":
                fail("kms:GetKeyRotationStatus must use an enforceable staging KMS tag condition")
        if "kms:CreateKey" in statement_actions:
            if resource != "*" or (statement.get("conditions") or {}).get("aws:RequestTag/Environment") != "staging":
                fail("kms:CreateKey must require an Environment=staging request tag")
        if "kms:TagResource" in statement_actions:
            conditions = statement.get("conditions") or {}
            if resource != "arn:aws:kms:us-east-1:${account_id}:key/*" or not (conditions.get("aws:ResourceTag/Environment") == "staging" or conditions.get("aws:RequestTag/Environment") == "staging"):
                fail("kms:TagResource must use a staging KMS key ARN and resource/request-tag condition")
        if "kms:CreateAlias" in statement_actions:
            conditions = statement.get("conditions") or {}
            alias_arn = "arn:aws:kms:us-east-1:${account_id}:alias/aether-staging-*"
            key_arn = "arn:aws:kms:us-east-1:${account_id}:key/*"
            if resource == alias_arn:
                if conditions != {"kms:RequestAlias": "alias/aether-staging-*"}:
                    fail("kms:CreateAlias alias authorization must require the staging alias name")
                operators = statement.get("condition_operators") or {}
                if operators.get("kms:RequestAlias") != "StringLike":
                    fail("kms:CreateAlias alias authorization must use StringLike for the wildcard alias")
            elif resource == key_arn:
                if conditions != {"aws:ResourceTag/Environment": "staging"}:
                    fail("kms:CreateAlias target-key authorization must require the staging key tag")
            else:
                fail("kms:CreateAlias must split alias and target-key resource scopes")
        if "kms:PutKeyPolicy" in statement_actions:
            if resource != "arn:aws:kms:us-east-1:${account_id}:key/*" or (statement.get("conditions") or {}).get("aws:ResourceTag/Environment") != "staging":
                fail("kms:PutKeyPolicy must use a staging KMS key ARN and resource-tag condition")
        for _kms_data_action in ("kms:GenerateDataKey", "kms:Decrypt"):
            if _kms_data_action in statement_actions:
                if resource != "arn:aws:kms:us-east-1:${account_id}:key/*" or (statement.get("conditions") or {}).get("aws:ResourceTag/Environment") != "staging":
                    fail(f"{_kms_data_action} must use a staging KMS key ARN and resource-tag condition")
        if "iam:CreateServiceLinkedRole" in statement_actions:
            if (statement.get("conditions") or {}).get("iam:AWSServiceName") != "ecs.amazonaws.com":
                fail("iam:CreateServiceLinkedRole must be restricted to ECS")

    expected_resources = {
        "s3:PutEncryptionConfiguration": "arn:aws:s3:::aether-staging-*",
        "s3:PutLifecycleConfiguration": "arn:aws:s3:::aether-staging-*",
        "s3:GetEncryptionConfiguration": "arn:aws:s3:::aether-staging-*",
        "s3:GetReplicationConfiguration": "arn:aws:s3:::aether-staging-*",
        "ecr:TagResource": "arn:aws:ecr:us-east-1:${account_id}:repository/aether-*",
        "ecr:ListTagsForResource": "arn:aws:ecr:us-east-1:${account_id}:repository/aether-*",
        "ecr:DescribeRepositories": "arn:aws:ecr:us-east-1:${account_id}:repository/aether-*",
        "ecr:PutImageScanningConfiguration": "arn:aws:ecr:us-east-1:${account_id}:repository/aether-*",
        "ecr:GetLifecyclePolicy": "arn:aws:ecr:us-east-1:${account_id}:repository/aether-*",
        "ecr:PutLifecyclePolicy": "arn:aws:ecr:us-east-1:${account_id}:repository/aether-*",
        "ecr:GetRepositoryPolicy": "arn:aws:ecr:us-east-1:${account_id}:repository/aether-*",
        "ecr:SetRepositoryPolicy": "arn:aws:ecr:us-east-1:${account_id}:repository/aether-*",
        "ecr:DeleteRepositoryPolicy": "arn:aws:ecr:us-east-1:${account_id}:repository/aether-*",
        "secretsmanager:TagResource": "arn:aws:secretsmanager:us-east-1:${account_id}:secret:aether/*",
        "secretsmanager:DescribeSecret": "arn:aws:secretsmanager:us-east-1:${account_id}:secret:aether/*",
        "secretsmanager:CreateSecret": "arn:aws:secretsmanager:us-east-1:${account_id}:secret:aether/*",
        "secretsmanager:UpdateSecret": "arn:aws:secretsmanager:us-east-1:${account_id}:secret:aether/*",
        "secretsmanager:DeleteSecret": "arn:aws:secretsmanager:us-east-1:${account_id}:secret:aether/*",
        "secretsmanager:RotateSecret": "arn:aws:secretsmanager:us-east-1:${account_id}:secret:aether/*",
        "ssm:AddTagsToResource": "arn:aws:ssm:us-east-1:${account_id}:parameter/aether/staging/*",
        "ssm:ListTagsForResource": "arn:aws:ssm:us-east-1:${account_id}:parameter/aether/staging/*",
        "kms:CreateKey": "*",
        "kms:TagResource": "arn:aws:kms:us-east-1:${account_id}:key/*",
        "kms:CreateAlias": [
            "arn:aws:kms:us-east-1:${account_id}:alias/aether-staging-*",
            "arn:aws:kms:us-east-1:${account_id}:key/*",
        ],
        "kms:ListAliases": "*",
        "kms:DescribeKey": "arn:aws:kms:us-east-1:${account_id}:key/*",
        "kms:GetKeyPolicy": "arn:aws:kms:us-east-1:${account_id}:key/*",
        "kms:ListResourceTags": "arn:aws:kms:us-east-1:${account_id}:key/*",
        "kms:CreateGrant": "arn:aws:kms:us-east-1:${account_id}:key/*",
        "kms:PutKeyPolicy": "arn:aws:kms:us-east-1:${account_id}:key/*",
        "kms:GenerateDataKey": "arn:aws:kms:us-east-1:${account_id}:key/*",
        "kms:Decrypt": "arn:aws:kms:us-east-1:${account_id}:key/*",
        "ec2:GetSecurityGroupsForVpc": "*",
        "freetier:GetAccountPlanState": "*",
        "kms:GetKeyRotationStatus": "*",
        "kms:ScheduleKeyDeletion": "*",
        "sns:SetTopicAttributes": [
            "arn:aws:sns:us-east-1:${account_id}:aether-staging-*",
            "arn:aws:sns:us-east-1:${account_id}:AETHER-staging-*",
        ],
        "sns:DeleteTopic": [
            "arn:aws:sns:us-east-1:${account_id}:aether-staging-*",
            "arn:aws:sns:us-east-1:${account_id}:AETHER-staging-*",
        ],
        "sns:Subscribe": [
            "arn:aws:sns:us-east-1:${account_id}:aether-staging-*",
            "arn:aws:sns:us-east-1:${account_id}:AETHER-staging-*",
        ],
        "elasticloadbalancing:ModifyTargetGroupAttributes": "arn:aws:elasticloadbalancing:us-east-1:${account_id}:targetgroup/aether-staging-*",
        "elasticloadbalancing:ModifyLoadBalancerAttributes": "arn:aws:elasticloadbalancing:us-east-1:${account_id}:loadbalancer/app/aether-staging-*",
        "dynamodb:ListTagsOfResource": "arn:aws:dynamodb:us-east-1:${account_id}:table/AETHER-staging-*",
        "iam:CreateServiceLinkedRole": "*",
        "iam:GetRole": "exact-staging-role-read-bindings",
        "iam:PassRole": "exact-staging-role-bindings",
        "lambda:TagResource": "exact-staging-lambda-bindings",
        "events:ListTargetsByRule": "arn:aws:events:us-east-1:${account_id}:rule/AETHER-staging-*",
        "events:PutRule": "arn:aws:events:us-east-1:${account_id}:rule/AETHER-staging-*",
        "events:DeleteRule": "arn:aws:events:us-east-1:${account_id}:rule/AETHER-staging-*",
        "events:DescribeRule": "arn:aws:events:us-east-1:${account_id}:rule/AETHER-staging-*",
        "events:PutTargets": "arn:aws:events:us-east-1:${account_id}:rule/AETHER-staging-*",
        "events:RemoveTargets": "arn:aws:events:us-east-1:${account_id}:rule/AETHER-staging-*",
        "events:TagResource": "arn:aws:events:us-east-1:${account_id}:rule/AETHER-staging-*",
        "logs:CreateLogGroup": "arn:aws:logs:us-east-1:${account_id}:log-group:/aws/lambda/AETHER-staging-*",
        "logs:TagResource": "arn:aws:logs:us-east-1:${account_id}:log-group:/aws/lambda/AETHER-staging-*",
        "logs:DescribeLogGroups": "*",
        "logs:PutRetentionPolicy": "arn:aws:logs:us-east-1:${account_id}:log-group:/aws/lambda/AETHER-staging-*",
        "logs:DeleteLogGroup": "arn:aws:logs:us-east-1:${account_id}:log-group:/aws/lambda/AETHER-staging-*",
        "elasticloadbalancing:DescribeTargetGroups": "*",
        "elasticloadbalancing:DescribeLoadBalancers": "*",
        "elasticloadbalancing:DescribeListeners": "*",
        "iam:SimulatePrincipalPolicy": "*",
    }
    for action in _LAMBDA_MANAGEMENT_ACTIONS:
        expected_resources[action] = "exact-staging-lambda-bindings"
    for action in _IAM_ROLE_MANAGEMENT_ACTIONS:
        expected_resources[action] = "exact-staging-lambda-role-bindings"

    for action, expected in expected_resources.items():
        matching = [s for s in statements if action in (s.get("actions") or [])]
        if action == "iam:PassRole":
            expected_scopes = {
                "arn:aws:iam::${account_id}:role/AETHER-staging-ecs-task-role",
                "arn:aws:iam::${account_id}:role/AETHER-staging-ecs-execution-role",
                "arn:aws:iam::${account_id}:role/AETHER-staging-vpc-flow-logs-role",
                "arn:aws:iam::${account_id}:role/AETHER-staging-drift-lambda",
                "arn:aws:iam::${account_id}:role/AETHER-staging-secret-rotation",
            }
            if {s.get("resource") for s in matching} != expected_scopes:
                fail("iam:PassRole has an unexpected resource scope")
            expected_principals = {
                s.get("resource"): (s.get("conditions") or {}).get("iam:PassedToService")
                for s in matching
            }
            if expected_principals != {
                "arn:aws:iam::${account_id}:role/AETHER-staging-ecs-task-role": ["ecs-tasks.amazonaws.com"],
                "arn:aws:iam::${account_id}:role/AETHER-staging-ecs-execution-role": ["ecs-tasks.amazonaws.com"],
                "arn:aws:iam::${account_id}:role/AETHER-staging-vpc-flow-logs-role": ["vpc-flow-logs.amazonaws.com"],
                "arn:aws:iam::${account_id}:role/AETHER-staging-drift-lambda": ["lambda.amazonaws.com"],
                "arn:aws:iam::${account_id}:role/AETHER-staging-secret-rotation": ["lambda.amazonaws.com"],
            }:
                fail("iam:PassRole resource and service-principal bindings do not match")
        elif action == "iam:GetRole":
            slr_arn = "arn:aws:iam::${account_id}:role/aws-service-role/ecs.amazonaws.com/AWSServiceRoleForECS"
            lambda_role_arns = {
                "arn:aws:iam::${account_id}:role/AETHER-staging-drift-lambda",
                "arn:aws:iam::${account_id}:role/AETHER-staging-secret-rotation",
            }
            single_resources = {s.get("resource") for s in matching if isinstance(s.get("resource"), str)}
            list_resources: set[str] = set()
            for s in matching:
                r = s.get("resource")
                if isinstance(r, list):
                    list_resources.update(r)
            if single_resources != {slr_arn} or list_resources != lambda_role_arns:
                fail("iam:GetRole has an unexpected resource scope")
        elif action == "lambda:TagResource":
            expected = {
                "arn:aws:lambda:us-east-1:${account_id}:function:AETHER-staging-ml-drift",
                "arn:aws:lambda:us-east-1:${account_id}:function:AETHER-staging-secret-rotation",
            }
            if len(matching) != 1 or set(matching[0].get("resource") or []) != expected:
                fail("lambda:TagResource must cover exactly the staging drift and secret-rotation functions")
        elif action in _LAMBDA_MANAGEMENT_ACTIONS:
            expected_fns = {
                "arn:aws:lambda:us-east-1:${account_id}:function:AETHER-staging-ml-drift",
                "arn:aws:lambda:us-east-1:${account_id}:function:AETHER-staging-secret-rotation",
            }
            if len(matching) != 1 or set(matching[0].get("resource") or []) != expected_fns:
                fail(f"{action} must cover exactly the staging Lambda functions")
        elif action in _IAM_ROLE_MANAGEMENT_ACTIONS:
            expected_roles = {
                "arn:aws:iam::${account_id}:role/AETHER-staging-drift-lambda",
                "arn:aws:iam::${account_id}:role/AETHER-staging-secret-rotation",
            }
            if len(matching) != 1 or set(matching[0].get("resource") or []) != expected_roles:
                fail(f"{action} must cover exactly the staging Lambda roles")
        elif action == "kms:CreateGrant":
            if len(matching) != 1 or matching[0].get("resource") != expected or (matching[0].get("conditions") or {}).get("aws:ResourceTag/Environment") != "staging":
                fail("kms:CreateGrant must be limited to staging-tagged keys")
        elif action == "kms:TagResource":
            if len(matching) != 2 or any(s.get("resource") != expected for s in matching):
                fail(f"{action} has an unexpected resource scope")
            conditions = [s.get("conditions") or {} for s in matching]
            if {tuple(sorted(c.items())) for c in conditions} != {
                (("aws:RequestTag/Environment", "staging"),),
                (("aws:ResourceTag/Environment", "staging"),),
            }:
                fail("kms:TagResource must cover request and resource staging tags")
        elif action == "kms:CreateAlias":
            if len(matching) != 2:
                fail("kms:CreateAlias must have separate alias and target-key statements")
            if {s.get("resource") for s in matching} != set(expected):
                fail("kms:CreateAlias has an unexpected resource scope")
        elif action.startswith("sns:"):
            if len(matching) != 1 or set(matching[0].get("resource") or []) != set(expected):
                fail(f"{action} has an unexpected resource scope")
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
