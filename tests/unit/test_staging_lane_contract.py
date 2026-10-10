"""Focused tests for the additive staging deployment-lane contract."""

from __future__ import annotations

import importlib.util
import json
import re
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


_ANNUAL_ON = "stripe_annual_prices_enabled = true\n"
_ANNUAL_OFF = "stripe_annual_prices_enabled = false\n"
_ANNUAL_SECRETS = (
    "stripe-price-beta-annual",
    "stripe-price-gamma-annual",
    "stripe-price-delta-annual",
)


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
            ("STRIPE_PRICE_BETA_ANNUAL", "stripe-price-beta-annual"),
            ("STRIPE_PRICE_GAMMA_ANNUAL", "stripe-price-gamma-annual"),
            ("STRIPE_PRICE_DELTA_ANNUAL", "stripe-price-delta-annual"),
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
        tfvars_text=_ANNUAL_OFF,
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


def _stub_annual_runner(checked: list[str]):
    """Monthly secrets hold a value; the yearly ones are Terraform stubs."""

    def run(args, **kwargs):
        assert "describe-secret" in args, f"secret value read is forbidden: {args}"
        secret_id = args[args.index("--secret-id") + 1]
        checked.append(secret_id)
        versions = {} if secret_id.endswith("-annual") else {"version": ["AWSCURRENT"]}
        return subprocess.CompletedProcess(args, 0, json.dumps({"VersionIdsToStages": versions}), "")

    return run


def test_staging_profile_turns_on_annual_prices_and_other_profiles_do_not():
    contract = _load()
    assert contract.staging_annual_prices_enabled() is True
    assert contract.staging_annual_prices_enabled("") is False
    assert contract.staging_annual_prices_enabled(_ANNUAL_OFF) is False
    assert contract.staging_annual_prices_enabled("stripe_annual_prices_enabled = true # yearly\n") is True
    try:
        contract.staging_annual_prices_enabled(_ANNUAL_ON + _ANNUAL_OFF)
    except ValueError:
        pass
    else:
        raise AssertionError("an ambiguous double assignment must be rejected")
    # The live Stripe account is out of scope: only the staging sandbox turns
    # yearly prices on.
    for profile in (ROOT / "infra/aws/terraform/profiles").glob("*.tfvars"):
        if profile.name == "staging.tfvars":
            continue
        assert "stripe_annual_prices_enabled" not in profile.read_text(encoding="utf-8"), profile.name


def test_aws_price_preflight_fails_closed_on_annual_stubs_only_when_enabled():
    contract = _load()
    checked: list[str] = []
    errors = contract.validate(
        profile="staging",
        deployment_lane="pilot",
        require_aws_price_secrets=True,
        tfvars_text=_ANNUAL_ON,
        runner=_stub_annual_runner(checked),
    )
    assert sorted(errors) == sorted(
        f"required Stripe test price secret aether/{name} has no AWSCURRENT version"
        for name in _ANNUAL_SECRETS
    )
    assert {f"aether/{name}" for name in _ANNUAL_SECRETS} <= set(checked)

    checked.clear()
    assert contract.validate(
        profile="staging",
        deployment_lane="pilot",
        require_aws_price_secrets=True,
        tfvars_text=_ANNUAL_OFF,
        runner=_stub_annual_runner(checked),
    ) == []
    assert not any(name.endswith("-annual") for name in checked)


def test_aws_staging_preflight_requires_annual_secrets_in_pilot_when_enabled():
    contract = _load()
    errors = contract.aws_staging_secret_errors(
        deployment_lane="pilot",
        annual_prices_enabled=True,
        runner=_stub_annual_runner([]),
    )
    assert sorted(errors) == sorted(
        f"required staging secret aether/{name} has no AWSCURRENT version"
        for name in _ANNUAL_SECRETS
    )
    # Full staging does not enable Stripe billing, so it never mounts them.
    assert contract.aws_staging_secret_errors(
        deployment_lane="full",
        annual_prices_enabled=True,
        runner=_stub_annual_runner([]),
    ) == []


def test_pilot_runtime_wiring_requires_annual_mounts_when_enabled():
    contract = _load()
    errors = contract.validate(
        profile="staging",
        deployment_lane="pilot",
        check_runtime_wiring=True,
        bootstrap_text=_complete_bootstrap(),
        ecs_text=_complete_ecs_wiring(),
        tfvars_text=_ANNUAL_ON,
    )
    assert sorted(errors) == sorted(f"ECS secret mount missing aether/{name}" for name in _ANNUAL_SECRETS)
    annual_mounts = "\n".join(f'lookup(var.secret_arns, "{name}", "")' for name in _ANNUAL_SECRETS)
    assert contract.validate(
        profile="staging",
        deployment_lane="pilot",
        check_runtime_wiring=True,
        bootstrap_text=_complete_bootstrap(),
        ecs_text=_complete_ecs_wiring() + annual_mounts,
        tfvars_text=_ANNUAL_ON,
    ) == []


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
    # Every promote/delivery dispatch carries the lane; no lane binding exists
    # outside one. (A fixed count broke each time a dispatch was added.)
    dispatches = re.findall(r'dispatch_output="\$\(gh workflow run .*?2>&1\)"', lifecycle, re.S)
    assert len(dispatches) >= 4
    assert all('-f deployment_lane="$DEPLOYMENT_LANE"' in block for block in dispatches)
    assert lifecycle.count('-f deployment_lane="$DEPLOYMENT_LANE"') == len(dispatches)
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


def test_pilot_plan_requires_annual_state_owners_when_the_profile_enables_them():
    """A pilot plan must not create an empty yearly stub that tasks then mount."""
    promote = (ROOT / ".github/workflows/terraform-promote.yml").read_text(encoding="utf-8")
    start = promote.index("      - name: Create immutable reviewed plan")
    end = promote.index("      - name:", start + 1)
    block = promote[start:end]
    assert "working-directory: infra/aws/terraform" in block
    flag_gate = block.index("stripe_annual_prices_enabled[[:space:]]*=[[:space:]]*true")
    assert "profiles/staging.tfvars" in block[flag_gate:flag_gate + 200]
    owners = block[flag_gate:block.index('for name in "${required_pilot_secret_names[@]}"', flag_gate)]
    for name in _ANNUAL_SECRETS:
        assert name in owners
    assert 'required_staging_secret_names+=("${required_pilot_secret_names[@]}")' in block
    assert "run staging-state-reconcile" in block
