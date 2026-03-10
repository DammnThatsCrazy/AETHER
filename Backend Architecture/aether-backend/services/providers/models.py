"""
Aether Service — Provider Gateway Pydantic Models

Request/response schemas for the BYOK admin API.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


# ── Key Management ─────────────────────────────────────────────────────

class ProviderKeyCreate(BaseModel):
    """Store or update a BYOK API key for a provider."""
    provider_name: str = Field(..., description="Provider name (e.g. 'alchemy', 'etherscan')")
    api_key: str = Field(..., min_length=1, description="The raw API key")
    endpoint: Optional[str] = Field(None, description="Custom endpoint URL (optional)")


class ProviderKeyResponse(BaseModel):
    """Masked BYOK key info returned to the client."""
    provider_name: str
    masked_key: str
    endpoint: Optional[str] = None
    enabled: bool = True
    stored_at: str


# ── Routing ────────────────────────────────────────────────────────────

class ProviderRouteRequest(BaseModel):
    """Request to route a provider call through the gateway."""
    category: str = Field(..., description="Provider category (e.g. 'blockchain_rpc')")
    method: str = Field(..., description="Method to call")
    params: dict = Field(default_factory=dict, description="Call parameters")
    preferred_provider: Optional[str] = Field(None, description="Preferred provider name")


# ── Usage ──────────────────────────────────────────────────────────────

class UsageQuery(BaseModel):
    """Query parameters for usage data."""
    category: Optional[str] = None
    provider_name: Optional[str] = None
