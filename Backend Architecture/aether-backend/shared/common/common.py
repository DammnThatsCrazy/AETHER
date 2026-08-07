"""
Aether Shared — @aether/common
Error classes, response formatters, validation schemas, pagination helpers, date utilities.
Used by ALL services.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Generic, Optional, TypeVar
from dataclasses import dataclass, field
from enum import IntEnum


# ═══════════════════════════════════════════════════════════════════════════
# ERROR CLASSES
# ═══════════════════════════════════════════════════════════════════════════

class ErrorCode(IntEnum):
    BAD_REQUEST = 400
    UNAUTHORIZED = 401
    FORBIDDEN = 403
    NOT_FOUND = 404
    CONFLICT = 409
    UNPROCESSABLE = 422
    RATE_LIMITED = 429
    INTERNAL = 500
    SERVICE_UNAVAILABLE = 503


# Base URI for Problem-Details `type` members. Slugs are stable API contract;
# the URIs are identifiers, not required to dereference.
PROBLEM_TYPE_BASE = "https://errors.aether.dev/"

# Statuses that are safe to retry by default. 4xx (except 429) means the
# request itself is wrong and retrying is pointless.
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


def _stable_code(cls_name: str) -> str:
    """BadRequestError -> BAD_REQUEST (stable machine-readable string code)."""
    import re as _re

    base = cls_name.removesuffix("Error") or "Aether"
    return _re.sub(r"(?<!^)(?=[A-Z])", "_", base).upper()


def _title_from_code(code: str) -> str:
    return code.replace("_", " ").title()


class AetherError(Exception):
    """Base error — all service errors inherit from this.

    ``to_dict()`` emits an RFC-7807-compatible Problem Details body
    (``type``/``title``/``status``/``code``/``detail``/``retryable`` plus
    correlation members) while retaining the legacy nested ``error`` object
    that existing clients read.
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        details: Optional[dict] = None,
        request_id: Optional[str] = None,
        retryable: Optional[bool] = None,
    ):
        self.code = code
        self.message = message
        self.details = details or {}
        self.request_id = request_id or str(uuid.uuid4())
        self.retryable = (
            retryable if retryable is not None else code.value in _RETRYABLE_STATUSES
        )
        super().__init__(message)

    def to_dict(self) -> dict:
        stable = _stable_code(type(self).__name__)
        body = {
            "type": f"{PROBLEM_TYPE_BASE}{stable.lower().replace('_', '-')}",
            "title": _title_from_code(stable),
            "status": self.code.value,
            "code": stable,
            "detail": self.message,
            "message": self.message,
            "request_id": self.request_id,
            "correlation_id": self.request_id,
            "retryable": self.retryable,
            # Legacy nested envelope — existing clients read error.code/message.
            "error": {
                "code": self.code.value,
                "message": self.message,
                "details": self.details,
                "request_id": self.request_id,
            },
        }
        if self.details:
            body["errors"] = [self.details] if not isinstance(self.details, list) else self.details
        return body


def problem_dict(
    status: int,
    title: str,
    detail: str,
    *,
    code: str,
    type_slug: Optional[str] = None,
    retryable: Optional[bool] = None,
    request_id: str = "",
    extensions: Optional[dict] = None,
) -> dict:
    """Build a canonical Problem-Details JSON body (pure dict, no framework)."""
    rid = request_id or str(uuid.uuid4())
    slug = type_slug or code.lower().replace("_", "-")
    body = {
        "type": f"{PROBLEM_TYPE_BASE}{slug}",
        "title": title,
        "status": status,
        "code": code,
        "detail": detail,
        "message": detail,
        "request_id": rid,
        "correlation_id": rid,
        "retryable": retryable if retryable is not None else status in _RETRYABLE_STATUSES,
        "error": {"code": status, "message": detail, "details": extensions or {}, "request_id": rid},
    }
    if extensions:
        body.update(extensions)
    return body


def problem_response(
    status: int,
    title: str,
    detail: str,
    *,
    code: str,
    type_slug: Optional[str] = None,
    retryable: Optional[bool] = None,
    request_id: str = "",
    extensions: Optional[dict] = None,
    headers: Optional[dict] = None,
):
    """Canonical Problem-Details JSONResponse for middleware/route early exits."""
    from starlette.responses import JSONResponse  # local import: keep module framework-free

    return JSONResponse(
        status_code=status,
        content=problem_dict(
            status,
            title,
            detail,
            code=code,
            type_slug=type_slug,
            retryable=retryable,
            request_id=request_id,
            extensions=extensions,
        ),
        headers=headers,
    )


class BadRequestError(AetherError):
    def __init__(self, message: str = "Bad request", **kwargs: Any):
        super().__init__(ErrorCode.BAD_REQUEST, message, **kwargs)


class UnauthorizedError(AetherError):
    def __init__(self, message: str = "Unauthorized", **kwargs: Any):
        super().__init__(ErrorCode.UNAUTHORIZED, message, **kwargs)


class ForbiddenError(AetherError):
    def __init__(self, message: str = "Forbidden", **kwargs: Any):
        super().__init__(ErrorCode.FORBIDDEN, message, **kwargs)


class NotFoundError(AetherError):
    def __init__(self, resource: str = "Resource", **kwargs: Any):
        super().__init__(ErrorCode.NOT_FOUND, f"{resource} not found", **kwargs)


class ConflictError(AetherError):
    def __init__(self, message: str = "Conflict", **kwargs: Any):
        super().__init__(ErrorCode.CONFLICT, message, **kwargs)


class RateLimitedError(AetherError):
    def __init__(self, retry_after: int = 60, **kwargs: Any):
        super().__init__(
            ErrorCode.RATE_LIMITED,
            "Rate limit exceeded",
            details={"retry_after_seconds": retry_after},
            **kwargs,
        )


class ServiceUnavailableError(AetherError):
    def __init__(self, service: str = "Service", **kwargs: Any):
        super().__init__(
            ErrorCode.SERVICE_UNAVAILABLE,
            f"{service} is temporarily unavailable",
            **kwargs,
        )


# ═══════════════════════════════════════════════════════════════════════════
# RESPONSE FORMATTERS
# ═══════════════════════════════════════════════════════════════════════════

T = TypeVar("T")


@dataclass
class APIResponse(Generic[T]):
    """Standard success response wrapper."""
    data: T
    meta: dict = field(default_factory=dict)
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict:
        ts = utc_now().isoformat()
        return {
            "data": self.data,
            "status": "success",
            "timestamp": ts,
            "meta": {
                **self.meta,
                "request_id": self.request_id,
                "timestamp": ts,
            },
        }


@dataclass
class PaginatedResponse(Generic[T]):
    """Paginated response for list endpoints."""
    data: list[T]
    pagination: PaginationMeta
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict:
        return {
            "data": self.data,
            "pagination": self.pagination.to_dict(),
            "meta": {
                "request_id": self.request_id,
                "timestamp": utc_now().isoformat(),
            },
        }


# ═══════════════════════════════════════════════════════════════════════════
# PAGINATION
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class CursorPagination:
    """Cursor-based pagination for event streams."""
    cursor: Optional[str] = None
    limit: int = 50

    def __post_init__(self) -> None:
        self.limit = min(max(self.limit, 1), 200)


@dataclass
class OffsetPagination:
    """Offset-based pagination for admin lists."""
    offset: int = 0
    limit: int = 50
    sort_by: str = "created_at"
    sort_order: str = "desc"

    def __post_init__(self) -> None:
        self.limit = min(max(self.limit, 1), 200)
        self.offset = max(self.offset, 0)


@dataclass
class PaginationMeta:
    total: Optional[int] = None
    limit: int = 50
    offset: Optional[int] = None
    cursor: Optional[str] = None
    next_cursor: Optional[str] = None
    has_more: bool = False

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"limit": self.limit, "has_more": self.has_more}
        if self.total is not None:
            d["total"] = self.total
        if self.offset is not None:
            d["offset"] = self.offset
        if self.cursor is not None:
            d["cursor"] = self.cursor
        if self.next_cursor is not None:
            d["next_cursor"] = self.next_cursor
        return d


# ═══════════════════════════════════════════════════════════════════════════
# VALIDATION HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def validate_uuid(value: str, field_name: str = "id") -> str:
    try:
        uuid.UUID(value)
        return value
    except ValueError:
        raise BadRequestError(f"Invalid UUID for {field_name}: {value}")


def validate_required(data: dict, required_fields: list[str]) -> None:
    missing = [f for f in required_fields if f not in data or data[f] is None]
    if missing:
        raise BadRequestError(
            f"Missing required fields: {', '.join(missing)}",
            details={"missing_fields": missing},
        )


def validate_enum(value: str, allowed: list[str], field_name: str = "field") -> str:
    if value not in allowed:
        raise BadRequestError(
            f"Invalid value for {field_name}: '{value}'. Allowed: {allowed}"
        )
    return value


def validate_string_length(
    value: str, field_name: str, min_len: int = 1, max_len: int = 1000
) -> str:
    if len(value) < min_len or len(value) > max_len:
        raise BadRequestError(
            f"{field_name} must be between {min_len} and {max_len} characters"
        )
    return value


# ═══════════════════════════════════════════════════════════════════════════
# DATE UTILITIES
# ═══════════════════════════════════════════════════════════════════════════

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        raise BadRequestError(f"Invalid ISO date: {value}")


def to_iso(dt: datetime) -> str:
    return dt.isoformat()


def parse_event_time(value: Any) -> Optional[datetime]:
    """Parse a canonical event-time value into an aware UTC ``datetime``, or
    ``None`` if it cannot be parsed.

    This is the single shared parser for the event-time rule behind audit
    finding H: attribution must REFUSE on an invalid/absent conversion
    timestamp rather than silently substituting ``now()``. It mirrors the
    accept/reject rule enforced by ``BaseEvent.validate_timestamp``
    (``services/ingestion/batch.py``) — the same
    ``datetime.fromisoformat(value.replace("Z", "+00:00"))`` call — and does
    not invent any additional accepted formats.

    Accepts:
      - a ``datetime`` instance: returned unchanged if timezone-aware, or
        stamped with ``tzinfo=UTC`` if naive. A naive value is ASSUMED to
        already be UTC; it is never reinterpreted via an inferred local zone.
      - anything else (typically a ``str``): stringified and parsed with
        ``datetime.fromisoformat`` (after mapping a trailing ``Z`` to
        ``+00:00``), then normalized naive -> UTC the same way.

    Returns ``None`` (never raises) for:
      - ``None``
      - ``""`` (empty string)
      - any value that does not parse as ISO-8601 (e.g. ``"not-a-date"``)

    Note for callers: this function cannot distinguish a time FIELD that is
    ABSENT (e.g. a missing dict key) from one that is PRESENT but invalid —
    both a missing value and an unparseable one are the caller's problem to
    detect *before* calling this helper. Callers that must tell "no time
    supplied, fall back to real-time now()" apart from "a time was supplied
    but is corrupt, refuse" (e.g. ``services.attribution.resolver``) need to
    perform that presence check themselves and only call this helper once
    they know a value is present.
    """
    # Delegates to the temporal kernel — the sanctioned owner of timezone
    # attachment. ``coerce_utc_lenient`` carries the exact assume-UTC-on-naive
    # rule this helper used to inline, kept byte-for-byte for behavior parity
    # while keeping raw tzinfo attachment out of this non-kernel module.
    from shared.temporal.instant import coerce_utc_lenient

    return coerce_utc_lenient(value)
