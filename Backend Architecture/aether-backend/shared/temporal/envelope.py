"""Canonical temporal envelopes.

Two envelopes live here:

- :class:`EventTemporalEnvelope` — the ingestion-time record of when an event
  occurred / was sent / was received, with source timezone provenance, skew,
  lag, and a classified temporal state. Computed server-side; SDK fields are
  optional evidence, never trusted authority.
- :class:`TemporalEnvelope` — the Python mirror of the bitemporal graph
  envelope in ``packages/shared/graph-contract.ts`` (``TemporalEnvelope``),
  closing the parity gap documented in ``UNIVERSAL_GRAPH_CONTRACT.md``.

Vocabulary consts are parity-tested against ``packages/shared/temporal.ts``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

TemporalState = Literal[
    "valid",
    "normalized",
    "legacy_inferred",
    "skewed",
    "late",
    "future",
    "ambiguous",
    "timezone_unknown",
    "authority_missing",
    "invalid",
    "quarantined",
]

TEMPORAL_STATES: tuple[str, ...] = (
    "valid",
    "normalized",
    "legacy_inferred",
    "skewed",
    "late",
    "future",
    "ambiguous",
    "timezone_unknown",
    "authority_missing",
    "invalid",
    "quarantined",
)

TimeZoneSource = Literal[
    "device",
    "user_preference",
    "provider",
    "tenant",
    "geoip",
    "import_mapping",
    "server",
    "unknown",
]

TIME_ZONE_SOURCES: tuple[str, ...] = (
    "device",
    "user_preference",
    "provider",
    "tenant",
    "geoip",
    "import_mapping",
    "server",
    "unknown",
)

ClockSource = Literal["device", "provider", "server", "blockchain", "import"]

CLOCK_SOURCES: tuple[str, ...] = (
    "device",
    "provider",
    "server",
    "blockchain",
    "import",
)

TemporalPrecision = Literal["second", "millisecond", "microsecond", "nanosecond"]

TEMPORAL_PRECISIONS: tuple[str, ...] = (
    "second",
    "millisecond",
    "microsecond",
    "nanosecond",
)


class EventTemporalEnvelope(BaseModel):
    """Server-computed temporal facts for one accepted event.

    ``occurred_at``/``received_at`` are canonical UTC instants. Source fields
    preserve the client's claims as evidence (never re-used as another
    viewer's display authority). Persisted additively alongside Bronze rows.
    """

    model_config = ConfigDict(extra="forbid")

    occurred_at: datetime
    sent_at: Optional[datetime] = None
    received_at: datetime

    source_timestamp_original: Optional[str] = None
    source_time_zone: Optional[str] = None
    source_utc_offset_minutes: Optional[int] = None
    source_locale: Optional[str] = None

    time_zone_source: TimeZoneSource = "unknown"
    clock_source: ClockSource = "device"
    precision: TemporalPrecision = "millisecond"

    clock_skew_ms: Optional[int] = None
    delivery_lag_ms: Optional[int] = None

    temporal_state: TemporalState = "valid"
    reason_codes: list[str] = []

    temporal_policy_version: Optional[str] = None
    tzdb_version: Optional[str] = None

    def model_dump_bronze(self) -> dict:
        """JSON-safe dict for additive Bronze persistence."""
        return self.model_dump(mode="json", exclude_none=True)


class TemporalEnvelope(BaseModel):
    """Bitemporal time envelope — Python mirror of the TS graph contract.

    Field-for-field twin of ``TemporalEnvelope`` in
    ``packages/shared/graph-contract.ts`` (parity-tested). ``lifecycle_state``
    values are owned by the graph contract's ``LifecycleState``.
    """

    model_config = ConfigDict(extra="forbid")

    event_time: str
    observed_time: str
    ingestion_time: Optional[str] = None
    processed_time: Optional[str] = None
    graph_mutation_time: Optional[str] = None
    first_seen: str
    last_seen: str
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    recorded_at: Optional[str] = None
    superseded_at: Optional[str] = None
    age_days: Optional[float] = None
    recency_score: Optional[float] = None
    lifecycle_state: str


__all__ = [
    "TemporalState",
    "TEMPORAL_STATES",
    "TimeZoneSource",
    "TIME_ZONE_SOURCES",
    "ClockSource",
    "CLOCK_SOURCES",
    "TemporalPrecision",
    "TEMPORAL_PRECISIONS",
    "EventTemporalEnvelope",
    "TemporalEnvelope",
]
