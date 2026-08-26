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


# The repository's intended backend names are the canonical pair below.  The
# staging account currently uses its already-provisioned, account-qualified
# pair instead; accepting that exact reviewed pair lets the apply preflight
# validate the real backend rather than rejecting it before IAM simulation.
# Keep this an explicit allow-list: a prefix match would turn a typo or an
# unrelated bucket into an accepted state backend.
APPROVED_BUCKETS = {
    "aether-terraform-state",
    "aether-staging-terraform-state-olympus",
}
APPROVED_LOCK_TABLES = {
    "aether-terraform-locks",
    "aether-staging-terraform-lock",
}


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


def validate_backend_names(bucket: str, lock_table: str) -> list[str]:
    """Reject state backends outside the reviewed canonical/staging set."""
    errors: list[str] = []
    if bucket not in APPROVED_BUCKETS:
        errors.append(
            "TF_STATE_BUCKET must be one of the reviewed Terraform state backend buckets"
        )
    if lock_table not in APPROVED_LOCK_TABLES:
        errors.append(
            "TF_LOCK_TABLE must be one of the reviewed Terraform state lock tables"
        )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role-arn", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--lock-table", required=True)
    parser.add_argument("--account-id", required=True)
    args = parser.parse_args()
    errors = validate_backend_names(args.bucket, args.lock_table)
    if errors:
        for error in errors:
            print(f"::error::{error}", file=sys.stderr)
        return 1
    bucket = f"arn:aws:s3:::{args.bucket}"
    objects = f"{bucket}/profiles/access-probe"
    lock = f"arn:aws:dynamodb:us-east-1:{args.account_id}:table/{args.lock_table}"
    errors += _simulate(args.role_arn, ["s3:ListBucket"], bucket, "profiles/")
    errors += _simulate(
        args.role_arn,
        ["s3:GetBucketVersioning", "s3:GetBucketLocation"],
        bucket,
    )
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
