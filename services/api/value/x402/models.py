"""
Aether Service — x402 Models
Payment terms, payment proof, captured transactions, economic graph nodes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field, PrivateAttr


class PaymentTerms(BaseModel):
    """Parsed from PAYMENT-REQUIRED HTTP header (402 response)."""
    amount: float
    token: str = "USDC"
    chain: str  # CAIP-2 format, e.g. "eip155:1" or "solana:mainnet"
    recipient: str
    memo: Optional[str] = None
    expires_at: Optional[str] = None


class PaymentProof(BaseModel):
    """Parsed from X-PAYMENT HTTP header (client request)."""
    tx_hash: str
    payer: str
    chain: str
    amount: float
    token: str = "USDC"


class PaymentResponse(BaseModel):
    """Parsed from X-PAYMENT-RESPONSE HTTP header (server confirmation)."""
    verified: bool = False
    receipt_id: Optional[str] = None
    settled_at: Optional[str] = None


class CapturedX402Transaction(BaseModel):
    """A complete x402 payment transaction captured from HTTP headers."""
    capture_id: str = ""
    payer_agent_id: str
    payee_service_id: str
    terms: PaymentTerms
    proof: Optional[PaymentProof] = None
    response: Optional[PaymentResponse] = None
    request_url: str = ""
    request_method: str = "GET"
    amount_usd: float = 0.0
    fee_eliminated_usd: float = 0.0
    captured_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class X402Node(BaseModel):
    """A node in the x402 economic graph (agent or service)."""
    node_id: str
    node_type: str = Field(..., pattern="^(agent|service)$")
    total_paid_usd: float = 0.0
    total_received_usd: float = 0.0
    transaction_count: int = 0
    unique_services: int = 0
    fee_eliminated_usd: float = 0.0
    _seen_services: set = PrivateAttr(default_factory=set)


class SpendingSummary(BaseModel):
    """Spending summary for an agent's x402 payments."""
    agent_id: str
    total_spent_usd: float = 0.0
    total_transactions: int = 0
    unique_services: int = 0
    avg_payment_usd: float = 0.0
    fee_eliminated_usd: float = 0.0
    payments: list[dict[str, Any]] = Field(default_factory=list)
