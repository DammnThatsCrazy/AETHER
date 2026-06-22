"""Flow-of-Funds Trace — Pydantic models."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from services.operational_intelligence.models import EvidenceRef


FlowDirection = Literal["upstream", "downstream", "both"]

FlowNodeKind = Literal[
    "user",
    "agent",
    "wallet",
    "exchange",
    "contract",
    "unknown",
]

PatternTag = Literal[
    "layering",
    "smurfing",
    "structuring",
    "round_trip",
    "aggregation",
    "dispersion",
    "mule_chain",
    "cross_chain",
    "rapid_movement",
    "dormant_activation",
    "high_velocity",
    "split_deposit",
    "merge_withdrawal",
    "delegation_relay",
]


class FlowTraceRequest(BaseModel):
    tenant_id: str
    anchor_entity_id: str
    direction: FlowDirection = "downstream"
    max_hops: int = Field(default=6, ge=1, le=20)
    min_amount_usd: Optional[float] = Field(default=None, ge=0)
    label: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class FlowTraceNode(BaseModel):
    id: str
    entity_id: str
    entity_type: FlowNodeKind
    label: Optional[str] = None
    hop: int = Field(ge=0)
    is_source: bool = False
    is_sink: bool = False
    is_aggregation_point: bool = False
    risk_score: float = Field(default=0.0, ge=0.0, le=100.0)
    total_received_usd: float = Field(ge=0.0)
    total_sent_usd: float = Field(ge=0.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class FlowTracePath(BaseModel):
    id: str
    trace_id: str
    path_nodes: list[str]
    path_edges: list[str]
    hop_count: int = Field(ge=0)
    total_amount_usd: float = Field(ge=0.0)
    risk_score: float = Field(default=0.0, ge=0.0, le=100.0)
    pattern_tags: list[PatternTag] = Field(default_factory=list)
    contains_cycle: bool = False
    passes_through_sink: bool = False
    passes_through_source: bool = False
    discovered_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class FlowTraceResponse(BaseModel):
    id: str
    tenant_id: str
    anchor_entity_id: str
    direction: FlowDirection
    label: Optional[str] = None
    status: Literal["pending", "complete", "failed"] = "complete"
    path_count: int = Field(ge=0)
    node_count: int = Field(ge=0)
    source_nodes: list[str] = Field(default_factory=list)
    sink_nodes: list[str] = Field(default_factory=list)
    aggregation_points: list[str] = Field(default_factory=list)
    cycle_detected: bool = False
    cycle_nodes: list[str] = Field(default_factory=list)
    risk_score: float = Field(default=0.0, ge=0.0, le=100.0)
    pattern_tags: list[PatternTag] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    created_at: str
    completed_at: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class FlowTraceAttachRequest(BaseModel):
    tenant_id: str
    case_id: str
