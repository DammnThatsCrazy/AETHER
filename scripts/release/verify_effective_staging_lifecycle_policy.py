#!/usr/bin/env python3
"""Verify the live staging lifecycle role realizes its reviewed policy.

The lifecycle role is externally managed, so the checked-in manifest alone is
not evidence that the role used by the TTL guard has the required permissions.
This read-only check compares the exact reviewed inline policy and rejects
unexpected attached managed policies before a lifecycle workflow can mutate
ECS, SSM, S3, or Application Auto Scaling state.

No application secret values are requested or printed.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.parse
from pathlib import Path
from typing import Any, NoReturn

import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.release.check_staging_lifecycle_policy import render_policy_document

DEFAULT_MANIFEST = ROOT / "config/staging_lifecycle_iam_policy.yaml"
DEFAULT_POLICY_NAME = "AetherStagingLifecyclePolicy"
EXPECTED_ROLE = "AetherStagingLifecycle"


def fail(message: str) -> NoReturn:
    print(f"::error::{message}", file=sys.stderr)
    raise SystemExit(1)


def aws_json(*args: str) -> dict[str, Any]:
    result = subprocess.run(
        ["aws", *args, "--output", "json"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        fail(
            f"AWS lifecycle-policy inspection failed for {args[0]}: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    try:
        value = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        fail(f"AWS lifecycle-policy inspection returned invalid JSON: {exc}")
    if isinstance(value, str):
        value = json.loads(urllib.parse.unquote(value))
    if not isinstance(value, dict):
        fail("AWS lifecycle-policy inspection returned a non-object response")
    return value


def role_name_from_arn(role_arn: str) -> str:
    prefix = "arn:aws:iam::"
    if not role_arn.startswith(prefix) or ":role/" not in role_arn:
        fail("lifecycle role ARN must be a concrete IAM role ARN")
    name = role_arn.split(":role/", 1)[1]
    if "/" in name:
        fail("lifecycle role paths are not accepted")
    return name


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else [value]


def _normalized_statement(statement: dict[str, Any]) -> str:
    """Normalize AWS string/list encodings for semantic statement comparison."""
    normalized = {
        "Sid": statement.get("Sid"),
        "Effect": statement.get("Effect", "Allow"),
        "Action": sorted(str(item) for item in _as_list(statement.get("Action", []))),
        "Resource": sorted(str(item) for item in _as_list(statement.get("Resource", "*"))),
    }
    if statement.get("Condition"):
        normalized["Condition"] = statement["Condition"]
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"))


def compare_documents(expected: dict[str, Any], actual: dict[str, Any]) -> tuple[list[str], list[str]]:
    expected_statements = {
        _normalized_statement(statement)
        for statement in expected.get("Statement", [])
        if isinstance(statement, dict)
    }
    actual_statements = {
        _normalized_statement(statement)
        for statement in actual.get("Statement", [])
        if isinstance(statement, dict)
    }

    def sid_map(items: set[str]) -> list[str]:
        return sorted(json.loads(item).get("Sid") or "<missing-sid>" for item in items)

    return sid_map(expected_statements - actual_statements), sid_map(actual_statements - expected_statements)


def inline_policy_name_errors(policy_names: set[str], expected_name: str) -> list[str]:
    """Return drift errors for the lifecycle role's inline policy name set."""
    expected = {expected_name}
    errors: list[str] = []
    missing = sorted(expected - policy_names)
    unexpected = sorted(policy_names - expected)
    if missing:
        errors.append("missing inline policies: " + ", ".join(missing))
    if unexpected:
        errors.append("unexpected inline policies: " + ", ".join(unexpected))
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role-arn", required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--policy-name", default=DEFAULT_POLICY_NAME)
    args = parser.parse_args(argv)

    role_name = role_name_from_arn(args.role_arn)
    if role_name != EXPECTED_ROLE:
        fail(f"effective lifecycle policy check must target {EXPECTED_ROLE}, not {role_name}")

    document = yaml.safe_load(args.manifest.read_text(encoding="utf-8")) or {}
    if document.get("profile") != "staging" or document.get("role") != EXPECTED_ROLE:
        fail("staging lifecycle IAM manifest is not for AetherStagingLifecycle")
    account_id = args.role_arn.split(":", 4)[4].split(":", 1)[0]
    expected = render_policy_document(document, account_id)

    inline = aws_json("iam", "list-role-policies", "--role-name", role_name)
    policy_names = set(inline.get("PolicyNames", []))
    inline_errors = inline_policy_name_errors(policy_names, args.policy_name)
    if inline_errors:
        fail(f"{role_name} inline policy set drifted: " + "; ".join(inline_errors))

    attached = aws_json("iam", "list-attached-role-policies", "--role-name", role_name)
    attached_names = sorted(
        str(item.get("PolicyName"))
        for item in attached.get("AttachedPolicies", [])
        if isinstance(item, dict) and item.get("PolicyName")
    )
    if attached_names:
        fail(
            f"{role_name} has unexpected attached managed policies: "
            + ", ".join(attached_names)
        )

    live = aws_json(
        "iam",
        "get-role-policy",
        "--role-name",
        role_name,
        "--policy-name",
        args.policy_name,
    )
    actual = live.get("PolicyDocument", {})
    if isinstance(actual, str):
        actual = json.loads(urllib.parse.unquote(actual))
    if not isinstance(actual, dict):
        fail("live lifecycle policy document is not an object")

    missing, unexpected = compare_documents(expected, actual)
    if missing or unexpected:
        detail = []
        if missing:
            detail.append("missing statements: " + ", ".join(missing))
        if unexpected:
            detail.append("unexpected statements: " + ", ".join(unexpected))
        fail(f"{role_name} live inline policy drifted from the reviewed manifest (" + "; ".join(detail) + ")")

    print(f"Effective staging lifecycle policy matches the reviewed manifest ({len(expected['Statement'])} statements).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
