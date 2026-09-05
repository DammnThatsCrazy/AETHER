#!/usr/bin/env python3
"""Validate the reviewed, least-privilege staging apply IAM contract."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import NoReturn

import yaml


REQUIRED_ACTIONS = {
    # S3
    "s3:PutEncryptionConfiguration",
    "s3:PutLifecycleConfiguration",
    "s3:GetEncryptionConfiguration",
    "s3:GetReplicationConfiguration",
    "s3:CreateBucket",
    "s3:DeleteBucket",
    "s3:PutBucketPolicy",
    "s3:DeleteBucketPolicy",
    "s3:PutBucketVersioning",
    "s3:PutBucketLogging",
    "s3:PutBucketTagging",
    "s3:PutPublicAccessBlock",
    "s3:PutBucketAcl",
    "s3:GetBucketPolicy",
    "s3:GetBucketAcl",
    "s3:GetBucketCORS",
    "s3:GetBucketWebsite",
    "s3:GetBucketVersioning",
    "s3:GetBucketLogging",
    "s3:GetBucketLocation",
    "s3:GetBucketTagging",
    "s3:GetBucketPublicAccessBlock",
    "s3:GetBucketObjectLockConfiguration",
    "s3:GetAccelerateConfiguration",
    "s3:GetBucketRequestPayment",
    "s3:GetBucketNotification",
    "s3:GetBucketOwnershipControls",
    "s3:ListBucket",
    # ECR
    "ecr:TagResource",
    "ecr:ListTagsForResource",
    "ecr:DescribeRepositories",
    "ecr:PutImageScanningConfiguration",
    "ecr:DescribeImageScanFindings",
    "ecr:GetImageScanningConfiguration",
    "ecr:GetLifecyclePolicy",
    "ecr:PutLifecyclePolicy",
    "ecr:DeleteLifecyclePolicy",
    "ecr:GetRepositoryPolicy",
    "ecr:SetRepositoryPolicy",
    "ecr:DeleteRepositoryPolicy",
    "ecr:CreateRepository",
    "ecr:DeleteRepository",
    # Secrets Manager
    "secretsmanager:TagResource",
    "secretsmanager:DescribeSecret",
    "secretsmanager:GetResourcePolicy",
    "secretsmanager:ListSecretVersionIds",
    "secretsmanager:CreateSecret",
    "secretsmanager:UpdateSecret",
    "secretsmanager:DeleteSecret",
    "secretsmanager:RotateSecret",
    "secretsmanager:ListSecrets",
    # SSM
    "ssm:AddTagsToResource",
    "ssm:ListTagsForResource",
    "ssm:PutParameter",
    "ssm:DeleteParameter",
    "ssm:GetParameter",
    "ssm:GetParameters",
    "ssm:DescribeParameters",
    # KMS
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
    "kms:GetKeyRotationStatus",
    "kms:ScheduleKeyDeletion",
    # EC2 / VPC
    "ec2:GetSecurityGroupsForVpc",
    "ec2:CreateVpc",
    "ec2:DeleteVpc",
    "ec2:ModifyVpcAttribute",
    "ec2:CreateTags",
    "ec2:DeleteTags",
    "ec2:CreateSubnet",
    "ec2:DeleteSubnet",
    "ec2:CreateInternetGateway",
    "ec2:AttachInternetGateway",
    "ec2:DetachInternetGateway",
    "ec2:DeleteInternetGateway",
    "ec2:AllocateAddress",
    "ec2:ReleaseAddress",
    "ec2:CreateNatGateway",
    "ec2:DeleteNatGateway",
    "ec2:CreateRouteTable",
    "ec2:DeleteRouteTable",
    "ec2:CreateRoute",
    "ec2:DeleteRoute",
    "ec2:AssociateRouteTable",
    "ec2:DisassociateRouteTable",
    "ec2:ReplaceRouteTableAssociation",
    "ec2:CreateSecurityGroup",
    "ec2:DeleteSecurityGroup",
    "ec2:AuthorizeSecurityGroupIngress",
    "ec2:AuthorizeSecurityGroupEgress",
    "ec2:RevokeSecurityGroupIngress",
    "ec2:RevokeSecurityGroupEgress",
    "ec2:CreateFlowLogs",
    "ec2:DeleteFlowLogs",
    "ec2:DescribeVpcs",
    "ec2:DescribeSubnets",
    "ec2:DescribeSecurityGroups",
    "ec2:DescribeSecurityGroupRules",
    "ec2:DescribeRouteTables",
    "ec2:DescribeInternetGateways",
    "ec2:DescribeNatGateways",
    "ec2:DescribeAddresses",
    "ec2:DescribeVpcAttribute",
    "ec2:DescribeNetworkInterfaces",
    "ec2:DescribeFlowLogs",
    "ec2:DescribeNetworkAcls",
    "ec2:DescribeVpcEndpoints",
    "ec2:DescribeAvailabilityZones",
    # ECS
    "ecs:CreateCluster",
    "ecs:DeleteCluster",
    "ecs:UpdateCluster",
    "ecs:TagResource",
    "ecs:RegisterTaskDefinition",
    "ecs:DeregisterTaskDefinition",
    "ecs:CreateService",
    "ecs:DeleteService",
    "ecs:UpdateService",
    "ecs:PutClusterCapacityProviders",
    "ecs:DescribeServices",
    "ecs:DescribeTaskDefinition",
    "ecs:DescribeClusters",
    "ecs:ListServices",
    "ecs:ListTagsForResource",
    # ALB / ELBv2
    "elasticloadbalancing:ModifyTargetGroupAttributes",
    "elasticloadbalancing:ModifyLoadBalancerAttributes",
    "elasticloadbalancing:DescribeTargetGroups",
    "elasticloadbalancing:DescribeLoadBalancers",
    "elasticloadbalancing:DescribeListeners",
    "elasticloadbalancing:CreateLoadBalancer",
    "elasticloadbalancing:DeleteLoadBalancer",
    "elasticloadbalancing:CreateTargetGroup",
    "elasticloadbalancing:DeleteTargetGroup",
    "elasticloadbalancing:CreateListener",
    "elasticloadbalancing:DeleteListener",
    "elasticloadbalancing:ModifyListener",
    "elasticloadbalancing:CreateRule",
    "elasticloadbalancing:DeleteRule",
    "elasticloadbalancing:ModifyRule",
    "elasticloadbalancing:AddTags",
    "elasticloadbalancing:RemoveTags",
    "elasticloadbalancing:SetSecurityGroups",
    "elasticloadbalancing:SetSubnets",
    "elasticloadbalancing:RegisterTargets",
    "elasticloadbalancing:DeregisterTargets",
    "elasticloadbalancing:DescribeLoadBalancerAttributes",
    "elasticloadbalancing:DescribeListenerCertificates",
    "elasticloadbalancing:DescribeTargetGroupAttributes",
    "elasticloadbalancing:DescribeTags",
    "elasticloadbalancing:DescribeRules",
    "elasticloadbalancing:DescribeListenerAttributes",
    # Aurora / RDS
    "rds:CreateDBCluster",
    "rds:DeleteDBCluster",
    "rds:ModifyDBCluster",
    "rds:CreateDBInstance",
    "rds:DeleteDBInstance",
    "rds:ModifyDBInstance",
    "rds:CreateDBSubnetGroup",
    "rds:DeleteDBSubnetGroup",
    "rds:ModifyDBSubnetGroup",
    "rds:CreateDBClusterParameterGroup",
    "rds:DeleteDBClusterParameterGroup",
    "rds:ModifyDBClusterParameterGroup",
    "rds:AddTagsToResource",
    "rds:RemoveTagsFromResource",
    "rds:DescribeDBClusters",
    "rds:DescribeDBSubnetGroups",
    "rds:DescribeDBClusterParameterGroups",
    "rds:DescribeDBClusterParameters",
    "rds:DescribeDBInstances",
    "rds:ListTagsForResource",
    # DynamoDB
    "dynamodb:ListTagsOfResource",
    "dynamodb:CreateTable",
    "dynamodb:DeleteTable",
    "dynamodb:UpdateTable",
    "dynamodb:TagResource",
    "dynamodb:UntagResource",
    "dynamodb:UpdateContinuousBackups",
    "dynamodb:UpdateTimeToLive",
    "dynamodb:DescribeTable",
    "dynamodb:DescribeContinuousBackups",
    "dynamodb:DescribeTimeToLive",
    # SQS
    "sqs:CreateQueue",
    "sqs:DeleteQueue",
    "sqs:SetQueueAttributes",
    "sqs:TagQueue",
    "sqs:UntagQueue",
    "sqs:GetQueueAttributes",
    "sqs:GetQueueUrl",
    "sqs:ListQueueTags",
    # SNS
    "sns:SetTopicAttributes",
    "sns:DeleteTopic",
    "sns:Subscribe",
    "sns:CreateTopic",
    "sns:TagResource",
    "sns:Unsubscribe",
    "sns:GetTopicAttributes",
    "sns:ListTagsForResource",
    "sns:GetSubscriptionAttributes",
    # CloudWatch
    "cloudwatch:PutMetricAlarm",
    "cloudwatch:DeleteAlarms",
    "cloudwatch:TagResource",
    "cloudwatch:PutDashboard",
    "cloudwatch:DeleteDashboards",
    "cloudwatch:DescribeAlarms",
    "cloudwatch:GetDashboard",
    "cloudwatch:ListTagsForResource",
    # CloudWatch Logs
    "logs:CreateLogGroup",
    "logs:TagResource",
    "logs:DescribeLogGroups",
    "logs:PutRetentionPolicy",
    "logs:DeleteLogGroup",
    "logs:PutMetricFilter",
    "logs:DeleteMetricFilter",
    "logs:DescribeMetricFilters",
    "logs:ListTagsForResource",
    # Application Auto Scaling
    "application-autoscaling:RegisterScalableTarget",
    "application-autoscaling:DeregisterScalableTarget",
    "application-autoscaling:PutScalingPolicy",
    "application-autoscaling:DeleteScalingPolicy",
    "application-autoscaling:TagResource",
    "application-autoscaling:DescribeScalableTargets",
    "application-autoscaling:DescribeScalingPolicies",
    # IAM
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
    "iam:SimulatePrincipalPolicy",
    # Lambda
    "lambda:TagResource",
    "lambda:CreateFunction",
    "lambda:GetFunction",
    "lambda:GetFunctionCodeSigningConfig",
    "lambda:UpdateFunctionCode",
    "lambda:UpdateFunctionConfiguration",
    "lambda:DeleteFunction",
    "lambda:AddPermission",
    "lambda:RemovePermission",
    "lambda:GetPolicy",
    "lambda:ListTags",
    "lambda:GetFunctionConfiguration",
    # EventBridge
    "events:ListTargetsByRule",
    "events:PutRule",
    "events:DeleteRule",
    "events:DescribeRule",
    "events:PutTargets",
    "events:RemoveTargets",
    "events:TagResource",
    # STS
    "sts:GetCallerIdentity",
    # Free Tier
    "freetier:GetAccountPlanState",
}
_LAMBDA_MANAGEMENT_ACTIONS = {
    "lambda:CreateFunction",
    "lambda:GetFunction",
    "lambda:GetFunctionCodeSigningConfig",
    "lambda:UpdateFunctionCode",
    "lambda:UpdateFunctionConfiguration",
    "lambda:DeleteFunction",
    "lambda:AddPermission",
    "lambda:RemovePermission",
    "lambda:GetPolicy",
    "lambda:ListTags",
    "lambda:GetFunctionConfiguration",
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
    # EC2 / VPC write (API requires '*')
    "ec2:CreateVpc",
    "ec2:DeleteVpc",
    "ec2:ModifyVpcAttribute",
    "ec2:CreateTags",
    "ec2:DeleteTags",
    "ec2:CreateSubnet",
    "ec2:DeleteSubnet",
    "ec2:CreateInternetGateway",
    "ec2:AttachInternetGateway",
    "ec2:DetachInternetGateway",
    "ec2:DeleteInternetGateway",
    "ec2:AllocateAddress",
    "ec2:ReleaseAddress",
    "ec2:CreateNatGateway",
    "ec2:DeleteNatGateway",
    "ec2:CreateRouteTable",
    "ec2:DeleteRouteTable",
    "ec2:CreateRoute",
    "ec2:DeleteRoute",
    "ec2:AssociateRouteTable",
    "ec2:DisassociateRouteTable",
    "ec2:ReplaceRouteTableAssociation",
    "ec2:CreateSecurityGroup",
    "ec2:DeleteSecurityGroup",
    "ec2:AuthorizeSecurityGroupIngress",
    "ec2:AuthorizeSecurityGroupEgress",
    "ec2:RevokeSecurityGroupIngress",
    "ec2:RevokeSecurityGroupEgress",
    "ec2:CreateFlowLogs",
    "ec2:DeleteFlowLogs",
    # EC2 / VPC read
    "ec2:GetSecurityGroupsForVpc",
    "ec2:DescribeVpcs",
    "ec2:DescribeSubnets",
    "ec2:DescribeSecurityGroups",
    "ec2:DescribeSecurityGroupRules",
    "ec2:DescribeRouteTables",
    "ec2:DescribeInternetGateways",
    "ec2:DescribeNatGateways",
    "ec2:DescribeAddresses",
    "ec2:DescribeVpcAttribute",
    "ec2:DescribeNetworkInterfaces",
    "ec2:DescribeFlowLogs",
    "ec2:DescribeNetworkAcls",
    "ec2:DescribeVpcEndpoints",
    "ec2:DescribeAvailabilityZones",
    # ECS
    "ecs:CreateCluster",
    "ecs:DeleteCluster",
    "ecs:UpdateCluster",
    "ecs:TagResource",
    "ecs:RegisterTaskDefinition",
    "ecs:DeregisterTaskDefinition",
    "ecs:CreateService",
    "ecs:DeleteService",
    "ecs:UpdateService",
    "ecs:PutClusterCapacityProviders",
    "ecs:DescribeServices",
    "ecs:DescribeTaskDefinition",
    "ecs:DescribeClusters",
    "ecs:ListServices",
    "ecs:ListTagsForResource",
    # ALB / ELBv2
    "elasticloadbalancing:DescribeTargetGroups",
    "elasticloadbalancing:DescribeLoadBalancers",
    "elasticloadbalancing:DescribeListeners",
    "elasticloadbalancing:CreateLoadBalancer",
    "elasticloadbalancing:DeleteLoadBalancer",
    "elasticloadbalancing:CreateTargetGroup",
    "elasticloadbalancing:DeleteTargetGroup",
    "elasticloadbalancing:CreateListener",
    "elasticloadbalancing:DeleteListener",
    "elasticloadbalancing:ModifyListener",
    "elasticloadbalancing:CreateRule",
    "elasticloadbalancing:DeleteRule",
    "elasticloadbalancing:ModifyRule",
    "elasticloadbalancing:AddTags",
    "elasticloadbalancing:RemoveTags",
    "elasticloadbalancing:SetSecurityGroups",
    "elasticloadbalancing:SetSubnets",
    "elasticloadbalancing:RegisterTargets",
    "elasticloadbalancing:DeregisterTargets",
    "elasticloadbalancing:DescribeLoadBalancerAttributes",
    "elasticloadbalancing:DescribeListenerCertificates",
    "elasticloadbalancing:DescribeTargetGroupAttributes",
    "elasticloadbalancing:DescribeTags",
    "elasticloadbalancing:DescribeRules",
    "elasticloadbalancing:DescribeListenerAttributes",
    # Aurora / RDS
    "rds:CreateDBCluster",
    "rds:DeleteDBCluster",
    "rds:ModifyDBCluster",
    "rds:CreateDBInstance",
    "rds:DeleteDBInstance",
    "rds:ModifyDBInstance",
    "rds:CreateDBSubnetGroup",
    "rds:DeleteDBSubnetGroup",
    "rds:ModifyDBSubnetGroup",
    "rds:CreateDBClusterParameterGroup",
    "rds:DeleteDBClusterParameterGroup",
    "rds:ModifyDBClusterParameterGroup",
    "rds:AddTagsToResource",
    "rds:RemoveTagsFromResource",
    "rds:DescribeDBClusters",
    "rds:DescribeDBSubnetGroups",
    "rds:DescribeDBClusterParameterGroups",
    "rds:DescribeDBClusterParameters",
    "rds:DescribeDBInstances",
    "rds:ListTagsForResource",
    # CloudWatch
    "cloudwatch:PutMetricAlarm",
    "cloudwatch:DeleteAlarms",
    "cloudwatch:TagResource",
    "cloudwatch:PutDashboard",
    "cloudwatch:DeleteDashboards",
    "cloudwatch:DescribeAlarms",
    "cloudwatch:GetDashboard",
    "cloudwatch:ListTagsForResource",
    # CloudWatch Logs read
    "logs:DescribeLogGroups",
    "logs:DescribeMetricFilters",
    "logs:ListTagsForResource",
    # Application Auto Scaling
    "application-autoscaling:RegisterScalableTarget",
    "application-autoscaling:DeregisterScalableTarget",
    "application-autoscaling:PutScalingPolicy",
    "application-autoscaling:DeleteScalingPolicy",
    "application-autoscaling:TagResource",
    "application-autoscaling:DescribeScalableTargets",
    "application-autoscaling:DescribeScalingPolicies",
    # Secrets Manager
    "secretsmanager:ListSecrets",
    # SSM (DescribeParameters is a filter/list API requiring resource '*')
    "ssm:DescribeParameters",
    # STS
    "sts:GetCallerIdentity",
    # IAM
    "iam:CreateServiceLinkedRole",
    "iam:SimulatePrincipalPolicy",
    # KMS
    "kms:GetKeyRotationStatus",
    "kms:ScheduleKeyDeletion",
    "kms:CreateKey",
    "kms:ListAliases",
    # Free Tier
    "freetier:GetAccountPlanState",
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

_S3_STAGING_BUCKET = "arn:aws:s3:::aether-staging-*"
_ECR_REPO = "arn:aws:ecr:us-east-1:${account_id}:repository/aether-*"
_SECRET_ARN = "arn:aws:secretsmanager:us-east-1:${account_id}:secret:aether/*"
_SSM_PARAM = "arn:aws:ssm:us-east-1:${account_id}:parameter/aether/staging/*"
_DYNAMO_TABLE = "arn:aws:dynamodb:us-east-1:${account_id}:table/AETHER-staging-*"
_SQS_QUEUE = "arn:aws:sqs:us-east-1:${account_id}:AETHER-staging-*"
_EVENTS_RULE = "arn:aws:events:us-east-1:${account_id}:rule/AETHER-staging-*"
_KMS_KEY = "arn:aws:kms:us-east-1:${account_id}:key/*"
_SNS_RESOURCES = [
    "arn:aws:sns:us-east-1:${account_id}:aether-staging-*",
    "arn:aws:sns:us-east-1:${account_id}:AETHER-staging-*",
]
_LOG_GROUP_RESOURCES = [
    "arn:aws:logs:us-east-1:${account_id}:log-group:/aws/lambda/AETHER-staging-*",
    "arn:aws:logs:us-east-1:${account_id}:log-group:/ecs/AETHER-staging/*",
    "arn:aws:logs:us-east-1:${account_id}:log-group:/aws/vpc/AETHER-staging/*",
    "arn:aws:logs:us-east-1:${account_id}:log-group:/aether/AETHER-staging/*",
]
_LAMBDA_ROLE_ARNS = {
    "arn:aws:iam::${account_id}:role/AETHER-staging-drift-lambda",
    "arn:aws:iam::${account_id}:role/AETHER-staging-secret-rotation",
}
_INFRA_ROLE_ARNS = {
    "arn:aws:iam::${account_id}:role/AETHER-staging-ecs-task-role",
    "arn:aws:iam::${account_id}:role/AETHER-staging-ecs-execution-role",
    "arn:aws:iam::${account_id}:role/AETHER-staging-vpc-flow-logs-role",
    "arn:aws:iam::${account_id}:role/AETHER-staging-aurora-monitoring-role",
}
_LAMBDA_FN_ARNS = {
    "arn:aws:lambda:us-east-1:${account_id}:function:AETHER-staging-ml-drift",
    "arn:aws:lambda:us-east-1:${account_id}:function:AETHER-staging-secret-rotation",
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
            if passed_to not in (["ecs-tasks.amazonaws.com"], ["vpc-flow-logs.amazonaws.com"], ["lambda.amazonaws.com"], ["monitoring.rds.amazonaws.com"]):
                fail("iam:PassRole must be limited to the approved ECS, VPC flow-logs, Lambda, or RDS monitoring service principals")
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
            if resource != _KMS_KEY or not (conditions.get("aws:ResourceTag/Environment") == "staging" or conditions.get("aws:RequestTag/Environment") == "staging"):
                fail("kms:TagResource must use a staging KMS key ARN and resource/request-tag condition")
        if "kms:CreateAlias" in statement_actions:
            conditions = statement.get("conditions") or {}
            alias_arn = "arn:aws:kms:us-east-1:${account_id}:alias/aether-staging-*"
            if resource == alias_arn:
                if conditions != {"kms:RequestAlias": "alias/aether-staging-*"}:
                    fail("kms:CreateAlias alias authorization must require the staging alias name")
                operators = statement.get("condition_operators") or {}
                if operators.get("kms:RequestAlias") != "StringLike":
                    fail("kms:CreateAlias alias authorization must use StringLike for the wildcard alias")
            elif resource == _KMS_KEY:
                if conditions != {"aws:ResourceTag/Environment": "staging"}:
                    fail("kms:CreateAlias target-key authorization must require the staging key tag")
            else:
                fail("kms:CreateAlias must split alias and target-key resource scopes")
        if "kms:PutKeyPolicy" in statement_actions:
            if resource != _KMS_KEY or (statement.get("conditions") or {}).get("aws:ResourceTag/Environment") != "staging":
                fail("kms:PutKeyPolicy must use a staging KMS key ARN and resource-tag condition")
        for _kms_data_action in ("kms:GenerateDataKey", "kms:Decrypt"):
            if _kms_data_action in statement_actions:
                if resource != _KMS_KEY or (statement.get("conditions") or {}).get("aws:ResourceTag/Environment") != "staging":
                    fail(f"{_kms_data_action} must use a staging KMS key ARN and resource-tag condition")
        if "iam:CreateServiceLinkedRole" in statement_actions:
            if (statement.get("conditions") or {}).get("iam:AWSServiceName") != "ecs.amazonaws.com":
                fail("iam:CreateServiceLinkedRole must be restricted to ECS")

    expected_resources: dict[str, str | list[str]] = {}

    # S3
    for _s3 in (
        "s3:PutEncryptionConfiguration", "s3:PutLifecycleConfiguration",
        "s3:GetEncryptionConfiguration", "s3:GetReplicationConfiguration",
        "s3:CreateBucket", "s3:DeleteBucket",
        "s3:PutBucketPolicy", "s3:DeleteBucketPolicy",
        "s3:PutBucketVersioning", "s3:PutBucketLogging",
        "s3:PutBucketTagging", "s3:PutPublicAccessBlock", "s3:PutBucketAcl",
        "s3:GetBucketPolicy", "s3:GetBucketAcl", "s3:GetBucketCORS",
        "s3:GetBucketWebsite", "s3:GetBucketVersioning", "s3:GetBucketLogging",
        "s3:GetBucketLocation", "s3:GetBucketTagging",
        "s3:GetBucketPublicAccessBlock", "s3:GetBucketObjectLockConfiguration",
        "s3:GetAccelerateConfiguration",
        "s3:GetBucketRequestPayment", "s3:GetBucketNotification",
        "s3:GetBucketOwnershipControls", "s3:ListBucket",
    ):
        expected_resources[_s3] = _S3_STAGING_BUCKET

    # ECR
    for _ecr in (
        "ecr:TagResource", "ecr:ListTagsForResource", "ecr:DescribeRepositories",
        "ecr:PutImageScanningConfiguration", "ecr:DescribeImageScanFindings",
        "ecr:GetImageScanningConfiguration",
        "ecr:GetLifecyclePolicy", "ecr:PutLifecyclePolicy",
        "ecr:DeleteLifecyclePolicy",
        "ecr:GetRepositoryPolicy", "ecr:SetRepositoryPolicy",
        "ecr:DeleteRepositoryPolicy",
        "ecr:CreateRepository", "ecr:DeleteRepository",
    ):
        expected_resources[_ecr] = _ECR_REPO

    # Secrets Manager
    for _sm in (
        "secretsmanager:TagResource", "secretsmanager:DescribeSecret",
        "secretsmanager:GetResourcePolicy", "secretsmanager:ListSecretVersionIds",
        "secretsmanager:CreateSecret", "secretsmanager:UpdateSecret",
        "secretsmanager:DeleteSecret", "secretsmanager:RotateSecret",
    ):
        expected_resources[_sm] = _SECRET_ARN
    expected_resources["secretsmanager:ListSecrets"] = "*"

    # SSM
    for _ssm in (
        "ssm:AddTagsToResource", "ssm:ListTagsForResource",
        "ssm:PutParameter", "ssm:DeleteParameter",
        "ssm:GetParameter", "ssm:GetParameters",
    ):
        expected_resources[_ssm] = _SSM_PARAM
    expected_resources["ssm:DescribeParameters"] = "*"

    # KMS
    expected_resources["kms:CreateKey"] = "*"
    expected_resources["kms:TagResource"] = _KMS_KEY
    expected_resources["kms:CreateAlias"] = [
        "arn:aws:kms:us-east-1:${account_id}:alias/aether-staging-*",
        _KMS_KEY,
    ]
    expected_resources["kms:ListAliases"] = "*"
    for _kms in (
        "kms:DescribeKey", "kms:GetKeyPolicy", "kms:ListResourceTags",
        "kms:CreateGrant", "kms:PutKeyPolicy",
        "kms:GenerateDataKey", "kms:Decrypt",
    ):
        expected_resources[_kms] = _KMS_KEY
    expected_resources["kms:GetKeyRotationStatus"] = "*"
    expected_resources["kms:ScheduleKeyDeletion"] = "*"

    # EC2 / VPC — all require '*'
    for _ec2 in (
        "ec2:GetSecurityGroupsForVpc",
        "ec2:CreateVpc", "ec2:DeleteVpc", "ec2:ModifyVpcAttribute",
        "ec2:CreateTags", "ec2:DeleteTags",
        "ec2:CreateSubnet", "ec2:DeleteSubnet",
        "ec2:CreateInternetGateway", "ec2:AttachInternetGateway",
        "ec2:DetachInternetGateway", "ec2:DeleteInternetGateway",
        "ec2:AllocateAddress", "ec2:ReleaseAddress",
        "ec2:CreateNatGateway", "ec2:DeleteNatGateway",
        "ec2:CreateRouteTable", "ec2:DeleteRouteTable",
        "ec2:CreateRoute", "ec2:DeleteRoute",
        "ec2:AssociateRouteTable", "ec2:DisassociateRouteTable",
        "ec2:ReplaceRouteTableAssociation",
        "ec2:CreateSecurityGroup", "ec2:DeleteSecurityGroup",
        "ec2:AuthorizeSecurityGroupIngress", "ec2:AuthorizeSecurityGroupEgress",
        "ec2:RevokeSecurityGroupIngress", "ec2:RevokeSecurityGroupEgress",
        "ec2:CreateFlowLogs", "ec2:DeleteFlowLogs",
        "ec2:DescribeVpcs", "ec2:DescribeSubnets",
        "ec2:DescribeSecurityGroups", "ec2:DescribeSecurityGroupRules",
        "ec2:DescribeRouteTables", "ec2:DescribeInternetGateways",
        "ec2:DescribeNatGateways", "ec2:DescribeAddresses",
        "ec2:DescribeVpcAttribute", "ec2:DescribeNetworkInterfaces",
        "ec2:DescribeFlowLogs", "ec2:DescribeNetworkAcls",
        "ec2:DescribeVpcEndpoints", "ec2:DescribeAvailabilityZones",
    ):
        expected_resources[_ec2] = "*"

    # ECS — all require '*'
    for _ecs in (
        "ecs:CreateCluster", "ecs:DeleteCluster", "ecs:UpdateCluster",
        "ecs:TagResource", "ecs:RegisterTaskDefinition",
        "ecs:DeregisterTaskDefinition", "ecs:CreateService",
        "ecs:DeleteService", "ecs:UpdateService",
        "ecs:PutClusterCapacityProviders",
        "ecs:DescribeServices", "ecs:DescribeTaskDefinition",
        "ecs:DescribeClusters", "ecs:ListServices", "ecs:ListTagsForResource",
    ):
        expected_resources[_ecs] = "*"

    # ALB / ELBv2
    expected_resources["elasticloadbalancing:ModifyTargetGroupAttributes"] = (
        "arn:aws:elasticloadbalancing:us-east-1:${account_id}:targetgroup/aether-staging-*"
    )
    expected_resources["elasticloadbalancing:ModifyLoadBalancerAttributes"] = (
        "arn:aws:elasticloadbalancing:us-east-1:${account_id}:loadbalancer/app/aether-staging-*"
    )
    for _elb in (
        "elasticloadbalancing:DescribeTargetGroups",
        "elasticloadbalancing:DescribeLoadBalancers",
        "elasticloadbalancing:DescribeListeners",
        "elasticloadbalancing:CreateLoadBalancer",
        "elasticloadbalancing:DeleteLoadBalancer",
        "elasticloadbalancing:CreateTargetGroup",
        "elasticloadbalancing:DeleteTargetGroup",
        "elasticloadbalancing:CreateListener",
        "elasticloadbalancing:DeleteListener",
        "elasticloadbalancing:ModifyListener",
        "elasticloadbalancing:CreateRule",
        "elasticloadbalancing:DeleteRule",
        "elasticloadbalancing:ModifyRule",
        "elasticloadbalancing:AddTags",
        "elasticloadbalancing:RemoveTags",
        "elasticloadbalancing:SetSecurityGroups",
        "elasticloadbalancing:SetSubnets",
        "elasticloadbalancing:RegisterTargets",
        "elasticloadbalancing:DeregisterTargets",
        "elasticloadbalancing:DescribeLoadBalancerAttributes",
        "elasticloadbalancing:DescribeListenerCertificates",
        "elasticloadbalancing:DescribeTargetGroupAttributes",
        "elasticloadbalancing:DescribeTags",
        "elasticloadbalancing:DescribeRules",
    "elasticloadbalancing:DescribeListenerAttributes",
    ):
        expected_resources[_elb] = "*"

    # Aurora / RDS — all require '*'
    for _rds in (
        "rds:CreateDBCluster", "rds:DeleteDBCluster", "rds:ModifyDBCluster",
        "rds:CreateDBInstance", "rds:DeleteDBInstance", "rds:ModifyDBInstance",
        "rds:CreateDBSubnetGroup", "rds:DeleteDBSubnetGroup",
        "rds:ModifyDBSubnetGroup",
        "rds:CreateDBClusterParameterGroup",
        "rds:DeleteDBClusterParameterGroup",
        "rds:ModifyDBClusterParameterGroup",
        "rds:AddTagsToResource", "rds:RemoveTagsFromResource",
        "rds:DescribeDBClusters", "rds:DescribeDBSubnetGroups",
        "rds:DescribeDBClusterParameterGroups",
        "rds:DescribeDBClusterParameters",
        "rds:DescribeDBInstances", "rds:ListTagsForResource",
    ):
        expected_resources[_rds] = "*"

    # DynamoDB
    expected_resources["dynamodb:ListTagsOfResource"] = _DYNAMO_TABLE
    for _ddb in (
        "dynamodb:CreateTable", "dynamodb:DeleteTable", "dynamodb:UpdateTable",
        "dynamodb:TagResource", "dynamodb:UntagResource",
        "dynamodb:UpdateContinuousBackups", "dynamodb:UpdateTimeToLive",
        "dynamodb:DescribeTable", "dynamodb:DescribeContinuousBackups",
        "dynamodb:DescribeTimeToLive",
    ):
        expected_resources[_ddb] = _DYNAMO_TABLE

    # SQS
    for _sqs in (
        "sqs:CreateQueue", "sqs:DeleteQueue", "sqs:SetQueueAttributes",
        "sqs:TagQueue", "sqs:UntagQueue",
        "sqs:GetQueueAttributes", "sqs:GetQueueUrl", "sqs:ListQueueTags",
    ):
        expected_resources[_sqs] = _SQS_QUEUE

    # SNS
    for _sns in (
        "sns:SetTopicAttributes", "sns:DeleteTopic", "sns:Subscribe",
        "sns:CreateTopic", "sns:TagResource", "sns:Unsubscribe",
        "sns:GetTopicAttributes", "sns:ListTagsForResource",
        "sns:GetSubscriptionAttributes",
    ):
        expected_resources[_sns] = _SNS_RESOURCES

    # CloudWatch — all require '*'
    for _cw in (
        "cloudwatch:PutMetricAlarm", "cloudwatch:DeleteAlarms",
        "cloudwatch:TagResource", "cloudwatch:PutDashboard",
        "cloudwatch:DeleteDashboards", "cloudwatch:DescribeAlarms",
        "cloudwatch:GetDashboard", "cloudwatch:ListTagsForResource",
    ):
        expected_resources[_cw] = "*"

    # CloudWatch Logs
    for _log_scoped in (
        "logs:CreateLogGroup", "logs:TagResource",
        "logs:PutRetentionPolicy", "logs:DeleteLogGroup",
        "logs:PutMetricFilter", "logs:DeleteMetricFilter",
    ):
        expected_resources[_log_scoped] = _LOG_GROUP_RESOURCES
    for _log_global in ("logs:DescribeLogGroups", "logs:DescribeMetricFilters", "logs:ListTagsForResource"):
        expected_resources[_log_global] = "*"

    # Application Auto Scaling — all require '*'
    for _as in (
        "application-autoscaling:RegisterScalableTarget",
        "application-autoscaling:DeregisterScalableTarget",
        "application-autoscaling:PutScalingPolicy",
        "application-autoscaling:DeleteScalingPolicy",
        "application-autoscaling:TagResource",
        "application-autoscaling:DescribeScalableTargets",
        "application-autoscaling:DescribeScalingPolicies",
    ):
        expected_resources[_as] = "*"

    # EventBridge
    for _evt in (
        "events:ListTargetsByRule", "events:PutRule", "events:DeleteRule",
        "events:DescribeRule", "events:PutTargets", "events:RemoveTargets",
        "events:TagResource",
    ):
        expected_resources[_evt] = _EVENTS_RULE

    # STS / Free Tier
    expected_resources["sts:GetCallerIdentity"] = "*"
    expected_resources["freetier:GetAccountPlanState"] = "*"

    # IAM
    expected_resources["iam:CreateServiceLinkedRole"] = "*"
    expected_resources["iam:SimulatePrincipalPolicy"] = "*"
    expected_resources["iam:GetRole"] = "exact-staging-role-read-bindings"
    expected_resources["iam:PassRole"] = "exact-staging-role-bindings"
    expected_resources["lambda:TagResource"] = "exact-staging-lambda-bindings"
    for action in _LAMBDA_MANAGEMENT_ACTIONS:
        expected_resources[action] = "exact-staging-lambda-bindings"
    for action in _IAM_ROLE_MANAGEMENT_ACTIONS:
        expected_resources[action] = "exact-staging-role-management-bindings"

    for action, expected in expected_resources.items():
        matching = [s for s in statements if action in (s.get("actions") or [])]
        if action == "iam:PassRole":
            expected_scopes = {
                "arn:aws:iam::${account_id}:role/AETHER-staging-ecs-task-role",
                "arn:aws:iam::${account_id}:role/AETHER-staging-ecs-execution-role",
                "arn:aws:iam::${account_id}:role/AETHER-staging-vpc-flow-logs-role",
                "arn:aws:iam::${account_id}:role/AETHER-staging-drift-lambda",
                "arn:aws:iam::${account_id}:role/AETHER-staging-secret-rotation",
                "arn:aws:iam::${account_id}:role/AETHER-staging-aurora-monitoring-role",
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
                "arn:aws:iam::${account_id}:role/AETHER-staging-aurora-monitoring-role": ["monitoring.rds.amazonaws.com"],
            }:
                fail("iam:PassRole resource and service-principal bindings do not match")
        elif action == "iam:GetRole":
            slr_arn = "arn:aws:iam::${account_id}:role/aws-service-role/ecs.amazonaws.com/AWSServiceRoleForECS"
            single_resources = {s.get("resource") for s in matching if isinstance(s.get("resource"), str)}
            list_resources: set[str] = set()
            for s in matching:
                r = s.get("resource")
                if isinstance(r, list):
                    list_resources.update(r)
            if single_resources != {slr_arn} or list_resources != (_LAMBDA_ROLE_ARNS | _INFRA_ROLE_ARNS):
                fail("iam:GetRole has an unexpected resource scope")
        elif action == "lambda:TagResource":
            if len(matching) != 1 or set(matching[0].get("resource") or []) != _LAMBDA_FN_ARNS:
                fail("lambda:TagResource must cover exactly the staging drift and secret-rotation functions")
        elif action in _LAMBDA_MANAGEMENT_ACTIONS:
            if len(matching) != 1 or set(matching[0].get("resource") or []) != _LAMBDA_FN_ARNS:
                fail(f"{action} must cover exactly the staging Lambda functions")
        elif action in _IAM_ROLE_MANAGEMENT_ACTIONS:
            role_sets = {frozenset(s.get("resource") or []) for s in matching}
            if role_sets != {frozenset(_LAMBDA_ROLE_ARNS), frozenset(_INFRA_ROLE_ARNS)}:
                fail(f"{action} must cover exactly the staging Lambda and infrastructure roles")
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
        elif isinstance(expected, list):
            if len(matching) != 1 or (matching[0].get("resource") or []) != expected:
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
