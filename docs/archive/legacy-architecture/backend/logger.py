"""
Aether Shared — @aether/logger
Structured JSON logging with request tracing and correlation IDs.
Used by ALL services.
"""

from __future__ import annotations

import json
import logging
import sys
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

# Context-local correlation ID — set per-request by middleware
_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")
_tenant_id: ContextVar[str] = ContextVar("tenant_id", default="")


def set_request_context(correlation_id: str, tenant_id: str = ""):
    _correlation_id.set(correlation_id)
    _tenant_id.set(tenant_id)


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
        }

        # Attach extra fields if provided
        if hasattr(record, "extra_data"):
            log_entry["data"] = record.extra_data

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
):
    """Log a message with arbitrary structured data attached."""
    record = logger.makeRecord(
        logger.name, level, "", 0, message, (), None
    )
    record.extra_data = extra  # type: ignore
    logger.handle(record)
