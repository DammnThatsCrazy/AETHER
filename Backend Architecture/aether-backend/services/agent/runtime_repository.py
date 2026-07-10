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
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from shared.common.common import BadRequestError, ConflictError
from shared.store import DurableStore, get_store


# A controller heartbeat older than this is treated as stale (worker likely dead)
# so a one-off "healthy" beat can't mark a controller healthy forever.
HEARTBEAT_STALE_SECONDS = int(os.getenv("AGENT_HEARTBEAT_STALE_SECONDS", "90"))
# A worker run stuck in queued/running without a heartbeat for this long is
# considered stuck; sweep_stale_runs() marks it stale for operator recovery.
RUN_STALE_SECONDS = int(os.getenv("AGENT_RUN_STALE_SECONDS", "900"))
# Objective statuses from which a dispatch / resume must not silently revive work.
TERMINAL_OBJECTIVE_STATUSES = {"completed", "failed", "cancelled"}


OBJECTIVE_STATUSES = {"queued", "active", "paused", "blocked", "awaiting_review", "completed", "failed", "cancelled"}
REVIEW_STATUSES = {"pending", "approved", "rejected", "committed", "quarantined", "rolled_back"}
MUTATION_STATUSES = {"staged", "approved", "rejected", "committed", "quarantined", "rolled_back", "failed_commit"}
# Worker run lifecycle: queued → running → completed | failed | retry.
# dispatch_failed marks runs whose queue publish failed (hosted fail-closed);
# stale marks runs swept after exceeding RUN_STALE_SECONDS without progress.
RUN_STATUSES = {"queued", "running", "completed", "failed", "retry", "stale", "dispatch_failed"}
# Runs in these states still occupy a worker slot / block idempotent re-dispatch.
ACTIVE_RUN_STATUSES = {"queued", "running"}
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


def _age_seconds(iso_ts: str | None) -> float:
    """Seconds since an ISO-8601 timestamp; +inf when unparseable/missing."""
    if not iso_ts:
        return float("inf")
    try:
        ts = datetime.fromisoformat(iso_ts)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds()
    except (ValueError, TypeError):
        return float("inf")


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


_ERROR_MAX_LENGTH = 2000


def sanitize_error(error: Any) -> str:
    """Bound and sanitize a worker-supplied error before persisting it.

    Workers report free-form strings; cap the length so a runaway traceback
    can't bloat the store, and run dict/list errors through sanitize_payload
    so secret-shaped keys are redacted.
    """
    if error is None:
        return ""
    if isinstance(error, (dict, list)):
        error = json.dumps(sanitize_payload(error), default=str)
    text = str(error)
    return text[:_ERROR_MAX_LENGTH]


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
        if objective_id:
            # Maintain a per-objective list so an objective's timeline can be
            # read in full without scanning the namespace or being capped by
            # unrelated tenant events.
            await self.events.append_list(f"obj:{objective_id}", event)
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

    async def count_objectives(self, tenant_id: str, status: str | None = None) -> int:
        # Uncapped count for health snapshots — list_objectives slices to a
        # limit, which would under-report backlog in large tenants.
        if status:
            return await self.objectives.count(tenant_id=tenant_id, status=status)
        return await self.objectives.count(tenant_id=tenant_id)

    async def count_review_batches(self, tenant_id: str, status: str | None = None) -> int:
        if status:
            return await self.review_batches.count(tenant_id=tenant_id, status=status)
        return await self.review_batches.count(tenant_id=tenant_id)

    async def transition_objective(self, tenant_id: str, objective_id: str, action: str, actor_id: str, request_id: str, reason: str = "") -> dict[str, Any] | None:
        objective = await self.get_objective(tenant_id, objective_id)
        if objective is None:
            return None
        current = objective.get("status")
        # Guard illegal lifecycle transitions so a stray request can't revive a
        # terminal objective (e.g. resuming a cancelled one) or pause finished work.
        allowed_from = {
            "pause": {"queued", "active", "awaiting_review", "blocked"},
            "resume": {"paused"},
            "cancel": {"queued", "active", "paused", "awaiting_review", "blocked"},
        }
        if current not in allowed_from[action]:
            raise ConflictError(f"Cannot {action} objective in status '{current}'")
        status_map = {"pause": "paused", "resume": "active", "cancel": "cancelled"}
        # Explicit event names — f"{action}d" would emit "objective.canceld" for cancel.
        event_map = {"pause": "objective.paused", "resume": "objective.resumed", "cancel": "objective.cancelled"}
        objective["status"] = status_map[action]
        objective["updated_at"] = utc_now()
        if action == "pause":
            objective["paused_at"] = objective["updated_at"]
        if action == "cancel":
            objective["cancelled_at"] = objective["updated_at"]
        await self.objectives.set(objective_id, objective)
        payload = {"status": objective["status"]}
        if reason:
            # Preserve the operator's justification on the audit/timeline event.
            payload["reason"] = sanitize_payload({"reason": reason}).get("reason", "")
        await self.append_event(tenant_id, event_map[action], "operator", payload, objective_id, actor_id, request_id)
        return objective

    async def record_dispatch(self, tenant_id: str, objective_id: str, controller: str, actor_id: str, request_id: str) -> dict[str, Any] | None:
        objective = await self.get_objective(tenant_id, objective_id)
        if objective is None:
            return None
        current = objective.get("status")
        # Only dispatch objectives that are actually runnable. This blocks paused,
        # cancelled/terminal, AND awaiting_review/blocked — so dispatch can't
        # bypass the human review gate or undo a rejection.
        if current not in {"queued", "active"}:
            raise ConflictError(f"Cannot dispatch objective in status '{current}'")
        idem = stable_idempotency_key(tenant_id, {"objective_id": objective_id, "controller": controller})
        # Idempotent retries / double-clicks reuse the in-flight run instead of
        # queuing duplicate work for the same objective+controller.
        existing = [
            r for r in await self.worker_runs.find(tenant_id=tenant_id, objective_id=objective_id)
            if r.get("idempotency_key") == idem and r.get("status") in {"queued", "running"}
        ]
        if existing:
            return {"run": existing[0], "created": False}
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
            "idempotency_key": idem,
            "created_at": now,
            "updated_at": now,
            "heartbeat_at": now,
            "error": None,
        }
        await self.worker_runs.set(run["run_id"], run)
        await self.append_event(tenant_id, "step.dispatched", controller, run, objective_id, actor_id, request_id)
        return {"run": run, "created": True}

    # ── Worker run lifecycle (execution bridge) ──────────────────────────

    async def get_run(self, tenant_id: str, run_id: str) -> dict[str, Any] | None:
        run = await self.worker_runs.get(run_id)
        if not run or run.get("tenant_id") != tenant_id:
            return None
        return run

    async def list_runs(
        self,
        tenant_id: str,
        status: str | None = None,
        objective_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        filters: dict[str, Any] = {"tenant_id": tenant_id}
        if status:
            filters["status"] = status
        if objective_id:
            filters["objective_id"] = objective_id
        rows = await self.worker_runs.find(**filters)
        rows.sort(key=lambda row: row.get("created_at", ""), reverse=True)
        return rows[:limit]

    async def count_runs(self, tenant_id: str, status: str | None = None) -> int:
        if status:
            return await self.worker_runs.count(tenant_id=tenant_id, status=status)
        return await self.worker_runs.count(tenant_id=tenant_id)

    async def start_run(
        self, tenant_id: str, run_id: str, worker_id: str = "", request_id: str = ""
    ) -> dict[str, Any] | None:
        run = await self.get_run(tenant_id, run_id)
        if run is None:
            return None
        current = run.get("status")
        if current == "running":
            # Idempotent re-start (worker retry after acks_late redelivery):
            # refresh the heartbeat instead of failing the callback.
            run["heartbeat_at"] = utc_now()
            run["updated_at"] = run["heartbeat_at"]
            await self.worker_runs.set(run_id, run)
            return run
        if current not in {"queued", "retry"}:
            raise ConflictError(f"Cannot start run in status '{current}'")
        now = utc_now()
        run["status"] = "running"
        run["started_at"] = now
        run["heartbeat_at"] = now
        run["updated_at"] = now
        if worker_id:
            run["worker_id"] = worker_id
        await self.worker_runs.set(run_id, run)
        await self.append_event(
            tenant_id, "run.started", run.get("controller", "worker"),
            {"run_id": run_id, "status": "running", "worker_id": worker_id},
            run.get("objective_id", ""), worker_id or "worker", request_id,
        )
        return run

    async def complete_run(
        self,
        tenant_id: str,
        run_id: str,
        output: dict[str, Any] | None = None,
        actor_id: str = "worker",
        request_id: str = "",
    ) -> dict[str, Any] | None:
        run = await self.get_run(tenant_id, run_id)
        if run is None:
            return None
        current = run.get("status")
        if current == "completed":
            return run  # idempotent duplicate completion callback
        if current not in {"queued", "running", "retry"}:
            raise ConflictError(f"Cannot complete run in status '{current}'")
        now = utc_now()
        run["status"] = "completed"
        run["completed_at"] = now
        run["heartbeat_at"] = now
        run["updated_at"] = now
        run["output"] = sanitize_payload(output or {})
        run["error"] = None
        await self.worker_runs.set(run_id, run)
        await self.append_event(
            tenant_id, "run.completed", run.get("controller", "worker"),
            {"run_id": run_id, "status": "completed", "output": run["output"]},
            run.get("objective_id", ""), actor_id, request_id,
        )
        return run

    async def fail_run(
        self,
        tenant_id: str,
        run_id: str,
        error: Any = "",
        retry: bool = False,
        actor_id: str = "worker",
        request_id: str = "",
    ) -> dict[str, Any] | None:
        run = await self.get_run(tenant_id, run_id)
        if run is None:
            return None
        current = run.get("status")
        if current in {"completed", "failed"} and not retry:
            return run  # idempotent duplicate failure callback
        if current not in {"queued", "running", "retry", "failed"}:
            raise ConflictError(f"Cannot fail run in status '{current}'")
        now = utc_now()
        run["status"] = "retry" if retry else "failed"
        run["error"] = sanitize_error(error)
        run["heartbeat_at"] = now
        run["updated_at"] = now
        if retry:
            run["attempt"] = int(run.get("attempt", 1) or 1) + 1
        else:
            run["failed_at"] = now
        await self.worker_runs.set(run_id, run)
        await self.append_event(
            tenant_id, "run.retry" if retry else "run.failed", run.get("controller", "worker"),
            {"run_id": run_id, "status": run["status"], "error": run["error"], "attempt": run["attempt"]},
            run.get("objective_id", ""), actor_id, request_id,
        )
        return run

    async def mark_run_dispatch_failed(
        self, tenant_id: str, run_id: str, reason: str, actor_id: str = "system", request_id: str = ""
    ) -> dict[str, Any] | None:
        """Record that the queue publish for a freshly created run failed."""
        run = await self.get_run(tenant_id, run_id)
        if run is None:
            return None
        now = utc_now()
        run["status"] = "dispatch_failed"
        run["error"] = sanitize_error(reason)
        run["updated_at"] = now
        await self.worker_runs.set(run_id, run)
        await self.append_event(
            tenant_id, "run.dispatch_failed", run.get("controller", "worker"),
            {"run_id": run_id, "status": "dispatch_failed", "error": run["error"]},
            run.get("objective_id", ""), actor_id, request_id,
        )
        return run

    async def list_stuck_runs(
        self, tenant_id: str, stale_seconds: int | None = None
    ) -> list[dict[str, Any]]:
        """Runs still queued/running whose last progress signal is too old."""
        threshold = RUN_STALE_SECONDS if stale_seconds is None else stale_seconds
        stuck: list[dict[str, Any]] = []
        for status in sorted(ACTIVE_RUN_STATUSES):
            for run in await self.worker_runs.find(tenant_id=tenant_id, status=status):
                reference = run.get("heartbeat_at") or run.get("updated_at") or run.get("created_at")
                if _age_seconds(reference) > threshold:
                    stuck.append(run)
        stuck.sort(key=lambda row: row.get("created_at", ""))
        return stuck

    async def sweep_stale_runs(
        self, tenant_id: str, actor_id: str = "system", request_id: str = ""
    ) -> list[dict[str, Any]]:
        """Mark stuck runs stale so operators (or recovery) can replay them."""
        swept: list[dict[str, Any]] = []
        for run in await self.list_stuck_runs(tenant_id):
            now = utc_now()
            run["status"] = "stale"
            run["stale_at"] = now
            run["updated_at"] = now
            await self.worker_runs.set(run["run_id"], run)
            await self.append_event(
                tenant_id, "run.stale", run.get("controller", "worker"),
                {"run_id": run["run_id"], "status": "stale"},
                run.get("objective_id", ""), actor_id, request_id,
            )
            swept.append(run)
        return swept

    async def replay_run(
        self, tenant_id: str, run_id: str, actor_id: str = "operator", request_id: str = ""
    ) -> dict[str, Any] | None:
        """Create a fresh queued run carrying the same envelope as run_id.

        The new run reuses objective/controller/queue but gets a fresh
        idempotency-key suffix so record_dispatch-style dedupe does not
        collapse it back onto the dead run.
        """
        source = await self.get_run(tenant_id, run_id)
        if source is None:
            return None
        if source.get("status") in ACTIVE_RUN_STATUSES:
            raise ConflictError("Cannot replay a run that is still queued/running")
        objective = await self.get_objective(tenant_id, source.get("objective_id", ""))
        if objective is None or objective.get("status") not in {"queued", "active"}:
            raise ConflictError("Cannot replay a run whose objective is not runnable")
        now = utc_now()
        replay = {
            "run_id": new_id("run"),
            "tenant_id": tenant_id,
            "objective_id": source.get("objective_id"),
            "controller": source.get("controller"),
            "queue": source.get("queue", "default"),
            "status": "queued",
            "attempt": 1,
            "idempotency_key": f"{source.get('idempotency_key', '')}:replay:{uuid.uuid4().hex[:8]}",
            "replay_of": run_id,
            "created_at": now,
            "updated_at": now,
            "heartbeat_at": now,
            "error": None,
        }
        await self.worker_runs.set(replay["run_id"], replay)
        await self.append_event(
            tenant_id, "run.replayed", replay.get("controller", "worker"),
            {"run_id": replay["run_id"], "replay_of": run_id},
            replay.get("objective_id", ""), actor_id, request_id,
        )
        return replay

    async def prune_runs(self, tenant_id: str, keep_days: int = 30) -> int:
        """Retention: delete terminal runs older than keep_days.

        Timeline/audit events are never touched — only the run rows themselves.
        Active (queued/running) runs are always kept.
        """
        cutoff_seconds = max(0, keep_days) * 86400
        pruned = 0
        for run in await self.worker_runs.find(tenant_id=tenant_id):
            if run.get("status") in ACTIVE_RUN_STATUSES:
                continue
            if _age_seconds(run.get("created_at")) > cutoff_seconds:
                await self.worker_runs.delete(run["run_id"])
                pruned += 1
        return pruned

    async def run_counts(self, tenant_id: str) -> dict[str, int]:
        """Point-in-time run counts for health snapshots (uncapped)."""
        counts = {
            status: await self.worker_runs.count(tenant_id=tenant_id, status=status)
            for status in sorted(RUN_STATUSES)
        }
        counts["stuck"] = len(await self.list_stuck_runs(tenant_id))
        return counts

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
        now = utc_now()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in heartbeats:
            grouped.setdefault(row.get("controller"), []).append(row)
        statuses: list[dict[str, Any]] = []
        for controller in CONTROLLERS:
            rows = grouped.get(controller, [])
            if not rows:
                statuses.append({
                    "tenant_id": tenant_id, "controller": controller, "worker_id": None,
                    "status": "unknown", "queue_depth": 0, "worker_count": 0,
                    "workers": [], "metadata": {}, "updated_at": now,
                })
                continue
            workers: list[dict[str, Any]] = []
            total_depth = 0
            live_states: list[str] = []
            for r in rows:
                # Horizontally-scaled workers each heartbeat under their own
                # worker_id; sum their depths and expire stale rows instead of
                # collapsing to one arbitrary record.
                stale = _age_seconds(r.get("updated_at")) > HEARTBEAT_STALE_SECONDS
                wstatus = "stale" if stale else r.get("status", "unknown")
                depth = int(r.get("queue_depth", 0) or 0)
                # Keep the stale worker row for visibility, but exclude its last
                # reported depth from the live queue total — otherwise a dead
                # worker shows phantom backlog forever.
                if not stale:
                    total_depth += depth
                live_states.append(wstatus)
                workers.append({
                    "worker_id": r.get("worker_id"), "status": wstatus,
                    "queue_depth": depth, "updated_at": r.get("updated_at"), "stale": stale,
                })
            if any(s == "healthy" for s in live_states):
                agg = "healthy"
            elif any(s not in ("stale", "unknown") for s in live_states):
                agg = "degraded"
            else:
                agg = "stale"
            latest = max(rows, key=lambda r: r.get("updated_at", ""))
            statuses.append({
                "tenant_id": tenant_id, "controller": controller,
                "worker_id": latest.get("worker_id"), "status": agg,
                "queue_depth": total_depth, "worker_count": len(workers),
                "workers": workers, "metadata": latest.get("metadata", {}),
                "updated_at": latest.get("updated_at", now),
            })
        return statuses

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
        # Read from a list, never find(): find() scans the agent_events namespace,
        # which also matches the list keys and trips Redis WRONGTYPE on GET.
        if objective_id:
            # The objective's own list isn't diluted by other objectives' events,
            # so an older objective's timeline can't be pushed out of the window.
            rows = await self.events.get_list(f"obj:{objective_id}", limit=max(limit, 1000))
            rows = [row for row in rows if row.get("tenant_id") == tenant_id]
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
