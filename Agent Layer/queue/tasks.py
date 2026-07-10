"""
Aether Agent Layer — Celery Task Definitions
Thin wrappers that deserialize task payloads and delegate to the
BaseWorker.run() lifecycle (same guardrails apply as in-memory mode).

These tasks are registered with the Celery app but can also be called
directly (bypassing Celery) via execute_task_sync() for testing.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from config.settings import TaskPriority, WorkerType
from models.core import AgentTask, TaskResult

logger = logging.getLogger("aether.queue.tasks")

# ---------------------------------------------------------------------------
# Priority mapping (Celery uses 0=highest, 9=lowest)
# ---------------------------------------------------------------------------

_PRIORITY_TO_CELERY: dict[TaskPriority, int] = {
    TaskPriority.CRITICAL: 0,
    TaskPriority.HIGH: 2,
    TaskPriority.MEDIUM: 5,
    TaskPriority.LOW: 7,
    TaskPriority.BACKGROUND: 9,
}


def _task_to_dict(task: AgentTask) -> dict[str, Any]:
    """Serialize an AgentTask to a JSON-safe dict for Celery."""
    return {
        "task_id": task.task_id,
        "worker_type": task.worker_type.value,
        "priority": task.priority.value,
        "payload": task.payload,
        "created_at": task.created_at.isoformat(),
        "retries": task.retries,
    }


def _dict_to_task(data: dict[str, Any]) -> AgentTask:
    """Deserialize a dict back into an AgentTask."""
    return AgentTask(
        worker_type=WorkerType(data["worker_type"]),
        priority=TaskPriority(data["priority"]),
        payload=data["payload"],
        task_id=data["task_id"],
        retries=data.get("retries", 0),
    )


def _result_to_dict(result: TaskResult) -> dict[str, Any]:
    """Serialize a TaskResult to a JSON-safe dict."""
    return {
        "task_id": result.task_id,
        "worker_type": result.worker_type.value,
        "success": result.success,
        "data": result.data,
        "confidence": result.confidence,
        "error": result.error,
        "source_attribution": result.source_attribution,
        "created_at": result.created_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Celery tasks (registered only if Celery is available)
# ---------------------------------------------------------------------------

from queue.celery_app import get_celery_app, is_celery_available

_app = get_celery_app()

if _app is not None:

    @_app.task(
        name="queue.tasks.execute_task",
        bind=True,
        max_retries=3,
        default_retry_delay=30,
        acks_late=True,
    )
    def execute_task(self, task_data: dict[str, Any]) -> dict[str, Any]:
        """
        General-purpose Celery task. Resolves the worker from the
        global registry and runs it through the guardrails lifecycle.
        """
        task = _dict_to_task(task_data)
        result = _run_with_worker(task)
        return _result_to_dict(result)

    @_app.task(
        name="queue.tasks.execute_discovery_task",
        bind=True,
        max_retries=3,
        default_retry_delay=30,
        queue="discovery",
    )
    def execute_discovery_task(self, task_data: dict[str, Any]) -> dict[str, Any]:
        """Celery task routed to the 'discovery' queue."""
        task = _dict_to_task(task_data)
        result = _run_with_worker(task)
        return _result_to_dict(result)

    @_app.task(
        name="queue.tasks.execute_enrichment_task",
        bind=True,
        max_retries=3,
        default_retry_delay=30,
        queue="enrichment",
    )
    def execute_enrichment_task(self, task_data: dict[str, Any]) -> dict[str, Any]:
        """Celery task routed to the 'enrichment' queue."""
        task = _dict_to_task(task_data)
        result = _run_with_worker(task)
        return _result_to_dict(result)

    @_app.task(name="queue.tasks.execute_verification_task", bind=True, max_retries=3, default_retry_delay=30, queue="verification")
    def execute_verification_task(self, task_data: dict[str, Any]) -> dict[str, Any]:
        """Celery task routed to the 'verification' queue."""
        task = _dict_to_task(task_data)
        result = _run_with_worker(task)
        return _result_to_dict(result)

    @_app.task(name="queue.tasks.execute_commit_task", bind=True, max_retries=3, default_retry_delay=30, queue="commit")
    def execute_commit_task(self, task_data: dict[str, Any]) -> dict[str, Any]:
        """Celery task routed to the human-approved commit queue."""
        task = _dict_to_task(task_data)
        result = _run_with_worker(task)
        return _result_to_dict(result)

    @_app.task(name="queue.tasks.execute_recovery_task", bind=True, max_retries=5, default_retry_delay=60, queue="recovery")
    def execute_recovery_task(self, task_data: dict[str, Any]) -> dict[str, Any]:
        """Celery task routed to the recovery queue."""
        task = _dict_to_task(task_data)
        result = _run_with_worker(task)
        return _result_to_dict(result)

    @_app.task(
        name="aether.agent.execute_objective_step",
        bind=True,
        max_retries=3,
        default_retry_delay=30,
        acks_late=True,
    )
    def execute_objective_step(self, envelope: dict[str, Any]) -> dict[str, Any]:
        """Backend worker-bridge task (dispatched BY NAME from the backend).

        The backend's services/agent/worker_bridge.py send_task()s this name
        with the canonical execution envelope and routes it to the queue named
        in the envelope. Retries report ``retry`` back to the backend so the
        durable run record tracks attempts; the final failure reports
        ``failed``.
        """
        will_retry = self.request.retries < (self.max_retries or 0)
        try:
            return execute_objective_step_impl(envelope, will_retry=will_retry)
        except Exception as exc:
            if will_retry:
                raise self.retry(exc=exc)
            raise


# ---------------------------------------------------------------------------
# Backend worker-bridge step execution
# ---------------------------------------------------------------------------


def execute_objective_step_impl(
    envelope: dict[str, Any], will_retry: bool = False
) -> dict[str, Any]:
    """Execute one backend dispatch envelope and report status callbacks.

    Envelope contract (backend services/agent/worker_bridge.py): tenant_id,
    objective_id, run_id, controller, queue, idempotency_key, attempt,
    payload, created_at, request_id (+ optional plan_id/step_id).

    Lifecycle: mark the run ``running`` via the backend callback client,
    execute the step, then report ``completed`` — or ``retry``/``failed`` on
    exception (``retry`` while Celery retries remain, ``failed`` on the last
    attempt). Callable directly (without Celery) for tests and in-memory mode.
    """
    from agent_controller.runtime.backend_client import get_backend_client

    run_id = str(envelope.get("run_id", ""))
    tenant_id = str(envelope.get("tenant_id", ""))
    if not run_id or not tenant_id:
        raise ValueError("Envelope requires run_id and tenant_id")

    client = get_backend_client()
    worker_id = os.getenv("AETHER_WORKER_ID", "agent-layer-worker")
    client.post_run_status(run_id, "running", tenant_id=tenant_id, worker_id=worker_id)
    try:
        output = _execute_envelope_step(envelope)
    except Exception as exc:
        client.post_run_status(
            run_id,
            "retry" if will_retry else "failed",
            error=f"{type(exc).__name__}: {exc}"[:2000],
            tenant_id=tenant_id,
            worker_id=worker_id,
        )
        raise
    client.post_run_status(
        run_id, "completed", output=output, tenant_id=tenant_id, worker_id=worker_id
    )
    return {"run_id": run_id, "success": True, "output": output}


def _execute_envelope_step(envelope: dict[str, Any]) -> dict[str, Any]:
    """Execute the controller step described by the envelope.

    DOCUMENTED NO-OP ECHO STEP: the durable objective/plan state for hosted
    dispatch lives in the backend's AgentRuntimeRepository, not in this
    process — the in-memory ObjectiveRuntime here has no record of the
    objective referenced by the envelope, and the controller hierarchy
    (controller.py) is constructed per-process with its own registries, so
    there is no cleanly callable "execute one objective step" seam to invoke
    from a bare envelope today. The release-critical deliverable is the
    bridge contract itself (dispatch → running → completed/failed with
    durable state), so this step echoes the envelope payload as its output.
    When a controller-side step executor becomes callable from an envelope,
    replace only this function — the task lifecycle around it stays intact.
    """
    return {
        "step": "echo",
        "controller": envelope.get("controller", ""),
        "queue": envelope.get("queue", ""),
        "objective_id": envelope.get("objective_id", ""),
        "attempt": envelope.get("attempt", 1),
        "payload": envelope.get("payload") or {},
    }


# ---------------------------------------------------------------------------
# Worker resolution (shared between Celery and in-memory modes)
# ---------------------------------------------------------------------------

# Global worker registry — populated by the controller on startup
_worker_registry: dict[WorkerType, Any] = {}


def register_worker_for_tasks(worker: Any) -> None:
    """Called by the controller to make workers available to Celery tasks."""
    _worker_registry[worker.worker_type] = worker


def _run_with_worker(task: AgentTask) -> TaskResult:
    """Resolve worker from registry and execute via BaseWorker.run()."""
    worker = _worker_registry.get(task.worker_type)
    if worker is None:
        logger.error(f"No worker registered for {task.worker_type.value}")
        task.mark_failed(f"No worker for {task.worker_type.value}")
        return task.result  # type: ignore
    return worker.run(task)


# ---------------------------------------------------------------------------
# Discovery vs. Enrichment worker types (for queue routing)
# ---------------------------------------------------------------------------

_DISCOVERY_TYPES = {
    WorkerType.WEB_CRAWLER,
    WorkerType.API_SCANNER,
    WorkerType.SOCIAL_LISTENER,
    WorkerType.CHAIN_MONITOR,
    WorkerType.COMPETITOR_TRACKER,
}

_ENRICHMENT_TYPES = {
    WorkerType.ENTITY_RESOLVER,
    WorkerType.PROFILE_ENRICHER,
    WorkerType.TEMPORAL_FILLER,
    WorkerType.SEMANTIC_TAGGER,
    WorkerType.QUALITY_SCORER,
}


def submit_celery_task(task: AgentTask) -> Optional[str]:
    """
    Submit a task to the appropriate Celery queue.
    Returns the Celery AsyncResult ID, or None if Celery isn't available.
    """
    if not is_celery_available() or _app is None:
        return None

    task_data = _task_to_dict(task)
    celery_priority = _PRIORITY_TO_CELERY.get(task.priority, 5)

    headers = {"idempotency_key": task.task_id, "worker_type": task.worker_type.value}
    if task.worker_type in _DISCOVERY_TYPES:
        async_result = execute_discovery_task.apply_async(args=[task_data], priority=celery_priority, headers=headers)
    elif task.worker_type in _ENRICHMENT_TYPES:
        async_result = execute_enrichment_task.apply_async(args=[task_data], priority=celery_priority, headers=headers)
    else:
        async_result = execute_task.apply_async(args=[task_data], priority=celery_priority, headers=headers)

    logger.info(
        f"Task {task.task_id} submitted to Celery "
        f"(celery_id={async_result.id}, queue="
        f"{'discovery' if task.worker_type in _DISCOVERY_TYPES else 'enrichment'})"
    )
    return async_result.id


def execute_task_sync(task: AgentTask) -> TaskResult:
    """
    Run a task synchronously (bypass Celery).
    Used for testing and in-memory fallback mode.
    """
    return _run_with_worker(task)
