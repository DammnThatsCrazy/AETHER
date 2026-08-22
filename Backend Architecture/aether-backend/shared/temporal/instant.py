"""Strict canonical-instant parsing and formatting.

Platform invariant: all exact moments are stored and ordered as UTC instants.
This module is the ONLY sanctioned parser for exact instants — it rejects
timezone-naive values instead of silently assuming UTC (the legacy
``shared.common.common.parse_iso`` accepts naive strings and remains only for
compatibility call sites).

Every rejection raises :class:`TemporalError` carrying one of the stable
reason codes in :data:`TEMPORAL_REASON_CODES` so ingestion, diagnostics, and
metrics all speak the same vocabulary. The TS twin of the vocabulary lives in
``packages/shared/temporal.ts`` (parity-tested).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

TemporalReasonCode = Literal[
    "timestamp_invalid",
    "timestamp_naive",
    "timestamp_future",
    "timestamp_too_old",
    "timezone_invalid",
    "timezone_offset_mismatch",
    "local_time_ambiguous",
    "local_time_nonexistent",
    "temporal_authority_missing",
    "temporal_policy_violation",
    "temporal_provenance_missing",
    "clock_skew_warning",
    "delivery_lag_warning",
]

# Parallel const for iteration/validation (mirrors `temporalReasonCodes` in TS).
TEMPORAL_REASON_CODES: tuple[str, ...] = (
    "timestamp_invalid",
    "timestamp_naive",
    "timestamp_future",
    "timestamp_too_old",
    "timezone_invalid",
    "timezone_offset_mismatch",
    "local_time_ambiguous",
    "local_time_nonexistent",
    "temporal_authority_missing",
    "temporal_policy_violation",
    "temporal_provenance_missing",
    "clock_skew_warning",
    "delivery_lag_warning",
)

# Offsets beyond these bounds do not exist in the IANA database.
_MIN_OFFSET_MINUTES = -12 * 60
_MAX_OFFSET_MINUTES = 14 * 60


class TemporalError(ValueError):
    """A temporal value violated the canonical contract.

    ``reason_code`` is always one of :data:`TEMPORAL_REASON_CODES` so callers
    can classify without string-matching messages.
    """

    def __init__(self, reason_code: str, message: str) -> None:
        if reason_code not in TEMPORAL_REASON_CODES:
            raise ValueError(f"unknown temporal reason code: {reason_code!r}")
        super().__init__(message)
        self.reason_code = reason_code


def parse_instant_strict(value: str) -> datetime:
    """Parse an ISO-8601 exact instant, rejecting naive/malformed values.

    Accepts ``Z`` or an explicit numeric offset; normalizes to UTC. Never
    attaches an assumed timezone to a naive value — that is a policy decision
    the caller must make explicitly (and record as provenance).
    """
    if not isinstance(value, str) or not value.strip():
        raise TemporalError("timestamp_invalid", f"empty or non-string timestamp: {value!r}")
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00").replace("z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise TemporalError("timestamp_invalid", f"unparseable ISO-8601 timestamp: {value!r}") from exc
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        raise TemporalError(
            "timestamp_naive",
            f"timezone-naive timestamp rejected (no offset/Z): {value!r}",
        )
    offset_minutes = int(parsed.utcoffset().total_seconds() // 60)  # type: ignore[union-attr]
    if not (_MIN_OFFSET_MINUTES <= offset_minutes <= _MAX_OFFSET_MINUTES):
        raise TemporalError(
            "timezone_invalid",
            f"UTC offset {offset_minutes:+d} minutes outside valid range: {value!r}",
        )
    return parsed.astimezone(timezone.utc)


def ensure_aware_utc(dt: datetime) -> datetime:
    """Require a tz-aware datetime; return it normalized to UTC."""
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise TemporalError("timestamp_naive", "timezone-naive datetime rejected")
    return dt.astimezone(timezone.utc)


def to_iso_utc(dt: datetime) -> str:
    """Serialize an aware datetime in the canonical UTC ``Z`` form."""
    return ensure_aware_utc(dt).isoformat().replace("+00:00", "Z")


def try_parse_instant(value: str) -> tuple[Optional[datetime], Optional[str]]:
    """Non-raising variant: returns ``(instant, None)`` or ``(None, reason_code)``."""
    try:
        return parse_instant_strict(value), None
    except TemporalError as exc:
        return None, exc.reason_code


def coerce_utc_lenient(value: object) -> Optional[datetime]:
    """Lenient event-time coercion: parse an ISO-8601 string (or accept a
    ``datetime``), ASSUMING UTC for a timezone-naive value, and return ``None``
    for ``None`` / empty / unparseable input (never raising).

    This is the sanctioned, single home for the "assume UTC on a naive instant"
    policy that :func:`parse_instant_strict` deliberately refuses to apply
    implicitly. It lives in the kernel because the kernel is the only module
    permitted to attach a timezone (temporal-integrity gate). Callers — the
    attribution event-time helpers (``shared.common.common.parse_event_time``)
    and the campaign freshness watermark
    (``services.campaign.exploration._max_occurred_at``) — mirror the lenient
    acceptance rule that ``BaseEvent.validate_timestamp`` applies at ingestion,
    so downstream parsing accepts exactly what was accepted upstream instead of
    silently diverging. Prefer :func:`parse_instant_strict` /
    :func:`try_parse_instant` for any NEW path that can require an explicit
    offset; this helper exists only for parity with already-accepted data.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


__all__ = [
    "TemporalReasonCode",
    "TEMPORAL_REASON_CODES",
    "TemporalError",
    "parse_instant_strict",
    "ensure_aware_utc",
    "to_iso_utc",
    "try_parse_instant",
    "coerce_utc_lenient",
]
