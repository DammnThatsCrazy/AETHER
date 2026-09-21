#!/usr/bin/env python3
"""Validate the supplemental IAM contract used by staging deploy.yml."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "config/staging_application_delivery_iam_policy.yaml"
APPLY_MANIFEST = ROOT / "config/staging_apply_iam_policy.yaml"
WORKFLOW = ROOT / ".github/workflows/deploy.yml"

EXPECTED = {
    "ecr:GetAuthorizationToken",
    "ecr:BatchCheckLayerAvailability",
    "ecr:BatchGetImage",
    "ecr:CompleteLayerUpload",
    "ecr:DescribeImages",
    "ecr:GetDownloadUrlForLayer",
    "ecr:InitiateLayerUpload",
    "ecr:PutImage",
    "ecr:UploadLayerPart",
    "ecs:RunTask",
    "ecs:DescribeTasks",
    "s3:ListBucket",
    "s3:GetObject",
    "s3:PutObject",
    "s3:DeleteObject",
}

CLI_TO_IAM = {
    ("ecr", "describe-images"): {"ecr:DescribeImages"},
    ("ecs", "describe-clusters"): {"ecs:DescribeClusters"},
    ("ecs", "describe-services"): {"ecs:DescribeServices"},
    ("ecs", "describe-task-definition"): {"ecs:DescribeTaskDefinition"},
    ("ecs", "describe-tasks"): {"ecs:DescribeTasks"},
    ("ecs", "register-task-definition"): {"ecs:RegisterTaskDefinition"},
    ("ecs", "run-task"): {"ecs:RunTask"},
    ("ecs", "update-service"): {"ecs:UpdateService"},
    ("ecs", "wait"): set(),
    ("s3", "sync"): {"s3:ListBucket", "s3:GetObject", "s3:PutObject", "s3:DeleteObject"},
    ("s3", "cp"): {"s3:PutObject"},
    ("ssm", "get-parameter"): {"ssm:GetParameter"},
    ("iam", "simulate-principal-policy"): {"iam:SimulatePrincipalPolicy"},
    # deploy.yml verifies the exact assumed role before each mutating phase;
    # this read is already covered by the base staging apply contract.
    ("sts", "get-caller-identity"): {"sts:GetCallerIdentity"},
}

# The AWS CLI inventory above cannot see API calls made by Docker or by the
# docker/build-push-action. Keep those implicit ECR calls explicit here so the
# manifest checker fails when the runtime image path loses a required grant.
DOCKER_PULL_ECR_ACTIONS = {
    "ecr:BatchCheckLayerAvailability",
    "ecr:BatchGetImage",
    "ecr:GetDownloadUrlForLayer",
}
DOCKER_PUBLISH_ECR_ACTIONS = {
    "ecr:BatchCheckLayerAvailability",
    "ecr:BatchGetImage",
    "ecr:CompleteLayerUpload",
    "ecr:InitiateLayerUpload",
    "ecr:PutImage",
    "ecr:UploadLayerPart",
}


def _resolve(value: object, account_id: str) -> object:
    if isinstance(value, str):
        return value.replace("${account_id}", account_id)
    if isinstance(value, list):
        return [_resolve(item, account_id) for item in value]
    if isinstance(value, dict):
        return {key: _resolve(item, account_id) for key, item in value.items()}
    return value


def render_policy_document(document: dict, account_id: str) -> dict:
    if not re.fullmatch(r"\d{12}", account_id):
        raise ValueError("account_id must be a 12-digit AWS account id")
    statements = []
    for statement in document["statements"]:
        actions = statement["actions"]
        item = {
            "Sid": statement["sid"],
            "Effect": "Allow",
            "Action": actions[0] if len(actions) == 1 else actions,
            "Resource": _resolve(statement["resource"], account_id),
        }
        if statement.get("conditions"):
            item["Condition"] = _resolve(statement["conditions"], account_id)
        statements.append(item)
    return {"Version": "2012-10-17", "Statement": statements}


def workflow_actions(path: Path) -> set[str]:
    found: set[str] = set()
    unknown: list[str] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        if re.search(r"\bdocker\s+pull\b", line):
            found.update(DOCKER_PULL_ECR_ACTIONS)
        if "docker/build-push-action@" in line:
            found.update(DOCKER_PUBLISH_ECR_ACTIONS)
        for service, operation in re.findall(r"\baws\s+([a-z0-9-]+)\s+([a-z0-9-]+)\b", line):
            key = (service, operation)
            if key not in CLI_TO_IAM:
                unknown.append(f"{path}:{line_number}: aws {service} {operation}")
            found.update(CLI_TO_IAM.get(key, set()))
    if unknown:
        raise SystemExit("unmapped AWS CLI operations in staging deploy workflow: " + "; ".join(unknown))
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--workflow", type=Path, default=WORKFLOW)
    parser.add_argument("--apply-manifest", type=Path, default=APPLY_MANIFEST)
    parser.add_argument("--account-id")
    parser.add_argument("--render-output", type=Path)
    args = parser.parse_args(argv)

    document = yaml.safe_load(args.manifest.read_text(encoding="utf-8"))
    if document.get("version") != 1:
        raise SystemExit("staging application-delivery IAM contract version must be 1")
    if document.get("profile") != "staging" or document.get("role") != "AetherStagingDeploy":
        raise SystemExit("application-delivery IAM manifest must target staging/AetherStagingDeploy")

    actions = {action for statement in document.get("statements", []) for action in statement.get("actions", [])}
    missing = sorted(EXPECTED - actions)
    unexpected = sorted(actions - EXPECTED)
    if missing:
        raise SystemExit("missing staging application-delivery actions: " + ", ".join(missing))
    if unexpected:
        raise SystemExit("unreviewed staging application-delivery actions: " + ", ".join(unexpected))

    by_sid = {statement["sid"]: statement for statement in document["statements"]}
    auth = by_sid.get("AuthorizeStagingEcrClient")
    publish_image = by_sid.get("PublishStagingBackendImage")
    expected_cluster = "arn:aws:ecs:us-east-1:${account_id}:cluster/AETHER-staging"
    expected_task_definition = "arn:aws:ecs:us-east-1:${account_id}:task-definition/AETHER-staging-*"
    expected_tasks = "arn:aws:ecs:us-east-1:${account_id}:task/AETHER-staging/*"
    run = by_sid.get("RunStagingApplicationTasks")
    inspect = by_sid.get("InspectStagingApplicationTasks")
    publish = by_sid.get("PublishStagingStaticArtifacts")
    if not auth or auth["resource"] != "*" or auth.get("scope") != "global-read-required-by-api":
        raise SystemExit("AuthorizeStagingEcrClient must use the account-level ECR auth scope")
    expected_backend_repo = "arn:aws:ecr:us-east-1:${account_id}:repository/aether-backend"
    if not publish_image or publish_image["resource"] != expected_backend_repo:
        raise SystemExit("PublishStagingBackendImage must be limited to the immutable backend repository")
    if not run or run["resource"] != [expected_task_definition, expected_cluster]:
        raise SystemExit("RunStagingApplicationTasks has an unexpected resource scope")
    if run.get("conditions") != {"ArnEquals": {"ecs:cluster": expected_cluster}}:
        raise SystemExit("RunStagingApplicationTasks must be bound to the staging cluster")
    if not inspect or inspect["resource"] != expected_tasks:
        raise SystemExit("InspectStagingApplicationTasks has an unexpected resource scope")
    if inspect.get("conditions") != {"ArnEquals": {"ecs:cluster": expected_cluster}}:
        raise SystemExit("InspectStagingApplicationTasks must be bound to the staging cluster")
    if not publish or publish["resource"] != [
        "arn:aws:s3:::aether-staging-*",
        "arn:aws:s3:::aether-staging-*/*",
    ]:
        raise SystemExit("PublishStagingStaticArtifacts must cover only staging buckets and objects")

    apply_document = yaml.safe_load(args.apply_manifest.read_text(encoding="utf-8"))
    base_actions = {
        action for statement in apply_document.get("statements", []) for action in statement.get("actions", [])
    }
    missing_workflow = sorted(workflow_actions(args.workflow) - (base_actions | actions))
    if missing_workflow:
        raise SystemExit("staging deploy workflow actions are not covered by either IAM contract: " + ", ".join(missing_workflow))

    if args.render_output:
        if not args.account_id:
            raise SystemExit("--account-id is required with --render-output")
        args.render_output.write_text(
            json.dumps(render_policy_document(document, args.account_id), indent=2) + "\n",
            encoding="utf-8",
        )
    print(f"staging application-delivery IAM contract valid ({len(actions)} explicit actions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
