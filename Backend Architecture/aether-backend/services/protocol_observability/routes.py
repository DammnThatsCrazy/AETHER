"""
Protocol Observability Routes — x402 observation endpoints.

INVARIANT: These routes NEVER sign, execute, or settle x402 payments.
They observe and record x402 protocol interactions from the outside.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status

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


def _check_no_execution(data: dict) -> None:
    if data.get("execution_by_aether") is True:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="execution_by_aether must be false. AETHER does not execute.",
        )


@router.post("/v1/observability/x402/interactions", response_model=X402ObservationResponse, status_code=201)
async def observe_x402_interaction(req: X402InteractionRequest) -> X402ObservationResponse:
    """Observe an x402 protocol interaction."""
    _check_no_execution(req.model_dump())
    record = normalize_x402_interaction(req.model_dump(), req.tenant_id)
    repo = X402InteractionRepository()
    await repo.insert(record.interaction_id, record.model_dump(mode="json"))
    mutations = build_interaction_mutations(req.tenant_id, record.interaction_id, req.agent_id, req.resource_url)
    return X402ObservationResponse(
        observation_id=record.interaction_id,
        received_at=_utc_now(),
        graph_mutations_queued=len(mutations),
        tenant_id=req.tenant_id,
    )


@router.post("/v1/observability/x402/challenges", response_model=X402ObservationResponse, status_code=201)
async def observe_x402_challenge(req: X402ChallengeRequest) -> X402ObservationResponse:
    """Observe an x402 HTTP 402 challenge."""
    obs_id = _new_id()
    record = req.model_dump(mode="json")
    record["challenge_obs_id"] = obs_id
    record["received_at"] = _utc_now()
    repo = X402ChallengeRepository()
    await repo.insert(obs_id, record)
    mutations = build_challenge_mutations(req.tenant_id, obs_id, req.interaction_id)
    return X402ObservationResponse(
        observation_id=obs_id,
        received_at=record["received_at"],
        graph_mutations_queued=len(mutations),
        tenant_id=req.tenant_id,
    )


@router.post("/v1/observability/x402/requirements", response_model=X402ObservationResponse, status_code=201)
async def observe_x402_requirement(req: X402RequirementRequest) -> X402ObservationResponse:
    """Observe an x402 payment requirement."""
    obs_id = _new_id()
    record = req.model_dump(mode="json")
    record["requirement_obs_id"] = obs_id
    record["received_at"] = _utc_now()
    repo = X402RequirementRepository()
    await repo.insert(obs_id, record)
    return X402ObservationResponse(
        observation_id=obs_id, received_at=record["received_at"],
        graph_mutations_queued=1, tenant_id=req.tenant_id,
    )


@router.post("/v1/observability/x402/signatures", response_model=X402ObservationResponse, status_code=201)
async def observe_x402_signature(req: X402SignatureRequest) -> X402ObservationResponse:
    """Observe an x402 payment signature (signed externally, not by AETHER)."""
    _check_no_execution(req.model_dump())
    obs_id = _new_id()
    record = req.model_dump(mode="json")
    record["signature_obs_id"] = obs_id
    record["received_at"] = _utc_now()
    repo = X402SignatureRepository()
    await repo.insert(obs_id, record)
    return X402ObservationResponse(
        observation_id=obs_id, received_at=record["received_at"],
        graph_mutations_queued=1, tenant_id=req.tenant_id,
    )


@router.post("/v1/observability/x402/verifications", response_model=X402ObservationResponse, status_code=201)
async def observe_x402_verification(req: X402VerificationRequest) -> X402ObservationResponse:
    """Observe an x402 verification result."""
    obs_id = _new_id()
    record = req.model_dump(mode="json")
    record["verification_obs_id"] = obs_id
    record["received_at"] = _utc_now()
    repo = X402VerificationRepository()
    await repo.insert(obs_id, record)
    return X402ObservationResponse(
        observation_id=obs_id, received_at=record["received_at"],
        graph_mutations_queued=1, tenant_id=req.tenant_id,
    )


@router.post("/v1/observability/x402/settlements", response_model=X402ObservationResponse, status_code=201)
async def observe_x402_settlement(req: X402SettlementRequest) -> X402ObservationResponse:
    """Observe an x402 settlement (executed externally, not by AETHER)."""
    _check_no_execution(req.model_dump())
    record = normalize_x402_settlement(req.model_dump(), req.tenant_id)
    repo = X402SettlementObsRepository()
    await repo.insert(record.settlement_obs_id, record.model_dump(mode="json"))
    mutations = build_settlement_mutations(req.tenant_id, record.settlement_obs_id, req.interaction_id)
    return X402ObservationResponse(
        observation_id=record.settlement_obs_id,
        received_at=_utc_now(),
        graph_mutations_queued=len(mutations),
        tenant_id=req.tenant_id,
    )


@router.post("/v1/observability/x402/resource-access", response_model=X402ObservationResponse, status_code=201)
async def observe_x402_resource_access(req: X402ResourceAccessRequest) -> X402ObservationResponse:
    """Observe an x402 resource access outcome."""
    obs_id = _new_id()
    record = req.model_dump(mode="json")
    record["access_obs_id"] = obs_id
    record["received_at"] = _utc_now()
    repo = X402ResourceAccessRepository()
    await repo.insert(obs_id, record)
    mutations = build_resource_access_mutations(req.tenant_id, obs_id, req.interaction_id, req.access_granted)
    return X402ObservationResponse(
        observation_id=obs_id, received_at=record["received_at"],
        graph_mutations_queued=len(mutations), tenant_id=req.tenant_id,
    )


@router.get("/v1/admin/kyber/agentic-observability/x402")
async def kyber_x402_overview() -> dict:
    """Kyber operator: x402 observability overview."""
    return {"status": "ok", "message": "x402 observability overview"}


@router.get("/v1/admin/kyber/agentic-observability/replay")
async def kyber_x402_replay() -> dict:
    """Kyber operator: replay risk signals."""
    return {"status": "ok", "replay_risks": []}
