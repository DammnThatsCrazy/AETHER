#!/usr/bin/env python3
"""Validate the narrowly scoped Terraform backend access manifest."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml


EXPECTED = {
    "s3:ListBucket",
    "s3:GetObject",
    "s3:PutObject",
    "s3:DeleteObject",
    "s3:GetBucketVersioning",
    "s3:GetBucketLocation",
    "dynamodb:GetItem",
    "dynamodb:PutItem",
    "dynamodb:DeleteItem",
}

CANONICAL_BUCKET = "aether-terraform-state"
CANONICAL_LOCK_TABLE = "aether-terraform-locks"


def _backend_values(terraform_root: Path) -> tuple[set[str], set[str]]:
    """Read backend names from the checked-in environment sources."""
    buckets: set[str] = set()
    tables: set[str] = set()
    for path in sorted((terraform_root / "environments").glob("*/main.tf")):
        raw = path.read_text(encoding="utf-8")
        backend = re.search(r'backend\s+"s3"\s*\{(?P<body>.*?)\n\s*\}', raw, re.DOTALL)
        if backend is None:
            continue
        body = backend.group("body")
        buckets.update(re.findall(r'(?m)^\s*bucket\s*=\s*"([^"]+)"', body))
        tables.update(re.findall(r'(?m)^\s*dynamodb_table\s*=\s*"([^"]+)"', body))
    return buckets, tables


def validate(path: Path, terraform_root: Path | None = None) -> list[str]:
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return [f"cannot read state access policy: {exc}"]
    errors: list[str] = []
    if not isinstance(doc, dict) or doc.get("scope") != "terraform-state-backend":
        return ["state access policy must declare terraform-state-backend scope"]
    if doc.get("state_bucket") != CANONICAL_BUCKET:
        errors.append(f"state bucket must be {CANONICAL_BUCKET}")
    if doc.get("state_lock_table") != CANONICAL_LOCK_TABLE:
        errors.append(f"state lock table must be {CANONICAL_LOCK_TABLE}")
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
    if f"arn:aws:dynamodb:us-east-1:${{account_id}}:table/{CANONICAL_LOCK_TABLE}" not in raw:
        errors.append(f"state lock access is not restricted to {CANONICAL_LOCK_TABLE}")
    list_statement = next(
        (
            statement
            for statement in doc.get("statements", [])
            if isinstance(statement, dict) and "s3:ListBucket" in (statement.get("actions") or [])
        ),
        None,
    )
    list_condition = (list_statement or {}).get("conditions") or {}
    string_like = list_condition.get("StringLike") if isinstance(list_condition, dict) else None
    if not isinstance(string_like, dict) or string_like.get("s3:prefix") != ["profiles/*"]:
        errors.append("s3:ListBucket must use StringLike s3:prefix=profiles/*")
    if terraform_root is not None:
        buckets, tables = _backend_values(terraform_root)
        if buckets != {CANONICAL_BUCKET}:
            errors.append(f"backend bucket sources differ from {CANONICAL_BUCKET}: {sorted(buckets)}")
        if tables != {CANONICAL_LOCK_TABLE}:
            errors.append(f"backend lock-table sources differ from {CANONICAL_LOCK_TABLE}: {sorted(tables)}")
    if "resource: '*'" in raw or "actions:\n      - '*'" in raw:
        errors.append("state access policy must not contain wildcard resource or action grants")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--terraform-root", type=Path)
    args = parser.parse_args()
    errors = validate(args.manifest, args.terraform_root)
    if errors:
        for error in errors:
            print(f"::error::{error}")
        return 1
    print("Terraform state access policy valid: 9 explicit least-privilege actions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
