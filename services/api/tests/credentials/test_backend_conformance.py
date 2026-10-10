"""Cross-backend conformance: identical interface semantics."""
from __future__ import annotations

import pytest

from shared.certification.readiness import CredentialReadiness
from shared.credentials.in_memory import InMemoryCredentialBackend
from shared.credentials.interface import CredentialBackend, CredentialBackendNotConfigured
from shared.credentials.local_encrypted import LocalEncryptedCredentialBackend
from shared.credentials.store import CredentialStore

_FAKE = "sk-test-0000"


def _make(name: str) -> CredentialBackend:
    if name == "in_memory":
        return InMemoryCredentialBackend(store={})
    if name == "local_encrypted":
        return LocalEncryptedCredentialBackend(store=CredentialStore(rows={}))
    raise AssertionError(name)


@pytest.mark.parametrize("name", ["in_memory", "local_encrypted"])
@pytest.mark.asyncio
async def test_lifecycle_semantics_are_identical(name):
    b = _make(name)

    md = await b.create("t1", "r1", _FAKE)
    assert md.version == 1
    assert md.status == CredentialReadiness.PARTNER_LIVE
    assert md.credential_type == "api_key"

    cred = await b.get("t1", "r1")
    assert cred.api_key.get_secret_value() == _FAKE

    md2 = await b.rotate("t1", "r1", "sk-test-1111")
    assert md2.version == 2
    assert (await b.get("t1", "r1")).api_key.get_secret_value() == "sk-test-1111"

    assert await b.revoke("t1", "r1") is True
    assert await b.get("t1", "r1") is None
    revoked_md = await b.metadata("t1", "r1")
    assert revoked_md.status == CredentialReadiness.DISABLED

    assert await b.delete("t1", "r1") is True
    assert await b.metadata("t1", "r1") is None


@pytest.mark.parametrize("name", ["in_memory", "local_encrypted"])
@pytest.mark.asyncio
async def test_absent_ref_returns_none(name):
    b = _make(name)
    assert await b.get("t1", "missing") is None
    assert await b.metadata("t1", "missing") is None
    assert await b.revoke("t1", "missing") is False
    assert await b.delete("t1", "missing") is False
    assert await b.list("t1") == []


@pytest.mark.asyncio
async def test_aws_backend_raises_when_unconfigured(monkeypatch):
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    from shared.credentials.aws_secrets_manager import (
        AwsSecretsManagerCredentialBackend,
    )

    b = AwsSecretsManagerCredentialBackend(region=None)
    with pytest.raises(CredentialBackendNotConfigured):
        await b.create("t1", "r1", _FAKE)
