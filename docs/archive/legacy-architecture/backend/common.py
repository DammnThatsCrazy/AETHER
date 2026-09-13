"""
Aether Shared — @aether/common
Error classes, response formatters, validation schemas, pagination helpers, date utilities.
Used by ALL services.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from typing import Any, Generic, Optional, TypeVar

# ═══════════════════════════════════════════════════════════════════════════
# ERROR CLASSES
# ═══════════════════════════════════════════════════════════════════════════

class ErrorCode(IntEnum):
    BAD_REQUEST = 400
    UNAUTHORIZED = 401
    FORBIDDEN = 403
    NOT_FOUND = 404
    CONFLICT = 409
    RATE_LIMITED = 429
    INTERNAL = 500
    SERVICE_UNAVAILABLE = 503


class AetherError(Exception):
    """Base error — all service errors inherit from this."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        details: Optional[dict] = None,
        request_id: Optional[str] = None,
    ):
        self.code = code
        self.message = message
        self.details = details or {}
        self.request_id = request_id or str(uuid.uuid4())
        super().__init__(message)

    def to_dict(self) -> dict:
        """Consistent error format per spec:
        { error: { code, message, details, request_id } }
        """
        return {
            "error": {
                "code": self.code.value,
                "message": self.message,
                "details": self.details,
                "request_id": self.request_id,
            }
        }


class BadRequestError(AetherError):
    def __init__(self, message: str = "Bad request", **kwargs):
        super().__init__(ErrorCode.BAD_REQUEST, message, **kwargs)


class UnauthorizedError(AetherError):
    def __init__(self, message: str = "Unauthorized", **kwargs):
        super().__init__(ErrorCode.UNAUTHORIZED, message, **kwargs)


class ForbiddenError(AetherError):
    def __init__(self, message: str = "Forbidden", **kwargs):
        super().__init__(ErrorCode.FORBIDDEN, message, **kwargs)


class NotFoundError(AetherError):
    def __init__(self, resource: str = "Resource", **kwargs):
        super().__init__(ErrorCode.NOT_FOUND, f"{resource} not found", **kwargs)


class ConflictError(AetherError):
    def __init__(self, message: str = "Conflict", **kwargs):
        super().__init__(ErrorCode.CONFLICT, message, **kwargs)


class RateLimitedError(AetherError):
    def __init__(self, retry_after: int = 60, **kwargs):
        super().__init__(
            ErrorCode.RATE_LIMITED,
            "Rate limit exceeded",
            details={"retry_after_seconds": retry_after},
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
        return {
            "data": self.data,
            "meta": {
                **self.meta,
                "request_id": self.request_id,
                "timestamp": utc_now().isoformat(),
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

    def __post_init__(self):
        self.limit = min(max(self.limit, 1), 200)


@dataclass
class OffsetPagination:
    """Offset-based pagination for admin lists."""
    offset: int = 0
    limit: int = 50
    sort_by: str = "created_at"
    sort_order: str = "desc"  # "asc" or "desc"

    def __post_init__(self):
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


def validate_required(data: dict, required_fields: list[str]):
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
