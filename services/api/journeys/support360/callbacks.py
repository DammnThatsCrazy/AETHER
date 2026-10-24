"""Tenant-scoped support callback schedule and execution authority.

Callbacks are keyed by a canonical support case and a verified provider
connection. External callback IDs remain connection-scoped source keys. Every
accepted schedule or execution update is an immutable, idempotent event with
provider, case, connection, and event evidence; the parent row is only the
current projection of that event ledger.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional
from urllib.parse import quote
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from graph.operational_intelligence.models import EvidenceRef
from journeys.support360.cases import SupportCaseRepository
from repositories.repos import get_pool
from shared.temporal.instant import coerce_utc_lenient

_LOCAL_ENVIRONMENTS = frozenset({"local", "dev", "test"})
_MAX_CALLBACKS = 100
_MAX_EVENTS_PER_CALLBACK = 50


class SupportCallbackEventType(str, Enum):
    SCHEDULED = "support_callback_scheduled"
    RESCHEDULED = "support_callback_rescheduled"
    ATTEMPTED = "support_callback_attempted"
    COMPLETED = "support_callback_completed"
    FAILED = "support_callback_failed"
    CANCELLED = "support_callback_cancelled"


class SupportCallbackState(str, Enum):
    SCHEDULED = "scheduled"
    ATTEMPTED = "attempted"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SupportCallbackAuthorityError(RuntimeError):
    """A callback event cannot be accepted under its scope or lifecycle."""


class SupportCallbackNotFound(SupportCallbackAuthorityError):
    """A tenant-owned canonical callback or case is unavailable."""


class SupportCallbackTransitionError(SupportCallbackAuthorityError):
    """A callback event conflicts with the accepted callback lifecycle."""


class SupportCallbackEventInput(BaseModel):
    """Allow-listed source callback event; provider payloads are never stored."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    case_id: str = Field(min_length=1, max_length=64)
    source_callback_id: str = Field(min_length=1, max_length=256)
    source_event_id: str = Field(min_length=1, max_length=256)
    event_type: SupportCallbackEventType
    occurred_at: datetime
    scheduled_for: Optional[datetime] = None

    @field_validator("case_id")
    @classmethod
    def _canonical_case_id(cls, value: str) -> str:
        try:
            return str(UUID(value))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("case_id must be a canonical support case UUID") from exc

    @field_validator("source_callback_id", "source_event_id")
    @classmethod
    def _safe_source_identifier(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or any(ord(char) < 32 or ord(char) == 127 for char in normalized):
            raise ValueError("source identifiers must be non-empty printable text")
        return normalized

    @field_validator("occurred_at", "scheduled_for")
    @classmethod
    def _require_timezone_and_normalize(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("callback timestamps must include a timezone")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _validate_schedule_time(self) -> "SupportCallbackEventInput":
        requires_schedule = self.event_type in {
            SupportCallbackEventType.SCHEDULED,
            SupportCallbackEventType.RESCHEDULED,
        }
        if requires_schedule != (self.scheduled_for is not None):
            raise ValueError("scheduled_for is required only for schedule and reschedule events")
        return self


@dataclass(frozen=True)
class SupportCallbacksRead:
    callbacks: list[dict[str, Any]]
    available: bool
    complete: bool
    truncated: bool = False
    reason: Optional[str] = None
    scope_known: bool = True


@dataclass(frozen=True)
class SupportCallbackRead:
    record: Optional[dict[str, Any]]
    events: list[dict[str, Any]]
    available: bool
    complete: bool
    expired: bool = False
    reason: Optional[str] = None
    scope_known: bool = True


_LOCAL_CALLBACKS: dict[tuple[str, str, str], dict[str, Any]] = {}
_LOCAL_CALLBACK_EVENTS: dict[tuple[str, str, str], dict[str, Any]] = {}


def reset_local_support_callback_store() -> None:
    """Clear local-only callback records for isolated tests."""
    _LOCAL_CALLBACKS.clear()
    _LOCAL_CALLBACK_EVENTS.clear()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        return coerce_utc_lenient(value).astimezone(timezone.utc).isoformat()
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(timezone.utc).isoformat()
    return None


def _as_datetime(value: Any) -> Optional[datetime]:
    normalized = _iso(value)
    return datetime.fromisoformat(normalized) if normalized is not None else None


def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    return str(value.value if isinstance(value, Enum) else value)


def _row_dict(row: Any) -> dict[str, Any]:
    result = dict(row)
    for key, value in result.items():
        if isinstance(value, datetime):
            result[key] = coerce_utc_lenient(value).astimezone(timezone.utc).isoformat()
        elif key == "evidence_refs" and isinstance(value, str):
            try:
                result[key] = json.loads(value)
            except json.JSONDecodeError:
                result[key] = None
    return result


def _next_state(
    current: Optional[str], event_type: SupportCallbackEventType
) -> SupportCallbackState:
    if event_type is SupportCallbackEventType.SCHEDULED:
        if current is None:
            return SupportCallbackState.SCHEDULED
    elif event_type is SupportCallbackEventType.RESCHEDULED:
        if current == SupportCallbackState.SCHEDULED.value:
            return SupportCallbackState.SCHEDULED
    elif event_type is SupportCallbackEventType.ATTEMPTED:
        if current in {SupportCallbackState.SCHEDULED.value, SupportCallbackState.ATTEMPTED.value}:
            return SupportCallbackState.ATTEMPTED
    elif event_type is SupportCallbackEventType.COMPLETED:
        if current in {SupportCallbackState.SCHEDULED.value, SupportCallbackState.ATTEMPTED.value}:
            return SupportCallbackState.COMPLETED
    elif event_type is SupportCallbackEventType.FAILED:
        if current in {SupportCallbackState.SCHEDULED.value, SupportCallbackState.ATTEMPTED.value}:
            return SupportCallbackState.FAILED
    elif event_type is SupportCallbackEventType.CANCELLED:
        if current in {SupportCallbackState.SCHEDULED.value, SupportCallbackState.ATTEMPTED.value}:
            return SupportCallbackState.CANCELLED
    raise SupportCallbackTransitionError(
        f"{event_type.value} is not valid from support callback state {current!r}"
    )


def _validate_replay(
    existing: dict[str, Any], *, callback_id: str, case_id: str, event: SupportCallbackEventInput
) -> None:
    if (
        str(existing.get("callback_id")) != callback_id
        or str(existing.get("case_id")) != case_id
        or existing.get("event_type") != event.event_type.value
        or _as_datetime(existing.get("source_occurred_at")) != event.occurred_at
        or _as_datetime(existing.get("scheduled_for")) != event.scheduled_for
    ):
        raise SupportCallbackAuthorityError("source event ID replay payload does not match")


def _event_evidence_refs(
    *,
    tenant_id: str,
    case_id: str,
    callback_id: str,
    connection_id: str,
    provider_identity: str,
    connection_verified_at: str,
    case_last_observed_at: Optional[str],
    case_event: dict[str, Any],
    event: SupportCallbackEventInput,
    received_at: datetime,
) -> list[dict[str, Any]]:
    """Persist exact callback, case, connection, case-event, and provider-event refs."""
    case_event_ref, _ = _validated_case_event_evidence(
        case_event,
        connection_id=connection_id,
        provider_identity=provider_identity,
    )
    expected_connection_uri = f"store://provider_connections/{quote(connection_id, safe='')}"

    refs = [
        EvidenceRef(
            id=callback_id,
            type="entity",
            source="support_callbacks",
            observedAt=received_at.isoformat(),
            uri=f"store://support_callbacks/{quote(callback_id, safe='')}",
        ),
        EvidenceRef(
            id=case_id,
            type="entity",
            source="support_cases",
            observedAt=case_last_observed_at,
            uri=f"store://support_cases/{quote(case_id, safe='')}",
        ),
        case_event_ref,
        EvidenceRef(
            id=event.source_event_id,
            type="event",
            source=provider_identity,
            observedAt=event.occurred_at.isoformat(),
            uri=(
                "provider-event://"
                f"{quote(connection_id, safe='')}/{quote(event.source_event_id, safe='')}"
            ),
        ),
        EvidenceRef(
            id=connection_id,
            type="entity",
            source="provider_connections",
            observedAt=connection_verified_at,
            uri=expected_connection_uri,
        ),
    ]
    return [ref.model_dump(mode="json", by_alias=True) for ref in refs]


def _validated_case_event_evidence(
    case_event: dict[str, Any], *, connection_id: str, provider_identity: str
) -> tuple[EvidenceRef, EvidenceRef]:
    """Validate the exact provider and connection refs on the linked case event."""
    case_event_id = str(case_event.get("source_event_id") or "")
    case_event_at = _as_datetime(case_event.get("source_occurred_at"))
    if not case_event_id or case_event_at is None:
        raise SupportCallbackAuthorityError("canonical support case event evidence is unavailable")
    raw_refs = case_event.get("evidence_refs")
    if isinstance(raw_refs, str):
        try:
            raw_refs = json.loads(raw_refs)
        except json.JSONDecodeError as exc:
            raise SupportCallbackAuthorityError(
                "canonical support case event evidence is unavailable"
            ) from exc
    if not isinstance(raw_refs, (list, tuple)):
        raise SupportCallbackAuthorityError("canonical support case event evidence is unavailable")
    expected_event_uri = (
        f"provider-event://{quote(connection_id, safe='')}/{quote(case_event_id, safe='')}"
    )
    expected_connection_uri = f"store://provider_connections/{quote(connection_id, safe='')}"
    event_ref: Optional[EvidenceRef] = None
    connection_ref: Optional[EvidenceRef] = None
    for raw_ref in raw_refs:
        try:
            ref = (
                raw_ref if isinstance(raw_ref, EvidenceRef) else EvidenceRef.model_validate(raw_ref)
            )
        except (TypeError, ValueError):
            continue
        if (
            ref.id == case_event_id
            and ref.type == "event"
            and ref.source == provider_identity
            and ref.uri == expected_event_uri
            and _as_datetime(ref.observedAt) == case_event_at
        ):
            event_ref = ref
        elif (
            ref.id == connection_id
            and ref.type == "entity"
            and ref.source == "provider_connections"
            and ref.uri == expected_connection_uri
        ):
            connection_ref = ref
    if event_ref is None or connection_ref is None:
        raise SupportCallbackAuthorityError("canonical support case event evidence is unavailable")
    return event_ref, connection_ref


class SupportCallbackRepository:
    """Durable callback state and append-only event ledger."""

    def __init__(self, pool: Any = None) -> None:
        self._injected_pool = pool

    async def _pool(self) -> Any:
        pool = self._injected_pool
        if pool is None:
            pool = await get_pool()
        if (
            pool is None
            and os.environ.get("AETHER_ENV", "local").lower() not in _LOCAL_ENVIRONMENTS
        ):
            raise RuntimeError("support callback authority requires PostgreSQL outside local/test")
        return pool

    async def ingest_event(
        self,
        *,
        tenant_id: str,
        case_id: str,
        connection_id: str,
        provider_identity: str,
        connection_verified_at: str,
        case_record: dict[str, Any],
        case_event: dict[str, Any],
        event: SupportCallbackEventInput,
        observed_at: Optional[datetime] = None,
    ) -> dict[str, Any]:
        if not tenant_id or not case_id or not connection_id or not provider_identity:
            raise ValueError("tenant, case, provider connection, and provider scope are required")
        if event.case_id != case_id:
            raise SupportCallbackAuthorityError("callback case scope does not match the request")
        received_at = observed_at or _now()
        if received_at.tzinfo is None or received_at.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        received_at = received_at.astimezone(timezone.utc)
        retention_class, retention_days = SupportCaseRepository.retention_policy()
        expires_at = received_at + timedelta(days=retention_days)
        pool = await self._pool()
        if pool is None:
            return self._ingest_local(
                tenant_id=tenant_id,
                case_id=case_id,
                connection_id=connection_id,
                provider_identity=provider_identity,
                connection_verified_at=connection_verified_at,
                case_record=case_record,
                case_event=case_event,
                event=event,
                received_at=received_at,
                retention_class=retention_class,
                expires_at=expires_at,
            )

        async with pool.acquire() as conn:
            async with conn.transaction():
                callback_row = await conn.fetchrow(
                    """SELECT * FROM support_callbacks
                       WHERE tenant_id=$1 AND source_connection_id=$2 AND source_callback_id=$3
                       FOR UPDATE""",
                    tenant_id,
                    connection_id,
                    event.source_callback_id,
                )
                if (
                    callback_row is None
                    and event.event_type is not SupportCallbackEventType.SCHEDULED
                ):
                    raise SupportCallbackNotFound(
                        "a support_callback_scheduled event is required first"
                    )
                if callback_row is None:
                    callback_id = str(uuid4())
                    callback_row = await conn.fetchrow(
                        """INSERT INTO support_callbacks (
                               tenant_id, callback_id, case_id, source_connection_id,
                               source_provider_identity, source_callback_id, callback_state,
                               scheduled_for, schedule_observed_at, latest_event_occurred_at,
                               first_observed_at, last_observed_at, last_source_event_id,
                               event_count, retention_class, retention_expires_at
                           ) VALUES ($1,$2,$3,$4,$5,$6,'scheduled',$7,$8,$9,$8,$8,$10,0,$11,$12)
                           ON CONFLICT (tenant_id, source_connection_id, source_callback_id)
                           DO NOTHING RETURNING *""",
                        tenant_id,
                        callback_id,
                        case_id,
                        connection_id,
                        provider_identity,
                        event.source_callback_id,
                        event.scheduled_for,
                        received_at,
                        event.occurred_at,
                        event.source_event_id,
                        retention_class,
                        expires_at,
                    )
                    if callback_row is None:
                        callback_row = await conn.fetchrow(
                            """SELECT * FROM support_callbacks
                               WHERE tenant_id=$1 AND source_connection_id=$2 AND source_callback_id=$3
                               FOR UPDATE""",
                            tenant_id,
                            connection_id,
                            event.source_callback_id,
                        )
                if callback_row is None:
                    raise SupportCallbackAuthorityError(
                        "support callback could not be durably recorded"
                    )
                record = _row_dict(callback_row)
                callback_id = str(record["callback_id"])
                if (
                    record.get("tenant_id") != tenant_id
                    or str(record.get("case_id")) != case_id
                    or record.get("source_connection_id") != connection_id
                    or record.get("source_provider_identity") != provider_identity
                ):
                    raise SupportCallbackAuthorityError(
                        "support callback tenant/case/provider scope mismatch"
                    )

                duplicate = await conn.fetchrow(
                    """SELECT tenant_id, callback_id, case_id, source_event_id, event_type,
                              source_occurred_at, scheduled_for
                       FROM support_callback_events
                       WHERE tenant_id=$1 AND source_connection_id=$2 AND source_event_id=$3""",
                    tenant_id,
                    connection_id,
                    event.source_event_id,
                )
                if duplicate is not None:
                    _validate_replay(
                        _row_dict(duplicate), callback_id=callback_id, case_id=case_id, event=event
                    )
                    return record

                initial_schedule = (
                    int(record.get("event_count") or 0) == 0
                    and event.event_type is SupportCallbackEventType.SCHEDULED
                )
                latest = _as_datetime(record.get("latest_event_occurred_at"))
                stale_event = (
                    not initial_schedule and latest is not None and event.occurred_at < latest
                )
                next_state = (
                    SupportCallbackState.SCHEDULED
                    if initial_schedule
                    else None
                    if stale_event
                    else _next_state(record.get("callback_state"), event.event_type)
                )
                evidence_refs = _event_evidence_refs(
                    tenant_id=tenant_id,
                    case_id=case_id,
                    callback_id=callback_id,
                    connection_id=connection_id,
                    provider_identity=provider_identity,
                    connection_verified_at=connection_verified_at,
                    case_last_observed_at=_iso(case_record.get("last_observed_at")),
                    case_event=case_event,
                    event=event,
                    received_at=received_at,
                )
                inserted = await conn.fetchrow(
                    """INSERT INTO support_callback_events (
                           tenant_id, callback_id, case_id, source_connection_id,
                           source_event_id, case_source_event_id, event_type,
                           source_occurred_at, received_at,
                           scheduled_for, state_applied, evidence_refs
                       ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12::jsonb)
                       ON CONFLICT (tenant_id, source_connection_id, source_event_id)
                       DO NOTHING RETURNING source_event_id""",
                    tenant_id,
                    callback_id,
                    case_id,
                    connection_id,
                    event.source_event_id,
                    str(case_event.get("source_event_id")),
                    event.event_type.value,
                    event.occurred_at,
                    received_at,
                    event.scheduled_for,
                    not stale_event,
                    json.dumps(evidence_refs),
                )
                if inserted is None:
                    duplicate = await conn.fetchrow(
                        """SELECT tenant_id, callback_id, case_id, source_event_id, event_type,
                                  source_occurred_at, scheduled_for
                           FROM support_callback_events
                           WHERE tenant_id=$1 AND source_connection_id=$2 AND source_event_id=$3""",
                        tenant_id,
                        connection_id,
                        event.source_event_id,
                    )
                    if duplicate is None:
                        raise SupportCallbackAuthorityError(
                            "support callback event was not durably recorded"
                        )
                    _validate_replay(
                        _row_dict(duplicate), callback_id=callback_id, case_id=case_id, event=event
                    )
                    return record

                applied = not stale_event
                await conn.execute(
                    """UPDATE support_callbacks SET
                           callback_state=CASE WHEN $4 THEN $5 ELSE callback_state END,
                           scheduled_for=CASE WHEN $6 THEN $7 ELSE scheduled_for END,
                           schedule_observed_at=CASE WHEN $6 AND $4 THEN $8 ELSE schedule_observed_at END,
                           latest_event_occurred_at=CASE WHEN $4 THEN $9 ELSE latest_event_occurred_at END,
                           last_observed_at=GREATEST(last_observed_at,$8),
                           last_source_event_id=CASE WHEN $4 THEN $10 ELSE last_source_event_id END,
                           event_count=event_count+1,
                           retention_expires_at=GREATEST(retention_expires_at,$11),
                           updated_at=now()
                       WHERE tenant_id=$1 AND callback_id=$2""",
                    tenant_id,
                    callback_id,
                    case_id,
                    applied,
                    next_state.value if next_state is not None else None,
                    event.event_type
                    in {
                        SupportCallbackEventType.SCHEDULED,
                        SupportCallbackEventType.RESCHEDULED,
                    },
                    event.scheduled_for,
                    received_at,
                    event.occurred_at,
                    event.source_event_id,
                    expires_at,
                )
                updated = await conn.fetchrow(
                    "SELECT * FROM support_callbacks WHERE tenant_id=$1 AND callback_id=$2",
                    tenant_id,
                    callback_id,
                )
                return _row_dict(updated or record)

    def _ingest_local(
        self,
        *,
        tenant_id: str,
        case_id: str,
        connection_id: str,
        provider_identity: str,
        connection_verified_at: str,
        case_record: dict[str, Any],
        case_event: dict[str, Any],
        event: SupportCallbackEventInput,
        received_at: datetime,
        retention_class: str,
        expires_at: datetime,
    ) -> dict[str, Any]:
        scope = (tenant_id, connection_id, event.source_callback_id)
        event_key = (tenant_id, connection_id, event.source_event_id)
        record = _LOCAL_CALLBACKS.get(scope)
        if record is None and event.event_type is not SupportCallbackEventType.SCHEDULED:
            raise SupportCallbackNotFound("a support_callback_scheduled event is required first")
        if record is None:
            callback_id = str(uuid4())
            record = {
                "tenant_id": tenant_id,
                "callback_id": callback_id,
                "case_id": case_id,
                "source_connection_id": connection_id,
                "source_provider_identity": provider_identity,
                "source_callback_id": event.source_callback_id,
                "callback_state": SupportCallbackState.SCHEDULED.value,
                "scheduled_for": event.scheduled_for,
                "schedule_observed_at": received_at,
                "latest_event_occurred_at": event.occurred_at,
                "first_observed_at": received_at,
                "last_observed_at": received_at,
                "last_source_event_id": event.source_event_id,
                "event_count": 0,
                "retention_class": retention_class,
                "retention_expires_at": expires_at,
                "created_at": received_at,
                "updated_at": received_at,
            }
            _LOCAL_CALLBACKS[scope] = record
        if (
            record.get("tenant_id") != tenant_id
            or record.get("case_id") != case_id
            or record.get("source_connection_id") != connection_id
            or record.get("source_provider_identity") != provider_identity
        ):
            raise SupportCallbackAuthorityError(
                "support callback tenant/case/provider scope mismatch"
            )
        if event_key in _LOCAL_CALLBACK_EVENTS:
            _validate_replay(
                _LOCAL_CALLBACK_EVENTS[event_key],
                callback_id=str(record["callback_id"]),
                case_id=case_id,
                event=event,
            )
            return _row_dict(record)

        initial_schedule = (
            int(record.get("event_count") or 0) == 0
            and event.event_type is SupportCallbackEventType.SCHEDULED
        )
        latest = _as_datetime(record.get("latest_event_occurred_at"))
        stale_event = not initial_schedule and latest is not None and event.occurred_at < latest
        next_state = (
            SupportCallbackState.SCHEDULED
            if initial_schedule
            else None
            if stale_event
            else _next_state(record.get("callback_state"), event.event_type)
        )
        evidence_refs = _event_evidence_refs(
            tenant_id=tenant_id,
            case_id=case_id,
            callback_id=str(record["callback_id"]),
            connection_id=connection_id,
            provider_identity=provider_identity,
            connection_verified_at=connection_verified_at,
            case_last_observed_at=_iso(case_record.get("last_observed_at")),
            case_event=case_event,
            event=event,
            received_at=received_at,
        )
        _LOCAL_CALLBACK_EVENTS[event_key] = {
            "tenant_id": tenant_id,
            "callback_id": record["callback_id"],
            "case_id": case_id,
            "source_connection_id": connection_id,
            "source_provider_identity": provider_identity,
            "source_event_id": event.source_event_id,
            "case_source_event_id": str(case_event.get("source_event_id")),
            "event_type": event.event_type.value,
            "source_occurred_at": event.occurred_at,
            "received_at": received_at,
            "scheduled_for": event.scheduled_for,
            "state_applied": not stale_event,
            "evidence_refs": evidence_refs,
        }
        if not stale_event and next_state is not None:
            record["callback_state"] = next_state.value
            record["latest_event_occurred_at"] = event.occurred_at
            record["last_source_event_id"] = event.source_event_id
            if event.event_type in {
                SupportCallbackEventType.SCHEDULED,
                SupportCallbackEventType.RESCHEDULED,
            }:
                record["scheduled_for"] = event.scheduled_for
                record["schedule_observed_at"] = received_at
        record["last_observed_at"] = max(
            _as_datetime(record.get("last_observed_at")) or received_at, received_at
        )
        record["event_count"] = int(record.get("event_count") or 0) + 1
        record["retention_expires_at"] = max(
            _as_datetime(record.get("retention_expires_at")) or expires_at, expires_at
        )
        record["updated_at"] = received_at
        return _row_dict(record)

    async def list_for_case(
        self,
        tenant_id: str,
        case_id: str,
        *,
        limit: int = _MAX_CALLBACKS,
        after: Optional[str] = None,
        before: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> SupportCallbacksRead:
        """Read callbacks for one exact tenant/case, bounded by callback and event limits."""
        bounded_limit = min(max(int(limit), 1), _MAX_CALLBACKS)
        current_time = now or _now()
        if current_time.tzinfo is None or current_time.utcoffset() is None:
            raise ValueError("now must include a timezone")
        after_at = _as_datetime(after) if after else None
        before_at = _as_datetime(before) if before else None
        if (after and after_at is None) or (before and before_at is None):
            raise ValueError("callback window bounds must include a timezone")

        pool = await self._pool()
        if pool is None:
            rows = [
                _row_dict(row)
                for (row_tenant, _connection, _source_id), row in _LOCAL_CALLBACKS.items()
                if row_tenant == tenant_id
                and row.get("case_id") == case_id
                and (_as_datetime(row.get("retention_expires_at")) or current_time) > current_time
                and (
                    after_at is None
                    or (_as_datetime(row.get("scheduled_for")) or current_time) >= after_at
                )
                and (
                    before_at is None
                    or (_as_datetime(row.get("scheduled_for")) or current_time) <= before_at
                )
            ]
            rows.sort(
                key=lambda row: (
                    _as_datetime(row.get("scheduled_for"))
                    or datetime.min.replace(tzinfo=timezone.utc),
                    str(row.get("callback_id") or ""),
                ),
                reverse=True,
            )
            truncated = len(rows) > bounded_limit
            callbacks = rows[:bounded_limit]
            complete = not truncated
            for callback in callbacks:
                events = [
                    _row_dict(row)
                    for (
                        event_tenant,
                        _connection,
                        _event_id,
                    ), row in _LOCAL_CALLBACK_EVENTS.items()
                    if event_tenant == tenant_id
                    and row.get("case_id") == case_id
                    and row.get("callback_id") == callback.get("callback_id")
                ]
                events.sort(
                    key=lambda row: (
                        _as_datetime(row.get("source_occurred_at"))
                        or datetime.min.replace(tzinfo=timezone.utc),
                        _as_datetime(row.get("received_at"))
                        or datetime.min.replace(tzinfo=timezone.utc),
                    ),
                    reverse=True,
                )
                event_count = len(events)
                callback["event_count"] = event_count
                callback["events_complete"] = event_count <= _MAX_EVENTS_PER_CALLBACK
                callback["events"] = events[:_MAX_EVENTS_PER_CALLBACK]
                if not callback["events_complete"]:
                    complete = False
            return SupportCallbacksRead(
                callbacks=callbacks,
                available=True,
                complete=complete,
                truncated=not complete,
            )

        try:
            callback_rows = await pool.fetch(
                """SELECT * FROM support_callbacks
                   WHERE tenant_id=$1 AND case_id=$2 AND retention_expires_at>$3
                     AND ($4::timestamptz IS NULL OR scheduled_for >= $4)
                     AND ($5::timestamptz IS NULL OR scheduled_for <= $5)
                   ORDER BY scheduled_for DESC, callback_id DESC
                   LIMIT $6""",
                tenant_id,
                case_id,
                current_time,
                after_at,
                before_at,
                bounded_limit + 1,
            )
            rows = [_row_dict(row) for row in callback_rows]
            truncated = len(rows) > bounded_limit
            callbacks = rows[:bounded_limit]
            if not callbacks:
                return SupportCallbacksRead([], True, not truncated, truncated)
            callback_ids = [str(row["callback_id"]) for row in callbacks]
            event_rows = await pool.fetch(
                """SELECT * FROM (
                       SELECT e.*, row_number() OVER (
                                  PARTITION BY callback_id
                                  ORDER BY source_occurred_at DESC, received_at DESC, source_event_id DESC
                              ) AS event_rank,
                              count(*) OVER (PARTITION BY callback_id) AS event_total
                       FROM support_callback_events e
                       WHERE tenant_id=$1 AND case_id=$2 AND callback_id=ANY($3::uuid[])
                   ) ranked
                   WHERE event_rank <= $4
                   ORDER BY callback_id, source_occurred_at DESC, received_at DESC, source_event_id DESC""",
                tenant_id,
                case_id,
                [UUID(callback_id) for callback_id in callback_ids],
                _MAX_EVENTS_PER_CALLBACK,
            )
        except Exception:  # noqa: BLE001 - repository outage remains typed unknown
            return SupportCallbacksRead([], False, False, reason="support_callback_read_failed")

        grouped: dict[str, list[dict[str, Any]]] = {}
        event_totals: dict[str, int] = {}
        for raw in event_rows:
            row = _row_dict(raw)
            callback_id = str(row.get("callback_id") or "")
            event_totals[callback_id] = int(row.get("event_total") or 0)
            row.pop("event_rank", None)
            row.pop("event_total", None)
            grouped.setdefault(callback_id, []).append(row)
        complete = not truncated
        for callback in callbacks:
            callback_id = str(callback.get("callback_id") or "")
            events = grouped.get(callback_id, [])
            event_count = event_totals.get(callback_id, int(callback.get("event_count") or 0))
            events_complete = event_count <= _MAX_EVENTS_PER_CALLBACK
            callback["event_count"] = event_count
            callback["events_complete"] = events_complete
            callback["events"] = events
            if not events_complete:
                complete = False
        return SupportCallbacksRead(callbacks, True, complete, not complete)

    async def get_callback(
        self,
        tenant_id: str,
        callback_id: str,
        *,
        limit: int = _MAX_EVENTS_PER_CALLBACK,
        now: Optional[datetime] = None,
    ) -> SupportCallbackRead:
        """Read one exact tenant/callback ID and a bounded event history."""
        bounded_limit = min(max(int(limit), 1), _MAX_EVENTS_PER_CALLBACK)
        current_time = now or _now()
        if current_time.tzinfo is None or current_time.utcoffset() is None:
            raise ValueError("now must include a timezone")
        pool = await self._pool()
        if pool is None:
            record = next(
                (
                    row
                    for (row_tenant, _connection, _source_id), row in _LOCAL_CALLBACKS.items()
                    if row_tenant == tenant_id and row.get("callback_id") == callback_id
                ),
                None,
            )
            if record is None:
                return SupportCallbackRead(None, [], True, True)
            if (_as_datetime(record.get("retention_expires_at")) or current_time) <= current_time:
                return SupportCallbackRead(None, [], True, True, expired=True)
            events = [
                _row_dict(row)
                for (event_tenant, _connection, _event_id), row in _LOCAL_CALLBACK_EVENTS.items()
                if event_tenant == tenant_id and row.get("callback_id") == callback_id
            ]
            events.sort(
                key=lambda row: (
                    _as_datetime(row.get("source_occurred_at"))
                    or datetime.min.replace(tzinfo=timezone.utc),
                    _as_datetime(row.get("received_at"))
                    or datetime.min.replace(tzinfo=timezone.utc),
                ),
                reverse=True,
            )
            complete = len(events) <= bounded_limit
            return SupportCallbackRead(_row_dict(record), events[:bounded_limit], True, complete)
        try:
            raw_record = await pool.fetchrow(
                """SELECT * FROM support_callbacks
                   WHERE tenant_id=$1 AND callback_id=$2 AND retention_expires_at>$3""",
                tenant_id,
                callback_id,
                current_time,
            )
            if raw_record is None:
                expired = await pool.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM support_callbacks WHERE tenant_id=$1 AND callback_id=$2)",
                    tenant_id,
                    callback_id,
                )
                return SupportCallbackRead(None, [], True, True, expired=bool(expired))
            record = _row_dict(raw_record)
            event_rows = await pool.fetch(
                """SELECT * FROM support_callback_events
                   WHERE tenant_id=$1 AND callback_id=$2
                   ORDER BY source_occurred_at DESC, received_at DESC, source_event_id DESC
                   LIMIT $3""",
                tenant_id,
                callback_id,
                bounded_limit + 1,
            )
        except Exception:  # noqa: BLE001 - repository outage remains typed unknown
            return SupportCallbackRead(
                None, [], False, False, reason="support_callback_read_failed"
            )
        events = [_row_dict(row) for row in event_rows]
        complete = len(events) <= bounded_limit
        return SupportCallbackRead(record, events[:bounded_limit], True, complete)


class SupportCallbackIngestionService:
    """Bind callback events to a verified connection and its exact canonical case."""

    def __init__(
        self,
        *,
        callbacks: Optional[SupportCallbackRepository] = None,
        cases: Optional[SupportCaseRepository] = None,
        connections: Any = None,
    ) -> None:
        self._callbacks = callbacks if callbacks is not None else SupportCallbackRepository()
        self._cases = cases if cases is not None else SupportCaseRepository()
        if connections is None:
            from connectors.provider_runtime.connection import ProviderConnectionRepository

            connections = ProviderConnectionRepository()
        self._connections = connections

    async def ingest(
        self, tenant_id: str, connection_id: str, event: SupportCallbackEventInput
    ) -> dict[str, Any]:
        connection = await self._connections.find(connection_id)
        provider_identity = getattr(connection, "provider_identity", None) if connection else None
        verified_at = getattr(connection, "last_verified_at", None) if connection else None
        if (
            connection is None
            or getattr(connection, "tenant_id", None) != tenant_id
            or getattr(connection, "connection_id", connection_id) != connection_id
            or _text(getattr(connection, "state", None)) not in {"verified", "connected"}
            or not isinstance(provider_identity, str)
            or not provider_identity.strip()
            or not isinstance(verified_at, str)
            or not verified_at.strip()
        ):
            raise SupportCallbackAuthorityError("verified tenant provider connection is required")

        case_read = await self._cases.get_case(tenant_id, event.case_id)
        case_record = case_read.record
        if (
            not case_read.available
            or case_read.expired
            or not isinstance(case_record, dict)
            or case_record.get("tenant_id") != tenant_id
            or str(case_record.get("case_id")) != event.case_id
            or case_record.get("source_connection_id") != connection_id
            or case_record.get("source_provider_identity") != provider_identity
        ):
            raise SupportCallbackAuthorityError(
                "canonical support case must belong to the verified provider connection"
            )
        case_event_id = case_record.get("last_source_event_id")
        case_event = next(
            (
                row
                for row in case_read.events
                if isinstance(row, dict) and row.get("source_event_id") == case_event_id
            ),
            None,
        )
        if case_event is None:
            raise SupportCallbackAuthorityError(
                "canonical support case event evidence is unavailable"
            )
        # Validate the existing case event receipts before copying them into the
        # callback's event ledger as its exact case linkage evidence.
        _validated_case_event_evidence(
            case_event,
            connection_id=connection_id,
            provider_identity=provider_identity,
        )
        return await self._callbacks.ingest_event(
            tenant_id=tenant_id,
            case_id=event.case_id,
            connection_id=connection_id,
            provider_identity=provider_identity.strip(),
            connection_verified_at=verified_at.strip(),
            case_record=case_record,
            case_event=case_event,
            event=event,
        )


__all__ = [
    "SupportCallbackAuthorityError",
    "SupportCallbackEventInput",
    "SupportCallbackEventType",
    "SupportCallbackIngestionService",
    "SupportCallbackNotFound",
    "SupportCallbackRead",
    "SupportCallbackRepository",
    "SupportCallbackState",
    "SupportCallbackTransitionError",
    "SupportCallbacksRead",
    "reset_local_support_callback_store",
]
