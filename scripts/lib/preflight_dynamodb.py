"""DynamoDB cache check for the staging preflight gate.

The staging and production-lean profiles use the Terraform-managed DynamoDB
cache table instead of Redis. This check verifies the selected table is
reachable, active, and has the single ``cache_key`` hash key expected by the
runtime cache and durable-store adapters.
"""

from __future__ import annotations

import asyncio
from typing import Any

from .preflight_results import CheckResult, failed, passed, skipped

CHECK_NAME = "dynamodb:cache-table"


async def run_dynamodb_checks(
    env: dict, *, dry_run: bool = False
) -> list[CheckResult]:
    if dry_run:
        return [skipped(CHECK_NAME, "dry-run: live DynamoDB checks are not executed")]

    table_name = env.get("DYNAMODB_CACHE_TABLE", "").strip()
    if not table_name:
        return [failed(
            CHECK_NAME,
            "DYNAMODB_CACHE_TABLE is not set",
            "set DYNAMODB_CACHE_TABLE to the Terraform-managed cache table",
        )]

    try:
        import boto3
    except ImportError as exc:
        return [failed(
            CHECK_NAME,
            f"boto3 is not installed: {exc}",
            "pip install -e '.[backend]' (or pip install boto3)",
        )]

    kwargs: dict[str, Any] = {
        "region_name": (
            env.get("AWS_REGION")
            or env.get("AWS_DEFAULT_REGION")
            or "us-east-1"
        ),
    }
    endpoint = env.get("DYNAMODB_ENDPOINT", "").strip()
    if endpoint:
        kwargs["endpoint_url"] = endpoint

    try:
        client = boto3.client("dynamodb", **kwargs)
        response = await asyncio.to_thread(
            client.describe_table,
            TableName=table_name,
        )
    except Exception as exc:
        return [failed(
            CHECK_NAME,
            f"DescribeTable failed for {table_name}: {exc}",
            "verify AWS credentials, region, table name, and DynamoDB access",
        )]

    table = response.get("Table") or {}
    status = table.get("TableStatus")
    key_schema = table.get("KeySchema") or []
    has_exact_cache_key_schema = key_schema == [
        {"AttributeName": "cache_key", "KeyType": "HASH"}
    ]
    if status != "ACTIVE" or not has_exact_cache_key_schema:
        return [failed(
            CHECK_NAME,
            f"{table_name} is status={status!r} with key schema {key_schema!r}; "
            "expected exactly one cache_key HASH key",
            "reconcile the table to the Terraform-managed single-key cache schema",
        )]
    return [passed(CHECK_NAME, f"{table_name} is ACTIVE with cache_key hash key")]
