"""
Aether Security — Extraction Defense Metrics

Thread-safe metrics collector for the model extraction defense layer.
Provides counters, gauges, and histograms for operational monitoring.

Designed to integrate with Prometheus client, StatsD, or Aether's
internal ``shared.logger.metrics`` — any backend that supports
increment() / observe() / gauge().

Falls back to an in-memory collector when no external backend is
configured, exposing data via ``snapshot()``.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from threading import Lock
from typing import Optional

logger = logging.getLogger("aether.security.metrics")


@dataclass
class _Counter:
    """Simple thread-safe counter."""
    _value: int = 0
    _lock: Lock = field(default_factory=Lock)

    def increment(self, n: int = 1) -> None:
        with self._lock:
            self._value += n

    @property
    def value(self) -> int:
        return self._value


class DefenseMetrics:
    """
    Collects metrics from all extraction defense components.

    Metrics emitted:

    Counters:
        extraction_defense_requests_total      — total requests processed
        extraction_defense_blocks_total         — total requests blocked
        extraction_defense_canary_triggers      — canary detection events
        extraction_defense_rate_limited         — rate limit rejections
        extraction_defense_risk_blocks          — risk-score-based blocks

    Gauges (per-client, latest value):
        extraction_defense_risk_score           — current EMA risk score
        extraction_defense_active_clients       — number of tracked clients

    Histograms / distributions:
        extraction_defense_risk_distribution    — risk tier counts
    """

    def __init__(self) -> None:
        self._lock = Lock()

        # Counters
        self.requests_total = _Counter()
        self.blocks_total = _Counter()
        self.canary_triggers_total = _Counter()
        self.rate_limit_blocks = _Counter()
        self.risk_blocks = _Counter()
        self.cooldown_blocks = _Counter()

        # Per-model request counts
        self._model_requests: dict[str, int] = defaultdict(int)

        # Per-client risk scores (latest)
        self._client_risks: dict[str, float] = {}

        # Risk tier distribution
        self._tier_counts: dict[str, int] = defaultdict(int)

        # Block reason tracking
        self._block_reasons: dict[str, int] = defaultdict(int)

        # Canary trigger log (last N)
        self._canary_log: list[dict] = []
        self._max_canary_log: int = 100

        # Timestamps
        self._start_time: float = time.time()
        self._last_reset: float = time.time()

    # ------------------------------------------------------------------
    # Recording methods (called from defense_layer.py)
    # ------------------------------------------------------------------

    def record_request(self, api_key: str, model_name: str = "") -> None:
        """Record a request processed by the defense layer."""
        self.requests_total.increment()
        if model_name:
            with self._lock:
                self._model_requests[model_name] += 1

    def record_block(
        self,
        api_key: str,
        reason: str,
        detail: str = "",
    ) -> None:
        """Record a blocked request with reason."""
        self.blocks_total.increment()
        with self._lock:
            key = f"{reason}:{detail}" if detail else reason
            self._block_reasons[key] += 1

        if reason == "rate_limit":
            self.rate_limit_blocks.increment()
        elif reason == "risk_score":
            self.risk_blocks.increment()
        elif reason in ("canary_cooldown", "canary_block"):
            self.cooldown_blocks.increment()

    def record_canary_trigger(
        self,
        api_key: str,
        canary_id: Optional[int] = None,
    ) -> None:
        """Record a canary detection event."""
        self.canary_triggers_total.increment()
        with self._lock:
            entry = {
                "api_key": api_key[:8] + "..." if api_key else "",
                "canary_id": canary_id,
                "timestamp": time.time(),
            }
            self._canary_log.append(entry)
            if len(self._canary_log) > self._max_canary_log:
                self._canary_log = self._canary_log[-self._max_canary_log:]

    def record_risk_score(
        self,
        api_key: str,
        score: float,
        tier: str,
    ) -> None:
        """Record a risk score computation for a client."""
        with self._lock:
            self._client_risks[api_key] = score
            self._tier_counts[tier] += 1

    # ------------------------------------------------------------------
    # Snapshot for monitoring dashboards
    # ------------------------------------------------------------------

    def snapshot(self) -> dict:
        """
        Return a point-in-time snapshot of all metrics.

        Returns a dict suitable for JSON serialization or Prometheus
        exposition.
        """
        with self._lock:
            active_clients = len(self._client_risks)
            avg_risk = (
                sum(self._client_risks.values()) / active_clients
                if active_clients > 0
                else 0.0
            )
            max_risk = max(self._client_risks.values()) if self._client_risks else 0.0

            return {
                "uptime_seconds": round(time.time() - self._start_time, 1),
                "counters": {
                    "requests_total": self.requests_total.value,
                    "blocks_total": self.blocks_total.value,
                    "canary_triggers_total": self.canary_triggers_total.value,
                    "rate_limit_blocks": self.rate_limit_blocks.value,
                    "risk_blocks": self.risk_blocks.value,
                    "cooldown_blocks": self.cooldown_blocks.value,
                },
                "gauges": {
                    "active_clients": active_clients,
                    "avg_risk_score": round(avg_risk, 4),
                    "max_risk_score": round(max_risk, 4),
                },
                "risk_tier_distribution": dict(self._tier_counts),
                "block_reasons": dict(self._block_reasons),
                "model_requests": dict(self._model_requests),
                "recent_canary_triggers": list(self._canary_log[-10:]),
            }

    # ------------------------------------------------------------------
    # Prometheus bridge (optional)
    # ------------------------------------------------------------------

    def export_prometheus(self) -> Optional[str]:
        """
        Export metrics in Prometheus exposition format.

        Returns None if prometheus_client is not installed.
        """
        try:
            lines = []
            snap = self.snapshot()

            for name, value in snap["counters"].items():
                lines.append(f"# TYPE extraction_defense_{name} counter")
                lines.append(f"extraction_defense_{name} {value}")

            for name, value in snap["gauges"].items():
                lines.append(f"# TYPE extraction_defense_{name} gauge")
                lines.append(f"extraction_defense_{name} {value}")

            for tier, count in snap["risk_tier_distribution"].items():
                lines.append(
                    f'extraction_defense_risk_tier{{tier="{tier}"}} {count}'
                )

            return "\n".join(lines) + "\n"
        except Exception:
            return None

    def reset(self) -> None:
        """Reset all metrics. Useful for testing."""
        with self._lock:
            self.requests_total = _Counter()
            self.blocks_total = _Counter()
            self.canary_triggers_total = _Counter()
            self.rate_limit_blocks = _Counter()
            self.risk_blocks = _Counter()
            self.cooldown_blocks = _Counter()
            self._model_requests.clear()
            self._client_risks.clear()
            self._tier_counts.clear()
            self._block_reasons.clear()
            self._canary_log.clear()
            self._last_reset = time.time()
