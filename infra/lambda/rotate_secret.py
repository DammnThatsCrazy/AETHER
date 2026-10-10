"""
AETHER Secret Rotation Lambda

Implements the AWS Secrets Manager 4-phase rotation protocol for AETHER-managed
secrets. Invoked automatically on the rotation schedule configured in Terraform.

Secrets handled:
  aether/jwt-secret           — 30-day rotation; writes old → jwt-secret-previous
                                for zero-downtime (backend accepts both during window)
  aether/byok-encryption-key  — 30-day rotation; writes old → byok-encryption-key-previous
                                for zero-downtime; run scripts/byok_reencrypt.py after
  aether/watermark-secret-key — 90-day rotation; clean break (no _PREVIOUS needed)
  aether/canary-secret-seed   — 90-day rotation; clean break

Secrets NOT rotated here (external/on-chain sources):
  aether/stripe-secret-key        — must be rotated in Stripe Dashboard
  aether/stripe-webhook-secret    — must be rotated in Stripe Dashboard
  aether/oracle-signer-private-key — requires on-chain role update; see SECRET-ROTATION.md

Rotation protocol:
  createSecret  — generate new value, create AWSPENDING version
  setSecret     — for JWT/BYOK: copy current value to companion *-previous secret
  testSecret    — validate the AWSPENDING value is structurally correct
  finishSecret  — promote AWSPENDING → AWSCURRENT

The *-previous companion secrets are read at ECS startup via
JWT_SECRET_PREVIOUS / BYOK_ENCRYPTION_KEY_PREVIOUS env vars, letting the
backend accept tokens/keys from either the old or new secret until the next
deploy clears them.
"""

from __future__ import annotations

import base64
import logging
import os
import secrets as _secrets

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_client = None


def _sm() -> boto3.client:
    global _client
    if _client is None:
        _client = boto3.client("secretsmanager")
    return _client


# Secrets that get zero-downtime rotation via a companion "_previous" secret.
# When setSecret runs, the current AWSCURRENT value is copied here so the
# backend can still verify tokens/keys signed with the old secret.
_WITH_PREVIOUS: dict[str, str] = {
    "aether/jwt-secret":          "aether/jwt-secret-previous",
    "aether/byok-encryption-key": "aether/byok-encryption-key-previous",
}


def _generate(secret_id: str) -> str:
    """Generate an appropriate new secret value for the given secret."""
    if "byok-encryption-key" in secret_id:
        # Fernet-compatible key: 32 random bytes, URL-safe base64 encoded
        return base64.urlsafe_b64encode(os.urandom(32)).decode()
    # All other AETHER secrets: 64-char hex (256 bits of entropy)
    return _secrets.token_hex(32)


# ── Phase 1: createSecret ─────────────────────────────────────────────────────

def create_secret(secret_id: str, token: str) -> None:
    """Generate a new secret and store it as AWSPENDING (idempotent)."""
    try:
        _sm().get_secret_value(SecretId=secret_id, VersionStage="AWSPENDING")
        logger.info("createSecret: AWSPENDING already exists for %s — skipping", secret_id)
        return
    except _sm().exceptions.ResourceNotFoundException:
        pass

    new_value = _generate(secret_id)
    _sm().put_secret_value(
        SecretId=secret_id,
        ClientRequestToken=token,
        SecretString=new_value,
        VersionStages=["AWSPENDING"],
    )
    logger.info("createSecret: created AWSPENDING for %s", secret_id)


# ── Phase 2: setSecret ────────────────────────────────────────────────────────

def set_secret(secret_id: str, token: str) -> None:
    """
    For JWT and BYOK: copy the current secret value to the companion *-previous
    secret so the backend can gracefully accept the old value during the window
    between rotation and the next ECS deployment.
    """
    companion = _WITH_PREVIOUS.get(secret_id)
    if not companion:
        logger.info("setSecret: no companion secret for %s — clean-break rotation", secret_id)
        return

    current = _sm().get_secret_value(SecretId=secret_id, VersionStage="AWSCURRENT")
    current_value: str = current["SecretString"]

    try:
        _sm().put_secret_value(SecretId=companion, SecretString=current_value)
        logger.info("setSecret: updated companion %s with current value of %s", companion, secret_id)
    except _sm().exceptions.ResourceNotFoundException:
        _sm().create_secret(
            Name=companion,
            Description=f"Previous value of {secret_id} — set by rotation Lambda",
            SecretString=current_value,
        )
        logger.info("setSecret: created companion %s for %s", companion, secret_id)


# ── Phase 3: testSecret ───────────────────────────────────────────────────────

def test_secret(secret_id: str, token: str) -> None:
    """Validate the AWSPENDING value is structurally correct."""
    pending = _sm().get_secret_value(SecretId=secret_id, VersionStage="AWSPENDING")
    value: str = pending["SecretString"]

    if "byok-encryption-key" in secret_id:
        # Must decode as exactly 32 bytes (Fernet requirement)
        # Fernet keys are URL-safe base64 with optional padding
        decoded = base64.urlsafe_b64decode(value + "==")
        if len(decoded) != 32:
            raise ValueError(
                f"testSecret: invalid Fernet key length {len(decoded)} bytes for {secret_id} "
                "(expected 32)"
            )
    else:
        if len(value) < 32:
            raise ValueError(
                f"testSecret: secret value too short ({len(value)} chars) for {secret_id} "
                "(expected >= 32)"
            )

    logger.info("testSecret: passed for %s", secret_id)


# ── Phase 4: finishSecret ─────────────────────────────────────────────────────

def finish_secret(secret_id: str, token: str) -> None:
    """Promote AWSPENDING to AWSCURRENT (idempotent)."""
    metadata = _sm().describe_secret(SecretId=secret_id)
    current_version: str | None = None

    for version_id, stages in metadata.get("VersionIdsToStages", {}).items():
        if "AWSCURRENT" in stages:
            if version_id == token:
                logger.info(
                    "finishSecret: version %s is already AWSCURRENT for %s — skipping",
                    token[:8],
                    secret_id,
                )
                return
            current_version = version_id
            break

    _sm().update_secret_version_stage(
        SecretId=secret_id,
        VersionStage="AWSCURRENT",
        MoveToVersionId=token,
        RemoveFromVersionId=current_version,
    )
    logger.info(
        "finishSecret: promoted AWSPENDING → AWSCURRENT for %s (version %s)",
        secret_id,
        token[:8],
    )


# ── Entry point ───────────────────────────────────────────────────────────────

def lambda_handler(event: dict, context: object) -> None:
    step: str = event["Step"]
    secret_id: str = event["SecretId"]
    token: str = event["ClientRequestToken"]

    logger.info("rotation step=%s secret=%s token=%s...", step, secret_id, token[:8])

    metadata = _sm().describe_secret(SecretId=secret_id)

    if not metadata.get("RotationEnabled"):
        raise ValueError(f"Rotation is not enabled for secret {secret_id}")

    if token not in metadata.get("VersionIdsToStages", {}):
        raise ValueError(
            f"Token {token[:8]}... is not a pending version stage for {secret_id}. "
            "This may be a stale invocation — safe to ignore."
        )

    if step == "createSecret":
        create_secret(secret_id, token)
    elif step == "setSecret":
        set_secret(secret_id, token)
    elif step == "testSecret":
        test_secret(secret_id, token)
    elif step == "finishSecret":
        finish_secret(secret_id, token)
    else:
        raise ValueError(f"Unknown rotation step: {step!r}")
