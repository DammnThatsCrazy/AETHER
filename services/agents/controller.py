"""
Aether Agent Layer — Agent Controller
Central orchestrator: manages the task queue, dispatches work to the correct
worker, and integrates feedback to improve prioritization over time.

In production this wraps Celery. This scaffold uses a simple in-memory
priority queue so you can run and test locally first.
"""

from __future__ import annotations

import heapq
import logging
from typing import Optional

from config.settings import (
    AgentLayerSettings,
    TaskPriority,
    TaskStatus,
    WorkerType,
)
from guardrails.guardrails import Guardrails
from models.core import AgentTask, TaskResult
from workers.base import BaseWorker

logger = logging.getLogger("aether.controller")


class AgentController:
    """
    Responsibilities:
      - Accept and prioritize tasks
      - Dispatch tasks to the correct registered worker
      - Track task lifecycle (pending → running → completed/failed/review)
      - Expose hooks for scheduled (cron) and event-triggered tasks
      - Integrate human feedback to adjust future priorities
    """

    def __init__(self, settings: Optional[AgentLayerSettings] = None):
        self.settings = settings or AgentLayerSettings()
        self.guardrails = Guardrails(self.settings)

        # Priority queue: (priority_int, created_timestamp, task)
        self._queue: list[tuple[int, float, AgentTask]] = []

        # Registry: WorkerType → BaseWorker instance
        self._workers: dict[WorkerType, BaseWorker] = {}

        # Completed/failed task log
        self._history: list[AgentTask] = []

    # ------------------------------------------------------------------
    # Worker registration
    # ------------------------------------------------------------------

    def register_worker(self, worker: BaseWorker):
        """Register a worker instance for a given WorkerType."""
        self._workers[worker.worker_type] = worker
        logger.info(f"Registered worker: {worker.worker_type.value}")

    # ------------------------------------------------------------------
    # Task submission
    # ------------------------------------------------------------------

    def submit_task(self, task: AgentTask) -> str:
        """Add a task to the priority queue. Returns task_id."""
        if self.settings.kill_switch_enabled:
            raise RuntimeError("Kill switch engaged — cannot accept new tasks.")

        task.status = TaskStatus.QUEUED
        heapq.heappush(
            self._queue,
            (task.priority.value, task.created_at.timestamp(), task),
        )
        logger.info(
            f"Task {task.task_id} queued "
            f"(type={task.worker_type.value}, priority={task.priority.name})"
        )
        return task.task_id

    # ------------------------------------------------------------------
    # Dispatch — pull highest-priority task and run it
    # ------------------------------------------------------------------

    def dispatch_next(self) -> Optional[TaskResult]:
        """Pop the highest-priority task and execute it."""
        if not self._queue:
            logger.debug("Queue empty — nothing to dispatch")
            return None

        _, _, task = heapq.heappop(self._queue)
        worker = self._workers.get(task.worker_type)

        if worker is None:
            msg = f"No registered worker for type {task.worker_type.value}"
            logger.error(msg)
            task.mark_failed(msg)
            self._history.append(task)
            return task.result

        logger.info(f"Dispatching task {task.task_id} → {task.worker_type.value}")
        result = worker.run(task)
        self._history.append(task)
        return result

    def drain_queue(self, max_tasks: int = 100) -> list[TaskResult]:
        """Process up to max_tasks from the queue."""
        results = []
        for _ in range(max_tasks):
            r = self.dispatch_next()
            if r is None:
                break
            results.append(r)
        return results

    # ------------------------------------------------------------------
    # Scheduling hooks (integrate with Celery Beat / APScheduler)
    # ------------------------------------------------------------------

    def create_scheduled_task(
        self,
        worker_type: WorkerType,
        payload: dict,
        priority: TaskPriority = TaskPriority.MEDIUM,
    ) -> str:
        """Convenience method for cron-triggered tasks."""
        task = AgentTask(
            worker_type=worker_type,
            priority=priority,
            payload=payload,
        )
        return self.submit_task(task)

    def create_event_triggered_task(
        self,
        worker_type: WorkerType,
        payload: dict,
        priority: TaskPriority = TaskPriority.HIGH,
    ) -> str:
        """Convenience method for event-driven tasks (new entity, data alert)."""
        task = AgentTask(
            worker_type=worker_type,
            priority=priority,
            payload={**payload, "_trigger": "event"},
        )
        return self.submit_task(task)

    # ------------------------------------------------------------------
    # Feedback integration (stub)
    # ------------------------------------------------------------------

    def record_human_feedback(
        self,
        task_id: str,
        approved: bool,
        notes: str = "",
    ):
        """
        Record whether a human reviewer approved or rejected a
        result that was sent to human_review.

        In a real system this feeds into a lightweight model that
        adjusts priority weights and confidence thresholds.
        """
        logger.info(
            f"Human feedback for task {task_id}: "
            f"{'APPROVED' if approved else 'REJECTED'} — {notes}"
        )
        # TODO: feed into priority/confidence learning loop

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def queue_depth(self) -> int:
        return len(self._queue)

    @property
    def history(self) -> list[AgentTask]:
        return list(self._history)
