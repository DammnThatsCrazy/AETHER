"""Authenticated immutable ticket/conversation identities bound to support cases."""

from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
from datetime import datetime, timezone
import json
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from journeys.support360.cases import (
    SupportCaseAuthorityError,
    SupportCaseAuthorityRead,
    SupportCaseRepository,
    _as_datetime,
    _event_refs,
    _row_dict,
    _text,
)


class SupportSubjectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["ticket", "conversation"]
    case_id: str = Field(min_length=1, max_length=256)
    source_case_id: str = Field(min_length=1, max_length=256)
    source_subject_id: str = Field(min_length=1, max_length=256)
    source_account_id: str = Field(min_length=1, max_length=256)
    source_event_id: str = Field(min_length=1, max_length=256)
    occurred_at: datetime

    @field_validator(
        "case_id", "source_case_id", "source_subject_id", "source_account_id", "source_event_id"
    )
    @classmethod
    def exact_identifier(cls, value: str) -> str:
        if value != value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("identifiers must be exact printable text")
        return value

    @field_validator("case_id")
    @classmethod
    def canonical_case_id(cls, value: str) -> str:
        if str(UUID(value)) != value:
            raise ValueError("case_id must be an exact canonical UUID")
        return value

    @field_validator("occurred_at")
    @classmethod
    def aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at requires a timezone")
        return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class SupportSubjectRead:
    record: dict[str, Any] | None
    available: bool
    complete: bool


_LOCAL_SUBJECTS: dict[tuple[str, str], dict[str, Any]] = {}


def reset_local_support_subject_store() -> None:
    _LOCAL_SUBJECTS.clear()


def _subject_row(row: Any) -> dict[str, Any]:
    return _row_dict(row)


def _aware_datetime(value: Any) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(timezone.utc)


def _same_binding(existing: dict[str, Any], candidate: dict[str, Any]) -> bool:
    return all(existing.get(key) == candidate.get(key) for key in (
        "tenant_id", "subject_kind", "case_id", "source_connection_id",
        "source_provider_identity", "source_account_id", "source_subject_id", "source_case_id",
        "source_event_id",
    ))


def valid_subject_record(record: Any, tenant_id: str, kind: str, subject_id: str) -> bool:
    if not isinstance(record, dict) or any(
        not isinstance(record.get(key), str)
        or not record[key]
        or record[key] != record[key].strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in record[key])
        for key in (
            "tenant_id", "subject_kind", "subject_id", "case_id", "source_connection_id",
            "source_provider_identity", "source_account_id", "source_subject_id", "source_case_id",
            "source_event_id", "actor_id", "actor_type",
        )
    ):
        return False
    now = datetime.now(timezone.utc)
    timestamps = [_aware_datetime(record.get(key)) for key in (
        "source_occurred_at", "received_at", "connection_verified_at",
    )]
    try:
        canonical_ids = all(str(UUID(record[key])) == record[key] for key in ("subject_id", "case_id"))
    except (ValueError, TypeError):
        canonical_ids = False
    return (
        canonical_ids
        and kind in {"ticket", "conversation"}
        and record["tenant_id"] == tenant_id
        and record["subject_kind"] == kind
        and record["subject_id"] == subject_id
        and all(stamp is not None and stamp <= now for stamp in timestamps)
        and timestamps[0] <= timestamps[1]
        and timestamps[2] <= timestamps[1]
        and record.get("evidence_refs") == _event_refs(
            connection_id=record["source_connection_id"],
            provider_identity=record["source_provider_identity"],
            source_event_id=record["source_event_id"],
            source_occurred_at=timestamps[0],
            connection_verified_at=timestamps[2].isoformat(),
        )
    )


class SupportSubjectRepository:
    def __init__(self, *, cases: SupportCaseRepository | None = None) -> None:
        self.cases = cases if cases is not None else SupportCaseRepository()

    async def bind(self, record: dict[str, Any]) -> dict[str, Any]:
        if not valid_subject_record(
            record, record.get("tenant_id"), record.get("subject_kind"), record.get("subject_id"),
        ):
            raise SupportCaseAuthorityError("support subject binding is invalid")
        pool = await self.cases._pool()
        if pool is None:
            matches = [existing for existing in _LOCAL_SUBJECTS.values() if (
                existing["tenant_id"] == record["tenant_id"]
                and existing["source_connection_id"] == record["source_connection_id"]
                and (
                    (existing["subject_kind"], existing["source_account_id"], existing["source_subject_id"])
                    == (record["subject_kind"], record["source_account_id"], record["source_subject_id"])
                    or (existing["source_account_id"], existing["source_event_id"])
                    == (record["source_account_id"], record["source_event_id"])
                )
            )]
            if matches:
                if len(matches) != 1 or not _same_binding(matches[0], record):
                    raise SupportCaseAuthorityError("support subject binding conflicts")
                if matches[0]["source_event_id"] == record["source_event_id"] and (
                    matches[0]["source_occurred_at"] != record["source_occurred_at"]
                ):
                    raise SupportCaseAuthorityError("support subject event replay conflicts")
                return deepcopy(matches[0])
            _LOCAL_SUBJECTS[(record["tenant_id"], record["subject_id"])] = deepcopy(record)
            return deepcopy(record)
        columns = (
            "tenant_id", "subject_id", "subject_kind", "case_id", "source_connection_id",
            "source_provider_identity", "source_account_id", "source_subject_id", "source_case_id",
            "source_event_id", "actor_id", "actor_type", "source_occurred_at", "received_at",
            "connection_verified_at", "evidence_refs",
        )
        async with pool.acquire() as connection:
            async with connection.transaction():
                case = await connection.fetchrow(
                    """SELECT * FROM support_cases WHERE tenant_id=$1 AND case_id=$2
                       AND source_connection_id=$3 FOR KEY SHARE""",
                    record["tenant_id"], record["case_id"], record["source_connection_id"],
                )
                if case is None or any(case[key] != record[key] for key in (
                    "source_provider_identity", "source_case_id"
                )):
                    raise SupportCaseAuthorityError("support subject case scope conflicts")
                await connection.execute(
                    f"""INSERT INTO support_case_subjects ({', '.join(columns)})
                        VALUES ({', '.join(f'${index}' for index in range(1, len(columns) + 1))})
                        ON CONFLICT DO NOTHING""",
                    *(
                        _aware_datetime(record[key]) if key in {
                            "source_occurred_at", "received_at", "connection_verified_at"
                        } else json.dumps(record[key]) if key == "evidence_refs" else record[key]
                        for key in columns
                    ),
                )
                rows = await connection.fetch(
                    """SELECT * FROM support_case_subjects
                       WHERE tenant_id=$1 AND source_connection_id=$2 AND
                       ((subject_kind=$3 AND source_account_id=$4 AND source_subject_id=$5)
                        OR (source_account_id=$4 AND source_event_id=$6)) LIMIT 3""",
                    record["tenant_id"], record["source_connection_id"], record["subject_kind"],
                    record["source_account_id"], record["source_subject_id"], record["source_event_id"],
                )
                if len(rows) != 1 or not _same_binding(_subject_row(rows[0]), record):
                    raise SupportCaseAuthorityError("support subject binding conflicts")
                existing = _subject_row(rows[0])
                if existing["source_event_id"] == record["source_event_id"] and (
                    _as_datetime(existing["source_occurred_at"])
                    != _as_datetime(record["source_occurred_at"])
                ):
                    raise SupportCaseAuthorityError("support subject event replay conflicts")
                return existing

    async def read(self, tenant_id: str, kind: str, subject_id: str) -> SupportSubjectRead:
        try:
            if str(UUID(subject_id)) != subject_id:
                return SupportSubjectRead(None, True, True)
        except (ValueError, TypeError):
            return SupportSubjectRead(None, True, True)
        pool = await self.cases._pool()
        if pool is None:
            record = _LOCAL_SUBJECTS.get((tenant_id, subject_id))
            return SupportSubjectRead(
                deepcopy(record) if record and record["subject_kind"] == kind else None, True, True
            )
        rows = await pool.fetch(
            """SELECT * FROM support_case_subjects
               WHERE tenant_id=$1 AND subject_kind=$2 AND subject_id=$3 LIMIT 2""",
            tenant_id, kind, subject_id,
        )
        return SupportSubjectRead(_subject_row(rows[0]) if len(rows) == 1 else None, True, len(rows) <= 1)


class SupportSubjectIngestionService:
    def __init__(self, *, subjects: SupportSubjectRepository | None = None, connections: Any = None):
        self.subjects = subjects if subjects is not None else SupportSubjectRepository()
        if connections is None:
            from connectors.provider_runtime.connection import ProviderConnectionRepository

            connections = ProviderConnectionRepository()
        self.connections = connections

    async def ingest(
        self, tenant_id: str, connection_id: str, event: SupportSubjectInput,
        *, actor_id: str, actor_type: str,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        connection = await self.connections.find(connection_id)
        selected_accounts = getattr(connection, "selected_accounts", None)
        if (
            connection is None
            or getattr(connection, "connection_id", None) != connection_id
            or getattr(connection, "tenant_id", None) != tenant_id
            or _text(getattr(connection, "state", None)) not in {"verified", "connected"}
            or not isinstance(selected_accounts, list)
            or event.source_account_id not in selected_accounts
            or _aware_datetime(getattr(connection, "last_verified_at", None)) is None
            or _aware_datetime(connection.last_verified_at) > now
            or event.occurred_at > now
        ):
            raise SupportCaseAuthorityError("verified exact tenant provider account is required")
        read = await self.subjects.cases.get_case(tenant_id, event.case_id)
        if not isinstance(read, SupportCaseAuthorityRead) or not read.available or read.expired:
            raise SupportCaseAuthorityError("support subject case is unavailable")
        case = read.record
        if not isinstance(case, dict) or any(case.get(key) != expected for key, expected in (
            ("tenant_id", tenant_id), ("case_id", event.case_id),
            ("source_connection_id", connection_id),
            ("source_provider_identity", connection.provider_identity),
            ("source_case_id", event.source_case_id),
        )):
            raise SupportCaseAuthorityError("support subject case scope conflicts")
        record = {
            "tenant_id": tenant_id, "subject_id": str(uuid4()), "subject_kind": event.kind,
            "case_id": event.case_id, "source_connection_id": connection_id,
            "source_provider_identity": connection.provider_identity,
            "source_account_id": event.source_account_id,
            "source_subject_id": event.source_subject_id, "source_case_id": event.source_case_id,
            "source_event_id": event.source_event_id, "actor_id": actor_id, "actor_type": actor_type,
            "source_occurred_at": event.occurred_at.isoformat(), "received_at": now.isoformat(),
            "connection_verified_at": _aware_datetime(connection.last_verified_at).isoformat(),
            "evidence_refs": _event_refs(
                connection_id=connection_id, provider_identity=connection.provider_identity,
                source_event_id=event.source_event_id, source_occurred_at=event.occurred_at,
                connection_verified_at=_aware_datetime(connection.last_verified_at).isoformat(),
            ),
        }
        if not valid_subject_record(record, tenant_id, event.kind, record["subject_id"]):
            raise SupportCaseAuthorityError("support subject binding is invalid")
        return await self.subjects.bind(record)
