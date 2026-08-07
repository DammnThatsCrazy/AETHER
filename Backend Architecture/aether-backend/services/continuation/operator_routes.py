"""Kyber operator continuation API — /v1/kyber/continuations (operator / Kyber).

The SAME durable continuation plane as the tenant router, exposed to Kyber
operators and scoped to ``operator:{operator_id}``. It reuses
``ContinuationService``, the same ``continuations`` /
``continuation_selections`` tables and the same ``client_sync`` feed — there is
no second continuation store. The operator identity is always taken from the
authenticated Kyber session (``KyberAccessContext.operator_id``), never from the
request body.

Flag-gated INSIDE every handler via ``settings.continuation.enabled``
(``AETHER_CONTINUATION_ENABLED``, default OFF): when off the surface answers 404,
indistinguishable from an unmounted route — the same gate the tenant router uses.
Every route additionally authorizes through ``require_kyber_access`` with the
self capability, so only a live, device-bound workforce session can reach the
surface, and the operator may only ever read, update or delete their own
continuations (the row's ``principal_id`` must equal the authenticated
``operator_id``).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Path, Query

from config.settings import settings
from shared.common.common import APIResponse, NotFoundError
from shared.logger.logger import get_logger, metrics

from services.client_sync.emitter import enqueue_sync_change
from services.continuation import service as continuation_service
from services.continuation.routes import (
    ContinuationInput,
    ContinuationUpdate,
    HandoffRequest,
)
from services.kyber.access.capabilities import SELF_CAPABILITY
from services.kyber.access.dependencies import (
    KyberAccessContext,
    require_kyber_access,
)
from shared.continuation.models import ContinuationContext

logger = get_logger("aether.service.continuation.operator")
operator_router = APIRouter(prefix="/v1/kyber/continuations", tags=["Kyber Continuations"])

#: Operator continuations are Kyber-plane rows; the tenant plane uses "aether".
APP_KIND = "kyber"


def _require_enabled() -> None:
    if not settings.continuation.enabled:
        raise NotFoundError("continuation plane (feature not enabled)")


def _build_context(inp: ContinuationInput, principal_id: str) -> ContinuationContext:
    from shared.common.common import utc_now
    return ContinuationContext(
        id=inp.id or "",  # empty → the service mints a fresh id (create)
        principal_id=principal_id,
        tenant_id=None,  # operator continuations are not tenant-bound
        app_kind=APP_KIND,
        source_client=inp.source_client,
        surface=inp.surface,
        resource_references=inp.resource_references,
        canonical_context=inp.canonical_context,
        summary=inp.summary,
        sensitivity=inp.sensitivity,
        freshness=inp.freshness,
        expires_at=inp.expires_at,
        updated_at=utc_now().isoformat(),
    )


async def _require_owned(operator_id: str, continuation_id: str) -> dict:
    """Return the operator's own continuation; 404 for an absent OR foreign row.

    Scope binding (``o:{operator_id}``) already keeps another operator's rows
    out of reach; the ``principal_id`` equality check is the second, independent
    guard so a row that somehow carries a different principal reads as absent,
    exactly like the tenant router's not-found semantics.
    """
    row = await continuation_service.get(
        continuation_service.operator_scope(operator_id), continuation_id
    )
    if row is None or row.get("principal_id") != operator_id:
        raise NotFoundError("continuation not found")
    return row


# ── Handlers ──────────────────────────────────────────────────────────────────

@operator_router.post("")
async def create_operator_continuation(
    payload: ContinuationInput,
    idempotency_key: Optional[str] = Query(default=None),
    context: KyberAccessContext = Depends(require_kyber_access(SELF_CAPABILITY)),
) -> APIResponse:
    _require_enabled()
    operator_id = context.operator_id
    result = await continuation_service.create(
        scope=continuation_service.operator_scope(operator_id),
        principal_id=operator_id,
        app_kind=APP_KIND,
        tenant_id=None,
        body=_build_context(payload, operator_id),
        idempotency_key=idempotency_key,
    )
    metrics.increment(
        "continuation_created_total", labels={"replayed": str(result.get("replayed", False))}
    )
    await enqueue_sync_change(
        scope_key=continuation_service.operator_scope(operator_id),
        principal_id=operator_id,
        change_type="continuation_changed",
        resource_kind="continuation",
        resource_id=result.get("id"),
        revision=str(result.get("state_revision", 0)),
    )
    return APIResponse(data=result)


@operator_router.get("/recent")
async def recent_operator_continuations(
    limit: int = Query(default=25, ge=1, le=100),
    context: KyberAccessContext = Depends(require_kyber_access(SELF_CAPABILITY)),
) -> APIResponse:
    _require_enabled()
    operator_id = context.operator_id
    rows = await continuation_service.list_recent(
        continuation_service.operator_scope(operator_id), operator_id, limit
    )
    return APIResponse(data={"continuations": rows})


@operator_router.get("/{continuation_id}")
async def get_operator_continuation(
    continuation_id: str = Path(...),
    context: KyberAccessContext = Depends(require_kyber_access(SELF_CAPABILITY)),
) -> APIResponse:
    _require_enabled()
    row = await continuation_service.get(
        continuation_service.operator_scope(context.operator_id), continuation_id
    )
    if row is None:
        raise NotFoundError("continuation not found")
    return APIResponse(data=row)


@operator_router.patch("/{continuation_id}")
async def update_operator_continuation(
    payload: ContinuationUpdate,
    continuation_id: str = Path(...),
    context: KyberAccessContext = Depends(require_kyber_access(SELF_CAPABILITY)),
) -> APIResponse:
    _require_enabled()
    operator_id = context.operator_id
    await _require_owned(operator_id, continuation_id)
    ctx = _build_context(payload, operator_id).model_copy(update={"id": continuation_id})
    # ConflictError (state_revision mismatch) propagates → HTTP 409.
    row = await continuation_service.update(
        scope=continuation_service.operator_scope(operator_id),
        continuation_id=continuation_id,
        expected_revision=payload.expected_state_revision,
        body=ctx,
    )
    if row is None:
        raise NotFoundError("continuation not found")
    metrics.increment("continuation_updated_total")
    await enqueue_sync_change(
        scope_key=continuation_service.operator_scope(operator_id),
        principal_id=operator_id,
        change_type="continuation_changed",
        resource_kind="continuation",
        resource_id=continuation_id,
        revision=str(row.get("state_revision", 0)),
    )
    return APIResponse(data=row)


@operator_router.post("/{continuation_id}/handoff")
async def handoff_operator_continuation(
    payload: HandoffRequest,
    continuation_id: str = Path(...),
    context: KyberAccessContext = Depends(require_kyber_access(SELF_CAPABILITY)),
) -> APIResponse:
    _require_enabled()
    operator_id = context.operator_id
    await _require_owned(operator_id, continuation_id)
    selection = await continuation_service.handoff(
        scope=continuation_service.operator_scope(operator_id),
        principal_id=operator_id,
        continuation_id=continuation_id,
        mode=payload.mode,
        resource_ids=payload.resource_ids,
        saved_view_id=payload.saved_view_id,
        query_id=payload.query_id,
        as_of=payload.as_of,
        expires_at=payload.expires_at,
    )
    if selection is None:
        raise NotFoundError("continuation not found")
    metrics.increment("continuation_handoff_total", labels={"mode": payload.mode})
    return APIResponse(data=selection)


@operator_router.delete("/{continuation_id}")
async def delete_operator_continuation(
    continuation_id: str = Path(...),
    context: KyberAccessContext = Depends(require_kyber_access(SELF_CAPABILITY)),
) -> APIResponse:
    _require_enabled()
    operator_id = context.operator_id
    await _require_owned(operator_id, continuation_id)
    deleted = await continuation_service.delete(
        continuation_service.operator_scope(operator_id), continuation_id
    )
    if not deleted:
        raise NotFoundError("continuation not found")
    await enqueue_sync_change(
        scope_key=continuation_service.operator_scope(operator_id),
        principal_id=operator_id,
        change_type="continuation_changed",
        resource_kind="continuation",
        resource_id=continuation_id,
    )
    return APIResponse(data={"deleted": True, "id": continuation_id})
