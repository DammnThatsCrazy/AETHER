#!/usr/bin/env python3
"""Validate the transitional one-owner map for GitHub delivery workflows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config/delivery_workflow_authority.yaml"
REQUIRED_AUTHORITIES = {
    "verification", "candidate", "environment", "infrastructure",
    "promotion", "regression", "ephemeral_cleanup",
}


def _load(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a mapping")
    return value


def _workflow_triggers(workflow: dict[str, Any]) -> set[str]:
    value = workflow.get("on", workflow.get(True))
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return {str(item) for item in value}
    if isinstance(value, dict):
        return {str(item) for item in value}
    return set()


def validate(config_path: Path = CONFIG, root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    try:
        config = _load(config_path)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        return [f"cannot load workflow authority registry: {exc}"]
    if config.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if config.get("operator_surface") != "github_actions":
        errors.append("operator_surface must be github_actions")
    if config.get("kyber_mutation_controls") is not False:
        errors.append("kyber_mutation_controls must be false")
    authorities = config.get("authorities")
    if not isinstance(authorities, list) or not authorities:
        return errors + ["authorities must be a non-empty list"]
    seen: set[str] = set()
    for item in authorities:
        if not isinstance(item, dict):
            errors.append("each authority must be a mapping")
            continue
        authority_id = item.get("id")
        owner = item.get("owner")
        workflows = item.get("workflows")
        if not isinstance(authority_id, str) or not authority_id.strip():
            errors.append("each authority requires a non-empty id")
            continue
        if authority_id in seen:
            errors.append(f"duplicate authority: {authority_id}")
        seen.add(authority_id)
        if not isinstance(owner, str) or not owner.strip():
            errors.append(f"authority {authority_id} requires an owner")
        if not isinstance(workflows, list) or not workflows:
            errors.append(f"authority {authority_id} requires workflows")
            continue
        for raw_path in workflows:
            if not isinstance(raw_path, str) or not raw_path.startswith(".github/workflows/"):
                errors.append(f"authority {authority_id} has non-GitHub workflow path: {raw_path!r}")
                continue
            path = root / raw_path
            if not path.is_file():
                errors.append(f"authority {authority_id} workflow is missing: {raw_path}")
                continue
            try:
                workflow = _load(path)
            except (OSError, ValueError, yaml.YAMLError) as exc:
                errors.append(f"{raw_path}: cannot parse workflow: {exc}")
                continue
            if not _workflow_triggers(workflow):
                errors.append(f"{raw_path}: workflow must declare a trigger")
    missing = sorted(REQUIRED_AUTHORITIES - seen)
    extra = sorted(seen - REQUIRED_AUTHORITIES)
    if missing:
        errors.append("missing required authorities: " + ", ".join(missing))
    if extra:
        errors.append("unknown authorities: " + ", ".join(extra))
    return errors


def main() -> int:
    errors = validate()
    print(json.dumps({"schema_version": 1, "status": "FAILED" if errors else "PASS", "errors": errors}, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
