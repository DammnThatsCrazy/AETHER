"""IANA timezone validation and offset facts.

Persistent calendar authority is always an IANA zone id (``America/New_York``),
never an abbreviation (``EST``) or a bare numeric offset — offsets are evidence
about one instant, not rules. ``zoneinfo`` is the only backing implementation.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from shared.temporal.instant import TemporalError, ensure_aware_utc


@lru_cache(maxsize=1)
def _known_zones() -> frozenset[str]:
    return frozenset(available_timezones())


@lru_cache(maxsize=512)
def _zone(zone_id: str) -> ZoneInfo:
    return ZoneInfo(zone_id)


def is_valid_iana_zone(zone_id: str) -> bool:
    """True only for a canonical IANA zone id (case-sensitive).

    Legacy top-level entries the tzdb still ships (``EST``, ``MST7MDT``,
    ``GMT``, ``Zulu``, …) are rejected as persistent calendar authorities —
    they are abbreviations/aliases, not region zones. ``UTC`` and any
    ``Area/Location`` id (including ``Etc/UTC``) are accepted.
    """
    if not isinstance(zone_id, str) or zone_id not in _known_zones():
        return False
    return zone_id == "UTC" or "/" in zone_id


def require_valid_zone(zone_id: str) -> ZoneInfo:
    """Return the ZoneInfo for ``zone_id`` or raise ``timezone_invalid``.

    Rejects abbreviations (``EST``/``PST``) and anything else absent from the
    IANA database, including empty strings.
    """
    if not is_valid_iana_zone(zone_id):
        raise TemporalError("timezone_invalid", f"not an IANA timezone id: {zone_id!r}")
    try:
        return _zone(zone_id)
    except ZoneInfoNotFoundError as exc:  # pragma: no cover - tzdata missing
        raise TemporalError("timezone_invalid", f"timezone database missing {zone_id!r}") from exc


def offset_minutes_at(zone_id: str, instant: datetime) -> int:
    """The zone's UTC offset, in minutes, at one exact instant."""
    zone = require_valid_zone(zone_id)
    aware = ensure_aware_utc(instant)
    offset = aware.astimezone(zone).utcoffset() or timedelta(0)
    return int(offset.total_seconds() // 60)


def zone_offset_consistent(
    zone_id: str,
    instant: datetime,
    claimed_offset_minutes: int,
    *,
    tolerance_minutes: int = 0,
) -> bool:
    """Whether a claimed offset matches the zone's actual offset at ``instant``."""
    actual = offset_minutes_at(zone_id, instant)
    return abs(actual - claimed_offset_minutes) <= tolerance_minutes


def require_zone_offset_consistent(
    zone_id: str, instant: datetime, claimed_offset_minutes: int
) -> None:
    """Raise ``timezone_offset_mismatch`` when zone and claimed offset disagree."""
    if not zone_offset_consistent(zone_id, instant, claimed_offset_minutes):
        actual = offset_minutes_at(zone_id, instant)
        raise TemporalError(
            "timezone_offset_mismatch",
            f"zone {zone_id} has offset {actual:+d} at {instant.isoformat()}, "
            f"claimed {claimed_offset_minutes:+d}",
        )


@lru_cache(maxsize=1)
def tzdb_version() -> str:
    """Best-effort IANA tzdb version used by this process (``unknown`` if opaque).

    Prefers the ``tzdata`` wheel (pinned, reproducible); falls back to the
    platform database's ``tzdata.zi`` header.
    """
    try:
        from importlib.metadata import version

        return version("tzdata")
    except Exception:
        pass
    for base in ("/usr/share/zoneinfo", "/usr/lib/zoneinfo"):
        zi = Path(base) / "tzdata.zi"
        try:
            first = zi.read_text(encoding="utf-8", errors="ignore").splitlines()[0]
            # e.g. "# version 2025a"
            if "version" in first:
                return first.split("version", 1)[1].strip()
        except OSError:
            continue
    return "unknown"


def local_key(zone_id: Optional[str]) -> str:
    """Stable cache-key fragment for a zone (``utc`` when absent)."""
    return zone_id if zone_id and is_valid_iana_zone(zone_id) else "utc"


__all__ = [
    "is_valid_iana_zone",
    "require_valid_zone",
    "offset_minutes_at",
    "zone_offset_consistent",
    "require_zone_offset_consistent",
    "tzdb_version",
    "local_key",
]
