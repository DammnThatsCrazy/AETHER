#!/usr/bin/env python3
"""Verify the ECS task role can use the selected staging cache backend.

The Terraform plan can prove that the DynamoDB cache table exists and the ECS
task definition can prove that it names that table. Neither proves that the
running application task role can perform the cache health probe. This check
uses IAM policy simulation against the exact task-role/table pair after
Terraform apply and fails before the staging rehearsal when any required
operation is implicitly or explicitly denied.

No secret values are read.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable, Sequence
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


def simulate_cache_policy(
    role_arn: str,
    table_arn: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role-arn", required=True)
    parser.add_argument("--table-arn", required=True)
    args = parser.parse_args(argv)

    try:
        errors = simulate_cache_policy(args.role_arn, args.table_arn)
    except RuntimeError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    if errors:
        print("staging ECS cache IAM contract FAILED:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(
        "staging ECS cache IAM contract valid: "
        f"role={args.role_arn}; table={args.table_arn}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
