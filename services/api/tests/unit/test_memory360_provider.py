"""Memory360 contract behavior over tenant-scoped semantic records."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from graph.operational_intelligence.models import EvidenceRef  # noqa: E402
from intelligence.semantic_intelligence.memory360_provider import (  # noqa: E402
    Memory360Provider,
    RepositorySemanticMemoryReader,
    SemanticMemoryRead,
)
from intelligence.semantic_intelligence.memory_records import (  # noqa: E402
    ResolvedMemoryRecord,
    SemanticMemoryRecord,
    SemanticMemoryRecordRepository,
)
from intelligence.semantic_intelligence.memory_authorities import (  # noqa: E402
    SemanticContextCard,
    SemanticContextCardRepository,
    SemanticEmbeddingMetadata,
    SemanticEmbeddingMetadataRepository,
    SemanticMemoryMetadataRepository,
)
from intelligence.semantic_intelligence.repositories.base_fact_repo import (  # noqa: E402
    SemanticFactRepository,
)
from shared.intelligence_projections.contracts import (  # noqa: E402
    ProjectionContext,
    ProjectionRequest,
    ProjectionSubject,
)

TENANT = "tenant-memory360"
ENTITY = "semantic-entity-1"
OBSERVED_AT = "2026-10-19T10:00:00+00:00"


def _request(*, kind: str = "semantic_entity", subject_id: str = ENTITY, **overrides: Any):
    values: dict[str, Any] = {
        "projectionId": "memory360",
        "tenantId": TENANT,
        "subject": ProjectionSubject(kind=kind, id=subject_id),
        "page": {"limit": 20},
    }
    values.update(overrides)
    return ProjectionRequest(**values)


def _context(*, tenant_id: str = TENANT) -> ProjectionContext:
    return ProjectionContext(
        projectionId="memory360",
        tenantId=tenant_id,
        registryState="in_flight",
        dependencyState=[],
        warnings=[],
    )


def _gold(**overrides: Any) -> dict[str, Any]:
    row = {
        "state_id": "gold-state-1",
        "tenant_id": TENANT,
        "entity_ref": ENTITY,
        "entity_type": "user",
        "subject_ref": ENTITY,
        "semantic_summary": "2 weighted observations for semantic-entity-1",
        "active_topics": ["governance"],
        "dominant_narratives": [],
        "stance_distribution": {"supportive": 0.7, "opposed": 0.3},
        "intent_distribution": {"unknown": 1.0},
        "semantic_delta": {
            "reducer_version": "weighted-reducer.v3",
            "half_life_days": 30,
            "contradiction": True,
        },
        "persistence": "medium_ttl",
        "volatility": 0,
        "observation_count": 2,
        "unique_source_count": 2,
        "confidence": 0.82,
        "freshness": "fresh",
        "window_start": "2026-10-18T10:00:00+00:00",
        "window_end": "2026-10-19T10:00:00+00:00",
        "computed_at": "2026-10-19T11:00:00+00:00",
        "evidence_refs": [
            {
                "evidence_id": "source-evidence-1",
                "source_type": "conversation_event",
                "source_ref": "source-event-1",
                "observed_at": OBSERVED_AT,
                "confidence": 0.9,
            }
        ],
    }
    row.update(overrides)
    return row


def _observation(observation_id: str, source_event_id: str, **overrides: Any) -> dict[str, Any]:
    row = {
        "observation_id": observation_id,
        "tenant_id": TENANT,
        "primary_subject_ref": ENTITY,
        "source_event_id": source_event_id,
        "source_type": "conversation",
        "occurred_at": OBSERVED_AT,
        "processed_at": "2026-10-19T10:01:00+00:00",
        "updated_at": "2026-10-19T10:01:00+00:00",
        "topics": ["governance"],
        "model_id": "deterministic-semantic-classifier",
        "model_version": "1.0.0",
        "status": "classified",
        "claims": ["must-not-leak"],
        "actor_ref": "private-actor-ref",
        "raw_content": "private source text",
    }
    row.update(overrides)
    return row


class FakeReader:
    def __init__(self, result: SemanticMemoryRead) -> None:
        self.result = result
        self.calls: list[tuple[str, str, int, int]] = []

    async def read(
        self,
        tenant_id: str,
        entity_ref: str,
        *,
        offset: int,
        limit: int,
    ) -> SemanticMemoryRead:
        self.calls.append((tenant_id, entity_ref, offset, limit))
        return self.result


class FakeFactRepository:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[dict[str, Any]] = []

    async def list_by_tenant(
        self,
        tenant_id: str,
        subject: str,
        *,
        limit: int,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        self.calls.append(
            {"tenant_id": tenant_id, "subject": subject, "limit": limit, "offset": offset}
        )
        return self.rows[offset : offset + limit]

    async def find_by_ids(
        self,
        tenant_id: str,
        record_ids: list[str] | tuple[str, ...],
        *,
        subject: str | None = None,
    ) -> list[dict[str, Any]]:
        wanted = set(record_ids)
        matches = []
        for row in self.rows:
            row_id = (
                row.get("observation_id")
                or row.get("memory_id")
                or row.get("card_id")
                or row.get("embedding_id")
                or row.get("id")
            )
            row_subject = row.get("primary_subject_ref") or row.get("subject_ref")
            if (
                row.get("tenant_id") == tenant_id
                and row_id in wanted
                and (subject is None or row_subject == subject)
            ):
                matches.append(
                    {
                        **row,
                        "record_id": row_id,
                        "subject_ref": row_subject,
                    }
                )
        return matches

    async def upsert(self, fact: dict[str, Any]) -> dict[str, Any]:
        self.rows.append(fact["data"])
        return fact


class FakePolicyRepository:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = {row["policy_decision_id"]: row for row in rows}
        self.calls: list[str] = []

    async def find_by_id(self, record_id: str) -> dict[str, Any] | None:
        self.calls.append(record_id)
        return self.rows.get(record_id)


def _memory_record(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "memory_id": "mem-record-0001",
        "tenant_id": TENANT,
        "subject_ref": ENTITY,
        "subject_type": "profile",
        "memory_kind": "preference",
        "summary": "Prefers low-noise weekly status summaries.",
        "confidence": 0.94,
        "source_observation_ids": ["semantic-observation-memory-1"],
        "policy_decision_ref": "cpd-memory-0001",
        "retention_class": "standard_90d",
        "status": "classified",
        "created_at": "2026-10-19T12:00:00+00:00",
    }
    row.update(overrides)
    return row


def _policy_decision(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "policy_decision_id": "cpd-memory-0001",
        "tenant_id": TENANT,
        "subject_ref": ENTITY,
        "resource_type": "semantic_memory",
        "resource_id": "mem-record-0001",
        "action": "generate_feature",
        "allowed": True,
        "created_at": "2026-10-19T11:59:00+00:00",
    }
    row.update(overrides)
    return row


def _sections(result: Any) -> dict[str, Any]:
    return {section.id: section for section in result.sections}


async def test_semantic_entity_slots_have_tenant_bound_evidence_and_exact_claim_attribution() -> (
    None
):
    read = SemanticMemoryRead(
        gold_state=_gold(),
        gold_state_state="available",
        observations=(
            _observation("semantic-observation-1", "source-event-1"),
            _observation("semantic-observation-2", "source-event-2"),
        ),
        observations_state="available",
        observations_complete=True,
    )
    reader = FakeReader(read)

    result = await Memory360Provider(reader=reader).project(_request(), _context())

    assert reader.calls == [(TENANT, ENTITY, 0, 20)]
    sections = _sections(result)
    assert set(sections) == {
        "semantic_summary",
        "memories",
        "cards",
        "topics",
        "embeddings_meta",
        "source_links",
        "decay",
        "conflicts",
        "policy_state",
        "evidence_trace",
    }
    assert sections["semantic_summary"].state == "available"
    assert sections["semantic_summary"].content["epistemicState"] == "derived"
    assert sections["semantic_summary"].content["evidenceRefs"]
    assert sections["topics"].state == "available"
    assert sections["topics"].content["topics"][0]["epistemicState"] == "inferred"
    assert sections["source_links"].state == "degraded"
    assert sections["source_links"].content["sourceRecordJoinState"] == "unknown"
    assert sections["source_links"].content["links"][0]["sourceEventId"] == "source-event-1"
    assert sections["decay"].state == "degraded"
    assert sections["decay"].content["reducerHalfLifeDays"] == 30
    assert sections["decay"].content["decayScore"] is None
    assert sections["conflicts"].state == "degraded"
    assert sections["conflicts"].content["contradictionSignal"] is True
    assert sections["conflicts"].content["conflicts"] == []
    for slot_id in ("memories", "cards", "embeddings_meta", "policy_state"):
        assert sections[slot_id].state == "unknown"
    assert sections["policy_state"].content["riskLensState"] == "unknown"

    claims_by_id = {claim.id: claim for claim in result.claims}
    assert {slot_id for claim in result.claims for slot_id in claim.domainSlotIds or []} == {
        "semantic_summary",
        "topics",
        "source_links",
        "evidence_trace",
    }
    source_claim = claims_by_id[f"memory360:{ENTITY}:source-link:semantic-observation-1"]
    assert source_claim.domainSlotIds == ["source_links", "evidence_trace"]
    assert source_claim.evidenceRefs[0].id == "semantic-observation-1"
    assert claims_by_id[f"memory360:{ENTITY}:semantic-summary"].domainSlotIds == [
        "semantic_summary"
    ]
    assert all(claim.evidenceRefs for claim in result.claims)

    serialized = json.dumps(result.model_dump(mode="json"))
    for private_value in ("must-not-leak", "private-actor-ref", "private source text"):
        assert private_value not in serialized


async def test_exact_reader_tenant_filters_rows_and_uses_exact_subject_queries() -> None:
    gold_repo = FakeFactRepository([_gold(), _gold(tenant_id="tenant-other")])
    observation_repo = FakeFactRepository(
        [
            _observation("semantic-observation-1", "source-event-1"),
            _observation(
                "semantic-observation-cross-tenant", "private-event", tenant_id="tenant-other"
            ),
        ]
    )

    read = await RepositorySemanticMemoryReader(
        gold_repository=gold_repo,
        observation_repository=observation_repo,
    ).read(TENANT, ENTITY, offset=0, limit=20)

    assert gold_repo.calls == [{"tenant_id": TENANT, "subject": ENTITY, "limit": 2, "offset": 0}]
    assert observation_repo.calls == [
        {"tenant_id": TENANT, "subject": ENTITY, "limit": 21, "offset": 0}
    ]
    assert read.gold_state is None
    assert read.gold_state_state == "unknown"
    assert [row["observation_id"] for row in read.observations] == ["semantic-observation-1"]
    assert read.observations_state == "degraded"
    assert read.observations_complete is False
    assert "semantic_entity_gold_scope_mismatch" in read.warnings
    assert "semantic_observation_scope_or_identity_mismatch" in read.warnings


async def test_unjoined_consent_and_vector_hints_do_not_claim_memory_authority() -> None:
    """A consent snapshot or vector pointer is not a memory/card/embedding join.

    Silver semantic observations carry source context, and the shared semantic
    envelope can carry a vector pointer. Neither record establishes a typed
    durable context card or embedding report. The card registry can return an
    exact empty result, while embedding metadata remains unknown because no
    producer inventory is connected.
    """
    gold_repo = FakeFactRepository(
        [
            _gold(
                semantic_context={"vector_ref": "vector-entity-1"},
                card_id="card-unjoined-1",
            )
        ]
    )
    observation_repo = FakeFactRepository(
        [
            _observation(
                "semantic-observation-1",
                "source-event-1",
                consent_snapshot_id="consent-snapshot-unjoined-1",
                purposes=["analytics"],
                semantic_context={"vector_ref": "vector-observation-1"},
            )
        ]
    )
    provider = Memory360Provider(
        reader=RepositorySemanticMemoryReader(
            gold_repository=gold_repo,
            observation_repository=observation_repo,
        )
    )

    result = await provider.project(_request(), _context())

    sections = _sections(result)
    assert sections["memories"].state == "empty"
    assert sections["memories"].content["evidenceRefs"] == []
    assert sections["cards"].state == "empty"
    assert sections["cards"].content["coverage"] == "complete"
    assert sections["cards"].content["evidenceRefs"] == []
    assert sections["embeddings_meta"].state == "unknown"
    assert sections["embeddings_meta"].content["coverage"] == "unknown"
    assert sections["embeddings_meta"].content["evidenceRefs"] == []
    policy_state = sections["policy_state"]
    assert policy_state.state == "degraded"
    assert policy_state.canonicalAuthorityRefs == [
        "semantic_memory_records",
        "consent_policy_decisions",
        "evidence",
    ]
    assert policy_state.content["currentConsentState"] == "unknown"
    assert policy_state.content["currentPolicyState"] == "not_evaluated"
    assert policy_state.content["historicalDecisionCoverage"] == "complete"
    assert policy_state.content["historicalDecisionCount"] == 0
    assert policy_state.content["evidenceRefs"] == []
    assert sections["memories"].content["reason"] == (
        "no_canonical_semantic_memory_records_for_exact_subject"
    )
    assert sections["cards"].content["reason"] == (
        "no_registered_context_cards_for_exact_subject"
    )
    assert sections["embeddings_meta"].content["reason"] == (
        "embedding_provider_inventory_or_vector_store_authority_unavailable"
    )
    assert policy_state.content["reason"] == (
        "no_historical_memory_policy_decisions_current_policy_not_evaluated"
    )
    serialized = json.dumps(result.model_dump(mode="json"))
    for unjoined_hint in (
        "consent-snapshot-unjoined-1",
        "vector-entity-1",
        "vector-observation-1",
        "card-unjoined-1",
    ):
        assert unjoined_hint not in serialized


async def test_exact_memory_record_path_projects_only_policy_and_evidence_joined_records() -> None:
    source = _observation("semantic-observation-memory-1", "source-event-memory-1")
    denied_memory = _memory_record(
        memory_id="mem-record-denied-0001",
        policy_decision_ref="cpd-memory-denied-1",
        summary="must-not-leak-denied-memory",
    )
    foreign_memory = _memory_record(
        memory_id="mem-record-foreign-0001",
        tenant_id="tenant-other",
        policy_decision_ref="cpd-memory-foreign-1",
        summary="must-not-leak-foreign-memory",
    )
    record_repo = FakeFactRepository([
        _memory_record(required_consent_purposes_at_write=["analytics", "personalization"]),
        denied_memory,
        foreign_memory,
    ])
    policy_repo = FakePolicyRepository(
        [
            _policy_decision(required_purposes=["personalization", "analytics"]),
            _policy_decision(
                policy_decision_id="cpd-memory-denied-1",
                resource_id="mem-record-denied-0001",
                allowed=False,
            ),
            _policy_decision(
                policy_decision_id="cpd-memory-foreign-1",
                resource_id="mem-record-foreign-0001",
                tenant_id="tenant-other",
            ),
        ]
    )
    observations = FakeFactRepository([source])
    memory_repository = SemanticMemoryRecordRepository(
        record_repository=record_repo,
        observation_repository=observations,
        policy_repository=policy_repo,
    )
    reader = RepositorySemanticMemoryReader(
        gold_repository=FakeFactRepository([]),
        observation_repository=observations,
        memory_repository=memory_repository,
    )

    result = await Memory360Provider(reader=reader).project(_request(), _context())

    sections = _sections(result)
    memories = sections["memories"]
    assert memories.state == "degraded"
    assert memories.content["coverage"] == "partial"
    assert [item["memoryId"] for item in memories.content["items"]] == ["mem-record-0001"]
    item = memories.content["items"][0]
    assert item["subjectRef"] == ENTITY
    assert item["subjectType"] == "profile"
    assert item["policyDecisionRef"] == "cpd-memory-0001"
    assert item["policyDecisionOutcomeAtWrite"] == "historical_allow"
    assert item["requiredConsentPurposesAtWrite"] == ["analytics", "personalization"]
    assert memories.content["freshness"] == {
        "state": "unknown",
        "latestMemoryCreatedAt": "2026-10-19T12:00:00+00:00",
        "evaluation": "memory_staleness_threshold_not_configured",
    }
    assert {ref["id"] for ref in item["evidenceRefs"]} == {
        "mem-record-0001",
        "semantic-observation-memory-1",
        "cpd-memory-0001",
    }
    assert all(ref["observedAt"] for ref in item["evidenceRefs"])
    policy_state = sections["policy_state"]
    assert policy_state.state == "degraded"
    assert policy_state.content["coverage"] == "partial"
    assert policy_state.content["reason"] == (
        "historical_write_policy_decision_coverage_partial_current_policy_not_evaluated"
    )
    assert policy_state.content["evaluation"] == (
        "historical_write_decisions_only_current_policy_not_evaluated"
    )
    assert policy_state.content["currentConsentState"] == "unknown"
    assert policy_state.content["currentPolicyState"] == "not_evaluated"
    assert policy_state.content["historicalDecisionCoverage"] == "partial"
    assert policy_state.content["historicalDecisionCount"] == 1
    assert policy_state.content["historicalDecisions"] == [
        {
            "memoryId": "mem-record-0001",
            "policyDecisionId": "cpd-memory-0001",
            "outcomeAtWrite": "allowed",
            "requiredConsentPurposesAtWrite": ["analytics", "personalization"],
            "decidedAt": "2026-10-19T11:59:00+00:00",
            "evidenceRefs": [
                {
                    "id": "cpd-memory-0001",
                    "type": "annotation",
                    "source": "governance.consent_policy_decisions",
                    "observedAt": "2026-10-19T11:59:00+00:00",
                    "confidence": None,
                    "uri": (
                        "store://consent_policy_decisions/"
                        "tenant-memory360:cpd-memory-0001"
                    ),
                }
            ],
        }
    ]
    assert policy_state.content["evidenceRefs"] == policy_state.content[
        "historicalDecisions"
    ][0]["evidenceRefs"]
    assert sections["cards"].state == "empty"
    assert sections["embeddings_meta"].state == "unknown"
    assert policy_repo.calls == [
        "cpd-memory-0001",
        "cpd-memory-denied-1",
    ]
    serialized = json.dumps(result.model_dump(mode="json"))
    assert "must-not-leak-denied-memory" not in serialized
    assert "must-not-leak-foreign-memory" not in serialized
    memory_claim = next(claim for claim in result.claims if claim.kind == "semantic_memory_record")
    assert memory_claim.domainSlotIds == ["memories"]
    assert {ref.id for ref in memory_claim.evidenceRefs} == {
        "mem-record-0001",
        "semantic-observation-memory-1",
        "cpd-memory-0001",
    }


async def test_memory360_policy_slot_rejects_cross_tenant_memory_evidence() -> None:
    foreign_record = SemanticMemoryRecord.model_validate(
        _memory_record(tenant_id="tenant-other")
    )
    foreign_decision = EvidenceRef(
        id="cpd-memory-0001",
        type="annotation",
        source="governance.consent_policy_decisions",
        observedAt="2026-10-19T11:59:00+00:00",
        uri=(
            "store://consent_policy_decisions/"
            "tenant-other:cpd-memory-0001"
        ),
    )
    read = SemanticMemoryRead(
        memories=(
            ResolvedMemoryRecord(
                record=foreign_record,
                evidence_refs=(foreign_decision,),
                policy_outcome="historical_allow",
            ),
        ),
        memories_state="available",
        memories_complete=True,
    )

    result = await Memory360Provider(reader=FakeReader(read)).project(_request(), _context())

    sections = _sections(result)
    assert sections["memories"].state == "degraded"
    assert sections["memories"].content["items"] == []
    assert sections["policy_state"].content["historicalDecisions"] == []
    assert sections["policy_state"].content["evidenceRefs"] == []
    assert sections["policy_state"].content["historicalDecisionCoverage"] == "partial"
    assert "tenant-other" not in json.dumps(sections["policy_state"].content)


async def test_memory_record_creation_refuses_non_exact_or_denied_policy_decision() -> None:
    record_repo = FakeFactRepository([])
    repository = SemanticMemoryRecordRepository(
        record_repository=record_repo,
        observation_repository=FakeFactRepository(
            [_observation("semantic-observation-memory-1", "source-event-memory-1")]
        ),
        policy_repository=FakePolicyRepository(
            [
                _policy_decision(
                    resource_id="different-memory-id",
                )
            ]
        ),
    )
    record = SemanticMemoryRecord.model_validate(_memory_record())

    with pytest.raises(ValueError, match="memory_policy_decision_not_exact_allowed_authority"):
        await repository.create(record)

    assert record_repo.rows == []


async def test_memory_record_stamps_only_verified_required_purposes_and_checks_both_reads() -> None:
    record_repo = FakeFactRepository([])
    policy_repo = FakePolicyRepository(
        [_policy_decision(required_purposes=["personalization", "analytics"])]
    )
    repository = SemanticMemoryRecordRepository(
        record_repository=record_repo,
        observation_repository=FakeFactRepository(
            [_observation("semantic-observation-memory-1", "source-event-memory-1")]
        ),
        policy_repository=policy_repo,
    )
    input_record = SemanticMemoryRecord.model_validate(_memory_record())

    created = await repository.create(input_record)
    assert input_record.required_consent_purposes_at_write is None
    assert created.required_consent_purposes_at_write == ["analytics", "personalization"]
    assert record_repo.rows[0]["required_consent_purposes_at_write"] == [
        "analytics", "personalization"
    ]
    assert (await repository.create(input_record)) == created  # idempotent enrichment
    by_subject = await repository.read_for_subject(TENANT, ENTITY, offset=0, limit=10)
    by_id = await repository.read_for_ids(TENANT, ENTITY, ["mem-record-0001"])
    assert by_subject.state == by_id.state == "available"
    assert by_subject.records[0].record.required_consent_purposes_at_write == [
        "analytics", "personalization"
    ]
    assert by_id.records[0].record.required_consent_purposes_at_write == [
        "analytics", "personalization"
    ]

    policy_repo.rows["cpd-memory-0001"]["required_purposes"] = ["analytics"]
    by_subject = await repository.read_for_subject(TENANT, ENTITY, offset=0, limit=10)
    by_id = await repository.read_for_ids(TENANT, ENTITY, ["mem-record-0001"])
    for page in (by_subject, by_id):
        assert page.records == ()
        assert page.state == "degraded"
        assert "semantic_memory_policy_purpose_stamp_mismatch" in page.warnings


async def test_legacy_memory_without_purpose_stamp_preserves_explicit_unknown() -> None:
    policy_repo = FakePolicyRepository([_policy_decision(required_purposes=["analytics"])])
    repository = SemanticMemoryRecordRepository(
        record_repository=FakeFactRepository([_memory_record()]),
        observation_repository=FakeFactRepository(
            [_observation("semantic-observation-memory-1", "source-event-memory-1")]
        ),
        policy_repository=policy_repo,
    )

    by_subject = await repository.read_for_subject(TENANT, ENTITY, offset=0, limit=10)
    by_id = await repository.read_for_ids(TENANT, ENTITY, ["mem-record-0001"])
    assert by_subject.state == by_id.state == "available"
    assert by_subject.records[0].record.required_consent_purposes_at_write is None
    assert by_id.records[0].record.required_consent_purposes_at_write is None


async def test_memory_create_rejects_unverified_caller_purpose_stamp() -> None:
    record_repo = FakeFactRepository([])
    repository = SemanticMemoryRecordRepository(
        record_repository=record_repo,
        observation_repository=FakeFactRepository(
            [_observation("semantic-observation-memory-1", "source-event-memory-1")]
        ),
        policy_repository=FakePolicyRepository(
            [_policy_decision(required_purposes=["analytics"])]
        ),
    )
    record = SemanticMemoryRecord.model_validate(
        _memory_record(required_consent_purposes_at_write=["personalization"])
    )

    with pytest.raises(ValueError, match="memory_policy_required_purposes_not_exact_authority"):
        await repository.create(record)
    assert record_repo.rows == []


async def test_memory_record_creation_refuses_unjoined_source_observation() -> None:
    record_repo = FakeFactRepository([])
    repository = SemanticMemoryRecordRepository(
        record_repository=record_repo,
        observation_repository=FakeFactRepository(
            [
                _observation(
                    "semantic-observation-memory-1",
                    "source-event-memory-1",
                    tenant_id="tenant-other",
                )
            ]
        ),
        policy_repository=FakePolicyRepository([_policy_decision()]),
    )

    with pytest.raises(
        ValueError, match="memory_source_observations_not_exact_active_or_timestamped"
    ):
        await repository.create(SemanticMemoryRecord.model_validate(_memory_record()))

    assert record_repo.rows == []


async def test_context_card_and_embedding_metadata_have_exact_writer_reader_and_projection_paths() -> None:
    memory_id = "mem-context-card-source-0001"
    observation_id = "semantic-observation-card-0001"
    card_id = "context-card-0001"
    embedding_id = "embedding-meta-0001"
    source_observations = FakeFactRepository(
        [_observation(observation_id, "source-event-card-0001")]
    )
    policy_repo = FakePolicyRepository(
        [
            _policy_decision(
                policy_decision_id="cpd-memory-card-source-0001",
                resource_id=memory_id,
            ),
            _policy_decision(
                policy_decision_id="cpd-context-card-0001",
                resource_type="semantic_context_card",
                resource_id=card_id,
            ),
            _policy_decision(
                policy_decision_id="cpd-embedding-meta-0001",
                resource_type="semantic_embedding",
                resource_id=embedding_id,
            ),
        ]
    )
    memories = SemanticMemoryRecordRepository(
        record_repository=FakeFactRepository(
            [_memory_record(
                memory_id=memory_id,
                source_observation_ids=[observation_id],
                policy_decision_ref="cpd-memory-card-source-0001",
            )]
        ),
        observation_repository=source_observations,
        policy_repository=policy_repo,
    )
    cards = SemanticContextCardRepository(
        record_repository=FakeFactRepository([]),
        memory_repository=memories,
        policy_repository=policy_repo,
    )
    card = SemanticContextCard(
        card_id=card_id,
        tenant_id=TENANT,
        subject_ref=ENTITY,
        card_kind="preference",
        title="Communication preference",
        summary="Prefers concise updates.",
        source_memory_ids=[memory_id],
        policy_decision_ref="cpd-context-card-0001",
        actor_ref="authenticated-user-1",
        created_at="2026-10-20T11:00:00+00:00",
    )
    assert await cards.create(card) == card
    card_page = await cards.read_for_subject(TENANT, ENTITY, offset=0, limit=20)
    assert card_page.cards_state == "available"
    assert card_page.cards_complete is True
    assert card_page.cards[0].card == card
    assert {ref.id for ref in card_page.cards[0].evidence_refs} == {
        card_id,
        memory_id,
        observation_id,
        "cpd-memory-card-source-0001",
        "cpd-context-card-0001",
    }

    embeddings = SemanticEmbeddingMetadataRepository(
        record_repository=FakeFactRepository([]),
        card_repository=cards,
        policy_repository=policy_repo,
    )
    metadata = SemanticEmbeddingMetadata(
        embedding_id=embedding_id,
        tenant_id=TENANT,
        subject_ref=ENTITY,
        card_ids=[card_id],
        provider_id="reported-provider",
        model_id="reported-model",
        model_version="v1",
        dimensions=384,
        vector_store="reported-vector-store",
        namespace="tenant-memory360",
        vector_ref="opaque-vector-ref-1",
        producer_receipt_id="producer-receipt-1",
        policy_decision_ref="cpd-embedding-meta-0001",
        actor_ref="authenticated-user-1",
        observed_at="2026-10-20T11:01:00+00:00",
        created_at="2026-10-20T11:02:00+00:00",
    )
    assert await embeddings.create(metadata) == metadata
    embedding_page = await embeddings.read_for_subject(TENANT, ENTITY, offset=0, limit=20)
    assert embedding_page.embeddings_state == "degraded"
    assert len(embedding_page.embeddings) == 1
    assert embedding_page.embeddings[0].artifact_verification_state == "unknown"
    assert {ref.id for ref in embedding_page.embeddings[0].evidence_refs} == {
        embedding_id,
        card_id,
        memory_id,
        observation_id,
        "cpd-memory-card-source-0001",
        "cpd-context-card-0001",
        "cpd-embedding-meta-0001",
    }

    metadata_repository = SemanticMemoryMetadataRepository(
        card_repository=cards,
        embedding_repository=embeddings,
    )
    reader = RepositorySemanticMemoryReader(
        gold_repository=FakeFactRepository([]),
        observation_repository=source_observations,
        memory_repository=memories,
        metadata_repository=metadata_repository,
    )
    projected = await Memory360Provider(reader=reader).project(_request(), _context())
    sections = _sections(projected)
    assert sections["cards"].state == "available"
    assert sections["cards"].content["items"][0]["sourceMemoryIds"] == [memory_id]
    assert sections["embeddings_meta"].state == "degraded"
    item = sections["embeddings_meta"].content["items"][0]
    assert item["artifactVerificationState"] == "unknown"
    assert item["dimensions"] == 384
    assert sections["evidence_trace"].content["evidenceRefs"]


async def test_context_card_and_embedding_writers_fail_closed_on_wrong_tenant_source() -> None:
    card_repo = FakeFactRepository([])
    memory_repository = SemanticMemoryRecordRepository(
        record_repository=FakeFactRepository(
            [_memory_record(tenant_id="tenant-other")]
        ),
        observation_repository=FakeFactRepository(
            [_observation("semantic-observation-memory-1", "source-event-memory-1")]
        ),
        policy_repository=FakePolicyRepository([_policy_decision()]),
    )
    cards = SemanticContextCardRepository(
        record_repository=card_repo,
        memory_repository=memory_repository,
        policy_repository=FakePolicyRepository(
            [
                _policy_decision(
                    policy_decision_id="cpd-context-card-wrong-tenant",
                    resource_type="semantic_context_card",
                    resource_id="context-card-wrong-tenant",
                )
            ]
        ),
    )
    card = SemanticContextCard(
        card_id="context-card-wrong-tenant",
        tenant_id=TENANT,
        subject_ref=ENTITY,
        card_kind="summary",
        title="Blocked card",
        summary="Must not write from another tenant's memory.",
        source_memory_ids=["mem-record-0001"],
        policy_decision_ref="cpd-context-card-wrong-tenant",
        actor_ref="authenticated-user-1",
        created_at="2026-10-20T11:00:00+00:00",
    )

    with pytest.raises(ValueError, match="context_card_source_memories_not_exact"):
        await cards.create(card)
    assert card_repo.rows == []


async def test_memory_record_creation_rejects_lifecycle_tombstone_status() -> None:
    repository = SemanticMemoryRecordRepository(
        record_repository=FakeFactRepository([]),
        observation_repository=FakeFactRepository([]),
        policy_repository=FakePolicyRepository([]),
    )

    with pytest.raises(ValueError, match="new_memory_record_must_start_active"):
        await repository.create(
            SemanticMemoryRecord.model_validate(_memory_record(status="expired"))
        )


async def test_semantic_fact_authority_persists_and_reads_memory_with_exact_provenance() -> None:
    tenant_id = "tenant-memory360-fact-repository"
    subject_ref = "profile-memory360-fact-repository"
    memory_id = "mem-fact-repository-0001"
    source_id = "sem-memory-fact-source-0001"
    policy_id = "cpd-memory-fact-repository-0001"
    observation = _observation(
        source_id,
        "source-event-memory-fact-1",
        tenant_id=tenant_id,
        primary_subject_ref=subject_ref,
    )
    observation_repo = SemanticFactRepository("silver_semantic_observations")
    await observation_repo.upsert(
        {
            "id": source_id,
            "tenant_id": tenant_id,
            "subject_ref": subject_ref,
            "source_event_id": observation["source_event_id"],
            "occurred_at": OBSERVED_AT,
            "data": observation,
        }
    )
    record_repo = SemanticFactRepository("semantic_memory_records")
    policy_repo = FakePolicyRepository(
        [
            {
                "policy_decision_id": policy_id,
                "tenant_id": tenant_id,
                "subject_ref": subject_ref,
                "resource_type": "semantic_memory",
                "resource_id": memory_id,
                "action": "generate_feature",
                "allowed": True,
                "created_at": "2026-10-19T10:05:00+00:00",
            }
        ]
    )
    repository = SemanticMemoryRecordRepository(
        record_repository=record_repo,
        observation_repository=observation_repo,
        policy_repository=policy_repo,
    )
    record = SemanticMemoryRecord(
        memory_id=memory_id,
        tenant_id=tenant_id,
        subject_ref=subject_ref,
        subject_type="profile",
        memory_kind="preference",
        summary="Prefers concise release notes.",
        confidence=0.9,
        source_observation_ids=[source_id],
        policy_decision_ref=policy_id,
        created_at="2026-10-19T10:06:00+00:00",
    )

    created = await repository.create(record)
    conflicting = record.model_copy(
        update={"summary": "Changed content must append under a new memory ID."}
    )
    with pytest.raises(ValueError, match="memory_id_is_append_only"):
        await repository.create(conflicting)
    page = await repository.read_for_subject(
        tenant_id,
        subject_ref,
        offset=0,
        limit=20,
    )

    assert created == record
    assert page.state == "available"
    assert len(page.records) == 1
    assert page.records[0].record.memory_id == memory_id
    assert page.records[0].record.summary == "Prefers concise release notes."
    assert {ref.id for ref in page.records[0].evidence_refs} == {
        memory_id,
        source_id,
        policy_id,
    }
    assert all(ref.observedAt for ref in page.records[0].evidence_refs)
    assert policy_repo.calls == [policy_id, policy_id, policy_id]

    provider = Memory360Provider(
        reader=RepositorySemanticMemoryReader(
            gold_repository=SemanticFactRepository("gold_entity_semantic_state", mode="gold"),
            observation_repository=observation_repo,
            memory_repository=repository,
        )
    )
    projected = await provider.project(
        _request(tenantId=tenant_id, subject_id=subject_ref),
        _context(tenant_id=tenant_id),
    )
    memory_slot = _sections(projected)["memories"]
    assert memory_slot.state == "available"
    assert memory_slot.content["freshness"]["state"] == "unknown"
    assert memory_slot.content["freshness"]["latestMemoryCreatedAt"] == (
        "2026-10-19T10:06:00+00:00"
    )
    assert {ref["id"] for ref in memory_slot.content["evidenceRefs"]} == {
        memory_id,
        source_id,
        policy_id,
    }


async def test_non_active_observation_is_omitted_from_source_links_and_blocks_derived_state() -> (
    None
):
    read = SemanticMemoryRead(
        gold_state=_gold(),
        gold_state_state="available",
        observations=(
            _observation("semantic-observation-1", "source-event-1"),
            _observation(
                "semantic-observation-restricted",
                "restricted-event",
                status="consent_restricted",
            ),
        ),
        observations_state="available",
        observations_complete=True,
    )

    result = await Memory360Provider(reader=FakeReader(read)).project(_request(), _context())

    sections = _sections(result)
    assert sections["semantic_summary"].state == "unknown"
    assert sections["topics"].state == "available"
    assert sections["source_links"].state == "degraded"
    assert [link["observationId"] for link in sections["source_links"].content["links"]] == [
        "semantic-observation-1"
    ]
    assert sections["policy_state"].content["nonActiveRowsOmitted"] == 1
    assert all(
        evidence_ref.id != "semantic-observation-restricted"
        for claim in result.claims
        for evidence_ref in claim.evidenceRefs
    )


@pytest.mark.parametrize(
    "kind,subject_id", [("memory", "memory-1"), ("card", "card-1"), ("topic", "topic-1")]
)
async def test_unbacked_memory_card_and_topic_ids_return_all_ten_unknown_slots_without_reads(
    kind: str,
    subject_id: str,
) -> None:
    reader = FakeReader(SemanticMemoryRead())

    result = await Memory360Provider(reader=reader).project(
        _request(kind=kind, subject_id=subject_id),
        _context(),
    )

    sections = _sections(result)
    assert len(sections) == 10
    assert all(section.state == "unknown" for section in sections.values())
    assert reader.calls == []
    assert result.claims == []
    assert "memory_subject_kind_has_no_typed_canonical_reader" in result.degradedReasons


async def test_semantic_entity_historical_request_stays_unknown() -> None:
    reader = FakeReader(
        SemanticMemoryRead(
            gold_state=_gold(),
            gold_state_state="available",
            observations=(_observation("semantic-observation-1", "source-event-1"),),
            observations_state="available",
            observations_complete=True,
        )
    )

    result = await Memory360Provider(reader=reader).project(
        _request(asOf="2026-10-18T00:00:00+00:00"),
        _context(),
    )

    sections = _sections(result)
    assert sections["semantic_summary"].state == "unknown"
    assert sections["topics"].state == "unknown"
    assert result.claims == []
    assert "semantic_gold_historical_or_window_read_not_supported" in result.degradedReasons
