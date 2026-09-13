"""Canonical adapter result (§17) and bridge mappers.

:class:`AdapterResult` is the single shape every capability adapter returns in
the target architecture. This wave is purely additive, so the value here is the
type plus **bridge mappers** that lift the existing result types
(``ProviderResult``, ``ConnectionTestResult``, ``SyncResult``) into the
canonical result *without changing the originals*. Later waves can migrate call
sites onto :class:`AdapterResult` incrementally.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict

from services.integrations.connectors.base import (
    ConnectionTestResult,
    ConnectorSyncStatus,
    SyncResult,
)
from shared.providers.base import ProviderResult

T = TypeVar("T")


class AdapterStatus(str, Enum):
    """Canonical outcome classification for an adapter call."""

    OK = "ok"
    NOT_SUPPORTED = "not_supported"
    RETRYABLE_ERROR = "retryable_error"
    PERMANENT_ERROR = "permanent_error"
    RATE_LIMITED = "rate_limited"
    UNAUTHORIZED = "unauthorized"


class RateLimitInfo(BaseModel):
    """Provider rate-limit signal. Times are epoch-millis to avoid tz debt."""

    model_config = ConfigDict(frozen=True)

    limit: Optional[int] = None
    remaining: Optional[int] = None
    reset_epoch_ms: Optional[int] = None
    retry_after_ms: Optional[float] = None


class AdapterResult(BaseModel, Generic[T]):
    """Canonical, typed result of one adapter operation."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    success: bool
    status: AdapterStatus
    error_code: Optional[str] = None
    retryable: bool = False
    latency_ms: Optional[float] = None
    rate_limit: Optional[RateLimitInfo] = None
    provider_request_id: Optional[str] = None
    correlation_id: Optional[str] = None
    account: Optional[dict[str, Any]] = None
    data: Optional[T] = None

    # ── Constructors ───────────────────────────────────────────────────────

    @classmethod
    def ok(
        cls,
        data: Optional[T] = None,
        *,
        latency_ms: Optional[float] = None,
        provider_request_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        account: Optional[dict[str, Any]] = None,
        rate_limit: Optional[RateLimitInfo] = None,
    ) -> "AdapterResult[T]":
        return cls(
            success=True,
            status=AdapterStatus.OK,
            data=data,
            latency_ms=latency_ms,
            provider_request_id=provider_request_id,
            correlation_id=correlation_id,
            account=account,
            rate_limit=rate_limit,
        )

    @classmethod
    def not_supported(cls, op: str) -> "AdapterResult[T]":
        """Result for an operation the adapter does not implement."""
        return cls(
            success=False,
            status=AdapterStatus.NOT_SUPPORTED,
            error_code=f"not_supported:{op}",
            retryable=False,
        )


# ── Bridge mappers (adapters, not rewrites) ────────────────────────────────


def from_provider_result(pr: ProviderResult) -> AdapterResult[Any]:
    """Lift a :class:`ProviderResult` into an :class:`AdapterResult`.

    A ``ProviderResult`` carries no retry classification, so a failure is
    conservatively mapped to ``PERMANENT_ERROR`` (non-retryable). The original
    object is untouched.
    """
    if pr.success:
        return AdapterResult(
            success=True,
            status=AdapterStatus.OK,
            latency_ms=pr.latency_ms,
            provider_request_id=pr.provider_name or None,
            data=pr.data,
        )
    return AdapterResult(
        success=False,
        status=AdapterStatus.PERMANENT_ERROR,
        error_code=pr.error,
        retryable=False,
        latency_ms=pr.latency_ms,
        provider_request_id=pr.provider_name or None,
        data=pr.data,
    )


# ConnectionTestResult.status is a free string: "ok" | "ready" | "not_configured"
# | "disabled" | "error". Map the failure strings onto canonical statuses.
_CONNECTION_STATUS_MAP: dict[str, AdapterStatus] = {
    "not_configured": AdapterStatus.UNAUTHORIZED,
    "disabled": AdapterStatus.PERMANENT_ERROR,
    "error": AdapterStatus.RETRYABLE_ERROR,
}


def from_connection_test(t: ConnectionTestResult) -> AdapterResult[Any]:
    """Lift a :class:`ConnectionTestResult` into an :class:`AdapterResult`."""
    if t.ok:
        return AdapterResult(
            success=True,
            status=AdapterStatus.OK,
            data={"detail": t.detail, "status": t.status},
        )
    status = _CONNECTION_STATUS_MAP.get(t.status, AdapterStatus.PERMANENT_ERROR)
    return AdapterResult(
        success=False,
        status=status,
        error_code=t.status,
        retryable=status == AdapterStatus.RETRYABLE_ERROR,
        data={"detail": t.detail, "status": t.status},
    )


# SyncResult.status is a ConnectorSyncStatus literal. Classify each into the
# canonical outcome + retryability.
_SYNC_STATUS_MAP: dict[str, tuple[bool, AdapterStatus, bool]] = {
    # status -> (success, AdapterStatus, retryable)
    "healthy": (True, AdapterStatus.OK, False),
    "syncing": (True, AdapterStatus.OK, False),
    "never_synced": (True, AdapterStatus.OK, False),
    "degraded": (False, AdapterStatus.RETRYABLE_ERROR, True),
    "failed": (False, AdapterStatus.RETRYABLE_ERROR, True),
    "disabled": (False, AdapterStatus.PERMANENT_ERROR, False),
}


def from_sync_result(s: SyncResult) -> AdapterResult[Any]:
    """Lift a :class:`SyncResult` into an :class:`AdapterResult`."""
    sync_status: ConnectorSyncStatus = s.status
    success, status, retryable = _SYNC_STATUS_MAP.get(
        sync_status, (False, AdapterStatus.PERMANENT_ERROR, False)
    )
    return AdapterResult(
        success=success,
        status=status,
        error_code=None if success else str(sync_status),
        retryable=retryable,
        data={
            "events_ingested": s.events_ingested,
            "detail": s.detail,
            "sync_status": sync_status,
        },
    )


__all__ = [
    "AdapterResult",
    "AdapterStatus",
    "RateLimitInfo",
    "from_connection_test",
    "from_provider_result",
    "from_sync_result",
]
