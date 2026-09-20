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
        "STAGING_ADMIN_API_KEY": "admin-key",
        "SMOKE_API_KEY": "smoke-key",
        "KYBER_GOOGLE_CLIENT_ID": "google-client-id",
        "KYBER_GOOGLE_CLIENT_SECRET": "google-client-secret",
        "TF_BACKEND_IMAGE_DIGEST": "sha256:" + "a" * 64,
    }


def test_pilot_accepts_complete_nonsecret_credential_shape():
    assert checker.credential_errors(lane="pilot", env=_env()) == []


def test_pilot_does_not_require_deferred_google_credentials():
    env = _env()
    env.pop("KYBER_GOOGLE_CLIENT_ID")
    env.pop("KYBER_GOOGLE_CLIENT_SECRET")
    assert checker.credential_errors(lane="pilot", env=env) == []


def test_rejects_wrong_host_and_role_without_printing_values():
    env = _env()
    env["TF_DOMAIN_NAME"] = "https://api.staging.olympuslabsml.com"
    env["AWS_DEPLOY_ROLE_ARN"] = "not-an-arn"
    errors = checker.credential_errors(lane="pilot", env=env)
    assert any("TF_DOMAIN_NAME" in error for error in errors)
    assert any("AWS_DEPLOY_ROLE_ARN" in error for error in errors)
    assert "not-an-arn" not in " ".join(errors)


def test_full_requires_google_credentials():
    env = _env()
    env.pop("KYBER_GOOGLE_CLIENT_ID")
    env.pop("KYBER_GOOGLE_CLIENT_SECRET")
    errors = checker.credential_errors(lane="full", env=env)
    assert "missing credential KYBER_GOOGLE_CLIENT_ID" in errors
    assert "missing credential KYBER_GOOGLE_CLIENT_SECRET" in errors
