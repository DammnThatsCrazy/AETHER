"""Mobile-gateway service — scope binding + installation orchestration."""
from __future__ import annotations

import hashlib
from typing import Optional

from repositories.installation_repo import get_installation_repository

APP_KIND = "aether"


def tenant_scope(tenant_id: str) -> str:
    return f"t:{tenant_id}"


def hash_push_token(token: str) -> str:
    """Only the hash of a push token is ever stored (dedupe); the raw token is
    encrypted in the credential platform, never persisted here or logged."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def register(
    *,
    scope: str,
    principal_id: str,
    installation_id: Optional[str],
    platform: str,
    bundle_id: str,
    environment: str,
    device_name: Optional[str],
    push_token: Optional[str],
    push_provider: Optional[str],
) -> dict:
    repo = get_installation_repository()
    installation = await repo.register(
        tenant_scope=scope,
        principal_id=principal_id,
        installation_id=installation_id,
        app_kind=APP_KIND,
        platform=platform,
        bundle_id=bundle_id,
        environment=environment,
        device_name=device_name,
    )
    subscription = None
    if push_token and push_provider:
        subscription = await repo.add_subscription(
            tenant_scope=scope,
            installation_id=installation["id"],
            principal_id=principal_id,
            platform=platform,
            provider=push_provider,
            token_hash=hash_push_token(push_token),
            environment=environment,
        )
    return {"installation": installation, "subscription": subscription}


async def get(scope: str, installation_id: str) -> Optional[dict]:
    return await get_installation_repository().get(scope, installation_id)


async def list_for_principal(scope: str, principal_id: str) -> list[dict]:
    return await get_installation_repository().list_for_principal(scope, principal_id)


async def revoke(scope: str, installation_id: str) -> Optional[dict]:
    return await get_installation_repository().revoke(scope, installation_id)


async def add_subscription(
    *, scope: str, installation_id: str, principal_id: str, platform: str,
    provider: str, push_token: str, environment: str,
) -> Optional[dict]:
    repo = get_installation_repository()
    if await repo.get(scope, installation_id) is None:
        return None
    return await repo.add_subscription(
        tenant_scope=scope, installation_id=installation_id, principal_id=principal_id,
        platform=platform, provider=provider, token_hash=hash_push_token(push_token),
        environment=environment,
    )


async def erase_principal(scope: str, principal_id: str) -> int:
    return await get_installation_repository().delete_by_principal(scope, principal_id)
