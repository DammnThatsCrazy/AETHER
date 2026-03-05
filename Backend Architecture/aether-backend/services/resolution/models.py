"""
Aether Backend — Identity Resolution Models
Pydantic models for resolution request/response payloads.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Configuration ────────────────────────────────────────────────────

class ResolutionConfigUpdate(BaseModel):
    """Threshold settings for the resolution rules engine."""

    auto_merge_threshold: Optional[float] = Field(
        None, ge=0.0, le=1.0, description="Confidence above which auto-merge fires",
    )
    review_threshold: Optional[float] = Field(
        None, ge=0.0, le=1.0, description="Confidence above which review is flagged",
    )
    max_cluster_size: Optional[int] = Field(
        None, ge=2, le=500, description="Maximum members in an identity cluster",
    )
    cooldown_hours: Optional[int] = Field(
        None, ge=0, le=720, description="Hours before re-evaluating a rejected pair",
    )
    require_deterministic_for_auto: Optional[bool] = Field(
        None, description="Require at least one deterministic match for auto-merge",
    )


# ── Merge ────────────────────────────────────────────────────────────

class MergeRequest(BaseModel):
    """Manual merge request submitted by an admin."""

    primary_user_id: str
    secondary_user_id: str
    reason: str = "manual_merge"


# ── Pending Resolution ───────────────────────────────────────────────

class PendingResolutionResponse(BaseModel):
    """A resolution decision waiting for admin review."""

    decision_id: str
    profile_a_id: str
    profile_b_id: str
    composite_confidence: float
    signals: list[dict[str, Any]] = Field(default_factory=list)
    action: str
    timestamp: str


# ── Cluster ──────────────────────────────────────────────────────────

class ClusterResponse(BaseModel):
    """Identity cluster containing all linked profiles and identifiers."""

    cluster_id: str
    canonical_user_id: str
    members: list[str] = Field(default_factory=list)
    linked_devices: list[str] = Field(default_factory=list)
    linked_ips: list[str] = Field(default_factory=list)
    linked_wallets: list[str] = Field(default_factory=list)
    linked_emails: list[str] = Field(default_factory=list)
