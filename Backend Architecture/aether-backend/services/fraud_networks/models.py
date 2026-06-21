"""Fraud Network Intelligence — Pydantic models."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from services.operational_intelligence.models import EntityRef, EvidenceRef


NetworkType = Literal[
    "synthetic_identity_ring",
    "account_takeover_cluster",
    "mule_network",
    "card_fraud_ring",
    "referral_abuse_ring",
    "airdrop_farming_cluster",
    "reward_farming_ring",
    "wash_trading_ring",
    "layering_network",
    "smurfing_network",
    "delegation_abuse_cluster",
    "commerce_abuse_ring",
    "coordinated_inauthentic_behavior",
    "unknown",
]

MemberRole = Literal[
    "orchestrator",
    "controller",
    "mule",
    "beneficiary",
    "aggregator",
    "splitter",
    "recruiter",
    "facilitator",
    "synthetic_identity",
    "compromised_account",
    "cash_out_node",
    "injection_point",
    "relay",
    "dormant",
    "observer",
    "victim",
    "unknown",
]

NetworkStatus = Literal[
    "active",
    "suppressed",
    "escalated",
    "closed",
    "under_review",
]


class FraudNetworkBuildRequest(BaseModel):
    tenant_id: str
    anchor_entity_ids: list[str] = Field(..., min_length=1, description="Seed entities to cluster from")
    network_type: Optional[NetworkType] = None
    max_depth: int = Field(default=3, ge=1, le=10)
    min_confidence: float = Field(default=0.4, ge=0.0, le=1.0)
    label: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class FraudNetworkMember(BaseModel):
    id: str
    network_id: str
    tenant_id: str
    entity_id: str
    entity_type: str
    role: MemberRole
    risk_score: float = Field(ge=0.0, le=100.0)
    confidence: float = Field(ge=0.0, le=1.0)
    in_degree: int = Field(ge=0)
    out_degree: int = Field(ge=0)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    joined_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class FraudNetworkEdge(BaseModel):
    id: str
    network_id: str
    tenant_id: str
    from_entity_id: str
    to_entity_id: str
    edge_type: str
    risk_score: float = Field(ge=0.0, le=100.0)
    transfer_count: int = Field(ge=0)
    total_amount: str = "0"
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    detected_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class FraudNetworkResponse(BaseModel):
    id: str
    tenant_id: str
    label: Optional[str] = None
    network_type: NetworkType
    status: NetworkStatus
    risk_score: float = Field(ge=0.0, le=100.0)
    confidence_score: float = Field(ge=0.0, le=1.0)
    member_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)
    anchor_entity_ids: list[str]
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    detected_signals: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class FraudNetworkGraphNode(BaseModel):
    id: str
    label: str
    entity_type: str
    role: MemberRole
    risk_score: float
    confidence: float
    is_anchor: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class FraudNetworkGraphEdge(BaseModel):
    id: str
    source: str
    target: str
    edge_type: str
    risk_score: float
    transfer_count: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class FraudNetworkGraphResponse(BaseModel):
    network_id: str
    nodes: list[FraudNetworkGraphNode]
    edges: list[FraudNetworkGraphEdge]
    node_count: int
    edge_count: int
    computed_at: str


class NetworkAnnotateRequest(BaseModel):
    tenant_id: str
    body: str
    author_id: str


class NetworkOpenInvestigationRequest(BaseModel):
    tenant_id: str
    title: Optional[str] = None
    created_by: str


class NetworkStatusUpdateRequest(BaseModel):
    tenant_id: str
    reason: Optional[str] = None
