#!/usr/bin/env python3
"""Validate the narrow IAM contract used to inspect staging secret payloads."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml


EXPECTED_SECRET_ACTION = "secretsmanager:GetSecretValue"
EXPECTED_SECRET_RESOURCE_SUFFIX = ":secret:aether/*"
EXPECTED_KMS_ACTION = "kms:Decrypt"
EXPECTED_KMS_RESOURCE_SUFFIX = ":key/*"
EXPECTED_KMS_SCOPE = "staging-secrets-kms-key"
EXPECTED_KMS_CONDITIONS = {
    "StringEquals": {"aws:ResourceTag/Environment": "staging"},
    "ForAnyValue:StringLike": {"kms:ResourceAliases": ["alias/aether-staging-secrets"]},
}
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
    if not isinstance(statements, list) or len(statements) != 2:
        errors.append("policy must contain exactly two statements")
    else:
        by_sid = {statement.get("sid"): statement for statement in statements}
        secret_statement = by_sid.get("ReadStagingApplicationSecretPayloads")
        kms_statement = by_sid.get("DecryptStagingApplicationSecrets")
        if not isinstance(secret_statement, dict):
            errors.append("policy must declare ReadStagingApplicationSecretPayloads")
        else:
            actions = secret_statement.get("actions") or []
            if actions != [EXPECTED_SECRET_ACTION]:
                errors.append(
                    f"secret payload actions must be exactly [{EXPECTED_SECRET_ACTION!r}]"
                )
            resource = secret_statement.get("resource")
            if not isinstance(resource, str) or not resource.endswith(EXPECTED_SECRET_RESOURCE_SUFFIX):
                errors.append("secret payload resource must be limited to the staging aether/* prefix")
            if secret_statement.get("scope") != "staging-name-prefix":
                errors.append("secret payload statement must declare staging-name-prefix scope")
        if not isinstance(kms_statement, dict):
            errors.append("policy must declare DecryptStagingApplicationSecrets")
        else:
            if kms_statement.get("actions") != [EXPECTED_KMS_ACTION]:
                errors.append(f"KMS actions must be exactly [{EXPECTED_KMS_ACTION!r}]")
            resource = kms_statement.get("resource")
            if not isinstance(resource, str) or not resource.endswith(EXPECTED_KMS_RESOURCE_SUFFIX):
                errors.append("KMS resource must be limited to staging customer-managed keys")
            if kms_statement.get("scope") != EXPECTED_KMS_SCOPE:
                errors.append(f"KMS statement must declare {EXPECTED_KMS_SCOPE} scope")
            if kms_statement.get("conditions") != EXPECTED_KMS_CONDITIONS:
                errors.append("KMS decrypt must be restricted to the staging secrets key alias and tag")
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
    print("staging secret preflight IAM contract valid: payload read plus scoped staging-key decrypt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
