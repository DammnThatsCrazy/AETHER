"""Tenant access scope and emergency access endpoints.

Entering a tenant is an explicit, reasoned, expiring act. The ``/v1/kyber/scopes``
routes are the whole surface for it: open one scope, see the current one, list
history, close one. There is no route that widens a scope, changes its tenant,
or extends it — a different tenant or a longer window means opening a new scope,
which produces a new audit record.

``emergency_router`` (``/v1/kyber/emergency``) is the operator-facing surface of
:mod:`services.kyber.access.emergency`: request emergency root, have a *second*
operator approve it, and see what is live. It is a separate router rather than
more paths on the scope router because it is a different act with a different
approval model, and because the console mounts and audits the two separately.

Neither router is mounted in ``main.py``. Both are mounted by the Kyber console
assembly along with the rest of the Kyber plane.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, ForbiddenError, NotFoundError

from .capabilities import (
    ACTION_CLASS_FLEET_DESTRUCTIVE,
    ACTION_CLASS_READ,
    SELF_CAPABILITY,
)
from .dependencies import KyberAccessContext, require_kyber_access
from .disclosure import DisclosureLevel
from .emergency import emergency_access_service
from .scopes import (
    DEFAULT_SCOPE_MINUTES,
    MAX_SCOPE_MINUTES,
    MIN_REASON_LENGTH,
    MIN_SCOPE_MINUTES,
    access_scope_service,
)

router = APIRouter(prefix="/v1/kyber/scopes", tags=["Kyber Access"])
emergency_router = APIRouter(prefix="/v1/kyber/emergency", tags=["Kyber Emergency Access"])

#: Opening a scope is itself gated on the ability to read a tenant at all, so
#: an observer or designer cannot open one even though the route is generic.
_OPEN_CAPABILITY = "kyber.tenant.mirror.read_masked"


class OpenScopeRequest(BaseModel):
    """Body for opening a tenant access scope."""

    tenant_id: str = Field(min_length=1)
    purpose: str
    reason: str = Field(min_length=MIN_REASON_LENGTH)
    ticket_reference: Optional[str] = None
    disclosure_level: int = int(DisclosureLevel.D3_TENANT_VISIBLE)
    ttl_minutes: int = Field(default=DEFAULT_SCOPE_MINUTES, ge=MIN_SCOPE_MINUTES, le=MAX_SCOPE_MINUTES)


def _scope_body(scope: Any) -> dict:
    """Body-safe scope representation."""
    return {
        "scope_id": scope.scope_id,
        "operator_id": scope.operator_id,
        "session_id": scope.session_id,
        "device_id": scope.device_id,
        "environment": scope.environment,
        "tenant_id": scope.tenant_id,
        "purpose": scope.purpose,
        "reason": scope.reason,
        "ticket_reference": scope.ticket_reference,
        "disclosure_level": scope.disclosure_level,
        "status": scope.status,
        "entered_at": scope.entered_at,
        "expires_at": scope.expires_at,
        "exited_at": scope.exited_at,
        "revoked_at": scope.revoked_at,
    }


@router.post("")
async def open_scope(
    request: Request,
    body: OpenScopeRequest,
    context: KyberAccessContext = Depends(
        require_kyber_access(_OPEN_CAPABILITY, action_class=ACTION_CLASS_READ)
    ),
) -> dict:
    """Open a purpose-bound scope on exactly one tenant.

    The scope's disclosure ceiling is clamped to what the caller's role and the
    capability already allow, so a request cannot use the scope body to reach a
    level the role never granted.
    """
    ceiling = context.granted_disclosure
    requested = DisclosureLevel.parse(body.disclosure_level)
    level = min(ceiling, requested)

    scope = await access_scope_service.open_scope(
        operator_id=context.operator_id,
        session_id=context.session.session_id,
        device_id=context.session.device_id,
        environment=context.environment,
        tenant_id=body.tenant_id,
        purpose=body.purpose,
        reason=body.reason,
        ticket_reference=body.ticket_reference,
        disclosure_level=level,
        ttl_minutes=body.ttl_minutes,
        policy_decision_id=context.decision.policy_decision_id if context.decision else None,
    )
    return APIResponse(data=_scope_body(scope)).to_dict()


@router.get("/current")
async def current_scope(
    request: Request,
    context: KyberAccessContext = Depends(require_kyber_access(SELF_CAPABILITY)),
) -> dict:
    """The caller's live scope, or ``None`` when they are not inside one."""
    scope = await access_scope_service.current_scope(context.session.session_id)
    return APIResponse(data=_scope_body(scope) if scope else None).to_dict()


@router.get("")
async def list_scopes(
    request: Request,
    tenant_id: Optional[str] = None,
    active_only: bool = True,
    limit: int = 100,
    context: KyberAccessContext = Depends(require_kyber_access(SELF_CAPABILITY)),
) -> dict:
    """List scopes.

    Scoped to the caller unless they hold ``kyber.audit.read`` — reviewing
    another operator's tenant access is an audit capability, not a side effect
    of holding a session.
    """
    may_read_all = context.has_capability("kyber.audit.read")
    scopes = await access_scope_service.list_scopes(
        operator_id=None if may_read_all else context.operator_id,
        tenant_id=tenant_id,
        active_only=active_only,
        limit=max(1, min(limit, 500)),
    )
    return APIResponse(
        data=[_scope_body(s) for s in scopes],
        meta={"count": len(scopes), "scoped_to_caller": not may_read_all},
    ).to_dict()


@router.delete("/{scope_id}")
async def exit_scope(
    request: Request,
    scope_id: str,
    context: KyberAccessContext = Depends(require_kyber_access(SELF_CAPABILITY)),
) -> dict:
    """Close a scope the caller owns."""
    scope = await access_scope_service.get(scope_id)
    if scope is None:
        raise NotFoundError("Access scope")
    if scope.operator_id != context.operator_id:
        raise ForbiddenError("A scope may only be closed by the operator who opened it")

    closed = await access_scope_service.exit_scope(scope_id, actor_id=context.operator_id)
    return APIResponse(data=_scope_body(closed) if closed else None).to_dict()


__all__ = ["OpenScopeRequest", "router"]
