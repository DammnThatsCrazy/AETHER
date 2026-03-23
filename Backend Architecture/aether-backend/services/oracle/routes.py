"""
Aether Backend — Oracle Bridge Routes

Exposes the cryptographic oracle as a REST service for proof generation,
off-chain verification, and configuration introspection.

Routes:
    POST /v1/oracle/proof/generate   Generate a reward proof (internal, auth required)
    POST /v1/oracle/proof/verify     Verify a proof off-chain
    GET  /v1/oracle/signer           Get oracle signer address
    GET  /v1/oracle/config           Get oracle configuration (non-sensitive)

Security:
    The ``/proof/generate`` endpoint is intended for service-to-service
    calls only. In non-local environments, signing and internal-auth secrets
    must be explicitly configured or the module fails closed at import time.
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Header, HTTPException

from config.settings import Environment, settings
from pydantic import BaseModel, Field

from services.oracle.signer import OracleSigner, ProofConfig, RewardProof
from services.oracle.verifier import is_proof_expired, verify_reward_proof
from shared.decorators import api_response
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.service.oracle")

router = APIRouter(prefix="/v1/oracle", tags=["Oracle"])


def _require_env(name: str, local_default: str = "") -> str:
    value = os.environ.get(name)
    if value:
        return value
    if settings.env == Environment.LOCAL:
        return local_default
    raise RuntimeError(f"{name} must be set in non-local environments")



# ═══════════════════════════════════════════════════════════════════════════
# SINGLETON
# ═══════════════════════════════════════════════════════════════════════════

_config = ProofConfig(
    signer_private_key=_require_env(
        "ORACLE_SIGNER_KEY",
        "ac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",
    ),
    contract_address=_require_env(
        "REWARD_CONTRACT_ADDRESS",
        "0x5FbDB2315678afecb367f032d93F642f64180aa3",
    ),
    chain_id=int(os.environ.get("CHAIN_ID", "1")),
    proof_expiry_seconds=int(os.environ.get("PROOF_EXPIRY_SECONDS", "3600")),
)

_signer = OracleSigner(_config)

_INTERNAL_API_KEY = _require_env("ORACLE_INTERNAL_KEY", "aether-internal-dev-key")


# ═══════════════════════════════════════════════════════════════════════════
# REQUEST / RESPONSE MODELS
# ═══════════════════════════════════════════════════════════════════════════

class GenerateProofRequest(BaseModel):
    """Service-to-service proof generation request."""
    user: str = Field(..., description="Recipient wallet address (0x...)")
    action_type: str = Field(..., description="Qualifying event type")
    amount_wei: int = Field(..., gt=0, description="Reward amount in wei")


class GenerateProofResponse(BaseModel):
    user: str
    action_type: str
    amount_wei: int
    nonce: str
    expiry: int
    chain_id: int
    contract_address: str
    signature: str
    message_hash: str
    signer_public_key: str


class VerifyProofRequest(BaseModel):
    """Off-chain proof verification payload."""
    user: str
    action_type: str
    amount_wei: int
    nonce: str
    expiry: int
    chain_id: int
    contract_address: str
    signature: str
    message_hash: str
    signer_public_key: str


class VerifyProofResponse(BaseModel):
    valid: bool
    expired: bool
    signer_match: bool
    expected_signer: str


class SignerInfoResponse(BaseModel):
    address: str
    chain_id: int
    contract_address: str


class OracleConfigResponse(BaseModel):
    chain_id: int
    contract_address: str
    proof_expiry_seconds: int
    signer_address: str


# ═══════════════════════════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/proof/generate", response_model=None)
@api_response
async def generate_proof(
    body: GenerateProofRequest,
    x_internal_key: Optional[str] = Header(None, alias="X-Internal-Key"),
):
    """
    Generate a signed reward proof.

    **Internal endpoint** — callers must supply a valid
    ``X-Internal-Key`` header.
    """
    if x_internal_key != _INTERNAL_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid or missing internal API key")

    proof = await _signer.generate_proof(
        user=body.user,
        action_type=body.action_type,
        amount_wei=body.amount_wei,
    )

    metrics.increment("oracle_route_generate")
    return proof.to_dict()


@router.post("/proof/verify", response_model=None)
@api_response
async def verify_proof(body: VerifyProofRequest):
    """
    Verify a proof off-chain.

    Checks the message hash derivation, signature recovery, and expiry
    without touching the blockchain.
    """
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
        signer_public_key=body.signer_public_key,
    )

    expired = is_proof_expired(proof)
    valid = verify_reward_proof(proof, expected_signer=_signer.signer_address)

    metrics.increment("oracle_route_verify", labels={"valid": str(valid)})

    return VerifyProofResponse(
        valid=valid,
        expired=expired,
        signer_match=valid and not expired,
        expected_signer=_signer.signer_address,
    ).model_dump()


@router.get("/signer", response_model=None)
@api_response
async def get_signer_info():
    """Return the oracle signer's public address and target chain."""
    return SignerInfoResponse(
        address=_signer.signer_address,
        chain_id=_config.chain_id,
        contract_address=_config.contract_address,
    ).model_dump()


@router.get("/config", response_model=None)
@api_response
async def get_oracle_config():
    """
    Return non-sensitive oracle configuration.

    The private key is **never** exposed.
    """
    return OracleConfigResponse(
        chain_id=_config.chain_id,
        contract_address=_config.contract_address,
        proof_expiry_seconds=_config.proof_expiry_seconds,
        signer_address=_signer.signer_address,
    ).model_dump()
