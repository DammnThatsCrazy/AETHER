"""
Aether Agent Layer — Guardrails
Safety net that wraps every worker execution.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Optional

from config.settings import (
    AgentLayerSettings,
    ConfidenceThresholds,
    RateLimitBudget,
)
from models.core import AgentTask, AuditRecord, TaskResult

logger = logging.getLogger("aether.guardrails")


# ---------------------------------------------------------------------------
# Kill Switch
# ---------------------------------------------------------------------------

class KillSwitch:
    """Emergency stop — when engaged, all workers must halt immediately."""

    def __init__(self, settings: AgentLayerSettings):
        self._settings = settings

    @property
    def is_engaged(self) -> bool:
        return self._settings.kill_switch_enabled

    def engage(self):
        logger.critical("KILL SWITCH ENGAGED — halting all agent activity")
        self._settings.kill_switch_enabled = True

    def release(self):
        logger.warning("Kill switch released — resuming agent activity")
        self._settings.kill_switch_enabled = False

    def check(self):
        """Raises if kill switch is on. Call at the top of every worker run."""
        if self.is_engaged:
            raise RuntimeError("Agent kill switch is engaged. All work halted.")


# ---------------------------------------------------------------------------
# Rate Limiter (sliding-window token bucket per source)
# ---------------------------------------------------------------------------

class RateLimiter:
    """Per-source call budget enforcement."""

    def __init__(self, budgets: list[RateLimitBudget]):
        self._budgets = {b.source: b for b in budgets}
        # Simple sliding-window counters: {source: [(timestamp, count)]}
        self._minute_counts: dict[str, list[float]] = defaultdict(list)
        self._hour_counts: dict[str, list[float]] = defaultdict(list)
        self._day_counts: dict[str, list[float]] = defaultdict(list)

    def _prune(self, timestamps: list[float], window_seconds: int) -> list[float]:
        cutoff = time.time() - window_seconds
        return [t for t in timestamps if t > cutoff]

    def check_and_consume(self, source: str) -> bool:
        """Returns True if the call is allowed; False if rate-limited."""
        budget = self._budgets.get(source)
        if budget is None:
            return True  # no budget defined → allow

        now = time.time()

        self._minute_counts[source] = self._prune(self._minute_counts[source], 60)
        if len(self._minute_counts[source]) >= budget.max_calls_per_minute:
            logger.warning(f"Rate limit hit for {source} (per-minute)")
            return False

        self._hour_counts[source] = self._prune(self._hour_counts[source], 3600)
        if len(self._hour_counts[source]) >= budget.max_calls_per_hour:
            logger.warning(f"Rate limit hit for {source} (per-hour)")
            return False

        self._day_counts[source] = self._prune(self._day_counts[source], 86400)
        if len(self._day_counts[source]) >= budget.max_calls_per_day:
            logger.warning(f"Rate limit hit for {source} (per-day)")
            return False

        # Consume a token
        self._minute_counts[source].append(now)
        self._hour_counts[source].append(now)
        self._day_counts[source].append(now)
        return True


# ---------------------------------------------------------------------------
# PII Detector (placeholder — swap in a real classifier)
# ---------------------------------------------------------------------------

class PIIDetector:
    """
    Facade over the production PIIDetectorModel.
    Delegates to guardrails.pii_model for multi-layer detection
    (regex + checksum + optional NER).
    """

    def __init__(self):
        from guardrails.pii_model import PIIDetectorModel
        self._model = PIIDetectorModel(min_confidence=0.50)

    def scan(self, text: str) -> list[dict]:
        """Returns list of detected PII items with type, span, and confidence."""
        findings = self._model.scan(text)
        return [
            {
                "type": f.category.value,
                "value": f.value,
                "start": f.start,
                "end": f.end,
                "confidence": f.confidence,
                "layer": f.layer,
            }
            for f in findings
        ]

    def contains_pii(self, text: str) -> bool:
        return self._model.contains_pii(text)

    def redact(self, text: str) -> str:
        return self._model.redact(text)


# ---------------------------------------------------------------------------
# Confidence Gate
# ---------------------------------------------------------------------------

class ConfidenceGate:
    """Routes results based on confidence thresholds."""

    def __init__(self, thresholds: ConfidenceThresholds):
        self.thresholds = thresholds

    def evaluate(self, result: TaskResult) -> str:
        """
        Returns:
          - 'accept'       → confidence >= 0.7, write to graph
          - 'human_review'  → 0.3 <= confidence < 0.7
          - 'discard'       → confidence < 0.3
        """
        if result.confidence >= self.thresholds.auto_accept:
            return "accept"
        elif result.confidence >= self.thresholds.discard:
            logger.info(
                f"Task {result.task_id} queued for human review "
                f"(confidence={result.confidence:.2f})"
            )
            return "human_review"
        else:
            logger.info(
                f"Task {result.task_id} discarded "
                f"(confidence={result.confidence:.2f})"
            )
            return "discard"


# ---------------------------------------------------------------------------
# Audit Logger
# ---------------------------------------------------------------------------

class AuditLogger:
    """
    Logs every agent action with full provenance.
    In production, this writes to a durable store (DynamoDB / S3).
    For now, it keeps an in-memory log and prints to stdout.
    """

    def __init__(self):
        self._records: list[AuditRecord] = []

    def log(self, record: AuditRecord):
        self._records.append(record)
        logger.info(
            f"AUDIT | {record.action} | task={record.task_id} "
            f"| entity={record.entity_id} | conf={record.confidence:.2f}"
        )

    def get_records(self, task_id: Optional[str] = None) -> list[AuditRecord]:
        if task_id:
            return [r for r in self._records if r.task_id == task_id]
        return list(self._records)


# ---------------------------------------------------------------------------
# Cost Monitor (stub)
# ---------------------------------------------------------------------------

class CostMonitor:
    """Tracks spend and enforces budget caps."""

    def __init__(self, max_hourly: float, max_daily: float):
        self.max_hourly = max_hourly
        self.max_daily = max_daily
        self._hourly_spend = 0.0
        self._daily_spend = 0.0

    def record_cost(self, amount_usd: float):
        self._hourly_spend += amount_usd
        self._daily_spend += amount_usd

    def is_over_budget(self) -> bool:
        return (
            self._hourly_spend >= self.max_hourly
            or self._daily_spend >= self.max_daily
        )

    def reset_hourly(self):
        self._hourly_spend = 0.0

    def reset_daily(self):
        self._daily_spend = 0.0
        self._hourly_spend = 0.0


# ---------------------------------------------------------------------------
# Guardrails Facade — single entry point for workers to call
# ---------------------------------------------------------------------------

class Guardrails:
    """Aggregates all safety checks into a single interface."""

    def __init__(self, settings: AgentLayerSettings):
        self.kill_switch = KillSwitch(settings)
        self.rate_limiter = RateLimiter(settings.rate_limits)
        self.pii_detector = PIIDetector()
        self.confidence_gate = ConfidenceGate(settings.confidence)
        self.audit_logger = AuditLogger()
        self.cost_monitor = CostMonitor(
            max_hourly=settings.cost_controls.max_hourly_spend_usd,
            max_daily=settings.cost_controls.max_daily_spend_usd,
        )

    def pre_execute_checks(self, task: AgentTask, source: str) -> None:
        """Run before every worker execution. Raises on failure."""
        self.kill_switch.check()

        if self.cost_monitor.is_over_budget():
            raise RuntimeError(f"Cost budget exceeded. Task {task.task_id} blocked.")

        if not self.rate_limiter.check_and_consume(source):
            raise RuntimeError(
                f"Rate limit exceeded for source '{source}'. "
                f"Task {task.task_id} will be retried."
            )

    def post_execute_checks(self, result: TaskResult) -> str:
        """Run after worker execution. Returns disposition: accept/human_review/discard."""
        return self.confidence_gate.evaluate(result)
