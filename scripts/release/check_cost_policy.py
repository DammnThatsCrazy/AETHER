#!/usr/bin/env python3
"""Validate the production-lean cost policy.

Checks the canonical policy DATA (config/deployment_profiles.yaml). It asserts
production-lean declares the required cost_policy and that its forbidden list
covers every expensive scale/enterprise resource. The Terraform-plan level
gate that asserts a real plan excludes these resources is a follow-up
(ledger FT-9-TERRAFORM-PROFILES); this validator fixes the policy target.

Usage: python scripts/release/check_cost_policy.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import Reporter, load_yaml, main_guard  # noqa: E402

# Every expensive resource production-lean must forbid (monoprompt §2.1 / §11).
REQUIRED_FORBIDDEN = {
    "msk", "elasticache", "neptune", "clickhouse",
    "dedicated_ml_service", "frontend_ecs_services",
    "legacy_rds", "nat_gateway_unless_explicit",
    "always_on_staging_compute",
}
REQUIRED_PRESENT = {
    "cloudfront_s3_frontends", "single_ecs_backend",
    "aurora_serverless_v2", "sqs_sns", "s3_object_lake",
}


def check() -> int:
    r = Reporter("COST POLICY — production-lean forbidden/required resources")

    try:
        data = load_yaml("config/deployment_profiles.yaml")
    except FileNotFoundError:
        r.fail("config/deployment_profiles.yaml not found")
        return r.finish()

    lean = ((data or {}).get("profiles", {}) or {}).get("production-lean", {})
    r.require(bool(lean), "production-lean profile present", "production-lean profile missing")

    cost = (lean or {}).get("cost_policy", {})
    r.require(bool(cost), "production-lean cost_policy present", "production-lean cost_policy missing")

    forbidden = set((cost or {}).get("forbidden_resources", []) or [])
    missing_forbidden = REQUIRED_FORBIDDEN - forbidden
    r.require(not missing_forbidden,
              "cost_policy forbids all expensive scale/enterprise resources",
              f"cost_policy missing forbidden resources: {sorted(missing_forbidden)}")

    required = set((cost or {}).get("required_resources", []) or [])
    missing_required = REQUIRED_PRESENT - required
    r.require(not missing_required,
              "cost_policy declares the required lean resources",
              f"cost_policy missing required resources: {sorted(missing_required)}")

    # A forbidden resource must never also be required — internal coherence.
    overlap = forbidden & required
    r.require(not overlap,
              "no resource is both required and forbidden",
              f"resources both required and forbidden: {sorted(overlap)}")

    return r.finish()


if __name__ == "__main__":
    main_guard(check)
