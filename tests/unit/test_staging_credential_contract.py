"""Tests for the non-secret staging credential contract."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/release/check_staging_credential_contract.py"
SPEC = importlib.util.spec_from_file_location("staging_credential_contract", SCRIPT)
assert SPEC and SPEC.loader
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


def _env() -> dict[str, str]:
    return {
        **{name: f"arn:aws:iam::544471417928:role/{name}" for name in checker.ROLE_VARS},
        "TF_STATE_BUCKET": "aether-staging-terraform-state-olympus",
        "TF_LOCK_TABLE": "aether-staging-terraform-lock",
        "TF_ACM_CERTIFICATE_ARN": "arn:aws:acm:us-east-1:544471417928:certificate/00000000-0000-0000-0000-000000000000",
        "TF_DOMAIN_NAME": "api.staging.olympuslabsml.com",
        "TF_ALERT_EMAIL": "ops@olympuslabsml.com",
        "TF_AUTH0_DOMAIN": "olympus.us.auth0.com",
        "TF_AUTH0_MANAGEMENT_CLIENT_ID": "client-id",
        "TF_AUTH0_MANAGEMENT_CLIENT_SECRET": "client-secret",
        "TF_AMPLIFY_GITHUB_ACCESS_TOKEN": "github_pat_example",
        "TF_AETHER_APP_URL": "https://app.staging.olympuslabsml.com",
        "TF_KYBER_APP_URL": "https://kyber.staging.olympuslabsml.com",
        "STAGING_ADMIN_API_KEY": "ak_" + "a" * 24,
        "SMOKE_API_KEY": "smoke-key",
        "KYBER_GOOGLE_CLIENT_ID": "google-client-id",
        "KYBER_GOOGLE_CLIENT_SECRET": "google-client-secret",
        "TF_BACKEND_IMAGE_DIGEST": "sha256:" + "a" * 64,
    }


def test_pilot_accepts_complete_nonsecret_credential_shape():
    assert checker.credential_errors(lane="pilot", purpose="delivery", env=_env()) == []


def test_pilot_infrastructure_plan_does_not_require_post_bootstrap_runtime_keys():
    env = _env()
    env.pop("STAGING_ADMIN_API_KEY")
    env.pop("SMOKE_API_KEY")
    assert checker.credential_errors(lane="pilot", purpose="infrastructure", env=env) == []

    # Infrastructure shape validation must ignore stale runtime values too;
    # the strict runtime gate below is responsible for rejecting them.
    env["STAGING_ADMIN_API_KEY"] = "bootstrap-token-not-an-api-key"
    assert checker.credential_errors(lane="pilot", purpose="infrastructure", env=env) == []


def test_pilot_terraform_plan_accepts_missing_or_stale_admin_key():
    env = _env()
    env.pop("STAGING_ADMIN_API_KEY")
    assert checker.credential_errors(lane="pilot", purpose="terraform-plan", env=env) == []

    env["STAGING_ADMIN_API_KEY"] = "bootstrap-token-not-an-api-key"
    assert checker.credential_errors(lane="pilot", purpose="terraform-plan", env=env) == []


def test_full_terraform_plan_requires_a_durable_admin_key():
    env = _env()
    assert checker.credential_errors(lane="full", purpose="terraform-plan", env=env) == []

    env.pop("STAGING_ADMIN_API_KEY")
    errors = checker.credential_errors(lane="full", purpose="terraform-plan", env=env)
    assert "missing credential STAGING_ADMIN_API_KEY" in errors

    env["STAGING_ADMIN_API_KEY"] = "bootstrap-token-not-an-api-key"
    errors = checker.credential_errors(lane="full", purpose="terraform-plan", env=env)
    assert any("STAGING_ADMIN_API_KEY" in error for error in errors)


def test_pilot_infrastructure_plan_still_requires_common_provisioning_credentials():
    env = _env()
    env.pop("STAGING_ADMIN_API_KEY")
    env.pop("SMOKE_API_KEY")
    env.pop("AWS_TERRAFORM_PLAN_ROLE_ARN")
    errors = checker.credential_errors(lane="pilot", purpose="infrastructure", env=env)
    assert "missing credential AWS_TERRAFORM_PLAN_ROLE_ARN" in errors


def test_pilot_does_not_require_deferred_google_credentials():
    env = _env()
    env.pop("KYBER_GOOGLE_CLIENT_ID")
    env.pop("KYBER_GOOGLE_CLIENT_SECRET")
    assert checker.credential_errors(lane="pilot", purpose="delivery", env=env) == []


def test_rejects_wrong_host_and_role_without_printing_values():
    env = _env()
    env["TF_DOMAIN_NAME"] = "https://api.staging.olympuslabsml.com"
    env["AWS_DEPLOY_ROLE_ARN"] = "not-an-arn"
    errors = checker.credential_errors(lane="pilot", purpose="delivery", env=env)
    assert any("TF_DOMAIN_NAME" in error for error in errors)
    assert any("AWS_DEPLOY_ROLE_ARN" in error for error in errors)
    assert "not-an-arn" not in " ".join(errors)


def test_rejects_the_bootstrap_token_or_other_non_api_key_as_staging_admin_key():
    env = _env()
    env["STAGING_ADMIN_API_KEY"] = "bootstrap-token-value"
    errors = checker.credential_errors(lane="full", purpose="rehearsal", env=env)
    assert any("STAGING_ADMIN_API_KEY" in error for error in errors)


def test_full_requires_google_credentials():
    env = _env()
    env.pop("KYBER_GOOGLE_CLIENT_ID")
    env.pop("KYBER_GOOGLE_CLIENT_SECRET")
    errors = checker.credential_errors(lane="full", purpose="delivery", env=env)
    assert "missing credential KYBER_GOOGLE_CLIENT_ID" in errors
    assert "missing credential KYBER_GOOGLE_CLIENT_SECRET" in errors


def test_full_delivery_requires_smoke_key_in_addition_to_google_credentials():
    env = _env()
    env.pop("SMOKE_API_KEY")
    errors = checker.credential_errors(lane="full", purpose="delivery", env=env)
    assert "missing credential SMOKE_API_KEY" in errors
    assert not any("KYBER_GOOGLE" in error for error in errors)


def test_full_infrastructure_does_not_require_runtime_smoke_or_admin_keys():
    env = _env()
    env.pop("SMOKE_API_KEY")
    env.pop("STAGING_ADMIN_API_KEY")
    assert checker.credential_errors(lane="full", purpose="infrastructure", env=env) == []


def test_full_rehearsal_requires_durable_admin_key():
    env = _env()
    env.pop("STAGING_ADMIN_API_KEY")
    errors = checker.credential_errors(lane="full", purpose="rehearsal", env=env)
    assert "missing credential STAGING_ADMIN_API_KEY" in errors


def test_full_smoke_requires_smoke_key():
    env = _env()
    env.pop("SMOKE_API_KEY")
    errors = checker.credential_errors(lane="full", purpose="smoke", env=env)
    assert "missing credential SMOKE_API_KEY" in errors


def test_full_infrastructure_plan_still_requires_google_credentials():
    env = _env()
    env.pop("KYBER_GOOGLE_CLIENT_ID")
    errors = checker.credential_errors(lane="full", purpose="infrastructure", env=env)
    assert "missing credential KYBER_GOOGLE_CLIENT_ID" in errors


def test_pilot_rehearsal_can_bootstrap_admin_key_after_readiness():
    env = _env()
    env.pop("SMOKE_API_KEY")
    env.pop("STAGING_ADMIN_API_KEY")
    assert checker.credential_errors(lane="pilot", purpose="rehearsal", env=env) == []

    # A stale pre-bootstrap value is not a preflight blocker in the pilot lane;
    # the live /v1/me and one-time marker checks decide whether it can be reused.
    env["STAGING_ADMIN_API_KEY"] = "bootstrap-token-value"
    assert checker.credential_errors(lane="pilot", purpose="rehearsal", env=env) == []


def test_full_rehearsal_still_requires_a_shape_valid_durable_admin_key():
    env = _env()
    env.pop("STAGING_ADMIN_API_KEY")
    errors = checker.credential_errors(lane="full", purpose="rehearsal", env=env)
    assert "missing credential STAGING_ADMIN_API_KEY" in errors

    env["STAGING_ADMIN_API_KEY"] = "bootstrap-token-value"
    errors = checker.credential_errors(lane="full", purpose="rehearsal", env=env)
    assert any("STAGING_ADMIN_API_KEY" in error for error in errors)


def test_pilot_smoke_requires_only_its_fixed_smoke_key():
    env = _env()
    env.pop("STAGING_ADMIN_API_KEY")
    assert checker.credential_errors(lane="pilot", purpose="smoke", env=env) == []

    env.pop("SMOKE_API_KEY")
    errors = checker.credential_errors(lane="pilot", purpose="smoke", env=env)
    assert "missing credential SMOKE_API_KEY" in errors


def test_pilot_delivery_requires_smoke_key_but_not_admin_key():
    env = _env()
    env.pop("STAGING_ADMIN_API_KEY")
    assert checker.credential_errors(lane="pilot", purpose="delivery", env=env) == []

    env.pop("SMOKE_API_KEY")
    errors = checker.credential_errors(lane="pilot", purpose="delivery", env=env)
    assert "missing credential SMOKE_API_KEY" in errors


def test_unknown_credential_purpose_fails_closed():
    assert checker.credential_errors(lane="pilot", purpose="plan", env=_env()) == [
        "credential purpose must be one of infrastructure, terraform-plan, delivery, smoke, or rehearsal, got 'plan'"
    ]
