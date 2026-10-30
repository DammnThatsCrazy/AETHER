"""Canonical, append-only semantic memory records.

This authority stores explicit memory summaries separately from event-level
semantic observations and their recomputable Gold aggregates. A stored record
must name exact same-tenant source observations and an allowed canonical
consent-policy decision scoped to that exact memory resource. Consent snapshot
IDs and optional vector pointers are not policy or embedding authorities.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Optional, Protocol
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator

from graph.operational_intelligence.models import EvidenceRef
from governance.policy.repositories import ConsentPolicyDecisionRepository

from .models import SubjectType
from .repositories.base_fact_repo import SemanticFactRepository

_MEMORY_TABLE = "semantic_memory_records"
_OBSERVATION_TABLE = "silver_semantic_observations"
_ACTIVE_OBSERVATION_STATUSES = frozenset({"classified", "partial"})
_ACTIVE_MEMORY_STATUSES = frozenset({"classified", "partial"})
_MAX_SOURCE_OBSERVATIONS = 10
_MAX_PAGE_SIZE = 100
_MEMORY_ID_PREFIX = "mem_"


class SemanticMemoryRecord(BaseModel):
    """One explicit semantic memory, immutable after first persistence.

    Corrections and lifecycle changes create a new memory ID (optionally
    pointing to ``supersedes_memory_id``); only privacy/retention status
    transitions may update an existing row.
    """

    model_config = ConfigDict(extra="forbid")

    memory_id: str = Field(min_length=8, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=256)
    subject_ref: str = Field(min_length=1, max_length=512)
    subject_type: SubjectType
    memory_kind: Literal["fact", "preference", "operational_learning", "reminder"]
    summary: str = Field(min_length=1, max_length=2000)
    confidence: float = Field(ge=0, le=1)
    source_observation_ids: list[str] = Field(min_length=1, max_length=_MAX_SOURCE_OBSERVATIONS)
    policy_decision_ref: str = Field(min_length=1, max_length=256)
    # None is an explicit unknown for legacy decisions without required_purposes.
    # A stamped list is historical evidence only, never current consent.
    required_consent_purposes_at_write: Optional[list[str]] = None
    retention_class: Literal["standard_90d"] = "standard_90d"
    status: Literal[
        "classified",
        "partial",
        "superseded",
        "consent_restricted",
        "expired",
        "deleted",
    ] = "classified"
    supersedes_memory_id: Optional[str] = None
    created_at: datetime

    @field_validator("memory_id", "tenant_id", "subject_ref", "policy_decision_ref")
    @classmethod
    def required_identifier_is_trimmed(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("identifier must not be empty")
        return value

    @field_validator("source_observation_ids")
    @classmethod
    def source_ids_are_unique_and_nonempty(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("source observation IDs must not be empty")
        if len(set(normalized)) != len(normalized):
            raise ValueError("source observation IDs must be unique")
        return normalized

    @field_validator("required_consent_purposes_at_write")
    @classmethod
    def stamped_purposes_are_exact_and_nonempty(
        cls, value: Optional[list[str]]
    ) -> Optional[list[str]]:
        if value is None:
            return None
        normalized = _required_purposes({"required_purposes": value})
        if normalized is None:
            raise ValueError("required consent purposes must be unique and nonempty")
        return list(normalized)

    @field_validator("created_at")
    @classmethod
    def timestamp_is_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("created_at must include a timezone")
        return value.astimezone(timezone.utc)


class MemoryObservationRepository(Protocol):
    async def find_by_ids(
        self,
        tenant_id: str,
        record_ids: list[str] | tuple[str, ...],
        *,
        subject: Optional[str] = None,
    ) -> list[dict[str, Any]]: ...


class MemoryFactRepository(Protocol):
    async def upsert(self, fact: dict[str, Any]) -> dict[str, Any]: ...

    async def list_by_tenant(
        self,
        tenant_id: str,
        subject: Optional[str] = None,
        *,
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict[str, Any]]: ...


class MemoryPolicyRepository(Protocol):
    async def find_by_id(self, record_id: str) -> Optional[dict[str, Any]]: ...


@dataclass(frozen=True)
class ResolvedMemoryRecord:
    record: SemanticMemoryRecord
    evidence_refs: tuple[EvidenceRef, ...]
    policy_outcome: str


@dataclass(frozen=True)
class MemoryRecordPage:
    records: tuple[ResolvedMemoryRecord, ...] = ()
    state: str = "unknown"
    complete: bool = False
    truncated: bool = False
    next_offset: Optional[int] = None
    warnings: tuple[str, ...] = ()


class SemanticMemoryRecordRepository:
    """Read/write authority for explicit memory records in semantic Silver."""

    def __init__(
        self,
        *,
        record_repository: Optional[MemoryFactRepository] = None,
        observation_repository: Optional[MemoryObservationRepository] = None,
        policy_repository: Optional[MemoryPolicyRepository] = None,
    ) -> None:
        self._records = record_repository or SemanticFactRepository(_MEMORY_TABLE)
        self._observations = observation_repository or SemanticFactRepository(_OBSERVATION_TABLE)
        self._policies = policy_repository or ConsentPolicyDecisionRepository()

    async def create(self, record: SemanticMemoryRecord) -> SemanticMemoryRecord:
        """Append one memory after exact source and policy authority checks."""
        typed = SemanticMemoryRecord.model_validate(record)
        if typed.status not in _ACTIVE_MEMORY_STATUSES:
            raise ValueError("new_memory_record_must_start_active")
        source_rows = await self._observations.find_by_ids(
            typed.tenant_id,
            typed.source_observation_ids,
            subject=typed.subject_ref,
        )
        source_refs = _validated_source_refs(
            source_rows,
            tenant_id=typed.tenant_id,
            subject_ref=typed.subject_ref,
            observation_ids=typed.source_observation_ids,
        )
        if source_refs is None:
            raise ValueError("memory_source_observations_not_exact_active_or_timestamped")

        policy_row = await self._policies.find_by_id(typed.policy_decision_ref)
        if not _policy_matches_record(policy_row, typed):
            raise ValueError("memory_policy_decision_not_exact_allowed_authority")
        policy_ref = _policy_evidence_ref(policy_row, typed.tenant_id)
        if policy_ref is None:
            raise ValueError("memory_policy_decision_timestamp_missing_or_invalid")

        required_purposes = _required_purposes(policy_row)
        if (
            typed.required_consent_purposes_at_write is not None
            and typed.required_consent_purposes_at_write != (
                list(required_purposes) if required_purposes is not None else None
            )
        ):
            raise ValueError("memory_policy_required_purposes_not_exact_authority")
        typed = typed.model_copy(
            update={
                "required_consent_purposes_at_write": (
                    list(required_purposes) if required_purposes is not None else None
                )
            }
        )

        data = typed.model_dump(mode="json")
        data["idempotency_key"] = f"semantic-memory:{typed.tenant_id}:{typed.memory_id}"
        stored = await self._records.upsert(
            {
                "id": typed.memory_id,
                "tenant_id": typed.tenant_id,
                "source_event_id": None,
                "subject_ref": typed.subject_ref,
                "campaign_id": None,
                "occurred_at": typed.created_at,
                "idempotency_key": data["idempotency_key"],
                "data": data,
            }
        )
        stored_data = _mapping(stored.get("data") if isinstance(stored, dict) else None)
        if stored_data is None or not _same_immutable_memory(stored_data, typed):
            raise ValueError("memory_id_is_append_only_and_already_bound_to_other_content")
        return typed

    async def read_for_subject(
        self,
        tenant_id: str,
        subject_ref: str,
        *,
        offset: int,
        limit: int,
    ) -> MemoryRecordPage:
        """Return only exact active memories with source and policy provenance."""
        limit = min(max(int(limit), 1), _MAX_PAGE_SIZE)
        warnings: list[str] = []
        try:
            raw_rows = await self._records.list_by_tenant(
                tenant_id,
                subject_ref,
                limit=limit + 1,
                offset=offset,
            )
        except Exception:  # noqa: BLE001 - missing memory authority stays unknown
            return MemoryRecordPage(
                state="unknown",
                warnings=("semantic_memory_record_read_unavailable",),
            )

        truncated = len(raw_rows) > limit
        candidates = raw_rows[:limit]
        next_offset = offset + limit if truncated else None
        typed_rows: list[SemanticMemoryRecord] = []
        for raw in candidates:
            row = _mapping(raw)
            if (
                row is None
                or row.get("tenant_id") != tenant_id
                or row.get("subject_ref") != subject_ref
            ):
                warnings.append("semantic_memory_record_scope_mismatch")
                continue
            try:
                record = SemanticMemoryRecord.model_validate(_domain_memory_payload(row))
            except Exception:  # noqa: BLE001 - malformed canonical row is omitted
                warnings.append("semantic_memory_record_contract_invalid")
                continue
            if record.tenant_id != tenant_id or record.subject_ref != subject_ref:
                warnings.append("semantic_memory_record_scope_mismatch")
                continue
            if record.status not in _ACTIVE_MEMORY_STATUSES:
                warnings.append("semantic_memory_record_non_active_omitted")
                continue
            typed_rows.append(record)

        if truncated:
            warnings.append("semantic_memory_record_page_truncated")
        if not typed_rows and not candidates and not warnings:
            return MemoryRecordPage(
                state="empty", complete=not truncated, truncated=truncated, next_offset=next_offset
            )

        all_observation_ids = list(
            dict.fromkeys(
                source_id for record in typed_rows for source_id in record.source_observation_ids
            )
        )
        try:
            source_rows = await self._observations.find_by_ids(
                tenant_id,
                all_observation_ids,
                subject=subject_ref,
            )
        except Exception:  # noqa: BLE001 - provenance dependency degrades this slot
            source_rows = []
            warnings.append("semantic_memory_source_observation_read_unavailable")
        source_refs_by_id = _source_refs_by_id(
            source_rows,
            tenant_id=tenant_id,
            subject_ref=subject_ref,
        )

        resolved: list[ResolvedMemoryRecord] = []
        for record in typed_rows:
            refs = [source_refs_by_id.get(source_id) for source_id in record.source_observation_ids]
            if any(ref is None for ref in refs):
                warnings.append("semantic_memory_source_observation_join_missing")
                continue
            try:
                policy_row = await self._policies.find_by_id(record.policy_decision_ref)
            except Exception:  # noqa: BLE001 - policy join fail-closed
                policy_row = None
            if not _policy_matches_record(policy_row, record):
                warnings.append("semantic_memory_policy_decision_join_missing_or_denied")
                continue
            if not _purpose_stamp_matches_decision(record, policy_row):
                warnings.append("semantic_memory_policy_purpose_stamp_mismatch")
                continue
            policy_ref = _policy_evidence_ref(policy_row, tenant_id)
            if policy_ref is None:
                warnings.append("semantic_memory_policy_decision_timestamp_invalid")
                continue
            memory_ref = _memory_record_ref(record)
            if memory_ref is None:
                warnings.append("semantic_memory_record_timestamp_invalid")
                continue
            resolved.append(
                ResolvedMemoryRecord(
                    record=record,
                    evidence_refs=tuple(
                        _dedupe_refs([memory_ref, *[ref for ref in refs if ref], policy_ref])
                    ),
                    policy_outcome="historical_allow",
                )
            )

        state = "degraded" if warnings else "available" if resolved else "empty"
        return MemoryRecordPage(
            records=tuple(resolved),
            state=state,
            complete=not warnings and not truncated,
            truncated=truncated,
            next_offset=next_offset,
            warnings=tuple(dict.fromkeys(warnings)),
        )

    async def read_for_ids(
        self,
        tenant_id: str,
        subject_ref: str,
        memory_ids: list[str] | tuple[str, ...],
    ) -> MemoryRecordPage:
        """Resolve an exact bounded set of memory IDs with source/policy joins."""
        ids = list(dict.fromkeys(str(value).strip() for value in memory_ids if str(value).strip()))
        if not tenant_id or not subject_ref or len(ids) > 100:
            return MemoryRecordPage(
                state="unknown", warnings=("semantic_memory_exact_id_scope_invalid",)
            )
        if not ids:
            return MemoryRecordPage(state="empty", complete=True)
        warnings: list[str] = []
        try:
            raw_rows = await self._records.find_by_ids(tenant_id, ids, subject=subject_ref)
        except Exception:  # noqa: BLE001 - exact memory authority read remains unknown
            return MemoryRecordPage(
                state="unknown", warnings=("semantic_memory_exact_id_read_unavailable",)
            )
        typed_rows: list[SemanticMemoryRecord] = []
        for raw in raw_rows:
            row = _mapping(raw)
            if (
                row is None
                or row.get("tenant_id") != tenant_id
                or row.get("subject_ref") != subject_ref
            ):
                warnings.append("semantic_memory_record_scope_mismatch")
                continue
            try:
                record = SemanticMemoryRecord.model_validate(_domain_memory_payload(row))
            except Exception:  # noqa: BLE001 - malformed exact memory row is omitted
                warnings.append("semantic_memory_record_contract_invalid")
                continue
            if record.status not in _ACTIVE_MEMORY_STATUSES:
                warnings.append("semantic_memory_record_non_active_omitted")
                continue
            typed_rows.append(record)
        if {record.memory_id for record in typed_rows} != set(ids):
            warnings.append("semantic_memory_exact_id_read_incomplete_or_non_active")
        all_observation_ids = list(
            dict.fromkeys(
                source_id for record in typed_rows for source_id in record.source_observation_ids
            )
        )
        try:
            source_rows = await self._observations.find_by_ids(
                tenant_id, all_observation_ids, subject=subject_ref
            )
        except Exception:  # noqa: BLE001 - evidence joins fail closed
            source_rows = []
            warnings.append("semantic_memory_source_observation_read_unavailable")
        source_refs_by_id = _source_refs_by_id(
            source_rows, tenant_id=tenant_id, subject_ref=subject_ref
        )
        resolved: list[ResolvedMemoryRecord] = []
        for record in typed_rows:
            refs = [source_refs_by_id.get(source_id) for source_id in record.source_observation_ids]
            if any(ref is None for ref in refs):
                warnings.append("semantic_memory_source_observation_join_missing")
                continue
            try:
                policy_row = await self._policies.find_by_id(record.policy_decision_ref)
            except Exception:  # noqa: BLE001 - exact policy read fails closed
                policy_row = None
            if not _policy_matches_record(policy_row, record):
                warnings.append("semantic_memory_policy_decision_join_missing_or_denied")
                continue
            if not _purpose_stamp_matches_decision(record, policy_row):
                warnings.append("semantic_memory_policy_purpose_stamp_mismatch")
                continue
            policy_ref = _policy_evidence_ref(policy_row, tenant_id)
            memory_ref = _memory_record_ref(record)
            if policy_ref is None or memory_ref is None:
                warnings.append("semantic_memory_policy_or_record_timestamp_invalid")
                continue
            resolved.append(
                ResolvedMemoryRecord(
                    record=record,
                    evidence_refs=tuple(
                        _dedupe_refs([memory_ref, *[ref for ref in refs if ref], policy_ref])
                    ),
                    policy_outcome="historical_allow",
                )
            )
        state = "degraded" if warnings else "available" if resolved else "empty"
        return MemoryRecordPage(
            records=tuple(resolved),
            state=state,
            complete=not warnings,
            warnings=tuple(dict.fromkeys(warnings)),
        )


def _validated_source_refs(
    rows: list[dict[str, Any]],
    *,
    tenant_id: str,
    subject_ref: str,
    observation_ids: list[str],
) -> Optional[list[EvidenceRef]]:
    by_id = _source_refs_by_id(rows, tenant_id=tenant_id, subject_ref=subject_ref)
    if set(by_id) != set(observation_ids):
        return None
    return [by_id[observation_id] for observation_id in observation_ids]


def _source_refs_by_id(
    rows: list[dict[str, Any]], *, tenant_id: str, subject_ref: str
) -> dict[str, EvidenceRef]:
    result: dict[str, EvidenceRef] = {}
    for raw in rows:
        row = _mapping(raw)
        if (
            row is None
            or row.get("tenant_id") != tenant_id
            or row.get("primary_subject_ref") != subject_ref
            or _text(row.get("status")) not in _ACTIVE_OBSERVATION_STATUSES
        ):
            continue
        observation_id = _text(row.get("observation_id") or row.get("record_id"))
        observed_at = _timestamp(row.get("processed_at") or row.get("occurred_at"))
        if not observation_id or observed_at is None:
            continue
        result[observation_id] = EvidenceRef(
            id=observation_id,
            type="model_output",
            source=f"semantic_intelligence.{_OBSERVATION_TABLE}",
            observedAt=observed_at,
            uri=(
                f"store://{_OBSERVATION_TABLE}/"
                f"{quote(tenant_id, safe='')}:{quote(observation_id, safe='')}"
            ),
        )
    return result


def _policy_matches_record(raw: Optional[dict[str, Any]], record: SemanticMemoryRecord) -> bool:
    row = _mapping(raw)
    return bool(
        row
        and row.get("policy_decision_id") == record.policy_decision_ref
        and row.get("tenant_id") == record.tenant_id
        and row.get("subject_ref") == record.subject_ref
        and row.get("resource_type") == "semantic_memory"
        and row.get("resource_id") == record.memory_id
        and row.get("action") == "generate_feature"
        and row.get("allowed") is True
    )


def _required_purposes(raw: Optional[dict[str, Any]]) -> Optional[tuple[str, ...]]:
    row = _mapping(raw)
    value = row.get("required_purposes") if row is not None else None
    if not isinstance(value, list) or not value:
        return None
    if any(not isinstance(purpose, str) or not purpose or purpose != purpose.strip() for purpose in value):
        return None
    if len(set(value)) != len(value):
        return None
    return tuple(sorted(value))


def _purpose_stamp_matches_decision(
    record: SemanticMemoryRecord, raw: Optional[dict[str, Any]]
) -> bool:
    stamped = record.required_consent_purposes_at_write
    # An unstamped legacy record has unknown purpose provenance, even if the
    # decision can now be read; it remains eligible for the historical join.
    if stamped is None:
        return True
    return tuple(stamped) == _required_purposes(raw)


def _policy_evidence_ref(raw: Optional[dict[str, Any]], tenant_id: str) -> Optional[EvidenceRef]:
    row = _mapping(raw)
    if row is None or row.get("tenant_id") != tenant_id:
        return None
    decision_id = _text(row.get("policy_decision_id"))
    observed_at = _timestamp(row.get("created_at"))
    if not decision_id or observed_at is None:
        return None
    return EvidenceRef(
        id=decision_id,
        # EvidenceType has no dedicated policy variant; represent the decision
        # as an annotation while preserving its canonical source and URI.
        type="annotation",
        source="governance.consent_policy_decisions",
        observedAt=observed_at,
        uri=(
            "store://consent_policy_decisions/"
            f"{quote(tenant_id, safe='')}:{quote(decision_id, safe='')}"
        ),
    )


def _memory_record_ref(record: SemanticMemoryRecord) -> Optional[EvidenceRef]:
    observed_at = _timestamp(record.created_at)
    if observed_at is None:
        return None
    return EvidenceRef(
        id=record.memory_id,
        type="annotation",
        source=f"semantic_intelligence.{_MEMORY_TABLE}",
        observedAt=observed_at,
        uri=(
            f"store://{_MEMORY_TABLE}/"
            f"{quote(record.tenant_id, safe='')}:{quote(record.memory_id, safe='')}"
        ),
    )


def _same_immutable_memory(raw: dict[str, Any], requested: SemanticMemoryRecord) -> bool:
    try:
        stored = SemanticMemoryRecord.model_validate(_domain_memory_payload(raw))
    except Exception:  # noqa: BLE001 - conflicting immutable row
        return False
    return stored == requested


def _domain_memory_payload(raw: dict[str, Any]) -> dict[str, Any]:
    """Remove only fact-repository metadata before strict domain validation."""
    return {
        key: value
        for key, value in raw.items()
        if key not in {"idempotency_key", "record_id"}
    }


def _dedupe_refs(refs: list[EvidenceRef]) -> list[EvidenceRef]:
    result: list[EvidenceRef] = []
    seen: set[tuple[str, str, str]] = set()
    for ref in refs:
        key = (ref.id, ref.type, ref.source)
        if key not in seen:
            seen.add(key)
            result.append(ref)
    return result


def _mapping(value: Any) -> Optional[dict[str, Any]]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        try:
            value = value.model_dump(mode="json")
        except Exception:  # noqa: BLE001 - malformed row remains unknown
            return None
        return value if isinstance(value, dict) else None
    return None


def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "value"):
        value = value.value
    text = str(value).strip()
    return text or None


def _timestamp(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return None
        return value.astimezone(timezone.utc).isoformat()
    text = _text(value)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat()


__all__ = [
    "MemoryRecordPage",
    "ResolvedMemoryRecord",
    "SemanticMemoryRecord",
    "SemanticMemoryRecordRepository",
]
