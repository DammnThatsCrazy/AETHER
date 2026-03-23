"""
Aether Shared — @aether/logger
Structured JSON logging with request tracing, correlation IDs, and performance metrics.
Used by ALL services.
"""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from collections import defaultdict
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Optional

# Context-local correlation ID — set per-request by middleware
_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")
_tenant_id: ContextVar[str] = ContextVar("tenant_id", default="")
_service_name: ContextVar[str] = ContextVar("service_name", default="aether")


def set_request_context(
    correlation_id: str,
    tenant_id: str = "",
    service_name: str = "",
) -> None:
    _correlation_id.set(correlation_id)
    if tenant_id:
        _tenant_id.set(tenant_id)
    if service_name:
        _service_name.set(service_name)


def get_correlation_id() -> str:
    return _correlation_id.get() or str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Structured JSON formatter
# ---------------------------------------------------------------------------

class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": _correlation_id.get(""),
            "tenant_id": _tenant_id.get(""),
            "service": _service_name.get("aether"),
        }

        # Attach extra fields if provided
        if hasattr(record, "extra_data"):
            log_entry["data"] = record.extra_data  # type: ignore[attr-defined]

        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = {
                "type": type(record.exc_info[1]).__name__,
                "message": str(record.exc_info[1]),
            }

        return json.dumps(log_entry)


# ---------------------------------------------------------------------------
# Logger factory
# ---------------------------------------------------------------------------

def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """Create a structured JSON logger for a given service/module."""
    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
        logger.setLevel(level)
        logger.propagate = False

    return logger


# ---------------------------------------------------------------------------
# Convenience: log with extra structured data
# ---------------------------------------------------------------------------

def log_event(
    logger: logging.Logger,
    level: int,
    message: str,
    **extra: Any,
) -> None:
    """Log a message with arbitrary structured data attached."""
    record = logger.makeRecord(
        logger.name, level, "", 0, message, (), None
    )
    record.extra_data = extra  # type: ignore[attr-defined]
    logger.handle(record)


# ---------------------------------------------------------------------------
# Lightweight metrics counter (Prometheus-compatible in production)
# ---------------------------------------------------------------------------

try:
    from prometheus_client import Counter, Histogram, CollectorRegistry, generate_latest
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False


class MetricsCollector:
    """
    Metrics collection with Prometheus backend when available.

    Production: uses prometheus_client Counter/Histogram for /metrics export.
    Local/fallback: in-memory dicts (same interface, no Prometheus export).
    """

    def __init__(self) -> None:
        self._counters: dict[str, int] = defaultdict(int)
        self._histograms: dict[str, list[float]] = defaultdict(list)
        self._prom_counters: dict[str, Any] = {}
        self._prom_histograms: dict[str, Any] = {}
        self._prom_registry: Optional[Any] = None
        if PROMETHEUS_AVAILABLE:
            self._prom_registry = CollectorRegistry()

    def _get_prom_counter(self, name: str, label_names: tuple) -> Any:
        key = f"{name}:{','.join(label_names)}"
        if key not in self._prom_counters:
            safe_name = name.replace(".", "_").replace("-", "_").replace("{", "").replace("}", "")
            self._prom_counters[key] = Counter(
                safe_name, f"Aether counter: {name}",
                label_names, registry=self._prom_registry,
            )
        return self._prom_counters[key]

    def _get_prom_histogram(self, name: str, label_names: tuple) -> Any:
        key = f"{name}:{','.join(label_names)}"
        if key not in self._prom_histograms:
            safe_name = name.replace(".", "_").replace("-", "_").replace("{", "").replace("}", "")
            self._prom_histograms[key] = Histogram(
                safe_name, f"Aether histogram: {name}",
                label_names, registry=self._prom_registry,
            )
        return self._prom_histograms[key]

    def increment(self, name: str, value: int = 1, labels: Optional[dict] = None) -> None:
        key = self._key(name, labels)
        self._counters[key] += value
        if PROMETHEUS_AVAILABLE and self._prom_registry:
            label_names = tuple(sorted(labels.keys())) if labels else ()
            label_values = tuple(str(labels[k]) for k in sorted(labels.keys())) if labels else ()
            try:
                counter = self._get_prom_counter(name, label_names)
                if label_values:
                    counter.labels(*label_values).inc(value)
                else:
                    counter.inc(value)
            except Exception:
                pass  # Prometheus errors never break application logic

    def observe(self, name: str, value: float, labels: Optional[dict] = None) -> None:
        key = self._key(name, labels)
        self._histograms[key].append(value)
        if PROMETHEUS_AVAILABLE and self._prom_registry:
            label_names = tuple(sorted(labels.keys())) if labels else ()
            label_values = tuple(str(labels[k]) for k in sorted(labels.keys())) if labels else ()
            try:
                hist = self._get_prom_histogram(name, label_names)
                if label_values:
                    hist.labels(*label_values).observe(value)
                else:
                    hist.observe(value)
            except Exception:
                pass

    def get_counter(self, name: str, labels: Optional[dict] = None) -> int:
        return self._counters.get(self._key(name, labels), 0)

    def snapshot(self) -> dict[str, Any]:
        return {
            "counters": dict(self._counters),
            "histograms": {
                k: {"count": len(v), "avg": sum(v) / len(v) if v else 0}
                for k, v in self._histograms.items()
            },
        }

    def prometheus_export(self) -> bytes:
        """Export metrics in Prometheus text format."""
        if PROMETHEUS_AVAILABLE and self._prom_registry:
            return generate_latest(self._prom_registry)
        return b""

    @staticmethod
    def _key(name: str, labels: Optional[dict] = None) -> str:
        if not labels:
            return name
        suffix = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{suffix}}}"


# Singleton
metrics = MetricsCollector()
