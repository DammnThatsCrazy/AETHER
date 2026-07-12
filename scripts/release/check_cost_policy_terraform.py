#!/usr/bin/env python3
"""Validate the Terraform layer honors the production-lean cost policy.

Where check_cost_policy.py validates the canonical policy DATA
(config/deployment_profiles.yaml), this validator asserts the Terraform in
`AWS Deployment/aether-aws/terraform/` actually encodes it:

  1. The `deployment_profile` variable exists with the four valid profiles.
  2. The profile `locals` derive an `enable_*` toggle for every forbidden
     production-lean resource, and each is FALSE-by-derivation when the profile
     is production-lean (i.e. `local.scale || local.enterprise`, or literal
     `false`). `enable_legacy_rds` must be literally `false`.
  3. The four `profiles/*.tfvars` files exist and set a valid deployment_profile
     matching their filename.

Static analysis only (regex + a tiny boolean evaluator over the trusted, static
Terraform file). No terraform binary required. Exit 0 on pass, 1 on fail.

Usage: python scripts/release/check_cost_policy_terraform.py
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import Reporter, load_yaml, main_guard, repo_root  # noqa: E402

TF_DIR = "AWS Deployment/aether-aws/terraform"
PROFILES_TF = f"{TF_DIR}/profiles.tf"
VARIABLES_TF = f"{TF_DIR}/variables.tf"

VALID_PROFILES = ["staging", "production-lean", "production-scale", "enterprise-isolated"]

# Maps a production-lean forbidden resource (config/deployment_profiles.yaml) to
# the Terraform local that gates it. Resources that are not per-resource toggles
# (e.g. always_on_staging_compute — a staging lifecycle concern) are intentionally
# absent; the DATA validator (check_cost_policy.py) covers the full forbidden set.
FORBIDDEN_TO_LOCAL = {
    "msk": "enable_msk",
    "elasticache": "enable_elasticache",
    "neptune": "enable_neptune",
    "clickhouse": "enable_clickhouse",
    "dedicated_ml_service": "enable_dedicated_ml",
    "frontend_ecs_services": "enable_frontend_ecs",
    "legacy_rds": "enable_legacy_rds",
    "nat_gateway_unless_explicit": "enable_nat_gateway",
    "prometheus_grafana_servers": "enable_prometheus_grafana",
}

# Tokens permitted in a toggle RHS. Keeps the boolean eval closed over the
# trusted, static Terraform file (belt-and-braces even though input is our own).
_ALLOWED_TOKEN = re.compile(r"^(local\.\w+|true|false|\|\||&&|!|\(|\))$")


def _read(rel_path: str) -> str | None:
    path = repo_root() / rel_path
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def _extract_locals(tf_text: str) -> dict[str, str]:
    """Return {local_name: rhs_expression} for every `enable_* = <rhs>` line."""
    locals_map: dict[str, str] = {}
    for m in re.finditer(r"^\s*(enable_\w+)\s*=\s*(.+?)\s*$", tf_text, re.MULTILINE):
        name, rhs = m.group(1), m.group(2)
        # Strip trailing inline comments, if any.
        rhs = re.sub(r"#.*$", "", rhs).strip()
        locals_map[name] = rhs
    return locals_map


def _eval_lean(rhs: str) -> bool | None:
    """Evaluate a toggle RHS under the production-lean scenario.

    lean=True, scale=False, enterprise=False, staging=False. Returns the boolean
    result, or None if the RHS contains an unexpected token (treated as a fail).
    """
    scenario = {"lean": True, "scale": False, "enterprise": False, "staging": False}

    # Tokenize just enough to validate + translate: local.X, true/false, ops.
    tokens = re.findall(r"local\.\w+|true|false|\|\||&&|!|\(|\)", rhs)
    # Reject anything left over that isn't whitespace / a recognized token.
    stripped = re.sub(r"local\.\w+|true|false|\|\||&&|!|\(|\)|\s+", "", rhs)
    if stripped:
        return None
    for tok in tokens:
        if not _ALLOWED_TOKEN.match(tok):
            return None

    py = rhs
    py = py.replace("||", " or ").replace("&&", " and ").replace("!", " not ")
    py = re.sub(r"true\b", "True", py)
    py = re.sub(r"false\b", "False", py)

    def _sub_local(match: re.Match) -> str:
        key = match.group(1)
        return str(bool(scenario.get(key, False)))

    py = re.sub(r"local\.(\w+)", _sub_local, py)

    try:
        return bool(eval(py, {"__builtins__": {}}, {}))  # noqa: S307 - closed token set
    except Exception:
        return None


def check() -> int:
    r = Reporter("COST POLICY (TERRAFORM) — production-lean plan excludes forbidden resources")

    # --- Canonical forbidden list from the policy DATA ---
    try:
        data = load_yaml("config/deployment_profiles.yaml")
    except FileNotFoundError:
        r.fail("config/deployment_profiles.yaml not found")
        return r.finish()

    lean = ((data or {}).get("profiles", {}) or {}).get("production-lean", {})
    cost = (lean or {}).get("cost_policy", {})
    forbidden = list((cost or {}).get("forbidden_resources", []) or [])
    r.require(bool(forbidden),
              "production-lean cost_policy.forbidden_resources present",
              "production-lean cost_policy.forbidden_resources missing")

    # --- deployment_profile variable ---
    vars_text = _read(VARIABLES_TF)
    if vars_text is None:
        r.fail(f"{VARIABLES_TF} not found")
        return r.finish()

    r.require('variable "deployment_profile"' in vars_text,
              "deployment_profile variable declared",
              "deployment_profile variable missing from variables.tf")
    r.require(all(p in vars_text for p in VALID_PROFILES) and "contains(" in vars_text,
              "deployment_profile validation lists the four valid profiles",
              "deployment_profile validation does not list all valid profiles")

    # --- profiles.tf locals ---
    tf_text = _read(PROFILES_TF)
    if tf_text is None:
        r.fail(f"{PROFILES_TF} not found")
        return r.finish()

    locals_map = _extract_locals(tf_text)
    r.require(bool(locals_map),
              "profiles.tf declares enable_* locals",
              "profiles.tf has no enable_* locals")

    # Every forbidden resource that maps to a toggle must be false-by-derivation.
    for resource, local_name in FORBIDDEN_TO_LOCAL.items():
        if resource not in forbidden:
            # The resource is expected to be forbidden by the policy data; if the
            # policy dropped it, that's a real drift the DATA validator owns, but
            # flag it here too so the two stay coherent.
            r.fail(f"{resource} not in policy forbidden_resources (policy drift)")
            continue
        rhs = locals_map.get(local_name)
        if rhs is None:
            r.fail(f"{local_name} local missing for forbidden resource {resource}")
            continue
        result = _eval_lean(rhs)
        if result is None:
            r.fail(f"{local_name} RHS not statically analyzable: {rhs!r}")
        else:
            r.require(result is False,
                      f"{local_name} is false for production-lean ({resource})",
                      f"{local_name} is NOT false for production-lean: {rhs!r}")

    # legacy_rds must be hard-disabled (literal false), not merely scale-gated.
    legacy = locals_map.get("enable_legacy_rds", "")
    r.require(legacy.strip() == "false",
              "enable_legacy_rds is literally false",
              f"enable_legacy_rds must be literal false, got: {legacy!r}")

    # --- profiles/*.tfvars ---
    for profile in VALID_PROFILES:
        rel = f"{TF_DIR}/profiles/{profile}.tfvars"
        text = _read(rel)
        if text is None:
            r.fail(f"missing profile tfvars: profiles/{profile}.tfvars")
            continue
        m = re.search(r'deployment_profile\s*=\s*"([^"]+)"', text)
        if not m:
            r.fail(f"profiles/{profile}.tfvars does not set deployment_profile")
            continue
        value = m.group(1)
        ok = value == profile and value in VALID_PROFILES
        r.require(ok,
                  f"profiles/{profile}.tfvars sets deployment_profile = \"{value}\"",
                  f"profiles/{profile}.tfvars has mismatched/invalid profile: {value!r}")

    return r.finish()


if __name__ == "__main__":
    main_guard(check)
