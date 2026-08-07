"""Mobile-gateway service — scope binding + installation orchestration."""
from __future__ import annotations

import hashlib
from typing import Any, Optional

from shared.common.common import utc_now
from shared.temporal.instant import try_parse_instant

from repositories.installation_repo import get_installation_repository
from services.continuation import service as continuation_service
from services.mobile.config import build_mobile_config, validate_distribution_profile

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
    app_version: Optional[str] = None,
    distribution_profile: Optional[str] = None,
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
        app_version=app_version,
        distribution_profile=validate_distribution_profile(distribution_profile),
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


async def get_config(*, scope: str, installation_id: str) -> Optional[dict]:
    """Assemble the typed mobile config for an installation.

    Returns None when the installation does not exist in the tenant scope (the
    route 404s). The config's distribution_profile is the installation's
    declared profile (looked up by installation id); an install registered
    before the field existed resolves to the ``dev`` default in the response.
    """
    repo = get_installation_repository()
    installation = await repo.get(scope, installation_id)
    if installation is None:
        return None
    return build_mobile_config(
        app_kind=APP_KIND,
        environment=installation.get("environment") or "production",
        app_version=installation.get("app_version"),
        distribution_profile=installation.get("distribution_profile"),
    )


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


# ── Deep-link resolution ─────────────────────────────────────────────────────
#
# A mobile deep link carries only an opaque continuation id — never PII or a graph.
# Resolution is fail-closed: every failure that could leak the existence of a
# continuation (unknown installation, unowned installation, revoked installation,
# cross-scope / cross-plane / expired continuation) returns the SAME "unresolved"
# result, so a caller cannot probe for continuations it does not own. Only a
# resolvable continuation the caller owns can distinguish "resolved" from
# "step-up required".

_RESOLVED_UNRESOLVABLE = {"resolved": False, "reason": "unresolvable"}


def _is_expired(expires_at: Any) -> bool:
    if not expires_at:
        return False
    dt, _err = try_parse_instant(str(expires_at))
    if dt is None:
        return False
    return dt <= utc_now()


def _projection(ctx: dict) -> dict:
    """The bounded, reference-only projection returned to the client. Carries the
    summary + canonical_context references (saved_view_id / query_id / notification
    id / …) — never a materialized graph or raw payload."""
    return {
        "id": ctx.get("id"),
        "app_kind": ctx.get("app_kind"),
        "surface": ctx.get("surface"),
        "summary": ctx.get("summary"),
        "canonical_context": ctx.get("canonical_context"),
        "sensitivity": ctx.get("sensitivity", "standard"),
        "freshness": ctx.get("freshness"),
        "state_revision": ctx.get("state_revision"),
        "updated_at": ctx.get("updated_at"),
        "expires_at": ctx.get("expires_at"),
    }


async def resolve_deep_link(
    *,
    scope: str,
    principal_id: str,
    installation_id: str,
    continuation_id: str,
    elevated: bool = False,
) -> dict:
    """Resolve an opaque deep link to a bounded continuation projection.

    Ordered, fail-closed checks. All existence-revealing failures collapse to the
    same ``{"resolved": False, "reason": "unresolvable"}`` result.
    """
    repo = get_installation_repository()

    # 1) Installation must exist in scope, be owned by the caller, and not be revoked.
    installation = await repo.get(scope, installation_id)
    if (
        installation is None
        or installation.get("principal_id") != principal_id
        or installation.get("trust_state") == "revoked"
    ):
        return dict(_RESOLVED_UNRESOLVABLE)

    # 2) The installation plane must match this gateway (aether tenant plane).
    if installation.get("app_kind") != APP_KIND:
        return dict(_RESOLVED_UNRESOLVABLE)

    # 3) Continuation must resolve within the caller's scope (no cross-scope leak).
    ctx = await continuation_service.get(scope, continuation_id)
    if ctx is None:
        return dict(_RESOLVED_UNRESOLVABLE)

    # 4) Continuation plane must match; a Kyber continuation is not resolvable here.
    if ctx.get("app_kind") != APP_KIND:
        return dict(_RESOLVED_UNRESOLVABLE)

    # 5) Expired continuations are unresolvable.
    if _is_expired(ctx.get("expires_at")):
        return dict(_RESOLVED_UNRESOLVABLE)

    # 6) Restricted continuations require step-up. The caller has already proven
    #    installation ownership + scope, so surfacing "step up required" to the
    #    legitimate owner is not an existence leak.
    if ctx.get("sensitivity") == "restricted" and not elevated:
        return {"resolved": False, "reason": "step_up_required", "requires_step_up": True}

    return {"resolved": True, "continuation": _projection(ctx)}
