"""Canonical, tenant-scoped support case identity and lifecycle observations.

Only server-authenticated callers that name an exact tenant-owned provider
connection may ingest a case event. External case IDs are retained as scoped
source keys and never become AETHER case IDs. Case lifecycle is an observed
source assertion; message bodies and arbitrary provider payloads are not stored.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional
from urllib.parse import quote
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from graph.operational_intelligence.models import EvidenceRef
from repositories.repos import get_pool

_LOCAL_ENVIRONMENTS = frozenset({"local", "dev", "test"})
_MAX_EVENTS = 100


class SupportCaseEventType(str, Enum):
    CREATED = "support_case_created"
    UPDATED = "support_case_updated"
    ESCALATED = "support_case_escalated"
    RESOLVED = "support_case_resolved"
    REOPENED = "support_case_reopened"
    CLOSED = "support_case_closed"


class SupportCaseLifecycle(str, Enum):
    OPEN = "open"
    PENDING = "pending"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    CLOSED = "closed"


class SupportCaseEventInput(BaseModel):
    """Allow-listed support event envelope; arbitrary source payload is rejected."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_case_id: str = Field(min_length=1, max_length=256)
    source_event_id: str = Field(min_length=1, max_length=256)
    event_type: SupportCaseEventType
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def _require_timezone_and_normalize(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        return value.astimezone(timezone.utc)

    @field_validator("source_case_id", "source_event_id")
    @classmethod
    def _validate_source_identifiers(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or any(ord(char) < 32 or ord(char) == 127 for char in normalized):
            raise ValueError("source identifiers must be non-empty printable text")
        return normalized


class SupportCaseAuthorityError(RuntimeError):
    """A case event cannot be accepted under the current authority or lifecycle."""


class SupportCaseNotFound(SupportCaseAuthorityError):
    """A tenant-scoped canonical case is unavailable."""


class SupportCaseTransitionError(SupportCaseAuthorityError):
    """A source event conflicts with the accepted lifecycle state."""


@dataclass(frozen=True)
class SupportCaseAuthorityRead:
    record: Optional[dict[str, Any]]
    events: list[dict[str, Any]]
    available: bool
    complete: bool
    expired: bool = False
    reason: Optional[str] = None


_LOCAL_CASES: dict[tuple[str, str, str], dict[str, Any]] = {}
_LOCAL_EVENTS: dict[tuple[str, str, str], dict[str, Any]] = {}


def reset_local_support_case_store() -> None:
    """Clear local-only stores for isolated tests."""
    _LOCAL_CASES.clear()
    _LOCAL_EVENTS.clear()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc).isoformat()
    return None


def _event_refs(
    *,
    connection_id: str,
    provider_identity: str,
    source_event_id: str,
    source_occurred_at: datetime,
    connection_verified_at: Optional[str],
) -> list[dict[str, Any]]:
    refs = [
        EvidenceRef(
            id=source_event_id,
            type="event",
            source=provider_identity,
            observedAt=source_occurred_at.isoformat(),
            uri=(
                "provider-event://"
                f"{quote(connection_id, safe='')}/{quote(source_event_id, safe='')}"
            ),
        ),
        EvidenceRef(
            id=connection_id,
            type="entity",
            source="provider_connections",
            observedAt=_iso(connection_verified_at),
            uri=f"store://provider_connections/{quote(connection_id, safe='')}",
        ),
    ]
    return [ref.model_dump(mode="json", by_alias=True) for ref in refs]


def _next_lifecycle(
    current: Optional[str], event_type: SupportCaseEventType
) -> Optional[SupportCaseLifecycle]:
    """Resolve only explicit lifecycle event semantics; no status inference."""
    if event_type is SupportCaseEventType.CREATED:
        return SupportCaseLifecycle.OPEN if current is None else None
    if current is None:
        raise SupportCaseNotFound("a support_case_created event is required first")
    current_state = SupportCaseLifecycle(current)
    if event_type is SupportCaseEventType.UPDATED:
        return None
    if event_type is SupportCaseEventType.ESCALATED:
        if current_state in {SupportCaseLifecycle.OPEN, SupportCaseLifecycle.PENDING}:
            return SupportCaseLifecycle.ESCALATED
    elif event_type is SupportCaseEventType.RESOLVED:
        if current_state in {
            SupportCaseLifecycle.OPEN,
            SupportCaseLifecycle.PENDING,
            SupportCaseLifecycle.ESCALATED,
        }:
            return SupportCaseLifecycle.RESOLVED
    elif event_type is SupportCaseEventType.REOPENED:
        if current_state is SupportCaseLifecycle.RESOLVED:
            return SupportCaseLifecycle.OPEN
    elif event_type is SupportCaseEventType.CLOSED:
        if current_state is SupportCaseLifecycle.RESOLVED:
            return SupportCaseLifecycle.CLOSED
    raise SupportCaseTransitionError(
        f"{event_type.value} is not valid from support case state {current_state.value}"
    )


def _validate_idempotent_replay(
    record: Any,
    *,
    case_id: str,
    event: SupportCaseEventInput,
) -> None:
    """Reject event-ID reuse that changes case identity or event semantics."""
    existing = _row_dict(record)
    if str(existing.get("case_id")) != case_id:
        raise SupportCaseAuthorityError("source event ID was reused for another case")
    if (
        existing.get("event_type") != event.event_type.value
        or _as_datetime(existing.get("source_occurred_at")) != event.occurred_at
    ):
        raise SupportCaseAuthorityError("source event ID replay payload does not match")


class SupportCaseRepository:
    """Tenant-scoped durable support case identity, lifecycle, and evidence."""

    def __init__(self, pool: Any = None) -> None:
        self._injected_pool = pool

    async def _pool(self) -> Any:
        pool = self._injected_pool
        if pool is None:
            pool = await get_pool()
        if pool is None and os.environ.get("AETHER_ENV", "local").lower() not in _LOCAL_ENVIRONMENTS:
            raise RuntimeError("support case authority requires PostgreSQL outside local/test")
        return pool

    @staticmethod
    def retention_policy() -> tuple[str, int]:
        """Load configured storage retention and fail closed on unknown policy."""
        from shared.privacy.classification import DataClassification, get_rules
        from shared.privacy.retention import get_retention_days
        from shared.storage.manager import policy_for

        storage_policy = policy_for("support_cases")
        classification = DataClassification.CONFIDENTIAL
        rules = get_rules(classification)
        if storage_policy.retention_class != rules.retention.value:
            raise RuntimeError("support case storage and classification retention policies disagree")
        if storage_policy.delete_behavior != "hard_delete":
            raise RuntimeError("support case authority requires hard-delete retention")
        return storage_policy.retention_class, get_retention_days(classification)

    @staticmethod
    async def _has_active_storage_hold(
        tenant_id: str,
        *,
        case_id: str,
        source_case_id: str,
        source_event_ids: list[str],
    ) -> bool:
        """Check canonical tenant holds before hiding or deleting expired cases.

        A case hold protects its event ledger too. Event-scoped holds therefore
        match either the case ID or one of the source event IDs. Pagination is
        exhaustive so a hold beyond the first repository page cannot be missed.
        """
        from repositories.repos import StorageLegalHoldRepository

        repository = StorageLegalHoldRepository()
        offset = 0
        page_size = 500
        case_refs = {case_id, source_case_id}
        event_refs = {case_id, *source_event_ids}
        all_refs = case_refs | event_refs
        while True:
            holds = await repository.find_many(
                filters={"tenant_id": tenant_id, "status": "active"},
                limit=page_size,
                offset=offset,
            )
            for hold in holds:
                resource_type = _safe_text(hold.get("resource_type")) or ""
                if resource_type not in {"", "support_cases", "support_case_events"}:
                    continue
                subject_ref = _safe_text(hold.get("subject_ref")) or ""
                if not subject_ref:
                    return True
                if resource_type == "support_cases" and subject_ref in case_refs:
                    return True
                if resource_type == "support_case_events" and subject_ref in event_refs:
                    return True
                if not resource_type and subject_ref in all_refs:
                    return True
            if len(holds) < page_size:
                return False
            offset += page_size

    async def ingest_event(
        self,
        *,
        tenant_id: str,
        connection_id: str,
        provider_identity: str,
        connection_verified_at: Optional[str],
        event: SupportCaseEventInput,
        observed_at: Optional[datetime] = None,
    ) -> dict[str, Any]:
        if not tenant_id or not connection_id or not provider_identity:
            raise ValueError("tenant, connection, and provider scope are required")
        received_at = observed_at or _now()
        if received_at.tzinfo is None or received_at.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        received_at = received_at.astimezone(timezone.utc)
        retention_class, retention_days = self.retention_policy()
        expires_at = received_at + timedelta(days=retention_days)
        evidence_refs = _event_refs(
            connection_id=connection_id,
            provider_identity=provider_identity,
            source_event_id=event.source_event_id,
            source_occurred_at=event.occurred_at,
            connection_verified_at=connection_verified_at,
        )

        pool = await self._pool()
        if pool is None:
            return self._ingest_local(
                tenant_id=tenant_id,
                connection_id=connection_id,
                provider_identity=provider_identity,
                event=event,
                received_at=received_at,
                retention_class=retention_class,
                expires_at=expires_at,
                evidence_refs=evidence_refs,
            )

        async with pool.acquire() as conn:
            async with conn.transaction():
                record = await conn.fetchrow(
                    """SELECT * FROM support_cases
                       WHERE tenant_id=$1 AND source_connection_id=$2 AND source_case_id=$3
                       FOR UPDATE""",
                    tenant_id,
                    connection_id,
                    event.source_case_id,
                )
                record = _row_dict(record) if record is not None else None
                if record is None and event.event_type is not SupportCaseEventType.CREATED:
                    raise SupportCaseNotFound("a support_case_created event is required first")
                if record is None:
                    canonical_case_id = str(uuid4())
                    created = await conn.fetchrow(
                        """INSERT INTO support_cases (
                               tenant_id, case_id, source_connection_id, source_provider_identity,
                               source_case_id, lifecycle_state, lifecycle_observed_at,
                               first_observed_at, last_observed_at, last_source_event_id,
                               retention_class, retention_expires_at
                           ) VALUES ($1,$2,$3,$4,$5,'open',$6,$7,$7,$8,$9,$10)
                           ON CONFLICT (tenant_id, source_connection_id, source_case_id)
                           DO NOTHING RETURNING *""",
                        tenant_id,
                        canonical_case_id,
                        connection_id,
                        provider_identity,
                        event.source_case_id,
                        event.occurred_at,
                        received_at,
                        event.source_event_id,
                        retention_class,
                        expires_at,
                    )
                    if created is None:
                        record = await conn.fetchrow(
                            """SELECT * FROM support_cases
                               WHERE tenant_id=$1 AND source_connection_id=$2 AND source_case_id=$3
                               FOR UPDATE""",
                            tenant_id,
                            connection_id,
                            event.source_case_id,
                        )
                        record = _row_dict(record) if record is not None else None
                    else:
                        record = _row_dict(created)

                case_id = str(record["case_id"])
                duplicate = await conn.fetchrow(
                    """SELECT case_id, event_type, source_occurred_at
                       FROM support_case_events
                       WHERE tenant_id=$1 AND source_connection_id=$2 AND source_event_id=$3""",
                    tenant_id,
                    connection_id,
                    event.source_event_id,
                )
                if duplicate is not None:
                    _validate_idempotent_replay(duplicate, case_id=case_id, event=event)
                    return _row_dict(record)

                current_state = str(record["lifecycle_state"])
                previous_observed = _as_datetime(record.get("lifecycle_observed_at"))
                stale_event = (
                    previous_observed is not None and event.occurred_at < previous_observed
                )
                next_state = (
                    None
                    if stale_event
                    else _next_lifecycle(current_state, event.event_type)
                )
                applied = not stale_event
                inserted_event = await conn.fetchrow(
                    """INSERT INTO support_case_events (
                           tenant_id, case_id, source_connection_id, source_event_id,
                           event_type, source_occurred_at, received_at, lifecycle_applied,
                           evidence_refs
                       ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb)
                       ON CONFLICT (tenant_id, source_connection_id, source_event_id)
                       DO NOTHING RETURNING case_id""",
                    tenant_id,
                    case_id,
                    connection_id,
                    event.source_event_id,
                    event.event_type.value,
                    event.occurred_at,
                    received_at,
                    applied,
                    json.dumps(evidence_refs),
                )
                if inserted_event is None:
                    # A concurrent ingestion may have won the unique event ID
                    # after the preflight read. Never apply an event to this
                    # case unless its evidence row was inserted or an exact
                    # same-case replay is confirmed.
                    duplicate = await conn.fetchrow(
                        """SELECT case_id, event_type, source_occurred_at
                           FROM support_case_events
                           WHERE tenant_id=$1 AND source_connection_id=$2 AND source_event_id=$3""",
                        tenant_id,
                        connection_id,
                        event.source_event_id,
                    )
                    if duplicate is None:
                        raise SupportCaseAuthorityError(
                            "support case event could not be durably recorded"
                        )
                    _validate_idempotent_replay(duplicate, case_id=case_id, event=event)
                    return record
                await conn.execute(
                    """UPDATE support_cases SET
                           lifecycle_state=COALESCE($3,lifecycle_state),
                           lifecycle_observed_at=CASE WHEN $4 THEN $5 ELSE lifecycle_observed_at END,
                           resolved_at=CASE WHEN $6='resolved' THEN $5
                                            WHEN $6='open' THEN NULL ELSE resolved_at END,
                           closed_at=CASE WHEN $6='closed' THEN $5
                                          WHEN $6='open' THEN NULL ELSE closed_at END,
                           first_observed_at=LEAST(first_observed_at,$7),
                           last_observed_at=GREATEST(last_observed_at,$7),
                           last_source_event_id=CASE WHEN $4 THEN $8 ELSE last_source_event_id END,
                           retention_expires_at=GREATEST(retention_expires_at,$9),
                           updated_at=now()
                       WHERE tenant_id=$1 AND case_id=$2""",
                    tenant_id,
                    case_id,
                    next_state.value if next_state else None,
                    applied,
                    event.occurred_at,
                    next_state.value if next_state else None,
                    received_at,
                    event.source_event_id,
                    expires_at,
                )
                updated = await conn.fetchrow(
                    "SELECT * FROM support_cases WHERE tenant_id=$1 AND case_id=$2",
                    tenant_id,
                    case_id,
                )
                return _row_dict(updated or record)

    def _ingest_local(
        self,
        *,
        tenant_id: str,
        connection_id: str,
        provider_identity: str,
        event: SupportCaseEventInput,
        received_at: datetime,
        retention_class: str,
        expires_at: datetime,
        evidence_refs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        scope = (tenant_id, connection_id, event.source_case_id)
        event_key = (tenant_id, connection_id, event.source_event_id)
        record = _LOCAL_CASES.get(scope)
        if event_key in _LOCAL_EVENTS:
            _validate_idempotent_replay(
                _LOCAL_EVENTS[event_key],
                case_id=str((record or {}).get("case_id")),
                event=event,
            )
            return _row_dict(record or _LOCAL_EVENTS[event_key]["case"])
        if record is None:
            if event.event_type is not SupportCaseEventType.CREATED:
                raise SupportCaseNotFound("a support_case_created event is required first")
            record = {
                "tenant_id": tenant_id,
                "case_id": str(uuid4()),
                "source_connection_id": connection_id,
                "source_provider_identity": provider_identity,
                "source_case_id": event.source_case_id,
                "lifecycle_state": SupportCaseLifecycle.OPEN.value,
                "lifecycle_observed_at": event.occurred_at,
                "first_observed_at": received_at,
                "last_observed_at": received_at,
                "last_source_event_id": event.source_event_id,
                "resolved_at": None,
                "closed_at": None,
                "legal_hold": False,
                "retention_class": retention_class,
                "retention_expires_at": expires_at,
                "created_at": received_at,
                "updated_at": received_at,
            }
            _LOCAL_CASES[scope] = record
        else:
            previous = _as_datetime(record.get("lifecycle_observed_at"))
            stale_event = previous is not None and event.occurred_at < previous
            next_state = (
                None
                if stale_event
                else _next_lifecycle(record["lifecycle_state"], event.event_type)
            )
            if not stale_event:
                record["lifecycle_observed_at"] = event.occurred_at
                record["last_source_event_id"] = event.source_event_id
            if next_state is not None:
                record["lifecycle_state"] = next_state.value
                if next_state is SupportCaseLifecycle.RESOLVED:
                    record["resolved_at"] = event.occurred_at
                elif next_state is SupportCaseLifecycle.CLOSED:
                    record["closed_at"] = event.occurred_at
                elif next_state is SupportCaseLifecycle.OPEN:
                    record["resolved_at"] = None
                    record["closed_at"] = None
            record["last_observed_at"] = max(record["last_observed_at"], received_at)
            record["retention_expires_at"] = max(record["retention_expires_at"], expires_at)
            record["updated_at"] = received_at
        _LOCAL_EVENTS[event_key] = {
            "case_id": record["case_id"],
            "source_event_id": event.source_event_id,
            "event_type": event.event_type.value,
            "source_occurred_at": event.occurred_at,
            "received_at": received_at,
            "lifecycle_applied": not (
                record["lifecycle_observed_at"] is not None
                and event.occurred_at < _as_datetime(record["lifecycle_observed_at"])
            ),
            "evidence_refs": evidence_refs,
            "case": dict(record),
        }
        return _row_dict(record)

    async def get_case(
        self,
        tenant_id: str,
        case_id: str,
        *,
        limit: int = _MAX_EVENTS,
        now: Optional[datetime] = None,
    ) -> SupportCaseAuthorityRead:
        """Read one exact tenant/canonical case ID and its scoped event evidence."""
        limit = min(max(int(limit), 1), _MAX_EVENTS)
        current_time = now or _now()
        if current_time.tzinfo is None or current_time.utcoffset() is None:
            raise ValueError("now must include a timezone")
        pool = await self._pool()
        if pool is None:
            record = next(
                (
                    row
                    for key, row in _LOCAL_CASES.items()
                    if key[0] == tenant_id and row.get("case_id") == case_id
                ),
                None,
            )
            if record is None:
                return SupportCaseAuthorityRead(None, [], True, True)
            expires_at = _as_datetime(record.get("retention_expires_at"))
            scoped_events = [
                row
                for key, row in _LOCAL_EVENTS.items()
                if key[0] == tenant_id and row.get("case_id") == case_id
            ]
            scoped_events.sort(
                key=lambda row: (_as_datetime(row.get("source_occurred_at")) or _now()),
                reverse=True,
            )
            is_expired = expires_at is not None and expires_at <= current_time
            if is_expired and record.get("legal_hold") is not True:
                held = await self._has_active_storage_hold(
                    tenant_id,
                    case_id=case_id,
                    source_case_id=str(record.get("source_case_id") or ""),
                    source_event_ids=[
                        str(row.get("source_event_id"))
                        for row in scoped_events
                        if row.get("source_event_id")
                    ],
                )
                if not held:
                    return SupportCaseAuthorityRead(None, [], True, True, expired=True)
            complete = len(scoped_events) <= limit
            return SupportCaseAuthorityRead(
                _row_dict(record),
                [_row_dict(row) for row in scoped_events[:limit]],
                True,
                complete,
            )

        row = await pool.fetchrow(
            """SELECT * FROM support_cases
               WHERE tenant_id=$1 AND case_id=$2""",
            tenant_id,
            case_id,
        )
        if row is None:
            return SupportCaseAuthorityRead(None, [], True, True)
        record = _row_dict(row)
        expires_at = _as_datetime(record.get("retention_expires_at"))
        event_rows = await pool.fetch(
            """SELECT source_event_id, event_type, source_occurred_at,
                      received_at, lifecycle_applied, evidence_refs
               FROM support_case_events
               WHERE tenant_id=$1 AND case_id=$2
               ORDER BY source_occurred_at DESC, received_at DESC
               LIMIT $3""",
            tenant_id,
            case_id,
            limit + 1,
        )
        is_expired = expires_at is not None and expires_at <= current_time
        if is_expired and record.get("legal_hold") is not True:
            held = await self._has_active_storage_hold(
                tenant_id,
                case_id=case_id,
                source_case_id=str(record.get("source_case_id") or ""),
                source_event_ids=[
                    str(event.get("source_event_id"))
                    for event in event_rows
                    if event.get("source_event_id")
                ],
            )
            if not held:
                return SupportCaseAuthorityRead(None, [], True, True, expired=True)
        complete = len(event_rows) <= limit
        return SupportCaseAuthorityRead(
            record,
            [_row_dict(row) for row in event_rows[:limit]],
            True,
            complete,
        )

    async def purge_expired(self, *, now: Optional[datetime] = None, limit: int = 500) -> int:
        """Hard-delete expired non-held cases and their event evidence."""
        current_time = now or _now()
        if current_time.tzinfo is None or current_time.utcoffset() is None:
            raise ValueError("now must include a timezone")
        pool = await self._pool()
        if pool is None:
            expired_keys: list[tuple[str, str, str]] = []
            maximum = min(max(limit, 1), 5000)
            for key, record in list(_LOCAL_CASES.items()):
                expires_at = _as_datetime(record.get("retention_expires_at"))
                if (
                    len(expired_keys) >= maximum
                    or record.get("legal_hold") is True
                    or expires_at is None
                    or expires_at > current_time
                ):
                    continue
                events = [
                    event
                    for event_key, event in _LOCAL_EVENTS.items()
                    if event_key[0] == record.get("tenant_id")
                    and event.get("case_id") == record.get("case_id")
                ]
                held = await self._has_active_storage_hold(
                    key[0],
                    case_id=str(record.get("case_id")),
                    source_case_id=str(record.get("source_case_id") or ""),
                    source_event_ids=[
                        str(event.get("source_event_id"))
                        for event in events
                        if event.get("source_event_id")
                    ],
                )
                if not held:
                    expired_keys.append(key)
            case_ids = {_LOCAL_CASES[key]["case_id"] for key in expired_keys}
            for key in expired_keys:
                _LOCAL_CASES.pop(key, None)
            for key, event in list(_LOCAL_EVENTS.items()):
                if event.get("case_id") in case_ids:
                    _LOCAL_EVENTS.pop(key, None)
            return len(expired_keys)
        async with pool.acquire() as conn:
            async with conn.transaction():
                expired_rows = await conn.fetch(
                    """SELECT tenant_id, case_id, source_case_id FROM support_cases
                       WHERE retention_expires_at <= $1 AND legal_hold=false
                       ORDER BY retention_expires_at ASC
                       LIMIT $2 FOR UPDATE SKIP LOCKED""",
                    current_time,
                    min(max(limit, 1), 5000),
                )
                deleted = 0
                for raw_case in expired_rows:
                    case_record = _row_dict(raw_case)
                    case_id = str(case_record["case_id"])
                    event_rows = await conn.fetch(
                        """SELECT source_event_id FROM support_case_events
                           WHERE tenant_id=$1 AND case_id=$2""",
                        case_record["tenant_id"],
                        case_id,
                    )
                    held = await self._has_active_storage_hold(
                        str(case_record["tenant_id"]),
                        case_id=case_id,
                        source_case_id=str(case_record.get("source_case_id") or ""),
                        source_event_ids=[
                            str(event.get("source_event_id"))
                            for event in event_rows
                            if event.get("source_event_id")
                        ],
                    )
                    if held:
                        continue
                    result = await conn.execute(
                        """DELETE FROM support_cases
                           WHERE tenant_id=$1 AND case_id=$2
                             AND retention_expires_at <= $3 AND legal_hold=false""",
                        case_record["tenant_id"],
                        case_id,
                        current_time,
                    )
                    try:
                        deleted += int(str(result).split()[-1])
                    except (TypeError, ValueError, IndexError):
                        continue
                return deleted


class SupportCaseIngestionService:
    """Validate provider ownership, then append one scoped lifecycle observation."""

    def __init__(self, *, cases: Optional[SupportCaseRepository] = None, connections: Any = None):
        self._cases = cases if cases is not None else SupportCaseRepository()
        if connections is None:
            from connectors.provider_runtime.connection import ProviderConnectionRepository

            connections = ProviderConnectionRepository()
        self._connections = connections

    async def ingest(
        self,
        tenant_id: str,
        connection_id: str,
        event: SupportCaseEventInput,
    ) -> dict[str, Any]:
        connection = await self._connections.find(connection_id)
        if (
            connection is None
            or getattr(connection, "tenant_id", None) != tenant_id
            or _text(getattr(connection, "state", None)) not in {"verified", "connected"}
        ):
            # Use one failure shape so callers cannot probe another tenant's
            # provider-connection inventory.
            raise SupportCaseAuthorityError("verified tenant provider connection is required")
        provider_identity = _safe_text(getattr(connection, "provider_identity", None))
        verified_at = _safe_text(getattr(connection, "last_verified_at", None))
        if provider_identity is None or verified_at is None:
            raise SupportCaseAuthorityError("verified tenant provider connection is required")
        return await self._cases.ingest_event(
            tenant_id=tenant_id,
            connection_id=connection_id,
            provider_identity=provider_identity,
            connection_verified_at=verified_at,
            event=event,
        )


def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    return str(value.value if isinstance(value, Enum) else value)


def _safe_text(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > 256 or any(ord(char) < 32 for char in value):
        return None
    return value


def _as_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    normalized = _iso(value)
    if normalized is None:
        return None
    return datetime.fromisoformat(normalized)


def _row_dict(row: Any) -> dict[str, Any]:
    result = dict(row)
    for key, value in result.items():
        if isinstance(value, datetime):
            normalized = (
                value.replace(tzinfo=timezone.utc)
                if value.tzinfo is None or value.utcoffset() is None
                else value.astimezone(timezone.utc)
            )
            result[key] = normalized.isoformat()
        elif key == "evidence_refs" and isinstance(value, str):
            try:
                result[key] = json.loads(value)
            except json.JSONDecodeError:
                result[key] = []
    return result


__all__ = [
    "SupportCaseAuthorityError",
    "SupportCaseAuthorityRead",
    "SupportCaseEventInput",
    "SupportCaseEventType",
    "SupportCaseIngestionService",
    "SupportCaseLifecycle",
    "SupportCaseNotFound",
    "SupportCaseRepository",
    "SupportCaseTransitionError",
    "reset_local_support_case_store",
]
