"""
Durable repository for the hosted Agent Layer control plane.

The controller architecture remains in the Agent Layer package; this repository
is the backend/Kyber-facing durable state boundary. It uses the shared store
abstraction so local mode remains in-memory while hosted modes require Redis (or
an explicit AETHER_ALLOW_INMEMORY_STORE override).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from shared.store import DurableStore, get_store


OBJECTIVE_STATUSES = {"queued", "active", "paused", "blocked", "awaiting_review", "completed", "failed", "cancelled"}
REVIEW_STATUSES = {"pending", "approved", "rejected", "committed", "quarantined", "rolled_back"}
MUTATION_STATUSES = {"staged", "approved", "rejected", "committed", "quarantined", "rolled_back"}
MUTATION_CLASSES = {1, 2, 3, 4, 5}
CONTROLLERS = [
    "governance",
    "nous",
    "intake",
    "discovery",
    "enrichment",
    "verification",
    "commit",
    "recovery",
    "kinesis",
    "catalyst",
    "cycle",
]
QUEUES = ["default", "discovery", "enrichment", "verification", "commit", "recovery"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def stable_idempotency_key(tenant_id: str, payload: dict[str, Any]) -> str:
    raw = json.dumps({"tenant_id": tenant_id, "payload": payload}, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def sanitize_payload(value: Any) -> Any:
    """Remove obvious secrets before persisting events/review payloads."""
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            lowered = key.lower()
            if any(token in lowered for token in ("secret", "token", "password", "api_key", "apikey", "authorization")):
                clean[key] = "[redacted]"
            else:
                clean[key] = sanitize_payload(item)
        return clean
    if isinstance(value, list):
        return [sanitize_payload(item) for item in value]
    return value


class AgentRuntimeRepository:
    """Tenant-scoped durable state access for objectives, reviews and workers."""

    def __init__(self) -> None:
        self.objectives: DurableStore = get_store("agent_objectives")
        self.plans: DurableStore = get_store("agent_plans")
        self.steps: DurableStore = get_store("agent_plan_steps")
        self.checkpoints: DurableStore = get_store("agent_checkpoints")
        self.events: DurableStore = get_store("agent_events")
        self.review_batches: DurableStore = get_store("agent_review_batches")
        self.staged_mutations: DurableStore = get_store("agent_staged_mutations")
        self.heartbeats: DurableStore = get_store("agent_controller_heartbeats")
        self.worker_runs: DurableStore = get_store("agent_worker_runs")
        self.catalyst_triggers: DurableStore = get_store("catalyst_wake_triggers")
        self.control: DurableStore = get_store("agent_control")

    async def append_event(
        self,
        tenant_id: str,
        event_type: str,
        source: str,
        payload: dict[str, Any] | None = None,
        objective_id: str = "",
        actor_id: str = "system",
        request_id: str = "",
    ) -> dict[str, Any]:
        event = {
            "event_id": new_id("evt"),
            "tenant_id": tenant_id,
            "objective_id": objective_id,
            "event_type": event_type,
            "source": source,
            "actor_id": actor_id,
            "request_id": request_id,
            "payload": sanitize_payload(payload or {}),
            "created_at": utc_now(),
        }
        await self.events.set(event["event_id"], event)
        await self.events.append_list(tenant_id, event)
        return event

    async def create_objective(
        self,
        tenant_id: str,
        goal: str,
        objective_type: str,
        severity: str,
        priority: int,
        payload: dict[str, Any],
        opened_by: str,
        idempotency_key: str,
        request_id: str,
    ) -> dict[str, Any]:
        existing = await self.objectives.find(tenant_id=tenant_id, idempotency_key=idempotency_key)
        if existing:
            return existing[0]

        now = utc_now()
        objective = {
            "objective_id": new_id("obj"),
            "tenant_id": tenant_id,
            "type": objective_type,
            "goal": goal,
            "severity": severity,
            "priority": priority,
            "status": "queued",
            "payload": sanitize_payload(payload),
            "opened_by": opened_by,
            "idempotency_key": idempotency_key,
            "created_at": now,
            "updated_at": now,
            "paused_at": None,
            "cancelled_at": None,
        }
        await self.objectives.set(objective["objective_id"], objective)
        plan = {
            "plan_id": new_id("plan"),
            "tenant_id": tenant_id,
            "objective_id": objective["objective_id"],
            "status": "planned",
            "steps": [],
            "created_at": now,
            "updated_at": now,
        }
        await self.plans.set(plan["plan_id"], plan)
        await self.append_event(tenant_id, "objective.created", "intake", objective, objective["objective_id"], opened_by, request_id)
        return objective

    async def get_objective(self, tenant_id: str, objective_id: str) -> dict[str, Any] | None:
        objective = await self.objectives.get(objective_id)
        if not objective or objective.get("tenant_id") != tenant_id:
            return None
        return objective

    async def list_objectives(self, tenant_id: str, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        filters: dict[str, Any] = {"tenant_id": tenant_id}
        if status:
            filters["status"] = status
        rows = await self.objectives.find(**filters)
        rows.sort(key=lambda row: row.get("created_at", ""), reverse=True)
        return rows[:limit]

    async def transition_objective(self, tenant_id: str, objective_id: str, action: str, actor_id: str, request_id: str) -> dict[str, Any] | None:
        objective = await self.get_objective(tenant_id, objective_id)
        if objective is None:
            return None
        status_map = {"pause": "paused", "resume": "active", "cancel": "cancelled"}
        objective["status"] = status_map[action]
        objective["updated_at"] = utc_now()
        if action == "pause":
            objective["paused_at"] = objective["updated_at"]
        if action == "cancel":
            objective["cancelled_at"] = objective["updated_at"]
        await self.objectives.set(objective_id, objective)
        await self.append_event(tenant_id, f"objective.{action}d", "operator", {"status": objective["status"]}, objective_id, actor_id, request_id)
        return objective

    async def record_dispatch(self, tenant_id: str, objective_id: str, controller: str, actor_id: str, request_id: str) -> dict[str, Any] | None:
        objective = await self.get_objective(tenant_id, objective_id)
        if objective is None:
            return None
        now = utc_now()
        objective["status"] = "active"
        objective["updated_at"] = now
        await self.objectives.set(objective_id, objective)
        run = {
            "run_id": new_id("run"),
            "tenant_id": tenant_id,
            "objective_id": objective_id,
            "controller": controller,
            "queue": queue_for_controller(controller),
            "status": "queued",
            "attempt": 1,
            "idempotency_key": stable_idempotency_key(tenant_id, {"objective_id": objective_id, "controller": controller}),
            "created_at": now,
            "updated_at": now,
            "heartbeat_at": now,
            "error": None,
        }
        await self.worker_runs.set(run["run_id"], run)
        await self.append_event(tenant_id, "step.dispatched", controller, run, objective_id, actor_id, request_id)
        return run

    async def heartbeat(self, tenant_id: str, controller: str, status: str, queue_depth: int, worker_id: str, metadata: dict[str, Any], request_id: str) -> dict[str, Any]:
        heartbeat = {
            "heartbeat_id": f"{tenant_id}:{controller}:{worker_id}",
            "tenant_id": tenant_id,
            "controller": controller,
            "worker_id": worker_id,
            "status": status,
            "queue_depth": max(0, queue_depth),
            "metadata": sanitize_payload(metadata),
            "updated_at": utc_now(),
        }
        await self.heartbeats.set(heartbeat["heartbeat_id"], heartbeat)
        await self.append_event(tenant_id, "controller.heartbeat", controller, heartbeat, "", worker_id, request_id)
        return heartbeat

    async def controller_status(self, tenant_id: str) -> list[dict[str, Any]]:
        heartbeats = await self.heartbeats.find(tenant_id=tenant_id)
        by_controller = {row["controller"]: row for row in heartbeats}
        now = utc_now()
        return [
            by_controller.get(controller, {
                "tenant_id": tenant_id,
                "controller": controller,
                "worker_id": None,
                "status": "unknown",
                "queue_depth": 0,
                "metadata": {},
                "updated_at": now,
            })
            for controller in CONTROLLERS
        ]

    async def create_review_batch(self, tenant_id: str, objective_id: str, mutations: list[dict[str, Any]], actor_id: str, request_id: str) -> dict[str, Any]:
        now = utc_now()
        mutation_ids: list[str] = []
        for mutation in mutations:
            mutation_class = int(mutation.get("mutation_class", mutation.get("class", 1)))
            if mutation_class not in MUTATION_CLASSES:
                raise ValueError("mutation_class must be one of 1, 2, 3, 4, or 5")
            record = {
                "mutation_id": new_id("mut"),
                "tenant_id": tenant_id,
                "objective_id": objective_id,
                "mutation_class": mutation_class,
                "operation": mutation.get("operation", "upsert"),
                "target": sanitize_payload(mutation.get("target", {})),
                "diff": sanitize_payload(mutation.get("diff", {})),
                "status": "staged",
                "created_at": now,
                "updated_at": now,
            }
            await self.staged_mutations.set(record["mutation_id"], record)
            mutation_ids.append(record["mutation_id"])
            await self.append_event(tenant_id, "mutation.staged", "verification", record, objective_id, actor_id, request_id)
        batch = {
            "batch_id": new_id("review"),
            "tenant_id": tenant_id,
            "objective_id": objective_id,
            "status": "pending",
            "mutation_ids": mutation_ids,
            "created_at": now,
            "updated_at": now,
            "reviewed_by": None,
            "review_notes": None,
        }
        await self.review_batches.set(batch["batch_id"], batch)
        await self.append_event(tenant_id, "batch.created", "review_queue", batch, objective_id, actor_id, request_id)
        return batch

    async def list_review_batches(self, tenant_id: str, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        filters: dict[str, Any] = {"tenant_id": tenant_id}
        if status:
            filters["status"] = status
        batches = await self.review_batches.find(**filters)
        batches.sort(key=lambda row: row.get("created_at", ""), reverse=True)
        return batches[:limit]

    async def review_batches_for_objective(self, tenant_id: str, objective_id: str) -> list[dict[str, Any]]:
        return await self.review_batches.find(tenant_id=tenant_id, objective_id=objective_id)

    async def review_decision(self, tenant_id: str, batch_id: str, decision: str, reviewer: str, notes: str, request_id: str) -> dict[str, Any] | None:
        batch = await self.review_batches.get(batch_id)
        if not batch or batch.get("tenant_id") != tenant_id:
            return None
        if batch.get("status") != "pending":
            return batch
        now = utc_now()
        batch["status"] = "approved" if decision == "approve" else "rejected"
        batch["reviewed_by"] = reviewer
        batch["review_notes"] = sanitize_payload({"notes": notes}).get("notes", "")
        batch["updated_at"] = now
        await self.review_batches.set(batch_id, batch)
        mutation_status = "approved" if decision == "approve" else "rejected"
        for mutation_id in batch.get("mutation_ids", []):
            mutation = await self.staged_mutations.get(mutation_id)
            if mutation and mutation.get("tenant_id") == tenant_id:
                mutation["status"] = mutation_status
                mutation["updated_at"] = now
                await self.staged_mutations.set(mutation_id, mutation)
                await self.append_event(tenant_id, f"mutation.{mutation_status}", "review_queue", mutation, batch.get("objective_id", ""), reviewer, request_id)
        await self.append_event(tenant_id, f"batch.{batch['status']}", "review_queue", batch, batch.get("objective_id", ""), reviewer, request_id)
        await self._advance_objective_after_review(tenant_id, batch.get("objective_id", ""), batch["status"], reviewer, request_id)
        return batch

    async def _advance_objective_after_review(self, tenant_id: str, objective_id: str, batch_status: str, reviewer: str, request_id: str) -> None:
        """Move an objective out of ``awaiting_review`` once no pending batches remain.

        Without this an objective stays stuck in ``awaiting_review`` forever after
        its only review batch is approved/rejected. An approval releases it back to
        active work; a rejection blocks it for operator follow-up.
        """
        if not objective_id:
            return
        pending = [
            b for b in await self.review_batches.find(tenant_id=tenant_id, objective_id=objective_id)
            if b.get("status") == "pending"
        ]
        if pending:
            return
        objective = await self.objectives.get(objective_id)
        if not objective or objective.get("tenant_id") != tenant_id or objective.get("status") != "awaiting_review":
            return
        objective["status"] = "active" if batch_status == "approved" else "blocked"
        objective["updated_at"] = utc_now()
        await self.objectives.set(objective_id, objective)
        await self.append_event(tenant_id, f"objective.{objective['status']}", "review_queue", objective, objective_id, reviewer, request_id)

    async def events_for_tenant(self, tenant_id: str, limit: int = 100, objective_id: str | None = None) -> list[dict[str, Any]]:
        if objective_id:
            rows = await self.events.find(tenant_id=tenant_id, objective_id=objective_id)
        else:
            rows = await self.events.get_list(tenant_id, limit=limit)
        rows.sort(key=lambda row: row.get("created_at", ""), reverse=True)
        return rows[:limit]

    async def set_kill_switch(self, tenant_id: str, enabled: bool, actor_id: str, reason: str, request_id: str) -> dict[str, Any]:
        state = {"tenant_id": tenant_id, "enabled": enabled, "reason": sanitize_payload({"reason": reason}).get("reason", ""), "updated_at": utc_now(), "updated_by": actor_id}
        await self.control.set(f"kill_switch:{tenant_id}", state)
        await self.append_event(tenant_id, "kill_switch.engaged" if enabled else "kill_switch.released", "governance", state, "", actor_id, request_id)
        return state

    async def get_kill_switch(self, tenant_id: str) -> dict[str, Any]:
        return await self.control.get(f"kill_switch:{tenant_id}") or {"tenant_id": tenant_id, "enabled": False, "reason": "", "updated_at": None, "updated_by": None}


_repo: AgentRuntimeRepository | None = None


def get_agent_runtime_repository() -> AgentRuntimeRepository:
    global _repo
    if _repo is None:
        _repo = AgentRuntimeRepository()
    return _repo


def queue_for_controller(controller: str) -> str:
    return {
        "discovery": "discovery",
        "enrichment": "enrichment",
        "verification": "verification",
        "commit": "commit",
        "recovery": "recovery",
    }.get(controller, "default")
