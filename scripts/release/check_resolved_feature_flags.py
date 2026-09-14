#!/usr/bin/env python3
"""Validate the checked-in release feature-flag resolutions.

The runtime settings module remains the authority for flag names and defaults.
These manifests make the release decision explicit: every runtime flag whose
default is on for a deploy target must be deliberately placed in ``on`` or
``off``.  Any flag not listed resolves to its source default, and the manifests
declare that default-off flags remain off for this bounded release.

This is a credentialless, non-mutating validator.  It does not contact AWS,
Terraform, Auth0, or a feature-flag service.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover - environment diagnostic
    raise SystemExit("PyYAML is required to validate release manifests") from exc


ROOT = Path(__file__).resolve().parents[2]
SETTINGS = ROOT / "services/backend/config/settings.py"
DEPLOYMENT_PROFILES = ROOT / "config/deployment_profiles.yaml"
PYPROJECT = ROOT / "pyproject.toml"

REQUIRED_ON = {
    "TRUST_PLANE_ENABLED",
    "HUMAN_SESSIONS_ENABLED",
    "SERVICE_CREDENTIALS_ENABLED",
    "POLICY_ENFORCEMENT_ENABLED",
    "ROUTE_REGISTRY_ENFORCED",
    "KYBER_OPERATOR_GATE_ENFORCED",
    "KYBER_WORKFORCE_IDENTITY_ENABLED",
    "KYBER_DEVICE_TRUST_REQUIRED",
    "KYBER_BACKEND_AUTHZ_ENFORCED",
    "KYBER_SCOPE_V2_ENABLED",
    "KYBER_STEP_UP_REQUIRED",
    "AUTHORITATIVE_CONSENT_ENFORCEMENT_ENABLED",
    "TENANT_COMPLIANCE_POLICY_ENABLED",
    "INGESTION_ENVELOPE_REQUIRED_FIELDS_ENFORCED",
    "SEMANTIC_DURABLE_STORE_ENABLED",
}

REQUIRED_OFF = {
    "LEGACY_TENANT_REGISTRATION_ENABLED",
    "FIRST_ADMIN_BOOTSTRAP_ENABLED",
    "KYBER_LEGACY_OPERATOR_IDENTITY_ALLOWED",
    "KYBER_BOOTSTRAP_ENABLED",
    "AETHER_MOBILE_ENABLED",
    "AETHER_PAYMENT_RAILS_ENABLED",
}


def _pyproject_version() -> str:
    match = re.search(r'^version\s*=\s*"([^"]+)"', PYPROJECT.read_text(), re.MULTILINE)
    if not match:
        raise ValueError("pyproject.toml has no canonical version")
    return match.group(1)


def _default_bool(node: ast.AST | None) -> bool:
    """Resolve deploy-target defaults used by settings.py's _env_bool calls."""
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.Name) and node.id in {"_TRUST_DEFAULT_ON", "_KYBER_DEFAULT_ON"}:
        return True
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        if isinstance(node.operand, ast.Name) and node.operand.id in {
            "_TRUST_DEFAULT_ON",
            "_KYBER_DEFAULT_ON",
        }:
            return False
        if isinstance(node.operand, ast.Call) and isinstance(node.operand.func, ast.Name):
            if node.operand.func.id == "_is_local_default":
                return True
    # These expressions explicitly select staging/production.
    if isinstance(node, ast.Compare):
        rendered = ast.unparse(node)
        if "AETHER_ENV" in rendered and ("staging" in rendered or "production" in rendered):
            return True
    return False


def runtime_flags() -> tuple[set[str], set[str]]:
    tree = ast.parse(SETTINGS.read_text(encoding="utf-8"))
    names: set[str] = set()
    default_on: set[str] = set()
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_env_bool"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            continue
        name = node.args[0].value
        names.add(name)
        if _default_bool(node.args[1] if len(node.args) > 1 else None):
            default_on.add(name)
    return names, default_on


def _load(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: manifest root must be a mapping")
    return value


def _list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be a list of strings")
    return value


def _require(mapping: dict[str, Any], key: str, expected: Any, label: str) -> None:
    actual = mapping.get(key)
    if actual != expected:
        raise ValueError(f"{label}.{key} must be {expected!r}; found {actual!r}")


def validate(path: Path) -> list[str]:
    errors: list[str] = []
    data = _load(path)
    label = str(path.relative_to(ROOT))

    _require(data, "schema_version", 1, label)
    environment = data.get("environment")
    if environment not in {"staging", "production-lean"}:
        errors.append(f"{label}: environment must be staging or production-lean")
    release = data.get("release")
    if not isinstance(release, dict):
        errors.append(f"{label}: release must be a mapping")
        return errors
    try:
        if release.get("platform_version") != _pyproject_version():
            errors.append(
                f"{label}: release.platform_version {release.get('platform_version')!r} "
                f"!= pyproject.toml {_pyproject_version()!r}"
            )
    except ValueError as exc:
        errors.append(str(exc))
    if release.get("production_claim") is not False:
        errors.append(f"{label}: production_claim must remain false for this bounded alpha")
    if release.get("seven_day_cost_observation_required") is not True:
        errors.append(f"{label}: seven_day_cost_observation_required must be true")

    runtime = data.get("runtime")
    if not isinstance(runtime, dict):
        errors.append(f"{label}: runtime must be a mapping")
        return errors
    env = runtime.get("env")
    if not isinstance(env, dict):
        errors.append(f"{label}: runtime.env must be a mapping")
    else:
        # Terraform uses environment=production for the production-lean
        # deployment profile. The profile name is release-policy metadata, not
        # a value accepted by the runtime settings environment selector.
        runtime_environment = "production" if environment == "production-lean" else environment
        if env.get("AETHER_ENV") != runtime_environment:
            errors.append(
                f"{label}: runtime.env.AETHER_ENV must equal {runtime_environment!r} "
                f"for profile {environment!r}"
            )
        _require(env, "AETHER_CREDENTIAL_BACKEND", "aws_secrets_manager", label + ".runtime.env")
        _require(env, "CREDENTIAL_CIPHER", "aws_kms", label + ".runtime.env")

    flags = runtime.get("flags")
    if not isinstance(flags, dict):
        errors.append(f"{label}: runtime.flags must be a mapping")
        return errors
    try:
        on = set(_list(flags.get("on"), label + ".runtime.flags.on"))
        off = set(_list(flags.get("off"), label + ".runtime.flags.off"))
    except ValueError as exc:
        errors.append(str(exc))
        return errors
    all_flags, default_on = runtime_flags()
    duplicate = on & off
    unknown = (on | off) - all_flags
    missing_default_on = default_on - (on | off)
    if duplicate:
        errors.append(f"{label}: flags appear in both on and off: {sorted(duplicate)}")
    if unknown:
        errors.append(f"{label}: unknown runtime flags: {sorted(unknown)}")
    if missing_default_on:
        errors.append(
            f"{label}: every deploy-default-on flag must be resolved; missing {sorted(missing_default_on)}"
        )
    if flags.get("unlisted_default") != "off":
        errors.append(f"{label}: runtime.flags.unlisted_default must be 'off'")
    if not REQUIRED_ON <= on:
        errors.append(f"{label}: required release flags not ON: {sorted(REQUIRED_ON - on)}")
    if not REQUIRED_OFF <= off:
        errors.append(f"{label}: required release flags not OFF: {sorted(REQUIRED_OFF - off)}")
    for key in ("required_on", "required_off"):
        try:
            required = set(_list(flags.get(key), label + f".runtime.flags.{key}"))
        except ValueError as exc:
            errors.append(str(exc))
            continue
        selected = on if key == "required_on" else off
        if not required <= selected:
            errors.append(f"{label}: {key} contains unresolved flags: {sorted(required - selected)}")

    mobile = data.get("mobile")
    if not isinstance(mobile, dict):
        errors.append(f"{label}: mobile must be a mapping")
    else:
        if mobile.get("apps_enabled") is not False:
            errors.append(f"{label}: mobile.apps_enabled must be false")
        if mobile.get("distribution_posture") != "design_partner_dev_only":
            errors.append(f"{label}: mobile distribution posture must be design_partner_dev_only")
        rn = mobile.get("react_native_sdk")
        if not isinstance(rn, dict) or rn.get("release_policy") != "conditional_on_gate_pass":
            errors.append(f"{label}: React Native SDK must be conditional on its real gate")
        elif not rn.get("required_gates"):
            errors.append(f"{label}: React Native SDK must name required gates")

    hosting = data.get("hosting")
    if not isinstance(hosting, dict):
        errors.append(f"{label}: hosting must be a mapping")
    else:
        canonical_domains = hosting.get("canonical_domains")
        expected_domains = {
            "olympus_marketing": "https://www.olympuslabsml.com",
            "aether_marketing": "https://aether.olympuslabsml.com",
            "docs": "https://docs.olympuslabsml.com",
            "app": "https://app.olympuslabsml.com",
            "status": "https://status.olympuslabsml.com",
            "api": "https://api.olympuslabsml.com",
        }
        if canonical_domains != expected_domains:
            errors.append(f"{label}: hosting.canonical_domains must match the reviewed public domain map")
        if hosting.get("kyber") != "internal_only_no_public_dns":
            errors.append(f"{label}: hosting.kyber must remain internal_only_no_public_dns")
        if environment == "staging":
            if hosting.get("staging_custom_domain") != "disabled_until_promotion":
                errors.append(f"{label}: staging custom domains must remain disabled until promotion")
        elif hosting.get("production_custom_domain") != "enabled":
            errors.append(f"{label}: production-lean custom domains must be explicitly enabled")

    access = data.get("access_boundary")
    if not isinstance(access, dict):
        errors.append(f"{label}: access_boundary must be a mapping")
    else:
        aether = access.get("aether_tenant_admin", {})
        kyber = access.get("kyber_internal_operator", {})
        if not isinstance(aether, dict) or aether.get("can_access_kyber") is not False:
            errors.append(f"{label}: Aether tenant admin must not access Kyber")
        if not isinstance(kyber, dict) or kyber.get("workforce_identity_required") is not True:
            errors.append(f"{label}: Kyber operator must require workforce identity")
        if not isinstance(kyber, dict) or kyber.get("legacy_tenant_operator_path") is not False:
            errors.append(f"{label}: Kyber legacy tenant-operator path must be false")

    cost = data.get("cost_guardrails")
    if not isinstance(cost, dict):
        errors.append(f"{label}: cost_guardrails must be a mapping")
    else:
        if cost.get("seven_consecutive_observed_days_required") is not True:
            errors.append(f"{label}: cost guardrail must require seven observed days")
        if cost.get("evidence_mode") != "observed_only":
            errors.append(f"{label}: cost evidence mode must be observed_only")
        profile_name = "staging" if environment == "staging" else "production-lean"
        profiles = _load(DEPLOYMENT_PROFILES).get("profiles", {})
        profile = profiles.get(profile_name, {}) if isinstance(profiles, dict) else {}
        budget = profile.get("budget", {}) if isinstance(profile, dict) else {}
        budget_keys = (
            ("monthly_target_usd", "target_monthly_spend"),
            ("monthly_hard_cap_usd", "hard_monthly_spend"),
        ) if environment == "staging" else (
            ("monthly_target_usd", "target_fixed_monthly"),
            ("monthly_hard_cap_usd", "hard_fixed_monthly"),
        )
        for manifest_key, profile_key in budget_keys:
            if cost.get(manifest_key) != budget.get(profile_key):
                errors.append(
                    f"{label}: {manifest_key} {cost.get(manifest_key)!r} != "
                    f"config/deployment_profiles.yaml {profile_key} {budget.get(profile_key)!r}"
                )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifests", nargs="*", type=Path)
    parser.add_argument("--all", action="store_true", help="validate the checked-in staging and lean manifests")
    args = parser.parse_args()
    paths = (
        sorted((ROOT / "config/release/feature_flags").glob("*.yaml"))
        if args.all or not args.manifests
        else [ROOT / path for path in args.manifests]
    )
    if not paths:
        print("No release manifests found", file=sys.stderr)
        return 1
    errors: list[str] = []
    for path in paths:
        try:
            errors.extend(validate(path))
        except (OSError, ValueError, yaml.YAMLError) as exc:
            errors.append(f"{path}: {exc}")
    if errors:
        print("Resolved feature-flag validation failed:")
        for error in errors:
            print(f"  - {error}")
        return 1
    print(f"Resolved feature-flag validation passed for {len(paths)} manifest(s); deploy-default-on flags are explicit and mobile apps remain off.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
