"""Canonical, append-only support case agent assignment observations.

Assignment events are accepted only for an exact tenant-owned support case and
verified provider connection. Agent references must already resolve to exact
canonical ``agent`` entities in that same tenant. These records describe source
assignments and handoffs; they do not assert agent execution or business outcome.
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
from repositories.repos import EntityRepository, get_pool
from shared.temporal.instant import coerce_utc_lenient

_LOCAL_ENVIRONMENTS = frozenset({"local", "dev", "test"})
_MAX_ASSIGNMENT_EVENTS = 100


class SupportAgentAssignmentEventType(str, Enum):
    ASSIGNED = "support_agent_assigned"
    HANDOFF = "support_agent_handoff"
    UNASSIGNED = "support_agent_unassigned"


class SupportAgentAssignmentAuthorityError(RuntimeError):
    """An assignment cannot be accepted or trusted under its current scope."""


class SupportAgentAssignmentNotFound(SupportAgentAssignmentAuthorityError):
    """The exact tenant-owned support case is not available."""


class SupportAgentAssignmentEventInput(BaseModel):
    """Minimal source assignment revision; actor and tenant come from auth context."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    case_id: str = Field(min_length=1, max_length=64)
    source_assignment_id: str = Field(min_length=1, max_length=256)
    source_revision_id: str = Field(min_length=1, max_length=256)
    source_event_id: str = Field(min_length=1, max_length=256)
    event_type: SupportAgentAssignmentEventType
    agent_entity_id: Optional[str] = Field(default=None, max_length=256)
    previous_agent_entity_id: Optional[str] = Field(default=None, max_length=256)
    source_observed_at: datetime
    effective_at: datetime

    @field_validator("case_id")
    @classmethod
    def _canonical_case_id(cls, value: str) -> str:
        try:
            return str(UUID(value))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("case_id must be a canonical support case UUID") from exc

    @field_validator(
        "source_assignment_id",
        "source_revision_id",
        "source_event_id",
        "agent_entity_id",
        "previous_agent_entity_id",
    )
    @classmethod
    def _safe_identifier(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized or any(ord(char) < 32 or ord(char) == 127 for char in normalized):
            raise ValueError("assignment identifiers must be non-empty printable text")
        return normalized

    @field_validator("source_observed_at", "effective_at")
    @classmethod
    def _require_timezone_and_normalize(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("assignment timestamps must include a timezone")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _validate_assignment_transition_shape(self) -> "SupportAgentAssignmentEventInput":
        if self.event_type is SupportAgentAssignmentEventType.ASSIGNED:
            valid = self.agent_entity_id is not None and self.previous_agent_entity_id is None
        elif self.event_type is SupportAgentAssignmentEventType.HANDOFF:
            valid = (
                self.agent_entity_id is not None
                and self.previous_agent_entity_id is not None
                and self.agent_entity_id != self.previous_agent_entity_id
            )
        else:
            valid = self.agent_entity_id is None and self.previous_agent_entity_id is not None
        if not valid:
            raise ValueError("agent entity references do not match the assignment event type")
        return self


@dataclass(frozen=True)
class SupportAgentAssignmentRead:
    events: list[dict[str, Any]]
    available: bool
    complete: bool
    truncated: bool = False
    scope_known: bool = True
    reason: Optional[str] = None


_LOCAL_ASSIGNMENT_EVENTS: dict[tuple[str, str, str], dict[str, Any]] = {}
_LOCAL_ASSIGNMENT_REVISIONS: dict[tuple[str, str, str, str], str] = {}


def reset_local_support_agent_assignment_store() -> None:
    """Clear local-only assignment rows for isolated tests."""
    _LOCAL_ASSIGNMENT_EVENTS.clear()
    _LOCAL_ASSIGNMENT_REVISIONS.clear()


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


def _evidence_refs(
    *,
    tenant_id: str,
    case_record: dict[str, Any],
    connection_id: str,
    provider_identity: str,
    connection_verified_at: str,
    event: SupportAgentAssignmentEventInput,
    assignment_event_id: str,
    assigning_principal_id: str,
    assigning_principal_type: str,
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
            observedAt=connection_verified_at,
            uri=f"store://provider_connections/{quote(connection_id, safe='')}",
        ),
        EvidenceRef(
            id=event.source_event_id,
            type="event",
            source=provider_identity,
            observedAt=event.source_observed_at.isoformat(),
            uri=(
                "provider-event://"
                f"{quote(connection_id, safe='')}/{quote(event.source_event_id, safe='')}"
            ),
        ),
        EvidenceRef(
            id=event.source_assignment_id,
            type="event",
            source=provider_identity,
            observedAt=event.source_observed_at.isoformat(),
            uri=(
                "provider-record://"
                f"{quote(connection_id, safe='')}/"
                f"{quote(event.source_assignment_id, safe='')}/"
                f"{quote(event.source_revision_id, safe='')}"
            ),
        ),
        EvidenceRef(
            id=assigning_principal_id,
            type="entity",
            source="authenticated_principal",
            observedAt=received_at.isoformat(),
            uri=(
                f"actor://{quote(assigning_principal_type, safe='')}/"
                f"{quote(assigning_principal_id, safe='')}"
            ),
        ),
        EvidenceRef(
            id=assignment_event_id,
            type="event",
            source="support_case_agent_assignment_events",
            observedAt=received_at.isoformat(),
            uri=(
                "store://support_case_agent_assignment_events/"
                f"{quote(assignment_event_id, safe='')}"
            ),
        ),
    ]
    for agent_id in (event.agent_entity_id, event.previous_agent_entity_id):
        if agent_id:
            refs.append(
                EvidenceRef(
                    id=agent_id,
                    type="entity",
                    source="entities",
                    observedAt=None,
                    uri=f"store://entities/{quote(agent_id, safe='')}",
                )
            )
    return [ref.model_dump(mode="json", by_alias=True) for ref in refs]


def _replay_matches(
    existing: dict[str, Any],
    *,
    case_id: str,
    event: SupportAgentAssignmentEventInput,
    assigning_principal_id: str,
    assigning_principal_type: str,
) -> bool:
    return (
        str(existing.get("case_id")) == case_id
        and existing.get("source_assignment_id") == event.source_assignment_id
        and existing.get("source_revision_id") == event.source_revision_id
        and existing.get("event_type") == event.event_type.value
        and existing.get("agent_entity_id") == event.agent_entity_id
        and existing.get("previous_agent_entity_id") == event.previous_agent_entity_id
        and _as_datetime(existing.get("source_observed_at")) == event.source_observed_at
        and _as_datetime(existing.get("effective_at")) == event.effective_at
        and existing.get("assigning_principal_id") == assigning_principal_id
        and existing.get("assigning_principal_type") == assigning_principal_type
    )


class SupportAgentAssignmentRepository:
    """Durable append-only assignment ledger scoped to canonical cases."""

    def __init__(self, pool: Any = None) -> None:
        self._injected_pool = pool

    async def _pool(self) -> Any:
        pool = self._injected_pool
        if pool is None:
            pool = await get_pool()
        if pool is None and os.environ.get("AETHER_ENV", "local").lower() not in _LOCAL_ENVIRONMENTS:
            raise RuntimeError("support agent assignment authority requires PostgreSQL outside local/test")
        return pool

    async def append_event(
        self,
        *,
        tenant_id: str,
        case_record: dict[str, Any],
        connection_id: str,
        provider_identity: str,
        connection_verified_at: str,
        event: SupportAgentAssignmentEventInput,
        assigning_principal_id: str,
        assigning_principal_type: str,
        observed_at: Optional[datetime] = None,
    ) -> dict[str, Any]:
        case_id = str(case_record.get("case_id") or "")
        if (
            not tenant_id
            or not case_id
            or case_record.get("tenant_id") != tenant_id
            or case_id != event.case_id
            or case_record.get("source_connection_id") != connection_id
            or case_record.get("source_provider_identity") != provider_identity
            or not assigning_principal_id
            or not assigning_principal_type
        ):
            raise SupportAgentAssignmentAuthorityError("exact case, provider, and principal scope is required")
        received_at = observed_at or _now()
        if received_at.tzinfo is None or received_at.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        received_at = received_at.astimezone(timezone.utc)
        assignment_event_id = str(uuid4())
        refs = _evidence_refs(
            tenant_id=tenant_id,
            case_record=case_record,
            connection_id=connection_id,
            provider_identity=provider_identity,
            connection_verified_at=connection_verified_at,
            event=event,
            assignment_event_id=assignment_event_id,
            assigning_principal_id=assigning_principal_id,
            assigning_principal_type=assigning_principal_type,
            received_at=received_at,
        )
        values = {
            "tenant_id": tenant_id,
            "assignment_event_id": assignment_event_id,
            "case_id": case_id,
            "source_connection_id": connection_id,
            "source_provider_identity": provider_identity,
            "source_assignment_id": event.source_assignment_id,
            "source_revision_id": event.source_revision_id,
            "source_event_id": event.source_event_id,
            "event_type": event.event_type.value,
            "agent_entity_id": event.agent_entity_id,
            "previous_agent_entity_id": event.previous_agent_entity_id,
            "assigning_principal_id": assigning_principal_id,
            "assigning_principal_type": assigning_principal_type,
            "source_observed_at": event.source_observed_at.isoformat(),
            "effective_at": event.effective_at.isoformat(),
            "received_at": received_at.isoformat(),
            "evidence_refs": refs,
        }
        pool = await self._pool()
        if pool is None:
            return self._append_local(values, event=event)

        async with pool.acquire() as conn:
            async with conn.transaction():
                existing = await conn.fetchrow(
                    """SELECT * FROM support_case_agent_assignment_events
                       WHERE tenant_id=$1 AND source_connection_id=$2 AND source_event_id=$3""",
                    tenant_id,
                    connection_id,
                    event.source_event_id,
                )
                if existing is not None:
                    return self._validated_replay(
                        _row_dict(existing), case_id, event,
                        assigning_principal_id, assigning_principal_type,
                    )
                revision = await conn.fetchrow(
                    """SELECT assignment_event_id FROM support_case_agent_assignment_events
                       WHERE tenant_id=$1 AND case_id=$2 AND source_connection_id=$3
                         AND source_assignment_id=$4 AND source_revision_id=$5""",
                    tenant_id,
                    case_id,
                    connection_id,
                    event.source_assignment_id,
                    event.source_revision_id,
                )
                if revision is not None:
                    raise SupportAgentAssignmentAuthorityError(
                        "source assignment revision was already recorded with another event"
                    )
                inserted = await conn.fetchrow(
                    """INSERT INTO support_case_agent_assignment_events (
                           tenant_id, assignment_event_id, case_id, source_connection_id,
                           source_provider_identity, source_assignment_id, source_revision_id,
                           source_event_id, event_type, agent_entity_id,
                           previous_agent_entity_id, assigning_principal_id,
                           assigning_principal_type, source_observed_at, effective_at,
                           received_at, evidence_refs
                       ) VALUES (
                           $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17::jsonb
                       ) ON CONFLICT DO NOTHING RETURNING *""",
                    tenant_id,
                    assignment_event_id,
                    case_id,
                    connection_id,
                    provider_identity,
                    event.source_assignment_id,
                    event.source_revision_id,
                    event.source_event_id,
                    event.event_type.value,
                    event.agent_entity_id,
                    event.previous_agent_entity_id,
                    assigning_principal_id,
                    assigning_principal_type,
                    event.source_observed_at,
                    event.effective_at,
                    received_at,
                    json.dumps(refs),
                )
                if inserted is not None:
                    return _row_dict(inserted)
                duplicate = await conn.fetchrow(
                    """SELECT * FROM support_case_agent_assignment_events
                       WHERE tenant_id=$1 AND source_connection_id=$2 AND source_event_id=$3""",
                    tenant_id,
                    connection_id,
                    event.source_event_id,
                )
                if duplicate is not None:
                    return self._validated_replay(
                        _row_dict(duplicate), case_id, event,
                        assigning_principal_id, assigning_principal_type,
                    )
                raise SupportAgentAssignmentAuthorityError(
                    "source assignment revision conflicts with an existing record"
                )

    def _validated_replay(
        self,
        existing: dict[str, Any],
        case_id: str,
        event: SupportAgentAssignmentEventInput,
        assigning_principal_id: str,
        assigning_principal_type: str,
    ) -> dict[str, Any]:
        if not _replay_matches(
            existing,
            case_id=case_id,
            event=event,
            assigning_principal_id=assigning_principal_id,
            assigning_principal_type=assigning_principal_type,
        ):
            raise SupportAgentAssignmentAuthorityError("source event ID replay payload does not match")
        return existing

    def _append_local(
        self,
        values: dict[str, Any],
        *,
        event: SupportAgentAssignmentEventInput,
    ) -> dict[str, Any]:
        tenant_id = str(values["tenant_id"])
        connection_id = str(values["source_connection_id"])
        event_id = event.source_event_id
        key = (tenant_id, connection_id, event_id)
        revision_key = (
            tenant_id,
            str(values["case_id"]),
            connection_id,
            event.source_assignment_id,
            event.source_revision_id,
        )
        existing = _LOCAL_ASSIGNMENT_EVENTS.get(key)
        if existing is not None:
            return self._validated_replay(
                dict(existing),
                str(values["case_id"]),
                event,
                str(values["assigning_principal_id"]),
                str(values["assigning_principal_type"]),
            )
        conflicting_event = _LOCAL_ASSIGNMENT_REVISIONS.get(revision_key)
        if conflicting_event is not None:
            raise SupportAgentAssignmentAuthorityError(
                "source assignment revision was already recorded with another event"
            )
        _LOCAL_ASSIGNMENT_EVENTS[key] = dict(values)
        _LOCAL_ASSIGNMENT_REVISIONS[revision_key] = event_id
        return dict(values)

    async def list_for_case(
        self,
        tenant_id: str,
        case_id: str,
        *,
        connection_id: str,
        limit: int = _MAX_ASSIGNMENT_EVENTS,
    ) -> SupportAgentAssignmentRead:
        """Read a bounded, exact tenant/case/connection event history."""
        bounded_limit = min(max(int(limit), 1), _MAX_ASSIGNMENT_EVENTS)
        pool = await self._pool()
        if pool is None:
            rows = [
                dict(row)
                for (row_tenant, row_connection, _event_id), row in _LOCAL_ASSIGNMENT_EVENTS.items()
                if row_tenant == tenant_id
                and row_connection == connection_id
                and row.get("case_id") == case_id
            ]
            rows.sort(
                key=lambda row: (
                    _as_datetime(row.get("effective_at")) or datetime.min.replace(tzinfo=timezone.utc),
                    _as_datetime(row.get("received_at")) or datetime.min.replace(tzinfo=timezone.utc),
                    str(row.get("assignment_event_id") or ""),
                ),
                reverse=True,
            )
            truncated = len(rows) > bounded_limit
            return SupportAgentAssignmentRead(
                events=[_row_dict(row) for row in rows[:bounded_limit]],
                available=True,
                complete=not truncated,
                truncated=truncated,
            )

        try:
            rows = await pool.fetch(
                """SELECT * FROM support_case_agent_assignment_events
                   WHERE tenant_id=$1 AND case_id=$2 AND source_connection_id=$3
                   ORDER BY effective_at DESC, received_at DESC, assignment_event_id DESC
                   LIMIT $4""",
                tenant_id,
                case_id,
                connection_id,
                bounded_limit + 1,
            )
        except Exception:  # noqa: BLE001 - caller translates outages to unknown
            return SupportAgentAssignmentRead(
                events=[], available=False, complete=False, reason="assignment_read_unavailable"
            )
        truncated = len(rows) > bounded_limit
        return SupportAgentAssignmentRead(
            events=[_row_dict(row) for row in rows[:bounded_limit]],
            available=True,
            complete=not truncated,
            truncated=truncated,
        )


class SupportAgentAssignmentIngestionService:
    """Validate all canonical joins before appending one observed assignment."""

    def __init__(
        self,
        *,
        assignments: Optional[SupportAgentAssignmentRepository] = None,
        cases: Optional[SupportCaseRepository] = None,
        connections: Any = None,
        entities: Any = None,
    ) -> None:
        self._assignments = assignments or SupportAgentAssignmentRepository()
        self._cases = cases or SupportCaseRepository()
        if connections is None:
            from connectors.provider_runtime.connection import ProviderConnectionRepository

            connections = ProviderConnectionRepository()
        self._connections = connections
        self._entities = entities or EntityRepository()

    async def ingest(
        self,
        tenant_id: str,
        connection_id: str,
        event: SupportAgentAssignmentEventInput,
        *,
        assigning_principal_id: str,
        assigning_principal_type: str = "tenant_user",
    ) -> dict[str, Any]:
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
            raise SupportAgentAssignmentAuthorityError("verified tenant provider connection is required")

        case_read = await self._cases.get_case(tenant_id, event.case_id, limit=1)
        case_record = case_read.record if case_read.available else None
        if (
            not isinstance(case_record, dict)
            or case_record.get("tenant_id") != tenant_id
            or str(case_record.get("case_id")) != event.case_id
            or case_record.get("source_connection_id") != connection_id
            or case_record.get("source_provider_identity") != provider_identity
            or case_read.expired
        ):
            raise SupportAgentAssignmentNotFound("exact tenant-owned support case is unavailable")

        agent_ids = {
            value
            for value in (event.agent_entity_id, event.previous_agent_entity_id)
            if value is not None
        }
        try:
            entities, truncated = await self._entities.find_many_for_tenant_entity_ids(
                tenant_id,
                sorted(agent_ids),
            )
        except Exception as exc:  # noqa: BLE001 - identity authority is a fail-closed boundary
            raise SupportAgentAssignmentAuthorityError(
                "canonical support agent identity is unavailable"
            ) from exc
        exact_agents = [
            row
            for row in entities
            if isinstance(row, dict)
            and row.get("tenant_id") == tenant_id
            and row.get("entity_id") in agent_ids
            and row.get("entity_type") == "agent"
        ]
        if truncated or len(exact_agents) != len(agent_ids):
            raise SupportAgentAssignmentAuthorityError(
                "assignment references must resolve to exact tenant-owned canonical agent entities"
            )

        return await self._assignments.append_event(
            tenant_id=tenant_id,
            case_record=case_record,
            connection_id=connection_id,
            provider_identity=provider_identity,
            connection_verified_at=str(verified_at),
            event=event,
            assigning_principal_id=assigning_principal_id,
            assigning_principal_type=assigning_principal_type,
        )


def _connection_value(connection: Any, field: str) -> Optional[str]:
    value = connection.get(field) if isinstance(connection, dict) else getattr(connection, field, None)
    if value is None:
        return None
    normalized = str(value.value if isinstance(value, Enum) else value).strip()
    return normalized or None


__all__ = [
    "SupportAgentAssignmentAuthorityError",
    "SupportAgentAssignmentEventInput",
    "SupportAgentAssignmentEventType",
    "SupportAgentAssignmentIngestionService",
    "SupportAgentAssignmentNotFound",
    "SupportAgentAssignmentRead",
    "SupportAgentAssignmentRepository",
    "reset_local_support_agent_assignment_store",
]
