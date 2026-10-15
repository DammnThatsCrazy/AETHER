"""Issuing an API key — the one path every key is minted through.

Split out of the route handler because the interesting part is not request
plumbing: it is what a key is *actually* granted, and that decision has to be
identical no matter which surface minted it. There are two today — self-service
(``POST /v1/me/api-keys``) and the install page
(``POST /v1/sdk/sites/{site_id}/keys``) — and a second copy of this logic is
exactly how a publishable key ends up cached without its class, or issued with
authority its record does not show. So there is one function, and both call it.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Optional

from shared.auth.auth import (
    KEY_CLASS_PUBLISHABLE,
    KEY_CLASS_SECRET,
    PUBLISHABLE_KEY_PERMISSIONS,
)
from shared.common.common import BadRequestError
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.service.me.key_issuance")

#: Prefix on a secret key. Server-side only; never appears in page HTML.
SECRET_KEY_PREFIX = "ak_"
#: Prefix on a publishable key. See ``sdk_distribution.snippet``.
PUBLISHABLE_KEY_PREFIX = "pk_"


def resolve_key_grant(
    key_class: str, permissions: list[str], site_ids: Optional[list[str]]
) -> tuple[list[str], Optional[list[str]]]:
    """Decide what a requested key is actually issued with.

    Returns ``(permissions, site_ids)``.

    A publishable key is public by construction: it ships in page HTML. So it
    is issued only with the ingestion authority it needs, and only bound to
    named sites. Refusing an unscoped publishable key is what makes the binding
    meaningful — permitting one would make it tenant-wide.
    """
    if key_class != KEY_CLASS_PUBLISHABLE:
        return list(permissions), None

    if not site_ids:
        raise BadRequestError(
            "site_ids is required for a publishable key: bind it to the "
            "sites its snippet is installed on."
        )
    return list(PUBLISHABLE_KEY_PERMISSIONS), list(site_ids)


def generate_raw_key(key_class: str) -> str:
    """Mint a raw key whose prefix states its class.

    The prefix is not decoration. A secret key pasted into a snippet works
    perfectly until somebody reads it out of View Source, so the mistake is
    silent — the loader can only warn about it if the credential itself says
    what class it is.
    """
    prefix = (
        PUBLISHABLE_KEY_PREFIX
        if key_class == KEY_CLASS_PUBLISHABLE
        else SECRET_KEY_PREFIX
    )
    return f"{prefix}{uuid.uuid4().hex[:24]}"


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


async def mint_api_key(
    *,
    tenant,
    name: str,
    key_class: str = KEY_CLASS_SECRET,
    requested_permissions: Optional[list[str]] = None,
    site_ids: Optional[list[str]] = None,
    platform: Optional[str] = None,
    source: str = "self_service",
    repo=None,
) -> dict:
    """Issue one API key and return everything the caller may see of it.

    The grant is resolved here rather than by the caller, so no surface can
    mint a key whose permissions were decided somewhere this function cannot
    see. Returns ``{"raw_key", "record", "permissions", "site_ids"}`` — the raw
    key exists only in this return value.
    """
    permissions, bound_sites = resolve_key_grant(
        key_class, list(requested_permissions or []), site_ids
    )

    raw_key = generate_raw_key(key_class)
    hashed = hash_key(raw_key)

    if repo is None:
        from repositories.repos import APIKeyRepository

        repo = APIKeyRepository()

    record = await repo.insert(hashed[:12], {
        "tenant_id": tenant.tenant_id,
        "name": name,
        "tier": tenant.api_key_tier.value,
        "permissions": permissions,
        "platform": platform,
        "key_class": key_class,
        "site_ids": bound_sites,
        "key_hash": hashed,
        "last_used_at": None,
    })

    # Register in auth cache for immediate use.
    try:
        from dependencies.providers import get_registry

        registry = get_registry()
        await registry.api_key_validator.register_api_key(
            api_key=raw_key,
            tenant_id=tenant.tenant_id,
            role="editor",
            tier=tenant.api_key_tier.value,
            # The resolved list, not what was requested: validate_async reads
            # the cache before the durable record, so caching the request would
            # give a publishable key the narrow default here and silently strip
            # the ingest authority its record grants.
            permissions=permissions,
            key_class=key_class,
            site_ids=bound_sites,
        )
    except Exception as e:  # noqa: BLE001 — a cache miss must not fail issuance
        logger.warning(f"Failed to register key in auth cache: {e}")

    metrics.increment(f"api_keys_created_{source}")
    logger.info(
        f"API key created: tenant={tenant.tenant_id} name={name!r} "
        f"class={key_class} source={source}"
    )
    return {
        "raw_key": raw_key,
        "record": record,
        "permissions": permissions,
        "site_ids": bound_sites,
    }
