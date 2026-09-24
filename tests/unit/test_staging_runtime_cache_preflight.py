"""Tests for the pre-wake live ECS cache permission check."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/release/check_staging_runtime_iam.py"
SPEC = importlib.util.spec_from_file_location("staging_runtime_iam", SCRIPT)
assert SPEC and SPEC.loader
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


ACCOUNT_ID = "544471417928"
TABLE_NAME = "AETHER-staging-cache"
TABLE_ARN = f"arn:aws:dynamodb:us-east-1:{ACCOUNT_ID}:table/{TABLE_NAME}"


def _definition(role_name: str, container_name: str, table_name: str = TABLE_NAME) -> dict[str, Any]:
    return {
        "taskRoleArn": f"arn:aws:iam::{ACCOUNT_ID}:role/{role_name}",
        "containerDefinitions": [
            {
                "name": container_name,
                "environment": [
                    {"name": "CACHE_BACKEND", "value": "dynamodb"},
                    {"name": "DYNAMODB_CACHE_TABLE", "value": table_name},
                ],
            }
        ],
    }


def _client(*, backend_table: str = TABLE_NAME, status: str = "ACTIVE"):
    definitions = {
        "backend": _definition(
            "AETHER-staging-ecs-task-role", "aether-backend", backend_table
        ),
        "worker": _definition(
            "AETHER-staging-ecs-worker-task-role", "lean-worker"
        ),
    }

    def call(args: list[str]) -> dict[str, Any]:
        if args[:2] == ["sts", "get-caller-identity"]:
            return {"Account": ACCOUNT_ID}
        if args[:2] == ["ecs", "describe-services"]:
            return {
                "services": [
                    {
                        "serviceName": service,
                        "taskDefinition": f"arn:aws:ecs:us-east-1:{ACCOUNT_ID}:task-definition/{suffix}:1",
                    }
                    for service, suffix in (
                        ("AETHER-staging-backend", "backend"),
                        ("AETHER-staging-lean-worker", "worker"),
                    )
                ],
                "failures": [],
            }
        if args[:2] == ["ecs", "describe-task-definition"]:
            definition_key = "backend" if "backend:1" in args[args.index("--task-definition") + 1] else "worker"
            return {"taskDefinition": definitions[definition_key]}
        if args[:2] == ["dynamodb", "describe-table"]:
            return {
                "Table": {
                    "TableName": TABLE_NAME,
                    "TableArn": TABLE_ARN,
                    "TableStatus": status,
                }
            }
        raise AssertionError(args)

    return call


def test_live_preflight_simulates_cache_permissions_for_each_task_role():
    simulated: list[tuple[str, str, str]] = []

    def simulator(role_arn: str, table_arn: str, *, region: str) -> list[str]:
        simulated.append((role_arn, table_arn, region))
        return []

    errors = checker.live_ecs_cache_errors(
        cluster="AETHER-staging",
        expected_table_name=TABLE_NAME,
        region="us-east-1",
        client=_client(),
        simulator=simulator,
    )

    assert errors == []
    assert simulated == [
        (
            f"arn:aws:iam::{ACCOUNT_ID}:role/AETHER-staging-ecs-task-role",
            TABLE_ARN,
            "us-east-1",
        ),
        (
            f"arn:aws:iam::{ACCOUNT_ID}:role/AETHER-staging-ecs-worker-task-role",
            TABLE_ARN,
            "us-east-1",
        ),
    ]


def test_live_preflight_fails_before_simulation_for_miswired_cache_table():
    simulated: list[str] = []

    def simulator(role_arn: str, table_arn: str, *, region: str) -> list[str]:
        simulated.append(role_arn)
        return []

    errors = checker.live_ecs_cache_errors(
        cluster="AETHER-staging",
        expected_table_name=TABLE_NAME,
        region="us-east-1",
        client=_client(backend_table="AETHER-production-cache"),
        simulator=simulator,
    )

    assert errors == [
        "AETHER-staging-backend: DYNAMODB_CACHE_TABLE is not the expected staging table"
    ]
    assert simulated == []


def test_live_preflight_reports_a_denied_cache_action_for_the_role():
    def simulator(role_arn: str, table_arn: str, *, region: str) -> list[str]:
        if role_arn.endswith("AETHER-staging-ecs-task-role"):
            return [f"dynamodb:DescribeTable on {table_arn} is implicitDeny, expected allowed"]
        return []

    errors = checker.live_ecs_cache_errors(
        cluster="AETHER-staging",
        expected_table_name=TABLE_NAME,
        region="us-east-1",
        client=_client(),
        simulator=simulator,
    )

    assert errors == [
        "AETHER-staging-backend: dynamodb:DescribeTable on "
        f"{TABLE_ARN} is implicitDeny, expected allowed"
    ]


def test_live_preflight_rejects_inactive_cache_table():
    errors = checker.live_ecs_cache_errors(
        cluster="AETHER-staging",
        expected_table_name=TABLE_NAME,
        region="us-east-1",
        client=_client(status="CREATING"),
        simulator=lambda *_args, **_kwargs: [],
    )

    assert errors == [f"DynamoDB cache table {TABLE_NAME} is not ACTIVE"]
