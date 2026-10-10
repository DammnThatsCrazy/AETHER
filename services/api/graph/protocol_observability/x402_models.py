"""
Protocol Observability — x402 observation models.

These models represent x402 protocol interactions as OBSERVED from the outside.
AETHER does not sign, settle, or execute any x402 payment.
All execution_by_aether fields are Literal[False].
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


class X402InteractionObservedRecord(BaseModel):
    interaction_id: str = Field(default_factory=_new_id)
    tenant_id: str
    agent_id: Optional[str] = None
    resource_url: str
    provider: str = "unknown"
    observed_at: str = Field(default_factory=_utc_now)
    received_at: str = Field(default_factory=_utc_now)
    execution_by_aether: Literal[False] = False

    @model_validator(mode="after")
    def _enforce(self) -> "X402InteractionObservedRecord":
        if self.execution_by_aether is not False:
            raise ValueError("execution_by_aether must be False")
        return self


class X402ChallengeObservedRecord(BaseModel):
    challenge_obs_id: str = Field(default_factory=_new_id)
    interaction_id: Optional[str] = None
    http_status: int = 402
    payment_required_header: Optional[str] = None
    amount_usd: Optional[float] = None
    asset: Optional[str] = None
    network: Optional[str] = None
    recipient: Optional[str] = None
    schema_version: Optional[str] = None
    observed_at: str = Field(default_factory=_utc_now)
    tenant_id: str


class X402PaymentRequirementObservedRecord(BaseModel):
    requirement_obs_id: str = Field(default_factory=_new_id)
    challenge_obs_id: Optional[str] = None
    interaction_id: Optional[str] = None
    max_amount_usd: Optional[float] = None
    accepted_schemes: list[str] = Field(default_factory=list)
    pay_to: Optional[str] = None
    memo: Optional[str] = None
    expires_at: Optional[str] = None
    observed_at: str = Field(default_factory=_utc_now)
    tenant_id: str


class X402SignatureObservedRecord(BaseModel):
    signature_obs_id: str = Field(default_factory=_new_id)
    interaction_id: Optional[str] = None
    signed_by_external: Literal[True] = True
    signature_ref: Optional[str] = None
    signer_address: Optional[str] = None
    observed_at: str = Field(default_factory=_utc_now)
    tenant_id: str
    execution_by_aether: Literal[False] = False


class X402VerificationObservedRecord(BaseModel):
    verification_obs_id: str = Field(default_factory=_new_id)
    interaction_id: Optional[str] = None
    verification_result: Optional[str] = None
    verified_by: Optional[str] = None
    verified_at: Optional[str] = None
    observed_at: str = Field(default_factory=_utc_now)
    tenant_id: str


class X402SettlementObservedRecord(BaseModel):
    settlement_obs_id: str = Field(default_factory=_new_id)
    interaction_id: Optional[str] = None
    tx_hash: Optional[str] = None
    settled_at: Optional[str] = None
    settlement_by_external: Literal[True] = True
    execution_by_aether: Literal[False] = False
    observed_at: str = Field(default_factory=_utc_now)
    tenant_id: str


class X402ResourceAccessObservedRecord(BaseModel):
    access_obs_id: str = Field(default_factory=_new_id)
    interaction_id: Optional[str] = None
    access_granted: bool
    access_denied_reason: Optional[str] = None
    resource_url: Optional[str] = None
    observed_at: str = Field(default_factory=_utc_now)
    tenant_id: str


class X402ReplayRiskObservedRecord(BaseModel):
    replay_obs_id: str = Field(default_factory=_new_id)
    interaction_id: Optional[str] = None
    reason: Optional[str] = None
    observed_at: str = Field(default_factory=_utc_now)
    tenant_id: str
