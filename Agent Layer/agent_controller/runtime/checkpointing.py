"""
Aether Agent Layer — Checkpointing Runtime
Manages checkpoint records for objective/plan progress tracking.
Used by BOLT for continuity across sessions and process restarts.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("aether.runtime.checkpointing")


@dataclass
class CheckpointRecord:
    checkpoint_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    objective_id: str = ""
    plan_id: str = ""
    open_steps: list[str] = field(default_factory=list)
    completed_steps: list[str] = field(default_factory=list)
    blocked_steps: list[str] = field(default_factory=list)
    budget_spent: float = 0.0
    current_risks: list[str] = field(default_factory=list)
    summary: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


class CheckpointStore:
    """In-memory checkpoint store. Production: backed by PostgreSQL/Redis."""

    def __init__(self):
        self._checkpoints: dict[str, list[CheckpointRecord]] = {}

    def save(self, checkpoint: CheckpointRecord) -> None:
        key = checkpoint.objective_id
        self._checkpoints.setdefault(key, []).append(checkpoint)
        logger.info(
            f"Checkpoint saved: {checkpoint.checkpoint_id[:8]}... "
            f"for objective {key[:8]}..."
        )

    def latest(self, objective_id: str) -> Optional[CheckpointRecord]:
        records = self._checkpoints.get(objective_id, [])
        return records[-1] if records else None

    def history(self, objective_id: str) -> list[CheckpointRecord]:
        return list(self._checkpoints.get(objective_id, []))

    def all_latest(self) -> list[CheckpointRecord]:
        """Return the most recent checkpoint for every objective."""
        return [recs[-1] for recs in self._checkpoints.values() if recs]

    def create_checkpoint(
        self,
        objective_id: str,
        plan_id: str = "",
        open_steps: list[str] | None = None,
        completed_steps: list[str] | None = None,
        blocked_steps: list[str] | None = None,
        budget_spent: float = 0.0,
        current_risks: list[str] | None = None,
        summary: str = "",
    ) -> CheckpointRecord:
        cp = CheckpointRecord(
            objective_id=objective_id,
            plan_id=plan_id,
            open_steps=open_steps or [],
            completed_steps=completed_steps or [],
            blocked_steps=blocked_steps or [],
            budget_spent=budget_spent,
            current_risks=current_risks or [],
            summary=summary,
        )
        self.save(cp)
        return cp
