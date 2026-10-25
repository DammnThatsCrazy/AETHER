"""Canonical, source-asserted geographic timezone facts.

``LocationFact`` deliberately stores geography, not timezone inference inputs.
This authority records a timezone only when an upstream source explicitly
asserts one for an exact canonical ``location_facts.location_id``. Tenant and
subject identity are derived from that canonical row; callers cannot choose a
tenant or recording actor.

Reads are bitemporal and bounded. A record is eligible at an anchor only when
it was recorded and observed by then and its effective interval contains the
anchor. Historical reads also require the exact canonical location fact to
have been recorded, observed, and effective at that same instant. Coordinates,
cells, region labels, and place names are never used to select or derive a
timezone.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional, Protocol

from graph.operational_intelligence.models import EvidenceRef
from repositories.repos import BaseRepository
from shared.common.common import utc_now
from shared.temporal.instant import ensure_aware_utc
from shared.temporal.zones import offset_minutes_at, require_valid_zone, tzdb_version

TIMEZONE_ASSERTION_READ_CAP = 100
TIMEZONE_ASSERTION_ACTOR = "geo_temporal_graph.timezone_assertion_authority"
TIMEZONE_AUTHORITY_SOURCE = "geo_temporal_timezone_assertions"


class TimezoneAuthorityError(ValueError):
    """A source timezone assertion cannot be admitted to canonical authority."""


def _text(value: object, field: str, *, max_length: int = 512) -> str:
    if not isinstance(value, str):
        raise TimezoneAuthorityError(f"{field} must be a string")
    result = value.strip()
    if (
        not result
        or len(result) > max_length
        or any(ord(char) < 32 or ord(char) == 127 for char in result)
    ):
        raise TimezoneAuthorityError(f"{field} is empty or malformed")
    return result


def _utc(value: object, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise TimezoneAuthorityError(f"{field} must be a timezone-aware datetime")
    try:
        return ensure_aware_utc(value)
    except (TypeError, ValueError) as exc:
        raise TimezoneAuthorityError(f"{field} must be a valid instant") from exc


@dataclass(frozen=True)
class TimezoneSourceAssertion:
    """Source-owned assertion input; tenant and actor are intentionally absent."""

    timezone_id: str
    source_provider: str
    source_record_id: str
    evidence_refs: tuple[str, ...]
    observed_at: datetime
    effective_from: datetime
    effective_to: Optional[datetime] = None

    def validated(self) -> "TimezoneSourceAssertion":
        zone_id = _text(self.timezone_id, "timezone_id", max_length=128)
        try:
            require_valid_zone(zone_id)
        except Exception as exc:  # noqa: BLE001 - normalize temporal kernel errors
            raise TimezoneAuthorityError("timezone_id must be a canonical IANA zone") from exc
        provider = _text(self.source_provider, "source_provider", max_length=256)
        record_id = _text(self.source_record_id, "source_record_id")
        refs = tuple(
            dict.fromkeys(_text(ref, "evidence_ref") for ref in self.evidence_refs)
        )
        if not refs:
            raise TimezoneAuthorityError("at least one source evidence_ref is required")
        observed_at = _utc(self.observed_at, "observed_at")
        effective_from = _utc(self.effective_from, "effective_from")
        effective_to = (
            _utc(self.effective_to, "effective_to")
            if self.effective_to is not None
            else None
        )
        if effective_to is not None and effective_to <= effective_from:
            raise TimezoneAuthorityError("effective_to must be later than effective_from")
        return TimezoneSourceAssertion(
            timezone_id=zone_id,
            source_provider=provider,
            source_record_id=record_id,
            evidence_refs=refs,
            observed_at=observed_at,
            effective_from=effective_from,
            effective_to=effective_to,
        )


class _LocationFactLookup(Protocol):
    async def find_by_id(self, record_id: str) -> Optional[dict]:
        ...


class TimezoneAssertionRepository(BaseRepository):
    """Tenant-scoped storage and bounded access to source timezone assertions."""

    def __init__(self) -> None:
        super().__init__(TIMEZONE_AUTHORITY_SOURCE)

    async def for_location(
        self, tenant_id: str, location_id: str, *, limit: int = TIMEZONE_ASSERTION_READ_CAP + 1
    ) -> list[dict]:
        if not tenant_id or not location_id:
            return []
        return await self.find_many(
            filters={"tenant_id": tenant_id, "location_id": location_id},
            limit=min(max(int(limit), 1), TIMEZONE_ASSERTION_READ_CAP + 1),
            sort_by="created_at",
            sort_order="desc",
        )


@dataclass(frozen=True)
class TimezoneAssertionRead:
    state: str
    reason_code: Optional[str]
    content: Optional[dict[str, Any]]
    evidence_refs: tuple[EvidenceRef, ...]
    freshness: dict[str, Optional[str]]


class GeoTemporalTimezoneAuthority:
    """Owns exact canonical location-to-zone source assertions and reads."""

    def __init__(
        self,
        *,
        assertions: Optional[TimezoneAssertionRepository] = None,
        location_facts: Optional[_LocationFactLookup] = None,
    ) -> None:
        self._assertions = assertions or TimezoneAssertionRepository()
        if location_facts is None:
            from graph.geo.location_facts import location_fact_repo

            location_facts = location_fact_repo
        self._location_facts = location_facts

    async def record_source_assertion(
        self,
        *,
        location_id: str,
        assertion: TimezoneSourceAssertion,
    ) -> dict:
        """Record an explicit assertion against an existing canonical location.

        Tenant, subject, and recording actor are resolved/stamped by this
        authority. The caller supplies only the exact location key and source
        assertion payload; there is no route-level tenant/actor input.
        """
        location_key = _text(location_id, "location_id")
        source = assertion.validated()
        location = await self._location_facts.find_by_id(location_key)
        if not isinstance(location, dict):
            raise TimezoneAuthorityError("canonical location fact was not found")
        tenant_id = _text(location.get("tenant_id"), "canonical tenant_id")
        subject_type = _text(location.get("subject_type"), "canonical subject_type")
        subject_id = _text(location.get("subject_id"), "canonical subject_id")
        if location.get("location_id") != location_key or location.get("lifecycle_state") != "active":
            raise TimezoneAuthorityError("canonical location fact is not active")
        if subject_type not in {"entity", "population", "source"}:
            raise TimezoneAuthorityError("canonical location subject kind is unsupported")

        source_data = {
            "tenant_id": tenant_id,
            "location_id": location_key,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "timezone_id": source.timezone_id,
            "source_provider": source.source_provider,
            "source_record_id": source.source_record_id,
            "evidence_refs": list(source.evidence_refs),
            "observed_at": source.observed_at.isoformat(),
            "effective_from": source.effective_from.isoformat(),
            "effective_to": source.effective_to.isoformat() if source.effective_to else None,
        }
        digest = hashlib.sha256(
            json.dumps(source_data, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        assertion_id = f"geo-tz-{digest}"
        record = {
            **source_data,
            "id": assertion_id,
            "recorded_at": utc_now().astimezone(timezone.utc).isoformat(),
            "recorded_by": TIMEZONE_ASSERTION_ACTOR,
            "assertion_state": "asserted",
        }
        inserted = await self._assertions.insert_if_absent(assertion_id, record, tenant_id)
        if inserted:
            return record
        existing = await self._assertions.find_by_id(assertion_id)
        if not isinstance(existing, dict) or any(
            existing.get(key) != value for key, value in source_data.items()
        ):
            raise TimezoneAuthorityError("timezone assertion idempotency conflict")
        return existing

    async def timezone_for_location(
        self,
        *,
        tenant_id: str,
        subject_kind: str,
        subject_id: str,
        location_id: str,
        as_of: datetime,
        historical: bool,
    ) -> TimezoneAssertionRead:
        """Resolve a source assertion for the exact tenant/location at an anchor."""
        unknown = lambda code: TimezoneAssertionRead(  # noqa: E731
            "unknown", code, None, (), {"state": "unknown", "reasonCode": code}
        )
        try:
            anchor = _utc(as_of, "as_of")
            tenant = _text(tenant_id, "tenant_id")
            kind = _text(subject_kind, "subject_kind")
            sid = _text(subject_id, "subject_id")
            location_key = _text(location_id, "location_id")
        except TimezoneAuthorityError:
            return unknown("timezone_subject_scope_invalid")

        location = await self._location_facts.find_by_id(location_key)
        if not isinstance(location, dict):
            return unknown("canonical_location_fact_unavailable")
        if (
            location.get("tenant_id") != tenant
            or location.get("location_id") != location_key
            or location.get("subject_type") != kind
            or location.get("subject_id") != sid
        ):
            return unknown("timezone_location_subject_mismatch")

        location_state = location.get("lifecycle_state")
        if location_state not in {None, "active"}:
            # A data-subject erasure is not an ordinary temporal state change:
            # historical reads must not resurrect a removed location or its
            # dependent timezone assertions.
            if location.get("revoke_reason") == "dsr_erasure":
                return unknown("canonical_location_fact_erased")
            # Historical reads before a soft revoke remain valid only if every
            # temporal anchor proves the exact row existed at the requested time.
            revoked_at = _parse_time(location.get("revoked_at"))
            if not historical or revoked_at is None or revoked_at <= anchor:
                return unknown("canonical_location_fact_not_active_at_as_of")
        created_at = _parse_time(location.get("created_at"))
        observed_at = _parse_time(location.get("observed_at"))
        valid_from = _parse_time(location.get("valid_from"))
        valid_to = _parse_time(location.get("valid_to"))
        if created_at is not None and created_at > anchor:
            return unknown("canonical_location_fact_not_known_at_as_of")
        if observed_at is None or observed_at > anchor:
            return unknown("canonical_location_fact_not_observed_at_as_of")
        if valid_from is None or valid_from > anchor:
            return unknown("canonical_location_validity_unavailable_at_as_of")
        if valid_to is not None and valid_to <= anchor:
            return unknown("canonical_location_fact_not_effective_at_as_of")

        rows = await self._assertions.for_location(
            tenant, location_key, limit=TIMEZONE_ASSERTION_READ_CAP + 1
        )
        if len(rows) > TIMEZONE_ASSERTION_READ_CAP:
            return unknown("timezone_assertion_read_truncated")
        eligible: list[dict[str, Any]] = []
        for row in rows:
            if (
                row.get("tenant_id") != tenant
                or row.get("location_id") != location_key
                or row.get("subject_type") != kind
                or row.get("subject_id") != sid
                or row.get("assertion_state") != "asserted"
            ):
                return unknown("timezone_assertion_scope_or_state_invalid")
            recorded_at = _parse_time(row.get("recorded_at"))
            row_observed = _parse_time(row.get("observed_at"))
            effective_from = _parse_time(row.get("effective_from"))
            effective_to = _parse_time(row.get("effective_to"))
            if (
                recorded_at is None
                or row_observed is None
                or effective_from is None
                or (row.get("effective_to") is not None and effective_to is None)
            ):
                return unknown("timezone_assertion_temporal_evidence_invalid")
            if (
                recorded_at <= anchor
                and row_observed <= anchor
                and effective_from <= anchor
                and (effective_to is None or anchor < effective_to)
            ):
                zone_id = row.get("timezone_id")
                try:
                    require_valid_zone(zone_id)
                except Exception:  # noqa: BLE001 - invalid persisted data fails closed
                    return unknown("timezone_assertion_zone_invalid")
                refs = row.get("evidence_refs")
                if not isinstance(refs, list) or not refs or any(
                    not isinstance(ref, str) or not ref.strip() for ref in refs
                ):
                    return unknown("timezone_assertion_evidence_invalid")
                eligible.append(row)

        if not eligible:
            return unknown("timezone_assertion_not_effective_as_of")

        zones = sorted({row["timezone_id"] for row in eligible})
        assertion_refs = tuple(
            EvidenceRef(
                id=f"timezone-assertion:{row['id']}",
                type="event",
                source=TIMEZONE_AUTHORITY_SOURCE,
                observedAt=row["observed_at"],
            )
            for row in eligible
        )
        if len(zones) > 1:
            return TimezoneAssertionRead(
                "conflicted",
                "timezone_source_assertions_conflict_at_as_of",
                {
                    "asOf": anchor.isoformat(),
                    "conflictingTimezoneIds": zones,
                    "assertions": [_assertion_content(row) for row in eligible],
                },
                assertion_refs,
                {"state": "unknown", "reasonCode": "timezone_freshness_threshold_unconfigured"},
            )

        zone_id = zones[0]
        offset = offset_minutes_at(zone_id, anchor)
        latest_observed = max(row["observed_at"] for row in eligible)
        return TimezoneAssertionRead(
            "degraded",
            "timezone_freshness_threshold_unconfigured",
            {
                "timezoneId": zone_id,
                "asOf": anchor.isoformat(),
                "conversion": {
                    "instant": anchor.isoformat(),
                    "offsetMinutes": offset,
                    "tzdbVersion": tzdb_version(),
                },
                "assertions": [_assertion_content(row) for row in eligible],
            },
            assertion_refs,
            {
                "state": "unknown",
                "reasonCode": "timezone_freshness_threshold_unconfigured",
                "latestObservedAt": latest_observed,
            },
        )


def _parse_time(value: object) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    try:
        return ensure_aware_utc(parsed)
    except (TypeError, ValueError):
        return None


def _assertion_content(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "assertionId": row["id"],
        "timezoneId": row["timezone_id"],
        "sourceProvider": row["source_provider"],
        "sourceRecordId": row["source_record_id"],
        "sourceEvidenceRefs": list(row["evidence_refs"]),
        "observedAt": row["observed_at"],
        "effectiveFrom": row["effective_from"],
        "effectiveTo": row.get("effective_to"),
        "recordedAt": row["recorded_at"],
    }


geo_temporal_timezone_authority = GeoTemporalTimezoneAuthority()

__all__ = [
    "GeoTemporalTimezoneAuthority",
    "TIMEZONE_ASSERTION_ACTOR",
    "TIMEZONE_ASSERTION_READ_CAP",
    "TIMEZONE_AUTHORITY_SOURCE",
    "TimezoneAssertionRead",
    "TimezoneAssertionRepository",
    "TimezoneAuthorityError",
    "TimezoneSourceAssertion",
    "geo_temporal_timezone_authority",
]
