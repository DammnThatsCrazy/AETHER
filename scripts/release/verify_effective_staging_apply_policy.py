#!/usr/bin/env python3
"""Fail closed when the staging apply role does not realize its contract.

The checked-in YAML is the reviewed intent. This check reads the policies
actually attached to the assumed role and verifies every reviewed operation
against Allow/Deny effects, resource coverage, and condition compatibility.
Action-name presence alone is not sufficient: a wrong ARN, an unsatisfied
condition, or an overriding Deny must fail before Terraform mutation.
It deliberately does not print policy documents or secret values.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
import urllib.parse
from pathlib import Path
from typing import Any, NoReturn

import yaml


def fail(message: str) -> NoReturn:
    print(f"::error::{message}", file=sys.stderr)
    raise SystemExit(1)


def aws_json(*args: str) -> dict[str, Any]:
    result = subprocess.run(
        ["aws", *args, "--output", "json"], text=True, capture_output=True, check=False
    )
    if result.returncode:
        fail(
            f"AWS policy inspection failed for {args[0]}: {result.stderr.strip() or result.stdout.strip()}"
        )
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        fail(f"AWS policy inspection returned invalid JSON for {args[0]}: {exc}")
    if isinstance(value, str):
        value = json.loads(urllib.parse.unquote(value))
    return value


def role_name_from_arn(role_arn: str) -> str:
    prefix = "arn:aws:iam::"
    if not role_arn.startswith(prefix) or ":role/" not in role_arn:
        fail("role ARN must be a concrete IAM role ARN")
    name = role_arn.split(":role/", 1)[1]
    if "/" in name:
        fail("role ARN paths are not accepted for the staging apply role")
    return name


def policy_statements(document: dict[str, Any]) -> list[dict[str, Any]]:
    statements: list[dict[str, Any]] = []
    statements = document.get("Statement", [])
    if isinstance(statements, dict):
        statements = [statements]
    return [statement for statement in statements if isinstance(statement, dict)]


def policy_actions(document: dict[str, Any]) -> set[str]:
    """Return Allow actions for backwards-compatible diagnostics/tests."""
    allowed: set[str] = set()
    for statement in policy_statements(document):
        if statement.get("Effect") != "Allow":
            continue
        actions = statement.get("Action", [])
        if isinstance(actions, str):
            actions = [actions]
        allowed.update(action for action in actions if isinstance(action, str))
    return allowed


def load_effective_statements(role_name: str) -> tuple[list[dict[str, Any]], list[str]]:
    statements: list[dict[str, Any]] = []
    policy_names: list[str] = []
    inline = aws_json("iam", "list-role-policies", "--role-name", role_name)
    for name in inline.get("PolicyNames", []):
        policy_names.append(f"inline:{name}")
        document = aws_json(
            "iam", "get-role-policy", "--role-name", role_name, "--policy-name", name
        )
        raw = document.get("PolicyDocument", {})
        if isinstance(raw, str):
            raw = json.loads(urllib.parse.unquote(raw))
        statements.extend(policy_statements(raw))

    attached = aws_json("iam", "list-attached-role-policies", "--role-name", role_name)
    for policy in attached.get("AttachedPolicies", []):
        arn = policy.get("PolicyArn")
        name = policy.get("PolicyName", arn)
        if not arn:
            continue
        policy_names.append(f"managed:{name}")
        meta = aws_json("iam", "get-policy", "--policy-arn", arn)
        version = (meta.get("Policy", {}) or {}).get("DefaultVersionId")
        if not version:
            fail(f"managed policy {name} has no default version")
        version_doc = aws_json(
            "iam", "get-policy-version", "--policy-arn", arn, "--version-id", version
        )
        raw = (version_doc.get("PolicyVersion", {}) or {}).get("Document", {})
        if isinstance(raw, str):
            raw = json.loads(urllib.parse.unquote(raw))
        statements.extend(policy_statements(raw))
    return statements, policy_names


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return [value]


def _statement_actions(statement: dict[str, Any]) -> list[str]:
    return [value for value in _as_list(statement.get("Action", [])) if isinstance(value, str)]


def _statement_resources(statement: dict[str, Any]) -> list[str]:
    return [value for value in _as_list(statement.get("Resource", "*")) if isinstance(value, str)]


def _conditions_compatible(
    actual: Any, required: dict[str, Any] | None,
) -> bool:
    """Return whether an attached Allow can satisfy the reviewed context.

    An absent condition is broader and therefore compatible. If an attached
    statement adds a condition, the manifest must provide a matching key/value
    (including list-valued contexts). Unknown operators are rejected instead of
    being treated as equivalent by accident.
    """
    if not actual:
        return True
    if not isinstance(actual, dict) or not isinstance(required, dict):
        return False
    for operator, entries in actual.items():
        if operator not in {"StringEquals", "StringLike", "ArnEquals", "ArnLike", "ForAllValues:StringEquals", "ForAnyValue:StringEquals"}:
            return False
        if not isinstance(entries, dict):
            return False
        for key, actual_value in entries.items():
            if key not in required:
                return False
            wanted = required[key]
            actual_values = {str(v) for v in _as_list(actual_value)}
            wanted_values = {str(v) for v in _as_list(wanted)}
            if operator in {"StringLike", "ArnLike"}:
                if not any(
                    fnmatch.fnmatchcase(wanted_value, actual_pattern)
                    for wanted_value in wanted_values
                    for actual_pattern in actual_values
                ):
                    return False
            elif not (wanted_values & actual_values):
                return False
    return True


def _resource_sample(resource: str) -> str:
    """Make a deterministic concrete value for a reviewed ARN pattern."""
    if resource == "*":
        return resource
    return resource.replace("*", "contract-check")


def _operation_is_covered(
    statement: dict[str, Any], action: str, resource: str, conditions: dict[str, Any] | None,
) -> bool:
    if statement.get("Effect") != "Allow":
        return False
    if not any(fnmatch.fnmatchcase(action, pattern) for pattern in _statement_actions(statement)):
        return False
    sample = _resource_sample(resource)
    if not any(fnmatch.fnmatchcase(sample, pattern) for pattern in _statement_resources(statement)):
        return False
    return _conditions_compatible(statement.get("Condition"), conditions)


def _operation_is_denied(statement: dict[str, Any], action: str, resource: str) -> bool:
    if statement.get("Effect") != "Deny":
        return False
    if not any(fnmatch.fnmatchcase(action, pattern) for pattern in _statement_actions(statement)):
        return False
    sample = _resource_sample(resource)
    return any(fnmatch.fnmatchcase(sample, pattern) for pattern in _statement_resources(statement))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role-arn", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()

    role_name = role_name_from_arn(args.role_arn)
    if role_name != "AetherStagingDeploy":
        fail(f"effective policy check must target AetherStagingDeploy, not {role_name}")
    manifest = yaml.safe_load(Path(args.manifest).read_text()) or {}
    statements = manifest.get("statements")
    if manifest.get("profile") != "staging" or not isinstance(statements, list):
        fail("staging apply IAM manifest is malformed")
    account_id = args.role_arn.split(":", 4)[4].split(":", 1)[0]
    required_operations: list[tuple[str, str, dict[str, Any] | None]] = []
    for statement in statements:
        if not isinstance(statement, dict):
            continue
        resources = _as_list(statement.get("resource", "*"))
        conditions = statement.get("conditions")
        for action in statement.get("actions") or []:
            if not isinstance(action, str):
                continue
            for resource in resources:
                if isinstance(resource, str):
                    required_operations.append(
                        (action, resource.replace("${account_id}", account_id), conditions)
                    )
    if not required_operations:
        fail("staging apply IAM manifest declares no actions")
    effective, policy_names = load_effective_statements(role_name)
    denied = sorted(
        f"{action} on {resource}"
        for action, resource, _ in required_operations
        if any(_operation_is_denied(statement, action, resource) for statement in effective)
    )
    if denied:
        fail("AetherStagingDeploy has an explicit Deny for reviewed operations: " + "; ".join(denied))
    missing = sorted(
        f"{action} on {resource}"
        for action, resource, conditions in required_operations
        if not any(_operation_is_covered(statement, action, resource, conditions) for statement in effective)
    )
    if missing:
        fail(
            "AetherStagingDeploy effective policy does not cover reviewed operations: "
            + ", ".join(missing)
        )
    if not any(name.endswith("AetherStagingApplyMissingOps") for name in policy_names):
        fail("AetherStagingApplyMissingOps is not attached to AetherStagingDeploy")
    print(
        f"Effective staging apply policy covers {len(required_operations)} reviewed operations across {len(policy_names)} attached policies."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
