"""Append-only SLA and journey-link observations for Support360.

The records in this module are canonical support-scoped associations. Every
write is attached to an exact tenant-owned support case and verified provider
connection. Journey references resolve to exact canonical tenant records;
source assertions never become journey truth or an inferred SLA outcome.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
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
_MAX_EVENTS = 200


class SupportCaseContextAuthorityError(RuntimeError):
    """An exact canonical association or event could not be established."""


class SupportCaseContextNotFound(SupportCaseContextAuthorityError):
    """The exact tenant-owned case/connection scope is unavailable."""


class SupportSLAEventType(str, Enum):
    CONTRACT_OBSERVED = "support_sla_contract_observed"
    TIMER_STARTED = "support_sla_timer_started"
    TIMER_PAUSED = "support_sla_timer_paused"
    TIMER_RESUMED = "support_sla_timer_resumed"
    TIMER_MET = "support_sla_timer_met"
    TIMER_BREACHED = "support_sla_timer_breached"
    TIMER_CANCELLED = "support_sla_timer_cancelled"
    CONTRACT_WITHDRAWN = "support_sla_contract_withdrawn"


class SupportSLATimerKind(str, Enum):
    FIRST_RESPONSE = "first_response"
    RESOLUTION = "resolution"
    CUSTOM = "custom"


class SupportSLAEventInput(BaseModel):
    """Source-reported SLA contract or timer event; no local breach inference."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    case_id: str = Field(min_length=1, max_length=64)
    source_sla_id: str = Field(min_length=1, max_length=256)
    source_revision_id: str = Field(min_length=1, max_length=256)
    source_event_id: str = Field(min_length=1, max_length=256)
    event_type: SupportSLAEventType
    timer_kind: SupportSLATimerKind
    custom_timer_name: Optional[str] = Field(default=None, max_length=128)
    source_policy_id: str = Field(min_length=1, max_length=256)
    source_policy_version: str = Field(min_length=1, max_length=128)
    source_timer_state: Optional[str] = Field(
        default=None, pattern="^(not_started|running|paused|met|breached|cancelled|unknown)$"
    )
    target_duration_seconds: Optional[int] = Field(default=None, ge=0, le=315360000)
    due_at: Optional[datetime] = None
    source_observed_at: datetime
    effective_at: datetime
    source_evidence_refs: list[EvidenceRef] = Field(default_factory=list, max_length=20)

    @field_validator("case_id")
    @classmethod
    def _canonical_case_id(cls, value: str) -> str:
        try:
            return str(UUID(value))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("case_id must be a canonical support case UUID") from exc

    @field_validator(
        "source_sla_id",
        "source_revision_id",
        "source_event_id",
        "source_policy_id",
        "source_policy_version",
        "custom_timer_name",
    )
    @classmethod
    def _opaque_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized or any(ord(char) < 32 or ord(char) == 127 for char in normalized):
            raise ValueError("SLA identifiers must be non-empty printable text")
        return normalized

    @field_validator("source_observed_at", "effective_at", "due_at")
    @classmethod
    def _timezone_required(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("SLA timestamps must include a timezone")
        return value.astimezone(timezone.utc) if value is not None else None

    @model_validator(mode="after")
    def _contract_shape(self) -> "SupportSLAEventInput":
        if self.timer_kind is SupportSLATimerKind.CUSTOM and not self.custom_timer_name:
            raise ValueError("custom SLA timers require a typed source name")
        if self.timer_kind is not SupportSLATimerKind.CUSTOM and self.custom_timer_name is not None:
            raise ValueError("custom_timer_name is only valid for custom timers")
        if (
            self.event_type
            in {
                SupportSLAEventType.TIMER_STARTED,
                SupportSLAEventType.TIMER_RESUMED,
            }
            and self.due_at is None
            and self.target_duration_seconds is None
        ):
            raise ValueError(
                "started SLA timers require a source-reported due time or target duration"
            )
        expected_state = {
            SupportSLAEventType.TIMER_STARTED: "running",
            SupportSLAEventType.TIMER_PAUSED: "paused",
            SupportSLAEventType.TIMER_RESUMED: "running",
            SupportSLAEventType.TIMER_MET: "met",
            SupportSLAEventType.TIMER_BREACHED: "breached",
            SupportSLAEventType.TIMER_CANCELLED: "cancelled",
        }.get(self.event_type)
        if expected_state is not None and self.source_timer_state != expected_state:
            raise ValueError("source_timer_state must match the typed SLA timer event")
        return self


class SupportJourneyLinkEventType(str, Enum):
    LINKED = "support_case_journey_linked"
    UNLINKED = "support_case_journey_unlinked"


class SupportJourneyLinkEventInput(BaseModel):
    """Explicit source-reported link to one exact canonical journey."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    case_id: str = Field(min_length=1, max_length=64)
    source_link_id: str = Field(min_length=1, max_length=256)
    source_revision_id: str = Field(min_length=1, max_length=256)
    source_event_id: str = Field(min_length=1, max_length=256)
    journey_id: str = Field(min_length=1, max_length=64)
    event_type: SupportJourneyLinkEventType
    source_observed_at: datetime
    effective_at: datetime
    source_evidence_refs: list[EvidenceRef] = Field(default_factory=list, max_length=20)

    @field_validator("case_id", "journey_id")
    @classmethod
    def _canonical_uuid(cls, value: str) -> str:
        try:
            return str(UUID(value))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("case and journey IDs must be canonical UUIDs") from exc

    @field_validator("source_link_id", "source_revision_id", "source_event_id")
    @classmethod
    def _opaque_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or any(ord(char) < 32 or ord(char) == 127 for char in normalized):
            raise ValueError("journey link identifiers must be non-empty printable text")
        return normalized

    @field_validator("source_observed_at", "effective_at")
    @classmethod
    def _timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("journey link timestamps must include a timezone")
        return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class SupportCaseContextRead:
    events: list[dict[str, Any]]
    available: bool
    complete: bool
    truncated: bool = False
    reason: Optional[str] = None


_LOCAL_CONTEXT_EVENTS: dict[tuple[str, str, str], dict[str, Any]] = {}
_LOCAL_CONTEXT_REVISIONS: dict[tuple[str, str, str, str, str, str, str], str] = {}


def reset_local_support_case_context_store() -> None:
    _LOCAL_CONTEXT_EVENTS.clear()
    _LOCAL_CONTEXT_REVISIONS.clear()


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


def _row_dict(row: Any) -> dict[str, Any]:
    value = dict(row)
    for key, item in value.items():
        if isinstance(item, datetime):
            value[key] = coerce_utc_lenient(item).astimezone(timezone.utc).isoformat()
        elif key in {"payload", "evidence_refs"} and isinstance(item, str):
            try:
                value[key] = json.loads(item)
            except json.JSONDecodeError:
                value[key] = None
    return value


def _source_item_id(kind: str, payload: dict[str, Any]) -> str:
    if kind == "sla":
        return f"{payload['timer_kind']}:{payload['event_type']}"
    return str(payload["journey_id"])


def _validate_exact_event(existing: dict[str, Any], values: dict[str, Any]) -> None:
    immutable = (
        "tenant_id",
        "case_id",
        "source_connection_id",
        "source_provider_identity",
        "context_kind",
        "source_record_id",
        "source_revision_id",
        "source_item_id",
        "event_type",
        "source_event_id",
        "source_observed_at",
        "effective_at",
        "actor_id",
        "actor_type",
        "payload",
    )
    if any(existing.get(key) != values.get(key) for key in immutable):
        raise SupportCaseContextAuthorityError("source event replay payload does not match")


def _authority_evidence(
    *,
    case_record: dict[str, Any],
    connection_id: str,
    provider_identity: str,
    verified_at: str,
    source_event_id: str,
    event_source_observed_at: datetime,
    event_id: str,
    actor_id: str,
    actor_type: str,
    kind: str,
    source_record_id: str,
    source_revision_id: str,
    payload: dict[str, Any],
    source_refs: list[EvidenceRef],
    received_at: datetime,
) -> list[dict[str, Any]]:
    case_id = str(case_record["case_id"])
    refs = [
        EvidenceRef(
            id=case_id,
            type="entity",
            source="support_cases",
            observedAt=_iso(case_record.get("last_observed_at")),
            uri=f"store://support_cases/{quote(case_id, safe='')}",
        ),
        EvidenceRef(
            id=connection_id,
            type="entity",
            source="provider_connections",
            observedAt=verified_at,
            uri=f"store://provider_connections/{quote(connection_id, safe='')}",
        ),
        EvidenceRef(
            id=source_event_id,
            type="event",
            source=provider_identity,
            observedAt=event_source_observed_at.isoformat(),
            uri=f"provider-event://{quote(connection_id, safe='')}/{quote(source_event_id, safe='')}",
        ),
        EvidenceRef(
            id=actor_id,
            type="entity",
            source="authenticated_principal",
            observedAt=received_at.isoformat(),
            uri=f"actor://{quote(actor_type, safe='')}/{quote(actor_id, safe='')}",
        ),
        EvidenceRef(
            id=event_id,
            type="event",
            source="support_case_context_events",
            observedAt=received_at.isoformat(),
            uri=f"store://support_case_context_events/{quote(event_id, safe='')}",
        ),
        EvidenceRef(
            id=source_record_id,
            type="event",
            source=provider_identity,
            observedAt=event_source_observed_at.isoformat(),
            uri=f"provider-record://{quote(connection_id, safe='')}/{quote(source_record_id, safe='')}/{quote(source_revision_id, safe='')}",
        ),
    ]
    refs.extend(source_refs)
    if kind == "journey_links":
        journey_id = str(payload["journey_id"])
        refs.append(
            EvidenceRef(
                id=journey_id,
                type="entity",
                source="journey_versions",
                uri=f"store://journey_versions/{quote(journey_id, safe='')}",
            )
        )
    return [ref.model_dump(mode="json", by_alias=True, exclude_none=True) for ref in refs]


class SupportCaseContextRepository:
    """Durable append-only, exact case/connection-scoped event log."""

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
            raise RuntimeError(
                "support case context authority requires PostgreSQL outside local/test"
            )
        return pool

    async def append(
        self,
        *,
        kind: str,
        tenant_id: str,
        case_record: dict[str, Any],
        connection_id: str,
        provider_identity: str,
        connection_verified_at: str,
        event: BaseModel,
        actor_id: str,
        actor_type: str,
        observed_at: Optional[datetime] = None,
    ) -> dict[str, Any]:
        if kind not in {"sla", "journey_links"}:
            raise ValueError("unknown support case context authority kind")
        payload = event.model_dump(mode="json", exclude_none=True)
        if (
            not tenant_id
            or case_record.get("tenant_id") != tenant_id
            or payload.get("case_id") != case_record.get("case_id")
            or case_record.get("source_connection_id") != connection_id
            or case_record.get("source_provider_identity") != provider_identity
            or not actor_id.strip()
            or not actor_type.strip()
        ):
            raise SupportCaseContextAuthorityError(
                "exact case, provider, and principal scope is required"
            )
        received_at = observed_at or datetime.now(timezone.utc)
        if received_at.tzinfo is None or received_at.utcoffset() is None:
            raise ValueError("received_at must include a timezone")
        received_at = received_at.astimezone(timezone.utc)
        event_id = str(uuid4())
        source_record_id = str(
            payload.get("source_sla_id")
            or payload.get("source_link_id")
        )
        source_revision_id = str(payload["source_revision_id"])
        source_item_id = _source_item_id(kind, payload)
        event_type = str(payload["event_type"])
        source_event_id = str(payload["source_event_id"])
        source_observed_at = event.source_observed_at
        source_refs = list(getattr(event, "source_evidence_refs", []))
        for reference in source_refs:
            if (
                not reference.id
                or not reference.source
                or reference.source != provider_identity
                or reference.uri is not None
                or _iso(reference.observedAt) is None
                or "@" in reference.id
                or any(char.isspace() for char in reference.id)
            ):
                raise SupportCaseContextAuthorityError(
                    "source evidence must be metadata-only and namespaced to the verified provider"
                )
        evidence_refs = _authority_evidence(
            case_record=case_record,
            connection_id=connection_id,
            provider_identity=provider_identity,
            verified_at=connection_verified_at,
            source_event_id=source_event_id,
            event_source_observed_at=source_observed_at,
            event_id=event_id,
            actor_id=actor_id,
            actor_type=actor_type,
            kind=kind,
            source_record_id=source_record_id,
            source_revision_id=source_revision_id,
            payload=payload,
            source_refs=source_refs,
            received_at=received_at,
        )
        values = {
            "tenant_id": tenant_id,
            "context_event_id": event_id,
            "case_id": str(case_record["case_id"]),
            "source_connection_id": connection_id,
            "source_provider_identity": provider_identity,
            "context_kind": kind,
            "source_record_id": source_record_id,
            "source_revision_id": source_revision_id,
            "source_item_id": source_item_id,
            "source_event_id": source_event_id,
            "event_type": event_type,
            "actor_id": actor_id,
            "actor_type": actor_type,
            "source_observed_at": source_observed_at.isoformat(),
            "effective_at": event.effective_at.isoformat(),
            "received_at": received_at.isoformat(),
            "payload": payload,
            "evidence_refs": evidence_refs,
        }
        pool = await self._pool()
        if pool is None:
            return self._append_local(values)
        async with pool.acquire() as conn:
            async with conn.transaction():
                existing = await conn.fetchrow(
                    """SELECT * FROM support_case_context_events
                       WHERE tenant_id=$1 AND source_connection_id=$2 AND source_event_id=$3""",
                    tenant_id,
                    connection_id,
                    source_event_id,
                )
                if existing is not None:
                    row = _row_dict(existing)
                    _validate_exact_event(row, values)
                    return row
                revision = await conn.fetchrow(
                    """SELECT context_event_id FROM support_case_context_events
                       WHERE tenant_id=$1 AND case_id=$2 AND source_connection_id=$3
                         AND context_kind=$4 AND source_record_id=$5
                         AND source_revision_id=$6 AND source_item_id=$7""",
                    tenant_id,
                    values["case_id"],
                    connection_id,
                    kind,
                    source_record_id,
                    source_revision_id,
                    source_item_id,
                )
                if revision is not None:
                    raise SupportCaseContextAuthorityError(
                        "source record revision already exists for this exact item"
                    )
                inserted = await conn.fetchrow(
                    """INSERT INTO support_case_context_events (
                           tenant_id, context_event_id, case_id, source_connection_id,
                           source_provider_identity, context_kind, source_record_id,
                           source_revision_id, source_item_id, source_event_id, event_type,
                           actor_id, actor_type, source_observed_at, effective_at,
                           received_at, payload, evidence_refs
                       ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17::jsonb,$18::jsonb)
                       ON CONFLICT DO NOTHING RETURNING *""",
                    tenant_id,
                    event_id,
                    values["case_id"],
                    connection_id,
                    provider_identity,
                    kind,
                    source_record_id,
                    source_revision_id,
                    source_item_id,
                    source_event_id,
                    event_type,
                    actor_id,
                    actor_type,
                    event.source_observed_at,
                    event.effective_at,
                    received_at,
                    json.dumps(payload),
                    json.dumps(evidence_refs),
                )
                if inserted is not None:
                    return _row_dict(inserted)
                duplicate = await conn.fetchrow(
                    """SELECT * FROM support_case_context_events
                       WHERE tenant_id=$1 AND source_connection_id=$2 AND source_event_id=$3""",
                    tenant_id,
                    connection_id,
                    source_event_id,
                )
                if duplicate is not None:
                    row = _row_dict(duplicate)
                    _validate_exact_event(row, values)
                    return row
                raise SupportCaseContextAuthorityError(
                    "source record revision conflicts with an existing event"
                )

    @staticmethod
    def _append_local(values: dict[str, Any]) -> dict[str, Any]:
        key = (
            str(values["tenant_id"]),
            str(values["source_connection_id"]),
            str(values["source_event_id"]),
        )
        revision_key = (
            str(values["tenant_id"]),
            str(values["case_id"]),
            str(values["source_connection_id"]),
            str(values["context_kind"]),
            str(values["source_record_id"]),
            str(values["source_revision_id"]),
            str(values["source_item_id"]),
        )
        existing = _LOCAL_CONTEXT_EVENTS.get(key)
        if existing is not None:
            _validate_exact_event(existing, values)
            return dict(existing)
        if revision_key in _LOCAL_CONTEXT_REVISIONS:
            raise SupportCaseContextAuthorityError(
                "source record revision already exists for this exact item"
            )
        _LOCAL_CONTEXT_EVENTS[key] = dict(values)
        _LOCAL_CONTEXT_REVISIONS[revision_key] = str(values["source_event_id"])
        return dict(values)

    async def list_for_case(
        self,
        tenant_id: str,
        case_id: str,
        *,
        connection_id: str,
        kind: str,
        limit: int = _MAX_EVENTS,
    ) -> SupportCaseContextRead:
        bounded = min(max(int(limit), 1), _MAX_EVENTS)
        pool = await self._pool()
        if pool is None:
            rows = [
                row
                for row in _LOCAL_CONTEXT_EVENTS.values()
                if row.get("tenant_id") == tenant_id
                and row.get("case_id") == case_id
                and row.get("source_connection_id") == connection_id
                and row.get("context_kind") == kind
            ]
            rows.sort(
                key=lambda row: (
                    str(row.get("effective_at") or ""),
                    str(row.get("received_at") or ""),
                ),
                reverse=True,
            )
            truncated = len(rows) > bounded
            return SupportCaseContextRead(
                [dict(row) for row in rows[:bounded]], True, not truncated, truncated
            )
        try:
            rows = await pool.fetch(
                """SELECT * FROM support_case_context_events
                   WHERE tenant_id=$1 AND case_id=$2 AND source_connection_id=$3 AND context_kind=$4
                   ORDER BY effective_at DESC, received_at DESC, context_event_id DESC LIMIT $5""",
                tenant_id,
                case_id,
                connection_id,
                kind,
                bounded + 1,
            )
        except Exception:  # noqa: BLE001 - caller emits typed unknown slot
            return SupportCaseContextRead(
                [], False, False, reason="support_case_context_read_unavailable"
            )
        truncated = len(rows) > bounded
        return SupportCaseContextRead(
            [_row_dict(row) for row in rows[:bounded]], True, not truncated, truncated
        )


class SupportCaseContextIngestionService:
    """Validate provider connection, canonical case and referenced authorities."""

    def __init__(
        self,
        *,
        repository: Optional[SupportCaseContextRepository] = None,
        cases: Optional[SupportCaseRepository] = None,
        connections: Any = None,
        journeys: Any = None,
    ) -> None:
        self._repository = repository or SupportCaseContextRepository()
        self._cases = cases or SupportCaseRepository()
        if connections is None:
            from connectors.provider_runtime.connection import ProviderConnectionRepository

            connections = ProviderConnectionRepository()
        self._connections = connections
        self._journeys = journeys

    async def ingest(
        self,
        kind: str,
        tenant_id: str,
        connection_id: str,
        event: BaseModel,
        *,
        actor_id: str,
        actor_type: str,
    ) -> dict[str, Any]:
        if kind not in {"sla", "journey_links"}:
            raise ValueError("unknown support case context authority kind")
        connection = await self._connections.find(connection_id)
        connection_tenant = _connection_value(connection, "tenant_id")
        connection_state = _connection_value(connection, "state")
        provider_identity = _connection_value(connection, "provider_identity")
        verified_at = _connection_value(connection, "last_verified_at")
        if (
            connection is None
            or connection_tenant != tenant_id
            or connection_state not in {"verified", "connected"}
            or not provider_identity
            or not verified_at
        ):
            raise SupportCaseContextAuthorityError(
                "verified tenant provider connection is required"
            )
        case_id = str(getattr(event, "case_id", ""))
        read = await self._cases.get_case(tenant_id, case_id, limit=1)
        case_record = read.record if read.available else None
        if (
            not isinstance(case_record, dict)
            or case_record.get("tenant_id") != tenant_id
            or str(case_record.get("case_id")) != case_id
            or case_record.get("source_connection_id") != connection_id
            or case_record.get("source_provider_identity") != provider_identity
            or read.expired
        ):
            raise SupportCaseContextNotFound("exact tenant-owned support case is unavailable")
        if kind == "journey_links":
            if self._journeys is None:
                from journeys.measurement.repositories.journey_repo import JourneyRepository

                self._journeys = JourneyRepository()
            journey_id = str(getattr(event, "journey_id", ""))
            try:
                journey = await self._journeys.get_current(tenant_id, journey_id)
            except Exception as exc:  # noqa: BLE001 - exact journey authority required
                raise SupportCaseContextAuthorityError(
                    "canonical journey authority is unavailable"
                ) from exc
            if (
                not isinstance(journey, dict)
                or journey.get("tenant_id") != tenant_id
                or str(journey.get("journey_id")) != journey_id
                or journey.get("is_current") is not True
            ):
                raise SupportCaseContextAuthorityError(
                    "journey link requires an exact current tenant-owned journey"
                )
        return await self._repository.append(
            kind=kind,
            tenant_id=tenant_id,
            case_record=case_record,
            connection_id=connection_id,
            provider_identity=provider_identity,
            connection_verified_at=verified_at,
            event=event,
            actor_id=actor_id,
            actor_type=actor_type,
        )


def _connection_value(connection: Any, field: str) -> Optional[str]:
    value = (
        connection.get(field) if isinstance(connection, dict) else getattr(connection, field, None)
    )
    if value is None:
        return None
    normalized = str(value.value if isinstance(value, Enum) else value).strip()
    return normalized or None


__all__ = [
    "SupportCaseContextAuthorityError",
    "SupportCaseContextIngestionService",
    "SupportCaseContextNotFound",
    "SupportCaseContextRead",
    "SupportCaseContextRepository",
    "SupportJourneyLinkEventInput",
    "SupportJourneyLinkEventType",
    "SupportSLAEventInput",
    "SupportSLAEventType",
    "SupportSLATimerKind",
    "reset_local_support_case_context_store",
]
