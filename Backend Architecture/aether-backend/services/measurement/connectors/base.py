"""BaseConnector ABC — interface for all measurement connectors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class SyncResult:
    connector_id: str
    connector_type: str
    spend_records_written: int
    conversion_records_written: int
    touchpoint_records_written: int
    errors: list[str] = field(default_factory=list)
    cursor_state: dict[str, Any] = field(default_factory=dict)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


@dataclass
class ConnectorHealth:
    connector_id: str
    connector_type: str
    healthy: bool
    status_message: str
    last_success_at: Optional[datetime] = None
    lag_minutes: Optional[int] = None


class BaseConnector(ABC):
    """Abstract base for all measurement connectors.

    Connectors are responsible for:
    - Fetching spend data from ad platforms or commerce sources
    - Writing spend records to SpendRepository (idempotent via idempotency_key)
    - Writing conversion records to ConversionRepository (idempotent via dedup_key)
    - Maintaining a durable cursor in ConnectorRepository.cursor_state
    - Reporting health status

    Connectors MUST NOT:
    - Store any state in instance variables beyond the lifecycle of a single sync
    - Use in-memory structures as durable stores
    - Silently truncate data — if pagination is needed, paginate
    """

    connector_type: str = "base"

    def __init__(
        self,
        connector_id: str,
        tenant_id: str,
        config: dict[str, Any],
        cursor_state: dict[str, Any],
    ) -> None:
        self.connector_id = connector_id
        self.tenant_id = tenant_id
        self._config = config
        self._cursor_state = cursor_state

    @abstractmethod
    async def sync_incremental(self, cursor: dict[str, Any]) -> SyncResult:
        """Fetch data since the cursor and write to canonical stores.

        Args:
            cursor: The last-known sync cursor dict from ConnectorRepository.

        Returns:
            SyncResult with updated cursor_state for persistence.
        """

    @abstractmethod
    async def backfill(self, start: datetime, end: datetime) -> SyncResult:
        """Fetch all data for a historical time range.

        Idempotency is guaranteed by spend_records.idempotency_key ON CONFLICT DO UPDATE.
        """

    @abstractmethod
    async def health_check(self) -> ConnectorHealth:
        """Verify connectivity and credential validity."""

    @abstractmethod
    async def validate_credentials(self) -> bool:
        """Return True if credentials are valid, False otherwise."""

    def _make_spend_idem_key(self, *parts: str) -> str:
        import hashlib
        return hashlib.sha256(
            ":".join([self.tenant_id, self.connector_type, *parts]).encode()
        ).hexdigest()

    def _sync_result(
        self,
        *,
        spend_records_written: int = 0,
        conversion_records_written: int = 0,
        touchpoint_records_written: int = 0,
        errors: Optional[list[str]] = None,
        cursor_state: Optional[dict[str, Any]] = None,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
    ) -> SyncResult:
        """Build a contract-complete result for connectors with provider APIs."""
        return SyncResult(
            connector_id=self.connector_id,
            connector_type=self.connector_type,
            spend_records_written=spend_records_written,
            conversion_records_written=conversion_records_written,
            touchpoint_records_written=touchpoint_records_written,
            errors=errors or [],
            cursor_state=cursor_state or {},
            started_at=started_at,
            completed_at=completed_at,
        )

    def _health(self, healthy: bool, message: str) -> ConnectorHealth:
        """Build a truthful, connector-scoped health observation."""
        return ConnectorHealth(
            connector_id=self.connector_id,
            connector_type=self.connector_type,
            healthy=healthy,
            status_message=message,
        )
