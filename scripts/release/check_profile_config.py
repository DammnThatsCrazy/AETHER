#!/usr/bin/env python3
"""Validate the deployment-profile matrix and founding-tenant posture.

Checks:
  1. config/deployment_profiles.yaml parses and declares every canonical profile.
  2. Each profile has a backend selector for every backend dimension.
  3. config/posture/founding_tenant_production.yaml parses with required keys.
  4. Posture never claims a prohibited external attestation state.

Usage: python scripts/release/check_profile_config.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import Reporter, load_yaml, main_guard  # noqa: E402

CANONICAL_PROFILES = ["staging", "production"]
BACKEND_DIMS = ["database", "cache", "event", "graph", "analytics", "object", "ml"]

# The founding-tenant posture must never assert these — they require external
# artifacts the repo cannot produce.
FORBIDDEN_ATTESTATION = {"report_received"}
ALLOWED_STAGES = {
    "internal", "design_partner", "founding_tenant",
    "limited_availability", "general_availability", "enterprise_ga",
}


CANONICAL_ENVIRONMENTS = ["staging", "production"]


def _check_canonical_environments(r, data: dict, profiles: dict) -> None:
    """The two environments (staging, production) map onto the two profiles."""
    envs = data.get("canonical_environments")
    if not isinstance(envs, dict):
        r.fail("canonical_environments block missing")
        return
    r.require(
        list(envs) == CANONICAL_ENVIRONMENTS,
        "canonical environments are exactly staging and production",
        f"canonical environments must be {CANONICAL_ENVIRONMENTS}, got {list(envs)}",
    )
    unmapped = list(data.get("unmapped_profiles") or [])
    mapped: list[str] = []
    for name, spec in envs.items():
        mapped.extend((spec or {}).get("profiles") or [])
    r.require(
        len(mapped) == len(set(mapped)),
        "no profile belongs to two canonical environments",
        f"profiles mapped to more than one environment: "
        f"{sorted({p for p in mapped if mapped.count(p) > 1})}",
    )
    both = sorted(set(mapped) & set(unmapped))
    r.require(
        not both,
        "no profile is both mapped to an environment and listed as unmapped",
        f"profiles both mapped and unmapped: {both}",
    )
    covered = set(mapped) | set(unmapped)
    r.require(
        covered == set(profiles),
        "every profile is mapped to an environment or explicitly unmapped",
        f"unmapped profiles: {sorted(set(profiles) - covered)}; "
        f"unknown names: {sorted(covered - set(profiles))}",
    )

    staging = envs.get("staging") or {}
    lanes = set(((profiles.get("staging") or {}).get("deployment_lanes") or {}))
    r.require(
        set(staging.get("lanes") or []) == lanes,
        "staging lanes match the staging profile's deployment_lanes",
        f"staging lanes {staging.get('lanes')} != deployment_lanes {sorted(lanes)}",
    )

    production = envs.get("production") or {}
    r.require(
        list(production.get("profiles") or []) == ["production"],
        "production environment maps to exactly the production profile",
        f"production environment must map to [production], got {production.get('profiles')}",
    )


def check() -> int:
    r = Reporter("PROFILE CONFIG — deployment_profiles.yaml + posture")

    try:
        data = load_yaml("config/deployment_profiles.yaml")
    except FileNotFoundError:
        r.fail("config/deployment_profiles.yaml not found")
        return r.finish()

    profiles = (data or {}).get("profiles", {})
    r.require(isinstance(profiles, dict) and bool(profiles),
              "profiles block present", "profiles block missing or empty")

    # Canonical-count enforcement is TWO-directional. A profile added to the
    # matrix must be added here first (missing), and a profile removed from the
    # matrix must be removed here too (extra) — otherwise the canonical set
    # drifts one profile at a time with every check passing. This is the guard
    # that keeps the documented "two profiles" claim truthful.
    canonical_set = set(CANONICAL_PROFILES)
    declared_set = set(profiles)
    r.require(
        declared_set == canonical_set,
        f"profile set exactly matches canonical {len(canonical_set)} profiles",
        f"profile set mismatch: missing={sorted(canonical_set - declared_set)} "
        f"extra={sorted(declared_set - canonical_set)}",
    )

    for name in CANONICAL_PROFILES:
        if name not in profiles:
            r.fail(f"missing canonical profile: {name}")
            continue
        backends = (profiles[name] or {}).get("backends", {})
        missing = [d for d in BACKEND_DIMS if d not in backends]
        r.require(not missing,
                  f"{name}: all backend dimensions declared",
                  f"{name}: missing backend dimensions {missing}")

    _check_canonical_environments(r, data or {}, profiles)

    # Posture file
    try:
        posture = load_yaml("config/posture/founding_tenant_production.yaml")
    except FileNotFoundError:
        r.fail("config/posture/founding_tenant_production.yaml not found")
        return r.finish()

    for key in ("commercial_stage", "external_attestation_status",
                "permitted_data_classes", "prohibited_data_classes", "enabled_features"):
        r.require(key in (posture or {}),
                  f"posture declares {key}", f"posture missing {key}")

    stage = (posture or {}).get("commercial_stage")
    r.require(stage in ALLOWED_STAGES,
              f"posture commercial_stage valid ({stage})",
              f"posture commercial_stage invalid: {stage}")

    attest = (posture or {}).get("external_attestation_status")
    r.require(attest not in FORBIDDEN_ATTESTATION,
              f"posture external_attestation_status not over-claimed ({attest})",
              f"posture over-claims external attestation: {attest}")

    profile_ref = (posture or {}).get("deployment_profile")
    r.require(profile_ref in profiles,
              f"posture deployment_profile resolves ({profile_ref})",
              f"posture deployment_profile not a known profile: {profile_ref}")

    return r.finish()


if __name__ == "__main__":
    main_guard(check)
