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

    # Optional sink for agent_intelligence trace (multi-actor journey v1).
    # Set on the class or instance to a callable accepting kwargs:
    #   event_id, event_date, agent_id, reasoning_text, tool_calls, prompt_hash
    # Production wires this to the journey-service IcebergSnapshotWriter.
    reasoning_sink = None

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

        # 6 — Emit agent_intelligence trace for multi-actor journey v1.
        # Best-effort; never fails the task on emit error.
        self._emit_reasoning(task, result)

        return result

    # ------------------------------------------------------------------
    # Multi-actor journey v1 — agent_intelligence emit
    # ------------------------------------------------------------------

    def _emit_reasoning(self, task: AgentTask, result: TaskResult) -> None:
        sink = getattr(self, "reasoning_sink", None) or getattr(type(self), "reasoning_sink", None)
        if sink is None:
            return
        # Pull reasoning + tool calls off the result if the worker chose to
        # populate them; otherwise emit a minimal trace from audit fields.
        data = getattr(result, "data", {}) or {}
        try:
            sink(
                event_id=getattr(task, "triggering_event_id", task.task_id),
                event_date=str(getattr(task, "created_at", "") or "")[:10],
                agent_id=str(self.worker_type),
                reasoning_text=str(data.get("reasoning") or ""),
                tool_calls=list(data.get("tool_calls") or []),
                prompt_hash=str(data.get("prompt_hash") or ""),
            )
        except Exception:               # noqa: BLE001
            logger.exception(f"reasoning_sink failed for task {task.task_id}")

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
