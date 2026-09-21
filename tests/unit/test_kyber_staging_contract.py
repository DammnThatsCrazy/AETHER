"""Tests for the secret-free Kyber deployment contract validator."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/release/check_kyber_staging_contract.py"


@pytest.fixture
def contract_module():
    spec = importlib.util.spec_from_file_location("kyber_staging_contract", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _set_valid_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TF_DOMAIN_NAME", "api.staging.olympuslabsml.com")
    monkeypatch.setenv("TF_KYBER_APP_URL", "https://kyber.staging.olympuslabsml.com")
    monkeypatch.setenv("KYBER_GOOGLE_CLIENT_ID", "staging-client.apps.googleusercontent.com")
    monkeypatch.setenv("TF_KYBER_GOOGLE_HOSTED_DOMAIN", "olympuslabs.ai")


def test_contract_binds_google_callback_to_api_and_browser_to_kyber(monkeypatch, contract_module):
    _set_valid_env(monkeypatch)

    evidence = contract_module.validate_contract(require_public_client_id=True)

    assert evidence["api_origin"] == "https://api.staging.olympuslabsml.com"
    assert evidence["kyber_origin"] == "https://kyber.staging.olympuslabsml.com"
    assert evidence["google_redirect_uri"] == (
        "https://api.staging.olympuslabsml.com/v1/kyber/auth/callback"
    )
    assert evidence["allowed_origins"] == ["https://kyber.staging.olympuslabsml.com"]
    assert evidence["google_hosted_domain"] == "olympuslabs.ai"
    assert evidence["secret_values_read"] is False


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("TF_DOMAIN_NAME", "https://api.staging.olympuslabsml.com", "bare DNS"),
        ("TF_KYBER_APP_URL", "https://kyber.staging.olympuslabsml.com/path", "HTTPS origin"),
        ("KYBER_API_BASE_URL", "https://other.staging.olympuslabsml.com", "must match"),
        (
            "KYBER_GOOGLE_REDIRECT_URI",
            "https://kyber.staging.olympuslabsml.com/v1/kyber/auth/callback",
            "API origin",
        ),
        (
            "KYBER_ALLOWED_ORIGINS",
            "https://kyber.staging.olympuslabsml.com,https://evil.example",
            "exactly",
        ),
    ],
)
def test_contract_rejects_origin_and_callback_drift(
    monkeypatch, contract_module, name, value, message
):
    _set_valid_env(monkeypatch)
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=message):
        contract_module.validate_contract(require_public_client_id=True)


def test_contract_requires_the_public_client_id_only_when_requested(monkeypatch, contract_module):
    _set_valid_env(monkeypatch)
    monkeypatch.delenv("KYBER_GOOGLE_CLIENT_ID")

    evidence = contract_module.validate_contract()
    assert evidence["google_client_id_present"] is False

    with pytest.raises(ValueError, match="KYBER_GOOGLE_CLIENT_ID"):
        contract_module.validate_contract(require_public_client_id=True)
