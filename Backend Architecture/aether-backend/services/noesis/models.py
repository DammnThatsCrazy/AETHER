"""Typed Noesis request/response contract."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

ClaimType = Literal["fact", "computation", "inference", "recommendation"]

NoesisErrorCode = Literal[
    "rate_limited_qpm",
    "rate_limited_daily",
    "token_budget_exceeded",
    "safety_injection_detected",
    "safety_write_keyword",
    "plan_tenant_override_blocked",
    "plan_unsupported_filter",
    "plan_invalid_intent",
    "service_disabled",
    "canary_gate_blocked",
    "graph_unavailable",
    "internal_error",
    "safety_rejection",
    "unsupported_intent",
]

NoesisSurface = Literal["kyber", "aether"]
NoesisMode = Literal["deterministic", "llm_text_to_query", "fallback"]

# ─── GA constants ─────────────────────────────────────────────────────────

SUPPORTED_INTENTS: frozenset[str] = frozenset({
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
    # Communications Intelligence (read-only, evidence-backed)
    "communications_insight",
    # Suggestion Intelligence (read-only — Noesis may not mutate suggestions)
    "suggestion_lookup",
    "suggestion_summary",
    "suggestion_review_queue",
    "suggestion_explain",
    "suggestion_outcome_lookup",
    # Semantic-Sentiment Intelligence (read-only)
    "sentiment_explain",
    "narrative_analysis",
    "semantic_profile_explain",
})

SUPPORTED_ENTITY_TYPES: frozenset[str] = frozenset({
    "human", "wallet", "agent", "device", "organization",
    "campaign", "reward", "alert", "tenant",
})

SUPPORTED_FILTERS: frozenset[str] = frozenset({
    "tenant_id", "entity_type", "status", "risk_score",
    "time_range", "limit", "offset", "sort", "direction",
})

SUPPORTED_SORT_FIELDS: frozenset[str] = frozenset({
    "created_at", "updated_at", "risk_score", "display_name", "status",
})

MAX_LIMIT: int = 50

WRITE_LIKE_KEYWORDS: frozenset[str] = frozenset({
    "delete", "remove", "drop", "update", "modify", "change",
    "create", "insert", "add", "execute", "run", "mutate",
    "alter", "write", "set", "assign", "issue", "grant",
    "revoke", "export", "dump", "purge", "truncate",
})

INJECTION_PATTERNS: frozenset[str] = frozenset({
    "ignore previous", "ignore above", "ignore system",
    "disregard instructions", "forget instructions",
    "override instructions", "you are now", "act as",
    "new instructions", "system prompt", "developer mode",
    "jailbreak", "dan", "bypass",
})

# ─── Evidence envelope ────────────────────────────────────────────────────


class EvidenceSource(BaseModel):
    service: str
    resource_type: str
    resource_id: Optional[str] = None
    fetched_at: datetime
    freshness_seconds: Optional[int] = None
    confidence: Optional[float] = None


class EvidenceClaim(BaseModel):
    claim: str
    claim_type: ClaimType
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class EvidenceEnvelope(BaseModel):
    sources: list[EvidenceSource] = Field(default_factory=list)
    claims: list[EvidenceClaim] = Field(default_factory=list)
    sufficient: bool = True
    insufficient_reason: Optional[str] = None
    generated_at: Optional[datetime] = None


# ─── Request / Response models ────────────────────────────────────────────


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
    evidence: EvidenceEnvelope = Field(default_factory=EvidenceEnvelope)
    scope_summary: Optional[dict[str, Any]] = None


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
        "communications_insight",
        "suggestion_lookup",
        "suggestion_summary",
        "suggestion_review_queue",
        "suggestion_explain",
        "suggestion_outcome_lookup",
        "sentiment_explain",
        "narrative_analysis",
        "semantic_profile_explain",
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


class NoesisAuditEntry(BaseModel):
    request_id: str
    user_id: Optional[str] = None
    tenant_id: str
    requested_tenant_id: Optional[str] = None
    effective_tenant_id: str
    surface: str
    role: str
    permissions: list[str] = Field(default_factory=list)
    intent: str
    mode: str
    result_count: int = 0
    debug_returned: bool = False
    fallback_triggered: bool = False
    provider_used: Optional[str] = None
    rejected: bool = False
    rejection_reason: Optional[str] = None
    correlation_id: Optional[str] = None
    timestamp: Optional[datetime] = None
