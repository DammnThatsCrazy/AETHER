#!/usr/bin/env python3
"""Validate the production-lean cost policy.

Checks the canonical policy DATA (config/deployment_profiles.yaml). It asserts
production-lean declares the required cost_policy and that its forbidden list
covers every expensive scale/enterprise resource. The Terraform and immutable-delivery gates independently assert the selected
profile excludes these resources and deploys the declared role topology.

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
    # Self-managed Prometheus/Grafana EC2 re-introduces always-on servers the
    # lean profile replaced with managed CloudWatch. Present in the YAML and in
    # check_cost_policy_terraform.py's FORBIDDEN_TO_LOCAL map, so it belongs here.
    "prometheus_grafana_servers",
}
REQUIRED_PRESENT = {
    "cloudfront_s3_frontends", "explicit_runtime_role_services",
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

    check_always_on_staging_compute(r, data or {})

    return r.finish()


def check_always_on_staging_compute(r: Reporter, data: dict) -> None:
    """Evaluate the control the plan gate defers to this file.

    `always_on_staging_compute` is `not_plan_checkable`: a plan cannot show
    whether an environment is slept after validation, so
    check_terraform_plan_policy.py records it as DEFERRED rather than passed and
    names this file as the enforcer. That made this file's job real, and it was
    not being done — asserting the string appears in a list is not enforcement,
    it is a spell check.

    What is checkable here is the DATA that makes the prohibition mean
    something: staging must declare wake/sleep, must carry a bounded awake-hours
    budget materially smaller than a month, must be budgeted on total spend (so
    the awake hours actually enter the ceiling), and must declare that it sleeps
    after validation. Any one of those missing turns "no always-on staging
    compute" into an unenforced sentence.
    """
    staging = ((data.get("profiles") or {}).get("staging") or {})
    if not staging:
        r.fail("always_on_staging_compute: no staging profile to enforce it against")
        return

    forbidden = set((staging.get("cost_policy") or {}).get("forbidden_resources") or [])
    r.require(
        "always_on_staging_compute" in forbidden,
        "staging forbids always_on_staging_compute",
        "staging does not forbid always_on_staging_compute, so the awake-hours "
        "budget bounds nothing",
    )

    r.require(
        bool(staging.get("wake_sleep")),
        "staging declares wake_sleep: true",
        "staging does not declare wake_sleep: true, so its compute is always-on "
        "by declaration",
    )

    budget = staging.get("budget") or {}
    awake = budget.get("maximum_scheduled_awake_hours_per_month")
    reference = budget.get("pricing_hours_per_month")
    if not isinstance(awake, (int, float)) or isinstance(awake, bool) or awake <= 0:
        r.fail("staging declares no positive maximum_scheduled_awake_hours_per_month, "
               "so nothing bounds how long staging runs")
    elif not isinstance(reference, (int, float)) or awake >= float(reference):
        r.fail(f"staging awake-hours budget {awake} is not below its reference month "
               f"{reference}; an environment awake for a whole month is always-on "
               f"whatever the profile calls it")
    else:
        r.ok(f"staging awake-hours capped at {awake}/month against a "
             f"{reference}-hour reference month")

    r.require(
        "target_monthly_spend" in budget and "hard_monthly_spend" in budget,
        "staging is budgeted on total monthly spend, so the awake hours enter the ceiling",
        "staging declares no target_monthly_spend/hard_monthly_spend, so its "
        "awake-hours budget never reaches a numeric ceiling",
    )

    behavior = [str(b) for b in (staging.get("behavior") or [])]
    r.require(
        any("sleep" in b for b in behavior),
        "staging behavior declares it is slept after validation",
        f"staging behavior {behavior} never says the environment is slept; the "
        f"prohibition on always-on compute has no counterpart in the lifecycle",
    )


if __name__ == "__main__":
    main_guard(check)
