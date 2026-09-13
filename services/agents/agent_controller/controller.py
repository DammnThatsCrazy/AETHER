"""
Aether Agent Layer — Agent Controller
Central orchestrator: manages the task queue, dispatches work to the correct
worker, and integrates feedback to improve prioritization over time.

Supports two queue backends:
  - In-memory heapq (default, for development / testing)
  - Celery + Redis  (production, auto-detected)
"""

from __future__ import annotations

import heapq
import logging
from collections import deque
from queue.celery_app import is_celery_available
from queue.tasks import (
    register_worker_for_tasks,
    submit_celery_task,
)
from typing import Optional

from config.settings import (
    AgentLayerSettings,
    TaskPriority,
    TaskStatus,
    WorkerType,
)
from feedback.learning import FeedbackLoop
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
      - Delegate to Celery when available, else use in-memory queue
    """

    def __init__(
        self,
        settings: Optional[AgentLayerSettings] = None,
        use_celery: Optional[bool] = None,
    ):
        self.settings = settings or AgentLayerSettings()
        self.guardrails = Guardrails(self.settings)

        # Feedback learning loop
        self.feedback = FeedbackLoop(
            base_thresholds=self.settings.confidence,
            alpha=0.15,
        )

        # Queue backend selection
        if use_celery is None:
            self._use_celery = is_celery_available()
        else:
            self._use_celery = use_celery and is_celery_available()

        if self._use_celery:
            logger.info("Controller using Celery queue backend")
        else:
            logger.info("Controller using in-memory queue backend")

        # In-memory fallback: (priority_int, created_timestamp, task)
        self._queue: list[tuple[int, float, AgentTask]] = []

        # Registry: WorkerType → BaseWorker instance
        self._workers: dict[WorkerType, BaseWorker] = {}

        # Completed/failed task log (bounded ring buffer to prevent memory exhaustion)
        self._history: deque[AgentTask] = deque(maxlen=10_000)

        # Celery async result tracking
        self._celery_results: dict[str, str] = {}  # task_id → celery_id

    # ------------------------------------------------------------------
    # Worker registration
    # ------------------------------------------------------------------

    def register_worker(self, worker: BaseWorker) -> None:
        """Register a worker instance for a given WorkerType."""
        self._workers[worker.worker_type] = worker
        # Also register with the Celery task module
        register_worker_for_tasks(worker)
        logger.info(f"Registered worker: {worker.worker_type.value}")

    def register_workers(self, workers: list[BaseWorker]) -> None:
        """Convenience: register a list of workers at once."""
        for w in workers:
            self.register_worker(w)

    # ------------------------------------------------------------------
    # Task submission
    # ------------------------------------------------------------------

    def submit_task(self, task: AgentTask) -> str:
        """
        Add a task to the queue. Applies feedback-based priority
        adjustment, then routes to Celery or in-memory queue.
        Returns task_id.
        """
        if self.settings.kill_switch_enabled:
            raise RuntimeError("Kill switch engaged — cannot accept new tasks.")

        # Apply feedback-based priority boost
        adjusted = self.feedback.adjust_task_priority(
            task.worker_type, task.priority,
        )
        if adjusted != task.priority:
            logger.info(
                f"Priority adjusted for {task.task_id}: "
                f"{task.priority.name} → {adjusted.name} (feedback boost)"
            )
            task.priority = adjusted

        task.status = TaskStatus.QUEUED

        if self._use_celery:
            celery_id = submit_celery_task(task)
            if celery_id:
                self._celery_results[task.task_id] = celery_id
                logger.info(
                    f"Task {task.task_id} → Celery "
                    f"(type={task.worker_type.value}, priority={task.priority.name})"
                )
                return task.task_id

        # Fallback to in-memory queue
        heapq.heappush(
            self._queue,
            (task.priority.value, task.created_at.timestamp(), task),
        )
        logger.info(
            f"Task {task.task_id} queued in-memory "
            f"(type={task.worker_type.value}, priority={task.priority.name})"
        )
        return task.task_id

    # ------------------------------------------------------------------
    # Dispatch — pull highest-priority task and run it (in-memory mode)
    # ------------------------------------------------------------------

    def dispatch_next(self) -> Optional[TaskResult]:
        """Pop the highest-priority task and execute it (in-memory mode)."""
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
        """Process up to max_tasks from the in-memory queue."""
        results: list[TaskResult] = []
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
    # Feedback integration
    # ------------------------------------------------------------------

    def record_human_feedback(
        self,
        task_id: str,
        approved: bool,
        notes: str = "",
    ) -> None:
        """
        Record whether a human reviewer approved or rejected a result.
        Feeds into the learning loop to adjust thresholds and priorities.
        """
        # Look up the task in history to get worker_type + confidence
        task = next((t for t in self._history if t.task_id == task_id), None)
        if task is None:
            logger.warning(f"Feedback for unknown task: {task_id}")
            return

        confidence = task.result.confidence if task.result else 0.0

        self.feedback.record(
            task_id=task_id,
            worker_type=task.worker_type,
            confidence=confidence,
            approved=approved,
            notes=notes,
        )

        # Update task status
        if approved:
            task.status = TaskStatus.COMPLETED
        else:
            task.status = TaskStatus.DISCARDED

        logger.info(
            f"Human feedback for task {task_id}: "
            f"{'APPROVED' if approved else 'REJECTED'} — {notes}"
        )

    def feedback_stats(self) -> dict:
        """Get feedback loop statistics for monitoring."""
        return self.feedback.stats()

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def queue_depth(self) -> int:
        return len(self._queue)

    @property
    def history(self) -> list[AgentTask]:
        return list(self._history)

    @property
    def registered_workers(self) -> list[str]:
        return [wt.value for wt in self._workers]

    @property
    def using_celery(self) -> bool:
        return self._use_celery
