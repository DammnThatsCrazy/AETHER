"""
Aether Backend — Reward Automation Service Routes

Exposes the reward eligibility engine, queue processor, and campaign
management via a REST API.  The ``/evaluate`` endpoint is the primary
integration point — it orchestrates fraud scoring, attribution resolution,
eligibility evaluation, and (when eligible) proof generation in a single
call.

Multi-chain support:
    The oracle signer is a ``MultiChainSigner`` configured for all
    supported VM families (EVM, SVM, Bitcoin, MoveVM, NEAR, TVM, Cosmos).
    Campaigns specify their target ``vm_type`` so proofs are generated
    with the correct message format and signing scheme.

Routes:
    POST /v1/rewards/evaluate             Evaluate event for reward eligibility
    POST /v1/rewards/campaigns            Create a reward campaign
    GET  /v1/rewards/campaigns            List reward campaigns
    GET  /v1/rewards/campaigns/{id}       Get campaign details
    GET  /v1/rewards/queue/stats          Reward queue statistics
    GET  /v1/rewards/user/{address}       Get user reward history
    POST /v1/rewards/process              Trigger queue processing
    GET  /v1/rewards/proof/{reward_id}    Get reward proof for claiming
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.oracle.multichain_signer import (
    ChainConfig,
    MultiChainProofConfig,
    MultiChainSigner,
    VMType,
)
from services.oracle.signer import OracleSigner, ProofConfig
from services.fraud.engine import FraudEngine
from services.attribution.resolver import AttributionResolver
from services.rewards.eligibility import (
    Campaign,
    EligibilityEngine,
    EligibilityResult,
    RewardRule,
    RewardTier,
)
from services.rewards.queue import RewardQueue
from shared.common.common import NotFoundError
from shared.decorators import api_response
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.service.rewards")

router = APIRouter(prefix="/v1/rewards", tags=["Rewards"])


# ═══════════════════════════════════════════════════════════════════════════
# ENVIRONMENT-DRIVEN CHAIN CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

_ORACLE_SIGNER_KEY = os.environ.get(
    "ORACLE_SIGNER_KEY",
    "ac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",
)

_PROOF_EXPIRY_SECONDS = int(os.environ.get("PROOF_EXPIRY_SECONDS", "3600"))

# Per-chain configuration from environment variables
_chain_configs: dict[VMType, ChainConfig] = {
    VMType.EVM: ChainConfig(
        chain_id=int(os.environ.get("EVM_CHAIN_ID", "1")),
        contract_address=os.environ.get(
            "EVM_CONTRACT_ADDRESS",
            "0x5FbDB2315678afecb367f032d93F642f64180aa3",
        ),
        proof_expiry_seconds=_PROOF_EXPIRY_SECONDS,
    ),
    VMType.SVM: ChainConfig(
        chain_id=int(os.environ.get("SVM_CHAIN_ID", "101")),
        contract_address=os.environ.get(
            "SVM_PROGRAM_ID",
            "AetherRwd1111111111111111111111111111111111",
        ),
        proof_expiry_seconds=_PROOF_EXPIRY_SECONDS,
    ),
    VMType.BITCOIN: ChainConfig(
        chain_id=int(os.environ.get("BTC_CHAIN_ID", "0")),
        contract_address=os.environ.get(
            "BTC_INSCRIPTION_ADDRESS",
            "bc1qaetherrewards000000000000000000000000",
        ),
        proof_expiry_seconds=_PROOF_EXPIRY_SECONDS,
    ),
    VMType.MOVEVM: ChainConfig(
        chain_id=int(os.environ.get("SUI_CHAIN_ID", "1")),
        contract_address=os.environ.get(
            "SUI_MODULE_ADDRESS",
            "0x" + "a3" * 32,
        ),
        proof_expiry_seconds=_PROOF_EXPIRY_SECONDS,
    ),
    VMType.NEAR: ChainConfig(
        chain_id=int(os.environ.get("NEAR_CHAIN_ID", "0")),
        contract_address=os.environ.get(
            "NEAR_CONTRACT_ID",
            "aether-rewards.near",
        ),
        proof_expiry_seconds=_PROOF_EXPIRY_SECONDS,
    ),
    VMType.TVM: ChainConfig(
        chain_id=int(os.environ.get("TRON_CHAIN_ID", "728126428")),
        contract_address=os.environ.get(
            "TRON_CONTRACT_ADDRESS",
            "0x" + "b4" * 20,
        ),
        proof_expiry_seconds=_PROOF_EXPIRY_SECONDS,
    ),
    VMType.COSMOS: ChainConfig(
        chain_id=int(os.environ.get("COSMOS_CHAIN_ID", "1")),
        contract_address=os.environ.get(
            "COSMOS_CONTRACT_ADDRESS",
            "cosmos1aetherrewards00000000000000000000000",
        ),
        proof_expiry_seconds=_PROOF_EXPIRY_SECONDS,
    ),
}

_multichain_config = MultiChainProofConfig(
    signer_private_key=_ORACLE_SIGNER_KEY,
    chain_configs=_chain_configs,
)


# ═══════════════════════════════════════════════════════════════════════════
# SINGLETONS (initialised at import time)
# ═══════════════════════════════════════════════════════════════════════════

# Legacy EVM-only config (kept for backward compatibility with RewardQueue)
_oracle_config = ProofConfig(
    signer_private_key=_ORACLE_SIGNER_KEY,
    contract_address=_chain_configs[VMType.EVM].contract_address,
    chain_id=_chain_configs[VMType.EVM].chain_id,
    proof_expiry_seconds=_PROOF_EXPIRY_SECONDS,
)

_multichain_oracle = MultiChainSigner(_multichain_config)
_legacy_oracle = OracleSigner(_oracle_config)
_fraud_engine = FraudEngine()
_attribution_resolver = AttributionResolver()
_engine = EligibilityEngine()
_queue = RewardQueue(_legacy_oracle)


# ═══════════════════════════════════════════════════════════════════════════
# REQUEST / RESPONSE MODELS
# ═══════════════════════════════════════════════════════════════════════════

# -- evaluate -----------------------------------------------------------

class EvaluateRequest(BaseModel):
    """Payload for the ``/evaluate`` endpoint."""
    event_type: str = Field(..., description="e.g. conversion, signup, referral")
    user_address: Optional[str] = Field(None, description="Wallet address (0x...)")
    channel: Optional[str] = Field(None, description="Attribution channel")
    session_id: Optional[str] = None
    properties: dict[str, Any] = Field(default_factory=dict)


class EvaluateResponse(BaseModel):
    eligible: bool
    campaign_id: Optional[str] = None
    reward_tier: Optional[dict] = None
    reward_id: Optional[str] = None
    denial_reason: Optional[str] = None
    fraud_score: float = 0.0
    attribution_weight: float = 0.0
    vm_type: Optional[str] = None
    proof: Optional[dict] = None


# -- campaigns ----------------------------------------------------------

class RewardTierCreate(BaseModel):
    name: str
    amount_wei: int
    token_symbol: str = "ETH"
    description: str = ""
    vm_type: str = "evm"


class RewardRuleCreate(BaseModel):
    event_types: list[str]
    reward_tier: RewardTierCreate
    required_channel: Optional[str] = None
    min_attribution_weight: float = 0.0
    max_fraud_score: float = 40.0
    cooldown_seconds: int = 86_400
    max_per_user: int = 1
    requires_wallet: bool = True


class CampaignCreate(BaseModel):
    name: str
    description: str = ""
    rules: list[RewardRuleCreate] = Field(..., min_length=1)
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    total_budget_wei: int = Field(..., gt=0)
    chain_id: int = 1
    contract_address: Optional[str] = None
    vm_type: str = "evm"
    program_id: Optional[str] = None


class CampaignResponse(BaseModel):
    id: str
    name: str
    description: str
    rules: list[dict]
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    total_budget_wei: int
    spent_wei: int
    budget_remaining_wei: int
    active: bool
    chain_id: int
    contract_address: Optional[str] = None
    vm_type: str = "evm"
    program_id: Optional[str] = None


# -- queue --------------------------------------------------------------

class ProcessResponse(BaseModel):
    processed: int
    results: list[dict]


# ═══════════════════════════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/evaluate", response_model=None)
@api_response
async def evaluate_event(body: EvaluateRequest):
    """
    Full reward-evaluation pipeline:

    1. Evaluate the event with the fraud engine.
    2. Resolve attribution from the supplied journey touchpoints.
    3. Run the eligibility engine.
    4. If eligible, generate a multi-chain proof via the oracle signer.
    5. Enqueue the reward for tracking.
    """
    fraud_score = await _evaluate_fraud_score(body)
    attribution_weight = await _resolve_attribution_weight(body)

    # Step 3 -- Eligibility
    event_dict = {
        "event_type": body.event_type,
        "channel": body.channel,
        "session_id": body.session_id,
        "properties": body.properties,
    }

    result: EligibilityResult = await _engine.evaluate(
        event=event_dict,
        fraud_score=fraud_score,
        attribution_weight=attribution_weight,
        user_address=body.user_address,
    )

    response = EvaluateResponse(
        eligible=result.eligible,
        campaign_id=result.campaign_id or None,
        reward_tier=result.reward_tier.to_dict() if result.reward_tier else None,
        denial_reason=result.denial_reason,
        fraud_score=result.fraud_score,
        attribution_weight=result.attribution_weight,
    )

    # Step 4 -- Generate multi-chain proof and enqueue if eligible
    if result.eligible and body.user_address and result.reward_tier:
        campaign = _engine.get_campaign(result.campaign_id)
        vm_type = VMType.from_string(campaign.vm_type)
        response.vm_type = vm_type.value

        # Generate a multi-chain proof directly
        multichain_proof = await _multichain_oracle.generate_proof(
            user=body.user_address,
            action_type=body.event_type,
            amount=result.reward_tier.amount_wei,
            vm_type=vm_type,
            chain_id=campaign.chain_id,
        )
        response.proof = multichain_proof.to_dict()

        # Also enqueue via the legacy queue for tracking and persistence
        reward_id = await _queue.enqueue(
            user_address=body.user_address,
            action_type=body.event_type,
            campaign_id=result.campaign_id,
            reward_amount_wei=result.reward_tier.amount_wei,
            chain_id=campaign.chain_id,
        )
        _engine.record_claim(body.user_address, result.campaign_id)
        response.reward_id = reward_id

    metrics.increment("rewards_evaluate_requests")
    return response.model_dump()


# -- campaign management ------------------------------------------------

@router.post("/campaigns", response_model=None)
@api_response
async def create_campaign(body: CampaignCreate):
    """Register a new reward campaign with multi-chain support."""
    # Validate vm_type early
    vm_type = VMType.from_string(body.vm_type)

    campaign_id = str(uuid.uuid4())

    rules = [
        RewardRule(
            event_types=r.event_types,
            reward_tier=RewardTier(
                name=r.reward_tier.name,
                amount_wei=r.reward_tier.amount_wei,
                token_symbol=r.reward_tier.token_symbol,
                description=r.reward_tier.description,
                vm_type=body.vm_type,
            ),
            required_channel=r.required_channel,
            min_attribution_weight=r.min_attribution_weight,
            max_fraud_score=r.max_fraud_score,
            cooldown_seconds=r.cooldown_seconds,
            max_per_user=r.max_per_user,
            requires_wallet=r.requires_wallet,
        )
        for r in body.rules
    ]

    # Resolve the contract address: use explicit override, then program_id
    # (for Solana), then fall back to the chain config default.
    chain_cfg = _multichain_config.get_chain_config(vm_type)
    resolved_contract = (
        body.contract_address
        or body.program_id
        or chain_cfg.contract_address
    )

    campaign = Campaign(
        id=campaign_id,
        name=body.name,
        description=body.description,
        rules=rules,
        start_time=_parse_optional_datetime(body.start_time),
        end_time=_parse_optional_datetime(body.end_time),
        total_budget_wei=body.total_budget_wei,
        chain_id=body.chain_id,
        contract_address=resolved_contract,
        vm_type=body.vm_type,
        program_id=body.program_id,
    )

    _engine.register_campaign(campaign)
    return campaign.to_dict()


@router.get("/campaigns", response_model=None)
@api_response
async def list_campaigns():
    """List all registered reward campaigns."""
    campaigns = _engine.list_campaigns()
    return [c.to_dict() for c in campaigns]


@router.get("/campaigns/{campaign_id}", response_model=None)
@api_response
async def get_campaign(campaign_id: str):
    """Get a single campaign by ID."""
    campaign = _engine.get_campaign(campaign_id)
    return campaign.to_dict()


# -- queue management ---------------------------------------------------

@router.get("/queue/stats", response_model=None)
@api_response
async def queue_stats():
    """Return current reward queue statistics."""
    return _queue.get_stats()


@router.get("/user/{address}", response_model=None)
@api_response
async def get_user_rewards(address: str):
    """Return all rewards for a given wallet address."""
    rewards = _queue.get_user_rewards(address)
    return [r.to_dict() for r in rewards]


@router.post("/process", response_model=None)
@api_response
async def process_queue():
    """Trigger processing of all pending rewards in the queue."""
    results = await _queue.process_all()
    return {
        "processed": len(results),
        "results": [r.to_dict() for r in results],
    }


@router.get("/proof/{reward_id}", response_model=None)
@api_response
async def get_reward_proof(reward_id: str):
    """
    Retrieve the proof for a specific reward.

    Returns 404 if the reward doesn't exist, or 409 if the proof has not
    been generated yet.
    """
    reward = _queue.get_reward(reward_id)

    if reward.proof is None:
        raise HTTPException(
            status_code=409,
            detail=f"Proof not yet available; reward status={reward.status}",
        )

    return {
        "reward_id": reward.id,
        "status": reward.status,
        "proof": reward.proof,
    }


# ═══════════════════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ═══════════════════════════════════════════════════════════════════════════

async def _evaluate_fraud_score(body: EvaluateRequest) -> float:
    event = {
        "event_type": body.event_type,
        "channel": body.channel,
        "session_id": body.session_id,
        "properties": body.properties,
    }
    context = {
        "user_address": body.user_address,
        "session_id": body.session_id,
        **body.properties,
    }
    result = await _fraud_engine.evaluate(event, context)
    return float(result.composite_score)


async def _resolve_attribution_weight(body: EvaluateRequest) -> float:
    raw_touchpoints = body.properties.get("touchpoints") or []
    if not raw_touchpoints:
        raw_touchpoints = [{
            "channel": body.channel or "direct",
            "source": body.properties.get("source", body.channel or "direct"),
            "campaign": body.properties.get("campaign", ""),
            "timestamp": body.properties.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            "event_type": body.event_type,
            "properties": body.properties,
        }]
    result = await _attribution_resolver.resolve(
        user_id=body.user_address or body.session_id or "anonymous",
        event={"event_type": body.event_type, "properties": body.properties},
        touchpoints=raw_touchpoints,
        model_name=body.properties.get("attribution_model"),
    )
    if not result.credits:
        return 0.0
    return min(max(float(sum(c.weight for c in result.credits)), 0.0), 1.0)


def _parse_optional_datetime(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO datetime string or return ``None``."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
