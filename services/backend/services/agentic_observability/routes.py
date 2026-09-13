"""
Agentic Observability Routes — POST endpoints for observing agent activity.

INVARIANT: These routes NEVER execute, originate, sign, or settle anything.
They receive observations from external sources and store/graph-mutate them.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Request

from config.settings import settings
from repositories.agentic_observability_repos import (
    AgentActivityRepository, AgentConnectionRepository,
    AgentToolRepository, AgentRiskSignalRepository,
    ExternalAccountRepository,
)
from services.agentic_observability.event_normalizer import normalize, resolve_provider
from services.agentic_observability.graph_mutations import build_mutations, build_account_mutations
from services.agentic_observability.pipeline import ingest_observation
from services.agentic_observability.models import (
    AgenticObservationRecord, MCPConnectionObserved,
    AgentToolInvocationObserved, AgentRiskSignalRecord,
)
from services.agentic_observability.risk_signals import evaluate_risk
from services.agentic_observability.schemas import (
    AgentEventRequest, AgentAccountRequest, AgentToolRequest,
    AgentMCPRequest, AgentRiskSignalRequest, ObservationResponse,
)
from services.agentic_observability.foundation import (
    active_tenant_id as _tenant_id,
    check_no_execution as _check_no_execution,
    persist_mutations as _persist_mutations,
    require_permission as _require_perm,
    validate_event_name,
    validate_payload_tenant,
)
from services.security.request_context import require_kyber_operator

router = APIRouter()
mcp_router = APIRouter()

_SCHEMA_VERSION = "1.0"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _use_canonical_spine(tenant_id: str) -> bool:
    """Route this observation through the canonical durable spine?

    Default OFF: only when the flag is enabled globally or the tenant is a
    declared canary. Every other tenant keeps the synchronous legacy path.
    """
    cfg = settings.agentic_observability_ingestion
    return cfg.canonical_spine_enabled or tenant_id in cfg.canary_tenant_ids


def _prune_none(props: dict) -> dict:
    return {k: v for k, v in props.items() if v is not None}


async def _delegate_to_spine(
    *,
    tenant_id: str,
    event_name: str,
    provider_id: str,
    properties: dict,
    agent_id: str | None = None,
    actor_id: str | None = None,
    provider_event_id: str | None = None,
    integration_id: str | None = None,
    environment_id: str | None = None,
    observed_at: str | None = None,
) -> ObservationResponse:
    """Delegate to the canonical spine and report an HONEST queued projection.

    Graph projection happens asynchronously via the relay, so the delegated
    response reports mutations as ``queued`` (== outbox rows written) with zero
    synchronously built/persisted — the truthful state for an async pipeline.
    """
    ingest = await ingest_observation(
        tenant_id=tenant_id,
        event_name=event_name,
        provider_id=provider_id,
        integration_id=integration_id,
        environment_id=environment_id,
        provider_event_id=provider_event_id,
        actor_id=actor_id,
        agent_id=agent_id,
        observed_at=observed_at,
        properties=_prune_none(properties),
    )
    return ObservationResponse(
        observation_id=ingest.event_id,
        received_at=_utc_now(),
        graph_mutations_queued=ingest.outbox_written,
        tenant_id=tenant_id,
        graph_mutations_built=0,
        graph_mutations_persisted=0,
        graph_projection_status="queued",
    )


@router.post("/v1/observability/agent/events", response_model=ObservationResponse, status_code=201)
async def observe_agent_event(req: AgentEventRequest, request: Request) -> ObservationResponse:
    """Observe a generic agent activity event."""
    _require_perm(request, "write")
    tenant_id = _tenant_id(request)
    validate_payload_tenant(req, tenant_id)
    validate_event_name(req.event_name)
    _check_no_execution(req)

    # Normalize + evaluate risk on BOTH paths so derived signals
    # (autonomous_agent_without_known_id, unknown_mcp_server, large amount, …)
    # are computed for canary tenants too, not only the legacy path.
    raw = req.model_dump()
    record = normalize(raw, req.source.provider.value, tenant_id, req.event_name)
    computed_risk = evaluate_risk(record)
    existing = record.risk
    if existing and computed_risk.risk_level:
        _SEVERITY = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        ex_sev = _SEVERITY.get(existing.risk_level.value if existing.risk_level else "low", 0)
        co_sev = _SEVERITY.get(computed_risk.risk_level.value, 0)
        merged_level = computed_risk.risk_level if co_sev >= ex_sev else existing.risk_level
        merged_codes = list(dict.fromkeys((existing.reason_codes or []) + (computed_risk.reason_codes or [])))
        merged_flags = list(dict.fromkeys((existing.policy_flags or []) + (computed_risk.policy_flags or [])))
        merged_review = bool(existing.requires_review) or bool(computed_risk.requires_review)
        from services.agentic_observability.models import ObservationRisk
        record.risk = ObservationRisk(
            risk_level=merged_level,
            reason_codes=merged_codes,
            policy_flags=merged_flags,
            requires_review=merged_review,
        )
    elif computed_risk.risk_level and computed_risk.risk_level.value != "low":
        record.risk = computed_risk

    # Legacy compat store (Kyber "activities" count) — written on BOTH paths.
    await AgentActivityRepository().insert(record.observation_id, record.model_dump(mode="json"))

    if _use_canonical_spine(tenant_id):
        provider_id = resolve_provider(raw)
        agent_id = (req.agent.agent_id if req.agent and req.agent.agent_id else None) or req.actor.actor_id
        props: dict = {
            "agentId": agent_id,
            "objectType": req.object.object_type,
            "objectId": req.object.object_id,
            "status": req.action.status.value if req.action else None,
            "outcome": req.action.outcome if req.action else None,
            "provider": provider_id,
        }
        if record.risk:  # merged (client + derived) risk, not only client-supplied
            props["riskLevel"] = record.risk.risk_level.value if record.risk.risk_level else None
            props["reasonCodes"] = record.risk.reason_codes or None
            props["policyFlags"] = record.risk.policy_flags or None
        if req.economics:
            props["amount"] = req.economics.amount  # decimal string
            props["currency"] = req.economics.currency
            props["asset"] = req.economics.asset
            props["direction"] = req.economics.direction
        return await _delegate_to_spine(
            tenant_id=tenant_id,
            event_name=req.event_name,
            provider_id=provider_id,
            properties=props,
            agent_id=agent_id,
            actor_id=req.actor.actor_id,
            provider_event_id=(req.source.provider_event_id if req.source else None),
            integration_id=(req.source.integration_id if req.source else None),
            observed_at=req.observed_at,
        )

    mutations = build_mutations(record)
    projection = await _persist_mutations(mutations, tenant_id=tenant_id, trace_id=record.observation_id)
    return ObservationResponse(
        observation_id=record.observation_id,
        received_at=_utc_now(),
        graph_mutations_queued=projection.graph_mutations_persisted,
        tenant_id=tenant_id,
        graph_mutations_built=projection.graph_mutations_built,
        graph_mutations_persisted=projection.graph_mutations_persisted,
        graph_projection_status=projection.graph_projection_status,
    )


@router.post("/v1/observability/agent/accounts", response_model=ObservationResponse, status_code=201)
async def observe_agent_account(req: AgentAccountRequest, request: Request) -> ObservationResponse:
    """Observe an external agentic account."""
    _require_perm(request, "write")
    tenant_id = _tenant_id(request)
    validate_payload_tenant(req, tenant_id)
    _check_no_execution(req)
    obs_id = str(uuid.uuid4())
    repo = ExternalAccountRepository()
    record = req.model_dump(mode="json")
    record["observation_id"] = obs_id
    record["tenant_id"] = tenant_id
    record["received_at"] = _utc_now()
    await repo.insert(obs_id, record)

    mutations = build_account_mutations(tenant_id, req.agent_id, req.external_account_id)
    projection = await _persist_mutations(mutations, tenant_id=tenant_id, trace_id=obs_id)
    return ObservationResponse(
        observation_id=obs_id,
        received_at=record["received_at"],
        graph_mutations_queued=projection.graph_mutations_persisted,
        tenant_id=tenant_id,
        graph_mutations_built=projection.graph_mutations_built,
        graph_mutations_persisted=projection.graph_mutations_persisted,
        graph_projection_status=projection.graph_projection_status,
    )


@router.post("/v1/observability/agent/tools", response_model=ObservationResponse, status_code=201)
async def observe_agent_tool(req: AgentToolRequest, request: Request) -> ObservationResponse:
    """Observe an agent tool invocation."""
    _require_perm(request, "write")
    tenant_id = _tenant_id(request)
    validate_payload_tenant(req, tenant_id)
    _check_no_execution(req)

    obs_id = str(uuid.uuid4())
    record = req.model_dump(mode="json")
    record["observation_id"] = obs_id
    record["tenant_id"] = tenant_id
    record["received_at"] = _utc_now()
    # Legacy compat store (Kyber "tools" count) — written on BOTH paths.
    await AgentToolRepository().insert(obs_id, record)

    if _use_canonical_spine(tenant_id):
        provider_id = resolve_provider(req.model_dump())
        return await _delegate_to_spine(
            tenant_id=tenant_id,
            event_name="agent_tool_invocation_observed",
            provider_id=provider_id,
            properties={
                "agentId": req.agent_id,
                "toolName": req.tool_name,
                "status": req.status,
                "durationMs": req.duration_ms,
                "provider": provider_id,
                "objectType": "tool",
                "objectId": req.tool_name,
            },
            agent_id=req.agent_id,
            provider_event_id=obs_id,
            observed_at=req.observed_at,
        )

    return ObservationResponse(
        observation_id=obs_id,
        received_at=record["received_at"],
        graph_mutations_queued=0,
        tenant_id=tenant_id,
    )


@mcp_router.post("/v1/observability/agent/mcp", response_model=ObservationResponse, status_code=201)
async def observe_mcp_connection(req: AgentMCPRequest, request: Request) -> ObservationResponse:
    """Observe an MCP server connection."""
    _require_perm(request, "write")
    tenant_id = _tenant_id(request)
    validate_payload_tenant(req, tenant_id)
    _check_no_execution(req)

    obs_id = str(uuid.uuid4())
    record = req.model_dump(mode="json")
    record["observation_id"] = obs_id
    record["tenant_id"] = tenant_id
    record["received_at"] = _utc_now()
    # Legacy compat store (Kyber "mcp_connections" count) — written on BOTH paths.
    await AgentConnectionRepository().insert(obs_id, record)

    if _use_canonical_spine(tenant_id):
        provider_id = resolve_provider(req.model_dump())
        first_tool = req.tools[0] if req.tools else None
        return await _delegate_to_spine(
            tenant_id=tenant_id,
            event_name="agent_mcp_connection_observed",
            provider_id=provider_id,
            properties={
                "agentId": req.agent_id,
                "serverName": req.server_name,
                "serverUrl": req.server_url,
                "toolName": first_tool,
                "provider": provider_id,
                "objectType": "mcp_connection",
                "objectId": req.server_name,
            },
            agent_id=req.agent_id,
            provider_event_id=obs_id,
            observed_at=req.connected_at,
        )

    return ObservationResponse(
        observation_id=obs_id,
        received_at=record["received_at"],
        graph_mutations_queued=0,
        tenant_id=tenant_id,
    )


@router.post("/v1/observability/agent/risk-signals", response_model=ObservationResponse, status_code=201)
async def observe_risk_signal(req: AgentRiskSignalRequest, request: Request) -> ObservationResponse:
    """Record an agent risk signal."""
    _require_perm(request, "write")
    tenant_id = _tenant_id(request)
    validate_payload_tenant(req, tenant_id)
    _check_no_execution(req)

    signal = AgentRiskSignalRecord(
        agent_id=req.agent_id,
        risk_level=req.risk_level,
        reason_codes=req.reason_codes,
        policy_flags=req.policy_flags,
        tenant_id=tenant_id,
    )
    # Legacy compat store (Kyber "risk_signals" count) — written on BOTH paths.
    await AgentRiskSignalRepository().insert(signal.signal_id, signal.model_dump(mode="json"))

    if _use_canonical_spine(tenant_id):
        provider_id = resolve_provider(req.model_dump())
        return await _delegate_to_spine(
            tenant_id=tenant_id,
            event_name="agent_risk_signal_observed",
            provider_id=provider_id,
            properties={
                "agentId": req.agent_id,
                "riskLevel": req.risk_level.value if req.risk_level else None,
                "reasonCodes": req.reason_codes or None,
                "policyFlags": req.policy_flags or None,
                "provider": provider_id,
                "objectType": "risk_signal",
            },
            agent_id=req.agent_id,
            provider_event_id=signal.signal_id,
        )

    return ObservationResponse(
        observation_id=signal.signal_id,
        received_at=_utc_now(),
        graph_mutations_queued=0,
        tenant_id=tenant_id,
    )


# ---------------------------------------------------------------------------
# Kyber admin read routes
# ---------------------------------------------------------------------------

@router.get("/v1/admin/kyber/agentic-observability/overview", dependencies=[Depends(require_kyber_operator)])
async def kyber_agentic_overview(request: Request) -> dict:
    """Kyber operator: agentic observability overview."""
    _require_perm(request, "admin")
    tenant_id = _tenant_id(request)
    activity_repo = AgentActivityRepository()
    tool_repo = AgentToolRepository()
    connection_repo = AgentConnectionRepository()
    account_repo = ExternalAccountRepository()
    risk_repo = AgentRiskSignalRepository()
    return {
        "status": "ok",
        "tenant_id": tenant_id,
        "counts": {
            "activities": await activity_repo.count({"tenant_id": tenant_id}),
            "tools": await tool_repo.count({"tenant_id": tenant_id}),
            "mcp_connections": await connection_repo.count({"tenant_id": tenant_id}),
            "external_accounts": await account_repo.count({"tenant_id": tenant_id}),
            "risk_signals": await risk_repo.count({"tenant_id": tenant_id}),
        },
    }


@router.get("/v1/admin/kyber/agentic-observability/agents/{agent_id}", dependencies=[Depends(require_kyber_operator)])
async def kyber_agentic_agent(agent_id: str, request: Request) -> dict:
    """Kyber operator: single agent observability view."""
    _require_perm(request, "admin")
    tenant_id = _tenant_id(request)
    activity_repo = AgentActivityRepository()
    tool_repo = AgentToolRepository()
    connection_repo = AgentConnectionRepository()
    return {
        "agent_id": agent_id,
        "tenant_id": tenant_id,
        "status": "ok",
        "counts": {
            "activities": await activity_repo.count({"tenant_id": tenant_id, "agent_id": agent_id}),
            "tools": await tool_repo.count({"tenant_id": tenant_id, "agent_id": agent_id}),
            "mcp_connections": await connection_repo.count({"tenant_id": tenant_id, "agent_id": agent_id}),
        },
    }


@router.get("/v1/admin/kyber/agentic-observability/risk", dependencies=[Depends(require_kyber_operator)])
async def kyber_agentic_risk(request: Request) -> dict:
    """Kyber operator: risk signals overview."""
    _require_perm(request, "admin")
    tenant_id = _tenant_id(request)
    repo = AgentRiskSignalRepository()
    items = await repo.find_many(filters={"tenant_id": tenant_id}, limit=100)
    return {"status": "ok", "tenant_id": tenant_id, "risk_signals": items, "count": len(items)}
