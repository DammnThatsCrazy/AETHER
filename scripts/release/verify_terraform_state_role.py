#!/usr/bin/env python3
"""Verify the assumed apply role can access only the reviewed state paths.

This is an effective-policy check, not another copy of the checked-in
manifest. It uses IAM simulation after the role is assumed, so a missing or
stale attachment fails before Terraform can mutate infrastructure.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys


def _simulate(role: str, actions: list[str], resource: str, context: str | None = None) -> list[str]:
    cmd = [
        "aws", "iam", "simulate-principal-policy",
        "--policy-source-arn", role,
        "--action-names", *actions,
        "--resource-arns", resource,
        "--output", "json",
    ]
    if context:
        cmd.extend(["--context-entries", f"ContextKeyName=s3:prefix,ContextKeyValues={context},ContextKeyType=string"])
    result = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if result.returncode:
        return [f"IAM simulation failed: {result.stderr.strip() or result.stdout.strip()}"]
    try:
        evaluations = json.loads(result.stdout).get("EvaluationResults", [])
    except json.JSONDecodeError as exc:
        return [f"IAM simulation returned invalid JSON: {exc}"]
    failures = []
    for evaluation in evaluations:
        if evaluation.get("EvalDecision") != "allowed":
            failures.append(
                f"{evaluation.get('EvalActionName')} on {resource} evaluated as {evaluation.get('EvalDecision')}"
            )
    if len(evaluations) != len(actions):
        failures.append(f"IAM simulation returned {len(evaluations)} results for {len(actions)} actions")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role-arn", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--lock-table", required=True)
    parser.add_argument("--account-id", required=True)
    args = parser.parse_args()
    errors: list[str] = []
    if args.bucket != "aether-terraform-state":
        errors.append(
            "TF_STATE_BUCKET must be the canonical aether-terraform-state backend bucket"
        )
    if args.lock_table != "aether-terraform-locks":
        errors.append(
            "TF_LOCK_TABLE must be the canonical aether-terraform-locks backend table"
        )
    if errors:
        for error in errors:
            print(f"::error::{error}", file=sys.stderr)
        return 1
    bucket = f"arn:aws:s3:::{args.bucket}"
    objects = f"{bucket}/profiles/access-probe"
    lock = f"arn:aws:dynamodb:us-east-1:{args.account_id}:table/{args.lock_table}"
    errors += _simulate(args.role_arn, ["s3:ListBucket"], bucket, "profiles/")
    errors += _simulate(args.role_arn, ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"], objects)
    errors += _simulate(args.role_arn, ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem"], lock)
    if errors:
        for error in errors:
            print(f"::error::{error}", file=sys.stderr)
        return 1
    print("Effective Terraform state permissions match the reviewed least-privilege contract.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
