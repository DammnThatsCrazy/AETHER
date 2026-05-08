"""
Aether Service — Delegation (Profile 360)

Scoped, time-bound, revocable entity-to-entity delegations. Authoritative
storage is Postgres (DelegationRepository); a background DelegationProjector
mirrors active rows to the Neptune graph as DELEGATES edges for traversal.

Endpoints:
    POST /v1/delegations                       Grant a delegation
    GET  /v1/delegations/{delegation_id}       Read a delegation
    POST /v1/delegations/{delegation_id}/revoke   Revoke
    GET  /v1/delegations                       List (filterable)
    POST /v1/delegations/validate              Internal: scope check (no execution)
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, BadRequestError, NotFoundError
from shared.events.events import Event, EventProducer, Topic
from shared.graph.graph import Edge, EdgeType, GraphClient
from shared.logger.logger import get_logger, metrics
from dependencies.providers import get_cache, get_graph, get_producer
from repositories.repos import DelegationRepository
from services.delegation.engine import DelegationEngine

logger = get_logger("aether.service.delegation")
router = APIRouter(prefix="/v1/delegations", tags=["Profile 360 / Delegation"])

# Singletons constructed lazily so the cache provider is wired up first.
_repo: Optional[DelegationRepository] = None
_engine: Optional[DelegationEngine] = None


def _get_repo(cache=Depends(get_cache)) -> DelegationRepository:
    global _repo
    if _repo is None:
        _repo = DelegationRepository(cache=cache)
    return _repo


def _get_engine(repo: DelegationRepository = Depends(_get_repo)) -> DelegationEngine:
    global _engine
    if _engine is None:
        _engine = DelegationEngine(repo)
    return _engine


# ── Request models ─────────────────────────────────────────────────────

class DelegationGrant(BaseModel):
    delegation_id: str = ""
    grantor_entity_id: str
    grantee_entity_id: str
    scope: dict[str, Any] = Field(
        ...,
        description="{actions:[], resources:[], max_amount?}; '*' allowed in actions/resources",
    )
    starts_at: Optional[str] = None
    ends_at: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ValidateRequest(BaseModel):
    grantee_entity_id: str
    action: str
    resource: str
    amount: Optional[str] = None


# ── Endpoints ──────────────────────────────────────────────────────────

@router.post("")
async def grant(
    body: DelegationGrant,
    request: Request,
    repo: DelegationRepository = Depends(_get_repo),
    graph: GraphClient = Depends(get_graph),
    producer: EventProducer = Depends(get_producer),
):
    tenant = request.state.tenant
    tenant.require_permission("write")

    if not (body.scope.get("actions") or body.scope.get("resources")):
        raise BadRequestError("Scope must define at least one action or resource")

    delegation_id = body.delegation_id or str(uuid.uuid4())
    record = await repo.grant(
        delegation_id=delegation_id,
        tenant_id=tenant.tenant_id,
        grantor_entity_id=body.grantor_entity_id,
        grantee_entity_id=body.grantee_entity_id,
        scope=body.scope,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        metadata=body.metadata,
    )

    # Synchronously project to the graph as a best-effort mirror; the
    # DelegationProjector worker re-converges on event replay.
    try:
        await graph.add_edge(Edge(
            edge_type=EdgeType.DELEGATES,
            from_vertex_id=body.grantor_entity_id,
            to_vertex_id=body.grantee_entity_id,
            properties={
                "tenant_id": tenant.tenant_id,
                "delegation_id": delegation_id,
                "valid_from": record["starts_at"],
                "valid_to": record.get("ends_at") or "",
            },
        ))
    except Exception as e:  # pragma: no cover — projection is non-authoritative
        logger.warning(f"Graph projection failed for delegation {delegation_id}: {e}")

    await producer.publish(Event(
        topic=Topic.DELEGATION_CREATED,
        tenant_id=tenant.tenant_id,
        source_service="delegation",
        payload={
            "delegation_id": delegation_id,
            "grantor_entity_id": body.grantor_entity_id,
            "grantee_entity_id": body.grantee_entity_id,
            "scope": body.scope,
        },
    ))
    metrics.increment("delegations_granted")
    return APIResponse(data=record).to_dict()


@router.get("/{delegation_id}")
async def read(
    delegation_id: str,
    request: Request,
    repo: DelegationRepository = Depends(_get_repo),
):
    tenant = request.state.tenant
    tenant.require_permission("read")
    record = await repo.find_by_id(delegation_id)
    if record is None or record.get("tenant_id") != tenant.tenant_id:
        raise NotFoundError("Delegation")
    return APIResponse(data=record).to_dict()


@router.post("/{delegation_id}/revoke")
async def revoke(
    delegation_id: str,
    request: Request,
    repo: DelegationRepository = Depends(_get_repo),
    producer: EventProducer = Depends(get_producer),
):
    tenant = request.state.tenant
    tenant.require_permission("write")
    record = await repo.find_by_id(delegation_id)
    if record is None or record.get("tenant_id") != tenant.tenant_id:
        raise NotFoundError("Delegation")
    revoker = tenant.user_id or tenant.tenant_id
    updated = await repo.revoke(delegation_id, revoked_by_entity_id=revoker)
    await producer.publish(Event(
        topic=Topic.DELEGATION_REVOKED,
        tenant_id=tenant.tenant_id,
        source_service="delegation",
        payload={"delegation_id": delegation_id, "revoked_by": revoker},
    ))
    metrics.increment("delegations_revoked")
    return APIResponse(data=updated).to_dict()


@router.get("")
async def list_delegations(
    request: Request,
    grantor: Optional[str] = None,
    grantee: Optional[str] = None,
    active: bool = True,
    limit: int = 100,
    repo: DelegationRepository = Depends(_get_repo),
):
    tenant = request.state.tenant
    tenant.require_permission("read")
    if grantee:
        rows = (
            await repo.active_for(grantee) if active
            else await repo.find_many(filters={"grantee_entity_id": grantee}, limit=limit)
        )
    elif grantor:
        rows = await repo.find_many(filters={"grantor_entity_id": grantor}, limit=limit)
    else:
        rows = await repo.find_many(filters={"tenant_id": tenant.tenant_id}, limit=limit)
    rows = [r for r in rows if r.get("tenant_id") == tenant.tenant_id][:limit]
    return APIResponse(data={"delegations": rows, "count": len(rows)}).to_dict()


@router.post("/validate")
async def validate(
    body: ValidateRequest,
    request: Request,
    engine: DelegationEngine = Depends(_get_engine),
    producer: EventProducer = Depends(get_producer),
):
    """Internal scope check; used by the agent execution path before running."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    decision = await engine.evaluate(
        grantee_entity_id=body.grantee_entity_id,
        action=body.action,
        resource=body.resource,
        amount=body.amount,
    )
    topic = Topic.DELEGATION_VALIDATED if decision.allowed else Topic.DELEGATION_REJECTED
    await producer.publish(Event(
        topic=topic,
        tenant_id=tenant.tenant_id,
        source_service="delegation",
        payload={
            "grantee_entity_id": body.grantee_entity_id,
            "action": body.action,
            "resource": body.resource,
            "amount": body.amount,
            "decision": decision.to_dict(),
        },
    ))
    metrics.increment(
        "delegations_validated",
        labels={"allowed": "true" if decision.allowed else "false"},
    )
    return APIResponse(data=decision.to_dict()).to_dict()
