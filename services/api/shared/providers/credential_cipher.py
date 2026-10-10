"""Credential encryption abstraction for the durable credential authority.

Two implementations sit behind one interface:

* ``LocalCredentialCipher`` — authenticated AES-256-GCM with the credential
  encryption context bound in as AAD. Intended for local/test only and labelled
  as such; it derives its key from the configured local key material.
* ``AwsKmsEnvelopeCredentialCipher`` — production-shaped envelope encryption:
  a per-value data key from ``kms:GenerateDataKey`` under a customer-managed
  CMK, used to AES-256-GCM the value (AAD = encryption context), with the
  KMS-wrapped data key stored alongside the ciphertext and the same context
  passed to ``kms:Decrypt`` as the KMS encryption context (defence in depth).

The factory (:func:`get_credential_cipher`) **fails closed**: staging/production
must be configured with the approved KMS cipher or construction raises. Plaintext
is only ever handled here and at the single narrow authority call site that
decrypts for a provider request — never in a list/GET path, a log, an exception
message, a trace attribute, or a model serialization.
"""

from __future__ import annotations

import base64
import hashlib
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from shared.logger.logger import get_logger

logger = get_logger("aether.providers.credential_cipher")

# Bump when the on-disk blob format changes in a non-backward-compatible way.
ENCRYPTION_VERSION = "1"

# Cipher provider labels persisted with each row (also the config tokens).
LOCAL_PROVIDER = "local_aesgcm"
KMS_PROVIDER = "aws_kms_envelope"

_AAD_PREFIX = "aether-cred:v1"


class CredentialCipherError(RuntimeError):
    """A credential could not be encrypted or decrypted."""


class CredentialCipherConfigError(RuntimeError):
    """The cipher is mis-configured for the current environment (fail closed)."""


@dataclass(frozen=True)
class EncryptionContext:
    """Identity a ciphertext is cryptographically bound to.

    Bound as AES-GCM AAD (local) and as the KMS encryption context (envelope),
    so a ciphertext produced for one (tenant, provider, environment, slot,
    version) can never be decrypted while claiming a different identity — even
    if a row were mis-selected.
    """

    tenant_id: str
    provider: str
    environment: str
    slot_name: str
    credential_version: int

    def aad(self) -> bytes:
        """Canonical, order-fixed additional authenticated data."""
        return (
            f"{_AAD_PREFIX}|{self.tenant_id}|{self.provider}|{self.environment}"
            f"|{self.slot_name}|{int(self.credential_version)}"
        ).encode("utf-8")

    def kms_context(self) -> dict[str, str]:
        """KMS encryption-context map (all values must be strings)."""
        return {
            "tenant_id": self.tenant_id,
            "provider": self.provider,
            "environment": self.environment,
            "slot_name": self.slot_name,
            "credential_version": str(int(self.credential_version)),
        }


@dataclass(frozen=True)
class EncryptedBlob:
    """The persisted, non-reversible-at-rest representation of a secret."""

    encrypted_value: str        # base64(nonce || ciphertext||tag)
    encrypted_data_key: str     # base64(KMS-wrapped data key); "" for local
    encryption_provider: str
    encryption_key_id: str
    encryption_version: str
    safe_fingerprint: str

    def to_row(self) -> dict:
        """Fields to merge into a credential-version row."""
        return {
            "encrypted_value": self.encrypted_value,
            "encrypted_data_key": self.encrypted_data_key,
            "encryption_provider": self.encryption_provider,
            "encryption_key_id": self.encryption_key_id,
            "encryption_version": self.encryption_version,
            "safe_fingerprint": self.safe_fingerprint,
        }

    @classmethod
    def from_row(cls, row: dict) -> "EncryptedBlob":
        return cls(
            encrypted_value=row["encrypted_value"],
            encrypted_data_key=row.get("encrypted_data_key", ""),
            encryption_provider=row["encryption_provider"],
            encryption_key_id=row.get("encryption_key_id", ""),
            encryption_version=row.get("encryption_version", ENCRYPTION_VERSION),
            safe_fingerprint=row.get("safe_fingerprint", ""),
        )


def _fingerprint(encrypted_value: str) -> str:
    """Stable, non-reversible fingerprint of a ciphertext for safe display.

    Derived from the ciphertext (not the plaintext), so it identifies *which*
    credential version is loaded without being a confirmation oracle on the
    secret value.
    """
    digest = hashlib.sha256(encrypted_value.encode("utf-8")).hexdigest()
    return f"cf_{digest[-12:]}"


class CredentialCipher(ABC):
    """Encrypt/decrypt a credential value under a bound encryption context."""

    provider_label: str = "abstract"
    key_id: str = ""

    @abstractmethod
    def encrypt(self, plaintext: str, ctx: EncryptionContext) -> EncryptedBlob:
        ...

    @abstractmethod
    def decrypt(self, blob: EncryptedBlob, ctx: EncryptionContext) -> str:
        ...


class LocalCredentialCipher(CredentialCipher):
    """AES-256-GCM with AAD-bound context. LOCAL / TEST ONLY — never production."""

    provider_label = LOCAL_PROVIDER

    def __init__(self, local_key: str = "") -> None:
        # Derive a stable 32-byte key from whatever local material is configured.
        # A missing key is tolerated ONLY in local/test; the factory refuses to
        # build this cipher in staging/production.
        material = local_key or "aether-local-dev-credential-key"
        self._key = hashlib.sha256(material.encode("utf-8")).digest()
        self.key_id = "local:" + hashlib.sha256(self._key).hexdigest()[:8]
        logger.warning(
            "LocalCredentialCipher active (AES-GCM, non-production). "
            "Staging/production must use the AWS KMS envelope cipher."
        )

    def encrypt(self, plaintext: str, ctx: EncryptionContext) -> EncryptedBlob:
        nonce = os.urandom(12)
        ct = AESGCM(self._key).encrypt(nonce, plaintext.encode("utf-8"), ctx.aad())
        encoded = base64.b64encode(nonce + ct).decode("ascii")
        return EncryptedBlob(
            encrypted_value=encoded,
            encrypted_data_key="",
            encryption_provider=self.provider_label,
            encryption_key_id=self.key_id,
            encryption_version=ENCRYPTION_VERSION,
            safe_fingerprint=_fingerprint(encoded),
        )

    def decrypt(self, blob: EncryptedBlob, ctx: EncryptionContext) -> str:
        try:
            raw = base64.b64decode(blob.encrypted_value.encode("ascii"))
            nonce, ct = raw[:12], raw[12:]
            return AESGCM(self._key).decrypt(nonce, ct, ctx.aad()).decode("utf-8")
        except Exception as exc:  # narrow: never surface plaintext/secret in the message
            raise CredentialCipherError("local credential decryption failed") from _strip(exc)


class AwsKmsEnvelopeCredentialCipher(CredentialCipher):
    """Envelope encryption: per-value KMS data key + AES-256-GCM(value, aad=ctx)."""

    provider_label = KMS_PROVIDER

    def __init__(self, key_id: str, *, kms_client: object = None, region: str = "") -> None:
        if not key_id:
            raise CredentialCipherConfigError("AWS KMS cipher requires a key id")
        self.key_id = key_id
        self._region = region
        self._client = kms_client  # injectable for tests; lazily built otherwise

    def _kms(self):
        if self._client is None:
            import boto3  # lazy import — keeps module import cheap/offline-safe

            kwargs = {"region_name": self._region} if self._region else {}
            self._client = boto3.client("kms", **kwargs)
        return self._client

    def encrypt(self, plaintext: str, ctx: EncryptionContext) -> EncryptedBlob:
        try:
            resp = self._kms().generate_data_key(
                KeyId=self.key_id,
                KeySpec="AES_256",
                EncryptionContext=ctx.kms_context(),
            )
            data_key = resp["Plaintext"]
            wrapped = resp["CiphertextBlob"]
            nonce = os.urandom(12)
            ct = AESGCM(data_key).encrypt(nonce, plaintext.encode("utf-8"), ctx.aad())
            encoded = base64.b64encode(nonce + ct).decode("ascii")
            return EncryptedBlob(
                encrypted_value=encoded,
                encrypted_data_key=base64.b64encode(wrapped).decode("ascii"),
                encryption_provider=self.provider_label,
                encryption_key_id=self.key_id,
                encryption_version=ENCRYPTION_VERSION,
                safe_fingerprint=_fingerprint(encoded),
            )
        except CredentialCipherError:
            raise
        except Exception as exc:
            raise CredentialCipherError("KMS envelope encryption failed") from _strip(exc)

    def decrypt(self, blob: EncryptedBlob, ctx: EncryptionContext) -> str:
        try:
            wrapped = base64.b64decode(blob.encrypted_data_key.encode("ascii"))
            resp = self._kms().decrypt(
                CiphertextBlob=wrapped,
                EncryptionContext=ctx.kms_context(),
            )
            data_key = resp["Plaintext"]
            raw = base64.b64decode(blob.encrypted_value.encode("ascii"))
            nonce, ct = raw[:12], raw[12:]
            return AESGCM(data_key).decrypt(nonce, ct, ctx.aad()).decode("utf-8")
        except Exception as exc:
            raise CredentialCipherError("KMS envelope decryption failed") from _strip(exc)


def _strip(exc: BaseException) -> BaseException:
    """Return a context exception with no secret/plaintext in its message.

    Chained causes could contain provider payloads; we deliberately drop the
    original args and keep only the type name so nothing sensitive leaks into a
    traceback or an aggregated error store.
    """
    return type(exc)(type(exc).__name__)


def build_cipher(
    *,
    cipher_kind: str,
    kms_key_id: str = "",
    local_key: str = "",
    is_deploy_env: bool,
    region: str = "",
) -> CredentialCipher:
    """Pure, testable factory. ``is_deploy_env`` True for staging/production.

    Fail-closed rules:
    * a deploy environment must use the ``aws_kms`` cipher with a key id;
    * ``local`` is refused in a deploy environment.
    """
    kind = (cipher_kind or "").strip().lower()
    if kind in ("aws_kms", KMS_PROVIDER, "kms"):
        if not kms_key_id:
            raise CredentialCipherConfigError(
                "CREDENTIAL_KMS_KEY_ID must be set when the AWS KMS credential cipher is selected"
            )
        return AwsKmsEnvelopeCredentialCipher(key_id=kms_key_id, region=region)
    if kind in ("local", LOCAL_PROVIDER, ""):
        if is_deploy_env:
            raise CredentialCipherConfigError(
                "the local credential cipher is forbidden in staging/production; "
                "set CREDENTIAL_CIPHER=aws_kms and CREDENTIAL_KMS_KEY_ID"
            )
        return LocalCredentialCipher(local_key=local_key)
    raise CredentialCipherConfigError(f"unknown credential cipher kind: {cipher_kind!r}")


_cipher_singleton: CredentialCipher | None = None


def get_credential_cipher() -> CredentialCipher:
    """Process-wide cipher built from settings; fail-closed in deploy envs."""
    global _cipher_singleton
    if _cipher_singleton is None:
        from config.settings import Environment, settings

        pg = settings.provider_gateway
        is_deploy = settings.env in (Environment.STAGING, Environment.PRODUCTION)
        _cipher_singleton = build_cipher(
            cipher_kind=getattr(pg, "credential_cipher", "local"),
            kms_key_id=getattr(pg, "credential_kms_key_id", ""),
            local_key=getattr(pg, "encryption_key", ""),
            is_deploy_env=is_deploy,
            region=getattr(pg, "aws_region", "") or os.getenv("AWS_REGION", ""),
        )
    return _cipher_singleton


def reset_credential_cipher() -> None:
    """Drop the cached cipher (tests / hot config reload)."""
    global _cipher_singleton
    _cipher_singleton = None


__all__ = [
    "ENCRYPTION_VERSION",
    "LOCAL_PROVIDER",
    "KMS_PROVIDER",
    "EncryptionContext",
    "EncryptedBlob",
    "CredentialCipher",
    "LocalCredentialCipher",
    "AwsKmsEnvelopeCredentialCipher",
    "CredentialCipherError",
    "CredentialCipherConfigError",
    "build_cipher",
    "get_credential_cipher",
    "reset_credential_cipher",
]
