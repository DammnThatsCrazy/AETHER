#!/usr/bin/env python3
"""Reconcile and verify the externally managed staging Terraform plan role.

The staging plan role is intentionally outside Terraform state.  This command
is the narrow, confirmation-gated bridge between the reviewed
``config/staging_plan_iam_policy.yaml`` contract and that live role.  It only
updates one inline policy on ``AetherStagingPlan`` and then delegates to the
existing effective-policy verifier.  It never reads application secret
values, changes infrastructure, or grants Terraform mutation permissions.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, NoReturn

import yaml


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "config/staging_plan_iam_policy.yaml"
DEFAULT_SUPPLEMENTAL_MANIFEST = ROOT / "config/terraform_plan_state_access_policy.yaml"
VERIFY_SCRIPT = ROOT / "scripts/release/verify_effective_staging_apply_policy.py"
EXPECTED_ROLE = "AetherStagingPlan"
EXPECTED_POLICY_NAME = "AetherStagingPlanContract"
CONFIRMATION = "RECONCILE-STAGING-PLAN-IAM"
ROLE_PATTERN = re.compile(r"^arn:aws:iam::(?P<account>[0-9]{12}):role/AetherStagingPlan$")
ACCOUNT_PATTERN = re.compile(r"^[0-9]{12}$")
ACTION_PATTERN = re.compile(r"^[a-z0-9-]+:[A-Za-z0-9*?]+$")
RESOURCE_PATTERN = re.compile(r"^arn:aws:[A-Za-z0-9-]+:[^\s]*$")
SUPPORTED_CONDITION_OPERATORS = frozenset(
    {
        "StringEquals",
        "StringLike",
        "NumericEquals",
        "ArnEquals",
        "ArnLike",
        "ForAllValues:StringEquals",
        "ForAnyValue:StringEquals",
        "ForAnyValue:StringLike",
    }
)
READ_ONLY_ACTION_PREFIXES = (
    "Describe",
    "Get",
    "List",
    "Head",
    "BatchGet",
    "Simulate",
)


def fail(message: str) -> NoReturn:
    print(f"::error::{message}", file=sys.stderr)
    raise SystemExit(1)


def _as_list(value: Any, *, field: str) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, (str, int, float, bool)):
        return [value]
    fail(f"{field} must be a scalar or list")


def _resolve_account(value: Any, account_id: str) -> Any:
    if isinstance(value, str):
        return value.replace("${account_id}", account_id)
    if isinstance(value, list):
        return [_resolve_account(item, account_id) for item in value]
    if isinstance(value, dict):
        return {
            key: _resolve_account(item, account_id) for key, item in value.items()
        }
    return value


def _validate_string_values(values: Any, *, field: str) -> list[str]:
    result = _as_list(values, field=field)
    if not result or any(not isinstance(value, (str, int, float, bool)) for value in result):
        fail(f"{field} must contain only scalar IAM values")
    return [str(value) for value in result]


def _render_condition(statement: dict[str, Any], *, account_id: str) -> dict[str, dict[str, list[str]]]:
    raw = _resolve_account(statement.get("conditions"), account_id)
    operators = statement.get("condition_operators") or {}
    if not isinstance(operators, dict):
        fail(f"{statement.get('sid', '<unknown>')} condition_operators must be a mapping")
    if not raw:
        if operators:
            fail(f"{statement.get('sid', '<unknown>')} declares operators without conditions")
        return {}
    if not isinstance(raw, dict):
        fail(f"{statement.get('sid', '<unknown>')} conditions must be a mapping")

    # Already-nested AWS condition documents are preserved.  The checked-in
    # plan manifest currently uses flat key/value conditions, which default to
    # StringEquals unless condition_operators explicitly selects another
    # reviewed operator.
    nested = bool(raw) and all(
        key in SUPPORTED_CONDITION_OPERATORS and isinstance(value, dict)
        for key, value in raw.items()
    )
    if nested:
        if operators:
            fail(f"{statement.get('sid', '<unknown>')} cannot mix nested conditions and condition_operators")
        return {
            operator: {
                str(key): _validate_string_values(value, field=f"{statement.get('sid', '<unknown>')}.{operator}.{key}")
                for key, value in entries.items()
            }
            for operator, entries in raw.items()
        }

    rendered: dict[str, dict[str, list[str]]] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key:
            fail(f"{statement.get('sid', '<unknown>')} condition keys must be non-empty strings")
        operator = operators.get(key, "StringEquals")
        if not isinstance(operator, str) or operator not in SUPPORTED_CONDITION_OPERATORS:
            fail(f"{statement.get('sid', '<unknown>')} uses unsupported IAM condition operator")
        rendered.setdefault(operator, {})[key] = _validate_string_values(
            value, field=f"{statement.get('sid', '<unknown>')}.{key}"
        )
    return rendered


def render_policy_document(manifest: dict[str, Any], *, account_id: str) -> dict[str, Any]:
    """Render the reviewed YAML contract as an account-bound IAM document."""
    if not ACCOUNT_PATTERN.fullmatch(account_id):
        fail("AWS account id must contain exactly 12 digits")
    if manifest.get("version") != 1:
        fail("staging plan IAM manifest version must be 1")
    if manifest.get("profile") != "staging":
        fail("staging plan IAM manifest must target profile staging")
    if manifest.get("role") != EXPECTED_ROLE:
        fail(f"staging plan IAM manifest must target {EXPECTED_ROLE}")
    statements = manifest.get("statements")
    if not isinstance(statements, list) or not statements:
        fail("staging plan IAM manifest must declare a non-empty statements list")

    rendered: list[dict[str, Any]] = []
    seen_sids: set[str] = set()
    for statement in statements:
        if not isinstance(statement, dict):
            fail("staging plan IAM manifest contains a non-object statement")
        sid = statement.get("sid")
        if not isinstance(sid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", sid):
            fail("staging plan IAM statements require a safe sid")
        if sid in seen_sids:
            fail(f"duplicate staging plan IAM sid: {sid}")
        seen_sids.add(sid)

        actions = _validate_string_values(statement.get("actions"), field=f"{sid}.actions")
        for action in actions:
            if not ACTION_PATTERN.fullmatch(action) or action == "*" or action.endswith(":*"):
                fail(f"{sid} contains a wildcard IAM action outside the reviewed plan contract")
            action_name = action.split(":", 1)[1]
            if not action_name.startswith(READ_ONLY_ACTION_PREFIXES):
                fail(f"{sid} contains non-read-only IAM action {action}")

        resources = _validate_string_values(
            statement.get("resource", "*"), field=f"{sid}.resource"
        )
        resources = [str(_resolve_account(resource, account_id)) for resource in resources]
        for resource in resources:
            if resource != "*" and ("${" in resource or not RESOURCE_PATTERN.fullmatch(resource)):
                fail(f"{sid} contains an invalid or unresolved IAM resource")

        item: dict[str, Any] = {
            "Sid": sid,
            "Effect": "Allow",
            "Action": actions,
            "Resource": resources,
        }
        condition = _render_condition(statement, account_id=account_id)
        if condition:
            item["Condition"] = condition
        rendered.append(item)

    return {"Version": "2012-10-17", "Statement": rendered}


def target_role_parts(role_arn: str) -> tuple[str, str]:
    match = ROLE_PATTERN.fullmatch(role_arn)
    if not match:
        fail("target role ARN must be the unscoped AetherStagingPlan role")
    return match.group("account"), EXPECTED_ROLE


def _run(command: list[str], *, description: str) -> str:
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic returned"
        fail(f"{description} failed: {detail}")
    return result.stdout


def _verify_effective_policy(
    *,
    role_arn: str,
    manifest: Path,
    supplemental_manifest: Path,
    state_bucket: str,
    state_lock_table: str,
    attempts: int,
    delay_seconds: float,
) -> None:
    command = [
        sys.executable,
        str(VERIFY_SCRIPT),
        "--role-arn",
        role_arn,
        "--manifest",
        str(manifest),
        "--supplemental-manifest",
        str(supplemental_manifest),
        "--state-bucket",
        state_bucket,
        "--state-lock-table",
        state_lock_table,
        "--state-profile",
        "staging",
        "--expected-role",
        EXPECTED_ROLE,
        "--required-policy-suffix",
        EXPECTED_POLICY_NAME,
    ]
    last_error = "effective policy verification returned no diagnostic"
    for attempt in range(1, attempts + 1):
        result = subprocess.run(command, text=True, capture_output=True, check=False)
        if result.returncode == 0:
            if result.stdout:
                print(result.stdout, end="")
            return
        last_error = result.stderr.strip() or result.stdout.strip() or last_error
        if attempt < attempts:
            time.sleep(delay_seconds)
    fail(f"effective {EXPECTED_ROLE} policy did not verify after {attempts} attempts: {last_error}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role-arn", required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--supplemental-manifest", type=Path, default=DEFAULT_SUPPLEMENTAL_MANIFEST)
    parser.add_argument("--state-bucket", required=True)
    parser.add_argument("--state-lock-table", required=True)
    parser.add_argument("--confirmation", required=True)
    parser.add_argument("--verification-attempts", type=int, default=6)
    parser.add_argument("--verification-delay-seconds", type=float, default=5.0)
    args = parser.parse_args(argv)

    if args.confirmation != CONFIRMATION:
        fail("confirmation token does not authorize staging plan-role reconciliation")
    if args.verification_attempts < 1:
        fail("verification-attempts must be at least 1")
    if args.verification_delay_seconds < 0:
        fail("verification-delay-seconds cannot be negative")
    if not args.manifest.is_file() or not args.supplemental_manifest.is_file():
        fail("reviewed IAM manifest or supplemental state manifest is missing")

    account_id, role_name = target_role_parts(args.role_arn)
    try:
        manifest = yaml.safe_load(args.manifest.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        fail(f"staging plan IAM manifest is invalid YAML: {exc}")
    if not isinstance(manifest, dict):
        fail("staging plan IAM manifest root must be a mapping")
    document = render_policy_document(manifest, account_id=account_id)

    caller_account = _run(
        ["aws", "sts", "get-caller-identity", "--query", "Account", "--output", "text"],
        description="AWS caller identity check",
    ).strip()
    if caller_account != account_id:
        fail("reconciliation caller account does not match the target plan-role account")
    live_role_arn = _run(
        ["aws", "iam", "get-role", "--role-name", role_name, "--query", "Role.Arn", "--output", "text"],
        description="target plan-role lookup",
    ).strip()
    if live_role_arn != args.role_arn:
        fail("target plan role lookup did not resolve to the requested unscoped role ARN")

    policy_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".json", prefix="staging-plan-iam-", delete=False
        ) as handle:
            json.dump(document, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            policy_path = handle.name
        _run(
            [
                "aws",
                "iam",
                "put-role-policy",
                "--role-name",
                role_name,
                "--policy-name",
                EXPECTED_POLICY_NAME,
                "--policy-document",
                f"file://{policy_path}",
            ],
            description="reviewed staging plan IAM policy reconciliation",
        )
    finally:
        if policy_path:
            Path(policy_path).unlink(missing_ok=True)

    print(f"Applied the reviewed {EXPECTED_POLICY_NAME} policy to {EXPECTED_ROLE}; verifying effective coverage.")
    _verify_effective_policy(
        role_arn=args.role_arn,
        manifest=args.manifest,
        supplemental_manifest=args.supplemental_manifest,
        state_bucket=args.state_bucket,
        state_lock_table=args.state_lock_table,
        attempts=args.verification_attempts,
        delay_seconds=args.verification_delay_seconds,
    )
    print(f"Verified the effective {EXPECTED_ROLE} read-only plan contract.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
