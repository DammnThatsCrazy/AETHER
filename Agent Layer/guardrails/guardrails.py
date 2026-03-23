"""Aether Agent Layer — durable guardrails."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from config.settings import AgentLayerSettings, ConfidenceThresholds, RateLimitBudget
from models.core import AuditRecord, TaskResult, AgentTask

logger = logging.getLogger("aether.guardrails")


def _state_dir(component: str) -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    path = base / "aether" / component
    path.mkdir(parents=True, exist_ok=True)
    return path


def _guardrails_db_path() -> Path:
    explicit = os.environ.get("AETHER_GUARDRAILS_DB_PATH")
    env = os.environ.get("AETHER_ENV", "local").lower()
    if explicit:
        path = Path(explicit)
    elif env == "local":
        path = _state_dir("guardrails") / "guardrails.sqlite3"
    else:
        raise RuntimeError(
            "AETHER_GUARDRAILS_DB_PATH must be set in non-local environments to enable durable guardrail audit and cost tracking."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


class _GuardrailsStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS audit_records (audit_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, worker_type TEXT NOT NULL, action TEXT NOT NULL, entity_id TEXT, data_before TEXT, data_after TEXT, confidence REAL NOT NULL, timestamp TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS spend_ledger (id INTEGER PRIMARY KEY AUTOINCREMENT, amount_usd REAL NOT NULL, recorded_at REAL NOT NULL)"
            )

    def write_audit(self, record: AuditRecord) -> None:
        payload = asdict(record)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO audit_records(audit_id, task_id, worker_type, action, entity_id, data_before, data_after, confidence, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    payload["audit_id"], payload["task_id"], str(payload["worker_type"]), payload["action"], payload["entity_id"],
                    json.dumps(payload["data_before"], default=str), json.dumps(payload["data_after"], default=str), payload["confidence"], payload["timestamp"].isoformat(),
                ),
            )

    def read_audit(self, task_id: Optional[str] = None) -> list[AuditRecord]:
        query = "SELECT * FROM audit_records"
        params: tuple = ()
        if task_id:
            query += " WHERE task_id = ?"
            params = (task_id,)
        query += " ORDER BY timestamp"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        records: list[AuditRecord] = []
        for row in rows:
            records.append(
                AuditRecord(
                    task_id=row["task_id"],
                    worker_type=row["worker_type"],
                    action=row["action"],
                    entity_id=row["entity_id"],
                    data_before=json.loads(row["data_before"]) if row["data_before"] else None,
                    data_after=json.loads(row["data_after"]) if row["data_after"] else None,
                    confidence=row["confidence"],
                    audit_id=row["audit_id"],
                )
            )
        return records

    def record_spend(self, amount_usd: float) -> None:
        with self._connect() as conn:
            conn.execute("INSERT INTO spend_ledger(amount_usd, recorded_at) VALUES (?, ?)", (amount_usd, time.time()))

    def spend_totals(self) -> tuple[float, float]:
        now = time.time()
        with self._connect() as conn:
            hourly = conn.execute("SELECT COALESCE(SUM(amount_usd), 0) AS total FROM spend_ledger WHERE recorded_at >= ?", (now - 3600,)).fetchone()["total"]
            daily = conn.execute("SELECT COALESCE(SUM(amount_usd), 0) AS total FROM spend_ledger WHERE recorded_at >= ?", (now - 86400,)).fetchone()["total"]
        return float(hourly), float(daily)


class KillSwitch:
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
        if self.is_engaged:
            raise RuntimeError("Agent kill switch is engaged. All work halted.")


class RateLimiter:
    def __init__(self, budgets: list[RateLimitBudget]):
        self._budgets = {b.source: b for b in budgets}
        self._minute_counts: dict[str, list[float]] = defaultdict(list)
        self._hour_counts: dict[str, list[float]] = defaultdict(list)
        self._day_counts: dict[str, list[float]] = defaultdict(list)

    def _prune(self, timestamps: list[float], window_seconds: int) -> list[float]:
        cutoff = time.time() - window_seconds
        return [t for t in timestamps if t > cutoff]

    def check_and_consume(self, source: str) -> bool:
        budget = self._budgets.get(source)
        if budget is None:
            return True
        now = time.time()
        self._minute_counts[source] = self._prune(self._minute_counts[source], 60)
        self._hour_counts[source] = self._prune(self._hour_counts[source], 3600)
        self._day_counts[source] = self._prune(self._day_counts[source], 86400)
        if len(self._minute_counts[source]) >= budget.max_calls_per_minute:
            return False
        if len(self._hour_counts[source]) >= budget.max_calls_per_hour:
            return False
        if len(self._day_counts[source]) >= budget.max_calls_per_day:
            return False
        self._minute_counts[source].append(now)
        self._hour_counts[source].append(now)
        self._day_counts[source].append(now)
        return True


class PIIDetector:
    def __init__(self):
        from guardrails.pii_model import PIIDetectorModel
        self._model = PIIDetectorModel(min_confidence=0.50)

    def scan(self, text: str) -> list[dict]:
        findings = self._model.scan(text)
        return [{"type": f.category.value, "value": f.value, "start": f.start, "end": f.end, "confidence": f.confidence, "layer": f.layer} for f in findings]

    def contains_pii(self, text: str) -> bool:
        return self._model.contains_pii(text)

    def redact(self, text: str) -> str:
        return self._model.redact(text)


class ConfidenceGate:
    def __init__(self, thresholds: ConfidenceThresholds):
        self.thresholds = thresholds

    def evaluate(self, result: TaskResult) -> str:
        if result.confidence >= self.thresholds.auto_accept:
            return "accept"
        if result.confidence >= self.thresholds.discard:
            logger.info("Task %s queued for human review (confidence=%.2f)", result.task_id, result.confidence)
            return "human_review"
        logger.info("Task %s discarded (confidence=%.2f)", result.task_id, result.confidence)
        return "discard"


class AuditLogger:
    """Durable audit log backed by SQLite."""

    def __init__(self, db_path: Optional[Path] = None):
        self._store = _GuardrailsStore(db_path or _guardrails_db_path())

    def log(self, record: AuditRecord):
        self._store.write_audit(record)
        logger.info("AUDIT | %s | task=%s | entity=%s | conf=%.2f", record.action, record.task_id, record.entity_id, record.confidence)

    def get_records(self, task_id: Optional[str] = None) -> list[AuditRecord]:
        return self._store.read_audit(task_id)


class CostMonitor:
    """Durable spend tracker with hourly and daily budget enforcement."""

    def __init__(self, max_hourly: float, max_daily: float, db_path: Optional[Path] = None):
        self.max_hourly = max_hourly
        self.max_daily = max_daily
        self._store = _GuardrailsStore(db_path or _guardrails_db_path())

    @property
    def hourly_spend(self) -> float:
        return self._store.spend_totals()[0]

    @property
    def daily_spend(self) -> float:
        return self._store.spend_totals()[1]

    def record_cost(self, amount_usd: float):
        if amount_usd < 0:
            raise ValueError("amount_usd must be non-negative")
        self._store.record_spend(amount_usd)

    def is_over_budget(self) -> bool:
        hourly, daily = self._store.spend_totals()
        return hourly >= self.max_hourly or daily >= self.max_daily

    def reset_hourly(self):
        raise RuntimeError("Hourly spend is derived from the immutable ledger and cannot be reset manually")

    def reset_daily(self):
        raise RuntimeError("Daily spend is derived from the immutable ledger and cannot be reset manually")


class Guardrails:
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
        self.kill_switch.check()
        if self.cost_monitor.is_over_budget():
            raise RuntimeError(f"Cost budget exceeded. Task {task.task_id} blocked.")
        if not self.rate_limiter.check_and_consume(source):
            raise RuntimeError(f"Rate limit exceeded for source '{source}'. Task {task.task_id} will be retried.")

    def post_execute_checks(self, result: TaskResult) -> str:
        return self.confidence_gate.evaluate(result)
