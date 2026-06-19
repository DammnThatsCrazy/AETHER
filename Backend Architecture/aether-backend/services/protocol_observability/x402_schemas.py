"""Route request/response schemas for x402 protocol observability."""
from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field


class X402InteractionRequest(BaseModel):
    schema_version: str = "1.0"
    tenant_id: str
    agent_id: Optional[str] = None
    resource_url: str
    provider: str = "unknown"
    observed_at: Optional[str] = None
    execution_by_aether: Literal[False] = False


class X402ChallengeRequest(BaseModel):
    schema_version: str = "1.0"
    tenant_id: str
    interaction_id: Optional[str] = None
    http_status: int = 402
    amount_usd: Optional[float] = None
    asset: Optional[str] = None
    network: Optional[str] = None
    recipient: Optional[str] = None
    observed_at: Optional[str] = None
    execution_by_aether: Literal[False] = False


class X402RequirementRequest(BaseModel):
    schema_version: str = "1.0"
    tenant_id: str
    challenge_obs_id: Optional[str] = None
    interaction_id: Optional[str] = None
    max_amount_usd: Optional[float] = None
    pay_to: Optional[str] = None
    accepted_schemes: list[str] = Field(default_factory=list)
    observed_at: Optional[str] = None
    execution_by_aether: Literal[False] = False


class X402SignatureRequest(BaseModel):
    schema_version: str = "1.0"
    tenant_id: str
    interaction_id: Optional[str] = None
    signed_by_external: Literal[True] = True
    signer_address: Optional[str] = None
    observed_at: Optional[str] = None
    execution_by_aether: Literal[False] = False


class X402VerificationRequest(BaseModel):
    schema_version: str = "1.0"
    tenant_id: str
    interaction_id: Optional[str] = None
    verification_result: Optional[str] = None
    verified_by: Optional[str] = None
    observed_at: Optional[str] = None
    execution_by_aether: Literal[False] = False


class X402SettlementRequest(BaseModel):
    schema_version: str = "1.0"
    tenant_id: str
    interaction_id: Optional[str] = None
    tx_hash: Optional[str] = None
    settlement_by_external: Literal[True] = True
    execution_by_aether: Literal[False] = False
    observed_at: Optional[str] = None


class X402ResourceAccessRequest(BaseModel):
    schema_version: str = "1.0"
    tenant_id: str
    interaction_id: Optional[str] = None
    access_granted: bool
    access_denied_reason: Optional[str] = None
    resource_url: Optional[str] = None
    observed_at: Optional[str] = None
    execution_by_aether: Literal[False] = False


class X402ObservationResponse(BaseModel):
    observation_id: str
    received_at: str
    graph_mutations_queued: int = 0
    tenant_id: str
