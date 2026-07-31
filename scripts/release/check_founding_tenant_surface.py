#!/usr/bin/env python3
"""Fail-closed parity checks for the founding-tenant release surface."""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
STAGES = (
    "disabled", "integration", "staging", "internal_canary",
    "founding_tenant_canary", "founding_tenant_enabled",
    "general_availability_candidate",
)


def _literal_assignment(path: Path, name: str):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            target = node.targets[0] if isinstance(node, ast.Assign) else node.target
            if isinstance(target, ast.Name) and target.id == name:
                value = node.value
                if isinstance(value, ast.Call) and value.args:
                    value = value.args[0]
                return ast.literal_eval(value)
    raise ValueError(f"{name} not found in {path}")


def _makefile_targets() -> set[str]:
    """Every target name defined in the root Makefile (`name:` at column 0)."""
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    return set(re.findall(r"(?m)^([A-Za-z0-9][A-Za-z0-9_.\-]*)\s*:(?!=)", text))


def validate() -> list[str]:
    errors: list[str] = []
    manifest = yaml.safe_load((ROOT / "config/founding_tenant_release.yaml").read_text())
    profiles = yaml.safe_load((ROOT / "config/deployment_profiles.yaml").read_text())
    route_registry = yaml.safe_load((ROOT / "config/route_registry.yaml").read_text())
    if manifest["profile"] not in profiles["profiles"]:
        errors.append("FT_SURFACE_UNKNOWN_PROFILE")
    known = set(route_registry.get("known_prefixes") or [])
    for prefix in manifest["release_surface"]["enabled_route_prefixes"]:
        if prefix not in known:
            errors.append(f"FT_SURFACE_UNKNOWN_ROUTE:{prefix}")
    runtime = ROOT / "Backend Architecture/aether-backend/services/runtime"
    roles = set(_literal_assignment(runtime / "roles.py", "WORKER_ROLES")) | {"api"}
    declared_roles = set(manifest["release_surface"]["runtime_roles"])
    if roles != declared_roles:
        errors.append(f"FT_SURFACE_ROLE_DRIFT:expected={sorted(roles)}")
    source = (runtime / "consumer_specs.py").read_text(encoding="utf-8")
    for consumer in manifest["release_surface"]["consumers"]:
        if f'name="{consumer}"' not in source:
            errors.append(f"FT_SURFACE_UNKNOWN_CONSUMER:{consumer}")
    for name, rollout in manifest.get("rollouts", {}).items():
        stage = rollout.get("stage")
        if stage not in STAGES:
            errors.append(f"FT_ROLLOUT_INVALID_STAGE:{name}:{stage}")
        if not rollout.get("owner") or not rollout.get("rollback"):
            errors.append(f"FT_ROLLOUT_MISSING_CONTROL:{name}")
        if rollout.get("tenant_allowlist_env") != "FOUNDING_TENANT_ALLOWLIST":
            errors.append(f"FT_ROLLOUT_HARDCODED_TENANT:{name}")
    flags = manifest["required_controls"]["feature_flags"]
    for flag in ("POLICY_ENFORCEMENT_ENABLED", "ROUTE_REGISTRY_ENFORCED",
                 "KYBER_OPERATOR_GATE_ENFORCED", "SERVER_AUTHORITATIVE_CONSENT_ENABLED"):
        if flags.get(flag) is not True:
            errors.append(f"FT_UNSAFE_FLAG:{flag}")

    # required_controls.tests must name real, invokable release gates. A test
    # id that does not resolve to a Makefile target is a control that reads as
    # enforced in this manifest but cannot actually be run by anyone.
    required_tests = manifest["required_controls"].get("tests") or []
    if not required_tests:
        errors.append("FT_CONTROL_TESTS_EMPTY")
    make_targets = _makefile_targets()
    seen_tests: set[str] = set()
    for test_id in required_tests:
        if test_id in seen_tests:
            errors.append(f"FT_CONTROL_TEST_DUPLICATE:{test_id}")
        seen_tests.add(test_id)
        if test_id not in make_targets:
            errors.append(f"FT_CONTROL_TEST_UNKNOWN_TARGET:{test_id}")

    # required_controls.alerts must each carry a concrete, testable breach
    # condition. release_thresholds is the only place in this manifest that
    # operationalizes an alert into a numeric trigger; an alert with no
    # corresponding threshold key is a name with nothing wired behind it.
    required_alerts = manifest["required_controls"].get("alerts") or []
    if not required_alerts:
        errors.append("FT_CONTROL_ALERTS_EMPTY")
    thresholds = manifest.get("release_thresholds") or {}
    seen_alerts: set[str] = set()
    for alert in required_alerts:
        if alert in seen_alerts:
            errors.append(f"FT_ALERT_DUPLICATE:{alert}")
        seen_alerts.add(alert)
        if not any(key == alert or key.startswith(f"{alert}_") for key in thresholds):
            errors.append(f"FT_ALERT_NO_THRESHOLD:{alert}")

    return errors


def main() -> int:
    errors = validate()
    if errors:
        print("Founding-tenant surface FAILED:\n- " + "\n- ".join(errors), file=sys.stderr)
        return 1
    print("Founding-tenant surface passed: routes, roles, consumers, flags, and rollouts agree.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
