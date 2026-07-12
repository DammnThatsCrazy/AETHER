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

CANONICAL_PROFILES = [
    "local-mocked", "local-live", "local-full", "demo-static", "demo-live",
    "preview", "staging", "production-lean", "production-scale", "enterprise-isolated",
]
BACKEND_DIMS = ["database", "cache", "event", "graph", "analytics", "object", "ml"]

# The founding-tenant posture must never assert these — they require external
# artifacts the repo cannot produce.
FORBIDDEN_ATTESTATION = {"report_received"}
ALLOWED_STAGES = {
    "internal", "design_partner", "founding_tenant",
    "limited_availability", "general_availability", "enterprise_ga",
}


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

    for name in CANONICAL_PROFILES:
        if name not in profiles:
            r.fail(f"missing canonical profile: {name}")
            continue
        backends = (profiles[name] or {}).get("backends", {})
        missing = [d for d in BACKEND_DIMS if d not in backends]
        r.require(not missing,
                  f"{name}: all backend dimensions declared",
                  f"{name}: missing backend dimensions {missing}")

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
