"""
Aether Agent Layer — Base Worker
Every discovery and enrichment worker inherits from this class.
It enforces guardrails, audit logging, and a consistent execute lifecycle.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from config.settings import WorkerType
from guardrails.guardrails import Guardrails
from models.core import AgentTask, AuditRecord, TaskResult

logger = logging.getLogger("aether.worker")


class BaseWorker(ABC):
    """
    Abstract base for all agent workers.

    Subclasses must implement:
        - worker_type  (class-level WorkerType)
        - data_source  (string identifying the rate-limit source key)
        - _execute(task) -> TaskResult
    """

    worker_type: WorkerType
    data_source: str  # maps to a RateLimitBudget.source key

    def __init__(self, guardrails: Guardrails):
        self.guardrails = guardrails

    # ------------------------------------------------------------------
    # Public entry point — wraps _execute with guardrail lifecycle
    # ------------------------------------------------------------------

    def run(self, task: AgentTask) -> TaskResult:
        """
        Full lifecycle:
          1. Pre-checks  (kill switch, rate limit, cost budget)
          2. Execute      (worker-specific logic)
          3. PII scan     (flag any PII before graph insertion)
          4. Post-checks  (confidence gating)
          5. Audit log
        """
        # 1 — Pre-execution guardrails
        try:
            self.guardrails.pre_execute_checks(task, source=self.data_source)
        except RuntimeError as e:
            logger.error(f"Pre-check failed for task {task.task_id}: {e}")
            task.mark_failed(str(e))
            return task.result

        # 2 — Run the actual worker logic
        task.mark_running()
        try:
            result = self._execute(task)
        except Exception as e:
            logger.exception(f"Worker {self.worker_type} failed on task {task.task_id}")
            task.mark_failed(str(e))
            self._log_audit(task, action="execution_error")
            return task.result

        # 3 — PII scan on any text data in the result
        self._scan_pii(result)

        # 4 — Confidence gating
        disposition = self.guardrails.post_execute_checks(result)
        if disposition == "discard":
            task.mark_failed("Below confidence threshold — discarded")
            result.success = False
        elif disposition == "human_review":
            task.status = task.status.REVIEW
        else:
            task.mark_completed(result)

        # 5 — Audit trail
        self._log_audit(task, action=disposition, confidence=result.confidence)

        return result

    # ------------------------------------------------------------------
    # Subclasses implement this
    # ------------------------------------------------------------------

    @abstractmethod
    def _execute(self, task: AgentTask) -> TaskResult:
        """Worker-specific logic. Must return a TaskResult."""
        ...

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _scan_pii(self, result: TaskResult):
        """Flag PII in result data values (strings only)."""
        for key, value in result.data.items():
            if isinstance(value, str) and self.guardrails.pii_detector.contains_pii(value):
                result.data[f"_pii_flagged_{key}"] = True
                logger.warning(
                    f"PII detected in result field '{key}' for task {result.task_id}"
                )

    def _log_audit(
        self,
        task: AgentTask,
        action: str,
        confidence: float = 0.0,
    ):
        record = AuditRecord(
            task_id=task.task_id,
            worker_type=self.worker_type,
            action=action,
            confidence=confidence,
        )
        self.guardrails.audit_logger.log(record)
