"""
Aether Shared — Automatic Error Registry & Diagnostics
Registers, classifies, and tracks all errors across services.
Provides root-cause analysis and remediation guidance.

Usage:
    from shared.diagnostics.error_registry import error_registry, track_error, ErrorSeverity

    # Automatic tracking via decorator
    @track_error("commerce.record_payment")
    async def record_payment(...):
        ...

    # Manual registration
    error_registry.register(
        error=exc,
        service="x402",
        operation="snapshot_to_graph",
        context={"payments_count": len(payments)},
    )

    # Query diagnostics
    report = error_registry.get_report()
    health = error_registry.health_check()
"""

from __future__ import annotations

import asyncio
import hashlib
import traceback
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from functools import wraps
from typing import Any, Callable, Optional

from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.diagnostics")


# ═══════════════════════════════════════════════════════════════════════════
# ERROR SEVERITY & CLASSIFICATION
# ═══════════════════════════════════════════════════════════════════════════

class ErrorSeverity(str, Enum):
    CRITICAL = "critical"    # System-down, data loss risk
    HIGH = "high"            # Feature broken, degraded service
    MEDIUM = "medium"        # Partial failure, workaround available
    LOW = "low"              # Minor issue, cosmetic
    WARNING = "warning"      # Not an error yet, but trending toward one


class ErrorCategory(str, Enum):
    RACE_CONDITION = "race_condition"
    SECURITY = "security"
    DATA_INTEGRITY = "data_integrity"
    GRAPH_MUTATION = "graph_mutation"
    EVENT_PIPELINE = "event_pipeline"
    AUTH = "authentication"
    RATE_LIMIT = "rate_limit"
    VALIDATION = "validation"
    TIMEOUT = "timeout"
    DEPENDENCY = "dependency"
    MEMORY = "memory"
    CONFIGURATION = "configuration"
    UNKNOWN = "unknown"


# ═══════════════════════════════════════════════════════════════════════════
# ERROR FINGERPRINTING — groups identical errors together
# ═══════════════════════════════════════════════════════════════════════════

def _fingerprint(error: Exception, service: str, operation: str) -> str:
    """Generate a unique fingerprint for an error to group duplicates."""
    error_type = type(error).__name__
    # Use first 3 frames of traceback for fingerprint
    tb = traceback.extract_tb(error.__traceback__)
    frames = "|".join(f"{f.filename}:{f.lineno}" for f in tb[:3])
    raw = f"{service}:{operation}:{error_type}:{frames}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ═══════════════════════════════════════════════════════════════════════════
# ERROR CLASSIFICATION ENGINE
# ═══════════════════════════════════════════════════════════════════════════

# Maps exception types and keywords to categories + severity + remediation
_CLASSIFICATION_RULES: list[dict] = [
    # Race conditions
    {
        "keywords": ["concurrent", "lock", "deadlock", "race", "atomic"],
        "exception_types": ["RuntimeError"],
        "category": ErrorCategory.RACE_CONDITION,
        "severity": ErrorSeverity.CRITICAL,
        "remediation": "Add asyncio.Lock to protect shared mutable state. Use copy-and-swap pattern for list mutations during iteration.",
    },
    # Graph mutations
    {
        "keywords": ["graph", "vertex", "edge", "gremlin", "neptune", "upsert_vertex", "add_edge", "add_vertex"],
        "exception_types": ["ConnectionError", "TimeoutError"],
        "category": ErrorCategory.GRAPH_MUTATION,
        "severity": ErrorSeverity.HIGH,
        "remediation": "Graph database may be unavailable. Check Neptune endpoint connectivity. Retry with exponential backoff. Do NOT clear pending data on failure.",
    },
    # Event pipeline
    {
        "keywords": ["publish", "kafka", "event", "producer", "consumer", "topic"],
        "exception_types": ["KafkaError"],
        "category": ErrorCategory.EVENT_PIPELINE,
        "severity": ErrorSeverity.HIGH,
        "remediation": "Event producer failed. Record data locally first, then publish asynchronously. Check Kafka broker health.",
    },
    # Auth errors
    {
        "keywords": ["jwt", "token", "unauthorized", "forbidden", "permission", "api_key"],
        "exception_types": ["UnauthorizedError", "ForbiddenError"],
        "category": ErrorCategory.AUTH,
        "severity": ErrorSeverity.MEDIUM,
        "remediation": "Authentication or authorization failure. Verify JWT secret is set, API key is valid, and tenant has required permissions.",
    },
    # Rate limiting
    {
        "keywords": ["rate", "limit", "throttle", "429", "too many"],
        "exception_types": ["RateLimitError"],
        "category": ErrorCategory.RATE_LIMIT,
        "severity": ErrorSeverity.LOW,
        "remediation": "Rate limit exceeded. Implement exponential backoff with jitter. Check tier-specific limits in RateLimitConfig.",
    },
    # Validation
    {
        "keywords": ["validation", "invalid", "malformed", "parse", "schema", "pydantic"],
        "exception_types": ["ValidationError", "ValueError", "TypeError", "JSONDecodeError"],
        "category": ErrorCategory.VALIDATION,
        "severity": ErrorSeverity.MEDIUM,
        "remediation": "Input validation failed. Check request payload against the Pydantic model schema. Ensure all required fields are present and correctly typed.",
    },
    # Timeouts
    {
        "keywords": ["timeout", "timed out", "deadline", "exceeded"],
        "exception_types": ["TimeoutError", "asyncio.TimeoutError"],
        "category": ErrorCategory.TIMEOUT,
        "severity": ErrorSeverity.HIGH,
        "remediation": "Operation timed out. Check downstream service health. Consider increasing timeout thresholds or adding circuit breaker.",
    },
    # Memory
    {
        "keywords": ["memory", "oom", "heap", "allocation"],
        "exception_types": ["MemoryError"],
        "category": ErrorCategory.MEMORY,
        "severity": ErrorSeverity.CRITICAL,
        "remediation": "Memory exhaustion detected. Check for unbounded in-memory lists (ActionRecorder._actions, X402Interceptor._captures). Implement max_size limits and periodic flushing.",
    },
    # Dependency
    {
        "keywords": ["connect", "connection", "refused", "unreachable", "dns"],
        "exception_types": ["ConnectionError", "ConnectionRefusedError", "OSError"],
        "category": ErrorCategory.DEPENDENCY,
        "severity": ErrorSeverity.HIGH,
        "remediation": "External dependency unreachable. Check network connectivity, DNS resolution, and service health. Verify endpoint configuration in settings.py.",
    },
    # Configuration
    {
        "keywords": ["config", "setting", "environment", "env", "missing"],
        "exception_types": ["ConfigurationError"],
        "category": ErrorCategory.CONFIGURATION,
        "severity": ErrorSeverity.HIGH,
        "remediation": "Configuration error. Verify all required environment variables are set. Check config/settings.py for missing or invalid values.",
    },
    # Data integrity
    {
        "keywords": ["integrity", "duplicate", "inconsistent", "mismatch", "orphan", "stale"],
        "exception_types": ["IntegrityError"],
        "category": ErrorCategory.DATA_INTEGRITY,
        "severity": ErrorSeverity.HIGH,
        "remediation": "Data integrity violation. Check for duplicate entries, orphaned graph edges, or stale cache. Verify transactional boundaries in graph mutations.",
    },
]


def _classify_error(error: Exception, service: str, operation: str) -> tuple[ErrorCategory, ErrorSeverity, str]:
    """Classify an error into category, severity, and remediation advice."""
    error_str = str(error).lower()
    error_type = type(error).__name__
    operation_lower = operation.lower()
    combined = f"{error_str} {operation_lower} {service}"

    for rule in _CLASSIFICATION_RULES:
        # Check exception type match
        type_match = error_type in rule.get("exception_types", [])
        # Check keyword match
        keyword_match = any(kw in combined for kw in rule.get("keywords", []))

        if type_match or keyword_match:
            return rule["category"], rule["severity"], rule["remediation"]

    return ErrorCategory.UNKNOWN, ErrorSeverity.MEDIUM, (
        f"Unclassified error in {service}.{operation}. "
        f"Review the stack trace and add a classification rule to error_registry.py."
    )


# ═══════════════════════════════════════════════════════════════════════════
# ERROR RECORD
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class ErrorRecord:
    """A single error occurrence with full context."""
    fingerprint: str
    error_type: str
    message: str
    service: str
    operation: str
    category: ErrorCategory
    severity: ErrorSeverity
    remediation: str
    stack_trace: str
    context: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    occurrence_count: int = 1
    first_seen: str = ""
    last_seen: str = ""
    resolved: bool = False

    def to_dict(self) -> dict:
        return {
            "fingerprint": self.fingerprint,
            "error_type": self.error_type,
            "message": self.message[:500],  # Truncate long messages
            "service": self.service,
            "operation": self.operation,
            "category": self.category.value,
            "severity": self.severity.value,
            "remediation": self.remediation,
            "occurrence_count": self.occurrence_count,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "resolved": self.resolved,
            "context": self.context,
        }


# ═══════════════════════════════════════════════════════════════════════════
# CIRCUIT BREAKER — prevents cascading failures
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class CircuitBreaker:
    """Per-operation circuit breaker to prevent cascading failures."""
    failure_threshold: int = 5      # Failures before opening
    recovery_timeout: float = 30.0  # Seconds before half-open
    _failure_count: int = 0
    _last_failure_time: float = 0.0
    _state: str = "closed"  # closed, open, half_open

    def record_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self._failure_count >= self.failure_threshold:
            self._state = "open"

    def record_success(self) -> None:
        self._failure_count = 0
        self._state = "closed"

    @property
    def is_open(self) -> bool:
        if self._state == "open":
            if time.time() - self._last_failure_time > self.recovery_timeout:
                self._state = "half_open"
                return False
            return True
        return False

    @property
    def state(self) -> str:
        # Refresh state
        _ = self.is_open
        return self._state


# ═══════════════════════════════════════════════════════════════════════════
# ERROR REGISTRY — singleton that tracks all errors system-wide
# ═══════════════════════════════════════════════════════════════════════════

class ErrorRegistry:
    """
    Central error tracking, classification, and diagnostics.
    Thread-safe singleton that aggregates errors across all services.
    """

    MAX_UNIQUE_ERRORS = 1000
    MAX_RECENT_ERRORS = 200
    ALERT_THRESHOLD = 10  # errors per minute before alerting

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._errors: dict[str, ErrorRecord] = {}           # fingerprint -> record
        self._recent: deque[ErrorRecord] = deque(maxlen=self.MAX_RECENT_ERRORS)
        self._error_rate: deque[float] = deque(maxlen=600)   # timestamps for rate calc
        self._circuit_breakers: dict[str, CircuitBreaker] = defaultdict(CircuitBreaker)
        self._service_health: dict[str, dict] = {}          # service -> health stats
        self._suppressed: set[str] = set()                   # suppressed fingerprints
        self._started_at = time.time()

    def register(
        self,
        error: Exception,
        service: str,
        operation: str,
        context: Optional[dict] = None,
        severity_override: Optional[ErrorSeverity] = None,
    ) -> ErrorRecord:
        """
        Register an error occurrence. Deduplicates by fingerprint.
        Returns the ErrorRecord (new or updated).
        """
        fp = _fingerprint(error, service, operation)
        category, severity, remediation = _classify_error(error, service, operation)

        if severity_override:
            severity = severity_override

        now = datetime.now(timezone.utc).isoformat()
        stack = traceback.format_exception(type(error), error, error.__traceback__)
        stack_str = "".join(stack[-5:])  # Last 5 frames

        # Update or create record
        existing = self._errors.get(fp)
        if existing:
            existing.occurrence_count += 1
            existing.last_seen = now
            existing.context = context or existing.context
            record = existing
        else:
            record = ErrorRecord(
                fingerprint=fp,
                error_type=type(error).__name__,
                message=str(error),
                service=service,
                operation=operation,
                category=category,
                severity=severity,
                remediation=remediation,
                stack_trace=stack_str,
                context=context or {},
                first_seen=now,
                last_seen=now,
            )
            # Evict oldest if at capacity
            if len(self._errors) >= self.MAX_UNIQUE_ERRORS:
                oldest_fp = min(self._errors, key=lambda k: self._errors[k].last_seen)
                del self._errors[oldest_fp]
            self._errors[fp] = record

        self._recent.append(record)
        self._error_rate.append(time.time())

        # Update circuit breaker
        breaker_key = f"{service}.{operation}"
        self._circuit_breakers[breaker_key].record_failure()

        # Update service health
        if service not in self._service_health:
            self._service_health[service] = {"errors": 0, "last_error": "", "status": "healthy"}
        self._service_health[service]["errors"] += 1
        self._service_health[service]["last_error"] = now

        # Log with structured context
        log_method = {
            ErrorSeverity.CRITICAL: logger.critical,
            ErrorSeverity.HIGH: logger.error,
            ErrorSeverity.MEDIUM: logger.warning,
            ErrorSeverity.LOW: logger.info,
            ErrorSeverity.WARNING: logger.warning,
        }.get(severity, logger.error)

        log_method(
            f"[{severity.value.upper()}] {service}.{operation}: {type(error).__name__}: {error} "
            f"| category={category.value} | occurrences={record.occurrence_count} "
            f"| fingerprint={fp}"
        )

        # Metrics
        metrics.increment("errors_registered", labels={
            "service": service,
            "category": category.value,
            "severity": severity.value,
        })

        # Check alert threshold
        self._check_alert_threshold(service, operation, record)

        return record

    def record_success(self, service: str, operation: str) -> None:
        """Record a successful operation — resets circuit breaker."""
        breaker_key = f"{service}.{operation}"
        self._circuit_breakers[breaker_key].record_success()

    def is_circuit_open(self, service: str, operation: str) -> bool:
        """Check if the circuit breaker is open for an operation."""
        breaker_key = f"{service}.{operation}"
        return self._circuit_breakers[breaker_key].is_open

    def _check_alert_threshold(self, service: str, operation: str, record: ErrorRecord) -> None:
        """Check if error rate exceeds alert threshold."""
        now = time.time()
        recent_errors = sum(1 for t in self._error_rate if now - t < 60)

        if recent_errors >= self.ALERT_THRESHOLD:
            if service in self._service_health:
                self._service_health[service]["status"] = "degraded"
            logger.critical(
                f"ALERT: Error rate threshold exceeded ({recent_errors}/min) "
                f"| service={service} | operation={operation} "
                f"| latest: {record.message[:100]}"
            )
            metrics.increment("error_alerts_triggered", labels={"service": service})

    def suppress(self, fingerprint: str) -> None:
        """Suppress a known error by fingerprint (stops alerting)."""
        self._suppressed.add(fingerprint)

    def resolve(self, fingerprint: str) -> bool:
        """Mark an error as resolved."""
        record = self._errors.get(fingerprint)
        if record:
            record.resolved = True
            self._suppressed.discard(fingerprint)
            return True
        return False

    # -- Queries & Reports -------------------------------------------------

    def get_error(self, fingerprint: str) -> Optional[ErrorRecord]:
        """Get a specific error by fingerprint."""
        return self._errors.get(fingerprint)

    def get_errors(
        self,
        service: Optional[str] = None,
        category: Optional[ErrorCategory] = None,
        severity: Optional[ErrorSeverity] = None,
        resolved: Optional[bool] = None,
        limit: int = 50,
    ) -> list[dict]:
        """Query errors with optional filters."""
        results = list(self._errors.values())

        if service:
            results = [r for r in results if r.service == service]
        if category:
            results = [r for r in results if r.category == category]
        if severity:
            results = [r for r in results if r.severity == severity]
        if resolved is not None:
            results = [r for r in results if r.resolved == resolved]

        # Sort by severity (critical first), then occurrence count
        severity_order = {
            ErrorSeverity.CRITICAL: 0, ErrorSeverity.HIGH: 1,
            ErrorSeverity.MEDIUM: 2, ErrorSeverity.LOW: 3, ErrorSeverity.WARNING: 4,
        }
        results.sort(key=lambda r: (severity_order.get(r.severity, 5), -r.occurrence_count))

        return [r.to_dict() for r in results[:limit]]

    def get_report(self) -> dict:
        """Generate a comprehensive diagnostics report."""
        now = time.time()
        errors_last_hour = sum(1 for t in self._error_rate if now - t < 3600)
        errors_last_minute = sum(1 for t in self._error_rate if now - t < 60)

        by_severity = defaultdict(int)
        by_category = defaultdict(int)
        by_service = defaultdict(int)
        unresolved = 0

        for record in self._errors.values():
            by_severity[record.severity.value] += record.occurrence_count
            by_category[record.category.value] += record.occurrence_count
            by_service[record.service] += record.occurrence_count
            if not record.resolved:
                unresolved += 1

        # Find top offenders
        top_errors = sorted(
            self._errors.values(),
            key=lambda r: r.occurrence_count,
            reverse=True,
        )[:10]

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "uptime_seconds": round(now - self._started_at),
            "summary": {
                "total_unique_errors": len(self._errors),
                "total_occurrences": sum(r.occurrence_count for r in self._errors.values()),
                "unresolved": unresolved,
                "errors_last_minute": errors_last_minute,
                "errors_last_hour": errors_last_hour,
                "alert_status": "alerting" if errors_last_minute >= self.ALERT_THRESHOLD else "normal",
            },
            "by_severity": dict(by_severity),
            "by_category": dict(by_category),
            "by_service": dict(by_service),
            "circuit_breakers": {
                key: {"state": cb.state, "failures": cb._failure_count}
                for key, cb in self._circuit_breakers.items()
                if cb._failure_count > 0
            },
            "service_health": dict(self._service_health),
            "top_errors": [e.to_dict() for e in top_errors],
        }

    def health_check(self) -> dict:
        """Quick health check suitable for monitoring endpoints."""
        now = time.time()
        errors_last_minute = sum(1 for t in self._error_rate if now - t < 60)
        critical_count = sum(
            1 for r in self._errors.values()
            if r.severity == ErrorSeverity.CRITICAL and not r.resolved
        )
        open_breakers = sum(
            1 for cb in self._circuit_breakers.values()
            if cb.state == "open"
        )

        status = "healthy"
        if critical_count > 0 or open_breakers > 0:
            status = "critical"
        elif errors_last_minute >= self.ALERT_THRESHOLD:
            status = "degraded"

        return {
            "status": status,
            "errors_per_minute": errors_last_minute,
            "critical_unresolved": critical_count,
            "open_circuit_breakers": open_breakers,
            "unique_errors": len(self._errors),
        }

    def clear(self) -> None:
        """Clear all tracked errors. Use for testing only."""
        self._errors.clear()
        self._recent.clear()
        self._error_rate.clear()
        self._circuit_breakers.clear()
        self._service_health.clear()


# ═══════════════════════════════════════════════════════════════════════════
# DECORATOR — auto-tracking for async functions
# ═══════════════════════════════════════════════════════════════════════════

def track_error(operation: str, service: str = ""):
    """
    Decorator that automatically registers errors in the ErrorRegistry.

    Usage:
        @track_error("commerce.record_payment")
        async def record_payment(self, payment):
            ...

        @track_error("capture", service="x402")
        async def capture(self, ...):
            ...
    """
    def decorator(fn: Callable) -> Callable:
        _service = service or operation.split(".")[0] if "." in operation else "unknown"
        _operation = operation.split(".")[-1] if "." in operation else operation

        @wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Check circuit breaker
            if error_registry.is_circuit_open(_service, _operation):
                logger.warning(f"Circuit breaker OPEN for {_service}.{_operation} — skipping")
                raise RuntimeError(
                    f"Circuit breaker open for {_service}.{_operation}. "
                    f"Too many recent failures. Will auto-retry in 30s."
                )

            try:
                result = await fn(*args, **kwargs)
                error_registry.record_success(_service, _operation)
                return result
            except Exception as e:
                # Extract context from kwargs if available
                context = {}
                if "body" in kwargs and hasattr(kwargs["body"], "model_dump"):
                    try:
                        context["request_body_type"] = type(kwargs["body"]).__name__
                    except Exception:
                        pass

                error_registry.register(
                    error=e,
                    service=_service,
                    operation=_operation,
                    context=context,
                )
                raise  # Re-raise — the decorator only tracks, doesn't swallow

        return wrapper
    return decorator


# ═══════════════════════════════════════════════════════════════════════════
# SINGLETON INSTANCE
# ═══════════════════════════════════════════════════════════════════════════

error_registry = ErrorRegistry()
