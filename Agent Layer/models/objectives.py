"""
Aether Agent Layer — Objective & Plan Models
Durable objective runtime models for the multi-controller architecture.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class ObjectiveType(str, Enum):
    DISCOVERY = "discovery"
    ENRICHMENT = "enrichment"
    VERIFICATION = "verification"
    MAINTENANCE = "maintenance"
    RECOVERY = "recovery"
    RECONCILIATION = "reconciliation"


class ObjectiveStatus(str, Enum):
    PENDING = "pending"
    PLANNING = "planning"
    ACTIVE = "active"
    BLOCKED = "blocked"
    AWAITING_REVIEW = "awaiting_review"
    SLEEPING = "sleeping"
    COMPLETED = "completed"
    FAILED = "failed"
    RECOVERING = "recovering"
    CANCELLED = "cancelled"


class PlanStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    REPLANNING = "replanning"
    SUPERSEDED = "superseded"


class StepStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class Severity(int, Enum):
    CRITICAL = 0
    HIGH = 1
    MEDIUM = 2
    LOW = 3
    INFO = 4


# ---------------------------------------------------------------------------
# Objective — the top-level unit of agent work
# ---------------------------------------------------------------------------

@dataclass
class Objective:
    objective_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    objective_type: ObjectiveType = ObjectiveType.DISCOVERY
    source: str = ""
    target_entity_ids: list[str] = field(default_factory=list)
    goal_definition: str = ""
    success_criteria: list[str] = field(default_factory=list)
    severity: Severity = Severity.MEDIUM
    priority: int = 2
    policy_scope: str = "default"
    budget_limit: float = 0.0
    deadline: Optional[datetime] = None
    status: ObjectiveStatus = ObjectiveStatus.PENDING
    opened_by: str = ""
    opened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    owner_controller: str = ""
    current_plan_id: Optional[str] = None
    review_required: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def activate(self) -> None:
        self.status = ObjectiveStatus.ACTIVE

    def block(self, reason: str = "") -> None:
        self.status = ObjectiveStatus.BLOCKED
        self.metadata["block_reason"] = reason

    def complete(self) -> None:
        self.status = ObjectiveStatus.COMPLETED

    def fail(self, reason: str = "") -> None:
        self.status = ObjectiveStatus.FAILED
        self.metadata["failure_reason"] = reason

    def send_to_review(self) -> None:
        self.status = ObjectiveStatus.AWAITING_REVIEW

    def sleep(self) -> None:
        self.status = ObjectiveStatus.SLEEPING

    def recover(self) -> None:
        self.status = ObjectiveStatus.RECOVERING


# ---------------------------------------------------------------------------
# Plan — a structured execution plan for an objective
# ---------------------------------------------------------------------------

@dataclass
class Plan:
    plan_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    objective_id: str = ""
    version: int = 1
    status: PlanStatus = PlanStatus.DRAFT
    steps: list[PlanStep] = field(default_factory=list)
    dependencies: dict[str, list[str]] = field(default_factory=dict)
    estimated_cost: float = 0.0
    estimated_latency_seconds: float = 0.0
    created_by: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def activate(self) -> None:
        self.status = PlanStatus.ACTIVE
        self.updated_at = datetime.now(timezone.utc)

    def complete(self) -> None:
        self.status = PlanStatus.COMPLETED
        self.updated_at = datetime.now(timezone.utc)

    def fail(self) -> None:
        self.status = PlanStatus.FAILED
        self.updated_at = datetime.now(timezone.utc)

    def supersede(self) -> None:
        self.status = PlanStatus.SUPERSEDED
        self.updated_at = datetime.now(timezone.utc)

    @property
    def pending_steps(self) -> list[PlanStep]:
        return [s for s in self.steps if s.status == StepStatus.PENDING]

    @property
    def completed_steps(self) -> list[PlanStep]:
        return [s for s in self.steps if s.status == StepStatus.COMPLETED]

    @property
    def failed_steps(self) -> list[PlanStep]:
        return [s for s in self.steps if s.status == StepStatus.FAILED]

    @property
    def blocked_steps(self) -> list[PlanStep]:
        return [s for s in self.steps if s.status == StepStatus.BLOCKED]

    @property
    def progress_ratio(self) -> float:
        if not self.steps:
            return 0.0
        return len(self.completed_steps) / len(self.steps)


# ---------------------------------------------------------------------------
# PlanStep — a single step within a plan
# ---------------------------------------------------------------------------

@dataclass
class PlanStep:
    step_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    plan_id: str = ""
    required_domain: str = ""
    assigned_controller: str = ""
    assigned_team: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    expected_output_schema: dict[str, Any] = field(default_factory=dict)
    verification_requirements: list[str] = field(default_factory=list)
    retry_policy: dict[str, Any] = field(default_factory=lambda: {
        "max_retries": 3,
        "backoff_seconds": 30,
    })
    compensation_policy: dict[str, Any] = field(default_factory=dict)
    status: StepStatus = StepStatus.PENDING
    result: dict[str, Any] = field(default_factory=dict)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    def start(self) -> None:
        self.status = StepStatus.RUNNING
        self.started_at = datetime.now(timezone.utc)

    def complete(self, result: dict[str, Any] | None = None) -> None:
        self.status = StepStatus.COMPLETED
        self.completed_at = datetime.now(timezone.utc)
        if result:
            self.result = result

    def fail(self, error: str = "") -> None:
        self.status = StepStatus.FAILED
        self.completed_at = datetime.now(timezone.utc)
        self.result["error"] = error

    def block(self, reason: str = "") -> None:
        self.status = StepStatus.BLOCKED
        self.result["block_reason"] = reason
