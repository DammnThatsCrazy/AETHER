"""Agent Access Intelligence — capability authority + policy APIs (PR 2, Phase B1).

Two routers:

``/v1/capability-authorizations``  grant / list / read / revoke who may invoke what.
``/v1/capability-policy``          the persisted decision log, and a non-mutating
                                   evaluation of a proposed invocation.

Both mirror the conventions of ``services/delegation/routes.py``: read
``request.state.tenant``, call ``require_permission(...)``, scope every query by
``tenant.tenant_id``, publish lifecycle events on the existing
``Topic.DELEGATION_CREATED``/``Topic.DELEGATION_REVOKED`` topics (a capability
authorization *is* a delegation, so no new event type is registered), and return
``APIResponse``.

``POST /v1/capability-policy/evaluate`` requires ``read``, not ``write`` — it
persists a policy decision + audit record but mutates no tenant resource, and gating
it on ``write`` would stop read-only enforcement callers from checking before acting.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse
from shared.events.events import Event, EventProducer, Topic
from shared.logger.logger import get_logger, metrics
from dependencies.providers import get_producer

from services.agent_access_intelligence.authority import capability_authority_service
from services.security.policy_engine import policy_engine

logger = get_logger("aether.service.agent_access_intelligence.authority_routes")

authorizations_router = APIRouter(
    prefix="/v1/capability-authorizations",
    tags=["Agent Access Intelligence"],
)

policy_router = APIRouter(
    prefix="/v1/capability-policy",
    tags=["Agent Access Intelligence"],
)


# ── Request models ────────────────────────────────────────────────────────────

class CapabilityAuthorizationGrant(BaseModel):
    agent_id: str
    capability_id: Optional[str] = Field(
        default=None, description="Authorize exactly one capability."
    )
    server_key: Optional[str] = Field(
        default=None,
        description="Authorize every capability on one server (its observed name or URL).",
    )
    starts_at: Optional[str] = None
    ends_at: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CapabilityInvocationCheck(BaseModel):
    capability_id: str
    agent_id: Optional[str] = None


# ══════════════════════════════════════════════════════════════════════════════
# CAPABILITY AUTHORIZATIONS
# ══════════════════════════════════════════════════════════════════════════════

@authorizations_router.post("")
async def grant_authorization(
    body: CapabilityAuthorizationGrant,
    request: Request,
    producer: EventProducer = Depends(get_producer),
):
    """Authorize an agent to invoke a capability (or every capability on one server).

    The permission-gated POST is itself the authorizing act — there is no separate
    pending-approval state, because nothing in the platform would transition it. A
    tenant that requires multi-party sign-off routes that through the existing x402
    approvals flow before calling this."""
    tenant = request.state.tenant
    tenant.require_permission("write")
    granted_by = tenant.user_id or tenant.tenant_id

    record = await capability_authority_service.grant(
        tenant_id=tenant.tenant_id,
        granted_by_entity_id=granted_by,
        agent_id=body.agent_id,
        capability_id=body.capability_id,
        server_key=body.server_key,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        metadata=body.metadata,
    )

    await producer.publish(Event(
        topic=Topic.DELEGATION_CREATED,
        tenant_id=tenant.tenant_id,
        source_service="agent_access_intelligence",
        payload={
            "delegation_id": record.get("authorization_id"),
            "authorization_kind": "capability",
            "grantor_entity_id": granted_by,
            "grantee_entity_id": body.agent_id,
            "scope": record.get("scope"),
            "capability_observed": record.get("capability_observed"),
        },
    ))
    metrics.increment(
        "capability_authorizations_granted",
        labels={"observed": "true" if record.get("capability_observed") else "false"},
    )
    return APIResponse(data=record).to_dict()


@authorizations_router.get("")
async def list_authorizations(
    request: Request,
    agent_id: Optional[str] = Query(default=None),
    capability_id: Optional[str] = Query(default=None),
    state: Optional[str] = Query(
        default=None,
        description="Filter on the derived state: active | revoked | expired | pending.",
    ),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    tenant = request.state.tenant
    tenant.require_permission("read")
    rows = await capability_authority_service.list(
        tenant_id=tenant.tenant_id,
        agent_id=agent_id,
        capability_id=capability_id,
        state=state,
        limit=limit,
        offset=offset,
    )
    return APIResponse(data={"items": rows, "count": len(rows)}).to_dict()


@authorizations_router.get("/{authorization_id}")
async def read_authorization(authorization_id: str, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("read")
    return APIResponse(
        data=await capability_authority_service.get(
            tenant_id=tenant.tenant_id, authorization_id=authorization_id
        )
    ).to_dict()


@authorizations_router.post("/{authorization_id}/revoke")
async def revoke_authorization(
    authorization_id: str,
    request: Request,
    producer: EventProducer = Depends(get_producer),
):
    tenant = request.state.tenant
    tenant.require_permission("write")
    revoker = tenant.user_id or tenant.tenant_id
    record = await capability_authority_service.revoke(
        tenant_id=tenant.tenant_id,
        authorization_id=authorization_id,
        revoked_by_entity_id=revoker,
    )
    await producer.publish(Event(
        topic=Topic.DELEGATION_REVOKED,
        tenant_id=tenant.tenant_id,
        source_service="agent_access_intelligence",
        payload={
            "delegation_id": authorization_id,
            "authorization_kind": "capability",
            "revoked_by": revoker,
        },
    ))
    metrics.increment("capability_authorizations_revoked")
    return APIResponse(data=record).to_dict()


# ══════════════════════════════════════════════════════════════════════════════
# CAPABILITY POLICY
# ══════════════════════════════════════════════════════════════════════════════

@policy_router.post("/evaluate")
async def evaluate_invocation(
    body: CapabilityInvocationCheck,
    request: Request,
):
    """Evaluate whether an agent may invoke a capability, without invoking it.

    Requires ``read``: the call mutates no tenant resource. It does persist a
    ``capability.invoke`` policy decision and an audit record — that is the point,
    and it is what makes ``GET /v1/capability-policy/decisions`` a real log."""
    tenant = request.state.tenant
    tenant.require_permission("read")

    facts = await capability_authority_service.resolve(
        tenant_id=tenant.tenant_id,
        agent_id=body.agent_id,
        capability_id=body.capability_id,
    )
    decision = await policy_engine.check_capability_invocation(
        actor_id=tenant.user_id or tenant.tenant_id,
        actor_type='tenant_user',
        tenant_id=tenant.tenant_id,
        capability_id=body.capability_id,
        agent_id=body.agent_id,
        capability_observed=facts["capability_observed"],
        has_active_authorization=facts["authorized"],
        authorization_id=facts["authorization_id"],
        latest_risk_level=facts["latest_risk_level"],
    )
    metrics.increment(
        "capability_invocations_evaluated",
        labels={"allowed": "true" if decision.allowed else "false"},
    )
    return APIResponse(data={
        "decision": decision.model_dump(),
        # Context, not verdict inputs: risk is reported, never silently enforced.
        "context": {
            "capability_observed": facts["capability_observed"],
            "latest_risk_level": facts["latest_risk_level"],
            "authorization_id": facts["authorization_id"],
            "authorization_reason": facts["authorization_reason"],
        },
    }).to_dict()


@policy_router.get("/decisions")
async def list_capability_decisions(
    request: Request,
    limit: int = Query(100, ge=1, le=500),
):
    """The tenant's persisted ``capability.invoke`` decisions (allows and denies)."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    # Filtered in the query, not after the fact: a post-filter over a `limit`-sized
    # page would silently return an empty log for any tenant whose most recent
    # decisions happen to be other policy keys.
    rows = await policy_engine.list_decisions(
        tenant_id=tenant.tenant_id, limit=limit, policy_key="capability.invoke",
    )
    return APIResponse(data={"items": rows, "count": len(rows)}).to_dict()
