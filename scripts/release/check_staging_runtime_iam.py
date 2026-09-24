#!/usr/bin/env python3
"""Verify the ECS task role can use the selected staging cache backend.

The Terraform plan can prove that the DynamoDB cache table exists and the ECS
task definition can prove that it names that table. Neither proves that the
running application task role can perform the cache health probe. This check
uses IAM policy simulation against the exact task-role/table pair after
Terraform apply and fails before the staging rehearsal when any required
operation is implicitly or explicitly denied. Its live-ECS mode performs the
same check before wake planning, against the task roles and cache table already
registered in ECS; the post-apply mode remains as a second checkpoint.

No secret values are read.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import Any


REQUIRED_CACHE_ACTIONS: tuple[str, ...] = (
    "dynamodb:DescribeTable",
    "dynamodb:GetItem",
    "dynamodb:PutItem",
    "dynamodb:UpdateItem",
    "dynamodb:DeleteItem",
    "dynamodb:Query",
    "dynamodb:Scan",
    "dynamodb:BatchGetItem",
    "dynamodb:BatchWriteItem",
)

STAGING_SERVICES = {
    "AETHER-staging-backend": "aether-backend",
    "AETHER-staging-lean-worker": "lean-worker",
}

AwsCall = Callable[[list[str]], Mapping[str, Any]]
CacheSimulator = Callable[..., list[str]]


def aws_json(args: list[str]) -> Mapping[str, Any]:
    """Run a metadata-only AWS CLI request and require a JSON object."""

    result = subprocess.run(
        ["aws", *args, "--output", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        raise RuntimeError(
            f"AWS metadata request failed for {args[0]}"
            + (f": {detail[-1]}" if detail else "")
        )
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"AWS metadata request for {args[0]} returned invalid JSON") from exc
    if not isinstance(payload, Mapping):
        raise RuntimeError(f"AWS metadata request for {args[0]} returned a non-object")
    return payload


def simulate_cache_policy(
    role_arn: str,
    table_arn: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    region: str | None = None,
) -> list[str]:
    """Return one error for each cache action not allowed on the table ARN."""

    command = [
        "aws",
        "iam",
        "simulate-principal-policy",
        "--policy-source-arn",
        role_arn,
        "--action-names",
        *REQUIRED_CACHE_ACTIONS,
        "--resource-arns",
        table_arn,
        "--output",
        "json",
    ]
    if region:
        command.extend(["--region", region])
    result = runner(command, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(
            "IAM simulation failed for the staging ECS task role"
            + (f": {detail}" if detail else "")
        )
    try:
        payload: dict[str, Any] = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("IAM simulation returned invalid JSON") from exc

    evaluations = payload.get("EvaluationResults")
    if not isinstance(evaluations, list):
        raise RuntimeError("IAM simulation returned no EvaluationResults")

    decisions = {
        str(item.get("EvalActionName")): str(item.get("EvalDecision", "")).lower()
        for item in evaluations
        if isinstance(item, dict)
    }
    return [
        f"{action} on {table_arn} is {decisions.get(action, 'missing')}, expected allowed"
        for action in REQUIRED_CACHE_ACTIONS
        if decisions.get(action) != "allowed"
    ]


def live_ecs_cache_errors(
    *,
    cluster: str,
    expected_table_name: str,
    region: str,
    client: AwsCall | None = None,
    simulator: CacheSimulator | None = None,
) -> list[str]:
    """Check each live staging task role against its configured cache table.

    Only ECS task-definition metadata and DynamoDB table metadata are read;
    secret values and cache records are never accessed.
    """

    aws = client or aws_json
    simulate = simulator or simulate_cache_policy
    errors: list[str] = []
    identity = aws(["sts", "get-caller-identity"])
    account_id = identity.get("Account")
    if not isinstance(account_id, str) or len(account_id) != 12 or not account_id.isdigit():
        return ["AWS caller identity did not provide a valid 12-digit account ID"]

    services_payload = aws(
        [
            "ecs",
            "describe-services",
            "--cluster",
            cluster,
            "--services",
            *STAGING_SERVICES,
            "--region",
            region,
        ]
    )
    service_rows = services_payload.get("services")
    failures = services_payload.get("failures")
    if isinstance(failures, list) and failures:
        return ["ECS could not resolve every staging cache service"]
    if not isinstance(service_rows, list):
        return ["ECS describe-services returned no staging service list"]
    by_name = {
        str(row.get("serviceName")): row
        for row in service_rows
        if isinstance(row, dict) and isinstance(row.get("serviceName"), str)
    }
    if len(service_rows) != len(STAGING_SERVICES) or set(by_name) != set(STAGING_SERVICES):
        return [
            "ECS staging cache services do not match the required pair: "
            + ", ".join(sorted(by_name))
        ]

    role_services: dict[str, list[str]] = {}
    for service_name, container_name in STAGING_SERVICES.items():
        task_definition_arn = by_name[service_name].get("taskDefinition")
        if not isinstance(task_definition_arn, str) or not task_definition_arn:
            errors.append(f"{service_name}: ECS service has no task definition")
            continue
        task_payload = aws(
            [
                "ecs",
                "describe-task-definition",
                "--task-definition",
                task_definition_arn,
                "--region",
                region,
            ]
        )
        definition = task_payload.get("taskDefinition")
        if not isinstance(definition, dict):
            errors.append(f"{service_name}: ECS task definition metadata is missing")
            continue
        role_arn = definition.get("taskRoleArn")
        if (
            not isinstance(role_arn, str)
            or not role_arn.startswith(f"arn:aws:iam::{account_id}:role/")
        ):
            errors.append(f"{service_name}: task role is missing or belongs to another AWS account")
            continue

        containers = definition.get("containerDefinitions")
        matches = [
            row
            for row in containers or []
            if isinstance(row, dict) and row.get("name") == container_name
        ] if isinstance(containers, list) else []
        if len(matches) != 1:
            errors.append(f"{service_name}: expected exactly one {container_name} container")
            continue
        environment_rows = matches[0].get("environment")
        if not isinstance(environment_rows, list):
            errors.append(f"{service_name}: cache environment metadata is missing")
            continue
        environment = {
            row.get("name"): row.get("value")
            for row in environment_rows
            if isinstance(row, dict)
        }
        if environment.get("CACHE_BACKEND") != "dynamodb":
            errors.append(f"{service_name}: CACHE_BACKEND is not dynamodb")
        if environment.get("DYNAMODB_CACHE_TABLE") != expected_table_name:
            errors.append(
                f"{service_name}: DYNAMODB_CACHE_TABLE is not the expected staging table"
            )
        role_services.setdefault(role_arn, []).append(service_name)

    if errors:
        return errors

    table_payload = aws(
        [
            "dynamodb",
            "describe-table",
            "--table-name",
            expected_table_name,
            "--region",
            region,
        ]
    )
    table = table_payload.get("Table")
    if not isinstance(table, dict):
        return [f"DynamoDB cache table {expected_table_name} was not found"]
    table_arn = table.get("TableArn")
    expected_arn_prefix = f"arn:aws:dynamodb:{region}:{account_id}:table/"
    if table.get("TableName") != expected_table_name:
        errors.append("DynamoDB returned a table name different from the expected staging table")
    if table.get("TableStatus") != "ACTIVE":
        errors.append(f"DynamoDB cache table {expected_table_name} is not ACTIVE")
    if not isinstance(table_arn, str) or not table_arn.startswith(expected_arn_prefix):
        errors.append("DynamoDB cache table ARN is outside the expected staging account or region")
    if errors:
        return errors

    for role_arn, services in role_services.items():
        try:
            denied = simulate(role_arn, table_arn, region=region)
        except RuntimeError as exc:
            errors.append(f"{', '.join(services)}: {exc}")
            continue
        errors.extend(f"{', '.join(services)}: {denial}" for denial in denied)
    return errors


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--role-arn")
    mode.add_argument("--live-ecs-cluster")
    parser.add_argument("--table-arn")
    parser.add_argument("--expected-table-name")
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args(argv)

    try:
        if args.live_ecs_cluster:
            if not args.expected_table_name:
                parser.error("--expected-table-name is required with --live-ecs-cluster")
            errors = live_ecs_cache_errors(
                cluster=args.live_ecs_cluster,
                expected_table_name=args.expected_table_name,
                region=args.region,
            )
            success_message = (
                "staging ECS cache IAM contract valid for the live service task roles: "
                f"cluster={args.live_ecs_cluster}; table={args.expected_table_name}"
            )
        else:
            if not args.role_arn or not args.table_arn:
                parser.error("--role-arn and --table-arn are both required for post-apply mode")
            errors = simulate_cache_policy(args.role_arn, args.table_arn, region=args.region)
            success_message = (
                "staging ECS cache IAM contract valid: "
                f"role={args.role_arn}; table={args.table_arn}"
            )
    except RuntimeError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    if errors:
        print("staging ECS cache IAM contract FAILED:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(success_message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
