"""WS-D durable truth stores.

Each store wraps a named ``shared.store.get_store(...)`` (the SAME durable
seam that backs ``ai_execution_facts`` / agent tasks — Redis in production,
in-memory locally) and serializes WS-D primitive carriers as JSON documents.
No new alembic table is required for these stores: they are KV documents
keyed by ``tenant_id:record_id`` with top-level ``tenant_id`` so
``DurableStore.find(tenant_id=...)`` stays tenant-scoped end to end.

Stores here are INERT unless the caller enables the owning flag:
``RelationshipFactStore`` (item 1 / flag ``relationship_fact_enabled``),
``EpisodeStore`` + the episode engine (item 2 / ``episode_engine_enabled``),
``OutcomeTruthStore`` (item 3 / ``outcome_truth_store_enabled``) and
``CorrelationRegistry`` (item 6 / ``correlation_first_class_enabled``). The
store classes never check the flag themselves — callers gate the *write path*;
the classes are safe to construct and read at any time.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from shared.backend_interpretation.primitives import (
    EpisodeRecord,
    OutcomeContextRef,
    OutcomeTruthRecord,
    RelationshipFact,
    OUTCOME_STATES,
)
from shared.store import DurableStore, get_store

logger = logging.getLogger("aether.backend_interpretation.stores")

_STORE_RELATIONSHIP_FACTS = "relationship_facts"
_STORE_EPISODES = "episode_records"
_STORE_OUTCOME_TRUTH = "outcome_truth"
_STORE_CORRELATION = "correlation_registry"

# In-memory singleton factories keyed by store name (tests reset via
# ``shared.store.reset_in_memory_stores``).
_factories: dict[str, type["BaseTruthStore"]] = {}


def _kv(name: str) -> DurableStore:
    return get_store(name)


# ── Base ─────────────────────────────────────────────────────────────────────


class BaseTruthStore:
    """JSON-document KV wrapper over a named ``DurableStore``."""

    store_name = "base"
    _document_type = dict

    def __init__(self) -> None:
        self._store = _kv(self.store_name)

    # Internal JSON round-trip (documents are plain JSON; carriers validated on
    # read so a corrupt/foreign row is a typed skip, never a raise).
    def _roundtrip(self, document: dict[str, Any]) -> Optional[dict[str, Any]]:
        return document

    async def _get_doc(self, key: str) -> Optional[dict[str, Any]]:
        return await self._store.get(key)

    async def _set_doc(self, key: str, document: dict[str, Any]) -> None:
        await self._store.set(key, document)

    async def _delete_doc(self, key: str) -> bool:
        return await self._store.delete(key)

    async def _find_docs(self, tenant_id: str) -> list[dict[str, Any]]:
        return await self._store.find(tenant_id=tenant_id)


# ── Relationship facts (item 1) ──────────────────────────────────────────────


class RelationshipFactStore(BaseTruthStore):
    """Durable store for typed :class:`RelationshipFact` rows."""

    store_name = _STORE_RELATIONSHIP_FACTS

    @staticmethod
    def _key(tenant_id: str, fact_id: str) -> str:
        return f"{tenant_id}:{fact_id}"

    async def upsert(self, fact: RelationshipFact) -> RelationshipFact:
        await self._store.set(self._key(fact.tenant_id, fact.fact_id), fact.model_dump(mode="json"))
        return fact

    async def get(self, tenant_id: str, fact_id: str) -> Optional[RelationshipFact]:
        doc = await self._get_doc(self._key(tenant_id, fact_id))
        if not doc:
            return None
        return RelationshipFact.model_validate(doc)

    async def delete(self, tenant_id: str, fact_id: str) -> bool:
        return await self._delete_doc(self._key(tenant_id, fact_id))

    async def list_by_tenant(self, tenant_id: str) -> list[RelationshipFact]:
        facts: list[RelationshipFact] = []
        for doc in await self._find_docs(tenant_id):
            try:
                facts.append(RelationshipFact.model_validate(doc))
            except Exception:  # noqa: BLE001 - typed skip on foreign/corrupt row
                logger.warning("Skipping non-relationship-fact row in %s", self.store_name)
        return facts

    async def list_active(self, tenant_id: str) -> list[RelationshipFact]:
        return [f for f in await self.list_by_tenant(tenant_id) if f.is_active]


# ── Episodes (item 2) ────────────────────────────────────────────────────────


class EpisodeStore(BaseTruthStore):
    """Durable store for canonical :class:`EpisodeRecord` rows."""

    store_name = _STORE_EPISODES

    @staticmethod
    def _key(tenant_id: str, episode_id: str) -> str:
        return f"{tenant_id}:{episode_id}"

    async def upsert(self, record: EpisodeRecord) -> EpisodeRecord:
        await self._store.set(
            self._key(record.tenant_id, record.episode_id),
            record.model_dump(mode="json"),
        )
        return record

    async def get(self, tenant_id: str, episode_id: str) -> Optional[EpisodeRecord]:
        doc = await self._get_doc(self._key(tenant_id, episode_id))
        if not doc:
            return None
        return EpisodeRecord.model_validate(doc)

    async def delete(self, tenant_id: str, episode_id: str) -> bool:
        return await self._delete_doc(self._key(tenant_id, episode_id))

    async def list_by_tenant(self, tenant_id: str) -> list[EpisodeRecord]:
        records: list[EpisodeRecord] = []
        for doc in await self._find_docs(tenant_id):
            try:
                records.append(EpisodeRecord.model_validate(doc))
            except Exception:  # noqa: BLE001
                logger.warning("Skipping non-episode row in %s", self.store_name)
        return records

    async def list_page_by_tenant(
        self,
        tenant_id: str,
        *,
        limit: int,
        cursor: Optional[str] = None,
    ) -> "EpisodePageRead":
        """Read one bounded tenant episode page and retain malformed-row state."""
        if not tenant_id:
            raise ValueError("list_page_by_tenant requires a tenant_id")
        documents, next_cursor, truncated = await self._store.find_page(
            limit=limit,
            cursor=cursor,
            key_prefix=f"{tenant_id}:",
        )
        records: list[EpisodeRecord] = []
        invalid_records = False
        for document in documents:
            if not isinstance(document, dict) or document.get("tenant_id") != tenant_id:
                invalid_records = True
                continue
            try:
                records.append(EpisodeRecord.model_validate(document))
            except Exception:  # noqa: BLE001 - malformed rows degrade completeness
                invalid_records = True
        return EpisodePageRead(
            records=tuple(records),
            next_cursor=next_cursor,
            truncated=truncated,
            invalid_records=invalid_records,
        )

    async def list_for_subject(
        self, tenant_id: str, kind: str, subject_id: str
    ) -> list[EpisodeRecord]:
        subject_match = _subject_matches
        return [
            r
            for r in await self.list_by_tenant(tenant_id)
            if subject_match(r.subject, kind, subject_id)
        ]


@dataclass(frozen=True)
class EpisodePageRead:
    """One tenant-bounded page of validated durable episode records."""

    records: tuple[EpisodeRecord, ...]
    next_cursor: Optional[str]
    truncated: bool
    invalid_records: bool = False


# ── Outcome truth (item 3) ───────────────────────────────────────────────────


class OutcomeTruthStore(BaseTruthStore):
    """Durable outcome-truth store WITH lineage (item 3).

    Rows are :class:`OutcomeTruthRecord` documents that retain evidence_refs +
    model/policy derivation lineage the identity-style outcome read drops today.
    """

    store_name = _STORE_OUTCOME_TRUTH

    @staticmethod
    def _key(tenant_id: str, outcome_id: str) -> str:
        return f"{tenant_id}:{outcome_id}"

    async def upsert(self, record: OutcomeTruthRecord) -> OutcomeTruthRecord:
        await self._store.set(
            self._key(record.tenant_id, record.outcome_id),
            record.model_dump(mode="json"),
        )
        return record

    async def get(self, tenant_id: str, outcome_id: str) -> Optional[OutcomeTruthRecord]:
        doc = await self._get_doc(self._key(tenant_id, outcome_id))
        if not doc:
            return None
        return OutcomeTruthRecord.model_validate(doc)

    async def delete(self, tenant_id: str, outcome_id: str) -> bool:
        return await self._delete_doc(self._key(tenant_id, outcome_id))

    async def list_by_tenant(self, tenant_id: str) -> list[OutcomeTruthRecord]:
        records: list[OutcomeTruthRecord] = []
        for doc in await self._find_docs(tenant_id):
            try:
                records.append(OutcomeTruthRecord.model_validate(doc))
            except Exception:  # noqa: BLE001
                logger.warning("Skipping non-outcome row in %s", self.store_name)
        return records

    async def list_for_prediction(
        self,
        tenant_id: str,
        prediction_id: str,
        label_contract_version: str,
        *,
        limit: int,
    ) -> tuple[list[OutcomeTruthRecord], bool, bool]:
        """Return a bounded exact tenant/prediction/label-contract lookup.

        The backing store has no secondary index for prediction associations.
        Use its bounded tenant-key page and exact document filters; callers get
        ``truncated`` when the tenant page has more rows to scan and
        ``invalid_records`` when a matching document cannot be validated.
        No subject or time correlation is used to fill missing references.
        """
        if not tenant_id or not prediction_id or not label_contract_version:
            return [], False, True
        bounded = min(max(int(limit), 1), 100)
        page_size = 250
        max_scanned = 5_000
        cursor: Optional[str] = None
        scanned = 0
        truncated = False
        docs: list[dict[str, Any]] = []
        while scanned < max_scanned:
            page_limit = min(page_size, max_scanned - scanned)
            page, cursor, has_more = await self._store.find_page(
                limit=page_limit,
                cursor=cursor,
                key_prefix=f"{tenant_id}:",
                tenant_id=tenant_id,
                prediction_id=prediction_id,
                prediction_label_contract_version=label_contract_version,
            )
            docs.extend(page)
            scanned += page_limit
            # Two exact rows are enough to establish ambiguity. Do not read
            # further records for an association that must be suppressed.
            if len(docs) > 1:
                truncated = False
                break
            if not has_more:
                cursor = None
                break
            if scanned >= max_scanned:
                truncated = True
                break
        records: list[OutcomeTruthRecord] = []
        invalid_records = False
        for doc in docs:
            try:
                record = OutcomeTruthRecord.model_validate(doc)
            except Exception:  # noqa: BLE001 - malformed canonical rows fail closed
                invalid_records = True
                continue
            if (
                record.tenant_id != tenant_id
                or record.prediction_id != prediction_id
                or record.prediction_label_contract_version != label_contract_version
                or record.state not in OUTCOME_STATES
            ):
                invalid_records = True
                continue
            records.append(record)
        return records[:bounded], truncated or len(records) > bounded, invalid_records


# ── Correlation registry (item 6) ────────────────────────────────────────────


class CorrelationRegistry(BaseTruthStore):
    """First-class correlation registry (Invariant #12 / item 6).

    Correlation is today opaque (dropped at graph promotion). This registry is
    the canonical, tenant-scoped, first-class index: one row per
    ``(tenant_id, correlation_id)`` family, accumulating the observation ids,
    evidence refs and causation links that produced it. Written only when
    ``correlation_first_class_enabled`` is ON.
    """

    store_name = _STORE_CORRELATION

    @staticmethod
    def _key(tenant_id: str, correlation_id: str) -> str:
        return f"{tenant_id}:{correlation_id}"

    async def get(self, tenant_id: str, correlation_id: str) -> Optional[dict[str, Any]]:
        return await self._get_doc(self._key(tenant_id, correlation_id))

    async def register(
        self,
        *,
        tenant_id: str,
        correlation_id: str,
        observation_id: Optional[str] = None,
        evidence_ref: Optional[dict[str, Any]] = None,
        causation_id: Optional[str] = None,
        source: Optional[str] = None,
    ) -> dict[str, Any]:
        """Merge one observation/evidence ref into a correlation family."""
        key = self._key(tenant_id, correlation_id)
        row = await self._get_doc(key)
        if not row:
            row = {
                "tenant_id": tenant_id,
                "correlation_id": correlation_id,
                "causation_id": causation_id,
                "observation_ids": [],
                "evidence_refs": [],
                "sources": [],
            }
        if causation_id and not row.get("causation_id"):
            row["causation_id"] = causation_id
        if observation_id and observation_id not in row["observation_ids"]:
            row["observation_ids"].append(observation_id)
        if evidence_ref and evidence_ref.get("id"):
            ids = {r.get("id") for r in row["evidence_refs"]}
            if evidence_ref["id"] not in ids:
                row["evidence_refs"].append(evidence_ref)
        if source and source not in row["sources"]:
            row["sources"].append(source)
        row["observation_count"] = len(row["observation_ids"])
        await self._set_doc(key, row)
        return row

    async def list_by_tenant(self, tenant_id: str) -> list[dict[str, Any]]:
        return [
            row
            for row in await self._find_docs(tenant_id)
            if isinstance(row, dict) and row.get("correlation_id")
        ]


def _subject_matches(subject: Any, kind: str, subject_id: str) -> bool:
    if subject is None:
        return False
    if isinstance(subject, dict):
        return subject.get("kind") == kind and subject.get("id") == subject_id
    return getattr(subject, "kind", None) == kind and getattr(subject, "id", None) == subject_id


# Projection-plane subject vocabulary (generated registry) — deliberately
# coarser than ``EntityRef.kind``. Durable WS-D rows carry rich ``EntityRef``
# kinds ("user", "org", ...); projection requests carry these coarse kinds
# ("entity", "campaign", ...).
_PROJECTION_SUBJECT_KINDS = frozenset(
    (
        "agent",
        "campaign",
        "cluster",
        "connection",
        "deployment",
        "entity",
        "episode",
        "infrastructure",
        "population",
        "relationship",
        "source",
    )
)


def subject_matches_request(subject: Any, request_kind: str, request_id: str) -> bool:
    """Match a durable row's ``EntityRef`` subject to a coarse request subject.

    Exact ``(kind, id)`` equality wins (rich-kind requests stay precise). A
    coarse request kind cannot be stored on an ``EntityRef`` row, so a coarse
    request addresses durable rows by id — a user-scoped outcome row stays
    reachable from an ``entity``/``campaign`` request about that user while
    tenant scoping still holds end to end.
    """
    if subject is None or not request_id:
        return False
    if isinstance(subject, dict):
        kind = subject.get("kind")
        subject_id = subject.get("id")
    else:
        kind = getattr(subject, "kind", None)
        subject_id = getattr(subject, "id", None)
    if subject_id != request_id:
        return False
    if kind == request_kind:
        return True
    if isinstance(subject, OutcomeContextRef):
        # Product measurement contexts are exact references, not coarse
        # aliases for another context that happens to reuse the same id.
        return False
    if request_kind == "agent":
        # Agent is a canonical entity kind in EntityRef. Do not let a coarse
        # agent request bind an unrelated same-id user/entity outcome row.
        return False
    return request_kind in _PROJECTION_SUBJECT_KINDS


# ── Outcome360 provider adapter (item 3 wiring) ──────────────────────────────


class OutcomeTruthStoreReader:
    """Reads OutcomeTruthRecords as measurement :class:`Outcome` rows.

    Satisfies the ``journeys.measurement.outcome.provider.OutcomeStore``
    protocol surface (``async list_outcomes(tenant_id, subject)``) so the
    ``outcome360`` provider can read durable, lineage-carrying outcome truth
    instead of returning ``None``. The exact-money strings and derivation
    lineage live on the durable :class:`OutcomeTruthRecord`; the legacy
    contract's ``value: Optional[float]`` is projected from a present
    ``value_amount`` only (never a silent 0.0). Agent subjects require exact
    agent-kind EntityRef matches; a same-id user or other entity row is excluded.
    """

    def __init__(self, store: Optional[OutcomeTruthStore] = None) -> None:
        self._store = store or OutcomeTruthStore()

    async def list_outcomes(self, tenant_id: str, subject: Any) -> list[Any]:
        from journeys.measurement.outcome.contracts import Outcome, OutcomeState

        rows = await self._store.list_by_tenant(tenant_id)
        outcomes: list[Outcome] = []
        subject_id = getattr(subject, "id", None)
        subject_kind = getattr(subject, "kind", None)
        for row in rows:
            if not subject_matches_request(row.subject, subject_kind, subject_id):
                continue
            value: Optional[float] = None
            if row.value_state in ("present", "zero", "empty", "degraded"):
                try:
                    value = (
                        float(row.value_amount)
                        if row.value_amount not in (None, "")
                        else (0.0 if row.value_state == "zero" else None)
                    )
                except (TypeError, ValueError):
                    value = None
            try:
                state = OutcomeState(row.state)
            except ValueError:
                state = OutcomeState.UNKNOWN
            outcomes.append(
                Outcome(
                    id=row.outcome_id,
                    tenant_id=row.tenant_id,
                    domain=row.definition_ref,
                    state=state,
                    definition_ref=row.definition_ref,
                    achieved_at=row.achieved_at,
                    value=value,
                    evidence_refs=row.evidence_refs,
                    prediction_id=row.prediction_id,
                    prediction_label_contract_version=row.prediction_label_contract_version,
                    updated_at=row.updated_at,
                )
            )
        return outcomes


def relationship_fact_store() -> RelationshipFactStore:
    return RelationshipFactStore()


def episode_store() -> EpisodeStore:
    return EpisodeStore()


def outcome_truth_store() -> OutcomeTruthStore:
    return OutcomeTruthStore()


def correlation_registry() -> CorrelationRegistry:
    return CorrelationRegistry()


__all__ = [
    "BaseTruthStore",
    "CorrelationRegistry",
    "EpisodeStore",
    "OutcomeTruthStore",
    "OutcomeTruthStoreReader",
    "RelationshipFactStore",
    "correlation_registry",
    "episode_store",
    "outcome_truth_store",
    "relationship_fact_store",
]
