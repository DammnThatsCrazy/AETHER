"""Reward tenant-webhook signing secret — credential-authority resolution.

The tenant_webhook reward rail's HMAC signing secret lives in the durable
credential authority (provider ``tenant_webhook``, slot
``webhook_signing_secret``, domain ``rewards``) — KMS-encrypted, versioned,
rotatable, with active+previous overlap so a rotation does not break in-flight
receiver verification. Rail configs and durable outbox jobs persist only a
``secret_ref``; the plaintext secret is resolved here at the narrow signing
call site, never stored in a job, an audit record, or an API response.

secret_ref format: ``credref://rewards/tenant_webhook/{environment}/webhook_signing_secret``
"""

from __future__ import annotations

import os
from typing import Optional

from shared.logger.logger import get_logger

logger = get_logger("aether.rewards.webhook_secret")

WEBHOOK_PROVIDER = "tenant_webhook"
WEBHOOK_SLOT = "webhook_signing_secret"
_REF_PREFIX = "credref://rewards/tenant_webhook/"


def _is_local_env() -> bool:
    return os.getenv("AETHER_ENV", "local").strip().lower() in ("local", "test")


def credential_environment() -> str:
    env = os.getenv("AETHER_ENV", "local").strip().lower()
    return "live" if env in ("production", "prod") else "sandbox"


def make_secret_ref(environment: Optional[str] = None) -> str:
    env = environment or credential_environment()
    return f"{_REF_PREFIX}{env}/{WEBHOOK_SLOT}"


def parse_secret_ref(ref: str) -> Optional[str]:
    """Return the environment encoded in a reward webhook secret_ref, else None."""
    if not isinstance(ref, str) or not ref.startswith(_REF_PREFIX):
        return None
    rest = ref[len(_REF_PREFIX):]
    parts = rest.split("/")
    return parts[0] if parts and parts[0] else None


async def store_secret(tenant_id: str, secret: str, *, actor: str,
                       environment: Optional[str] = None) -> str:
    """Dual-write: store a submitted signing secret in the authority (rotating
    if one already exists) and return its ``secret_ref``."""
    env = environment or credential_environment()
    from services.providers.credentials.authority import credential_authority

    try:
        existing = await credential_authority.get_active_secret(
            tenant_id, WEBHOOK_PROVIDER, env, WEBHOOK_SLOT
        )
    except Exception:
        existing = None

    if existing is None:
        pending = await credential_authority.create_pending(
            tenant_id, WEBHOOK_PROVIDER, env, WEBHOOK_SLOT, secret, created_by=actor
        )
        await credential_authority.activate(
            tenant_id, WEBHOOK_PROVIDER, env, WEBHOOK_SLOT,
            credential_version=int(pending["credential_version"]), actor=actor,
        )
    else:
        await credential_authority.rotate(
            tenant_id, WEBHOOK_PROVIDER, env, WEBHOOK_SLOT, secret, actor=actor
        )
    return make_secret_ref(env)


async def resolve_secrets(tenant_id: str, secret_ref: Optional[str]) -> list[str]:
    """Resolve a reward webhook signing secret_ref to its active + valid-previous
    secrets (rotation overlap). Empty list when unresolved — the caller must
    treat that as fail-closed."""
    if not secret_ref:
        return []
    env = parse_secret_ref(secret_ref) or credential_environment()
    from services.providers.credentials.authority import credential_authority

    try:
        return await credential_authority.get_verification_secrets(
            tenant_id, WEBHOOK_PROVIDER, env, WEBHOOK_SLOT
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "reward webhook secret resolution failed tenant=%s: %s",
            tenant_id, type(exc).__name__,
        )
        return []


async def resolve_signing_secret(
    tenant_id: str, rail_config: dict
) -> str:
    """Resolve the ONE secret to sign a delivery with.

    Order: (1) a configured ``secret_ref`` resolved through the authority
    (production path); (2) an inline ``signing_secret`` still present on a
    not-yet-migrated rail config, but ONLY in local/test — never in a deployed
    environment. Returns ``""`` when nothing resolves (fail-closed: the
    receiver's HMAC will not match and the delivery is retried/dead-lettered
    rather than silently signed with an empty key... callers should treat an
    empty result as a hard error)."""
    config = rail_config.get("config", rail_config) if isinstance(rail_config, dict) else {}
    secret_ref = config.get("secret_ref") or rail_config.get("secret_ref")
    if secret_ref:
        secrets = await resolve_secrets(tenant_id, secret_ref)
        if secrets:
            return secrets[0]
    inline = config.get("signing_secret") or rail_config.get("signing_secret")
    if inline and _is_local_env():
        return inline
    return ""


__all__ = [
    "WEBHOOK_PROVIDER",
    "WEBHOOK_SLOT",
    "credential_environment",
    "make_secret_ref",
    "parse_secret_ref",
    "resolve_secrets",
    "resolve_signing_secret",
    "store_secret",
]
