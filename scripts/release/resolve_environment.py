#!/usr/bin/env python3
"""Resolve a canonical deployment profile against observed capabilities.

The resolver is deliberately pure with respect to infrastructure: it consumes
an operator/workflow capability record and emits a typed decision before any
plan or apply.  Missing capabilities are ``UNKNOWN`` rather than healthy.
Dependencies are closed transitively, and only the profile's explicit
``degradable`` set may produce ``PASS_WITH_DEGRADATION``.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS = ROOT / "config" / "environment_requirements.yaml"
STATUSES = frozenset({"PASS", "UNAVAILABLE", "BLOCKED", "UNKNOWN"})


def load_requirements(path: Path = REQUIREMENTS) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if data.get("schema_version") != 1:
        raise ValueError("environment requirements schema_version must be 1")
    profiles = data.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise ValueError("environment requirements must declare profiles")
    dependencies = data.get("dependencies", {})
    if not isinstance(dependencies, dict):
        raise ValueError("environment dependencies must be a mapping")
    known = set().union(*(set(v.get("required", [])) | set(v.get("optional", [])) for v in profiles.values()))
    for capability, deps in dependencies.items():
        if capability not in known:
            raise ValueError(f"dependency target {capability!r} is not registered")
        if not isinstance(deps, list) or any(dep not in known for dep in deps):
            raise ValueError(f"dependencies for {capability!r} reference unknown capability")
    return data


def _dependency_status(capability: str, observed: dict[str, str], dependencies: dict[str, list[str]], seen: set[str] | None = None) -> tuple[str, str | None]:
    seen = seen or set()
    if capability in seen:
        raise ValueError(f"cyclic environment dependency at {capability}")
    seen.add(capability)
    status = observed.get(capability, "UNKNOWN")
    if status != "PASS":
        return status, None
    for dependency in dependencies.get(capability, []):
        dep_status, _ = _dependency_status(dependency, observed, dependencies, seen.copy())
        if dep_status != "PASS":
            return "UNAVAILABLE", f"requires capability {dependency} ({dep_status})"
    return "PASS", None


def resolve(profile: str, observed: dict[str, str], requirements: dict[str, Any] | None = None) -> dict[str, Any]:
    requirements = requirements or load_requirements()
    profiles = requirements["profiles"]
    if profile not in profiles:
        raise ValueError(f"unknown deployment profile: {profile}")
    unknown_statuses = {status for status in observed.values() if status not in STATUSES}
    if unknown_statuses:
        raise ValueError(f"unknown capability status: {sorted(unknown_statuses)}")
    spec = profiles[profile]
    required = set(spec.get("required", []))
    optional = set(spec.get("optional", []))
    degradable = set(spec.get("degradable", []))
    if not degradable <= required:
        raise ValueError(f"degradable capabilities must be required: {sorted(degradable - required)}")
    dependencies = requirements.get("dependencies", {})
    all_capabilities = sorted(required | optional | set(observed))
    capabilities: dict[str, dict[str, Any]] = {}
    omitted: list[dict[str, str]] = []
    blockers: list[str] = []
    for capability in all_capabilities:
        status, dependency_reason = _dependency_status(capability, observed, dependencies)
        entry: dict[str, Any] = {"status": status, "required": capability in required}
        if dependency_reason:
            entry["reason"] = dependency_reason
        capabilities[capability] = entry
        if status == "PASS":
            continue
        if capability in degradable:
            omitted.append({"capability": capability, "reason": dependency_reason or f"observed capability status is {status}", "impact": "DEGRADED"})
        elif capability in required:
            blockers.append(f"{capability}: {dependency_reason or status}")
        elif capability in optional:
            omitted.append({"capability": capability, "reason": dependency_reason or f"observed capability status is {status}", "impact": "OPTIONAL"})
    if blockers:
        disposition = "BLOCKED_EXTERNAL"
        resolved_profile = profile
    elif omitted and any(item["impact"] == "DEGRADED" for item in omitted):
        disposition = "PASS_WITH_DEGRADATION"
        resolved_profile = f"{profile}-degraded"
    else:
        disposition = "PASS"
        resolved_profile = profile
    promotion_target = spec.get("promotion_equivalence")
    production_equivalent = bool(promotion_target and disposition == "PASS")
    return {
        "schema_version": 1,
        "requested_profile": profile,
        "resolved_profile": resolved_profile,
        "capabilities": capabilities,
        "omitted": omitted,
        "promotion_equivalence": promotion_target,
        "production_equivalent": production_equivalent,
        "disposition": disposition,
        "blockers": blockers,
    }


def _observed(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        name, separator, status = value.partition("=")
        if not separator or not name or not status or name in result:
            raise ValueError(f"capability must be NAME=STATUS and unique: {value!r}")
        result[name] = status.upper()
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--capability", action="append", default=[], metavar="NAME=STATUS")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = resolve(args.profile, _observed(args.capability))
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(json.dumps({"schema_version": 1, "status": "BLOCKED_EXTERNAL", "error": str(exc)}, indent=2))
        return 2
    rendered = json.dumps(result, indent=2) + "\n"
    print(rendered, end="")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    return 0 if result["disposition"] != "BLOCKED_EXTERNAL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
