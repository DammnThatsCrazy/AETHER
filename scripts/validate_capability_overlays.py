#!/usr/bin/env python3
"""Validate the capability overlay registry.

Profiles describe environments; flags describe capabilities. This keeps a
capability from becoming a deployment profile: overlay names must start with
``enable-``, must not equal a deployment profile name, and every bound flag must
exist in the backend settings.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config/capability_overlays.yaml"
PROFILES = ROOT / "config/deployment_profiles.yaml"
CLASSES = {"core", "beta", "experimental", "internal"}


def validate(
    registry: Path = REGISTRY, profiles: Path = PROFILES, root: Path = ROOT
) -> list[str]:
    errors: list[str] = []
    try:
        raw: Any = yaml.safe_load(registry.read_text(encoding="utf-8"))
        profile_names = set((yaml.safe_load(profiles.read_text(encoding="utf-8")) or {}).get("profiles", {}))
    except (OSError, yaml.YAMLError) as exc:
        return [f"cannot load capability overlays or profiles: {exc}"]
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        return ["schema_version must be 1"]
    overlays = raw.get("overlays")
    if not isinstance(overlays, dict) or not overlays:
        return ["overlays must be a non-empty mapping"]
    try:
        settings_text = (root / str(raw.get("flags_source", ""))).read_text(encoding="utf-8")
    except OSError:
        return [f"flags_source {raw.get('flags_source')!r} is not readable"]

    for name, spec in overlays.items():
        if not str(name).startswith("enable-"):
            errors.append(f"{name}: overlay names must start with enable-")
        if name in profile_names:
            errors.append(f"{name}: a capability overlay must not be a deployment profile")
        if not isinstance(spec, dict):
            errors.append(f"{name}: entry must be a mapping")
            continue
        if spec.get("class") not in CLASSES:
            errors.append(f"{name}: class must be one of {sorted(CLASSES)}")
        flags = spec.get("flags")
        if not isinstance(flags, list):
            errors.append(f"{name}: flags must be a list")
            continue
        status = spec.get("status")
        if status == "bound" and not flags:
            errors.append(f"{name}: a bound overlay must list at least one flag")
        elif status == "unbound":
            if flags:
                errors.append(f"{name}: an unbound overlay must not list flags")
            if not str(spec.get("note") or "").strip():
                errors.append(f"{name}: an unbound overlay needs a note saying why")
        elif status not in {"bound", "unbound"}:
            errors.append(f"{name}: status must be bound or unbound")
        for flag in flags:
            if flag not in settings_text:
                errors.append(f"{name}: flag {flag} does not exist in {raw['flags_source']}")
    return errors


def main() -> int:
    errors = validate()
    if errors:
        print("capability overlays: FAIL")
        for error in errors:
            print(f"  - {error}")
        return 1
    raw = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    bound = sum(1 for s in raw["overlays"].values() if s["status"] == "bound")
    print(f"capability overlays: {len(raw['overlays'])} OK ({bound} bound, {len(raw['overlays']) - bound} unbound)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
