"""Temporal enforcement for canonical ingestion (`/v1/batch`).

Computes the server-authoritative :class:`EventTemporalEnvelope` for every
event — strict instant parsing, IANA zone validation, zone/offset consistency,
clock skew and delivery lag against the generated per-family policy — and maps
the findings to a disposition through the mode ladder:

    off      → nothing runs (zero cost)
    shadow   → envelope + meters only; behavior unchanged
    warn     → shadow + reason surfaced on the event result
    enforce  → reject/quarantine dispositions are applied

Reason codes and meters are computed identically in every active mode, so
shadow telemetry directly predicts enforcement impact. Pure computation — no
I/O; callers pass ``received_at`` from their existing request scope.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from shared.temporal.authority import (
    classify_temporal_state,
    compute_clock_skew_ms,
    compute_delivery_lag_ms,
)
from shared.temporal.envelope import EventTemporalEnvelope
from shared.temporal.generated_policy import (
    TEMPORAL_DEFAULT_BOUNDS,
    TEMPORAL_FAMILY_BOUNDS,
    TEMPORAL_POLICY_VERSION,
    TEMPORAL_REASON_DISPOSITIONS,
)
from shared.temporal.instant import try_parse_instant
from shared.temporal.zones import is_valid_iana_zone, tzdb_version, zone_offset_consistent

# Disposition severity, mildest → harshest. The harshest triggered wins.
_DISPOSITION_ORDER = ("accept", "accept_with_warning", "quarantine", "reject")

_VALID_TZ_SOURCES = frozenset(
    ("device", "user_preference", "provider", "tenant", "geoip", "import_mapping", "server", "unknown")
)
_VALID_CLOCK_SOURCES = frozenset(("device", "provider", "server", "blockchain", "import"))


@dataclass
class TemporalDecision:
    """Outcome of temporal enforcement for one event."""

    envelope: Optional[EventTemporalEnvelope]
    disposition: str  # accept | accept_with_warning | quarantine | reject
    reason_codes: list[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return self.disposition in ("quarantine", "reject")


def _worst_disposition(reason_codes: list[str]) -> str:
    worst = "accept"
    for code in reason_codes:
        disposition = TEMPORAL_REASON_DISPOSITIONS.get(code, "accept_with_warning")
        if _DISPOSITION_ORDER.index(disposition) > _DISPOSITION_ORDER.index(worst):
            worst = disposition
    return worst


def enforce_temporal(
    *,
    event_timestamp: str,
    event_family: str,
    context_timezone: Optional[str],
    context_offset_minutes: Optional[int],
    context_tz_source: Optional[str],
    context_clock_source: Optional[str],
    context_locale: Optional[str],
    sent_at: Optional[str],
    received_at: datetime,
) -> TemporalDecision:
    """Classify one event's temporal facts against the generated policy."""

    bounds = TEMPORAL_FAMILY_BOUNDS.get(event_family, TEMPORAL_DEFAULT_BOUNDS)
    reason_codes: list[str] = []

    occurred_at, parse_reason = try_parse_instant(event_timestamp)
    if occurred_at is None:
        # Unparseable/naive: no envelope is computable; the disposition alone
        # decides (reject under enforce; recorded evidence otherwise).
        assert parse_reason is not None
        return TemporalDecision(
            envelope=None,
            disposition=TEMPORAL_REASON_DISPOSITIONS.get(parse_reason, "reject"),
            reason_codes=[parse_reason],
        )

    sent_instant = None
    if sent_at:
        sent_instant, _sent_reason = try_parse_instant(sent_at)
        # sentAt problems are batch-level; BatchRequest validation already
        # bounds the format. A naive sentAt simply yields no lag measurement.

    tz_known = bool(context_timezone)
    if context_timezone:
        if not is_valid_iana_zone(context_timezone):
            reason_codes.append("timezone_invalid")
            tz_known = False
        elif context_offset_minutes is not None and not zone_offset_consistent(
            context_timezone, occurred_at, context_offset_minutes
        ):
            reason_codes.append("timezone_offset_mismatch")

    clock_skew_ms = compute_clock_skew_ms(occurred_at, received_at)
    delivery_lag_ms = (
        compute_delivery_lag_ms(sent_instant, received_at) if sent_instant else None
    )

    state, classify_reasons = classify_temporal_state(
        clock_skew_ms=clock_skew_ms,
        delivery_lag_ms=delivery_lag_ms,
        max_future_skew_ms=bounds["maxFutureSkewMs"],
        warn_skew_ms=bounds["warnSkewMs"],
        max_lateness_ms=bounds["maxLatenessMs"],
        source_time_zone_known=tz_known,
    )
    reason_codes.extend(classify_reasons)

    if "timezone_invalid" in reason_codes or "timezone_offset_mismatch" in reason_codes:
        if state == "valid":
            state = "invalid"

    tz_source = context_tz_source if context_tz_source in _VALID_TZ_SOURCES else "unknown"
    clock_source = (
        context_clock_source if context_clock_source in _VALID_CLOCK_SOURCES else "device"
    )

    envelope = EventTemporalEnvelope(
        occurred_at=occurred_at,
        sent_at=sent_instant,
        received_at=received_at,
        source_timestamp_original=event_timestamp,
        source_time_zone=context_timezone if tz_known else None,
        source_utc_offset_minutes=context_offset_minutes,
        source_locale=context_locale,
        time_zone_source=tz_source,
        clock_source=clock_source,
        clock_skew_ms=clock_skew_ms,
        delivery_lag_ms=delivery_lag_ms,
        temporal_state=state,
        reason_codes=reason_codes,
        temporal_policy_version=TEMPORAL_POLICY_VERSION,
        tzdb_version=tzdb_version(),
    )
    return TemporalDecision(
        envelope=envelope,
        disposition=_worst_disposition(reason_codes),
        reason_codes=reason_codes,
    )


__all__ = ["TemporalDecision", "enforce_temporal"]
