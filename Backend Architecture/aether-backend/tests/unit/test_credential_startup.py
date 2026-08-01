"""Fail-closed credential-cipher startup validation per environment."""

from __future__ import annotations

import os

os.environ.setdefault("AETHER_ENV", "local")

from config.settings import Environment, ProviderGatewayConfig, settings  # noqa: E402
from services.providers.credentials.startup import (  # noqa: E402
    CredentialCipherStartupValidator,
)


def test_local_env_allows_local_cipher(monkeypatch):
    monkeypatch.setattr(settings, "env", Environment.LOCAL)
    assert CredentialCipherStartupValidator().validate() == []


def test_staging_rejects_local_cipher(monkeypatch):
    monkeypatch.setattr(settings, "env", Environment.STAGING)
    monkeypatch.setattr(
        settings, "provider_gateway",
        ProviderGatewayConfig(credential_cipher="local", credential_kms_key_id=""),
    )
    errs = CredentialCipherStartupValidator().validate()
    assert errs and any("CREDENTIAL_CIPHER" in e for e in errs)


def test_staging_kms_requires_key(monkeypatch):
    monkeypatch.setattr(settings, "env", Environment.STAGING)
    monkeypatch.setattr(
        settings, "provider_gateway",
        ProviderGatewayConfig(credential_cipher="aws_kms", credential_kms_key_id=""),
    )
    errs = CredentialCipherStartupValidator().validate()
    assert errs and any("CREDENTIAL_KMS_KEY_ID" in e for e in errs)


def test_staging_kms_with_key_ok(monkeypatch):
    monkeypatch.setattr(settings, "env", Environment.STAGING)
    monkeypatch.setattr(
        settings, "provider_gateway",
        ProviderGatewayConfig(credential_cipher="aws_kms", credential_kms_key_id="arn:aws:kms:key/x"),
    )
    assert CredentialCipherStartupValidator().validate() == []
