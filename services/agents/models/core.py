"""
Aether Agent Layer — Core Data Models
Shared models for tasks, results, and audit records.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from config.settings import TaskPriority, TaskStatus, WorkerType

# ---------------------------------------------------------------------------
# Task — the unit of work the controller dispatches to workers
# ---------------------------------------------------------------------------

@dataclass
class AgentTask:
    worker_type: WorkerType
    priority: TaskPriority
    payload: dict[str, Any]

    # Auto-generated
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    retries: int = 0

    # Populated after execution
    result: Optional[TaskResult] = None

    def mark_running(self):
        self.status = TaskStatus.RUNNING
        self.started_at = datetime.now(timezone.utc)

    def mark_completed(self, result: TaskResult):
        self.status = TaskStatus.COMPLETED
        self.completed_at = datetime.now(timezone.utc)
        self.result = result

    def mark_failed(self, error: str):
        self.status = TaskStatus.FAILED
        self.completed_at = datetime.now(timezone.utc)
        self.result = TaskResult(
            task_id=self.task_id,
            worker_type=self.worker_type,
            success=False,
            error=error,
        )


# ---------------------------------------------------------------------------
# TaskResult — what a worker hands back
# ---------------------------------------------------------------------------

@dataclass
class TaskResult:
    task_id: str
    worker_type: WorkerType
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    error: Optional[str] = None
    source_attribution: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# AuditRecord — provenance trail for every agent action
# ---------------------------------------------------------------------------

@dataclass
class AuditRecord:
    task_id: str
    worker_type: WorkerType
    action: str                     # e.g. "discovery", "enrichment", "graph_insert"
    entity_id: Optional[str] = None
    data_before: Optional[dict] = None
    data_after: Optional[dict] = None
    confidence: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    audit_id: str = field(default_factory=lambda: str(uuid.uuid4()))


# ---------------------------------------------------------------------------
# GraphEntity — lightweight representation of a graph node for workers
# ---------------------------------------------------------------------------

@dataclass
class GraphEntity:
    entity_id: str
    entity_type: str                # "user", "company", "wallet", "campaign", etc.
    properties: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    source: Optional[str] = None
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
