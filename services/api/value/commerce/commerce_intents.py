"""Canonical tenant-scoped commerce intent declarations.

This authority stores explicit declarations about a canonical product or
offer. It does not promote product views, cart changes, checkouts, targeting
plans, or payment attempts into purchase intent. Records are immutable source
revisions with tenant scope, actor attribution, temporal context, idempotency,
and evidence references.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from graph.operational_intelligence.models import EvidenceRef
from repositories.repos import get_pool
from value.commerce.product_offer_catalog import CommerceProductOfferCatalogRepository


CommerceIntentSubjectKind = Literal["product", "offer"]
CommerceIntentKind = Literal["purchase", "subscription", "renewal", "replenishment", "comparison"]
CommerceIntentState = Literal[
    "declared", "active", "fulfilled", "abandoned", "withdrawn", "expired"
]
CommerceIntentActorKind = Literal["human", "org", "wallet", "agent", "service", "system"]

_LOCAL = os.getenv("AETHER_ENV", "local").lower() == "local"
_MAX_INTENT_EVIDENCE_REFS = 32
_MAX_INTENTS_PER_SUBJECT = 500
_LOCAL_INTENTS: dict[tuple[str, str, str], dict[str, Any]] = {}
_LOCAL_INTENT_LOCK = asyncio.Lock()
_API_SOURCE = "aether_commerce_intent_api"


def _instant(value: Any, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field_name} must be an ISO-8601 timestamp") from exc
    else:
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp")
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _identifier(value: str, field_name: str, max_length: int = 512) -> str:
    if not value.strip() or len(value) > max_length or any(ord(char) < 32 for char in value):
        raise ValueError(f"{field_name} must be non-empty text without control characters")
    return value


class CommerceIntentDeclaration(BaseModel):
    """Strict human declaration input; actor and provenance are server-bound."""

    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=256)
    intent_id: Optional[str] = Field(default=None, min_length=1, max_length=256)
    subject_kind: CommerceIntentSubjectKind
    subject_id: str = Field(min_length=1, max_length=256)
    intent_kind: CommerceIntentKind
    state: CommerceIntentState = "declared"
    effective_at: Optional[datetime] = None

    @model_validator(mode="before")
    @classmethod
    def normalize_effective_at(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        normalized = dict(values)
        if normalized.get("effective_at") is not None:
            normalized["effective_at"] = _instant(normalized["effective_at"], "effective_at")
        return normalized

    @model_validator(mode="after")
    def validate_identifiers(self) -> "CommerceIntentDeclaration":
        _identifier(self.idempotency_key, "idempotency_key", 256)
        _identifier(self.subject_id, "subject_id", 256)
        if self.intent_id is not None:
            _identifier(self.intent_id, "intent_id", 256)
        return self


class CommerceIntentRecord(BaseModel):
    """One immutable source revision for an explicit commerce intent."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1, max_length=128)
    intent_id: str = Field(min_length=1, max_length=256)
    idempotency_key: str = Field(min_length=1, max_length=256)
    subject_kind: CommerceIntentSubjectKind
    subject_id: str = Field(min_length=1, max_length=256)
    intent_kind: CommerceIntentKind
    state: CommerceIntentState
    actor_kind: CommerceIntentActorKind
    actor_id: str = Field(min_length=1, max_length=256)
    effective_at: datetime
    observed_at: datetime
    source_provider: str = Field(min_length=1, max_length=96)
    source_record_id: str = Field(min_length=1, max_length=512)
    source_revision_id: str = Field(min_length=1, max_length=512)
    evidence_refs: list[EvidenceRef] = Field(min_length=1, max_length=_MAX_INTENT_EVIDENCE_REFS)

    @model_validator(mode="before")
    @classmethod
    def normalize_instants(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        normalized = dict(values)
        for name in ("effective_at", "observed_at"):
            if name in normalized:
                normalized[name] = _instant(normalized[name], name)
        return normalized

    @model_validator(mode="after")
    def validate_identity_and_evidence(self) -> "CommerceIntentRecord":
        for name in (
            "tenant_id",
            "intent_id",
            "idempotency_key",
            "subject_id",
            "actor_id",
            "source_provider",
            "source_record_id",
            "source_revision_id",
        ):
            _identifier(getattr(self, name), name)
        if not any(
            ref.source == self.source_provider and ref.id == self.source_record_id
            for ref in self.evidence_refs
        ):
            raise ValueError("evidence_refs must include the exact source record")
        return self


class CommerceIntentSubjectNotFound(ValueError):
    """The canonical subject is absent from this tenant's catalog authority."""


class CommerceIntentIdempotencyConflict(ValueError):
    """An idempotency key or immutable source revision was reused with changes."""


class CommerceIntentRepository:
    """Append-only intent revisions, tenant-exact and queryable as of a time.

    The local memory backend mirrors the production PostgreSQL schema for
    tests and local development. Production reads and writes use the migration
    owned ``commerce_intent_records`` table.
    """

    def __init__(
        self,
        catalog: Optional[CommerceProductOfferCatalogRepository] = None,
    ) -> None:
        self._catalog = catalog or CommerceProductOfferCatalogRepository()
        self._local = _LOCAL_INTENTS

    async def _pool(self) -> Any:
        return None if _LOCAL else await get_pool()

    async def _require_canonical_subject(self, record: CommerceIntentRecord) -> None:
        if record.subject_kind == "product":
            subject = await self._catalog.get_product(
                record.tenant_id, record.subject_id, as_of=record.effective_at
            )
        else:
            subject = await self._catalog.get_offer(
                record.tenant_id, record.subject_id, as_of=record.effective_at
            )
        if subject is None:
            raise CommerceIntentSubjectNotFound(
                "intent must reference an existing product or offer owned by the same tenant"
            )

    async def record_intent(self, record: CommerceIntentRecord) -> CommerceIntentRecord:
        """Persist one immutable revision after verifying its exact subject."""
        await self._require_canonical_subject(record)
        payload = record.model_dump(mode="json")
        key = (record.tenant_id, record.intent_id, record.source_revision_id)
        pool = await self._pool()
        if pool is None:
            async with _LOCAL_INTENT_LOCK:
                existing_idempotency = next(
                    (
                        raw
                        for (tenant_id, _, _), raw in self._local.items()
                        if tenant_id == record.tenant_id
                        and raw.get("idempotency_key") == record.idempotency_key
                    ),
                    None,
                )
                if existing_idempotency is not None:
                    return self._same_idempotent_record(existing_idempotency, payload)
                existing_revision = self._local.get(key)
                if existing_revision is not None:
                    return self._same_idempotent_record(existing_revision, payload)
                self._local[key] = payload
            return record

        async with pool.acquire() as conn:
            inserted = await conn.fetchrow(
                """
                INSERT INTO commerce_intent_records (
                    tenant_id, intent_id, source_revision_id, idempotency_key,
                    subject_kind, subject_id, intent_kind, lifecycle_state,
                    actor_kind, actor_id, effective_at, observed_at,
                    source_provider, source_record_id, evidence_refs, data
                ) VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15::jsonb,$16::jsonb
                )
                ON CONFLICT DO NOTHING
                RETURNING source_revision_id
                """,
                record.tenant_id,
                record.intent_id,
                record.source_revision_id,
                record.idempotency_key,
                record.subject_kind,
                record.subject_id,
                record.intent_kind,
                record.state,
                record.actor_kind,
                record.actor_id,
                record.effective_at,
                record.observed_at,
                record.source_provider,
                record.source_record_id,
                json.dumps([ref.model_dump(mode="json") for ref in record.evidence_refs]),
                json.dumps(payload),
            )
            if inserted is not None:
                return record
            existing = await conn.fetchrow(
                """SELECT data FROM commerce_intent_records
                   WHERE tenant_id=$1 AND idempotency_key=$2
                   UNION ALL
                   SELECT data FROM commerce_intent_records
                   WHERE tenant_id=$1 AND intent_id=$3 AND source_revision_id=$4
                   LIMIT 1""",
                record.tenant_id,
                record.idempotency_key,
                record.intent_id,
                record.source_revision_id,
            )
        if existing is None:
            raise RuntimeError("commerce intent write conflicted without a matching revision")
        return self._same_idempotent_record(_json_object(existing["data"]), payload)

    async def record_declaration(
        self,
        tenant_id: str,
        actor_kind: CommerceIntentActorKind,
        actor_id: str,
        declaration: CommerceIntentDeclaration,
    ) -> CommerceIntentRecord:
        """Record a human/API declaration with server-generated provenance."""
        intent_id = declaration.intent_id or _stable_intent_id(
            tenant_id, declaration.idempotency_key
        )
        existing = await self._get_by_idempotency_key(tenant_id, declaration.idempotency_key)
        if existing is not None:
            return self._same_declaration(existing, declaration, intent_id, actor_kind, actor_id)

        observed_at = datetime.now(timezone.utc)
        source_record_id = f"commerce-intent-api:{declaration.idempotency_key}"
        record = CommerceIntentRecord(
            tenant_id=tenant_id,
            intent_id=intent_id,
            idempotency_key=declaration.idempotency_key,
            subject_kind=declaration.subject_kind,
            subject_id=declaration.subject_id,
            intent_kind=declaration.intent_kind,
            state=declaration.state,
            actor_kind=actor_kind,
            actor_id=actor_id,
            effective_at=declaration.effective_at or observed_at,
            observed_at=observed_at,
            source_provider=_API_SOURCE,
            source_record_id=source_record_id,
            source_revision_id=declaration.idempotency_key,
            evidence_refs=[
                EvidenceRef(
                    id=source_record_id,
                    type="annotation",
                    source=_API_SOURCE,
                )
            ],
        )
        try:
            return await self.record_intent(record)
        except CommerceIntentIdempotencyConflict:
            # Concurrent retries can both observe an absent key before one
            # wins the unique insert. Resolve that race against the stored
            # immutable declaration rather than rejecting its fresh clock read.
            existing = await self._get_by_idempotency_key(tenant_id, declaration.idempotency_key)
            if existing is None:
                raise
            return self._same_declaration(existing, declaration, intent_id, actor_kind, actor_id)

    async def list_for_subject(
        self,
        tenant_id: str,
        subject_kind: CommerceIntentSubjectKind,
        subject_id: str,
        *,
        as_of: Optional[datetime] = None,
        limit: int = _MAX_INTENTS_PER_SUBJECT,
    ) -> tuple[list[CommerceIntentRecord], bool]:
        """Return latest effective revision per intent and whether it was capped.

        Both source effective time and AETHER observation time must be at or
        before the requested anchor. An empty result is complete for explicit
        records held by this authority; it says nothing about unobserved intent
        outside this authority.
        """
        if not tenant_id or not subject_id:
            return [], False
        anchor = _instant(as_of or datetime.now(timezone.utc), "as_of")
        limit = min(max(int(limit), 1), _MAX_INTENTS_PER_SUBJECT)
        pool = await self._pool()
        if pool is None:
            candidates = [
                CommerceIntentRecord.model_validate(raw)
                for (row_tenant, _, _), raw in self._local.items()
                if row_tenant == tenant_id
                and raw.get("subject_kind") == subject_kind
                and raw.get("subject_id") == subject_id
            ]
            latest: dict[str, CommerceIntentRecord] = {}
            for row in candidates:
                if row.effective_at > anchor or row.observed_at > anchor:
                    continue
                current = latest.get(row.intent_id)
                row_order = (row.effective_at, row.observed_at, row.source_revision_id)
                current_order = (
                    (current.effective_at, current.observed_at, current.source_revision_id)
                    if current is not None
                    else None
                )
                if current_order is None or row_order > current_order:
                    latest[row.intent_id] = row
            ordered = sorted(
                latest.values(),
                key=lambda row: (row.effective_at, row.observed_at, row.intent_id),
                reverse=True,
            )
            return ordered[:limit], len(ordered) > limit

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                WITH latest AS (
                    SELECT DISTINCT ON (intent_id)
                        intent_id, source_revision_id, effective_at, observed_at, data
                    FROM commerce_intent_records
                    WHERE tenant_id=$1 AND subject_kind=$2 AND subject_id=$3
                      AND effective_at <= $4 AND observed_at <= $4
                    ORDER BY intent_id, effective_at DESC, observed_at DESC,
                             source_revision_id DESC
                )
                SELECT data FROM latest
                ORDER BY effective_at DESC, observed_at DESC, intent_id DESC
                LIMIT $5
                """,
                tenant_id,
                subject_kind,
                subject_id,
                anchor,
                limit + 1,
            )
        truncated = len(rows) > limit
        records = [
            CommerceIntentRecord.model_validate(_json_object(row["data"])) for row in rows[:limit]
        ]
        return records, truncated

    async def _get_by_idempotency_key(
        self, tenant_id: str, idempotency_key: str
    ) -> Optional[CommerceIntentRecord]:
        pool = await self._pool()
        if pool is None:
            raw = next(
                (
                    value
                    for (row_tenant, _, _), value in self._local.items()
                    if row_tenant == tenant_id and value.get("idempotency_key") == idempotency_key
                ),
                None,
            )
            return CommerceIntentRecord.model_validate(raw) if raw is not None else None
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT data FROM commerce_intent_records
                   WHERE tenant_id=$1 AND idempotency_key=$2""",
                tenant_id,
                idempotency_key,
            )
        return (
            CommerceIntentRecord.model_validate(_json_object(row["data"]))
            if row is not None
            else None
        )

    @staticmethod
    def _same_declaration(
        existing: CommerceIntentRecord,
        declaration: CommerceIntentDeclaration,
        intent_id: str,
        actor_kind: CommerceIntentActorKind,
        actor_id: str,
    ) -> CommerceIntentRecord:
        same = (
            existing.intent_id == intent_id
            and existing.subject_kind == declaration.subject_kind
            and existing.subject_id == declaration.subject_id
            and existing.intent_kind == declaration.intent_kind
            and existing.state == declaration.state
            and existing.actor_kind == actor_kind
            and existing.actor_id == actor_id
            and existing.idempotency_key == declaration.idempotency_key
            and (
                declaration.effective_at is None
                or existing.effective_at == declaration.effective_at
            )
        )
        if not same:
            raise CommerceIntentIdempotencyConflict(
                "idempotency key was reused with a different declaration"
            )
        return existing

    @staticmethod
    def _same_idempotent_record(
        existing: dict[str, Any], incoming: dict[str, Any]
    ) -> CommerceIntentRecord:
        if _idempotency_content(existing) != _idempotency_content(incoming):
            raise CommerceIntentIdempotencyConflict(
                "idempotency key or source revision was reused with different content"
            )
        return CommerceIntentRecord.model_validate(existing)


def _idempotency_content(value: dict[str, Any]) -> dict[str, Any]:
    """Ignore server observation time on replay; source facts stay exact."""
    result = dict(value)
    result.pop("observed_at", None)
    return result


def _stable_intent_id(tenant_id: str, idempotency_key: str) -> str:
    basis = f"{tenant_id}\x00{idempotency_key}".encode("utf-8")
    return f"ci_{hashlib.sha256(basis).hexdigest()[:32]}"


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


__all__ = [
    "CommerceIntentActorKind",
    "CommerceIntentDeclaration",
    "CommerceIntentIdempotencyConflict",
    "CommerceIntentKind",
    "CommerceIntentRecord",
    "CommerceIntentRepository",
    "CommerceIntentState",
    "CommerceIntentSubjectKind",
    "CommerceIntentSubjectNotFound",
]
