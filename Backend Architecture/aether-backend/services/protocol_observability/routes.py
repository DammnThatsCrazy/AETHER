"""
Protocol Observability Routes — x402 observation endpoints.

INVARIANT: These routes NEVER sign, execute, or settle x402 payments.
They observe and record x402 protocol interactions from the outside.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, status
from shared.graph.graph import Vertex, Edge

from repositories.agentic_observability_repos import (
    X402InteractionRepository, X402ChallengeRepository,
    X402RequirementRepository, X402SignatureRepository,
    X402VerificationRepository, X402SettlementObsRepository,
    X402ResourceAccessRepository,
)
from services.protocol_observability.x402_graph_mutations import (
    build_interaction_mutations, build_challenge_mutations,
    build_settlement_mutations, build_resource_access_mutations,
)
from services.protocol_observability.x402_normalizer import normalize_x402_interaction, normalize_x402_settlement
from services.protocol_observability.x402_schemas import (
    X402InteractionRequest, X402ChallengeRequest, X402RequirementRequest,
    X402SignatureRequest, X402VerificationRequest, X402SettlementRequest,
    X402ResourceAccessRequest, X402ObservationResponse,
)

router = APIRouter()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


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


def _check_no_execution(data: dict) -> None:
    if data.get("execution_by_aether") is True:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="execution_by_aether must be false. AETHER does not execute.",
        )


async def _persist_mutations(mutations: list) -> None:
    if not mutations:
        return
    try:
        from dependencies.providers import get_graph
        graph = get_graph()
        for m in mutations:
            if isinstance(m, Vertex):
                await graph.add_vertex(m)
            elif isinstance(m, Edge):
                await graph.add_edge(m)
    except Exception:
        pass


@router.post("/v1/observability/x402/interactions", response_model=X402ObservationResponse, status_code=201)
async def observe_x402_interaction(req: X402InteractionRequest, request: Request) -> X402ObservationResponse:
    """Observe an x402 protocol interaction."""
    _require_perm(request, "write")
    tenant_id = _tenant_id(request)
    _check_no_execution(req.model_dump())
    raw = req.model_dump()
    raw["tenant_id"] = tenant_id
    record = normalize_x402_interaction(raw, tenant_id)
    repo = X402InteractionRepository()
    await repo.insert(record.interaction_id, record.model_dump(mode="json"))
    mutations = build_interaction_mutations(tenant_id, record.interaction_id, req.agent_id, req.resource_url)
    await _persist_mutations(mutations)
    return X402ObservationResponse(
        observation_id=record.interaction_id,
        received_at=_utc_now(),
        graph_mutations_queued=len(mutations),
        tenant_id=tenant_id,
    )


@router.post("/v1/observability/x402/challenges", response_model=X402ObservationResponse, status_code=201)
async def observe_x402_challenge(req: X402ChallengeRequest, request: Request) -> X402ObservationResponse:
    """Observe an x402 HTTP 402 challenge."""
    _require_perm(request, "write")
    tenant_id = _tenant_id(request)
    _check_no_execution(req.model_dump())
    obs_id = _new_id()
    record = req.model_dump(mode="json")
    record["challenge_obs_id"] = obs_id
    record["tenant_id"] = tenant_id
    record["received_at"] = _utc_now()
    repo = X402ChallengeRepository()
    await repo.insert(obs_id, record)
    mutations = build_challenge_mutations(tenant_id, obs_id, req.interaction_id)
    await _persist_mutations(mutations)
    return X402ObservationResponse(
        observation_id=obs_id,
        received_at=record["received_at"],
        graph_mutations_queued=len(mutations),
        tenant_id=tenant_id,
    )


@router.post("/v1/observability/x402/requirements", response_model=X402ObservationResponse, status_code=201)
async def observe_x402_requirement(req: X402RequirementRequest, request: Request) -> X402ObservationResponse:
    """Observe an x402 payment requirement."""
    _require_perm(request, "write")
    tenant_id = _tenant_id(request)
    _check_no_execution(req.model_dump())
    obs_id = _new_id()
    record = req.model_dump(mode="json")
    record["requirement_obs_id"] = obs_id
    record["tenant_id"] = tenant_id
    record["received_at"] = _utc_now()
    repo = X402RequirementRepository()
    await repo.insert(obs_id, record)
    return X402ObservationResponse(
        observation_id=obs_id, received_at=record["received_at"],
        graph_mutations_queued=1, tenant_id=tenant_id,
    )


@router.post("/v1/observability/x402/signatures", response_model=X402ObservationResponse, status_code=201)
async def observe_x402_signature(req: X402SignatureRequest, request: Request) -> X402ObservationResponse:
    """Observe an x402 payment signature (signed externally, not by AETHER)."""
    _require_perm(request, "write")
    tenant_id = _tenant_id(request)
    _check_no_execution(req.model_dump())
    obs_id = _new_id()
    record = req.model_dump(mode="json")
    record["signature_obs_id"] = obs_id
    record["tenant_id"] = tenant_id
    record["received_at"] = _utc_now()
    repo = X402SignatureRepository()
    await repo.insert(obs_id, record)
    return X402ObservationResponse(
        observation_id=obs_id, received_at=record["received_at"],
        graph_mutations_queued=1, tenant_id=tenant_id,
    )


@router.post("/v1/observability/x402/verifications", response_model=X402ObservationResponse, status_code=201)
async def observe_x402_verification(req: X402VerificationRequest, request: Request) -> X402ObservationResponse:
    """Observe an x402 verification result."""
    _require_perm(request, "write")
    tenant_id = _tenant_id(request)
    obs_id = _new_id()
    record = req.model_dump(mode="json")
    record["verification_obs_id"] = obs_id
    record["tenant_id"] = tenant_id
    record["received_at"] = _utc_now()
    repo = X402VerificationRepository()
    await repo.insert(obs_id, record)
    return X402ObservationResponse(
        observation_id=obs_id, received_at=record["received_at"],
        graph_mutations_queued=1, tenant_id=tenant_id,
    )


@router.post("/v1/observability/x402/settlements", response_model=X402ObservationResponse, status_code=201)
async def observe_x402_settlement(req: X402SettlementRequest, request: Request) -> X402ObservationResponse:
    """Observe an x402 settlement (executed externally, not by AETHER)."""
    _require_perm(request, "write")
    tenant_id = _tenant_id(request)
    _check_no_execution(req.model_dump())
    raw = req.model_dump()
    raw["tenant_id"] = tenant_id
    record = normalize_x402_settlement(raw, tenant_id)
    repo = X402SettlementObsRepository()
    await repo.insert(record.settlement_obs_id, record.model_dump(mode="json"))
    mutations = build_settlement_mutations(tenant_id, record.settlement_obs_id, req.interaction_id)
    await _persist_mutations(mutations)
    return X402ObservationResponse(
        observation_id=record.settlement_obs_id,
        received_at=_utc_now(),
        graph_mutations_queued=len(mutations),
        tenant_id=tenant_id,
    )


@router.post("/v1/observability/x402/resource-access", response_model=X402ObservationResponse, status_code=201)
async def observe_x402_resource_access(req: X402ResourceAccessRequest, request: Request) -> X402ObservationResponse:
    """Observe an x402 resource access outcome."""
    _require_perm(request, "write")
    tenant_id = _tenant_id(request)
    obs_id = _new_id()
    record = req.model_dump(mode="json")
    record["access_obs_id"] = obs_id
    record["tenant_id"] = tenant_id
    record["received_at"] = _utc_now()
    repo = X402ResourceAccessRepository()
    await repo.insert(obs_id, record)
    mutations = build_resource_access_mutations(tenant_id, obs_id, req.interaction_id, req.access_granted)
    await _persist_mutations(mutations)
    return X402ObservationResponse(
        observation_id=obs_id, received_at=record["received_at"],
        graph_mutations_queued=len(mutations), tenant_id=tenant_id,
    )


@router.get("/v1/admin/kyber/agentic-observability/x402")
async def kyber_x402_overview(request: Request) -> dict:
    """Kyber operator: x402 observability overview."""
    _require_perm(request, "admin")
    return {"status": "ok", "message": "x402 observability overview"}


@router.get("/v1/admin/kyber/agentic-observability/replay")
async def kyber_x402_replay(request: Request) -> dict:
    """Kyber operator: replay risk signals."""
    _require_perm(request, "admin")
    return {"status": "ok", "replay_risks": []}
