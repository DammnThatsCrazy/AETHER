"""
Aether Service — Commerce Models
Payment records, agent hire records, fee elimination reports.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


class PaymentRecord(BaseModel):
    """A payment between any combination of humans, agents, and services."""
    payment_id: str = ""
    tenant_id: Optional[str] = None
    payer_id: str
    payer_type: str = Field(..., pattern="^(human|agent|service)$")
    payee_id: str
    payee_type: str = Field(..., pattern="^(human|agent|service)$")
    amount: float
    currency: str = "USD"
    method: str = Field(default="usdc", pattern="^(x402|sponge|usdc|card|eth|sol)$")
    chain_id: Optional[str] = None
    vm_type: Optional[str] = None
    tx_hash: Optional[str] = None
    fee_eliminated_usd: float = 0.0
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class AgentHireRecord(BaseModel):
    """Records when one agent hires another for a task."""
    hire_id: str = ""
    hiring_agent_id: str
    hired_agent_id: str
    task_type: str
    agreed_amount: float = 0.0
    currency: str = "USD"
    payment_id: Optional[str] = None
    status: str = Field(default="pending", pattern="^(pending|active|completed|cancelled)$")
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    completed_at: Optional[str] = None


class FeeEliminationReport(BaseModel):
    """Fee elimination summary for a time period."""
    period: str
    total_transactions: int = 0
    total_volume_usd: float = 0.0
    card_fees_would_be_usd: float = 0.0
    actual_fees_usd: float = 0.0
    eliminated_usd: float = 0.0

    @property
    def elimination_rate(self) -> float:
        if self.card_fees_would_be_usd == 0:
            return 0.0
        return self.eliminated_usd / self.card_fees_would_be_usd
