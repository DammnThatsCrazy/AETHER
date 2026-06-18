"""
Agentic Observability Routes — POST endpoints for observing agent activity.

INVARIANT: These routes NEVER execute, originate, sign, or settle anything.
They receive observations from external sources and store/graph-mutate them.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from repositories.agentic_observability_repos import (
    AgentActivityRepository, AgentConnectionRepository,
    AgentToolRepository, AgentRiskSignalRepository,
    ExternalAccountRepository,
)
from services.agentic_observability.event_normalizer import normalize
from services.agentic_observability.graph_mutations import build_mutations, build_account_mutations
from services.agentic_observability.models import (
    AgenticObservationRecord, MCPConnectionObserved,
    AgentToolInvocationObserved, AgentRiskSignalRecord,
)
from services.agentic_observability.risk_signals import evaluate_risk
from services.agentic_observability.schemas import (
    AgentEventRequest, AgentAccountRequest, AgentToolRequest,
    AgentMCPRequest, AgentRiskSignalRequest, ObservationResponse,
)

router = APIRouter()

_SCHEMA_VERSION = "1.0"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tenant_id(request: Request) -> str:
    tenant = getattr(request.state, "tenant", None)
    if not tenant:
        raise HTTPException(status_code=401, detail="Missing tenant context")
    return tenant.tenant_id


def _require_perm(request: Request, perm: str) -> None:
    tenant = getattr(request.state, "tenant", None)
    if not tenant:
        raise HTTPException(status_code=401, detail="Missing tenant context")
    if hasattr(tenant, "require_permission"):
        try:
            tenant.require_permission(perm)
            return
        except Exception as e:
            raise HTTPException(status_code=403, detail=str(e))
    if hasattr(tenant, "has_permission") and not tenant.has_permission(perm):
        raise HTTPException(status_code=403, detail=f"Permission denied: {perm}")


def _check_no_execution(payload: Any) -> None:
    """Reject any payload claiming execution_by_aether=True."""
    data = payload if isinstance(payload, dict) else payload.model_dump()
    if data.get("execution_by_aether") is True:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="execution_by_aether must be false. AETHER does not execute.",
        )
    if "economics" in data and data["economics"] and data["economics"].get("is_execution_by_aether") is True:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="economics.is_execution_by_aether must be false. AETHER does not execute.",
        )


@router.post("/v1/observability/agent/events", response_model=ObservationResponse, status_code=201)
async def observe_agent_event(req: AgentEventRequest, request: Request) -> ObservationResponse:
    """Observe a generic agent activity event."""
    _require_perm(request, "write")
    tenant_id = _tenant_id(request)
    _check_no_execution(req)
    raw = req.model_dump()
    record = normalize(raw, req.source.provider.value, tenant_id, req.event_name)
    computed_risk = evaluate_risk(record)
    if computed_risk.risk_level and computed_risk.risk_level.value != "low":
        record.risk = computed_risk

    repo = AgentActivityRepository()
    await repo.insert(record.observation_id, record.model_dump(mode="json"))

    mutations = build_mutations(record)
    received_at = _utc_now()
    return ObservationResponse(
        observation_id=record.observation_id,
        received_at=received_at,
        graph_mutations_queued=len(mutations),
        tenant_id=tenant_id,
    )


@router.post("/v1/observability/agent/accounts", response_model=ObservationResponse, status_code=201)
async def observe_agent_account(req: AgentAccountRequest, request: Request) -> ObservationResponse:
    """Observe an external agentic account."""
    _require_perm(request, "write")
    tenant_id = _tenant_id(request)
    _check_no_execution(req)
    obs_id = str(uuid.uuid4())
    repo = ExternalAccountRepository()
    record = req.model_dump(mode="json")
    record["observation_id"] = obs_id
    record["tenant_id"] = tenant_id
    record["received_at"] = _utc_now()
    await repo.insert(obs_id, record)

    mutations = build_account_mutations(tenant_id, req.agent_id, req.external_account_id)
    return ObservationResponse(
        observation_id=obs_id,
        received_at=record["received_at"],
        graph_mutations_queued=len(mutations),
        tenant_id=tenant_id,
    )


@router.post("/v1/observability/agent/tools", response_model=ObservationResponse, status_code=201)
async def observe_agent_tool(req: AgentToolRequest, request: Request) -> ObservationResponse:
    """Observe an agent tool invocation."""
    _require_perm(request, "write")
    tenant_id = _tenant_id(request)
    _check_no_execution(req)
    obs_id = str(uuid.uuid4())
    record = req.model_dump(mode="json")
    record["observation_id"] = obs_id
    record["tenant_id"] = tenant_id
    record["received_at"] = _utc_now()
    repo = AgentToolRepository()
    await repo.insert(obs_id, record)
    return ObservationResponse(
        observation_id=obs_id,
        received_at=record["received_at"],
        graph_mutations_queued=1,
        tenant_id=tenant_id,
    )


@router.post("/v1/observability/agent/mcp", response_model=ObservationResponse, status_code=201)
async def observe_mcp_connection(req: AgentMCPRequest, request: Request) -> ObservationResponse:
    """Observe an MCP server connection."""
    _require_perm(request, "write")
    tenant_id = _tenant_id(request)
    _check_no_execution(req)
    obs_id = str(uuid.uuid4())
    record = req.model_dump(mode="json")
    record["observation_id"] = obs_id
    record["tenant_id"] = tenant_id
    record["received_at"] = _utc_now()
    repo = AgentConnectionRepository()
    await repo.insert(obs_id, record)
    return ObservationResponse(
        observation_id=obs_id,
        received_at=record["received_at"],
        graph_mutations_queued=2,
        tenant_id=tenant_id,
    )


@router.post("/v1/observability/agent/risk-signals", response_model=ObservationResponse, status_code=201)
async def observe_risk_signal(req: AgentRiskSignalRequest, request: Request) -> ObservationResponse:
    """Record an agent risk signal."""
    _require_perm(request, "write")
    tenant_id = _tenant_id(request)
    _check_no_execution(req)
    obs_id = str(uuid.uuid4())
    record = req.model_dump(mode="json")
    record["observation_id"] = obs_id
    record["tenant_id"] = tenant_id
    record["received_at"] = _utc_now()
    repo = AgentRiskSignalRepository()
    await repo.insert(obs_id, record)
    return ObservationResponse(
        observation_id=obs_id,
        received_at=record["received_at"],
        graph_mutations_queued=0,
        tenant_id=tenant_id,
    )


# ---------------------------------------------------------------------------
# Kyber admin read routes
# ---------------------------------------------------------------------------

@router.get("/v1/admin/kyber/agentic-observability/overview")
async def kyber_agentic_overview(request: Request) -> dict:
    """Kyber operator: agentic observability overview."""
    _require_perm(request, "admin")
    return {"status": "ok", "message": "Agentic observability overview — queries TBD"}


@router.get("/v1/admin/kyber/agentic-observability/agents/{agent_id}")
async def kyber_agentic_agent(agent_id: str, request: Request) -> dict:
    """Kyber operator: single agent observability view."""
    _require_perm(request, "admin")
    return {"agent_id": agent_id, "status": "ok"}


@router.get("/v1/admin/kyber/agentic-observability/risk")
async def kyber_agentic_risk(request: Request) -> dict:
    """Kyber operator: risk signals overview."""
    _require_perm(request, "admin")
    return {"status": "ok", "risk_signals": []}
