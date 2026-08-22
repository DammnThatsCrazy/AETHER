"""
Aether Backend — Reward Enablement Routes (A6)

Full API surface for attribution-verified reward eligibility. Aether verifies
eligibility and produces reward action payloads; tenants execute rewards through
their own configured rails. Aether never holds, transfers, or distributes rewards.

See docs/source-of-truth/REWARD_NO_CUSTODY_MODEL.md for the custody boundary.

Tenant-scoped endpoints (require auth middleware):
    Campaigns:   POST/GET/PATCH /campaigns, /campaigns/{id}/pause|resume|archive
    Rules:       POST/GET/PATCH /campaigns/{id}/rules, /rules/{id}/enable|disable
    Evaluation:  POST /evaluate, POST /evaluate/batch
    Decisions:   GET /decisions, GET /decisions/{id}
    Actions:     GET /actions, GET /actions/{id}/approve|reject|deliver|cancel
    Proofs:      GET /proofs, POST /proofs/verify, POST /proofs/{id}/revoke
    Receipts:    POST/GET /receipts, GET /receipts/{id}
    Rails:       POST/GET/PATCH /rails, POST /rails/{id}/verify|disable

Legacy endpoints (local/test mode backward compatibility):
    GET  /queue/stats
    GET  /user/{address}
    POST /process
    GET  /proof/{reward_id}
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from repositories.repos import get_pool
from services.oracle.multichain_signer import (
    ChainConfig,
    MultiChainProofConfig,
    MultiChainSigner,
    VMType,
)
from services.oracle.signer import OracleSigner, ProofConfig
from services.rewards.eligibility import (
    Campaign,
    EligibilityEngine,
    EligibilityResult,
    RewardRule,
    RewardTier,
)
from services.rewards.policy_engine import (
    AttributionResultInput,
    ConsentSnapshotInput,
    FraudDecisionInput,
    IdentityInput,
    RewardPolicyEngine,
)
from services.rewards.budget import BudgetReservationService
from services.rewards.queue import RewardQueue
from services.rewards.rails import DeliveryResult, RailUnavailableError, get_rail_adapter
from services.rewards.repositories import (
    ContractRegistryRepository,
    RewardActionRepository,
    RewardAuditEvidenceRepository,
    RewardAuditRepository,
    RewardCampaignRepository,
    RewardDecisionRepository,
    RewardProofRepository,
    RewardRailConfigRepository,
    RewardReceiptRepository,
    RewardRuleRepository,
)
from services.measurement.repositories.attribution_run_repo import AttributionRunRepository
from shared.decorators import api_response
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.service.rewards")

router = APIRouter(prefix="/v1/rewards", tags=["Rewards"])

_HARDHAT_TEST_KEY = "ac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
_PROOF_EXPIRY_SECONDS = int(os.environ.get("PROOF_EXPIRY_SECONDS", "3600"))


# ═══════════════════════════════════════════════════════════════════════════
# LEGACY SINGLETONS (local/test backward compatibility)
# ═══════════════════════════════════════════════════════════════════════════
# The legacy in-memory eligibility/queue/proof stack signs with the LOCAL
# bootstrap key only. It is initialized lazily so importing this module never
# reads a signer key: in staging/production the durable policy-engine path
# resolves TENANT signer credentials via services/rewards/signing.py, and the
# legacy endpoints fail closed with SignerUnavailableError instead of ever
# touching a deployment-global ORACLE_SIGNER_KEY.

_chain_configs: dict[VMType, ChainConfig] = {
    VMType.EVM: ChainConfig(
        chain_id=int(os.environ.get("EVM_CHAIN_ID", "1")),
        contract_address=os.environ.get("EVM_CONTRACT_ADDRESS", "0x5FbDB2315678afecb367f032d93F642f64180aa3"),
        proof_expiry_seconds=_PROOF_EXPIRY_SECONDS,
    ),
    VMType.SVM: ChainConfig(
        chain_id=int(os.environ.get("SVM_CHAIN_ID", "101")),
        contract_address=os.environ.get("SVM_PROGRAM_ID", "AetherRwd1111111111111111111111111111111111"),
        proof_expiry_seconds=_PROOF_EXPIRY_SECONDS,
    ),
    VMType.BITCOIN: ChainConfig(
        chain_id=int(os.environ.get("BTC_CHAIN_ID", "0")),
        contract_address=os.environ.get("BTC_INSCRIPTION_ADDRESS", "bc1qaetherrewards000000000000000000000000"),
        proof_expiry_seconds=_PROOF_EXPIRY_SECONDS,
    ),
    VMType.MOVEVM: ChainConfig(
        chain_id=int(os.environ.get("SUI_CHAIN_ID", "1")),
        contract_address=os.environ.get("SUI_MODULE_ADDRESS", "0x" + "a3" * 32),
        proof_expiry_seconds=_PROOF_EXPIRY_SECONDS,
    ),
    VMType.NEAR: ChainConfig(
        chain_id=int(os.environ.get("NEAR_CHAIN_ID", "0")),
        contract_address=os.environ.get("NEAR_CONTRACT_ID", "aether-rewards.near"),
        proof_expiry_seconds=_PROOF_EXPIRY_SECONDS,
    ),
    VMType.TVM: ChainConfig(
        chain_id=int(os.environ.get("TRON_CHAIN_ID", "728126428")),
        contract_address=os.environ.get("TRON_CONTRACT_ADDRESS", "0x" + "b4" * 20),
        proof_expiry_seconds=_PROOF_EXPIRY_SECONDS,
    ),
    VMType.COSMOS: ChainConfig(
        chain_id=int(os.environ.get("COSMOS_CHAIN_ID", "1")),
        contract_address=os.environ.get("COSMOS_CONTRACT_ADDRESS", "cosmos1aetherrewards00000000000000000000000"),
        proof_expiry_seconds=_PROOF_EXPIRY_SECONDS,
    ),
}

class _LegacyProofStack:
    """Lazily-initialized local/test proof stack (bootstrap-key-signed)."""

    def __init__(self) -> None:
        self._initialized = False
        self.multichain_config: Optional[MultiChainProofConfig] = None
        self.multichain_oracle: Optional[MultiChainSigner] = None
        self.legacy_oracle: Optional[OracleSigner] = None
        self.queue: Optional[RewardQueue] = None

    def get(self) -> "_LegacyProofStack":
        if not self._initialized:
            from services.rewards.signing import local_bootstrap_key

            key = local_bootstrap_key()  # raises outside local/test — fail closed
            self.multichain_config = MultiChainProofConfig(
                signer_private_key=key, chain_configs=_chain_configs
            )
            self.multichain_oracle = MultiChainSigner(self.multichain_config)
            self.legacy_oracle = OracleSigner(ProofConfig(
                signer_private_key=key,
                contract_address=_chain_configs[VMType.EVM].contract_address,
                chain_id=_chain_configs[VMType.EVM].chain_id,
                proof_expiry_seconds=_PROOF_EXPIRY_SECONDS,
            ))
            self.queue = RewardQueue(self.legacy_oracle)
            self._initialized = True
        return self


_legacy_stack = _LegacyProofStack()
_engine = EligibilityEngine()
_policy_engine = RewardPolicyEngine()
# Durable, concurrency-safe campaign budget reservations (reserve→commit→release).
_budget_service = BudgetReservationService()


async def _release_reservation(action: dict, tenant_id: str, reason: str) -> None:
    """Best-effort release of a budget reservation tied to an action."""
    res_id = (action or {}).get("reservation_id")
    if not res_id:
        return
    try:
        await _budget_service.release(res_id, tenant_id=tenant_id)
        logger.info("budget reservation released res=%s reason=%s", res_id, reason)
    except Exception as exc:  # never fail the request path on a ledger hiccup
        logger.warning("budget reservation release failed res=%s: %s", res_id, exc)


async def _commit_reservation(res_id: Optional[str], tenant_id: str, reason: str) -> None:
    """Best-effort commit of a budget reservation (spend is now final)."""
    if not res_id:
        return
    try:
        await _budget_service.commit(res_id, tenant_id=tenant_id)
        logger.info("budget reservation committed res=%s reason=%s", res_id, reason)
    except Exception as exc:
        logger.warning("budget reservation commit failed res=%s: %s", res_id, exc)


# ═══════════════════════════════════════════════════════════════════════════
# SHARED REQUEST / RESPONSE MODELS
# ═══════════════════════════════════════════════════════════════════════════

# ── Campaigns ──────────────────────────────────────────────────────────────

class CampaignCreate(BaseModel):
    name: str
    description: str = ""
    project_id: Optional[str] = None
    status: str = "active"
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    reward_objective: Optional[str] = None
    default_execution_mode: str = "recommend_only"
    default_rail: str = "recommend_only"
    attribution_model: str = "last_touch"
    fraud_policy_id: Optional[str] = None
    consent_policy_id: Optional[str] = None
    budget_policy: dict = Field(default_factory=dict)
    external_campaign_ref: Optional[str] = None
    # Legacy fields (local mode, kept for backward compat)
    rules: Optional[list[dict]] = None
    total_budget_wei: Optional[int] = None
    chain_id: Optional[int] = None  # None → fall back to EVM_CHAIN_ID at evaluation time
    contract_address: Optional[str] = None
    vm_type: str = "evm"
    program_id: Optional[str] = None


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    reward_objective: Optional[str] = None
    default_execution_mode: Optional[str] = None
    default_rail: Optional[str] = None
    attribution_model: Optional[str] = None
    budget_policy: Optional[dict] = None
    external_campaign_ref: Optional[str] = None


# ── Rules ──────────────────────────────────────────────────────────────────

class RuleCreate(BaseModel):
    name: str
    description: str = ""
    event_types: list[str] = Field(..., min_length=1)
    required_channel: Optional[str] = None
    required_properties: dict = Field(default_factory=dict)
    min_attribution_weight: float = 0.0
    min_attribution_confidence: float = 0.0
    max_fraud_score: float = 40.0
    identity_confidence_min: float = 0.0
    wallet_binding_confidence_min: float = 0.0
    requires_wallet: bool = False
    requires_account: bool = False
    requires_consent_purposes: list[str] = Field(default_factory=list)
    cooldown_seconds: int = 86400
    max_per_user: int = 1
    max_total_uses: Optional[int] = None
    reward_amount: Optional[float] = None
    reward_unit: Optional[str] = None
    reward_currency: Optional[str] = None
    reward_metadata: dict = Field(default_factory=dict)
    execution_mode: str = "recommend_only"
    rail: str = "recommend_only"
    priority: int = 0


class RuleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    event_types: Optional[list[str]] = None
    required_channel: Optional[str] = None
    required_properties: Optional[dict] = None
    min_attribution_weight: Optional[float] = None
    min_attribution_confidence: Optional[float] = None
    max_fraud_score: Optional[float] = None
    identity_confidence_min: Optional[float] = None
    wallet_binding_confidence_min: Optional[float] = None
    requires_wallet: Optional[bool] = None
    requires_account: Optional[bool] = None
    requires_consent_purposes: Optional[list[str]] = None
    cooldown_seconds: Optional[int] = None
    max_per_user: Optional[int] = None
    max_total_uses: Optional[int] = None
    reward_amount: Optional[float] = None
    reward_unit: Optional[str] = None
    reward_currency: Optional[str] = None
    reward_metadata: Optional[dict] = None
    execution_mode: Optional[str] = None
    rail: Optional[str] = None
    priority: Optional[int] = None


# ── Evaluate ───────────────────────────────────────────────────────────────

class EvaluateRequest(BaseModel):
    event_type: str = Field(..., description="e.g. conversion, signup, referral")
    event_id: Optional[str] = None
    tenant_id: Optional[str] = Field(None, description="Required in non-local environments")
    project_id: Optional[str] = None
    user_id: Optional[str] = None
    account_ref: Optional[str] = None
    wallet_address: Optional[str] = None
    user_address: Optional[str] = Field(None, description="Deprecated alias for wallet_address")
    identity_cluster_id: Optional[str] = None
    journey_id: Optional[str] = None
    attribution_result_id: Optional[str] = None
    fraud_decision_id: Optional[str] = None
    consent_snapshot_id: Optional[str] = None
    channel: Optional[str] = Field(None, description="Attribution channel")
    session_id: Optional[str] = None
    properties: dict = Field(default_factory=dict)
    idempotency_key: Optional[str] = None
    recommend_only_without_attribution: bool = False

    @property
    def effective_wallet_address(self) -> Optional[str]:
        return self.wallet_address or self.user_address


class EvaluateResponse(BaseModel):
    eligible: bool
    decision: str = "ineligible"
    decision_reason: Optional[str] = None
    denial_reason: Optional[str] = None
    decision_id: Optional[str] = None
    campaign_id: Optional[str] = None
    rule_id: Optional[str] = None
    execution_mode: Optional[str] = None
    rail: Optional[str] = None
    next_action: Optional[dict] = None
    action_id: Optional[str] = None
    proof: Optional[dict] = None
    attribution: Optional[dict] = None
    fraud: Optional[dict] = None
    identity: Optional[dict] = None
    reward: Optional[dict] = None
    # Legacy backward-compat fields
    reward_id: Optional[str] = None
    reward_tier: Optional[dict] = None
    fraud_score: float = 0.0
    attribution_weight: float = 0.0
    vm_type: Optional[str] = None


# ── Actions ────────────────────────────────────────────────────────────────

class ActionApproveRequest(BaseModel):
    reason: Optional[str] = None


class ActionRejectRequest(BaseModel):
    reason: str = Field(..., description="Required reason for rejection")


class ActionCancelRequest(BaseModel):
    reason: Optional[str] = None


# ── Proofs ─────────────────────────────────────────────────────────────────

class ProofRevokeRequest(BaseModel):
    reason: str = Field(..., description="Required reason for revocation")


class ProofVerifyRequest(BaseModel):
    user: str
    action_type: str
    amount_wei: int
    nonce: str
    expiry: int
    chain_id: int
    contract_address: str
    signature: str
    message_hash: str


# ── Receipts ───────────────────────────────────────────────────────────────

class ReceiptCreate(BaseModel):
    decision_id: Optional[str] = None
    action_payload_id: Optional[str] = None
    proof_id: Optional[str] = None
    rail: str
    execution_mode: str
    external_execution_id: Optional[str] = None
    tx_hash: Optional[str] = None
    chain_id: Optional[int] = None
    provider: Optional[str] = None
    status: str = "unknown"
    receipt_payload: dict = Field(default_factory=dict)
    observed_at: Optional[datetime] = None


# ── Rails ──────────────────────────────────────────────────────────────────

class ContractRegistryCreate(BaseModel):
    chain_id: int
    contract_address: str
    contract_name: str
    # oracle_signer_address is required — must match Aether's oracle signer address.
    # Derive with: Account.from_key(ORACLE_SIGNER_KEY).address
    oracle_signer_address: str
    vm_type: str = "evm"
    allowed_campaign_ids: list[str] = Field(default_factory=list)
    abi_ref: Optional[str] = None


class RailConfigCreate(BaseModel):
    rail: str
    enabled: bool = False
    config: dict = Field(default_factory=dict)
    secret_ref: Optional[str] = None
    webhook_url: Optional[str] = None
    contract_address: Optional[str] = None
    chain_id: Optional[int] = None
    vm_type: Optional[str] = None
    provider: Optional[str] = None
    verification_method: Optional[str] = None


class RailConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    config: Optional[dict] = None
    secret_ref: Optional[str] = None
    webhook_url: Optional[str] = None
    contract_address: Optional[str] = None
    chain_id: Optional[int] = None
    vm_type: Optional[str] = None
    provider: Optional[str] = None
    verification_method: Optional[str] = None


# ── Legacy campaign create (kept for backward compat with local mode) ───────

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


# ═══════════════════════════════════════════════════════════════════════════
# AUTH + REPO HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _get_tenant_id(request: Request, body_tenant_id: Optional[str] = None) -> str:
    """Extract tenant_id from auth middleware; fall back to body/env in local mode."""
    if hasattr(request.state, "tenant") and request.state.tenant:
        return request.state.tenant.tenant_id

    env = os.getenv("AETHER_ENV", "local").lower()
    if env in ("local", "test"):
        return body_tenant_id or os.getenv("DEFAULT_TENANT_ID", "tenant_local_dev")

    raise HTTPException(status_code=401, detail="Authentication required")


def _require_permission(request: Request, permission: str) -> None:
    """Enforce tenant permission via auth middleware; bypass in local mode."""
    if hasattr(request.state, "tenant") and request.state.tenant:
        request.state.tenant.require_permission(permission)


def _actor_id(request: Request) -> str:
    """Best-effort actor identity for audit/credential attribution."""
    tenant = getattr(request.state, "tenant", None)
    if tenant is None:
        return "system"
    return str(
        getattr(tenant, "principal_id", None)
        or getattr(tenant, "user_id", None)
        or getattr(tenant, "tenant_id", None)
        or "system"
    )


async def _get_repos() -> dict:
    pool = await get_pool()
    return {
        "campaigns": RewardCampaignRepository(),
        "rules": RewardRuleRepository(),
        "decisions": RewardDecisionRepository(),
        "actions": RewardActionRepository(),
        "proofs": RewardProofRepository(),
        "receipts": RewardReceiptRepository(),
        "audit": RewardAuditRepository(),
        "rail_configs": RewardRailConfigRepository(),
        "contracts": ContractRegistryRepository(),
        "audit_evidence": RewardAuditEvidenceRepository(),
    }


async def _audit(
    repos: dict,
    tenant_id: str,
    action: str,
    target_type: str,
    target_id: Optional[str],
    *,
    actor_type: str = "system",
    actor_id: Optional[str] = None,
    before_state: Optional[dict] = None,
    after_state: Optional[dict] = None,
    reason: Optional[str] = None,
    request_id: Optional[str] = None,
) -> None:
    try:
        await repos["audit"].append({
            "tenant_id": tenant_id,
            "actor_type": actor_type,
            "actor_id": actor_id,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "before_state": before_state,
            "after_state": after_state,
            "reason": reason,
            "request_id": request_id,
        })
    except Exception as exc:
        logger.warning(f"Audit log write failed (non-fatal): {exc}")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ═══════════════════════════════════════════════════════════════════════════
# FRAUD / ATTRIBUTION / CONSENT HEURISTICS
# ═══════════════════════════════════════════════════════════════════════════

async def _compute_fraud_score(properties: dict) -> float:
    ml_url = os.getenv("ML_SERVING_URL", "")
    if ml_url:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(f"{ml_url}/v1/predict", json={"type": "bot", "signals": properties})
                if resp.status_code == 200:
                    prediction = resp.json().get("data", {}).get("prediction", {})
                    return min(prediction.get("confidence", 0.0) * 100.0, 100.0)
        except Exception as e:
            logger.warning(f"ML fraud scoring unavailable: {e} — using heuristics")

    env = os.getenv("AETHER_ENV", "local").lower()
    if env not in ("local", "test"):
        logger.warning(f"DEGRADED: fraud scoring using heuristic fallback in {env} environment")
        metrics.increment("rewards_fraud_heuristic_fallback", labels={"env": env})

    score = 0.0
    if properties.get("vpn_detected"):
        score += 25.0
    if properties.get("bot_probability", 0) > 0.7:
        score += 35.0
    if properties.get("device_count", 1) > 5:
        score += 15.0
    return min(score, 100.0)


async def _compute_attribution_weight(
    channel: Optional[str],
    properties: dict,
    tenant_id: Optional[str] = None,
    profile_id: Optional[str] = None,
) -> float:
    """Return attribution weight from canonical credits when available.

    Priority:
    1. Canonical attribution_credits for the given conversion_id + profile
    2. Explicit attribution_weight_override in properties
    3. Channel-based heuristic fallback
    """
    conversion_id = properties.get("conversion_id")
    if conversion_id and tenant_id and profile_id:
        try:
            run_repo = AttributionRunRepository()
            credits = await run_repo.list_credits_for_conversion(
                tenant_id, conversion_id, active_only=True
            )
            if credits:
                # Sum credit weights for this profile_id across all credits
                profile_weight = sum(
                    float(c.get("credit_weight", 0))
                    for c in credits
                    if c.get("profile_id") == profile_id or c.get("campaign_id") == properties.get("campaign_id")
                )
                if profile_weight > 0:
                    return min(profile_weight, 1.0)
                # Any positive credit means the entity is in the attribution path
                total_weight = sum(float(c.get("credit_weight", 0)) for c in credits)
                if total_weight > 0:
                    return min(total_weight, 1.0)
        except Exception:
            pass  # fall through to heuristic

    base_weights: dict[str, float] = {
        "organic": 0.9, "social": 0.7, "referral": 0.8,
        "paid_search": 0.6, "email": 0.5, "direct": 1.0,
    }
    weight = base_weights.get(channel or "", 0.5)
    weight = properties.get("attribution_weight_override", weight)
    return min(max(float(weight), 0.0), 1.0)


def _build_fraud_input(fraud_decision_id: Optional[str], score: float, decision: str = "approve") -> Optional[FraudDecisionInput]:
    if not fraud_decision_id and score == 0.0:
        return None
    fid = fraud_decision_id or f"heuristic_{uuid.uuid4().hex[:8]}"
    return FraudDecisionInput(fraud_decision_id=fid, score=score, decision=decision)


def _build_attribution_input(
    attribution_result_id: Optional[str], channel: Optional[str], weight: float
) -> Optional[AttributionResultInput]:
    if not attribution_result_id and weight == 0.0:
        return None
    aid = attribution_result_id or f"heuristic_{uuid.uuid4().hex[:8]}"
    return AttributionResultInput(
        attribution_result_id=aid,
        model="channel_heuristic",
        attribution_weight=weight,
        confidence=weight,
        channel=channel,
    )


def _parse_optional_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


# ═══════════════════════════════════════════════════════════════════════════
# CAMPAIGN ROUTES
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/campaigns", response_model=None)
@api_response
async def create_campaign(request: Request, body: CampaignCreate):
    """Create a reward campaign for tenant-scoped eligibility evaluation."""
    _require_permission(request, "rewards:write")
    tenant_id = _get_tenant_id(request, body.model_dump().get("tenant_id"))
    repos = await _get_repos()

    campaign_data = {
        "name": body.name,
        "description": body.description,
        "project_id": body.project_id,
        "status": body.status,
        "start_time": body.start_time.isoformat() if body.start_time else None,
        "end_time": body.end_time.isoformat() if body.end_time else None,
        "reward_objective": body.reward_objective,
        "default_execution_mode": body.default_execution_mode,
        "default_rail": body.default_rail,
        "attribution_model": body.attribution_model,
        "fraud_policy_id": body.fraud_policy_id,
        "consent_policy_id": body.consent_policy_id,
        "budget_policy": body.budget_policy,
        "external_campaign_ref": body.external_campaign_ref,
        "contract_address": body.contract_address,
        # Omit chain_id when not supplied so the registry gate and adapter fall back
        # to EVM_CHAIN_ID at evaluation time rather than hardcoding mainnet (1).
        **( {"chain_id": body.chain_id} if body.chain_id is not None else {} ),
        "vm_type": body.vm_type,
        "program_id": body.program_id,
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
    }

    campaign = await repos["campaigns"].create(tenant_id, campaign_data)
    await _audit(repos, tenant_id, "campaign.created", "reward_campaign", campaign["id"],
                 after_state=campaign)

    # Legacy: register in-memory engine for local mode if rules were provided
    env = os.getenv("AETHER_ENV", "local").lower()
    if env in ("local", "test") and body.rules:
        _register_legacy_campaign(campaign["id"], body)

    metrics.increment("rewards_campaigns_created_total", labels={"tenant_id": tenant_id})
    return campaign


@router.get("/campaigns", response_model=None)
@api_response
async def list_campaigns(
    request: Request,
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List reward campaigns for the authenticated tenant."""
    _require_permission(request, "rewards:read")
    tenant_id = _get_tenant_id(request)
    repos = await _get_repos()

    env = os.getenv("AETHER_ENV", "local").lower()
    if env in ("local", "test"):
        legacy = _engine.list_campaigns()
        if legacy:
            return [c.to_dict() for c in legacy]

    campaigns = await repos["campaigns"].list(tenant_id, status=status, limit=limit, offset=offset)
    return campaigns


@router.get("/campaigns/{campaign_id}", response_model=None)
@api_response
async def get_campaign(request: Request, campaign_id: str):
    """Get a single reward campaign by ID."""
    _require_permission(request, "rewards:read")
    tenant_id = _get_tenant_id(request)

    env = os.getenv("AETHER_ENV", "local").lower()
    if env in ("local", "test"):
        try:
            campaign = _engine.get_campaign(campaign_id)
            return campaign.to_dict()
        except Exception:
            pass

    repos = await _get_repos()
    return await repos["campaigns"].get(campaign_id, tenant_id)


@router.patch("/campaigns/{campaign_id}", response_model=None)
@api_response
async def update_campaign(request: Request, campaign_id: str, body: CampaignUpdate):
    """Update mutable campaign fields."""
    _require_permission(request, "rewards:write")
    tenant_id = _get_tenant_id(request)
    repos = await _get_repos()

    before = await repos["campaigns"].get(campaign_id, tenant_id)
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if "start_time" in patch and isinstance(patch["start_time"], datetime):
        patch["start_time"] = patch["start_time"].isoformat()
    if "end_time" in patch and isinstance(patch["end_time"], datetime):
        patch["end_time"] = patch["end_time"].isoformat()
    patch["updated_at"] = _utc_now()

    updated = await repos["campaigns"].update(campaign_id, patch)
    await _audit(repos, tenant_id, "campaign.updated", "reward_campaign", campaign_id,
                 before_state=before, after_state=updated)
    return updated


@router.post("/campaigns/{campaign_id}/pause", response_model=None)
@api_response
async def pause_campaign(request: Request, campaign_id: str):
    """Pause an active campaign (stops new eligibility evaluations)."""
    _require_permission(request, "rewards:write")
    tenant_id = _get_tenant_id(request)
    repos = await _get_repos()
    before = await repos["campaigns"].get(campaign_id, tenant_id)
    updated = await repos["campaigns"].update_status(campaign_id, tenant_id, "paused")
    await _audit(repos, tenant_id, "campaign.paused", "reward_campaign", campaign_id,
                 before_state=before, after_state=updated)
    return updated


@router.post("/campaigns/{campaign_id}/resume", response_model=None)
@api_response
async def resume_campaign(request: Request, campaign_id: str):
    """Resume a paused campaign."""
    _require_permission(request, "rewards:write")
    tenant_id = _get_tenant_id(request)
    repos = await _get_repos()
    before = await repos["campaigns"].get(campaign_id, tenant_id)
    updated = await repos["campaigns"].update_status(campaign_id, tenant_id, "active")
    await _audit(repos, tenant_id, "campaign.resumed", "reward_campaign", campaign_id,
                 before_state=before, after_state=updated)
    return updated


@router.post("/campaigns/{campaign_id}/archive", response_model=None)
@api_response
async def archive_campaign(request: Request, campaign_id: str):
    """Archive a campaign (soft delete; audit log preserved)."""
    _require_permission(request, "rewards:write")
    tenant_id = _get_tenant_id(request)
    repos = await _get_repos()
    before = await repos["campaigns"].get(campaign_id, tenant_id)
    updated = await repos["campaigns"].archive(campaign_id, tenant_id)
    await _audit(repos, tenant_id, "campaign.archived", "reward_campaign", campaign_id,
                 before_state=before, after_state=updated)
    return updated


# ═══════════════════════════════════════════════════════════════════════════
# RULE ROUTES
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/campaigns/{campaign_id}/rules", response_model=None)
@api_response
async def create_rule(request: Request, campaign_id: str, body: RuleCreate):
    """Add a reward rule to a campaign."""
    _require_permission(request, "rewards:write")
    tenant_id = _get_tenant_id(request)
    repos = await _get_repos()

    # Verify campaign belongs to tenant
    await repos["campaigns"].get(campaign_id, tenant_id)

    rule_data = body.model_dump()
    rule_data["created_at"] = _utc_now()
    rule_data["updated_at"] = _utc_now()

    rule = await repos["rules"].create(tenant_id, campaign_id, rule_data)
    await _audit(repos, tenant_id, "rule.created", "reward_rule", rule["id"],
                 after_state=rule)
    metrics.increment("rewards_rules_created_total", labels={"tenant_id": tenant_id})
    return rule


@router.get("/campaigns/{campaign_id}/rules", response_model=None)
@api_response
async def list_rules(request: Request, campaign_id: str):
    """List rules for a campaign, sorted by priority."""
    _require_permission(request, "rewards:read")
    tenant_id = _get_tenant_id(request)
    repos = await _get_repos()
    await repos["campaigns"].get(campaign_id, tenant_id)
    return await repos["rules"].list_for_campaign(campaign_id, tenant_id)


@router.get("/rules/{rule_id}", response_model=None)
@api_response
async def get_rule(request: Request, rule_id: str):
    """Get a single reward rule by ID."""
    _require_permission(request, "rewards:read")
    tenant_id = _get_tenant_id(request)
    repos = await _get_repos()
    return await repos["rules"].get(rule_id, tenant_id)


@router.patch("/rules/{rule_id}", response_model=None)
@api_response
async def update_rule(request: Request, rule_id: str, body: RuleUpdate):
    """Update mutable rule fields."""
    _require_permission(request, "rewards:write")
    tenant_id = _get_tenant_id(request)
    repos = await _get_repos()

    before = await repos["rules"].get(rule_id, tenant_id)
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    patch["updated_at"] = _utc_now()
    updated = await repos["rules"].update(rule_id, patch)
    await _audit(repos, tenant_id, "rule.updated", "reward_rule", rule_id,
                 before_state=before, after_state=updated)
    return updated


@router.post("/rules/{rule_id}/enable", response_model=None)
@api_response
async def enable_rule(request: Request, rule_id: str):
    """Enable a disabled reward rule."""
    _require_permission(request, "rewards:write")
    tenant_id = _get_tenant_id(request)
    repos = await _get_repos()
    updated = await repos["rules"].set_active(rule_id, tenant_id, True)
    await _audit(repos, tenant_id, "rule.enabled", "reward_rule", rule_id)
    return updated


@router.post("/rules/{rule_id}/disable", response_model=None)
@api_response
async def disable_rule(request: Request, rule_id: str):
    """Disable a reward rule (stops it matching events)."""
    _require_permission(request, "rewards:write")
    tenant_id = _get_tenant_id(request)
    repos = await _get_repos()
    updated = await repos["rules"].set_active(rule_id, tenant_id, False)
    await _audit(repos, tenant_id, "rule.disabled", "reward_rule", rule_id)
    return updated


# ═══════════════════════════════════════════════════════════════════════════
# EVALUATE + DECISIONS
# ═══════════════════════════════════════════════════════════════════════════

async def _evaluate_event_core(request: Request, body: EvaluateRequest) -> dict:
    """Core evaluate logic shared by /evaluate and /evaluate/batch."""
    env = os.getenv("AETHER_ENV", "local").lower()
    is_local = env in ("local", "test")

    # Require tenant_id in production
    if not is_local and not body.tenant_id:
        raise HTTPException(status_code=422, detail="tenant_id is required in non-local environments")

    tenant_id = _get_tenant_id(request, body.tenant_id)

    # ── Fraud scoring ────────────────────────────────────────────────────
    fraud_score = await _compute_fraud_score(body.properties)
    fraud_decision = "approve" if fraud_score < 40.0 else ("review" if fraud_score < 70.0 else "reject")
    fraud_input = _build_fraud_input(body.fraud_decision_id, fraud_score, fraud_decision)

    # ── Attribution weight ───────────────────────────────────────────────
    attribution_weight = await _compute_attribution_weight(
        body.channel, body.properties,
        tenant_id=tenant_id, profile_id=body.user_id,
    )
    attribution_input = _build_attribution_input(
        body.attribution_result_id, body.channel, attribution_weight
    )

    # ── Identity ─────────────────────────────────────────────────────────
    identity_input = IdentityInput(
        user_id=body.user_id,
        account_ref=body.account_ref,
        wallet_address=body.effective_wallet_address,
        identity_cluster_id=body.identity_cluster_id,
        journey_id=body.journey_id,
        identity_confidence=1.0,
        wallet_binding_confidence=1.0 if body.effective_wallet_address else 0.0,
    )

    # ── Consent ──────────────────────────────────────────────────────────
    consent_input: Optional[ConsentSnapshotInput] = None
    if body.consent_snapshot_id:
        consent_input = ConsentSnapshotInput(
            consent_snapshot_id=body.consent_snapshot_id,
            purposes_granted=["analytics", "marketing"],
        )

    # ── Policy evaluation ────────────────────────────────────────────────
    repos = await _get_repos()

    decision = await _policy_engine.evaluate(
        tenant_id=tenant_id,
        project_id=body.project_id,
        event_type=body.event_type,
        event_channel=body.channel,
        event_properties=body.properties,
        attribution=attribution_input,
        fraud=fraud_input,
        consent=consent_input,
        identity=identity_input,
        idempotency_key=body.idempotency_key,
        recommend_only_without_attribution=body.recommend_only_without_attribution,
        campaign_repo=repos["campaigns"],
        rule_repo=repos["rules"],
        decision_repo=repos["decisions"],
        budget_service=_budget_service,
    )

    # Registry-verified signer address, set by the onchain_claim pre-check below
    # and re-checked against the actually-signed proof after generation.
    _verified_signer: Optional[str] = None

    # ── Contract registry pre-check (before persisting decision) ─────────
    # Gate onchain_claim before create_once so an unregistered contract does not
    # consume cooldown/per-user/total-use caps by leaving an eligible=True row.
    if decision.eligible and decision.rail == "onchain_claim" and not is_local:
        # For idempotent retries, _decision_from_record reconstructs the decision
        # with campaign_id but no campaign dict. Hydrate so the registry check
        # uses the campaign's contract_address instead of falling back to the
        # global EVM_CONTRACT_ADDRESS env var.
        if not decision.campaign and decision.campaign_id:
            try:
                _hydrated = await repos["campaigns"].get(decision.campaign_id, tenant_id)
                decision.campaign = _hydrated
            except Exception:
                pass
        _campaign = decision.campaign or {}
        # Campaign-only chain identity outside local/test — mirror the adapter's
        # rule (OnchainClaimAdapter.build_action_payload) HERE, before the
        # decision is persisted. Falling back to a deployment-global
        # EVM_CONTRACT_ADDRESS/EVM_CHAIN_ID let the pre-check pass on a legacy
        # global address and persist an eligible decision (consuming
        # cooldown/use caps) that the adapter would then refuse — leaving the
        # caller an eligible response with no action or proof.
        _ANVIL_CONTRACT = "0x5fbdb2315678afecb367f032d93f642f64180aa3"
        _contract_address = _campaign.get("contract_address")
        if not _contract_address:
            raise HTTPException(
                status_code=422,
                detail=(
                    "onchain_claim rail requires an explicit campaign contract_address "
                    "outside local/test (deployment-global env fallbacks are refused "
                    "fail-closed)."
                ),
            )
        if str(_contract_address).lower() == _ANVIL_CONTRACT:
            raise HTTPException(
                status_code=422,
                detail=(
                    "onchain_claim refuses the Anvil/Hardhat default contract address "
                    "outside local/test."
                ),
            )
        _raw_chain_id = _campaign.get("chain_id")
        if not _raw_chain_id:
            raise HTTPException(
                status_code=422,
                detail=(
                    "onchain_claim rail requires an explicit campaign chain_id outside "
                    "local/test (deployment-global env fallbacks are refused fail-closed)."
                ),
            )
        _chain_id = int(_raw_chain_id)
        _registry_entry = await repos["contracts"].find_for_proof(
            tenant_id, _chain_id, _contract_address, decision.campaign_id or ""
        )
        if _registry_entry is None:
            raise HTTPException(
                status_code=403,
                detail=(
                    "Contract not in verified registry for this tenant. "
                    "Register and verify via POST /v1/rewards/contracts before generating proofs."
                ),
            )

        # ── SIGNER-ROTATION GUARD ────────────────────────────────────────
        # The registry row records the signer address the contract was verified
        # to accept. If the tenant has since rotated its reward_signer
        # credential, proofs signed by the new key would be rejected on chain
        # while the registry still says "verified". Compare the CURRENT active
        # signer's address with the verified row and fail closed on a mismatch,
        # rather than persisting a decision and emitting an unclaimable proof.
        _verified_signer = (_registry_entry.get("oracle_signer_address") or "").lower()
        if _verified_signer:
            try:
                from services.rewards.signing import (
                    resolve_reward_signer_address,
                    reward_credential_environment,
                )

                _current_signer = (
                    await resolve_reward_signer_address(
                        tenant_id, reward_credential_environment()
                    )
                ).lower()
            except Exception as exc:  # noqa: BLE001 — cannot confirm signer → fail closed
                raise HTTPException(
                    status_code=409,
                    detail=f"onchain_claim signer could not be resolved for verification: {exc}",
                )
            if _current_signer != _verified_signer:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "reward_signer has been rotated: the active signer "
                        f"({_current_signer}) does not match the address the contract "
                        f"registry was verified for ({_verified_signer}). Re-register and "
                        "re-verify the contract for the new signer before generating proofs."
                    ),
                )

        # ── EVM MAINNET AUDIT GATE ───────────────────────────────────────
        # Block mainnet on-chain reward activation unless external-audit
        # evidence is recorded for this contract. Local/testnet unaffected.
        from services.rewards.onchain_gate import (
            MainnetAuditRequiredError,
            assert_mainnet_audit_evidence,
        )
        try:
            await assert_mainnet_audit_evidence(
                tenant_id=tenant_id,
                chain_id=_chain_id,
                contract_address=_contract_address,
                evidence_repo=repos["audit_evidence"],
                is_local=is_local,
            )
        except MainnetAuditRequiredError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc))

    # ── Persist decision ─────────────────────────────────────────────────
    decision_record: Optional[dict] = None
    try:
        decision_record, _ = await repos["decisions"].create_once(
            tenant_id=tenant_id,
            idempotency_key=body.idempotency_key,
            data={
                "project_id": body.project_id,
                "campaign_id": decision.campaign_id,
                "rule_id": decision.rule_id,
                "event_id": body.event_id,
                "journey_id": body.journey_id,
                "identity_cluster_id": body.identity_cluster_id,
                "actor_id": body.user_id,
                "user_id": body.user_id,
                "account_ref": body.account_ref,
                "wallet_address": body.effective_wallet_address,
                "eligible": decision.eligible,
                "decision": decision.decision,
                "decision_reason": decision.decision_reason,
                "denial_reason": decision.denial_reason,
                "attribution_weight": attribution_weight,
                "fraud_score": fraud_score,
                "execution_mode": decision.execution_mode,
                "rail": decision.rail,
                "reservation_id": decision.reservation_id,
                "created_at": _utc_now(),
            },
        )
    except Exception as exc:
        logger.warning(f"Decision persistence failed (non-fatal in local mode): {exc}")

    decision_id = decision_record["id"] if decision_record else None

    # ── Build action payload if eligible ─────────────────────────────────
    action_id: Optional[str] = None
    proof_dict: Optional[dict] = None

    if decision.eligible and decision.rail and decision.rail != "recommend_only":
        try:
            adapter = get_rail_adapter(decision.rail)
            rail_config = {}
            try:
                rail_conf_record = await repos["rail_configs"].get_by_rail(tenant_id, decision.rail)
                rail_config = rail_conf_record.get("config", {}) if rail_conf_record else {}
            except Exception:
                pass

            idempotency_key = body.idempotency_key or str(uuid.uuid4())
            payload = await adapter.build_action_payload(
                decision=decision,
                rule=decision.rule or {},
                campaign=decision.campaign or {},
                tenant_id=tenant_id,
                idempotency_key=idempotency_key,
            )

            # build_action_payload returns an ENVELOPE
            # {rail, execution_mode, status, payload: {...}, [proof, proof_data,
            # payload_hash]}. Store the INNER delivery payload as
            # action["payload"] so the outbox senders and the inline adapters
            # find recipient_id / amount / idempotency_key DIRECTLY — nesting the
            # whole envelope made every internal_credit / stripe_credit /
            # x402_credit action deliver amount=0 and fail (and wrapped the
            # tenant_webhook body one level too deep). Envelope-only artifacts the
            # delivery payload does not carry (onchain proof, webhook
            # payload_hash) are preserved at the action level.
            inner_payload = (
                payload.get("payload")
                if isinstance(payload.get("payload"), dict)
                else payload
            )
            action_data = {
                "decision_id": decision_id,
                "campaign_id": decision.campaign_id,
                "rule_id": decision.rule_id,
                "rail": decision.rail,
                "execution_mode": decision.execution_mode or "recommend_only",
                "payload": inner_payload,
                "status": payload.get("status", "created"),
                "delivery_attempts": 0,
                # Carry the budget reservation so reject/cancel release it and
                # receipt/delivery commit it (reserve→commit→release lifecycle).
                "reservation_id": decision.reservation_id,
                "created_at": _utc_now(),
                "updated_at": _utc_now(),
            }
            for _artifact in ("proof", "proof_data", "payload_hash"):
                if _artifact in payload:
                    action_data[_artifact] = payload[_artifact]
            action_record = await repos["actions"].create(tenant_id, action_data)
            action_id = action_record["id"]

            # Delivery routing.
            from services.rewards.senders import has_sender

            if has_sender(decision.rail):
                # DURABLE outbox: EVERY sender-backed rail (tenant_webhook,
                # internal_credit, stripe_credit, x402_credit) delivers through
                # the outbox — enqueue and keep the action 'pending'; it is only
                # marked 'delivered' once the outbox records a ProviderReceipt,
                # never on the synchronous request path. The stripe_credit /
                # x402_credit adapters are outbox-only and RAISE if delivered
                # inline, so routing them here (not through adapter.deliver) is
                # required, not optional — otherwise their actions stay inert and
                # their budget reservations leak until the stale-reservation sweep.
                try:
                    from services.rewards.delivery_outbox import reward_delivery_outbox
                    await reward_delivery_outbox.enqueue(action_record, rail_config, tenant_id)
                    await repos["actions"].transition(action_id, tenant_id, "pending")
                except Exception as exc:
                    logger.error(f"{decision.rail} durable enqueue failed: {exc}", exc_info=True)
                    await repos["actions"].transition(
                        action_id, tenant_id, "failed",
                        extra={"last_delivery_error": str(exc)},
                    )
                    await _release_reservation(action_record, tenant_id, "outbox_enqueue_failed")
            elif decision.rail not in ("manual_approval", "onchain_claim"):
                # Deliver terminal/no-op rails (recommend_only, manual_export) inline.
                delivery: DeliveryResult = await adapter.deliver(action_record, rail_config)
                await repos["actions"].transition(
                    action_id, tenant_id, delivery.status,
                    extra={"last_delivery_error": delivery.error} if delivery.error else None,
                )

            # Extract proof for onchain_claim rail
            if decision.rail == "onchain_claim":
                proof_dict = payload.get("proof")
                # Re-check the ACTUALLY-signed proof's signer against the
                # registry-verified address. The earlier guard checked the
                # active signer address, but build_action_payload resolves the
                # key independently — a rotation between the two would slip a
                # proof signed by the new, unregistered key through. Fail closed
                # here (after the real signature) rather than emit an
                # unclaimable proof.
                if _verified_signer and isinstance(proof_dict, dict):
                    _signed_by = (proof_dict.get("signer_address") or "").lower()
                    if _signed_by and _signed_by != _verified_signer:
                        raise HTTPException(
                            status_code=409,
                            detail=(
                                "reward_signer rotated during proof generation: the proof "
                                f"was signed by {_signed_by}, which does not match the "
                                f"contract registry's verified signer ({_verified_signer}). "
                                "Re-register and re-verify the contract for the new signer."
                            ),
                        )

        except RailUnavailableError as exc:
            logger.warning(f"Rail {exc.rail} unavailable: {exc.reason}")
        except HTTPException:
            raise
        except Exception as exc:
            logger.error(f"Action payload creation failed: {exc}", exc_info=True)
            # Action never materialized → release the budget reservation so it
            # doesn't leak (no action row exists to carry/release it later).
            if action_id is None and decision.reservation_id:
                await _release_reservation(
                    {"reservation_id": decision.reservation_id}, tenant_id, "action_creation_failed"
                )

    # ── Legacy in-memory path (local mode fallback) ───────────────────────
    if is_local and not decision.campaign_id and body.effective_wallet_address:
        return await _legacy_evaluate(body, fraud_score, attribution_weight, decision)

    metrics.increment(
        "rewards_evaluate_requests",
        labels={"tenant_id": tenant_id, "eligible": str(decision.eligible)},
    )

    resp = EvaluateResponse(
        eligible=decision.eligible,
        decision=decision.decision,
        decision_reason=decision.decision_reason,
        denial_reason=decision.denial_reason,
        decision_id=decision_id,
        campaign_id=decision.campaign_id,
        rule_id=decision.rule_id,
        execution_mode=decision.execution_mode,
        rail=decision.rail,
        next_action=decision.next_action,
        action_id=action_id,
        reward_id=action_id,
        proof=proof_dict,
        attribution=decision.attribution,
        fraud=decision.fraud,
        identity=decision.identity,
        reward=decision.reward,
        fraud_score=fraud_score,
        attribution_weight=attribution_weight,
    )
    return resp.model_dump()


@router.post("/evaluate", response_model=None)
@api_response
async def evaluate_event(request: Request, body: EvaluateRequest):
    """
    Evaluate an event for reward eligibility.

    Aether verifies attribution, fraud, consent, and identity signals, then
    produces an eligibility decision and (if eligible) a reward action payload.
    Aether does not execute the reward; the tenant does.

    In non-local environments: tenant_id and idempotency_key are required.
    In local/test mode: defaults are used for backward compatibility.
    """
    return await _evaluate_event_core(request, body)


async def _legacy_evaluate(
    body: EvaluateRequest,
    fraud_score: float,
    attribution_weight: float,
    policy_decision,
) -> dict:
    """Local mode fallback: use in-memory EligibilityEngine + MultiChainSigner."""
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
        user_address=body.effective_wallet_address,
    )

    resp = EvaluateResponse(
        eligible=result.eligible,
        decision="eligible" if result.eligible else "ineligible",
        campaign_id=result.campaign_id or None,
        reward_tier=result.reward_tier.to_dict() if result.reward_tier else None,
        denial_reason=result.denial_reason,
        fraud_score=result.fraud_score,
        attribution_weight=result.attribution_weight,
    )

    if result.eligible and body.effective_wallet_address and result.reward_tier:
        campaign = _engine.get_campaign(result.campaign_id)
        vm_type = VMType.from_string(campaign.vm_type)
        resp.vm_type = vm_type.value

        multichain_proof = await _legacy_stack.get().multichain_oracle.generate_proof(
            user=body.effective_wallet_address,
            action_type=body.event_type,
            amount=result.reward_tier.amount_wei,
            vm_type=vm_type,
            chain_id=campaign.chain_id,
        )
        resp.proof = multichain_proof.to_dict()

        reward_id = await _legacy_stack.get().queue.enqueue(
            user_address=body.effective_wallet_address,
            action_type=body.event_type,
            campaign_id=result.campaign_id,
            reward_amount_wei=result.reward_tier.amount_wei,
            chain_id=campaign.chain_id,
        )
        _engine.record_claim(body.effective_wallet_address, result.campaign_id)
        resp.reward_id = reward_id
        resp.action_id = reward_id

    metrics.increment("rewards_evaluate_requests")
    return resp.model_dump()


@router.post("/evaluate/batch", response_model=None)
@api_response
async def batch_evaluate(request: Request, body: list[EvaluateRequest]):
    """Evaluate multiple events in a single request (max 50)."""
    _require_permission(request, "rewards:read")
    if len(body) > 50:
        raise HTTPException(status_code=422, detail="Batch size cannot exceed 50 events")

    results = []
    for item in body:
        try:
            result = await _evaluate_event_core(request, item)
            results.append({"success": True, "result": result})
        except HTTPException as exc:
            results.append({"success": False, "error": exc.detail, "event_type": item.event_type})
        except Exception as exc:
            results.append({"success": False, "error": str(exc), "event_type": item.event_type})
    return {"results": results, "count": len(results)}


@router.get("/decisions", response_model=None)
@api_response
async def list_decisions(
    request: Request,
    decision: Optional[str] = Query(None),
    campaign_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List eligibility decisions for the authenticated tenant."""
    _require_permission(request, "rewards:read")
    tenant_id = _get_tenant_id(request)
    repos = await _get_repos()

    filters: dict = {}
    if decision:
        filters["decision"] = decision
    if campaign_id:
        filters["campaign_id"] = campaign_id

    return await repos["decisions"].list(tenant_id, filters=filters, limit=limit, offset=offset)


@router.get("/decisions/{decision_id}", response_model=None)
@api_response
async def get_decision(request: Request, decision_id: str):
    """Get a single eligibility decision by ID."""
    _require_permission(request, "rewards:read")
    tenant_id = _get_tenant_id(request)
    repos = await _get_repos()
    return await repos["decisions"].get(decision_id, tenant_id)


# ═══════════════════════════════════════════════════════════════════════════
# ACTION ROUTES
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/actions", response_model=None)
@api_response
async def list_actions(
    request: Request,
    status: Optional[str] = Query(None),
    rail: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List reward action payloads for the authenticated tenant."""
    _require_permission(request, "rewards:read")
    tenant_id = _get_tenant_id(request)
    repos = await _get_repos()
    return await repos["actions"].list(tenant_id, status=status, rail=rail, limit=limit, offset=offset)


@router.get("/actions/{action_id}", response_model=None)
@api_response
async def get_action(request: Request, action_id: str):
    """Get a single reward action payload by ID."""
    _require_permission(request, "rewards:read")
    tenant_id = _get_tenant_id(request)
    repos = await _get_repos()
    return await repos["actions"].get(action_id, tenant_id)


@router.post("/actions/{action_id}/approve", response_model=None)
@api_response
async def approve_action(request: Request, action_id: str, body: ActionApproveRequest):
    """Approve a pending_approval action payload for delivery."""
    _require_permission(request, "rewards:approve")
    tenant_id = _get_tenant_id(request)
    repos = await _get_repos()

    before = await repos["actions"].get(action_id, tenant_id)
    if before.get("status") != "pending_approval":
        raise HTTPException(status_code=409, detail=f"Action is not pending_approval (status={before.get('status')})")

    updated = await repos["actions"].transition(action_id, tenant_id, "ready")
    await _audit(repos, tenant_id, "action.approved", "reward_action", action_id,
                 before_state=before, after_state=updated, reason=body.reason)
    metrics.increment("rewards_actions_approved_total", labels={"tenant_id": tenant_id})
    return updated


@router.post("/actions/{action_id}/reject", response_model=None)
@api_response
async def reject_action(request: Request, action_id: str, body: ActionRejectRequest):
    """Reject a pending_approval action payload."""
    _require_permission(request, "rewards:approve")
    tenant_id = _get_tenant_id(request)
    repos = await _get_repos()

    before = await repos["actions"].get(action_id, tenant_id)
    if before.get("status") != "pending_approval":
        raise HTTPException(status_code=409, detail=f"Action is not pending_approval (status={before.get('status')})")

    updated = await repos["actions"].transition(action_id, tenant_id, "rejected")
    # Reward abandoned → release its budget reservation back to the campaign.
    await _release_reservation(before, tenant_id, "action.rejected")
    await _audit(repos, tenant_id, "action.rejected", "reward_action", action_id,
                 before_state=before, after_state=updated, reason=body.reason)
    metrics.increment("rewards_actions_rejected_total", labels={"tenant_id": tenant_id})
    return updated


@router.post("/actions/{action_id}/deliver", response_model=None)
@api_response
async def deliver_action(request: Request, action_id: str):
    """Manually trigger delivery of a ready action payload."""
    _require_permission(request, "rewards:write")
    tenant_id = _get_tenant_id(request)
    repos = await _get_repos()

    action = await repos["actions"].get(action_id, tenant_id)
    if action.get("status") not in ("ready", "failed"):
        raise HTTPException(status_code=409, detail=f"Action cannot be delivered in status={action.get('status')}")

    rail = action.get("rail", "recommend_only")
    adapter = get_rail_adapter(rail)
    rail_config = {}
    try:
        rail_conf_record = await repos["rail_configs"].get_by_rail(tenant_id, rail)
        rail_config = rail_conf_record.get("config", {}) if rail_conf_record else {}
    except Exception:
        pass

    # Sender-backed rails deliver ONLY through the durable outbox (the
    # stripe_credit / x402_credit adapters raise if delivered inline). Enqueue
    # and return 'pending'; the outbox drives it to 'delivered' on a receipt.
    from services.rewards.senders import has_sender

    if has_sender(rail):
        try:
            from services.rewards.delivery_outbox import reward_delivery_outbox
            await reward_delivery_outbox.enqueue(action, rail_config, tenant_id)
            updated = await repos["actions"].transition(action_id, tenant_id, "pending")
            metrics.increment("rewards_actions_delivered_total", labels={"rail": rail, "tenant_id": tenant_id})
            return updated
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Rail {rail} enqueue failed: {exc}")

    try:
        delivery: DeliveryResult = await adapter.deliver(action, rail_config)
        updated = await repos["actions"].transition(
            action_id, tenant_id, delivery.status,
            extra={"last_delivery_error": delivery.error} if delivery.error else None,
        )
        if not delivery.success:
            await repos["actions"].increment_delivery_attempts(action_id, tenant_id, delivery.error)
        metrics.increment("rewards_actions_delivered_total", labels={"rail": rail, "tenant_id": tenant_id})
        return updated
    except RailUnavailableError as exc:
        raise HTTPException(status_code=422, detail=f"Rail {exc.rail} unavailable: {exc.reason}")


@router.post("/actions/{action_id}/cancel", response_model=None)
@api_response
async def cancel_action(request: Request, action_id: str, body: ActionCancelRequest):
    """Cancel an action payload."""
    _require_permission(request, "rewards:write")
    tenant_id = _get_tenant_id(request)
    repos = await _get_repos()

    before = await repos["actions"].get(action_id, tenant_id)
    if before.get("status") in ("delivered", "cancelled"):
        raise HTTPException(status_code=409, detail=f"Cannot cancel action in status={before.get('status')}")

    updated = await repos["actions"].transition(action_id, tenant_id, "cancelled")
    # Reward cancelled → release its budget reservation back to the campaign.
    await _release_reservation(before, tenant_id, "action.cancelled")
    await _audit(repos, tenant_id, "action.cancelled", "reward_action", action_id,
                 before_state=before, after_state=updated, reason=body.reason)
    return updated


# ═══════════════════════════════════════════════════════════════════════════
# PROOF ROUTES
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/proofs", response_model=None)
@api_response
async def list_proofs(
    request: Request,
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List on-chain claim proofs for the authenticated tenant."""
    _require_permission(request, "rewards:read")
    tenant_id = _get_tenant_id(request)
    repos = await _get_repos()
    return await repos["proofs"].list(tenant_id, status=status, limit=limit, offset=offset)


@router.get("/proofs/{proof_id}", response_model=None)
@api_response
async def get_proof(request: Request, proof_id: str):
    """Get a single on-chain claim proof by ID."""
    _require_permission(request, "rewards:read")
    tenant_id = _get_tenant_id(request)
    repos = await _get_repos()
    return await repos["proofs"].get(proof_id, tenant_id)


@router.post("/proofs/{proof_id}/revoke", response_model=None)
@api_response
async def revoke_proof(request: Request, proof_id: str, body: ProofRevokeRequest):
    """Revoke an unused proof (prevents on-chain claim)."""
    _require_permission(request, "rewards:write")
    tenant_id = _get_tenant_id(request)
    repos = await _get_repos()

    before = await repos["proofs"].get(proof_id, tenant_id)
    if before.get("status") == "used":
        raise HTTPException(status_code=409, detail="Cannot revoke a proof that has already been used")
    if before.get("status") == "revoked":
        raise HTTPException(status_code=409, detail="Proof is already revoked")

    updated = await repos["proofs"].mark_revoked(proof_id, tenant_id, reason=body.reason)
    await _audit(repos, tenant_id, "proof.revoked", "reward_proof", proof_id,
                 before_state=before, after_state=updated, reason=body.reason)
    return updated


@router.post("/proofs/verify", response_model=None)
@api_response
async def verify_proof_endpoint(request: Request, body: ProofVerifyRequest):
    """Verify an on-chain claim proof off-chain (signature + expiry check)."""
    _require_permission(request, "rewards:read")
    from services.oracle.signer import OracleProofSigner, RewardProof
    from services.oracle.verifier import is_proof_expired, verify_reward_proof

    proof = RewardProof(
        user=body.user,
        action_type=body.action_type,
        amount_wei=body.amount_wei,
        nonce=body.nonce,
        expiry=body.expiry,
        chain_id=body.chain_id,
        contract_address=body.contract_address,
        signature=body.signature,
        message_hash=body.message_hash,
    )
    expired = is_proof_expired(proof)
    valid = verify_reward_proof(proof, expected_signer=_legacy_stack.get().legacy_oracle.signer_address)
    return {
        "valid": valid,
        "expired": expired,
        "signer_match": valid and not expired,
        "expected_signer": _legacy_stack.get().legacy_oracle.signer_address,
    }


# ═══════════════════════════════════════════════════════════════════════════
# RECEIPT ROUTES
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/receipts", response_model=None)
@api_response
async def create_receipt(request: Request, body: ReceiptCreate):
    """Submit an execution receipt from a tenant rail (webhook, contract, etc.)."""
    _require_permission(request, "rewards:write")
    tenant_id = _get_tenant_id(request)
    repos = await _get_repos()

    receipt_data = {
        **body.model_dump(),
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
    }
    if receipt_data.get("observed_at") and isinstance(receipt_data["observed_at"], datetime):
        receipt_data["observed_at"] = receipt_data["observed_at"].isoformat()

    receipt = await repos["receipts"].create(tenant_id, receipt_data)

    # A confirmed execution receipt finalizes the spend → commit the budget
    # reservation tied to the action/decision (reserve→commit lifecycle).
    if body.status in ("success", "delivered", "confirmed", "executed"):
        res_id: Optional[str] = None
        try:
            if body.action_payload_id:
                action = await repos["actions"].get(body.action_payload_id, tenant_id)
                res_id = action.get("reservation_id")
            elif body.decision_id:
                decision = await repos["decisions"].get(body.decision_id, tenant_id)
                res_id = decision.get("reservation_id")
        except Exception as exc:
            logger.warning(f"receipt reservation lookup failed (non-fatal): {exc}")
        await _commit_reservation(res_id, tenant_id, "receipt.recorded")

    metrics.increment("rewards_receipts_created_total", labels={"rail": body.rail, "tenant_id": tenant_id})
    return receipt


@router.get("/receipts", response_model=None)
@api_response
async def list_receipts(
    request: Request,
    rail: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List execution receipts for the authenticated tenant."""
    _require_permission(request, "rewards:read")
    tenant_id = _get_tenant_id(request)
    repos = await _get_repos()
    return await repos["receipts"].list(tenant_id, rail=rail, status=status, limit=limit, offset=offset)


@router.get("/receipts/{receipt_id}", response_model=None)
@api_response
async def get_receipt(request: Request, receipt_id: str):
    """Get a single execution receipt by ID."""
    _require_permission(request, "rewards:read")
    tenant_id = _get_tenant_id(request)
    repos = await _get_repos()
    return await repos["receipts"].get(receipt_id, tenant_id)


# ═══════════════════════════════════════════════════════════════════════════
# RAIL CONFIGURATION ROUTES
# ═══════════════════════════════════════════════════════════════════════════

# Secret-bearing keys inside a rail ``config`` dict. Values under these keys
# are WRITE-ONLY: they are never returned by any rail API response and never
# persisted into audit before/after states.
_RAIL_SECRET_KEYS = frozenset({
    "signing_secret", "webhook_secret", "api_key", "api_secret",
    "secret", "token", "private_key", "signer_key",
})


def _redact_rail_config(record: Optional[dict]) -> Optional[dict]:
    """Return a deep-copied rail record with secret material replaced by
    presence markers (``has_<key>`` + short non-reversible fingerprint)."""
    if not isinstance(record, dict):
        return record
    import copy as _copy
    import hashlib as _hashlib

    redacted = _copy.deepcopy(record)
    cfg = redacted.get("config")
    if isinstance(cfg, dict):
        for key in list(cfg.keys()):
            if key in _RAIL_SECRET_KEYS and isinstance(cfg[key], str) and cfg[key]:
                fingerprint = _hashlib.sha256(cfg[key].encode("utf-8")).hexdigest()[:12]
                cfg[key] = "<redacted>"
                cfg[f"has_{key}"] = True
                cfg[f"{key}_fingerprint"] = fingerprint
    return redacted


@router.post("/rails", response_model=None)
@api_response
async def configure_rail(request: Request, body: RailConfigCreate):
    """Configure or update a delivery rail for the authenticated tenant."""
    _require_permission(request, "rewards:write")
    tenant_id = _get_tenant_id(request)
    repos = await _get_repos()

    # Intentionally-unsupported rails cannot be configured — fail closed before
    # touching the adapter, so an out-of-release rail is never activatable.
    from services.rewards.rail_matrix import classification_for, is_configurable

    classification = classification_for(body.rail)
    if classification is not None and not is_configurable(body.rail):
        raise HTTPException(
            status_code=422,
            detail={
                "rail": body.rail,
                "tier": classification.tier,
                "error": f"rail {body.rail!r} is {classification.tier} and cannot be "
                         f"configured: {classification.external_action or classification.summary}",
            },
        )

    # Reject an unknown rail up front (before any secret handling).
    try:
        adapter = get_rail_adapter(body.rail)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Unknown rail: {body.rail}")

    config_data = {
        **body.model_dump(),
        "status": "pending_verification",
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
    }

    # Credential-only: a submitted tenant_webhook signing secret is dual-written
    # into the credential authority and replaced by a secret_ref before the rail
    # config is ever persisted — plaintext never reaches the JSONB row or audit.
    # This runs BEFORE validation so a tenant submitting only the documented
    # nested config.signing_secret has it converted to a secret_ref that
    # validation then accepts, instead of being rejected 422 before the
    # dual-write could run.
    if body.rail == "tenant_webhook":
        inner = config_data.get("config") or {}
        submitted = inner.get("signing_secret") or config_data.get("signing_secret")
        if submitted:
            from services.rewards.webhook_secret import store_secret

            actor = _actor_id(request)
            secret_ref = await store_secret(tenant_id, submitted, actor=actor)
            inner.pop("signing_secret", None)
            config_data.pop("signing_secret", None)
            inner["secret_ref"] = secret_ref
            config_data["config"] = inner
            config_data["secret_ref"] = secret_ref

    # Validate config via adapter, against the (already dual-written) config so a
    # tenant_webhook secret_ref satisfies the HMAC-material requirement.
    errors = adapter.validate_config(config_data)
    if errors:
        raise HTTPException(status_code=422, detail={"rail": body.rail, "validation_errors": errors})

    rail_config = await repos["rail_configs"].create_or_update(tenant_id, body.rail, config_data)
    await _audit(repos, tenant_id, "rail.configured", "rail_config", rail_config.get("id"),
                 after_state=_redact_rail_config(rail_config))
    return _redact_rail_config(rail_config)


@router.get("/rails", response_model=None)
@api_response
async def list_rails(request: Request):
    """List configured delivery rails for the authenticated tenant."""
    _require_permission(request, "rewards:read")
    tenant_id = _get_tenant_id(request)
    repos = await _get_repos()
    return [_redact_rail_config(r) for r in await repos["rail_configs"].list(tenant_id)]


@router.get("/rails/{rail_id}", response_model=None)
@api_response
async def get_rail(request: Request, rail_id: str):
    """Get a single rail configuration by ID."""
    _require_permission(request, "rewards:read")
    tenant_id = _get_tenant_id(request)
    repos = await _get_repos()
    return _redact_rail_config(await repos["rail_configs"].get(rail_id, tenant_id))


@router.patch("/rails/{rail_id}", response_model=None)
@api_response
async def update_rail(request: Request, rail_id: str, body: RailConfigUpdate):
    """Update a rail configuration."""
    _require_permission(request, "rewards:write")
    tenant_id = _get_tenant_id(request)
    repos = await _get_repos()

    before = await repos["rail_configs"].get(rail_id, tenant_id)
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    patch["updated_at"] = _utc_now()

    # Credential-only: mirror configure_rail's dual-write exactly. A PATCH can
    # rotate a tenant_webhook signing secret via config.signing_secret just as
    # easily as a CREATE can set one — without this, the plaintext-purge
    # migration only ever runs once and every later PATCH would reintroduce a
    # plaintext secret into the row. Submitted secret is stored in the
    # credential authority and replaced by a secret_ref BEFORE persistence.
    rail = (before or {}).get("rail")
    if rail == "tenant_webhook":
        inner = patch.get("config") or {}
        submitted = inner.get("signing_secret") or patch.get("signing_secret")
        if submitted:
            # Validate the MERGED (existing + patch) config BEFORE rotating the
            # credential. Rotating first and then rejecting the update on an
            # invalid field (e.g. a malformed webhook_url) would leave the rail
            # row unchanged but the ACTIVE secret already rotated — subsequent
            # deliveries would then sign with a secret from a rejected config
            # and fail receiver verification. Fail closed before store_secret.
            before_config = (before or {}).get("config") or {}
            merged_config = {**before_config, **inner}
            validation_target = {
                "webhook_url": (
                    patch.get("webhook_url")
                    or merged_config.get("webhook_url")
                    or (before or {}).get("webhook_url")
                ),
                "signing_secret": submitted,
            }
            errors = get_rail_adapter(rail).validate_config(validation_target)
            if errors:
                raise HTTPException(
                    status_code=422, detail={"rail": rail, "validation_errors": errors}
                )

            from services.rewards.webhook_secret import store_secret

            actor = _actor_id(request)
            secret_ref = await store_secret(tenant_id, submitted, actor=actor)
            inner.pop("signing_secret", None)
            patch.pop("signing_secret", None)
            inner["secret_ref"] = secret_ref
            patch["config"] = inner
            patch["secret_ref"] = secret_ref

    updated = await repos["rail_configs"].update(rail_id, patch)
    await _audit(repos, tenant_id, "rail.updated", "rail_config", rail_id,
                 before_state=_redact_rail_config(before),
                 after_state=_redact_rail_config(updated))
    return _redact_rail_config(updated)


@router.post("/rails/{rail_id}/verify", response_model=None)
@api_response
async def verify_rail(request: Request, rail_id: str):
    """Verify rail connectivity by sending a test delivery."""
    _require_permission(request, "rewards:write")
    tenant_id = _get_tenant_id(request)
    repos = await _get_repos()

    rail_record = await repos["rail_configs"].get(rail_id, tenant_id)
    rail_name = rail_record.get("rail", "")

    try:
        adapter = get_rail_adapter(rail_name)
        result = await adapter.health_check(rail_record)
        status = "verified" if result.get("healthy") else "verification_failed"
        await repos["rail_configs"].set_status(rail_id, tenant_id, status)
        await _audit(repos, tenant_id, f"rail.{status}", "rail_config", rail_id)
        return {**result, "status": status, "rail": rail_name}
    except RailUnavailableError as exc:
        raise HTTPException(status_code=422, detail=f"Rail {exc.rail} unavailable: {exc.reason}")


@router.post("/rails/{rail_id}/disable", response_model=None)
@api_response
async def disable_rail(request: Request, rail_id: str):
    """Disable a configured rail (stops delivery; config preserved)."""
    _require_permission(request, "rewards:write")
    tenant_id = _get_tenant_id(request)
    repos = await _get_repos()
    before = await repos["rail_configs"].get(rail_id, tenant_id)
    updated = await repos["rail_configs"].update(rail_id, {"enabled": False, "updated_at": _utc_now()})
    await _audit(repos, tenant_id, "rail.disabled", "rail_config", rail_id,
                 before_state=_redact_rail_config(before),
                 after_state=_redact_rail_config(updated))
    return _redact_rail_config(updated)


# ═══════════════════════════════════════════════════════════════════════════
# CONTRACT REGISTRY ROUTES
# Tenants register and verify smart contracts before generating onchain_claim
# proofs. Required in non-local environments by the registry gate in /evaluate.
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/contracts", response_model=None)
@api_response
async def register_contract(request: Request, body: ContractRegistryCreate):
    """Register a smart contract for onchain_claim proof generation."""
    _require_permission(request, "rewards:write")
    tenant_id = _get_tenant_id(request)
    repos = await _get_repos()
    record = await repos["contracts"].register(tenant_id, {
        **body.model_dump(),
        "verification_status": "pending",
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
    })
    await _audit(repos, tenant_id, "contract.registered", "contract_registry", record.get("id"),
                 after_state=record)
    return record


@router.get("/contracts", response_model=None)
@api_response
async def list_contracts(request: Request):
    """List all registered contracts for the authenticated tenant."""
    _require_permission(request, "rewards:read")
    tenant_id = _get_tenant_id(request)
    repos = await _get_repos()
    return await repos["contracts"].list(tenant_id)


@router.get("/contracts/{registry_id}", response_model=None)
@api_response
async def get_contract(request: Request, registry_id: str):
    """Get a single registered contract by ID."""
    _require_permission(request, "rewards:read")
    tenant_id = _get_tenant_id(request)
    repos = await _get_repos()
    return await repos["contracts"].get(registry_id, tenant_id)


@router.post("/contracts/{registry_id}/verify", response_model=None)
@api_response
async def verify_contract(request: Request, registry_id: str):
    """Mark a registered contract as verified, enabling proof generation for it.

    Requires rewards:admin (Aether operator) permission — tenants cannot self-verify.
    Operators must confirm the tenant controls the contract_address before verifying.
    This prevents a tenant from registering an arbitrary contract address, setting
    Aether's public oracle signer, and obtaining proofs for a contract they don't own.
    """
    _require_permission(request, "rewards:admin")
    tenant_id = _get_tenant_id(request)
    repos = await _get_repos()
    record = await repos["contracts"].get(registry_id, tenant_id)

    registered_signer = record.get("oracle_signer_address", "")
    if not registered_signer:
        raise HTTPException(
            status_code=422,
            detail="oracle_signer_address is required before verification. "
                   "Re-register with oracle_signer_address set to Aether's oracle address.",
        )

    # Compare against the TENANT's resolved reward signer — fail closed: a
    # contract may never verify without proving the registered signer matches
    # the key that will actually sign this tenant's proofs.
    from services.rewards.signing import (
        SignerUnavailableError,
        resolve_reward_signer,
        reward_credential_environment,
    )

    try:
        signer_key = await resolve_reward_signer(
            tenant_id, reward_credential_environment(), "evm"
        )
    except SignerUnavailableError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"cannot verify contract without a resolvable reward signer: {exc}",
        )
    try:
        from eth_account import Account as _Account  # noqa: PLC0415
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail=(
                "eth_account is unavailable — signer-address verification cannot "
                "run, and contract verification never passes unverified."
            ),
        )
    _key = signer_key[2:] if signer_key.startswith("0x") else signer_key
    _expected = _Account.from_key(bytes.fromhex(_key)).address.lower()
    if registered_signer.lower() != _expected:
        raise HTTPException(
            status_code=422,
            detail=(
                f"oracle_signer_address {registered_signer!r} does not match the "
                "tenant's resolved reward signer. Update the registry entry and "
                "re-verify, or rotate the signer credential and update the contract."
            ),
        )

    updated = await repos["contracts"].verify(registry_id, tenant_id)
    await _audit(repos, tenant_id, "contract.verified", "contract_registry", registry_id,
                 after_state=updated)
    return updated


# ═══════════════════════════════════════════════════════════════════════════
# EXTERNAL AUDIT EVIDENCE ROUTES
# Records the external security-audit evidence required to activate EVM mainnet
# on-chain rewards (see services/rewards/onchain_gate.py).
# ═══════════════════════════════════════════════════════════════════════════

class AuditEvidenceCreate(BaseModel):
    chain_id: int
    contract_address: str
    auditor: str
    report_uri: Optional[str] = None
    report_hash: Optional[str] = None
    summary: Optional[str] = None
    status: str = "recorded"


@router.post("/audit-evidence", response_model=None)
@api_response
async def create_audit_evidence(request: Request, body: AuditEvidenceCreate):
    """Record external security-audit evidence for an on-chain reward contract.

    A non-revoked entry for (tenant, chain_id, contract_address) is required to
    activate EVM mainnet on-chain rewards.
    """
    _require_permission(request, "rewards:write")
    tenant_id = _get_tenant_id(request)
    repos = await _get_repos()
    record = await repos["audit_evidence"].create(tenant_id, {
        **body.model_dump(),
        "recorded_at": _utc_now(),
    })
    await _audit(repos, tenant_id, "audit_evidence.recorded", "reward_audit_evidence", record.get("id"),
                 after_state=record)
    metrics.increment("rewards_audit_evidence_recorded", labels={"tenant_id": tenant_id})
    return record


@router.get("/audit-evidence", response_model=None)
@api_response
async def list_audit_evidence(
    request: Request,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List recorded external-audit evidence for the authenticated tenant."""
    _require_permission(request, "rewards:read")
    tenant_id = _get_tenant_id(request)
    repos = await _get_repos()
    return await repos["audit_evidence"].list(tenant_id, limit=limit, offset=offset)


@router.post("/audit-evidence/{evidence_id}/verify", response_model=None)
@api_response
async def verify_audit_evidence(request: Request, evidence_id: str):
    """Operator marks an audit-evidence entry as verified (rewards:admin)."""
    _require_permission(request, "rewards:admin")
    tenant_id = _get_tenant_id(request)
    repos = await _get_repos()
    updated = await repos["audit_evidence"].set_status(evidence_id, tenant_id, "verified")
    await _audit(repos, tenant_id, "audit_evidence.verified", "reward_audit_evidence", evidence_id,
                 after_state=updated)
    return updated


@router.post("/audit-evidence/{evidence_id}/revoke", response_model=None)
@api_response
async def revoke_audit_evidence(request: Request, evidence_id: str):
    """Revoke an audit-evidence entry (re-gates mainnet activation for the contract)."""
    _require_permission(request, "rewards:admin")
    tenant_id = _get_tenant_id(request)
    repos = await _get_repos()
    updated = await repos["audit_evidence"].set_status(evidence_id, tenant_id, "revoked")
    await _audit(repos, tenant_id, "audit_evidence.revoked", "reward_audit_evidence", evidence_id,
                 after_state=updated)
    return updated


# ═══════════════════════════════════════════════════════════════════════════
# DURABLE DELIVERY OUTBOX ROUTES (tenant_webhook)
# Operator status + replay for the durable, leased reward-delivery outbox.
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/outbox/status", response_model=None)
@api_response
async def outbox_status(request: Request):
    """Return durable reward-delivery job counts by state for the tenant."""
    _require_permission(request, "rewards:read")
    tenant_id = _get_tenant_id(request)
    from services.rewards.delivery_outbox import reward_delivery_outbox
    return {"tenant_id": tenant_id, "jobs_by_state": await reward_delivery_outbox.status(tenant_id)}


@router.post("/outbox/drain", response_model=None)
@api_response
async def outbox_drain(request: Request, batch_size: int = Query(10, ge=1, le=100)):
    """Operator-triggered drain of the durable reward-delivery outbox.

    Leases and dispatches a batch of runnable jobs (retry/backoff/DLQ applied),
    recording a ProviderReceipt on success. Also used as a manual replay trigger
    in environments without the background outbox worker running.
    """
    _require_permission(request, "rewards:write")
    from services.rewards.delivery_outbox import reward_delivery_outbox
    summary = await reward_delivery_outbox.drain(batch_size=batch_size)
    metrics.increment("rewards_outbox_drain_requests", labels={"tenant_id": _get_tenant_id(request)})
    return summary


@router.post("/actions/{action_id}/redeliver", response_model=None)
@api_response
async def redeliver_action(request: Request, action_id: str):
    """Operator replay: requeue a failed tenant_webhook delivery for the action."""
    _require_permission(request, "rewards:write")
    tenant_id = _get_tenant_id(request)
    repos = await _get_repos()
    action = await repos["actions"].get(action_id, tenant_id)
    job_id = action.get("delivery_job_id")
    if not job_id:
        raise HTTPException(status_code=409, detail="Action has no durable delivery job to replay")
    from services.rewards.delivery_outbox import reward_delivery_outbox
    try:
        job = await reward_delivery_outbox.redeliver(job_id, tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    await repos["actions"].transition(action_id, tenant_id, "pending")
    return {"action_id": action_id, "job": job}


# ═══════════════════════════════════════════════════════════════════════════
# LEGACY COMPATIBILITY ROUTES (local/test mode)
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/queue/stats", response_model=None)
@api_response
async def queue_stats():
    """Return current reward queue statistics (legacy local-mode endpoint)."""
    return _legacy_stack.get().queue.get_stats()


@router.get("/user/{address}", response_model=None)
@api_response
async def get_user_rewards(address: str):
    """Return all rewards for a given wallet address (legacy local-mode endpoint)."""
    rewards = _legacy_stack.get().queue.get_user_rewards(address)
    return [r.to_dict() for r in rewards]


@router.post("/process", response_model=None)
@api_response
async def process_queue():
    """Trigger processing of pending rewards in the queue (legacy local-mode endpoint)."""
    results = await _legacy_stack.get().queue.process_all()
    return {"processed": len(results), "results": [r.to_dict() for r in results]}


@router.get("/proof/{reward_id}", response_model=None)
@api_response
async def get_reward_proof(reward_id: str):
    """Retrieve proof for a queued reward (legacy local-mode endpoint)."""
    reward = _legacy_stack.get().queue.get_reward(reward_id)
    if reward.proof is None:
        raise HTTPException(
            status_code=409,
            detail=f"Proof not yet available; reward status={reward.status}",
        )
    return {"reward_id": reward.id, "status": reward.status, "proof": reward.proof}


# ═══════════════════════════════════════════════════════════════════════════
# LEGACY HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _register_legacy_campaign(campaign_id: str, body: CampaignCreate) -> None:
    """Register campaign in local in-memory engine for backward compat."""
    try:
        if not body.rules:
            return
        rules = [
            RewardRule(
                event_types=r["event_types"],
                reward_tier=RewardTier(
                    name=r["reward_tier"]["name"],
                    amount_wei=r["reward_tier"]["amount_wei"],
                    token_symbol=r["reward_tier"].get("token_symbol", "ETH"),
                    description=r["reward_tier"].get("description", ""),
                    vm_type=body.vm_type,
                ),
                required_channel=r.get("required_channel"),
                min_attribution_weight=r.get("min_attribution_weight", 0.0),
                max_fraud_score=r.get("max_fraud_score", 40.0),
                cooldown_seconds=r.get("cooldown_seconds", 86400),
                max_per_user=r.get("max_per_user", 1),
                requires_wallet=r.get("requires_wallet", True),
            )
            for r in body.rules
            if isinstance(r, dict) and "event_types" in r and "reward_tier" in r
        ]
        chain_cfg = _legacy_stack.get().multichain_config.get_chain_config(VMType.from_string(body.vm_type))
        campaign = Campaign(
            id=campaign_id,
            name=body.name,
            description=body.description,
            rules=rules,
            start_time=body.start_time,
            end_time=body.end_time,
            total_budget_wei=body.total_budget_wei or 0,
            chain_id=body.chain_id,
            contract_address=body.contract_address or chain_cfg.contract_address,
            vm_type=body.vm_type,
            program_id=body.program_id,
        )
        _engine.register_campaign(campaign)
    except Exception as exc:
        logger.debug(f"Legacy campaign registration failed (non-fatal): {exc}")
