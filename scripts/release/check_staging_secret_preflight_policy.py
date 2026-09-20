#!/usr/bin/env python3
"""Validate the narrow IAM contract used to inspect staging secret payloads."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml


EXPECTED_ACTION = "secretsmanager:GetSecretValue"
EXPECTED_RESOURCE_SUFFIX = ":secret:aether/*"
REQUIRED_FORBIDDEN = {
    "secretsmanager:PutSecretValue",
    "secretsmanager:UpdateSecret",
    "secretsmanager:DeleteSecret",
    "secretsmanager:RotateSecret",
    "kms:*",
    "iam:*",
}


def policy_errors(path: Path) -> list[str]:
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    errors: list[str] = []
    if document.get("version") != 1:
        errors.append("policy version must be 1")
    if document.get("profile") != "staging":
        errors.append("policy profile must be staging")
    if document.get("role") != "AetherStagingSecretPreflight":
        errors.append("policy role must be AetherStagingSecretPreflight")
    statements = document.get("statements")
    if not isinstance(statements, list) or len(statements) != 1:
        errors.append("policy must contain exactly one statement")
    else:
        statement = statements[0]
        actions = statement.get("actions") or []
        if actions != [EXPECTED_ACTION]:
            errors.append(f"policy actions must be exactly [{EXPECTED_ACTION!r}]")
        resource = statement.get("resource")
        if not isinstance(resource, str) or not resource.endswith(EXPECTED_RESOURCE_SUFFIX):
            errors.append("policy resource must be limited to the staging aether/* secret prefix")
        if statement.get("scope") != "staging-name-prefix":
            errors.append("policy statement must declare staging-name-prefix scope")
    forbidden = set(document.get("forbidden_actions") or [])
    missing_forbidden = sorted(REQUIRED_FORBIDDEN - forbidden)
    if missing_forbidden:
        errors.append("policy forbidden_actions is missing: " + ", ".join(missing_forbidden))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("config/staging_secret_preflight_iam_policy.yaml"),
    )
    args = parser.parse_args()
    errors = policy_errors(args.manifest)
    if errors:
        for error in errors:
            print(f"::error::{error}")
        return 1
    print("staging secret preflight IAM contract valid: one read-only aether/* payload permission")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
