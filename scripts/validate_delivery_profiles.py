#!/usr/bin/env python3
"""Validate deployable frontend manifests and runtime fallback selection."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def validate_frontend(manifest: dict, policy: dict) -> list[str]:
    errors: list[str] = []
    profile = manifest.get("profile")
    profile_policy = policy["profiles"].get(profile)
    if not profile_policy:
        return [f"unknown deployment profile: {profile}"]
    for field in policy["required_frontend_fields"]:
        if not manifest.get(field):
            errors.append(f"missing frontend field: {field}")
    tokens = policy["placeholder_tokens"]
    for field, value in manifest.items():
        values = value if isinstance(value, list) else [value]
        for entry in values:
            if not isinstance(entry, str):
                continue
            lowered = entry.lower()
            if not profile_policy["allow_placeholder_endpoints"] and any(t in lowered for t in tokens):
                errors.append(f"{field} contains prohibited placeholder")
            if profile_policy["require_https"] and (field.endswith("url") or field.endswith("urls") or field == "identity_issuer"):
                if urlparse(entry).scheme not in {"https", "wss"}:
                    errors.append(f"{field} must use https or wss")
    return errors


def validate_fallbacks(profile: str, active: list[str], registry: dict) -> list[str]:
    if profile not in registry["profiles"]:
        return [f"unknown runtime profile: {profile}"]
    known = {item["fallback_id"]: item for item in registry["fallbacks"]}
    errors = [f"unknown fallback: {item}" for item in active if item not in known]
    errors += [f"fallback {item} is prohibited in {profile}" for item in active if item in known and profile not in known[item]["allowed_profiles"]]
    return errors


def validate_registry(registry: dict) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for item in registry.get("fallbacks", []):
        fallback_id = item.get("fallback_id", "")
        if not fallback_id or fallback_id in seen:
            errors.append(f"missing or duplicate fallback_id: {fallback_id}")
        seen.add(fallback_id)
        unknown = set(item.get("allowed_profiles", [])) - set(registry.get("profiles", []))
        if unknown:
            errors.append(f"fallback {fallback_id} has unknown profiles: {sorted(unknown)}")
        if item.get("readiness_effect") not in {"blocking", "degraded"}:
            errors.append(f"fallback {fallback_id} has invalid readiness_effect")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path, nargs="?")
    parser.add_argument(
        "--check-registry",
        action="store_true",
        help="validate committed profile/fallback policy without a deployment manifest",
    )
    parser.add_argument("--active-fallback", action="append", default=[])
    args = parser.parse_args()
    profile_policy = load_yaml(ROOT / "config/deployment_profile_compatibility.yaml")
    fallback_registry = load_yaml(ROOT / "config/runtime_fallbacks.yaml")
    errors = validate_registry(fallback_registry)
    manifest: dict = {}
    if args.manifest:
        manifest = json.loads(args.manifest.read_text())
        errors.extend(validate_frontend(manifest, profile_policy))
        errors.extend(validate_fallbacks(manifest.get("profile", ""), args.active_fallback, fallback_registry))
    elif not args.check_registry:
        parser.error("manifest is required unless --check-registry is used")
    result = {"status": "FAILED" if errors else "PASS", "profile": manifest.get("profile"), "errors": errors}
    print(json.dumps(result, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
