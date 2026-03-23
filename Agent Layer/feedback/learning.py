"""
Aether Agent Layer — Feedback Learning Loop
Adjusts confidence thresholds and priority weights based on accumulated
human review decisions.

Architecture:
  1. FeedbackStore — persists (task_id, worker_type, confidence, approved) records to a durable SQLite ledger
  2. ThresholdTuner — per-worker exponential moving average that shifts the
     auto_accept / discard thresholds toward the empirical decision boundary
  3. PriorityBooster — adjusts task priority scores based on historical
     yield (approved / total) per worker type

Integrations:
  - Called by AgentController.record_human_feedback()
  - Reads/writes from a durable SQLite store by default
  - Periodic refit (every N feedback events or on a schedule)
"""

from __future__ import annotations

import logging
import math
import os
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from config.settings import (
    ConfidenceThresholds,
    TaskPriority,
    WorkerType,
)

logger = logging.getLogger("aether.feedback")


# ---------------------------------------------------------------------------
# Feedback Record
# ---------------------------------------------------------------------------

@dataclass
class FeedbackRecord:
    task_id: str
    worker_type: WorkerType
    confidence: float
    approved: bool
    notes: str = ""
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ---------------------------------------------------------------------------
# Feedback Store
# ---------------------------------------------------------------------------


def _feedback_db_path() -> Path:
    explicit = os.getenv("AETHER_FEEDBACK_DB_PATH")
    env = os.getenv("AETHER_ENV", "local").lower()
    if explicit:
        path = Path(explicit)
    elif env == "local":
        path = Path(os.getenv("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "aether" / "feedback" / "feedback.sqlite3"
    else:
        raise RuntimeError("AETHER_FEEDBACK_DB_PATH must be set in non-local environments to enable durable feedback learning")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


class FeedbackStore:
    """Append-only feedback log with per-worker indexing persisted in SQLite."""

    def __init__(self):
        self._db_path = _feedback_db_path()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS feedback_records (task_id TEXT PRIMARY KEY, worker_type TEXT NOT NULL, confidence REAL NOT NULL, approved INTEGER NOT NULL, notes TEXT NOT NULL, timestamp TEXT NOT NULL)")

    def add(self, record: FeedbackRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO feedback_records(task_id, worker_type, confidence, approved, notes, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                (record.task_id, record.worker_type.value, record.confidence, int(record.approved), record.notes, record.timestamp.isoformat()),
            )

    def _rows(self, worker_type: Optional[WorkerType] = None) -> list[sqlite3.Row]:
        query = "SELECT * FROM feedback_records"
        params: tuple = ()
        if worker_type is not None:
            query += " WHERE worker_type = ?"
            params = (worker_type.value,)
        with self._connect() as conn:
            return conn.execute(query, params).fetchall()

    def get_all(self) -> list[FeedbackRecord]:
        return [self._from_row(row) for row in self._rows()]

    def get_by_worker(self, wt: WorkerType) -> list[FeedbackRecord]:
        return [self._from_row(row) for row in self._rows(wt)]

    @staticmethod
    def _from_row(row: sqlite3.Row) -> FeedbackRecord:
        return FeedbackRecord(
            task_id=row["task_id"],
            worker_type=WorkerType(row["worker_type"]),
            confidence=row["confidence"],
            approved=bool(row["approved"]),
            notes=row["notes"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
        )

    @property
    def total_count(self) -> int:
        return len(self._rows())


# ---------------------------------------------------------------------------
# Threshold Tuner
# ---------------------------------------------------------------------------

class ThresholdTuner:
    """
    Adjusts auto_accept and discard thresholds per worker type using
    an exponential moving average of the confidence values at the
    human-decision boundary.

    Key insight: if humans consistently approve results at confidence 0.55,
    the auto_accept threshold can be safely lowered toward 0.55.
    If they consistently reject at 0.45, the discard threshold rises toward 0.45.
    """

    def __init__(
        self,
        base_thresholds: ConfidenceThresholds,
        alpha: float = 0.15,          # EMA smoothing factor
        min_samples: int = 10,         # minimum feedback before adjusting
        max_shift: float = 0.20,       # max delta from base thresholds
    ):
        self._base = base_thresholds
        self._alpha = alpha
        self._min_samples = min_samples
        self._max_shift = max_shift

        # Per-worker EMA state
        self._accept_ema: dict[WorkerType, float] = {}
        self._discard_ema: dict[WorkerType, float] = {}

    def update(self, record: FeedbackRecord) -> None:
        """Process one feedback event and update the EMA."""
        wt = record.worker_type

        if record.approved:
            # Approved at this confidence → auto_accept can consider going lower
            prev = self._accept_ema.get(wt, self._base.auto_accept)
            self._accept_ema[wt] = (
                self._alpha * record.confidence + (1 - self._alpha) * prev
            )
        else:
            # Rejected at this confidence → discard can consider going higher
            prev = self._discard_ema.get(wt, self._base.discard)
            self._discard_ema[wt] = (
                self._alpha * record.confidence + (1 - self._alpha) * prev
            )

    def get_thresholds(
        self,
        worker_type: WorkerType,
        sample_count: int,
    ) -> ConfidenceThresholds:
        """
        Return tuned thresholds for a specific worker type.
        Falls back to base thresholds if not enough samples.
        """
        if sample_count < self._min_samples:
            return self._base

        accept = self._accept_ema.get(worker_type, self._base.auto_accept)
        discard = self._discard_ema.get(worker_type, self._base.discard)

        # Clamp to base ± max_shift
        accept = max(
            self._base.auto_accept - self._max_shift,
            min(accept, self._base.auto_accept + self._max_shift),
        )
        discard = max(
            self._base.discard - self._max_shift,
            min(discard, self._base.discard + self._max_shift),
        )

        # Ensure accept > discard with a minimum gap
        if accept - discard < 0.10:
            midpoint = (accept + discard) / 2
            accept = midpoint + 0.05
            discard = midpoint - 0.05

        return ConfidenceThresholds(
            auto_accept=round(accept, 4),
            discard=round(discard, 4),
        )


# ---------------------------------------------------------------------------
# Priority Booster
# ---------------------------------------------------------------------------

class PriorityBooster:
    """
    Adjusts task priorities based on per-worker-type yield rate.
    Workers with high approval rates get a priority boost (lower value);
    workers with low approval rates get deprioritized.
    """

    def __init__(self, min_samples: int = 5):
        self._min_samples = min_samples

    def compute_boost(
        self,
        worker_type: WorkerType,
        records: list[FeedbackRecord],
    ) -> int:
        """
        Returns a priority adjustment:
          -1 = boost (higher priority)
           0 = no change
          +1 = deprioritize
        """
        if len(records) < self._min_samples:
            return 0

        approved = sum(1 for r in records if r.approved)
        yield_rate = approved / len(records)

        if yield_rate >= 0.85:
            return -1  # reliable worker → boost
        elif yield_rate <= 0.40:
            return +1  # unreliable → deprioritize
        return 0

    def adjust_priority(
        self,
        base_priority: TaskPriority,
        boost: int,
    ) -> TaskPriority:
        """Apply boost to a TaskPriority, clamping to valid range."""
        new_val = base_priority.value + boost
        new_val = max(TaskPriority.CRITICAL.value, min(new_val, TaskPriority.BACKGROUND.value))
        return TaskPriority(new_val)


# ---------------------------------------------------------------------------
# Feedback Learning Loop — Facade
# ---------------------------------------------------------------------------

class FeedbackLoop:
    """
    Main entry point for the feedback system.
    Orchestrates storage, threshold tuning, and priority boosting.
    """

    def __init__(
        self,
        base_thresholds: ConfidenceThresholds,
        alpha: float = 0.15,
        min_samples_threshold: int = 10,
        min_samples_priority: int = 5,
    ):
        self.store = FeedbackStore()
        self.tuner = ThresholdTuner(
            base_thresholds,
            alpha=alpha,
            min_samples=min_samples_threshold,
        )
        self.booster = PriorityBooster(min_samples=min_samples_priority)

    def record(
        self,
        task_id: str,
        worker_type: WorkerType,
        confidence: float,
        approved: bool,
        notes: str = "",
    ) -> FeedbackRecord:
        """Record a human feedback decision and update models."""
        record = FeedbackRecord(
            task_id=task_id,
            worker_type=worker_type,
            confidence=confidence,
            approved=approved,
            notes=notes,
        )
        self.store.add(record)
        self.tuner.update(record)

        logger.info(
            f"Feedback recorded: task={task_id[:8]}... "
            f"worker={worker_type.value} conf={confidence:.2f} "
            f"approved={approved}"
        )
        return record

    def get_thresholds(self, worker_type: WorkerType) -> ConfidenceThresholds:
        """Get tuned confidence thresholds for a worker type."""
        records = self.store.get_by_worker(worker_type)
        return self.tuner.get_thresholds(worker_type, len(records))

    def get_priority_boost(self, worker_type: WorkerType) -> int:
        """Get priority adjustment for a worker type."""
        records = self.store.get_by_worker(worker_type)
        return self.booster.compute_boost(worker_type, records)

    def adjust_task_priority(
        self,
        worker_type: WorkerType,
        base_priority: TaskPriority,
    ) -> TaskPriority:
        """Convenience: get boosted priority for a new task."""
        boost = self.get_priority_boost(worker_type)
        return self.booster.adjust_priority(base_priority, boost)

    def stats(self) -> dict:
        """Summary statistics for monitoring."""
        total = self.store.total_count
        if total == 0:
            return {"total_feedback": 0, "per_worker": {}}

        per_worker: dict[str, dict] = {}
        for wt in WorkerType:
            records = self.store.get_by_worker(wt)
            if not records:
                continue
            approved = sum(1 for r in records if r.approved)
            confs = [r.confidence for r in records]
            thresholds = self.get_thresholds(wt)
            per_worker[wt.value] = {
                "count": len(records),
                "approved": approved,
                "rejected": len(records) - approved,
                "yield_rate": round(approved / len(records), 3),
                "avg_confidence": round(statistics.mean(confs), 3),
                "tuned_auto_accept": thresholds.auto_accept,
                "tuned_discard": thresholds.discard,
                "priority_boost": self.get_priority_boost(wt),
            }

        return {
            "total_feedback": total,
            "approval_rate": round(
                sum(1 for r in self.store.get_all() if r.approved) / total, 3
            ),
            "per_worker": per_worker,
        }
