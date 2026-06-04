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
  - A2H interactions (notifications, recommendations, deliveries, escalations)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from config.settings import settings
from shared.common.common import APIResponse, BadRequestError, ConflictError, NotFoundError
from shared.events.events import Event, EventProducer, Topic
from shared.graph.graph import Edge, EdgeType, GraphClient, Vertex, VertexType
from shared.graph.relationship_layers import get_cross_layer_paths, get_layer_subgraph, RelationshipLayer
from shared.logger.logger import get_logger, metrics
from shared.scoring.trust_score import TrustScoreComposite
from shared.store import get_store
from services.agent.runtime_repository import (
    CONTROLLERS, QUEUES, REVIEW_STATUSES, OBJECTIVE_STATUSES, MUTATION_CLASSES,
    get_agent_runtime_repository, stable_idempotency_key, utc_now,
)


def _queue_for_controller(name: str) -> str:
    """Map a controller to the Celery queue it is routed to.

    Mirrors ``Agent Layer/queue/celery_app.py`` task_routes: the named
    controller queues route 1:1, everything else falls to ``default``.
    """
    return name if name in QUEUES else "default"


def _validate_mutation_classes(staged: Any) -> None:
    """Reject malformed staged-mutation classes before anything is persisted."""
    if not isinstance(staged, list):
        return
    for mutation in staged:
        raw = mutation.get("mutation_class", mutation.get("class", 1)) if isinstance(mutation, dict) else None
        try:
            mutation_class = int(raw)
        except (TypeError, ValueError):
            raise BadRequestError("mutation_class must be an integer in 1, 2, 3, 4, or 5")
        if mutation_class not in MUTATION_CLASSES:
            raise BadRequestError("mutation_class must be one of 1, 2, 3, 4, or 5")

logger = get_logger("aether.service.agent")
router = APIRouter(prefix="/v1/agent", tags=["Agent"])

# Shared instances (in production, injected via dependency providers)
_graph = GraphClient()
_producer = EventProducer()
_trust_scorer = TrustScoreComposite()

_runtime_repo = get_agent_runtime_repository()


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "") or request.headers.get("X-Correlation-ID", "")


def _actor_id(request: Request) -> str:
    tenant = request.state.tenant
    return getattr(tenant, "user_id", None) or getattr(tenant, "tenant_id", "operator")


def _envelope(data: Any, request: Request, status: str = "success", meta: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "data": data,
        "status": status,
        "timestamp": utc_now(),
        "meta": {"request_id": _request_id(request), **(meta or {})},
    }


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
    reason: str = ""


class ObjectiveSubmission(BaseModel):
    goal: str = Field(..., min_length=3, max_length=4000)
    objective_type: str = Field(default="operator_directive", max_length=128)
    severity: str = Field(default="medium", pattern="^(critical|high|medium|low|background)$")
    priority: int = Field(default=2, ge=0, le=9)
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = ""


class ObjectiveAction(BaseModel):
    reason: str = ""


class DispatchRequest(BaseModel):
    objective_id: str
    controller: str = Field(default="nous")


class ReviewDecision(BaseModel):
    notes: str = ""


class ControllerHeartbeat(BaseModel):
    controller: str
    status: str = Field(default="healthy", pattern="^(healthy|degraded|failed|unknown)$")
    queue_depth: int = Field(default=0, ge=0)
    worker_id: str = "kyber"
    metadata: dict[str, Any] = Field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════
# HOSTED AGENT LAYER CONTROL PLANE — Kyber operator API
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/health")
async def controller_health(request: Request):
    """Aggregate controller health, queue depths and durable kill-switch state."""
    tenant = request.state.tenant
    tenant.require_permission("agent:manage")
    controllers = await _runtime_repo.controller_status(tenant.tenant_id)
    kill_switch = await _runtime_repo.get_kill_switch(tenant.tenant_id)
    objectives = await _runtime_repo.list_objectives(tenant.tenant_id, limit=500)
    review_batches = await _runtime_repo.list_review_batches(tenant.tenant_id, status="pending", limit=500)
    active = sum(1 for objective in objectives if objective.get("status") == "active")
    blocked = sum(1 for objective in objectives if objective.get("status") == "blocked")
    failed = sum(1 for objective in objectives if objective.get("status") == "failed")
    for name, value in {
        "agent_active_objectives": active,
        "agent_blocked_objectives": blocked,
        "agent_failed_objectives": failed,
        "agent_awaiting_review": len(review_batches),
        "agent_kill_switch_state": int(bool(kill_switch.get("enabled"))),
    }.items():
        # These are point-in-time snapshots; observe them (gauge semantics) so a
        # 10s Kyber health poll doesn't inflate the counts into the thousands.
        metrics.observe(name, float(value))
    return _envelope({
        "kill_switch": kill_switch,
        "controllers": controllers,
        "queues": [
            {"name": queue, "depth": sum(
                int(c.get("queue_depth", 0) or 0)
                for c in controllers
                if _queue_for_controller(c.get("controller", "")) == queue
            )}
            for queue in QUEUES
        ],
        "objectives": {"active": active, "blocked": blocked, "failed": failed, "total": len(objectives)},
        "review": {"awaiting_review": len(review_batches)},
    }, request)


@router.post("/objectives")
async def submit_objective(body: ObjectiveSubmission, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("agent:manage")
    kill_switch = await _runtime_repo.get_kill_switch(tenant.tenant_id)
    if kill_switch.get("enabled"):
        raise ConflictError("Agent kill switch is engaged; release it before submitting objectives")
    payload = body.payload
    staged = payload.get("staged_mutations") if isinstance(payload, dict) else None
    # Validate client-controlled mutation classes BEFORE persisting the objective,
    # so a malformed payload returns 400 instead of a 500 that strands a queued
    # objective with no review batch.
    _validate_mutation_classes(staged)
    idem = body.idempotency_key or stable_idempotency_key(tenant.tenant_id, body.model_dump())
    objective = await _runtime_repo.create_objective(
        tenant.tenant_id, body.goal, body.objective_type, body.severity, body.priority,
        payload, _actor_id(request), idem, _request_id(request),
    )
    # Idempotent retries (same idempotency key) return the existing objective; only
    # stage a review batch the first time so retries don't pile up duplicate
    # pending approvals for a single objective.
    if isinstance(staged, list) and staged and not await _runtime_repo.review_batches_for_objective(
        tenant.tenant_id, objective["objective_id"]
    ):
        await _runtime_repo.create_review_batch(tenant.tenant_id, objective["objective_id"], staged, _actor_id(request), _request_id(request))
        objective["status"] = "awaiting_review"
        objective["updated_at"] = utc_now()
        await _runtime_repo.objectives.set(objective["objective_id"], objective)
    metrics.increment("agent_objectives_created", labels={"type": body.objective_type})
    return _envelope(objective, request)


@router.get("/objectives")
async def list_objectives(request: Request, status: str | None = None, limit: int = 100):
    tenant = request.state.tenant
    tenant.require_permission("agent:manage")
    if status and status not in OBJECTIVE_STATUSES:
        raise BadRequestError(f"Invalid objective status: {status}")
    rows = await _runtime_repo.list_objectives(tenant.tenant_id, status=status, limit=limit)
    return _envelope({"objectives": rows, "total": len(rows)}, request)


@router.get("/objectives/{objective_id}")
async def get_objective(objective_id: str, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("agent:manage")
    objective = await _runtime_repo.get_objective(tenant.tenant_id, objective_id)
    if objective is None:
        raise NotFoundError("Objective")
    plans = await _runtime_repo.plans.find(tenant_id=tenant.tenant_id, objective_id=objective_id)
    steps = await _runtime_repo.steps.find(tenant_id=tenant.tenant_id, objective_id=objective_id)
    checkpoints = await _runtime_repo.checkpoints.find(tenant_id=tenant.tenant_id, objective_id=objective_id)
    events = await _runtime_repo.events_for_tenant(tenant.tenant_id, limit=100, objective_id=objective_id)
    return _envelope({"objective": objective, "plans": plans, "steps": steps, "checkpoints": checkpoints, "events": events}, request)


@router.post("/objectives/{objective_id}/pause")
async def pause_objective(objective_id: str, body: ObjectiveAction, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("agent:pause")
    objective = await _runtime_repo.transition_objective(tenant.tenant_id, objective_id, "pause", _actor_id(request), _request_id(request), reason=body.reason)
    if objective is None:
        raise NotFoundError("Objective")
    return _envelope(objective, request)


@router.post("/objectives/{objective_id}/resume")
async def resume_objective(objective_id: str, body: ObjectiveAction, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("agent:dispatch")
    objective = await _runtime_repo.transition_objective(tenant.tenant_id, objective_id, "resume", _actor_id(request), _request_id(request), reason=body.reason)
    if objective is None:
        raise NotFoundError("Objective")
    return _envelope(objective, request)


@router.post("/objectives/{objective_id}/cancel")
async def cancel_objective(objective_id: str, body: ObjectiveAction, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("agent:pause")
    objective = await _runtime_repo.transition_objective(tenant.tenant_id, objective_id, "cancel", _actor_id(request), _request_id(request), reason=body.reason)
    if objective is None:
        raise NotFoundError("Objective")
    return _envelope(objective, request)


@router.post("/dispatch")
async def dispatch_step(body: DispatchRequest, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("agent:dispatch")
    if body.controller not in CONTROLLERS:
        raise BadRequestError(f"Unknown controller: {body.controller}")
    kill_switch = await _runtime_repo.get_kill_switch(tenant.tenant_id)
    if kill_switch.get("enabled"):
        raise ConflictError("Agent kill switch is engaged; dispatch is disabled")
    run = await _runtime_repo.record_dispatch(tenant.tenant_id, body.objective_id, body.controller, _actor_id(request), _request_id(request))
    if run is None:
        raise NotFoundError("Objective")
    # Actually enqueue the run for a worker to consume — recording the run row
    # alone leaves dispatch reporting success while no controller ever picks it
    # up. Publish on the agent task topic with the routing/idempotency metadata.
    await _producer.publish(Event(
        topic=Topic.AGENT_TASK_STARTED,
        tenant_id=tenant.tenant_id,
        source_service="agent",
        payload={
            "run_id": run["run_id"],
            "objective_id": run["objective_id"],
            "controller": run["controller"],
            "queue": run["queue"],
            "idempotency_key": run["idempotency_key"],
        },
    ))
    metrics.increment("agent_worker_runs_queued", labels={"controller": body.controller, "queue": run["queue"]})
    return _envelope(run, request)


@router.get("/review-batches")
async def list_review_batches(request: Request, status: str | None = None, limit: int = 100):
    tenant = request.state.tenant
    tenant.require_permission("agent:manage")
    if status and status not in REVIEW_STATUSES:
        raise BadRequestError(f"Invalid review status: {status}")
    batches = await _runtime_repo.list_review_batches(tenant.tenant_id, status=status, limit=limit)
    return _envelope({"batches": batches, "total": len(batches)}, request)


@router.post("/review-batches/{batch_id}/approve")
async def approve_review_batch(batch_id: str, body: ReviewDecision, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("agent:approve")
    batch = await _runtime_repo.review_decision(tenant.tenant_id, batch_id, "approve", _actor_id(request), body.notes, _request_id(request))
    if batch is None:
        raise NotFoundError("Review batch")
    metrics.increment("agent_mutation_approvals")
    return _envelope(batch, request)


@router.post("/review-batches/{batch_id}/reject")
async def reject_review_batch(batch_id: str, body: ReviewDecision, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("agent:approve")
    batch = await _runtime_repo.review_decision(tenant.tenant_id, batch_id, "reject", _actor_id(request), body.notes, _request_id(request))
    if batch is None:
        raise NotFoundError("Review batch")
    metrics.increment("agent_mutation_rejections")
    return _envelope(batch, request)


@router.get("/events")
async def timeline_events(request: Request, objective_id: str | None = None, limit: int = 100):
    tenant = request.state.tenant
    tenant.require_permission("agent:manage")
    events = await _runtime_repo.events_for_tenant(tenant.tenant_id, limit=limit, objective_id=objective_id)
    return _envelope({"events": events, "total": len(events)}, request)


@router.post("/controllers/heartbeat")
async def controller_heartbeat(body: ControllerHeartbeat, request: Request):
    tenant = request.state.tenant
    # Heartbeats drive health/stale-worker detection, so they must come from a
    # worker service credential — not any operator holding agent:manage, who
    # could otherwise make a dead controller look healthy.
    tenant.require_permission("agent:heartbeat")
    if body.controller not in CONTROLLERS:
        raise BadRequestError(f"Unknown controller: {body.controller}")
    heartbeat = await _runtime_repo.heartbeat(tenant.tenant_id, body.controller, body.status, body.queue_depth, body.worker_id, body.metadata, _request_id(request))
    metrics.increment("agent_controller_heartbeats", labels={"controller": body.controller, "status": body.status})
    return _envelope(heartbeat, request)


@router.get("/controllers/status")
async def controllers_status(request: Request):
    tenant = request.state.tenant
    tenant.require_permission("agent:manage")
    controllers = await _runtime_repo.controller_status(tenant.tenant_id)
    return _envelope({"controllers": controllers, "total": len(controllers)}, request)


@router.get("/status")
async def agent_status(request: Request):
    """Get current agent layer status."""
    tenant = request.state.tenant
    tenant.require_permission("agent:manage")
    health = await controller_health(request)
    data = dict(health["data"])
    kill_switch = data.get("kill_switch")
    data.update({
        # /v1/agent/status exposes kill_switch as a boolean (Kyber's client schema
        # validates z.boolean()); surface the full record under kill_switch_state
        # so the richer health() shape is still available without breaking the
        # status contract.
        "kill_switch": bool(kill_switch.get("enabled")) if isinstance(kill_switch, dict) else bool(kill_switch),
        "kill_switch_state": kill_switch if isinstance(kill_switch, dict) else None,
        "active_workers": sum(1 for c in data["controllers"] if c.get("status") in {"healthy", "degraded"}),
        "worker_types": VALID_WORKER_TYPES,
        # Kyber's Command/Mission views render status.workers; map controller
        # health rows back into that array so they aren't left empty.
        "workers": [
            {
                "worker_type": c.get("controller"),
                "status": c.get("status", "unknown"),
                "current_task": None,
                "queue_depth": c.get("queue_depth", 0),
                "worker_count": c.get("worker_count", 0),
            }
            for c in data["controllers"]
        ],
    })
    return _envelope(data, request)


# ── Durable Task & Audit Stores ───────────────────────────────────────

_task_store = get_store("agent_tasks")
_audit_store = get_store("agent_audit")

_PRIORITY_MAP = {
    "critical": 0, "high": 1, "medium": 2, "low": 3, "background": 4,
}


@router.post("/tasks")
async def submit_task(body: TaskSubmission, request: Request):
    """Submit a new task to the agent controller.

    Creates a task record, validates the payload, and queues it for
    execution by the appropriate agent worker. Returns immediately
    with a task ID for status polling.
    """
    tenant = request.state.tenant
    tenant.require_permission("agent:manage")

    # Honour the tenant emergency stop here too — the legacy task path must not
    # be a way to keep queuing agent work after the kill switch is engaged.
    kill_switch = await _runtime_repo.get_kill_switch(tenant.tenant_id)
    if kill_switch.get("enabled"):
        raise ConflictError("Agent kill switch is engaged; release it before submitting tasks")

    if body.worker_type not in VALID_WORKER_TYPES:
        raise BadRequestError(
            f"Unknown worker type: {body.worker_type}. "
            f"Valid types: {VALID_WORKER_TYPES}"
        )

    task_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    task = {
        "task_id": task_id,
        "tenant_id": tenant.tenant_id,
        "worker_type": body.worker_type,
        "priority": body.priority,
        "priority_value": _PRIORITY_MAP.get(body.priority, 2),
        "payload": body.payload,
        "status": "queued",
        "created_at": now,
        "started_at": None,
        "completed_at": None,
        "result": None,
        "error": None,
    }
    await _task_store.set(task_id, task)

    # Publish task event for the agent controller to pick up
    await _producer.publish(Event(
        topic=Topic.AGENT_TASK_STARTED,
        tenant_id=tenant.tenant_id,
        source_service="agent",
        payload=task,
    ))

    # Record audit entry
    await _audit_store.append_list(
        tenant.tenant_id,
        {
            "task_id": task_id,
            "action": "task_submitted",
            "worker_type": body.worker_type,
            "tenant_id": tenant.tenant_id,
            "timestamp": now,
        },
    )

    metrics.increment("agent_tasks_submitted", labels={"worker_type": body.worker_type})
    logger.info(
        "Task submitted: id=%s type=%s priority=%s tenant=%s",
        task_id, body.worker_type, body.priority, tenant.tenant_id,
    )

    return _envelope({
        "task_id": task_id,
        "worker_type": body.worker_type,
        "priority": body.priority,
        "status": "queued",
        "created_at": now,
        "started_at": None,
        "completed_at": None,
        "result": None,
        "error": None,
    }, request)


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, request: Request):
    """Get task status and result.

    Returns the current task state including status, result (if completed),
    and error (if failed).
    """
    tenant = request.state.tenant
    tenant.require_permission("agent:manage")

    task = await _task_store.get(task_id)
    if task is None or task.get("tenant_id") != tenant.tenant_id:
        raise NotFoundError("Task")

    return _envelope({
        "task_id": task["task_id"],
        "worker_type": task["worker_type"],
        "priority": task["priority"],
        "status": task["status"],
        "created_at": task["created_at"],
        "started_at": task["started_at"],
        "completed_at": task["completed_at"],
        "result": task["result"],
        "error": task["error"],
    }, request)


@router.get("/audit")
async def get_audit_trail(request: Request, limit: int = 50):
    """Get the agent audit trail for this tenant.

    Returns the most recent audit records, filtered by tenant.
    """
    tenant = request.state.tenant
    tenant.require_permission("agent:manage")

    tenant_records = await _audit_store.get_list(tenant.tenant_id, limit=limit)
    # Return most recent first
    records = sorted(
        tenant_records, key=lambda r: r.get("timestamp", ""), reverse=True
    )[:limit]

    return _envelope({
        "records": records,
        "total": len(tenant_records),
    }, request)


@router.post("/kill-switch")
async def toggle_kill_switch(body: KillSwitchAction, request: Request):
    """Engage or release the tenant-scoped agent kill switch."""
    tenant = request.state.tenant
    tenant.require_permission("admin")
    enabled = body.action == "engage"
    state = await _runtime_repo.set_kill_switch(tenant.tenant_id, enabled, _actor_id(request), body.reason, _request_id(request))
    logger.warning("Agent kill switch action=%s tenant=%s request_id=%s", body.action, tenant.tenant_id, _request_id(request))
    metrics.increment("agent_kill_switch_toggled", labels={"enabled": str(enabled).lower()})
    return _envelope({"kill_switch": enabled, "action": body.action, "state": state}, request)


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
            raise BadRequestError(f"Invalid layer: {layer}. Use H2H, H2A, A2H, A2A, or all")
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


# ═══════════════════════════════════════════════════════════════════════════
# INTELLIGENCE GRAPH — Agent-to-Human (A2H)
# ═══════════════════════════════════════════════════════════════════════════

VALID_A2H_TYPES = {"notification", "recommendation", "delivery", "escalation"}

_A2H_EDGE_MAP = {
    "notification": EdgeType.NOTIFIES,
    "recommendation": EdgeType.RECOMMENDS,
    "delivery": EdgeType.DELIVERS_TO,
    "escalation": EdgeType.ESCALATES_TO,
}

_A2H_TOPIC_MAP = {
    "notification": Topic.AGENT_NOTIFICATION_SENT,
    "recommendation": Topic.AGENT_RECOMMENDATION_MADE,
    "delivery": Topic.AGENT_RESULT_DELIVERED,
    "escalation": Topic.AGENT_ESCALATION_RAISED,
}


class A2HInteraction(BaseModel):
    """Record an agent-to-human interaction (notification, recommendation, delivery, escalation)."""
    agent_id: str
    target_user_id: str
    interaction_type: str = Field(..., description="One of: notification, recommendation, delivery, escalation")
    content_summary: str = ""
    task_id: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    properties: dict[str, Any] = Field(default_factory=dict)


@router.post("/{agent_id}/a2h")
async def record_a2h_interaction(agent_id: str, body: A2HInteraction, request: Request):
    """Record an agent-to-human interaction and create A2H edge in the graph.

    Supports four interaction types:
    - **notification**: Agent sends an alert or status update to a user
    - **recommendation**: Agent proactively suggests an action to a user
    - **delivery**: Agent delivers a completed task result to a user
    - **escalation**: Agent escalates a decision to a human for review
    """
    if not settings.intelligence_graph.enable_agent_layer:
        raise BadRequestError("Intelligence Graph agent layer is not enabled")
    tenant = request.state.tenant
    tenant.require_permission("agent:manage")
    body.agent_id = agent_id

    if body.interaction_type not in VALID_A2H_TYPES:
        raise BadRequestError(
            f"Invalid A2H interaction type: {body.interaction_type}. "
            f"Valid: {sorted(VALID_A2H_TYPES)}"
        )

    edge_type = _A2H_EDGE_MAP[body.interaction_type]
    topic = _A2H_TOPIC_MAP[body.interaction_type]
    now = datetime.now(timezone.utc).isoformat()

    # Create A2H edge: Agent → User
    await _graph.add_edge(Edge(
        edge_type=edge_type,
        from_vertex_id=agent_id,
        to_vertex_id=body.target_user_id,
        properties={
            "content_summary": body.content_summary,
            "task_id": body.task_id or "",
            "confidence": str(body.confidence),
            "tenant_id": tenant.tenant_id,
            **body.properties,
        },
    ))

    # Publish A2H event
    await _producer.publish(Event(
        topic=topic,
        tenant_id=tenant.tenant_id,
        source_service="agent",
        payload={
            "agent_id": agent_id,
            "target_user_id": body.target_user_id,
            "interaction_type": body.interaction_type,
            "content_summary": body.content_summary,
            "task_id": body.task_id,
            "confidence": body.confidence,
            "timestamp": now,
        },
    ))

    metrics.increment("agent_a2h_interactions", labels={"type": body.interaction_type})
    logger.info(
        "A2H interaction: agent=%s type=%s target=%s",
        agent_id, body.interaction_type, body.target_user_id,
    )

    return APIResponse(data={
        "agent_id": agent_id,
        "target_user_id": body.target_user_id,
        "interaction_type": body.interaction_type,
        "edge_type": edge_type,
        "timestamp": now,
    }).to_dict()
