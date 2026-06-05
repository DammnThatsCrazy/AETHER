"""Typed Noesis request/response contract."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

NoesisSurface = Literal["kyber", "aether"]
NoesisMode = Literal["deterministic", "llm_text_to_query", "fallback"]


class NoesisContext(BaseModel):
    current_page: Optional[str] = None
    selected_entity_id: Optional[str] = None
    selected_entity_type: Optional[str] = None
    time_range: Optional[str] = None
    filters: dict[str, Any] = Field(default_factory=dict)


class NoesisQueryRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    surface: NoesisSurface
    tenant_id: Optional[str] = Field(default=None, max_length=128)
    conversation_id: Optional[str] = Field(default=None, max_length=128)
    context: NoesisContext = Field(default_factory=NoesisContext)


class NoesisAction(BaseModel):
    type: Literal["navigate", "open_inspector", "highlight_graph", "refine_query"]
    label: Optional[str] = None
    href: Optional[str] = None
    entity_id: Optional[str] = None
    entity_type: Optional[str] = None
    node_ids: list[str] = Field(default_factory=list)
    edge_ids: list[str] = Field(default_factory=list)
    prompt: Optional[str] = None


class NoesisGraph(BaseModel):
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    highlights: list[str] = Field(default_factory=list)


class NoesisError(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class NoesisResponse(BaseModel):
    conversation_id: Optional[str] = None
    answer: str
    mode: NoesisMode
    intent: str
    confidence: float = Field(ge=0.0, le=1.0)
    entities: list[dict[str, Any]] = Field(default_factory=list)
    results: list[dict[str, Any]] = Field(default_factory=list)
    graph: NoesisGraph = Field(default_factory=NoesisGraph)
    actions: list[NoesisAction] = Field(default_factory=list)
    query_debug: Optional[dict[str, Any]] = None
    warnings: list[str] = Field(default_factory=list)
    error: Optional[NoesisError] = None


class QueryPlan(BaseModel):
    intent: Literal[
        "entity_search",
        "graph_lookup",
        "alert_lookup",
        "tenant_summary",
        "profile_lookup",
        "wallet_lookup",
        "agent_lookup",
        "health_lookup",
        "campaign_reward_lookup",
        "risk_cluster_lookup",
        "unsupported",
    ]
    target: Optional[str] = None
    entity_type: Optional[str] = None
    tenant_id: Optional[str] = None
    time_range: Optional[str] = None
    filters: dict[str, Any] = Field(default_factory=dict)
    limit: int = Field(default=10, ge=1, le=50)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    source: Literal["deterministic", "llm"] = "deterministic"


class NoesisConversationMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    created_at: Optional[str] = None
    response: Optional[dict[str, Any]] = None


class NoesisConversationRecord(BaseModel):
    conversation_id: str
    surface: NoesisSurface
    tenant_id: str
    created_at: str
    updated_at: str
    title: str = "Noesis conversation"
    messages: list[NoesisConversationMessage] = Field(default_factory=list)


class NoesisConversationList(BaseModel):
    conversations: list[dict[str, Any]] = Field(default_factory=list)
    count: int = 0
