"""Focused tests for the additive staging deployment-lane contract."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/release/check_staging_lane_contract.py"


def _load():
    spec = importlib.util.spec_from_file_location("staging_lane_contract", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _config() -> dict:
    return yaml.safe_load((ROOT / "config/deployment_profiles.yaml").read_text(encoding="utf-8"))


def _complete_ecs_wiring() -> str:
    env = "\n".join(f"{{ name = \"{name}\" }}" for name in (
        "AETHER_ENV",
        "DEPLOYMENT_PROFILE",
        "AUTH0_DOMAIN",
        "AUTH0_API_AUDIENCE",
        "APP_URL",
        "CREDENTIAL_CIPHER",
        "CREDENTIAL_KMS_KEY_ID",
        "STRIPE_BILLING_ENABLED",
        "STRIPE_PRICE_ALPHA",
        "STRIPE_PRICE_BETA",
        "STRIPE_PRICE_GAMMA",
        "STRIPE_PRICE_DELTA",
        "STRIPE_PRICE_EPSILON",
        "STRIPE_PRICE_OMICRON",
        "STRIPE_PRICE_OMEGA",
        "STRIPE_CHECKOUT_SUCCESS_URL",
        "STRIPE_CHECKOUT_CANCEL_URL",
        "STRIPE_PORTAL_RETURN_URL",
    ))
    mounts = "\n".join(
        f'lookup(var.secret_arns, "{name}", "")'
        for name in (
            "stripe-secret-key",
            "stripe-webhook-secret",
            "stripe-price-alpha",
            "stripe-price-beta",
            "stripe-price-gamma",
            "stripe-price-delta",
            "stripe-price-epsilon",
            "stripe-price-omicron",
            "stripe-price-omega",
        )
    )
    return f"{env}\n{mounts}\n"


def _complete_bootstrap() -> str:
    return "\n".join(
        f'"{env}": "{secret}"'
        for env, secret in (
            ("STRIPE_SECRET_KEY", "stripe-secret-key"),
            ("STRIPE_WEBHOOK_SECRET", "stripe-webhook-secret"),
            ("STRIPE_PRICE_ALPHA", "stripe-price-alpha"),
            ("STRIPE_PRICE_BETA", "stripe-price-beta"),
            ("STRIPE_PRICE_GAMMA", "stripe-price-gamma"),
            ("STRIPE_PRICE_DELTA", "stripe-price-delta"),
            ("STRIPE_PRICE_EPSILON", "stripe-price-epsilon"),
            ("STRIPE_PRICE_OMICRON", "stripe-price-omicron"),
            ("STRIPE_PRICE_OMEGA", "stripe-price-omega"),
        )
    )


def test_full_lane_preserves_the_canonical_staging_profile():
    contract = _load()
    assert contract.validate(profile="staging", deployment_lane="full") == []
    assert contract.validate(profile="production-lean", deployment_lane="full") == [
        "deployment_lane=full is valid only with deployment_profile=staging"
    ]


def test_pilot_lane_fails_closed_when_runtime_wiring_is_incomplete():
    contract = _load()
    errors = contract.validate(
        profile="staging",
        deployment_lane="pilot",
        check_runtime_wiring=True,
        bootstrap_text=_complete_bootstrap(),
        ecs_text="",
    )
    assert errors
    assert any("STRIPE_PRICE_ALPHA" in error for error in errors)
    assert any("stripe-price-alpha" in error for error in errors)
    assert any("STRIPE_BILLING_ENABLED" in error for error in errors)
    assert any("STRIPE_CHECKOUT_SUCCESS_URL" in error for error in errors)


def test_pilot_runtime_wiring_contract_passes_only_when_all_mounts_and_env_exist():
    contract = _load()
    errors = contract.validate(
        profile="staging",
        deployment_lane="pilot",
        check_runtime_wiring=True,
        bootstrap_text=_complete_bootstrap(),
        ecs_text=_complete_ecs_wiring(),
    )
    assert errors == []


def test_pilot_is_staging_only():
    contract = _load()
    errors = contract.validate(profile="production-lean", deployment_lane="pilot")
    assert errors == ["deployment_lane=pilot is valid only with deployment_profile=staging"]


def test_lane_contract_rejects_missing_deferred_or_stripe_requirements():
    contract = _load()
    data = _config()
    pilot = data["profiles"]["staging"]["deployment_lanes"]["pilot"]
    pilot["deferred_capabilities"].remove("gcp_hosting")
    pilot["stripe_contract"]["fail_closed_if_unwired"] = False
    errors = contract.contract_errors(data, profile="staging", deployment_lane="pilot")
    assert any("deferred_capabilities" in error for error in errors)
    assert any("fail closed" in error for error in errors)


def _fake_aws_runner():
    def run(args, **kwargs):
        if "describe-secret" in args:
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps({"VersionIdsToStages": {"version": ["AWSCURRENT"]}}),
                "",
            )
        raise AssertionError(f"secret value read is forbidden: {args}")

    return run


def test_aws_price_preflight_checks_metadata_without_reading_values():
    contract = _load()
    assert contract.validate(
        profile="staging",
        deployment_lane="pilot",
        require_aws_price_secrets=True,
        runner=_fake_aws_runner(),
    ) == []
    assert len(contract.REQUIRED_POPULATED_PRICE_SECRETS) == 4


def test_aws_staging_preflight_covers_every_mounted_secret_without_values():
    contract = _load()
    assert contract.aws_staging_secret_errors(
        deployment_lane="pilot",
        runner=_fake_aws_runner(),
    ) == []
    assert contract.aws_staging_secret_errors(
        deployment_lane="full",
        runner=_fake_aws_runner(),
    ) == []
    assert len(contract.REQUIRED_PILOT_STAGING_SECRETS) == 16
    assert len(contract.REQUIRED_FULL_STAGING_SECRETS) == 14


def test_workflows_dispatch_and_record_the_same_lane_without_changing_state_key():
    lifecycle = (ROOT / ".github/workflows/staging-lifecycle.yml").read_text(encoding="utf-8")
    promote = (ROOT / ".github/workflows/terraform-promote.yml").read_text(encoding="utf-8")
    smoke = (ROOT / ".github/workflows/staging-smoke.yml").read_text(encoding="utf-8")
    delivery = (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")
    pilot_entrypoint = (ROOT / ".github/workflows/pilot-staging.yml").read_text(encoding="utf-8")

    assert "deployment_lane:" in lifecycle
    assert "options: [full, pilot]" in lifecycle
    assert lifecycle.count('-f deployment_lane="$DEPLOYMENT_LANE"') == 4
    assert "deployment_lane: ${{ steps.route.outputs.deployment_lane }}" in lifecycle

    assert "deployment_lane:" in promote
    assert "options: [full, pilot]" in promote
    assert '-var "deployment_lane=${DEPLOYMENT_LANE}"' in promote
    assert "reviewed.deployment-lane" in promote
    assert "--require-aws-price-secrets" in promote
    assert "--require-aws-staging-secrets" in promote
    assert "required_staging_secret_names" in promote
    assert "module.secrets.aws_kms_key.secrets" in promote
    assert "module.secrets.aws_kms_alias.secrets" in promote
    assert 'profiles/${PROFILE}/terraform.tfstate' in promote

    assert "deployment_lane:" in smoke
    assert "check_staging_lane_contract.py" in smoke

    assert "check_staging_lane_contract.py" in delivery
    assert "deployment_lane:" in delivery
    assert "check_staging_lane_contract.py" in pilot_entrypoint
    assert "-f profile=staging -f deployment_lane=pilot" in pilot_entrypoint
