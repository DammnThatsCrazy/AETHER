#!/usr/bin/env python3
"""Validate canonical release evidence and render the Kyber readiness projection."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "contracts/delivery/release-evidence-bundle.schema.json"
JOURNEYS = ROOT / "config/golden_journeys.yaml"
BLOCKING = {"BLOCKED", "FAILED"}
REQUIRED_JOURNEYS = {"tenant_activation", "first_graph", "first_insight", "investigation", "recovery"}


def validate_bundle(bundle: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    missing = set(schema["required"]) - set(bundle)
    if missing:
        errors.append("missing required properties: " + ", ".join(sorted(missing)))
    unknown = set(bundle) - set(schema["properties"])
    if unknown:
        errors.append("unknown properties: " + ", ".join(sorted(unknown)))
    if bundle.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", str(bundle.get("artifact_digest", ""))):
        errors.append("artifact_digest must be an immutable sha256 digest")
    if bundle.get("status") not in {"READY", "PASS_WITH_DEGRADATION", "BLOCKED", "FAILED"}:
        errors.append("status is not an allowed disposition")
    checks = bundle.get("checks", {})
    values = set(checks.values()) if isinstance(checks, dict) else set()
    required_checks = set(schema["properties"]["checks"]["required"])
    if not isinstance(checks, dict):
        errors.append("checks must be an object")
    elif required_checks - set(checks):
        errors.append("missing required checks: " + ", ".join(sorted(required_checks - set(checks))))
    allowed_check_results = {"PASS", "PASS_WITH_DEGRADATION", "BLOCKED", "FAILED", "NOT_APPLICABLE"}
    if values - allowed_check_results:
        errors.append("checks contain an invalid result")
    status = bundle.get("status")
    if status == "READY" and values & BLOCKING:
        errors.append("READY is forbidden while a check is BLOCKED or FAILED")
    if status == "READY" and "PASS_WITH_DEGRADATION" in values:
        errors.append("READY is forbidden when a check passed with degradation")
    if status == "PASS_WITH_DEGRADATION" and not bundle.get("known_degradations"):
        errors.append("PASS_WITH_DEGRADATION requires at least one known degradation")
    if status == "BLOCKED" and "BLOCKED" not in values:
        errors.append("BLOCKED disposition requires a BLOCKED check")
    if status == "FAILED" and "FAILED" not in values:
        errors.append("FAILED disposition requires a FAILED check")
    return sorted(set(errors))


def validate_journey_registry(path: Path = JOURNEYS) -> list[str]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    journeys = doc.get("journeys", {})
    errors = []
    missing = REQUIRED_JOURNEYS - set(journeys)
    if missing:
        errors.append("missing golden journeys: " + ", ".join(sorted(missing)))
    for name, value in journeys.items():
        if not value.get("owner"):
            errors.append(f"{name}: owner is required")
        if not value.get("assertions"):
            errors.append(f"{name}: assertions are required")
    return errors


def kyber_projection(bundle: dict[str, Any]) -> dict[str, Any]:
    """Return presentation-only data; Kyber must not recompute disposition."""
    checks = bundle.get("checks", {})
    blockers = [{"check": k, "status": v} for k, v in checks.items() if v in BLOCKING]
    return {
        "release_candidate_id": bundle.get("release_candidate_id"),
        "commit_sha": bundle.get("commit_sha"),
        "artifact_digest": bundle.get("artifact_digest"),
        "deployment_profile": bundle.get("deployment_profile"),
        "disposition": bundle.get("status"),
        "checks": checks,
        "blockers": blockers,
        "known_degradations": bundle.get("known_degradations", []),
        "evidence": bundle.get("evidence", []),
        "action": "repair blockers and publish a new evidence bundle" if blockers else "eligible for profile-specific approval",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path, nargs="?")
    parser.add_argument("--check-registry", action="store_true", help="validate the golden-journey registry only")
    parser.add_argument("--kyber-output", type=Path)
    args = parser.parse_args()
    errors = validate_journey_registry()
    if args.bundle is None:
        if not args.check_registry:
            parser.error("bundle is required unless --check-registry is used")
        if errors:
            print(json.dumps({"status": "FAILED", "errors": errors}, indent=2))
            return 1
        print(json.dumps({"status": "PASS", "registry": str(JOURNEYS.relative_to(ROOT))}))
        return 0
    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    errors += validate_bundle(bundle)
    if errors:
        print(json.dumps({"status": "FAILED", "errors": errors}, indent=2))
        return 1
    if args.kyber_output:
        args.kyber_output.parent.mkdir(parents=True, exist_ok=True)
        args.kyber_output.write_text(json.dumps(kyber_projection(bundle), indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "disposition": bundle["status"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
