#!/usr/bin/env python3
"""Fail closed when the staging apply role does not realize its contract.

The checked-in YAML is the reviewed intent.  This check reads the policies
actually attached to the assumed role and verifies that every reviewed action
is present in an Allow statement.  It deliberately does not print policy
documents or secret values.
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


def policy_actions(document: dict[str, Any]) -> set[str]:
    allowed: set[str] = set()
    statements = document.get("Statement", [])
    if isinstance(statements, dict):
        statements = [statements]
    for statement in statements:
        if not isinstance(statement, dict) or statement.get("Effect") != "Allow":
            continue
        actions = statement.get("Action", [])
        if isinstance(actions, str):
            actions = [actions]
        allowed.update(action for action in actions if isinstance(action, str))
    return allowed


def load_effective_actions(role_name: str) -> tuple[set[str], list[str]]:
    actions: set[str] = set()
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
        actions.update(policy_actions(raw))

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
        actions.update(policy_actions(raw))
    return actions, policy_names


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
    required = {
        action
        for statement in statements
        if isinstance(statement, dict)
        for action in (statement.get("actions") or [])
        if isinstance(action, str)
    }
    if not required:
        fail("staging apply IAM manifest declares no actions")
    effective, policy_names = load_effective_actions(role_name)
    missing = sorted(
        action
        for action in required
        if not any(fnmatch.fnmatchcase(action, pattern) for pattern in effective)
    )
    if missing:
        fail(
            "AetherStagingDeploy effective policy is missing reviewed actions: "
            + ", ".join(missing)
        )
    if not any(name.endswith("AetherStagingApplyMissingOps") for name in policy_names):
        fail("AetherStagingApplyMissingOps is not attached to AetherStagingDeploy")
    print(
        f"Effective staging apply policy covers {len(required)} reviewed actions across {len(policy_names)} attached policies."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
