"""
Aether Service — Agent
AI agent orchestration, task management, worker coordination.
Bridges to the aether-agent-layer module.

Intelligence Graph extensions (L2 — Agent Behavioral):
  - Agent registration with graph binding
  - Task lifecycle events with state snapshots
  - Decision records (roads not taken)
  - Ground truth feedback loop with confidence_delta
  - Agent subgraph and trust score queries
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from config.settings import settings
from shared.common.common import APIResponse, BadRequestError
from shared.events.events import Event, EventProducer, Topic
from shared.graph.graph import Edge, EdgeType, GraphClient, Vertex, VertexType
from shared.graph.relationship_layers import get_cross_layer_paths, get_layer_subgraph, RelationshipLayer
from shared.logger.logger import get_logger, metrics
from shared.scoring.trust_score import TrustScoreComposite

logger = get_logger("aether.service.agent")
router = APIRouter(prefix="/v1/agent", tags=["Agent"])

# Shared instances (in production, injected via dependency providers)
_graph = GraphClient()
_producer = EventProducer()
_trust_scorer = TrustScoreComposite()

VALID_WORKER_TYPES = [
    "web_crawler", "api_scanner", "social_listener",
    "chain_monitor", "competitor_tracker",
    "entity_resolver", "profile_enricher", "temporal_filler",
    "semantic_tagger", "quality_scorer",
]


class TaskSubmission(BaseModel):
    worker_type: str
    priority: str = Field(default="medium", pattern="^(critical|high|medium|low|background)$")
    payload: dict[str, Any] = Field(default_factory=dict)


class KillSwitchAction(BaseModel):
    action: str = Field(..., pattern="^(engage|release)$")


@router.get("/status")
async def agent_status(request: Request):
    """Get current agent layer status."""
    request.state.tenant.require_permission("agent:manage")
    return APIResponse(data={
        "kill_switch": False,
        "queue_depth": 0,
        "active_workers": 0,
        "worker_types": VALID_WORKER_TYPES,
    }).to_dict()


@router.post("/tasks")
async def submit_task(body: TaskSubmission, request: Request):
    """Submit a new task to the agent controller."""
    request.state.tenant.require_permission("agent:manage")

    if body.worker_type not in VALID_WORKER_TYPES:
        raise BadRequestError(f"Unknown worker type: {body.worker_type}")

    return APIResponse(data={
        "task_id": "stub_task_001",
        "worker_type": body.worker_type,
        "priority": body.priority,
        "status": "queued",
    }).to_dict()


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, request: Request):
    """Get task status and result."""
    request.state.tenant.require_permission("agent:manage")
    return APIResponse(data={
        "task_id": task_id,
        "status": "stub",
        "result": None,
    }).to_dict()


@router.get("/audit")
async def get_audit_trail(request: Request, limit: int = 50):
    """Get the agent audit trail."""
    request.state.tenant.require_permission("agent:manage")
    return APIResponse(data={"records": [], "total": 0}).to_dict()


@router.post("/kill-switch")
async def toggle_kill_switch(body: KillSwitchAction, request: Request):
    """Engage or release the agent kill switch."""
    request.state.tenant.require_permission("admin")
    logger.warning(f"Kill switch action: {body.action}")
    return APIResponse(data={
        "kill_switch": body.action == "engage",
        "action": body.action,
    }).to_dict()


# ═══════════════════════════════════════════════════════════════════════════
# INTELLIGENCE GRAPH — Agent Behavioral (L2)
# ═══════════════════════════════════════════════════════════════════════════

class AgentRegistration(BaseModel):
    """Register an AI agent with the intelligence graph."""
    agent_id: str = ""
    owner_user_id: str
    model_name: str
    model_version: str = "1.0"
    capabilities: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    status: str = Field(default="active", pattern="^(active|paused|terminated)$")


class DecisionRecord(BaseModel):
    """Roads not taken — captures rejected alternatives for ground truth learning."""
    chosen_action: str
    rejected_alternatives: list[str] = Field(default_factory=list)
    reasoning: str = ""
    confidence: float = 0.0


class TaskLifecycleEvent(BaseModel):
    """Records a task lifecycle event with state snapshot."""
    task_id: str
    agent_id: str
    event_type: str = Field(
        ..., pattern="^(started|tool_called|decision_made|completed|verified)$"
    )
    state_snapshot: dict[str, Any] = Field(default_factory=dict)
    decision_record: Optional[DecisionRecord] = None
    confidence: float = 0.0
    tenant_id: str = ""
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class GroundTruthFeedback(BaseModel):
    """Submit ground truth feedback for a completed task."""
    task_id: str
    agent_id: str
    predicted_outcome: str
    actual_outcome: str
    confidence_delta: float = 0.0
    verified_by: str = Field(default="human", pattern="^(human|automated)$")
    tenant_id: str = ""
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# In-memory stores (production: backed by TimescaleDB + Neptune)
_registered_agents: dict[str, AgentRegistration] = {}
_lifecycle_events: list[TaskLifecycleEvent] = []
_feedback_records: list[GroundTruthFeedback] = []


@router.post("/register")
async def register_agent(body: AgentRegistration, request: Request):
    """Register an agent and create AGENT vertex + LAUNCHED_BY edge in the graph."""
    if not settings.intelligence_graph.enable_agent_layer:
        raise BadRequestError("Intelligence Graph agent layer is not enabled")
    request.state.tenant.require_permission("agent:manage")

    if not body.agent_id:
        body.agent_id = str(uuid.uuid4())

    tenant_id = request.state.tenant.tenant_id

    # Create AGENT vertex
    vertex = Vertex(
        vertex_type=VertexType.AGENT,
        vertex_id=body.agent_id,
        properties={
            "owner_user_id": body.owner_user_id,
            "model_name": body.model_name,
            "model_version": body.model_version,
            "capabilities": ",".join(body.capabilities),
            "status": body.status,
        },
    )
    await _graph.add_vertex(vertex)

    # Create LAUNCHED_BY edge: agent -> user
    await _graph.add_edge(Edge(
        edge_type=EdgeType.LAUNCHED_BY,
        from_vertex_id=body.agent_id,
        to_vertex_id=body.owner_user_id,
    ))

    # Create DELEGATES edge: user -> agent
    await _graph.add_edge(Edge(
        edge_type=EdgeType.DELEGATES,
        from_vertex_id=body.owner_user_id,
        to_vertex_id=body.agent_id,
        properties={"permissions": ",".join(body.permissions)},
    ))

    _registered_agents[f"{tenant_id}:{body.agent_id}"] = body
    metrics.increment("agents_registered")
    logger.info(f"Agent registered: {body.agent_id} (owner={body.owner_user_id})")

    return APIResponse(data=body.model_dump()).to_dict()


@router.post("/tasks/{task_id}/lifecycle")
async def record_lifecycle_event(task_id: str, body: TaskLifecycleEvent, request: Request):
    """Record a task lifecycle event with state snapshot."""
    if not settings.intelligence_graph.enable_agent_layer:
        raise BadRequestError("Intelligence Graph agent layer is not enabled")
    request.state.tenant.require_permission("agent:manage")
    body.task_id = task_id
    body.tenant_id = request.state.tenant.tenant_id

    # Determine event topic
    topic_map = {
        "started": Topic.AGENT_TASK_STARTED,
        "completed": Topic.AGENT_TASK_COMPLETED,
        "decision_made": Topic.AGENT_DECISION_MADE,
    }
    topic = topic_map.get(body.event_type, Topic.AGENT_STATE_SNAPSHOT)

    await _producer.publish(Event(
        topic=topic,
        payload=body.model_dump(),
        source_service="agent",
    ))

    _lifecycle_events.append(body)
    metrics.increment("agent_lifecycle_events", labels={"type": body.event_type})
    logger.info(f"Lifecycle event: task={task_id} type={body.event_type} agent={body.agent_id}")

    return APIResponse(data=body.model_dump()).to_dict()


@router.post("/tasks/{task_id}/decision")
async def record_decision(task_id: str, body: TaskLifecycleEvent, request: Request):
    """Record a decision with rejected alternatives (roads not taken)."""
    if not settings.intelligence_graph.enable_agent_layer:
        raise BadRequestError("Intelligence Graph agent layer is not enabled")
    request.state.tenant.require_permission("agent:manage")
    body.task_id = task_id
    body.event_type = "decision_made"
    body.tenant_id = request.state.tenant.tenant_id

    await _producer.publish(Event(
        topic=Topic.AGENT_DECISION_MADE,
        payload=body.model_dump(),
        source_service="agent",
    ))

    _lifecycle_events.append(body)
    metrics.increment("agent_decisions_recorded")

    return APIResponse(data=body.model_dump()).to_dict()


@router.post("/tasks/{task_id}/feedback")
async def submit_feedback(task_id: str, body: GroundTruthFeedback, request: Request):
    """Submit ground truth feedback and compute confidence_delta."""
    if not settings.intelligence_graph.enable_agent_layer:
        raise BadRequestError("Intelligence Graph agent layer is not enabled")
    request.state.tenant.require_permission("agent:manage")
    body.task_id = task_id
    body.tenant_id = request.state.tenant.tenant_id

    # Compute confidence_delta from lifecycle events (filtered by tenant)
    tenant_id = request.state.tenant.tenant_id
    task_events = [
        e for e in _lifecycle_events
        if e.task_id == task_id and e.tenant_id == tenant_id
    ]
    if task_events:
        predicted_confidence = task_events[-1].confidence
        # Use string similarity for near-misses instead of binary exact match
        similarity = SequenceMatcher(None, body.predicted_outcome, body.actual_outcome).ratio()
        body.confidence_delta = round(similarity - predicted_confidence, 4)

    await _producer.publish(Event(
        topic=Topic.AGENT_GROUND_TRUTH,
        payload=body.model_dump(),
        source_service="agent",
    ))

    _feedback_records.append(body)
    metrics.increment("agent_feedback_submitted", labels={"verified_by": body.verified_by})
    logger.info(
        f"Ground truth: task={task_id} delta={body.confidence_delta} "
        f"verified_by={body.verified_by}"
    )

    return APIResponse(data=body.model_dump()).to_dict()


@router.get("/{agent_id}/graph")
async def get_agent_graph(agent_id: str, request: Request, layer: str = "all"):
    """Get an agent's subgraph (hired agents, contracts, payments)."""
    if not settings.intelligence_graph.enable_agent_layer:
        raise BadRequestError("Intelligence Graph agent layer is not enabled")
    request.state.tenant.require_permission("agent:manage")

    if layer != "all":
        try:
            rel_layer = RelationshipLayer(layer)
        except ValueError:
            raise BadRequestError(f"Invalid layer: {layer}. Use H2H, H2A, A2A, or all")
        subgraph = await get_layer_subgraph(_graph, agent_id, rel_layer)
    else:
        # Get all connected vertices
        neighbors = await _graph.get_neighbors(agent_id, direction="both")
        subgraph = {
            "agent_id": agent_id,
            "vertices": [
                {"id": v.vertex_id, "type": v.vertex_type, "properties": v.properties}
                for v in neighbors
            ],
            "vertex_count": len(neighbors),
        }

    # Add cross-layer paths
    paths = await get_cross_layer_paths(_graph, agent_id)
    subgraph["cross_layer_paths"] = paths

    return APIResponse(data=subgraph).to_dict()


@router.get("/{agent_id}/trust")
async def get_agent_trust(agent_id: str, request: Request):
    """Get an agent's composite trust score."""
    if not settings.intelligence_graph.enable_agent_layer:
        raise BadRequestError("Intelligence Graph agent layer is not enabled")
    if not settings.intelligence_graph.enable_trust_scoring:
        raise BadRequestError("Intelligence Graph agent layer is not enabled")
    request.state.tenant.require_permission("agent:manage")

    score = await _trust_scorer.compute(
        entity_id=agent_id,
        entity_type="agent",
    )

    return APIResponse(data=score.to_dict()).to_dict()
