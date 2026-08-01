"""Continuation-plane service — scope binding + repository orchestration.

Every operation is bound to the authenticated scope. Tenant (Aether) callers use
``t:{tenant_id}``; operator (Kyber) callers use ``o:{operator_id}``. The service
never trusts a client-supplied tenant/principal/app_kind — the route passes the
authenticated values and they overwrite whatever the body carried.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from shared.common.common import utc_now

from repositories.continuation_repo import get_continuation_repository, new_token
from shared.continuation.models import (
    ContinuationContext,
    ContinuationSelection,
    SELECTION_MODES,
)


def tenant_scope(tenant_id: str) -> str:
    return f"t:{tenant_id}"


def operator_scope(operator_id: str) -> str:
    return f"o:{operator_id}"


def _new_id() -> str:
    return f"cont_{uuid.uuid4().hex}"


async def create(
    *,
    scope: str,
    principal_id: str,
    app_kind: str,
    tenant_id: Optional[str],
    body: ContinuationContext,
    idempotency_key: Optional[str] = None,
) -> dict:
    """Create a continuation, forcing identity onto the authenticated caller."""
    ctx = body.model_copy(update={
        "id": body.id or _new_id(),
        "principal_id": principal_id,
        "app_kind": app_kind,
        "tenant_id": tenant_id,
        "state_revision": 0,
        "updated_at": utc_now().isoformat(),
    })
    repo = get_continuation_repository()
    return await repo.create(
        tenant_scope=scope,
        continuation_id=ctx.id,
        principal_id=principal_id,
        app_kind=app_kind,
        source_client=ctx.source_client,
        surface=ctx.surface,
        sensitivity=ctx.sensitivity,
        freshness=ctx.freshness,
        context=ctx.model_dump(mode="json"),
        idempotency_key=idempotency_key,
        expires_at=ctx.expires_at,
    )


async def get(scope: str, continuation_id: str) -> Optional[dict]:
    return await get_continuation_repository().get_scoped(scope, continuation_id)


async def list_recent(scope: str, principal_id: str, limit: int = 25) -> list[dict]:
    return await get_continuation_repository().list_recent(scope, principal_id, limit)


async def update(
    *,
    scope: str,
    continuation_id: str,
    expected_revision: int,
    body: ContinuationContext,
) -> Optional[dict]:
    """Compare-and-swap update. Returns None when absent in scope; the repository
    raises ConflictError on a state_revision mismatch (→ HTTP 409)."""
    ctx = body.model_copy(update={"id": continuation_id})
    repo = get_continuation_repository()
    return await repo.cas_update(
        tenant_scope=scope,
        continuation_id=continuation_id,
        expected_revision=expected_revision,
        context=ctx.model_dump(mode="json"),
        surface=ctx.surface,
        sensitivity=ctx.sensitivity,
        freshness=ctx.freshness,
        expires_at=ctx.expires_at if ctx.expires_at is not None else "__unset__",
    )


async def delete(scope: str, continuation_id: str) -> bool:
    return await get_continuation_repository().delete_scoped(scope, continuation_id)


async def handoff(
    *,
    scope: str,
    principal_id: str,
    continuation_id: str,
    mode: str,
    resource_ids: Optional[list[str]] = None,
    saved_view_id: Optional[str] = None,
    query_id: Optional[str] = None,
    as_of: Any = None,
    expires_at: Any = None,
) -> Optional[dict]:
    """Mint the backend selection token for a continuation (decision-log D4).

    Returns None when the continuation is absent in scope. The token resolves the
    same subject set for both Noesis exact-handoff and mobile deep-links.
    """
    if mode not in SELECTION_MODES:
        raise ValueError(f"mode must be one of {SELECTION_MODES}")
    repo = get_continuation_repository()
    existing = await repo.get_scoped(scope, continuation_id)
    if existing is None:
        return None
    selection = {
        "continuation_id": continuation_id,
        "resource_ids": resource_ids,
        "saved_view_id": saved_view_id,
        "query_id": query_id,
    }
    return await repo.create_selection(
        tenant_scope=scope,
        principal_id=principal_id,
        mode=mode,
        selection=selection,
        as_of=as_of,
        expires_at=expires_at,
    )


async def resolve_selection(scope: str, token: str) -> Optional[dict]:
    return await get_continuation_repository().get_selection(scope, token)


async def erase_principal(scope: str, principal_id: str) -> int:
    """DSR hook — remove every continuation + selection for a subject."""
    return await get_continuation_repository().delete_by_principal(scope, principal_id)
