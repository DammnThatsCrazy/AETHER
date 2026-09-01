#!/usr/bin/env python3
"""Create or validate the versioned ChangePlan carried by a change."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
REQUIRED = {
    "schema_version", "change_id", "title", "owner", "domains", "paths",
    "contracts", "surfaces", "risk_level", "risk_classes", "migrations",
    "security_sensitive", "deployment_impact", "required_checks",
    "deferred_checks", "rollback_notes",
}


def validate(data: dict) -> list[str]:
    errors = []
    missing = sorted(REQUIRED - set(data))
    unknown = sorted(set(data) - REQUIRED)
    if missing:
        errors.append("missing fields: " + ", ".join(missing))
    if unknown:
        errors.append("unknown fields: " + ", ".join(unknown))
    if data.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if data.get("risk_level") not in {"low", "medium", "high", "critical"}:
        errors.append("risk_level must be low, medium, high, or critical")
    for key in ("change_id", "title", "owner", "rollback_notes"):
        if not isinstance(data.get(key), str) or not data.get(key, "").strip():
            errors.append(f"{key} must be a non-empty string")
    for key in ("domains", "paths", "required_checks"):
        if not isinstance(data.get(key), list) or not data.get(key):
            errors.append(f"{key} must be a non-empty list")
    for key in ("migrations", "security_sensitive", "deployment_impact"):
        if not isinstance(data.get(key), bool):
            errors.append(f"{key} must be boolean")
    contracts = data.get("contracts")
    if not isinstance(contracts, dict) or set(contracts) != {"changed", "consumed"}:
        errors.append("contracts must contain exactly changed and consumed arrays")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", type=Path)
    parser.add_argument("--create", metavar="CHANGE_ID")
    parser.add_argument("--title")
    parser.add_argument("--owner")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.create:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", args.create):
            parser.error("CHANGE_ID must be lowercase kebab-case")
        if not args.title or not args.owner:
            parser.error("--create requires --title and --owner")
        from scripts.check_router import changed_files, route
        routed = route(changed_files("HEAD", []))
        data = {
            "schema_version": 1, "change_id": args.create, "title": args.title,
            "owner": args.owner, "domains": routed["affected_domains"] or ["delivery"],
            "paths": routed["changed_files"] or ["CHANGE_PLAN_ONLY"],
            "contracts": {"changed": [], "consumed": []}, "surfaces": [],
            "risk_level": "medium", "risk_classes": [], "migrations": False,
            "security_sensitive": False, "deployment_impact": False,
            "required_checks": [item["check_id"] for item in routed["checks"]],
            "deferred_checks": [], "rollback_notes": "Revert the change commit.",
        }
        output = args.output or ROOT / "evidence" / "local" / f"{args.create}.change-plan.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        try:
            print(output.relative_to(ROOT))
        except ValueError:
            print(output)
        return 0
    if not args.path:
        parser.error("provide a ChangePlan path or --create")
    try:
        data = json.loads(args.path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"BLOCKED: cannot read ChangePlan: {exc}", file=sys.stderr)
        return 2
    errors = validate(data)
    if errors:
        print("INVALID ChangePlan:\n- " + "\n- ".join(errors), file=sys.stderr)
        return 1
    print(f"VALID ChangePlan: {data['change_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
