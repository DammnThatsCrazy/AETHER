#!/usr/bin/env python3
"""Validate the canonical staging deployment-lane and pilot Stripe contract.

``deployment_profile=staging`` remains the only staging profile and the only
Terraform state identity.  ``deployment_lane`` is an explicit overlay token:
``full`` preserves the existing rehearsal and ``pilot`` enables the complete
customer-facing lean staging contract.

The pilot contract is deliberately fail-closed. It checks the repository
registry and ECS wiring without printing secret values, and an optional
read-only AWS preflight checks that all four self-service Stripe test price-ID
secrets have an ``AWSCURRENT`` version. Contract-tier identifiers remain
optional operator mappings. Secret values are never read by this checker;
secure bootstrap is responsible for validating identifiers before writing them
to Secrets Manager.

Examples:

  python scripts/release/check_staging_lane_contract.py \
    --profile staging --deployment-lane full

  python scripts/release/check_staging_lane_contract.py \
    --profile staging --deployment-lane pilot --check-runtime-wiring

  python scripts/release/check_staging_lane_contract.py \
    --profile staging --deployment-lane pilot --check-runtime-wiring \
    --require-aws-price-secrets
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Mapping

import yaml


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "deployment_profiles.yaml"
BOOTSTRAP_PATH = ROOT / "scripts" / "bootstrap_aws_secrets.py"
ECS_PATH = ROOT / "deploy" / "aws" / "terraform" / "modules" / "ecs" / "main.tf"

ALLOWED_LANES = frozenset({"full", "pilot"})
PUBLIC_SURFACES = frozenset({
    "olympus_marketing",
    "aether_marketing",
    "aether_docs",
    "aether_app",
    "aether_status",
})
PILOT_DEFERRED = frozenset({
    "kyber_operator_ui",
    "kyber_workforce_identity",
    "google_workforce_credentials",
    "google_oidc",
    "gcp_hosting",
})
PILOT_CONTROLS = frozenset({
    "aws_networking",
    "durable_aurora_postgres",
    "durable_persistence",
    "tenant_isolation",
    "secrets_manager",
    "stripe_billing",
    "stripe_webhooks",
    "stripe_entitlements",
    "cloudwatch_observability",
    "wake_sleep_lifecycle",
    "immutable_artifact_redeploy",
    "database_migrations",
    "full_staging_smoke",
})
REQUIRED_RUNTIME_ENV = (
    "STRIPE_BILLING_ENABLED",
    "STRIPE_PRICE_ALPHA",
    "STRIPE_PRICE_BETA",
    "STRIPE_PRICE_GAMMA",
    "STRIPE_PRICE_DELTA",
    "STRIPE_CHECKOUT_SUCCESS_URL",
    "STRIPE_CHECKOUT_CANCEL_URL",
    "STRIPE_PORTAL_RETURN_URL",
)
REQUIRED_HOSTED_RUNTIME_ENV = (
    "AETHER_ENV",
    "DEPLOYMENT_PROFILE",
    "AUTH0_DOMAIN",
    "AUTH0_API_AUDIENCE",
    "APP_URL",
    "CREDENTIAL_CIPHER",
    "CREDENTIAL_KMS_KEY_ID",
)
REQUIRED_SECRET_MOUNTS = (
    "stripe-secret-key",
    "stripe-webhook-secret",
    "stripe-price-alpha",
    "stripe-price-beta",
    "stripe-price-gamma",
    "stripe-price-delta",
)
REQUIRED_POPULATED_PRICE_SECRETS = (
    "stripe-price-alpha",
    "stripe-price-beta",
    "stripe-price-gamma",
    "stripe-price-delta",
)
REQUIRED_STAGING_BASE_SECRETS = (
    "jwt-secret",
    "byok-encryption-key",
    "stripe-secret-key",
    "stripe-webhook-secret",
    "oracle-signer-private-key",
    "watermark-secret-key",
    "canary-secret-seed",
    "extraction-canary-seed",
    "sdk-config-secret",
    "first-admin-bootstrap-token",
    "jwt-secret-previous",
    "byok-encryption-key-previous",
)
REQUIRED_FULL_STAGING_SECRETS = REQUIRED_STAGING_BASE_SECRETS + (
    "kyber-google-client-id",
    "kyber-google-client-secret",
)
REQUIRED_PILOT_STAGING_SECRETS = REQUIRED_STAGING_BASE_SECRETS + REQUIRED_POPULATED_PRICE_SECRETS
Runner = Callable[..., subprocess.CompletedProcess[str]]


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def load_config(path: Path = CONFIG_PATH) -> Mapping[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = yaml.safe_load(handle)
    return _mapping(value)


def _contains_all(values: Any, required: set[str]) -> bool:
    return isinstance(values, list) and required <= set(values)


def contract_errors(
    data: Mapping[str, Any],
    *,
    profile: str = "staging",
    deployment_lane: str = "full",
) -> list[str]:
    """Return structural lane errors without inspecting infrastructure."""
    errors: list[str] = []
    profiles = _mapping(data.get("profiles"))
    if profile not in profiles:
        return [f"unknown deployment profile: {profile}"]

    if deployment_lane not in ALLOWED_LANES:
        errors.append(
            f"deployment_lane must be one of {sorted(ALLOWED_LANES)}, got {deployment_lane!r}"
        )

    # The lane selector is a staging-only overlay. Other Terraform profiles
    # retain their historical profile-only invocation surface and must not
    # accidentally acquire staging lane semantics.
    if profile != "staging":
        if deployment_lane in ALLOWED_LANES:
            errors.append(
                f"deployment_lane={deployment_lane} is valid only with deployment_profile=staging"
            )
        return errors

    staging = _mapping(profiles[profile])
    if staging.get("class") != "staging":
        errors.append("staging deployment profile must remain class: staging")
    if staging.get("environment") != "staging":
        errors.append("staging deployment profile must declare environment: staging")

    lane_contract = _mapping(staging.get("deployment_lane"))
    allowed = set(lane_contract.get("allowed") or [])
    if allowed != set(ALLOWED_LANES):
        errors.append(
            f"staging.deployment_lane.allowed must be {sorted(ALLOWED_LANES)}, got {sorted(allowed)}"
        )
    if lane_contract.get("default") != "full":
        errors.append("staging.deployment_lane.default must remain full")
    valid_when = _mapping(lane_contract.get("valid_when"))
    if valid_when != {"profile": "staging", "environment": "staging"}:
        errors.append(
            "staging.deployment_lane.valid_when must bind the token to profile=staging and environment=staging"
        )

    lanes = _mapping(staging.get("deployment_lanes"))
    if set(lanes) != set(ALLOWED_LANES):
        errors.append("staging.deployment_lanes must declare exactly full and pilot")
        return errors
    full = _mapping(lanes.get("full"))
    if full.get("state_namespace") != "staging":
        errors.append("staging.deployment_lanes.full must use state_namespace: staging")

    pilot = _mapping(lanes.get("pilot"))
    if pilot.get("base_lane") != "full":
        errors.append("staging.deployment_lanes.pilot must extend base_lane: full")
    if pilot.get("state_namespace") != "staging":
        errors.append("staging.deployment_lanes.pilot must use state_namespace: staging")
    if not _contains_all(pilot.get("required_surfaces"), set(PUBLIC_SURFACES)):
        errors.append("staging pilot must require all five Aether/Olympus public surfaces")
    if not _contains_all(pilot.get("required_controls"), set(PILOT_CONTROLS)):
        errors.append("staging pilot is missing one or more complete-AWS-staging controls")
    if set(pilot.get("deferred_capabilities") or []) != set(PILOT_DEFERRED):
        errors.append(
            "staging pilot deferred_capabilities must be exactly the Kyber/workforce and GCP/Google deferrals"
        )

    stripe = _mapping(pilot.get("stripe_contract"))
    if stripe.get("enabled") is not True:
        errors.append("staging pilot Stripe billing must be enabled")
    if stripe.get("fail_closed_if_unwired") is not True:
        errors.append("staging pilot Stripe contract must fail closed when runtime wiring is incomplete")
    if not _contains_all(stripe.get("required_runtime_env"), set(REQUIRED_RUNTIME_ENV)):
        errors.append("staging pilot Stripe contract is missing required runtime environment names")
    if not _contains_all(stripe.get("required_secret_mounts"), set(REQUIRED_SECRET_MOUNTS)):
        errors.append("staging pilot Stripe contract is missing required ECS secret mounts")
    if set(stripe.get("required_populated_secret_mounts") or []) != set(REQUIRED_POPULATED_PRICE_SECRETS):
        errors.append("staging pilot must require populated four self-service Stripe test price secrets")
    if stripe.get("secret_registry_source") != "scripts/bootstrap_aws_secrets.py":
        errors.append("staging pilot Stripe contract must reference the bootstrap secret registry")
    if stripe.get("ecs_mount_source") != "deploy/aws/terraform/modules/ecs/main.tf":
        errors.append("staging pilot Stripe contract must reference ECS secret wiring")

    return errors


def runtime_wiring_errors(
    *,
    bootstrap_text: str,
    ecs_text: str,
) -> list[str]:
    """Find missing static Stripe registry/runtime wiring for the pilot lane."""
    errors: list[str] = []
    for env_name, secret_name in (
        ("STRIPE_SECRET_KEY", "stripe-secret-key"),
        ("STRIPE_WEBHOOK_SECRET", "stripe-webhook-secret"),
        ("STRIPE_PRICE_ALPHA", "stripe-price-alpha"),
        ("STRIPE_PRICE_BETA", "stripe-price-beta"),
        ("STRIPE_PRICE_GAMMA", "stripe-price-gamma"),
        ("STRIPE_PRICE_DELTA", "stripe-price-delta"),
        ("STRIPE_PRICE_EPSILON", "stripe-price-epsilon"),
        ("STRIPE_PRICE_OMICRON", "stripe-price-omicron"),
        ("STRIPE_PRICE_OMEGA", "stripe-price-omega"),
    ):
        registry_token = f'"{env_name}": "{secret_name}"'
        if registry_token not in bootstrap_text:
            errors.append(f"bootstrap registry missing {env_name} -> {secret_name}")

    for env_name in REQUIRED_HOSTED_RUNTIME_ENV + REQUIRED_RUNTIME_ENV:
        if env_name not in ecs_text:
            errors.append(f"ECS runtime wiring missing {env_name}")

    for secret_name in REQUIRED_SECRET_MOUNTS:
        lookup = re.compile(
            rf"lookup\(\s*var\.secret_arns\s*,\s*[\"']{re.escape(secret_name)}[\"']"
        )
        if not lookup.search(ecs_text):
            errors.append(f"ECS secret mount missing aether/{secret_name}")
    return errors


def _aws_json(
    args: list[str],
    *,
    runner: Runner = subprocess.run,
) -> tuple[dict[str, Any] | None, str | None]:
    result = runner(
        ["aws", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None, "AWS Secrets Manager metadata request failed"
    try:
        value = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return None, "AWS Secrets Manager returned invalid metadata"
    return _mapping(value), None


def aws_price_secret_errors(*, runner: Runner = subprocess.run) -> list[str]:
    """Check required price secret metadata without reading secret values."""
    errors: list[str] = []
    for secret_name in REQUIRED_POPULATED_PRICE_SECRETS:
        metadata, error = _aws_json(
            [
                "secretsmanager",
                "describe-secret",
                "--secret-id",
                f"aether/{secret_name}",
                "--output",
                "json",
            ],
            runner=runner,
        )
        if error or metadata is None:
            errors.append(f"required Stripe test price secret aether/{secret_name} is missing or unreadable")
            continue
        if metadata.get("DeletedDate") is not None:
            errors.append(f"required Stripe test price secret aether/{secret_name} is pending deletion")
            continue
        versions = _mapping(metadata.get("VersionIdsToStages"))
        if not any("AWSCURRENT" in (stages or []) for stages in versions.values()):
            errors.append(f"required Stripe test price secret aether/{secret_name} has no AWSCURRENT version")
    # Secret values intentionally are not read by CI. The secure bootstrap
    # path validates real identifiers before writing them; this preflight only
    # proves that the current version exists and is not pending deletion.

    return errors


def aws_staging_secret_errors(
    *,
    deployment_lane: str,
    runner: Runner = subprocess.run,
) -> list[str]:
    """Check all ECS-mounted staging secret metadata without reading values."""
    if deployment_lane == "pilot":
        required = REQUIRED_PILOT_STAGING_SECRETS
    elif deployment_lane == "full":
        required = REQUIRED_FULL_STAGING_SECRETS
    else:
        return [f"unsupported staging deployment lane: {deployment_lane}"]

    errors: list[str] = []
    for secret_name in required:
        metadata, error = _aws_json(
            [
                "secretsmanager",
                "describe-secret",
                "--secret-id",
                f"aether/{secret_name}",
                "--output",
                "json",
            ],
            runner=runner,
        )
        if error or metadata is None:
            errors.append(f"required staging secret aether/{secret_name} is missing or unreadable")
            continue
        if metadata.get("DeletedDate") is not None:
            errors.append(f"required staging secret aether/{secret_name} is pending deletion")
            continue
        versions = _mapping(metadata.get("VersionIdsToStages"))
        if not any("AWSCURRENT" in (stages or []) for stages in versions.values()):
            errors.append(f"required staging secret aether/{secret_name} has no AWSCURRENT version")
    return errors


def validate(
    *,
    profile: str = "staging",
    deployment_lane: str = "full",
    check_runtime_wiring: bool = False,
    require_aws_price_secrets: bool = False,
    require_aws_staging_secrets: bool = False,
    data: Mapping[str, Any] | None = None,
    bootstrap_text: str | None = None,
    ecs_text: str | None = None,
    runner: Runner = subprocess.run,
) -> list[str]:
    data = data if data is not None else load_config()
    errors = contract_errors(data, profile=profile, deployment_lane=deployment_lane)

    if check_runtime_wiring and profile == "staging" and deployment_lane == "pilot":
        bootstrap = bootstrap_text if bootstrap_text is not None else BOOTSTRAP_PATH.read_text(encoding="utf-8")
        ecs = ecs_text if ecs_text is not None else ECS_PATH.read_text(encoding="utf-8")
        errors.extend(runtime_wiring_errors(bootstrap_text=bootstrap, ecs_text=ecs))
    if require_aws_price_secrets:
        if deployment_lane != "pilot" or profile != "staging":
            errors.append("AWS Stripe price preflight is valid only for deployment_profile=staging and deployment_lane=pilot")
        else:
            errors.extend(aws_price_secret_errors(runner=runner))
    if require_aws_staging_secrets:
        if profile != "staging":
            errors.append("AWS staging secret preflight is valid only for deployment_profile=staging")
        else:
            errors.extend(
                aws_staging_secret_errors(
                    deployment_lane=deployment_lane,
                    runner=runner,
                )
            )
    return sorted(set(errors))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="staging")
    parser.add_argument("--deployment-lane", default="full")
    parser.add_argument("--check-runtime-wiring", action="store_true")
    parser.add_argument("--require-aws-price-secrets", action="store_true")
    parser.add_argument("--require-aws-staging-secrets", action="store_true")
    args = parser.parse_args(argv)

    try:
        errors = validate(
            profile=args.profile,
            deployment_lane=args.deployment_lane,
            check_runtime_wiring=args.check_runtime_wiring,
            require_aws_price_secrets=args.require_aws_price_secrets,
            require_aws_staging_secrets=args.require_aws_staging_secrets,
        )
    except (FileNotFoundError, OSError, yaml.YAMLError) as exc:
        print(f"::error::staging deployment lane contract could not load its inputs: {exc}", file=sys.stderr)
        return 1

    if errors:
        print("::error::staging deployment lane contract failed closed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    checked = " with static Stripe runtime wiring" if args.check_runtime_wiring else ""
    aws_checked = " and current-version AWS Stripe price secrets" if args.require_aws_price_secrets else ""
    print(
        f"staging deployment lane contract valid: profile={args.profile} "
        f"deployment_lane={args.deployment_lane}, state_namespace=staging{checked}{aws_checked}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
