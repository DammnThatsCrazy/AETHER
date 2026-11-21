"""
User/Org-owned agent declarations — Profile 360 layer.

This is distinct from the existing AgentController workers (WEB_CRAWLER,
ENTITY_RESOLVER, …) which are *system* workers. A tenant declares its own
agent here: config (model, tools, constraints, risk_tolerance) and explicit
ownership (owner_entity_id).

Aether is observation-only (ADR-012). It never admits, runs, or gates an
agent's action, and it never calls an agent's tools or resources. What the
agent actually does arrives as observed agent events through the canonical
ingestion spine (``POST /v1/batch``). Execution rows written before this change
remain readable as history.

Endpoints (mounted under /v1/agents — distinct from the singular /v1/agent):
    POST  /v1/agents                                  Declare an agent
    GET   /v1/agents/{agent_id}
    PATCH /v1/agents/{agent_id}
    GET   /v1/agents/{agent_id}/executions            Historical execution rows
    GET   /v1/agents/{agent_id}/executions/{execution_id}
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, ConflictError, NotFoundError
from shared.graph.graph import Edge, EdgeType, GraphClient, Vertex, VertexType
from shared.graph.mutation_gateway import GraphMutationGateway
from shared.graph.mutation_intents import edge_intent, vertex_intent
from shared.logger.logger import get_logger, metrics
from dependencies.providers import get_graph
from repositories.repos import (
    AgentConfigRepository,
    AgentExecutionRepository,
)

logger = get_logger("aether.service.agent.user")
router = APIRouter(prefix="/v1/agents", tags=["Profile 360 / Agents"])

_configs = AgentConfigRepository()
_executions = AgentExecutionRepository()


# ── Request models ─────────────────────────────────────────────────────

class AgentRegister(BaseModel):
    agent_id: str = ""
    owner_entity_id: str
    model: str
    tools: list[str] = Field(default_factory=list)
    resource_uris: list[str] = Field(default_factory=list, max_length=100)
    constraints: dict[str, Any] = Field(default_factory=dict)
    risk_tolerance: str = Field(default="medium", pattern="^(low|medium|high)$")


class AgentUpdate(BaseModel):
    model: Optional[str] = None
    tools: Optional[list[str]] = None
    resource_uris: Optional[list[str]] = Field(default=None, max_length=100)
    constraints: Optional[dict[str, Any]] = None
    risk_tolerance: Optional[str] = Field(default=None, pattern="^(low|medium|high)$")


# ── Endpoints ──────────────────────────────────────────────────────────

@router.post("")
async def register(
    body: AgentRegister,
    request: Request,
    graph: GraphClient = Depends(get_graph),
):
    tenant = request.state.tenant
    tenant.require_permission("write")
    agent_id = body.agent_id or str(uuid.uuid4())
    # Insert would replace the row, handing any writer the agent's ownership.
    existing = await _configs.find_by_id(agent_id) if body.agent_id else None
    # A row in another tenant falls through to insert's generic refusal.
    if existing is not None and existing.get("tenant_id") == tenant.tenant_id:
        raise ConflictError("Agent is already registered")
    record = await _configs.register(
        agent_id=agent_id,
        owner_entity_id=body.owner_entity_id,
        tenant_id=tenant.tenant_id,
        model=body.model,
        tools=body.tools,
        resource_uris=body.resource_uris,
        constraints=body.constraints,
        risk_tolerance=body.risk_tolerance,
        # Server-derived: only an owner registering their own agent proves ownership.
        asserted_by_entity_id=getattr(tenant, "user_id", None),
    )
    # Project agent + ownership.
    gateway = GraphMutationGateway(graph_client=graph)
    await gateway.apply(vertex_intent(
        Vertex(
            vertex_type=VertexType.AGENT,
            vertex_id=agent_id,
            properties={
                "tenant_id": tenant.tenant_id,
                "owner_entity_id": body.owner_entity_id,
                "model": body.model,
                "risk_tolerance": body.risk_tolerance,
            },
        ),
        operation="node_versioned", tenant_id=tenant.tenant_id,
        actor_kind="human", actor_id="user_agents_api",
    ))
    await gateway.apply(edge_intent(
        Edge(
            edge_type=EdgeType.OWNS,
            from_vertex_id=body.owner_entity_id,
            to_vertex_id=agent_id,
            # OWNS is an H2A ownership edge — consent_purpose required in enforce.
            properties={
                "tenant_id": tenant.tenant_id,
                "kind": "agent",
                "consent_purpose": "agent",
            },
        ),
        operation="edge_created", tenant_id=tenant.tenant_id,
        actor_kind="human", actor_id="user_agents_api",
        subject_kind="entity", subject_id=body.owner_entity_id,
    ))
    metrics.increment("user_agents_registered")
    return APIResponse(data=record).to_dict()


@router.get("/{agent_id}")
async def read(agent_id: str, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("read")
    record = await _configs.find_by_id(agent_id)
    if record is None or record.get("tenant_id") != tenant.tenant_id:
        raise NotFoundError("Agent")
    return APIResponse(data=record).to_dict()


@router.patch("/{agent_id}")
async def update(agent_id: str, body: AgentUpdate, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("write")
    existing = await _configs.find_by_id(agent_id)
    if existing is None or existing.get("tenant_id") != tenant.tenant_id:
        raise NotFoundError("Agent")
    patch = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if any(key in patch for key in ("tools", "resource_uris", "constraints", "risk_tolerance")):
        patch["policy_version"] = (existing.get("policy_version") or 1) + 1
    updated = await _configs.update(agent_id, patch)
    return APIResponse(data=updated).to_dict()




@router.get("/{agent_id}/executions")
async def list_executions(
    agent_id: str,
    request: Request,
    limit: int = 50,
):
    tenant = request.state.tenant
    tenant.require_permission("read")
    config = await _configs.find_by_id(agent_id)
    if config is None or config.get("tenant_id") != tenant.tenant_id:
        raise NotFoundError("Agent")
    rows = await _executions.list_for_agent(agent_id, tenant.tenant_id, limit=min(limit, 500))
    return APIResponse(data={
        "agent_id": agent_id,
        "executions": rows,
        "count": len(rows),
    }).to_dict()


@router.get("/{agent_id}/executions/{execution_id}")
async def read_execution(agent_id: str, execution_id: str, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("read")
    record = await _executions.find_by_id(execution_id)
    if record is None or record.get("tenant_id") != tenant.tenant_id \
            or record.get("agent_id") != agent_id:
        raise NotFoundError("Execution")
    return APIResponse(data=record).to_dict()
