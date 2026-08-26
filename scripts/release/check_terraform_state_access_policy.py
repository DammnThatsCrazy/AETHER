#!/usr/bin/env python3
"""Validate the narrowly scoped Terraform backend access manifest."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml


EXPECTED = {
    "s3:GetObject",
    "s3:PutObject",
    "s3:DeleteObject",
    "s3:GetBucketVersioning",
    "s3:GetBucketLocation",
    "dynamodb:GetItem",
    "dynamodb:PutItem",
    "dynamodb:DeleteItem",
}


def validate(path: Path) -> list[str]:
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return [f"cannot read state access policy: {exc}"]
    errors: list[str] = []
    if not isinstance(doc, dict) or doc.get("scope") != "terraform-state-backend":
        return ["state access policy must declare terraform-state-backend scope"]
    seen: set[str] = set()
    for statement in doc.get("statements", []):
        if not isinstance(statement, dict):
            errors.append("state access statements must be mappings")
            continue
        actions = statement.get("actions", [])
        if not isinstance(actions, list):
            errors.append(f"{statement.get('sid', '<unknown>')} actions must be a list")
            continue
        seen.update(action for action in actions if isinstance(action, str))
    if seen != EXPECTED:
        errors.append(f"state access actions differ from reviewed set: {sorted(seen ^ EXPECTED)}")
    raw = path.read_text(encoding="utf-8")
    if "arn:aws:s3:::aether-terraform-state/profiles/*" not in raw:
        errors.append("profile state object access is not restricted to profiles/*")
    if "arn:aws:dynamodb:us-east-1:${account_id}:table/AETHER-TerraformLock" not in raw:
        errors.append("state lock access is not restricted to AETHER-TerraformLock")
    if "resource: '*'" in raw or "actions:\n      - '*'" in raw:
        errors.append("state access policy must not contain wildcard resource or action grants")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    errors = validate(args.manifest)
    if errors:
        for error in errors:
            print(f"::error::{error}")
        return 1
    print("Terraform state access policy valid: 8 explicit least-privilege actions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
