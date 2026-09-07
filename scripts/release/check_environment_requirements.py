#!/usr/bin/env python3
"""Validate the profile capability requirement registry without cloud access."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
PROFILES = ROOT / "config" / "deployment_profiles.yaml"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.release.resolve_environment import load_requirements  # noqa: E402


def validate(requirements: dict[str, Any] | None = None, profiles: dict[str, Any] | None = None) -> list[str]:
    """Return structural errors; this function never discovers or mutates AWS."""
    requirements = requirements or load_requirements()
    profiles = profiles or (yaml.safe_load(PROFILES.read_text(encoding="utf-8")) or {})
    errors: list[str] = []
    expected = set((profiles.get("profiles") or {}).keys())
    actual = set((requirements.get("profiles") or {}).keys())
    if actual != expected:
        errors.append(f"profile coverage mismatch: missing={sorted(expected - actual)}, extra={sorted(actual - expected)}")
    dependencies = requirements.get("dependencies", {})
    for profile, spec in (requirements.get("profiles") or {}).items():
        if not isinstance(spec, dict):
            errors.append(f"{profile}: requirement must be a mapping")
            continue
        required = spec.get("required", [])
        optional = spec.get("optional", [])
        degradable = spec.get("degradable", [])
        for field, values in (("required", required), ("optional", optional), ("degradable", degradable)):
            if not isinstance(values, list) or len(values) != len(set(values)):
                errors.append(f"{profile}.{field}: must be a unique list")
        if isinstance(required, list) and isinstance(degradable, list) and not set(degradable) <= set(required):
            errors.append(f"{profile}.degradable must be a subset of required")
        overlap = set(required or []) & set(optional or []) if isinstance(required, list) and isinstance(optional, list) else set()
        if overlap:
            errors.append(f"{profile}: capability cannot be both required and optional: {sorted(overlap)}")
        if spec.get("promotion_equivalence") and spec["promotion_equivalence"] not in expected:
            errors.append(f"{profile}: promotion_equivalence references unknown profile")
    known = set().union(*(
        set(spec.get("required", [])) | set(spec.get("optional", []))
        for spec in (requirements.get("profiles") or {}).values()
        if isinstance(spec, dict)
    ))
    for capability, deps in dependencies.items():
        if capability not in known:
            errors.append(f"dependency target {capability!r} is not registered")
        if not isinstance(deps, list):
            errors.append(f"dependencies[{capability!r}] must be a list")
            continue
        for dependency in deps:
            if dependency not in known:
                errors.append(f"dependencies[{capability!r}] references unknown {dependency!r}")
    return sorted(set(errors))


def main() -> int:
    try:
        errors = validate()
    except (OSError, ValueError, TypeError, yaml.YAMLError) as exc:
        errors = [str(exc)]
    if errors:
        print(json.dumps({"status": "FAILED", "errors": errors}, indent=2))
        return 1
    requirements = load_requirements()
    print(json.dumps({
        "status": "PASS",
        "profiles": len(requirements.get("profiles", {})),
        "dependencies": len(requirements.get("dependencies", {})),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
