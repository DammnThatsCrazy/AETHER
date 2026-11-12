"""Append-only context-card and embedding-metadata authorities for Memory360.

Cards and metadata are explicit records tied to exact same-tenant memory/card
IDs and persisted consent decisions. Embedding metadata is a producer report;
this module has no vector store and therefore never verifies vector existence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Optional, Protocol
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator

from graph.operational_intelligence.models import EvidenceRef
from governance.policy.repositories import ConsentPolicyDecisionRepository
from .memory_records import (
    MemoryRecordPage,
    ResolvedMemoryRecord,
    SemanticMemoryRecordRepository,
    _mapping,
    _timestamp,
    _text,
)
from .repositories.base_fact_repo import SemanticFactRepository

_CARD_TABLE = "semantic_context_cards"
_EMBEDDING_TABLE = "semantic_embedding_metadata"
_ACTIVE_STATUSES = frozenset({"classified", "partial"})
_MAX_PAGE_SIZE = 100
_MAX_CARD_SOURCE_MEMORIES = 20
_MAX_EMBEDDING_CARDS = 20


class SemanticContextCard(BaseModel):
    """An explicitly authored context card over exact canonical memory IDs."""

    model_config = ConfigDict(extra="forbid")

    card_id: str = Field(min_length=8, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=256)
    subject_ref: str = Field(min_length=1, max_length=512)
    card_kind: Literal["summary", "profile", "preference", "operational"]
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=2000)
    source_memory_ids: list[str] = Field(min_length=1, max_length=_MAX_CARD_SOURCE_MEMORIES)
    policy_decision_ref: str = Field(min_length=1, max_length=256)
    actor_ref: str = Field(min_length=1, max_length=256)
    retention_class: Literal["standard_90d"] = "standard_90d"
    status: Literal[
        "classified", "partial", "superseded", "consent_restricted", "expired", "deleted"
    ] = "classified"
    created_at: datetime

    @field_validator(
        "card_id", "tenant_id", "subject_ref", "title", "summary", "policy_decision_ref", "actor_ref"
    )
    @classmethod
    def trim_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("context card identifiers and text must not be blank")
        return value

    @field_validator("source_memory_ids")
    @classmethod
    def memory_ids_are_unique(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized) or len(set(normalized)) != len(normalized):
            raise ValueError("context card memory IDs must be non-empty and unique")
        return normalized

    @field_validator("created_at")
    @classmethod
    def timestamp_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("created_at must include a timezone")
        return value.astimezone(timezone.utc)


class SemanticEmbeddingMetadata(BaseModel):
    """Explicit, tenant-reported metadata for a generated embedding artifact."""

    model_config = ConfigDict(extra="forbid")

    embedding_id: str = Field(min_length=8, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=256)
    subject_ref: str = Field(min_length=1, max_length=512)
    card_ids: list[str] = Field(min_length=1, max_length=_MAX_EMBEDDING_CARDS)
    provider_id: str = Field(min_length=1, max_length=128)
    model_id: str = Field(min_length=1, max_length=128)
    model_version: str = Field(min_length=1, max_length=128)
    dimensions: int = Field(ge=1, le=65_536)
    vector_store: str = Field(min_length=1, max_length=128)
    namespace: str = Field(min_length=1, max_length=256)
    vector_ref: str = Field(min_length=1, max_length=512)
    producer_receipt_id: str = Field(min_length=1, max_length=256)
    policy_decision_ref: str = Field(min_length=1, max_length=256)
    actor_ref: str = Field(min_length=1, max_length=256)
    retention_class: Literal["standard_90d"] = "standard_90d"
    status: Literal["reported", "consent_restricted", "expired", "deleted"] = "reported"
    observed_at: datetime
    created_at: datetime

    @field_validator(
        "embedding_id", "tenant_id", "subject_ref", "provider_id", "model_id", "model_version",
        "vector_store", "namespace", "vector_ref", "producer_receipt_id",
        "policy_decision_ref", "actor_ref",
    )
    @classmethod
    def trim_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("embedding metadata identifiers must not be blank")
        return value

    @field_validator("card_ids")
    @classmethod
    def card_ids_are_unique(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized) or len(set(normalized)) != len(normalized):
            raise ValueError("embedding source card IDs must be non-empty and unique")
        return normalized

    @field_validator("observed_at", "created_at")
    @classmethod
    def timestamp_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("embedding metadata timestamps must include a timezone")
        return value.astimezone(timezone.utc)


class MemoryAuthorityFactStore(Protocol):
    async def upsert(self, fact: dict[str, Any]) -> dict[str, Any]: ...

    async def list_by_tenant(
        self, tenant_id: str, subject: Optional[str] = None, *, limit: int = 500, offset: int = 0
    ) -> list[dict[str, Any]]: ...

    async def find_by_ids(
        self, tenant_id: str, record_ids: list[str] | tuple[str, ...], *, subject: Optional[str] = None
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class ResolvedContextCard:
    card: SemanticContextCard
    evidence_refs: tuple[EvidenceRef, ...]
    policy_outcome: str = "historical_allow"


@dataclass(frozen=True)
class ResolvedEmbeddingMetadata:
    metadata: SemanticEmbeddingMetadata
    evidence_refs: tuple[EvidenceRef, ...]
    policy_outcome: str = "historical_allow"
    artifact_verification_state: str = "unknown"


@dataclass(frozen=True)
class MemoryAuthorityRead:
    cards: tuple[ResolvedContextCard, ...] = ()
    cards_state: str = "unknown"
    cards_complete: bool = False
    cards_truncated: bool = False
    cards_next_offset: Optional[int] = None
    embeddings: tuple[ResolvedEmbeddingMetadata, ...] = ()
    embeddings_state: str = "unknown"
    embeddings_complete: bool = False
    embeddings_truncated: bool = False
    embeddings_next_offset: Optional[int] = None
    warnings: tuple[str, ...] = ()


class SemanticContextCardRepository:
    """Writer/read authority for policy-joined, exact-source context cards."""

    def __init__(
        self,
        *,
        record_repository: Optional[MemoryAuthorityFactStore] = None,
        memory_repository: Optional[Any] = None,
        policy_repository: Optional[Any] = None,
    ) -> None:
        self._records = record_repository or SemanticFactRepository(_CARD_TABLE)
        self._memories = memory_repository or SemanticMemoryRecordRepository()
        self._policies = policy_repository or ConsentPolicyDecisionRepository()

    async def create(self, card: SemanticContextCard) -> SemanticContextCard:
        typed = SemanticContextCard.model_validate(card)
        if typed.status not in _ACTIVE_STATUSES:
            raise ValueError("new_semantic_context_card_must_start_active")
        source_page = await self._memories.read_for_ids(
            typed.tenant_id, typed.subject_ref, typed.source_memory_ids
        )
        if not _exact_memory_page(source_page, typed.source_memory_ids):
            raise ValueError("context_card_source_memories_not_exact_active_or_policy_joined")
        policy_row = await self._policies.find_by_id(typed.policy_decision_ref)
        policy_ref = _exact_policy_ref(
            policy_row,
            tenant_id=typed.tenant_id,
            subject_ref=typed.subject_ref,
            resource_type="semantic_context_card",
            resource_id=typed.card_id,
            decision_id=typed.policy_decision_ref,
        )
        if policy_ref is None:
            raise ValueError("context_card_policy_decision_not_exact_allowed_authority")
        await _append_immutable(
            self._records,
            table=_CARD_TABLE,
            record_id=typed.card_id,
            tenant_id=typed.tenant_id,
            subject_ref=typed.subject_ref,
            created_at=typed.created_at,
            payload=typed.model_dump(mode="json"),
            idempotency_key=f"semantic-context-card:{typed.tenant_id}:{typed.card_id}",
            model=SemanticContextCard,
        )
        return typed

    async def read_for_subject(
        self, tenant_id: str, subject_ref: str, *, offset: int, limit: int
    ) -> tuple[ResolvedContextCard, ...] | MemoryAuthorityRead:
        limit = min(max(int(limit), 1), _MAX_PAGE_SIZE)
        warnings: list[str] = []
        try:
            rows = await self._records.list_by_tenant(
                tenant_id, subject_ref, limit=limit + 1, offset=offset
            )
        except Exception:  # noqa: BLE001 - missing card authority remains unknown
            return MemoryAuthorityRead(warnings=("semantic_context_card_read_unavailable",))
        truncated = len(rows) > limit
        candidates = rows[:limit]
        typed: list[SemanticContextCard] = []
        for raw in candidates:
            row = _mapping(raw)
            payload = _domain_payload(_row_data(row)) if row else None
            if row is None or row.get("tenant_id") != tenant_id or row.get("subject_ref") != subject_ref:
                warnings.append("semantic_context_card_scope_mismatch")
                continue
            try:
                card = SemanticContextCard.model_validate(payload)
            except Exception:  # noqa: BLE001 - malformed canonical rows stay omitted
                warnings.append("semantic_context_card_contract_invalid")
                continue
            if card.tenant_id != tenant_id or card.subject_ref != subject_ref:
                warnings.append("semantic_context_card_scope_mismatch")
            elif card.status not in _ACTIVE_STATUSES:
                warnings.append("semantic_context_card_non_active_omitted")
            else:
                typed.append(card)
        all_memory_ids = list(dict.fromkeys(
            memory_id for card in typed for memory_id in card.source_memory_ids
        ))
        memory_page = await self._memories.read_for_ids(tenant_id, subject_ref, all_memory_ids)
        warnings.extend(getattr(memory_page, "warnings", ()))
        memory_by_id = {
            resolved.record.memory_id: resolved
            for resolved in getattr(memory_page, "records", ())
        }
        resolved_cards: list[ResolvedContextCard] = []
        for card in typed:
            source_records = [memory_by_id.get(memory_id) for memory_id in card.source_memory_ids]
            if any(record is None for record in source_records):
                warnings.append("semantic_context_card_source_memory_join_missing")
                continue
            policy = await self._policies.find_by_id(card.policy_decision_ref)
            policy_ref = _exact_policy_ref(
                policy,
                tenant_id=tenant_id,
                subject_ref=subject_ref,
                resource_type="semantic_context_card",
                resource_id=card.card_id,
                decision_id=card.policy_decision_ref,
            )
            card_ref = _card_ref(card)
            if policy_ref is None or card_ref is None:
                warnings.append("semantic_context_card_policy_or_timestamp_join_invalid")
                continue
            evidence = _dedupe_refs(
                [
                    card_ref,
                    policy_ref,
                    *[
                        ref
                        for resolved in source_records
                        if resolved is not None
                        for ref in resolved.evidence_refs
                    ],
                ]
            )
            resolved_cards.append(ResolvedContextCard(card, tuple(evidence)))
        if truncated:
            warnings.append("semantic_context_card_page_truncated")
        card_state = "degraded" if warnings else "available" if resolved_cards else "empty"
        return MemoryAuthorityRead(
            cards=tuple(resolved_cards),
            cards_state=card_state,
            cards_complete=not warnings and not truncated,
            cards_truncated=truncated,
            cards_next_offset=offset + limit if truncated else None,
            warnings=tuple(dict.fromkeys(warnings)),
        )

    async def read_by_ids(
        self, tenant_id: str, subject_ref: str, card_ids: list[str] | tuple[str, ...]
    ) -> tuple[ResolvedContextCard, ...]:
        if not card_ids or len(card_ids) > _MAX_EMBEDDING_CARDS:
            return ()
        try:
            rows = await self._records.find_by_ids(tenant_id, card_ids, subject=subject_ref)
            cards: list[SemanticContextCard] = []
            for raw in rows:
                row = _mapping(raw)
                if row is None or row.get("tenant_id") != tenant_id or row.get("subject_ref") != subject_ref:
                    continue
                payload = _domain_payload(_row_data(row))
                card = SemanticContextCard.model_validate(payload)
                if card.status in _ACTIVE_STATUSES and card.tenant_id == tenant_id and card.subject_ref == subject_ref:
                    cards.append(card)
            if {card.card_id for card in cards} != set(card_ids):
                return ()
            source_ids = list(dict.fromkeys(
                memory_id for card in cards for memory_id in card.source_memory_ids
            ))
            memory_page = await self._memories.read_for_ids(tenant_id, subject_ref, source_ids)
            if not _exact_memory_page(memory_page, source_ids):
                return ()
            resolved_memories = {
                item.record.memory_id: item for item in memory_page.records
            }
            result: list[ResolvedContextCard] = []
            for card in cards:
                policy = await self._policies.find_by_id(card.policy_decision_ref)
                policy_ref = _exact_policy_ref(
                    policy,
                    tenant_id=tenant_id,
                    subject_ref=subject_ref,
                    resource_type="semantic_context_card",
                    resource_id=card.card_id,
                    decision_id=card.policy_decision_ref,
                )
                card_ref = _card_ref(card)
                if policy_ref is None or card_ref is None:
                    return ()
                refs = [card_ref, policy_ref]
                for memory_id in card.source_memory_ids:
                    refs.extend(resolved_memories[memory_id].evidence_refs)
                result.append(ResolvedContextCard(card, tuple(_dedupe_refs(refs))))
            return tuple(result)
        except Exception:  # noqa: BLE001 - exact card reads fail closed
            return ()


class SemanticEmbeddingMetadataRepository:
    """Writer/read authority for explicit, source-joined embedding reports."""

    def __init__(
        self,
        *,
        record_repository: Optional[MemoryAuthorityFactStore] = None,
        card_repository: Optional[Any] = None,
        policy_repository: Optional[Any] = None,
    ) -> None:
        self._records = record_repository or SemanticFactRepository(_EMBEDDING_TABLE)
        self._cards = card_repository or SemanticContextCardRepository()
        self._policies = policy_repository or ConsentPolicyDecisionRepository()

    async def create(self, metadata: SemanticEmbeddingMetadata) -> SemanticEmbeddingMetadata:
        typed = SemanticEmbeddingMetadata.model_validate(metadata)
        if typed.status != "reported":
            raise ValueError("new_semantic_embedding_metadata_must_start_reported")
        cards = await self._cards.read_by_ids(
            typed.tenant_id, typed.subject_ref, typed.card_ids
        )
        if {item.card.card_id for item in cards} != set(typed.card_ids):
            raise ValueError("embedding_source_cards_not_exact_active_or_policy_joined")
        policy = await self._policies.find_by_id(typed.policy_decision_ref)
        if _exact_policy_ref(
            policy,
            tenant_id=typed.tenant_id,
            subject_ref=typed.subject_ref,
            resource_type="semantic_embedding",
            resource_id=typed.embedding_id,
            decision_id=typed.policy_decision_ref,
        ) is None:
            raise ValueError("embedding_policy_decision_not_exact_allowed_authority")
        await _append_immutable(
            self._records,
            table=_EMBEDDING_TABLE,
            record_id=typed.embedding_id,
            tenant_id=typed.tenant_id,
            subject_ref=typed.subject_ref,
            created_at=typed.created_at,
            payload=typed.model_dump(mode="json"),
            idempotency_key=f"semantic-embedding:{typed.tenant_id}:{typed.embedding_id}",
            model=SemanticEmbeddingMetadata,
        )
        return typed

    async def read_for_subject(
        self, tenant_id: str, subject_ref: str, *, offset: int, limit: int
    ) -> MemoryAuthorityRead:
        limit = min(max(int(limit), 1), _MAX_PAGE_SIZE)
        warnings: list[str] = []
        try:
            rows = await self._records.list_by_tenant(
                tenant_id, subject_ref, limit=limit + 1, offset=offset
            )
        except Exception:  # noqa: BLE001 - embedding metadata read remains unknown
            return MemoryAuthorityRead(warnings=("semantic_embedding_metadata_read_unavailable",))
        truncated = len(rows) > limit
        candidates = rows[:limit]
        typed: list[SemanticEmbeddingMetadata] = []
        for raw in candidates:
            row = _mapping(raw)
            if row is None or row.get("tenant_id") != tenant_id or row.get("subject_ref") != subject_ref:
                warnings.append("semantic_embedding_metadata_scope_mismatch")
                continue
            try:
                metadata = SemanticEmbeddingMetadata.model_validate(_domain_payload(_row_data(row)))
            except Exception:  # noqa: BLE001 - malformed metadata stays unknown
                warnings.append("semantic_embedding_metadata_contract_invalid")
                continue
            if metadata.tenant_id != tenant_id or metadata.subject_ref != subject_ref:
                warnings.append("semantic_embedding_metadata_scope_mismatch")
            elif metadata.status != "reported":
                warnings.append("semantic_embedding_metadata_non_active_omitted")
            else:
                typed.append(metadata)
        card_ids = list(dict.fromkeys(card_id for item in typed for card_id in item.card_ids))
        cards = await self._cards.read_by_ids(tenant_id, subject_ref, card_ids)
        card_by_id = {item.card.card_id: item for item in cards}
        resolved: list[ResolvedEmbeddingMetadata] = []
        for item in typed:
            joined_cards = [card_by_id.get(card_id) for card_id in item.card_ids]
            if any(card is None for card in joined_cards):
                warnings.append("semantic_embedding_metadata_source_card_join_missing")
                continue
            policy = await self._policies.find_by_id(item.policy_decision_ref)
            policy_ref = _exact_policy_ref(
                policy,
                tenant_id=tenant_id,
                subject_ref=subject_ref,
                resource_type="semantic_embedding",
                resource_id=item.embedding_id,
                decision_id=item.policy_decision_ref,
            )
            metadata_ref = _embedding_ref(item)
            if policy_ref is None or metadata_ref is None:
                warnings.append("semantic_embedding_metadata_policy_or_timestamp_join_invalid")
                continue
            evidence = _dedupe_refs(
                [
                    metadata_ref,
                    policy_ref,
                    *[
                        ref
                        for card in joined_cards
                        if card is not None
                        for ref in card.evidence_refs
                    ],
                ]
            )
            resolved.append(ResolvedEmbeddingMetadata(item, tuple(evidence)))
        if truncated:
            warnings.append("semantic_embedding_metadata_page_truncated")
        if warnings:
            state = "degraded"
        elif resolved:
            state = "degraded"  # producer metadata is explicit but artifact existence is unverified
        else:
            state = "unknown"  # no vector producer inventory is connected to this authority
        return MemoryAuthorityRead(
            embeddings=tuple(resolved),
            embeddings_state=state,
            embeddings_complete=not warnings and not truncated,
            embeddings_truncated=truncated,
            embeddings_next_offset=offset + limit if truncated else None,
            warnings=tuple(dict.fromkeys(warnings)),
        )


class SemanticMemoryMetadataRepository:
    """Joined Memory360 card and embedding metadata read facade."""

    def __init__(
        self,
        *,
        card_repository: Optional[SemanticContextCardRepository] = None,
        embedding_repository: Optional[SemanticEmbeddingMetadataRepository] = None,
    ) -> None:
        self.cards = card_repository or SemanticContextCardRepository()
        self.embeddings = embedding_repository or SemanticEmbeddingMetadataRepository(
            card_repository=self.cards
        )

    async def read_for_subject(
        self, tenant_id: str, subject_ref: str, *, offset: int, limit: int
    ) -> MemoryAuthorityRead:
        card_read = await self.cards.read_for_subject(
            tenant_id, subject_ref, offset=offset, limit=limit
        )
        embedding_read = await self.embeddings.read_for_subject(
            tenant_id, subject_ref, offset=offset, limit=limit
        )
        if not isinstance(card_read, MemoryAuthorityRead):
            card_read = MemoryAuthorityRead()
        warnings = list(card_read.warnings) + list(embedding_read.warnings)
        return MemoryAuthorityRead(
            cards=card_read.cards,
            cards_state=card_read.cards_state,
            cards_complete=card_read.cards_complete,
            cards_truncated=card_read.cards_truncated,
            cards_next_offset=card_read.cards_next_offset,
            embeddings=embedding_read.embeddings,
            embeddings_state=embedding_read.embeddings_state,
            embeddings_complete=embedding_read.embeddings_complete,
            embeddings_truncated=embedding_read.embeddings_truncated,
            embeddings_next_offset=embedding_read.embeddings_next_offset,
            warnings=tuple(dict.fromkeys(warnings)),
        )


async def _append_immutable(
    repository: MemoryAuthorityFactStore,
    *,
    table: str,
    record_id: str,
    tenant_id: str,
    subject_ref: str,
    created_at: datetime,
    payload: dict[str, Any],
    idempotency_key: str,
    model: type[BaseModel],
) -> None:
    fact_data = {**payload, "idempotency_key": idempotency_key}
    existing_rows = await repository.find_by_ids(tenant_id, [record_id], subject=subject_ref)
    if existing_rows:
        existing_data = _row_data(_mapping(existing_rows[0]))
        if existing_data is None or _domain_payload(existing_data) != payload:
            raise ValueError(f"{table}_record_is_append_only")
        return
    stored = await repository.upsert(
        {
            "id": record_id,
            "tenant_id": tenant_id,
            "source_event_id": None,
            "subject_ref": subject_ref,
            "campaign_id": None,
            "occurred_at": created_at,
            "idempotency_key": idempotency_key,
            "data": fact_data,
        }
    )
    stored_data = _row_data(stored)
    try:
        persisted = model.model_validate(_domain_payload(stored_data or {})).model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001 - immutable row conflict
        raise ValueError(f"{table}_record_is_append_only") from exc
    if persisted != model.model_validate(payload).model_dump(mode="json"):
        raise ValueError(f"{table}_record_is_append_only")


def _exact_memory_page(page: Any, memory_ids: list[str]) -> bool:
    records = getattr(page, "records", ())
    return bool(
        getattr(page, "state", "unknown") == "available"
        and {record.record.memory_id for record in records} == set(memory_ids)
    )


def _domain_payload(data: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    ignored = {"idempotency_key", "record_id"}
    return {key: value for key, value in data.items() if key not in ignored}


def _row_data(row: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if row is None:
        return None
    return _mapping(row.get("data")) or row


def _exact_policy_ref(
    raw: Optional[dict[str, Any]],
    *,
    tenant_id: str,
    subject_ref: str,
    resource_type: str,
    resource_id: str,
    decision_id: str,
) -> Optional[EvidenceRef]:
    row = _mapping(raw)
    if not (
        row
        and row.get("policy_decision_id") == decision_id
        and row.get("tenant_id") == tenant_id
        and row.get("subject_ref") == subject_ref
        and row.get("resource_type") == resource_type
        and row.get("resource_id") == resource_id
        and row.get("action") == "generate_feature"
        and row.get("allowed") is True
    ):
        return None
    observed_at = _timestamp(row.get("created_at"))
    if observed_at is None:
        return None
    return EvidenceRef(
        id=decision_id,
        type="annotation",
        source="governance.consent_policy_decisions",
        observedAt=observed_at,
        uri=(
            "store://consent_policy_decisions/"
            f"{quote(tenant_id, safe='')}:{quote(decision_id, safe='')}"
        ),
    )


def _card_ref(card: SemanticContextCard) -> Optional[EvidenceRef]:
    observed_at = _timestamp(card.created_at)
    if observed_at is None:
        return None
    return EvidenceRef(
        id=card.card_id,
        type="annotation",
        source=f"semantic_intelligence.{_CARD_TABLE}",
        observedAt=observed_at,
        uri=f"store://{_CARD_TABLE}/{quote(card.tenant_id, safe='')}:{quote(card.card_id, safe='')}",
    )


def _embedding_ref(metadata: SemanticEmbeddingMetadata) -> Optional[EvidenceRef]:
    observed_at = _timestamp(metadata.observed_at)
    if observed_at is None:
        return None
    return EvidenceRef(
        id=metadata.embedding_id,
        type="annotation",
        source=f"semantic_intelligence.{_EMBEDDING_TABLE}",
        observedAt=observed_at,
        uri=(
            f"store://{_EMBEDDING_TABLE}/"
            f"{quote(metadata.tenant_id, safe='')}:{quote(metadata.embedding_id, safe='')}"
        ),
    )


def _dedupe_refs(refs: list[EvidenceRef]) -> list[EvidenceRef]:
    output: list[EvidenceRef] = []
    seen: set[tuple[str, str, str]] = set()
    for ref in refs:
        key = (ref.id, ref.type, ref.source)
        if key not in seen:
            seen.add(key)
            output.append(ref)
    return output


__all__ = [
    "MemoryAuthorityRead",
    "ResolvedContextCard",
    "ResolvedEmbeddingMetadata",
    "SemanticContextCard",
    "SemanticContextCardRepository",
    "SemanticEmbeddingMetadata",
    "SemanticEmbeddingMetadataRepository",
    "SemanticMemoryMetadataRepository",
]
