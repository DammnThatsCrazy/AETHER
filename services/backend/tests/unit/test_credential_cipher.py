"""Credential cipher: AES-GCM round-trip, AAD binding, KMS envelope, fail-closed."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from shared.providers.credential_cipher import (  # noqa: E402
    AwsKmsEnvelopeCredentialCipher,
    CredentialCipherConfigError,
    CredentialCipherError,
    EncryptedBlob,
    EncryptionContext,
    LocalCredentialCipher,
    build_cipher,
)


def _ctx(version: int = 1) -> EncryptionContext:
    return EncryptionContext("t1", "coinbase", "sandbox", "webhook_signing_secret", version)


def test_local_roundtrip_and_fingerprint():
    c = LocalCredentialCipher("unit-key")
    blob = c.encrypt("whsec_value", _ctx())
    assert c.decrypt(blob, _ctx()) == "whsec_value"
    # ciphertext + fingerprint never reveal the plaintext
    assert "whsec_value" not in blob.encrypted_value
    assert "whsec_value" not in blob.safe_fingerprint
    assert blob.encryption_provider == "local_aesgcm"


def test_local_aad_tamper_rejected():
    c = LocalCredentialCipher("unit-key")
    blob = c.encrypt("secret", _ctx(version=1))
    # any drift in the bound context must fail authentication
    for bad in (
        EncryptionContext("t2", "coinbase", "sandbox", "webhook_signing_secret", 1),
        EncryptionContext("t1", "moonpay", "sandbox", "webhook_signing_secret", 1),
        EncryptionContext("t1", "coinbase", "live", "webhook_signing_secret", 1),
        EncryptionContext("t1", "coinbase", "sandbox", "server_api_key", 1),
        _ctx(version=2),
    ):
        with pytest.raises(CredentialCipherError):
            c.decrypt(blob, bad)


class _FakeKMS:
    """Minimal in-memory KMS: remembers wrapped→(plaintext, context)."""

    def __init__(self):
        self._wrapped: dict[bytes, tuple[bytes, dict]] = {}
        self._n = 0

    def generate_data_key(self, KeyId, KeySpec, EncryptionContext):  # noqa: N803
        self._n += 1
        plaintext = os.urandom(32)
        wrapped = f"wrapped-{self._n}".encode()
        self._wrapped[wrapped] = (plaintext, dict(EncryptionContext))
        return {"Plaintext": plaintext, "CiphertextBlob": wrapped}

    def decrypt(self, CiphertextBlob, EncryptionContext):  # noqa: N803
        plaintext, ctx = self._wrapped[CiphertextBlob]
        # KMS enforces the encryption context on decrypt.
        if ctx != dict(EncryptionContext):
            raise ValueError("InvalidCiphertextException: encryption context mismatch")
        return {"Plaintext": plaintext}


def test_kms_envelope_roundtrip_and_context_enforced():
    kms = _FakeKMS()
    c = AwsKmsEnvelopeCredentialCipher(key_id="arn:aws:kms:key/abc", kms_client=kms)
    blob = c.encrypt("live_secret", _ctx())
    assert blob.encryption_provider == "aws_kms_envelope"
    assert blob.encrypted_data_key  # wrapped key stored
    assert c.decrypt(blob, _ctx()) == "live_secret"
    # a mismatched context is rejected at the KMS layer
    with pytest.raises(CredentialCipherError):
        c.decrypt(blob, _ctx(version=99))
    # blob survives a row round-trip
    row = blob.to_row()
    assert c.decrypt(EncryptedBlob.from_row(row), _ctx()) == "live_secret"


def test_factory_fails_closed_in_deploy_env():
    with pytest.raises(CredentialCipherConfigError):
        build_cipher(cipher_kind="local", is_deploy_env=True)
    with pytest.raises(CredentialCipherConfigError):
        build_cipher(cipher_kind="aws_kms", kms_key_id="", is_deploy_env=True)
    # local is fine outside deploy envs; aws_kms with a key id is fine anywhere
    assert isinstance(build_cipher(cipher_kind="local", is_deploy_env=False), LocalCredentialCipher)
    assert isinstance(
        build_cipher(cipher_kind="aws_kms", kms_key_id="k", is_deploy_env=True),
        AwsKmsEnvelopeCredentialCipher,
    )
