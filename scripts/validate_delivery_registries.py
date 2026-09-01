#!/usr/bin/env python3
"""Fail-closed static validation for fallback and golden-journey registries."""
from __future__ import annotations

import json
import shlex
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_JOURNEYS = {"tenant_activation", "first_graph", "first_insight", "investigation", "recovery"}
DEPLOYABLE_PROFILES = {"staging", "production-lean", "production-scale", "enterprise-isolated"}


def validate_fallback_registry(registry: dict, root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    ids: set[str] = set()
    for item in registry.get("fallbacks", []):
        fallback_id = item.get("fallback_id")
        if not fallback_id or fallback_id in ids:
            errors.append(f"fallback_id is missing or duplicated: {fallback_id!r}")
        ids.add(fallback_id)
        if not item.get("owner") or not item.get("surfaces"):
            errors.append(f"fallback {fallback_id} requires owner and surfaces")
        allowed = set(item.get("allowed_profiles", []))
        prohibited = allowed & DEPLOYABLE_PROFILES
        if prohibited:
            errors.append(f"blocking fallback {fallback_id} is allowed in deployable profiles: {sorted(prohibited)}")
        paths = item.get("implementation_paths", [])
        if not paths:
            errors.append(f"fallback {fallback_id} has no implementation_paths")
        for path in paths:
            if Path(path).is_absolute() or not (root / path).is_file():
                errors.append(f"fallback {fallback_id} implementation does not exist: {path}")
    return errors


def validate_journey_registry(registry: dict, root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    journeys = registry.get("journeys", {})
    missing = REQUIRED_JOURNEYS - set(journeys)
    extra = set(journeys) - REQUIRED_JOURNEYS
    if missing or extra:
        errors.append(f"golden journeys must be exactly canonical set; missing={sorted(missing)}, extra={sorted(extra)}")
    required = set(registry.get("required_assertion_classes", []))
    for journey_id, item in journeys.items():
        if not item.get("owner"):
            errors.append(f"journey {journey_id} has no owner")
        absent = required - set(item.get("assertions", []))
        if absent:
            errors.append(f"journey {journey_id} lacks assertion classes: {sorted(absent)}")
        status = item.get("implementation_status")
        command = item.get("command", "")
        if status == "BLOCKED":
            if command:
                errors.append(f"journey {journey_id} cannot declare a command while BLOCKED")
            if not item.get("blocker"):
                errors.append(f"journey {journey_id} BLOCKED status requires a blocker")
            continue
        if status != "IMPLEMENTED":
            errors.append(f"journey {journey_id} status must be BLOCKED or IMPLEMENTED")
        try:
            argv = shlex.split(command)
        except ValueError:
            argv = []
        if len(argv) != 3 or argv[:2] != ["python", "scripts/run_pytest_files.py"]:
            errors.append(f"journey {journey_id} command must use the isolated pytest runner with one path")
        elif Path(argv[2]).is_absolute() or not (root / argv[2]).is_file():
            errors.append(f"journey {journey_id} executable test path does not exist: {argv[2]}")
    return errors


def main() -> int:
    fallback = yaml.safe_load((ROOT / "config/runtime_fallbacks.yaml").read_text())
    journeys = yaml.safe_load((ROOT / "config/golden_journeys.yaml").read_text())
    errors = validate_fallback_registry(fallback) + validate_journey_registry(journeys)
    print(json.dumps({"status": "FAILED" if errors else "PASS", "errors": errors}, indent=2))
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
