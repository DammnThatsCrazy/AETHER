"""Typed, tenant-bound Episode360 links and Journey360 action intents.

These records carry explicit relationships between an episode and existing
canonical execution/attribution facts, and between a journey version and a
non-executable recommended action. They do not copy the source facts or grant
permission to execute an action. Episode observation references preserve the
source namespace and canonical observation/event lineage needed to resolve
legacy bare observation IDs without guessing their source.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Literal, Optional, Protocol, TypeAlias
from urllib.parse import quote
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from graph.operational_intelligence.models import EvidenceRef
from shared.backend_interpretation.primitives import EpisodeRecord, OutcomeTruthRecord
from shared.backend_interpretation.stores import EpisodeStore, OutcomeTruthStore
from intelligence.semantic_intelligence.repositories.base_fact_repo import SemanticFactRepository

_TABLE = "episode_journey_authority_records"
_MAX_LINKS_PER_SUBJECT = 100
_MAX_EVIDENCE_REFS = 20
_EPISODE_EXECUTION_SOURCE = "agent_executions"
_DELEGATION_SOURCE = "delegations"
_OUTCOME_SOURCE = "shared.backend_interpretation.stores.OutcomeTruthStore"
_CONVERSION_SOURCE = "canonical_conversions"
_ATTRIBUTION_RUN_SOURCE = "attribution_runs"
_ATTRIBUTION_CREDIT_SOURCE = "attribution_credits"
_JOURNEY_VERSION_SOURCE = (
    "services/api/journeys/measurement/repositories/journey_repo.py:journey_versions"
)
_JOURNEY_STEP_SOURCE = (
    "services/api/journeys/measurement/repositories/journey_step_repo.py:journey_steps"
)
_SEMANTIC_OBSERVATION_SOURCE = "semantic_intelligence.silver_semantic_observations"
_SEMANTIC_SOURCE_EVENT_REF_SOURCE = (
    "semantic_intelligence.silver_semantic_observations.source_event_id"
)
_SEMANTIC_RECEIPT_REF_SOURCE = (
    "semantic_intelligence.silver_semantic_observations.received_at"
)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("authority timestamps must include a timezone")
    return value.astimezone(timezone.utc)


class EpisodeAgentHandoffRecord(BaseModel):
    """Explicit agent execution and delegation link for one exact episode."""

    model_config = ConfigDict(extra="forbid")

    record_type: Literal["episode_agent_handoff"] = "episode_agent_handoff"
    record_id: str = Field(min_length=8, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=256)
    episode_id: str = Field(min_length=1, max_length=256)
    agent_id: str = Field(min_length=1, max_length=256)
    execution_id: str = Field(min_length=1, max_length=256)
    delegation_id: str = Field(min_length=1, max_length=256)
    source_event_id: str = Field(min_length=1, max_length=256)
    occurred_at: datetime
    recorded_at: datetime
    evidence_refs: list[EvidenceRef] = Field(min_length=2, max_length=_MAX_EVIDENCE_REFS)

    @field_validator("occurred_at", "recorded_at")
    @classmethod
    def timestamps_are_aware(cls, value: datetime) -> datetime:
        return _aware_utc(value)


class EpisodeAttributionLinkRecord(BaseModel):
    """Attribution credit explicitly reached through an episode-owned outcome."""

    model_config = ConfigDict(extra="forbid")

    record_type: Literal["episode_attribution_link"] = "episode_attribution_link"
    record_id: str = Field(min_length=8, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=256)
    episode_id: str = Field(min_length=1, max_length=256)
    outcome_id: str = Field(min_length=1, max_length=256)
    conversion_id: str = Field(min_length=1, max_length=256)
    attribution_run_id: str = Field(min_length=1, max_length=256)
    credit_id: str = Field(min_length=1, max_length=256)
    source_event_id: str = Field(min_length=1, max_length=256)
    credit_weight: str = Field(pattern=r"^(?:0(?:\.\d+)?|1(?:\.0+)?)$")
    occurred_at: datetime
    recorded_at: datetime
    evidence_refs: list[EvidenceRef] = Field(min_length=4, max_length=_MAX_EVIDENCE_REFS)

    @field_validator("occurred_at", "recorded_at")
    @classmethod
    def timestamps_are_aware(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @field_validator("credit_weight")
    @classmethod
    def weight_is_finite_unit_interval(cls, value: str) -> str:
        try:
            parsed = Decimal(value)
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("credit_weight must be a decimal") from exc
        if not parsed.is_finite() or not Decimal("0") <= parsed <= Decimal("1"):
            raise ValueError("credit_weight must be between zero and one")
        return format(parsed.normalize(), "f")


class EpisodeObservationReferenceRecord(BaseModel):
    """Explicit source namespace and lineage for one episode observation ID.

    ``EpisodeRecord.observation_ids`` predates source namespaces and is only a
    bare string list. This typed association is written only when the canonical
    semantic observation row itself contains an explicit ``source_namespace``;
    callers cannot fill that gap from a platform label or source type.
    """

    model_config = ConfigDict(extra="forbid")

    record_type: Literal["episode_observation_reference"] = "episode_observation_reference"
    record_id: str = Field(min_length=8, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=256)
    episode_id: str = Field(min_length=1, max_length=256)
    observation_id: str = Field(min_length=1, max_length=256)
    source_namespace: str = Field(min_length=1, max_length=256)
    source_event_id: str = Field(min_length=1, max_length=256)
    occurred_at: datetime
    received_at: datetime
    recorded_at: datetime
    linked_at: datetime
    evidence_refs: list[EvidenceRef] = Field(min_length=2, max_length=_MAX_EVIDENCE_REFS)

    @field_validator("source_namespace")
    @classmethod
    def namespace_is_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("source_namespace must be explicit and non-empty")
        return normalized

    @field_validator("occurred_at", "received_at", "recorded_at", "linked_at")
    @classmethod
    def timestamps_are_aware(cls, value: datetime) -> datetime:
        return _aware_utc(value)


class JourneyActionIntentRecord(BaseModel):
    """Governed action recommendation bound to one exact journey version.

    This is an intent only. It cannot authorize, dispatch, or prove execution.
    """

    model_config = ConfigDict(extra="forbid")

    record_type: Literal["journey_action_intent"] = "journey_action_intent"
    record_id: str = Field(min_length=8, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=256)
    journey_id: str = Field(min_length=1, max_length=256)
    journey_version_id: str = Field(min_length=1, max_length=256)
    action_intent_id: str = Field(min_length=1, max_length=256)
    recommendation_id: str = Field(min_length=1, max_length=256)
    action_key: str = Field(min_length=1, max_length=128)
    action_type: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=256)
    status: Literal["proposed", "superseded", "withdrawn"] = "proposed"
    actor_ref: str = Field(min_length=1, max_length=256)
    policy_decision_ref: Optional[str] = Field(default=None, max_length=256)
    non_executable: Literal[True] = True
    occurred_at: datetime
    recorded_at: datetime
    evidence_refs: list[EvidenceRef] = Field(min_length=2, max_length=_MAX_EVIDENCE_REFS)

    @field_validator("occurred_at", "recorded_at")
    @classmethod
    def timestamps_are_aware(cls, value: datetime) -> datetime:
        return _aware_utc(value)


class JourneyDropoffRecord(BaseModel):
    """Explicit abandonment fact tied to one canonical journey step/version."""

    model_config = ConfigDict(extra="forbid")

    record_type: Literal["journey_dropoff"] = "journey_dropoff"
    record_id: str = Field(min_length=8, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=256)
    journey_id: str = Field(min_length=1, max_length=256)
    journey_version_id: str = Field(min_length=1, max_length=256)
    step_id: str = Field(min_length=1, max_length=256)
    activity_id: str = Field(min_length=1, max_length=256)
    activity_type: Literal["journey_abandoned"] = "journey_abandoned"
    occurred_at: datetime
    recorded_at: datetime
    evidence_refs: list[EvidenceRef] = Field(min_length=2, max_length=_MAX_EVIDENCE_REFS)

    @field_validator("occurred_at", "recorded_at")
    @classmethod
    def timestamps_are_aware(cls, value: datetime) -> datetime:
        return _aware_utc(value)


class JourneyAcquisitionRole(str, Enum):
    """Closed role vocabulary emitted by traffic source classifier version 3.0."""

    ENTRY = "entry"
    DISCOVERY = "discovery"
    CAMPAIGN = "campaign"
    HANDOFF = "handoff"
    EXCLUDED = "excluded"


class JourneySourceRoleMarker(BaseModel):
    """Typed view of one persisted source role on an exact journey step.

    These roles classify source/acquisition markers. They do not define stage
    boundaries or establish that a journey contains a complete stage inventory.
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1, max_length=256)
    journey_id: str = Field(min_length=1, max_length=256)
    journey_version_id: str = Field(min_length=1, max_length=256)
    step_id: str = Field(min_length=1, max_length=256)
    activity_id: str = Field(min_length=1, max_length=256)
    step_position: int = Field(ge=0)
    journey_role: JourneyAcquisitionRole
    source_classifier_version: Literal["3.0"]
    occurred_at: datetime
    evidence_ref: EvidenceRef

    @field_validator("occurred_at")
    @classmethod
    def timestamp_is_aware(cls, value: datetime) -> datetime:
        return _aware_utc(value)


EpisodeAuthorityRecord: TypeAlias = (
    EpisodeAgentHandoffRecord
    | EpisodeAttributionLinkRecord
    | EpisodeObservationReferenceRecord
)
JourneyAuthorityRecord: TypeAlias = JourneyActionIntentRecord | JourneyDropoffRecord
AuthorityRecord: TypeAlias = EpisodeAuthorityRecord | JourneyAuthorityRecord


@dataclass(frozen=True)
class AuthorityFactRead:
    records: tuple[dict[str, Any], ...] = ()
    available: bool = True
    complete: bool = True
    truncated: bool = False
    invalid_records: bool = False
    tenant_mismatch: bool = False
    read_failed: bool = False


class AuthorityFactSource(Protocol):
    async def append(self, record: AuthorityRecord) -> AuthorityRecord: ...

    async def list_for_subject(
        self,
        tenant_id: str,
        subject_kind: str,
        subject_id: str,
        record_type: str,
        *,
        limit: int,
    ) -> AuthorityFactRead: ...


class EpisodeJourneyAuthorityFactStore(SemanticFactRepository):
    """Append-only fact storage with bounded exact type/subject reads."""

    def __init__(self) -> None:
        super().__init__(_TABLE)

    async def list_for_subject_type(
        self,
        tenant_id: str,
        subject_ref: str,
        record_type: str,
        *,
        limit: int,
    ) -> tuple[list[dict[str, Any]], bool]:
        if not tenant_id or not subject_ref or not record_type or limit <= 0:
            raise ValueError("exact tenant, subject, type, and positive limit are required")
        pool = await self._pool()
        if pool is None:
            rows = [
                row for row in self._store.values()
                if row.get("tenant_id") == tenant_id
                and row.get("subject_ref") == subject_ref
                and (row.get("data") or {}).get("record_type") == record_type
            ]
            rows.sort(key=lambda row: (str(row.get("occurred_at") or ""), str(row.get("id") or "")))
            truncated = len(rows) > limit
            return [dict(row.get("data") or {}) for row in rows[:limit]], truncated
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT id, tenant_id, subject_ref, data FROM {_TABLE} "
                "WHERE tenant_id=$1 AND subject_ref=$2 AND data->>'record_type'=$3 "
                "ORDER BY occurred_at ASC, id ASC LIMIT $4",
                tenant_id,
                subject_ref,
                record_type,
                limit + 1,
            )
        truncated = len(rows) > limit
        return [dict(row["data"]) for row in rows[:limit]], truncated


class EpisodeJourneyAuthorityRepository:
    """Writer/read boundary for explicit Episode360 and Journey360 links."""

    def __init__(self, *, store: Optional[EpisodeJourneyAuthorityFactStore] = None) -> None:
        self._store = store or EpisodeJourneyAuthorityFactStore()

    @staticmethod
    def subject_ref(record: AuthorityRecord) -> tuple[str, str]:
        if isinstance(
            record,
            (
                EpisodeAgentHandoffRecord,
                EpisodeAttributionLinkRecord,
                EpisodeObservationReferenceRecord,
            ),
        ):
            return "episode", record.episode_id
        return "journey", record.journey_id

    async def append(self, record: AuthorityRecord) -> AuthorityRecord:
        typed = _validate_authority_record(record)
        kind, subject_id = self.subject_ref(typed)
        subject_ref = f"{kind}:{subject_id}"
        payload = typed.model_dump(mode="json")
        payload["idempotency_key"] = (
            f"episode-journey-authority:{typed.tenant_id}:{typed.record_type}:{typed.record_id}"
        )
        existing_rows = await self._store.find_by_ids(
            typed.tenant_id, [typed.record_id], subject=subject_ref
        )
        if existing_rows:
            existing = existing_rows[0]
            persisted = {key: value for key, value in existing.items() if key not in {
                "idempotency_key", "record_id", "subject_ref"
            }}
            expected = {key: value for key, value in payload.items() if key != "idempotency_key"}
            if isinstance(typed, EpisodeObservationReferenceRecord):
                # A replay must keep the original association write time, not
                # replace it with the retry's clock value.
                persisted_linked_at = persisted.pop("linked_at", None)
                expected.pop("linked_at", None)
                if persisted_linked_at is None:
                    raise ValueError("episode_observation_reference_link_time_missing")
            if persisted != expected:
                raise ValueError("episode_journey_authority_record_is_append_only")
            if isinstance(typed, EpisodeObservationReferenceRecord):
                return EpisodeObservationReferenceRecord.model_validate({
                    **persisted,
                    "record_id": typed.record_id,
                    "linked_at": persisted_linked_at,
                })
            return typed
        await self._store.upsert(
            {
                "id": typed.record_id,
                "tenant_id": typed.tenant_id,
                "source_event_id": getattr(typed, "source_event_id", None),
                "subject_ref": subject_ref,
                "campaign_id": None,
                "occurred_at": typed.occurred_at,
                "idempotency_key": payload["idempotency_key"],
                "data": payload,
            }
        )
        persisted_rows = await self._store.find_by_ids(
            typed.tenant_id, [typed.record_id], subject=subject_ref
        )
        if len(persisted_rows) != 1:
            raise ValueError("episode_journey_authority_persisted_scope_mismatch")
        persisted = {
            key: value
            for key, value in persisted_rows[0].items()
            if key not in {"idempotency_key", "record_id", "subject_ref"}
        }
        expected = {key: value for key, value in payload.items() if key != "idempotency_key"}
        if isinstance(typed, EpisodeObservationReferenceRecord):
            persisted_linked_at = persisted.pop("linked_at", None)
            expected.pop("linked_at", None)
            if persisted_linked_at is None or persisted != expected:
                raise ValueError("episode_journey_authority_record_is_append_only")
            return EpisodeObservationReferenceRecord.model_validate({
                **persisted,
                "record_id": typed.record_id,
                "linked_at": persisted_linked_at,
            })
        if persisted != expected:
            raise ValueError("episode_journey_authority_record_is_append_only")
        return typed

    async def list_for_subject(
        self,
        tenant_id: str,
        subject_kind: str,
        subject_id: str,
        record_type: str,
        *,
        limit: int,
    ) -> AuthorityFactRead:
        if not tenant_id or not subject_id or limit <= 0:
            return AuthorityFactRead(available=False, complete=False, invalid_records=True)
        if (subject_kind, record_type) not in {
            ("episode", "episode_agent_handoff"),
            ("episode", "episode_attribution_link"),
            ("episode", "episode_observation_reference"),
            ("journey", "journey_action_intent"),
            ("journey", "journey_dropoff"),
        }:
            return AuthorityFactRead(available=False, complete=False, invalid_records=True)
        try:
            rows, truncated = await self._store.list_for_subject_type(
                tenant_id,
                f"{subject_kind}:{subject_id}",
                record_type,
                limit=limit,
            )
        except Exception:  # noqa: BLE001 - authority failure is isolated by caller
            return AuthorityFactRead(available=False, complete=False, read_failed=True)
        records: list[dict[str, Any]] = []
        invalid = False
        tenant_mismatch = False
        for raw in rows:
            try:
                payload = dict(raw)
                # Storage-only idempotency metadata is not part of the typed
                # authority contract and must not fail its strict parser.
                payload.pop("idempotency_key", None)
                record = _validate_authority_record(payload)
            except Exception:  # noqa: BLE001 - malformed source rows degrade completeness
                invalid = True
                continue
            kind, persisted_subject_id = self.subject_ref(record)
            if record.tenant_id != tenant_id:
                tenant_mismatch = True
                continue
            if kind != subject_kind or persisted_subject_id != subject_id:
                invalid = True
                continue
            if record.record_type != record_type:
                invalid = True
                continue
            records.append(record.model_dump(mode="json", exclude_none=True))
        return AuthorityFactRead(
            records=tuple(records),
            available=True,
            complete=not truncated and not invalid and not tenant_mismatch,
            truncated=truncated,
            invalid_records=invalid,
            tenant_mismatch=tenant_mismatch,
        )


class EpisodeJourneyAuthorityWriter:
    """Validated server-side producers for Episode links and Journey action intents."""

    def __init__(
        self,
        *,
        repository: Optional[EpisodeJourneyAuthorityRepository] = None,
        episode_store: Optional[EpisodeStore] = None,
        outcome_store: Optional[OutcomeTruthStore] = None,
        execution_repository: Any = None,
        delegation_repository: Any = None,
        conversion_repository: Any = None,
        attribution_repository: Any = None,
        journey_repository: Any = None,
        journey_step_repository: Any = None,
        observation_repository: Any = None,
    ) -> None:
        self._repository = repository or EpisodeJourneyAuthorityRepository()
        self._episode_store = episode_store or EpisodeStore()
        self._outcome_store = outcome_store or OutcomeTruthStore()
        self._executions = execution_repository
        self._delegations = delegation_repository
        self._conversions = conversion_repository
        self._attributions = attribution_repository
        self._journeys = journey_repository
        self._steps = journey_step_repository
        self._observations = observation_repository

    async def link_observation_reference(
        self, *, tenant_id: str, episode_id: str, observation_id: str
    ) -> EpisodeObservationReferenceRecord:
        """Record namespace only from exact canonical observation evidence.

        The source namespace is never a method argument. Older semantic rows
        without an explicit namespace remain unresolved instead of inheriting a
        namespace from ``source_type``, ``source_platform``, or the episode.
        """
        if not all((tenant_id, episode_id, observation_id)):
            raise ValueError("exact tenant, episode, and observation IDs are required")
        episode = await self._episode_store.get(tenant_id, episode_id)
        if (
            not isinstance(episode, EpisodeRecord)
            or episode.tenant_id != tenant_id
            or episode.episode_id != episode_id
            or observation_id not in set(episode.observation_ids)
        ):
            raise ValueError("episode_observation_reference_requires_recorded_episode_id")

        repository = self._observation_repository()
        rows = await repository.find_by_ids(tenant_id, [observation_id])
        if not isinstance(rows, list) or len(rows) != 1:
            raise ValueError("canonical_semantic_observation_not_unique_for_episode_reference")
        row = rows[0]
        if (
            not isinstance(row, dict)
            or row.get("tenant_id") != tenant_id
            or _text(row.get("record_id") or row.get("observation_id")) != observation_id
            or _text(row.get("observation_id")) != observation_id
            or _text(row.get("status")) not in {"classified", "partial"}
        ):
            raise ValueError("canonical_semantic_observation_scope_or_status_invalid")
        source_namespace = _text(row.get("source_namespace"))
        source_event_id = _text(row.get("source_event_id"))
        occurred_at = _timestamp(row.get("occurred_at"))
        received_at = _timestamp(row.get("received_at"))
        processed_at = _timestamp(row.get("processed_at"))
        if source_namespace is None:
            raise ValueError("canonical_semantic_observation_source_namespace_unavailable")
        if (
            source_event_id is None
            or occurred_at is None
            or received_at is None
            or processed_at is None
        ):
            raise ValueError("canonical_semantic_observation_event_lineage_incomplete")

        observation_uri = (
            "store://silver_semantic_observations/"
            f"{quote(tenant_id, safe='')}:{quote(observation_id, safe='')}"
        )
        record = EpisodeObservationReferenceRecord(
            record_id=_stable_record_id(
                tenant_id,
                "episode_observation_reference",
                episode_id,
                observation_id,
            ),
            tenant_id=tenant_id,
            episode_id=episode_id,
            observation_id=observation_id,
            source_namespace=source_namespace,
            source_event_id=source_event_id,
            occurred_at=occurred_at,
            received_at=received_at,
            recorded_at=processed_at,
            linked_at=datetime.now(timezone.utc),
            evidence_refs=[
                EvidenceRef(
                    id=observation_id,
                    type="event",
                    source=_SEMANTIC_OBSERVATION_SOURCE,
                    observedAt=processed_at.isoformat(),
                    uri=observation_uri,
                ),
                EvidenceRef(
                    id=source_event_id,
                    type="event",
                    source=_SEMANTIC_SOURCE_EVENT_REF_SOURCE,
                    observedAt=occurred_at.isoformat(),
                    uri=f"{observation_uri}/source-event/{quote(source_event_id, safe='')}",
                ),
                EvidenceRef(
                    id=observation_id,
                    type="event",
                    source=_SEMANTIC_RECEIPT_REF_SOURCE,
                    observedAt=received_at.isoformat(),
                    uri=f"{observation_uri}/receipt",
                ),
            ],
        )
        return await self._repository.append(record)

    def _observation_repository(self) -> Any:
        if self._observations is None:
            self._observations = SemanticFactRepository("silver_semantic_observations")
        return self._observations

    async def link_agent_handoff(
        self, *, tenant_id: str, episode_id: str, execution_id: str
    ) -> EpisodeAgentHandoffRecord:
        """Link an episode only to its exact source event, execution and grant."""
        if not tenant_id or not episode_id or not execution_id:
            raise ValueError("exact tenant, episode, and execution IDs are required")
        episode = await self._episode_store.get(tenant_id, episode_id)
        if (
            not isinstance(episode, EpisodeRecord)
            or episode.tenant_id != tenant_id
            or episode.episode_id != episode_id
            or episode.subject.kind != "agent"
        ):
            raise ValueError("episode_agent_handoff_requires_exact_agent_episode")
        executions = await self._execution_repository().find_many(
            {"tenant_id": tenant_id, "execution_id": execution_id}, limit=2
        )
        if len(executions) != 1:
            raise ValueError("canonical_agent_execution_not_unique_for_tenant")
        execution = executions[0]
        agent_id = _text(execution.get("agent_id"))
        event_id = _text(execution.get("triggered_by_event_id"))
        delegation_id = _text(execution.get("delegation_id"))
        started_at = _timestamp(execution.get("started_at") or execution.get("created_at"))
        if (
            execution.get("tenant_id") != tenant_id
            or _text(execution.get("execution_id") or execution.get("id")) != execution_id
            or agent_id != episode.subject.id
            or event_id is None
            or event_id not in set(episode.observation_ids)
            or delegation_id is None
            or started_at is None
        ):
            raise ValueError("agent_execution_does_not_exactly_match_episode_subject_event")
        grants = await self._delegation_repository().find_many(
            {"tenant_id": tenant_id, "delegation_id": delegation_id}, limit=2
        )
        if len(grants) != 1:
            raise ValueError("canonical_delegation_not_unique_for_tenant")
        grant = grants[0]
        if (
            grant.get("tenant_id") != tenant_id
            or _text(grant.get("delegation_id") or grant.get("id")) != delegation_id
            or agent_id not in {
                _text(grant.get("grantor_entity_id")),
                _text(grant.get("grantee_entity_id")),
            }
            or not _delegation_valid_at(grant, started_at)
        ):
            raise ValueError("canonical_delegation_does_not_cover_execution_actor_time")
        grant_time = _timestamp(grant.get("created_at") or grant.get("starts_at"))
        if grant_time is None:
            raise ValueError("canonical_delegation_evidence_timestamp_missing")
        record_id = _stable_record_id(tenant_id, "episode_agent_handoff", episode_id, execution_id)
        record = EpisodeAgentHandoffRecord(
            record_id=record_id,
            tenant_id=tenant_id,
            episode_id=episode_id,
            agent_id=agent_id,
            execution_id=execution_id,
            delegation_id=delegation_id,
            source_event_id=event_id,
            occurred_at=started_at,
            recorded_at=datetime.now(timezone.utc),
            evidence_refs=[
                EvidenceRef(
                    id=execution_id,
                    type="event",
                    source=_EPISODE_EXECUTION_SOURCE,
                    observedAt=started_at.isoformat(),
                    uri=f"store://agent_executions/{quote(execution_id, safe='')}",
                ),
                EvidenceRef(
                    id=delegation_id,
                    type="entity",
                    source=_DELEGATION_SOURCE,
                    observedAt=grant_time.isoformat(),
                    uri=f"store://delegations/{quote(delegation_id, safe='')}",
                ),
            ],
        )
        await self._repository.append(record)
        return record

    async def link_attribution_credit(
        self,
        *,
        tenant_id: str,
        episode_id: str,
        outcome_id: str,
        conversion_id: str,
        attribution_run_id: str,
        credit_id: str,
    ) -> EpisodeAttributionLinkRecord:
        """Link an episode outcome to one exact active canonical attribution credit."""
        if not all((tenant_id, episode_id, outcome_id, conversion_id, attribution_run_id, credit_id)):
            raise ValueError("exact tenant and canonical attribution IDs are required")
        episode = await self._episode_store.get(tenant_id, episode_id)
        if (
            not isinstance(episode, EpisodeRecord)
            or episode.tenant_id != tenant_id
            or episode.episode_id != episode_id
            or outcome_id not in episode.outcome_ids
        ):
            raise ValueError("attribution_link_requires_exact_episode_outcome_reference")
        outcome = await self._outcome_store.get(tenant_id, outcome_id)
        if not isinstance(outcome, OutcomeTruthRecord):
            raise ValueError("canonical_episode_outcome_not_found")
        outcome_subject = outcome.subject
        if (
            outcome.tenant_id != tenant_id
            or outcome.outcome_id != outcome_id
            or getattr(outcome_subject, "kind", None) != "episode"
            or getattr(outcome_subject, "id", None) != episode_id
            or not outcome.source_event_ids
        ):
            raise ValueError("outcome_does_not_exactly_reference_episode")
        conversion = await self._conversion_repository().get(tenant_id, conversion_id)
        if (
            not isinstance(conversion, dict)
            or conversion.get("tenant_id") != tenant_id
            or _text(conversion.get("conversion_id")) != conversion_id
            or _text(conversion.get("source_event_id")) not in set(outcome.source_event_ids)
        ):
            raise ValueError("canonical_conversion_not_linked_by_exact_outcome_source_event")
        attribution = self._attribution_repository()
        run = await attribution.get_run(attribution_run_id, tenant_id=tenant_id)
        if (
            not isinstance(run, dict)
            or run.get("tenant_id") != tenant_id
            or _text(run.get("attribution_run_id")) != attribution_run_id
            or _text(run.get("conversion_id")) != conversion_id
            or run.get("status") != "complete"
            or run.get("is_active") is not True
        ):
            raise ValueError("attribution_run_is_not_exact_active_completed_conversion_run")
        credit_rows = await attribution.list_credits_for_run(
            tenant_id, attribution_run_id, limit=101
        )
        matching = [
            row for row in credit_rows
            if row.get("tenant_id") == tenant_id
            and _text(row.get("credit_id")) == credit_id
            and _text(row.get("conversion_id")) == conversion_id
            and _text(row.get("attribution_run_id")) == attribution_run_id
        ]
        if len(matching) != 1 or len(credit_rows) > 100:
            raise ValueError("canonical_attribution_credit_not_unique_or_bounded")
        credit = matching[0]
        weight = _decimal_text(credit.get("credit_weight"))
        conversion_time = _timestamp(conversion.get("observed_at") or conversion.get("occurred_at"))
        outcome_time = _timestamp(outcome.achieved_at or outcome.observed_at)
        run_time = _timestamp(run.get("completed_at") or run.get("created_at"))
        credit_time = _timestamp(credit.get("created_at"))
        if None in (weight, conversion_time, outcome_time, run_time, credit_time):
            raise ValueError("attribution_link_source_evidence_incomplete")
        source_event_id = _text(conversion.get("source_event_id"))
        record_id = _stable_record_id(tenant_id, "episode_attribution_link", episode_id, credit_id)
        record = EpisodeAttributionLinkRecord(
            record_id=record_id,
            tenant_id=tenant_id,
            episode_id=episode_id,
            outcome_id=outcome_id,
            conversion_id=conversion_id,
            attribution_run_id=attribution_run_id,
            credit_id=credit_id,
            source_event_id=source_event_id,
            credit_weight=weight,
            occurred_at=outcome_time,
            recorded_at=datetime.now(timezone.utc),
            evidence_refs=[
                EvidenceRef(
                    id=outcome_id, type="event", source=_OUTCOME_SOURCE,
                    observedAt=outcome_time.isoformat(),
                    uri=f"store://outcome_truth/{quote(outcome_id, safe='')}",
                ),
                EvidenceRef(
                    id=conversion_id, type="transaction", source=_CONVERSION_SOURCE,
                    observedAt=conversion_time.isoformat(),
                    uri=f"store://canonical_conversions/{quote(conversion_id, safe='')}",
                ),
                EvidenceRef(
                    id=attribution_run_id, type="model_output", source=_ATTRIBUTION_RUN_SOURCE,
                    observedAt=run_time.isoformat(),
                    uri=f"store://attribution_runs/{quote(attribution_run_id, safe='')}",
                ),
                EvidenceRef(
                    id=credit_id, type="model_output", source=_ATTRIBUTION_CREDIT_SOURCE,
                    observedAt=credit_time.isoformat(),
                    uri=f"store://attribution_credits/{quote(credit_id, safe='')}",
                ),
            ],
        )
        await self._repository.append(record)
        return record

    async def record_action_intent(
        self, record: JourneyActionIntentRecord
    ) -> JourneyActionIntentRecord:
        """Persist a non-executable intent after exact current-version evidence checks."""
        typed = JourneyActionIntentRecord.model_validate(record)
        journey = await self._journey_repository().get_current(
            typed.tenant_id, typed.journey_id
        )
        if (
            not isinstance(journey, dict)
            or journey.get("tenant_id") != typed.tenant_id
            or _text(journey.get("journey_id")) != typed.journey_id
            or _text(journey.get("journey_version_id")) != typed.journey_version_id
            or journey.get("is_current") is not True
        ):
            raise ValueError("action_intent_requires_exact_current_tenant_journey_version")
        steps = await self._journey_step_repository().list_by_version(
            typed.tenant_id, typed.journey_version_id, limit=201
        )
        if not isinstance(steps, list) or len(steps) > 200:
            raise ValueError("action_intent_journey_step_evidence_read_incomplete")
        step_ids = {
            _text(step.get("step_id"))
            for step in steps
            if isinstance(step, dict)
            and step.get("tenant_id") == typed.tenant_id
            and _text(step.get("journey_id")) == typed.journey_id
            and _text(step.get("journey_version_id")) == typed.journey_version_id
        }
        refs = {ref.id: ref for ref in typed.evidence_refs}
        if (
            f"store://journey_versions/{typed.journey_version_id}"
            not in {ref.uri for ref in typed.evidence_refs}
            or not any(
                ref.id in step_ids
                and ref.source == _JOURNEY_STEP_SOURCE
                and ref.uri == f"store://journey_steps/{ref.id}"
                for ref in refs.values()
            )
        ):
            raise ValueError("action_intent_requires_exact_version_and_step_evidence")
        await self._repository.append(typed)
        return typed

    async def record_journey_dropoff(
        self,
        *,
        tenant_id: str,
        journey_id: str,
        journey_version_id: str,
        step_id: str,
    ) -> JourneyDropoffRecord:
        """Record an exact ``journey_abandoned`` step on the current version.

        Callers supply lookup keys only. The tenant, version marker, event type,
        activity ID, timestamps, and evidence are read from canonical sources.
        """
        if not all((tenant_id, journey_id, journey_version_id, step_id)):
            raise ValueError("exact tenant, journey, version, and step IDs are required")
        journey = await self._journey_repository().get_current(tenant_id, journey_id)
        if (
            not isinstance(journey, dict)
            or journey.get("tenant_id") != tenant_id
            or _text(journey.get("journey_id")) != journey_id
            or _text(journey.get("journey_version_id")) != journey_version_id
            or journey.get("is_current") is not True
        ):
            raise ValueError("dropoff_requires_exact_current_tenant_journey_version")
        step = await self._journey_step_repository().get_step(tenant_id, step_id)
        if (
            not isinstance(step, dict)
            or step.get("tenant_id") != tenant_id
            or _text(step.get("journey_id")) != journey_id
            or _text(step.get("journey_version_id")) != journey_version_id
            or _text(step.get("step_id")) != step_id
            or _text(step.get("activity_type")) != "journey_abandoned"
        ):
            raise ValueError("dropoff_requires_exact_canonical_journey_abandoned_step")
        activity_id = _text(step.get("activity_id"))
        occurred_at = _timestamp(step.get("occurred_at"))
        version_time = _timestamp(journey.get("computed_at"))
        if activity_id is None or occurred_at is None or version_time is None:
            raise ValueError("journey_dropoff_source_evidence_incomplete")
        record = JourneyDropoffRecord(
            record_id=_stable_record_id(
                tenant_id,
                "journey_dropoff",
                journey_version_id,
                step_id,
            ),
            tenant_id=tenant_id,
            journey_id=journey_id,
            journey_version_id=journey_version_id,
            step_id=step_id,
            activity_id=activity_id,
            occurred_at=occurred_at,
            recorded_at=datetime.now(timezone.utc),
            evidence_refs=[
                EvidenceRef(
                    id=journey_version_id,
                    type="entity",
                    source=_JOURNEY_VERSION_SOURCE,
                    observedAt=version_time.isoformat(),
                    uri=f"store://journey_versions/{quote(journey_version_id, safe='')}",
                ),
                EvidenceRef(
                    id=step_id,
                    type="event",
                    source=_JOURNEY_STEP_SOURCE,
                    observedAt=occurred_at.isoformat(),
                    uri=f"store://journey_steps/{quote(step_id, safe='')}",
                ),
            ],
        )
        await self._repository.append(record)
        return record

    def _execution_repository(self) -> Any:
        if self._executions is None:
            from repositories.repos import AgentExecutionRepository

            self._executions = AgentExecutionRepository()
        return self._executions

    def _delegation_repository(self) -> Any:
        if self._delegations is None:
            from repositories.repos import DelegationRepository

            self._delegations = DelegationRepository()
        return self._delegations

    def _conversion_repository(self) -> Any:
        if self._conversions is None:
            from journeys.measurement.repositories.conversion_repo import ConversionRepository

            self._conversions = ConversionRepository()
        return self._conversions

    def _attribution_repository(self) -> Any:
        if self._attributions is None:
            from journeys.measurement.repositories.attribution_run_repo import AttributionRunRepository

            self._attributions = AttributionRunRepository()
        return self._attributions

    def _journey_repository(self) -> Any:
        if self._journeys is None:
            from journeys.measurement.repositories.journey_repo import JourneyRepository

            self._journeys = JourneyRepository()
        return self._journeys

    def _journey_step_repository(self) -> Any:
        if self._steps is None:
            from journeys.measurement.repositories.journey_step_repo import JourneyStepRepository

            self._steps = JourneyStepRepository()
        return self._steps


def _validate_authority_record(value: Any) -> AuthorityRecord:
    if isinstance(
        value,
        EpisodeAgentHandoffRecord
        | EpisodeAttributionLinkRecord
        | EpisodeObservationReferenceRecord
        | JourneyActionIntentRecord
        | JourneyDropoffRecord,
    ):
        return value
    if not isinstance(value, dict):
        raise ValueError("authority record must be a typed mapping")
    record_type = value.get("record_type")
    model: type[BaseModel]
    if record_type == "episode_agent_handoff":
        model = EpisodeAgentHandoffRecord
    elif record_type == "episode_attribution_link":
        model = EpisodeAttributionLinkRecord
    elif record_type == "episode_observation_reference":
        model = EpisodeObservationReferenceRecord
    elif record_type == "journey_action_intent":
        model = JourneyActionIntentRecord
    elif record_type == "journey_dropoff":
        model = JourneyDropoffRecord
    else:
        raise ValueError("unknown episode journey authority record type")
    return model.model_validate(value)  # type: ignore[return-value]


def _stable_record_id(tenant_id: str, kind: str, subject_id: str, source_id: str) -> str:
    digest = hashlib.sha256(f"{tenant_id}\0{kind}\0{subject_id}\0{source_id}".encode()).hexdigest()
    return f"ejr_{digest[:40]}"


def _text(value: Any) -> Optional[str]:
    if not isinstance(value, (str, int, UUID)):
        return None
    text = str(value).strip()
    return text or None


def _timestamp(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _decimal_text(value: Any) -> Optional[str]:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not parsed.is_finite() or not Decimal("0") <= parsed <= Decimal("1"):
        return None
    return format(parsed.normalize(), "f")


def _delegation_valid_at(row: dict[str, Any], instant: datetime) -> bool:
    start = _timestamp(row.get("starts_at") or row.get("created_at"))
    end = _timestamp(row.get("ends_at")) if row.get("ends_at") else None
    revoked = _timestamp(row.get("revoked_at")) if row.get("revoked_at") else None
    return bool(
        start is not None
        and start <= instant
        and (end is None or instant < end)
        and (revoked is None or instant < revoked)
    )


__all__ = [
    "AuthorityFactRead",
    "AuthorityFactSource",
    "EpisodeAgentHandoffRecord",
    "EpisodeAttributionLinkRecord",
    "EpisodeObservationReferenceRecord",
    "EpisodeJourneyAuthorityFactStore",
    "EpisodeJourneyAuthorityRepository",
    "EpisodeJourneyAuthorityWriter",
    "JourneyAcquisitionRole",
    "JourneyActionIntentRecord",
    "JourneyDropoffRecord",
    "JourneySourceRoleMarker",
]
