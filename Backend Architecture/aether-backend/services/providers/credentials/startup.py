"""Fail-closed startup validation for the credential-encryption cipher.

Mirrors ``services/noesis/startup.py``: ``validate()`` returns a list of error
strings (empty = OK) which the app lifespan turns into a hard ``RuntimeError``
in non-local environments. The rule: staging/production must run the approved
KMS envelope cipher with a key id — a deploy environment must never fall back to
the local AES-GCM cipher or run with no key configured.
"""

from __future__ import annotations


class CredentialCipherStartupValidator:
    """Validate the credential cipher configuration for the current env."""

    def validate(self) -> list[str]:
        errors: list[str] = []
        from config.settings import Environment, settings

        pg = settings.provider_gateway
        is_deploy = settings.env in (Environment.STAGING, Environment.PRODUCTION)
        if not is_deploy:
            return errors  # local/CI: the local cipher is allowed

        kind = (getattr(pg, "credential_cipher", "") or "").strip().lower()
        if kind not in ("aws_kms", "aws_kms_envelope", "kms"):
            errors.append(
                "CREDENTIAL_CIPHER must be 'aws_kms' in staging/production "
                f"(got {getattr(pg, 'credential_cipher', '')!r}); the local cipher "
                "is forbidden outside local/test"
            )
        elif not getattr(pg, "credential_kms_key_id", ""):
            errors.append(
                "CREDENTIAL_KMS_KEY_ID must be set when CREDENTIAL_CIPHER=aws_kms"
            )
        return errors


__all__ = ["CredentialCipherStartupValidator"]
