"""Risk Overlay — Pydantic models."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class RiskGraphNode(BaseModel):
    id: str
    entity_id: str
    entity_type: str
    label: Optional[str] = None
    risk_score: float = Field(ge=0.0, le=100.0)
    confidence: float = Field(ge=0.0, le=1.0)
    role: Optional[str] = None
    is_source: bool = False
    is_sink: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class RiskGraphEdge(BaseModel):
    id: str
    source: str
    target: str
    edge_type: str
    risk_score: float = Field(ge=0.0, le=100.0)
    transfer_count: int = Field(ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RiskOverlayGraph(BaseModel):
    nodes: list[RiskGraphNode] = Field(default_factory=list)
    edges: list[RiskGraphEdge] = Field(default_factory=list)
    node_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)
    overlay_risk_score: float = Field(ge=0.0, le=100.0)
    computed_at: str


class RiskOverlayBuildRequest(BaseModel):
    tenant_id: str
    source_id: str
    source_type: Literal["fraud_network", "flow_trace"]
    label: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
