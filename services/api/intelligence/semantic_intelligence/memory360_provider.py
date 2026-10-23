"""Memory360 projection over canonical semantic memory, Silver, and Gold.

The semantic intelligence plane persists classified observations, explicit
typed memory records, and reduced entity state. Context cards, embedding
metadata, and current policy state still lack exact canonical read authorities;
those slots remain explicitly unknown.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional, Protocol
from urllib.parse import quote

from graph.operational_intelligence.models import EvidenceRef, PageInfo
from shared.contracts_models.epistemic import EpistemicStatus
from shared.intelligence_projections.contracts import (
    ClaimEnvelope,
    ProjectionContext,
    ProjectionRequest,
    ProjectionResult,
    ProjectionSection,
)
from shared.intelligence_projections.generated_registry import (
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
)
from shared.intelligence_projections.provider import IntelligenceProjectionProvider
from shared.intelligence_projections.registry import ProviderRegistry

from .memory_records import (
    MemoryRecordPage,
    ResolvedMemoryRecord,
    SemanticMemoryRecordRepository,
)

_MEMORY_REQUIRED_SLOTS = (
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
)
_MEMORY_SLOT_TITLES = {
    "semantic_summary": "Semantic summary",
    "memories": "Memory records",
    "cards": "Knowledge cards",
    "topics": "Semantic topics",
    "embeddings_meta": "Embedding metadata",
    "source_links": "Source links",
    "decay": "Memory decay",
    "conflicts": "Semantic conflicts",
    "policy_state": "Memory policy state",
    "evidence_trace": "Memory evidence trace",
}
_GOLD_ENTITY_TABLE = "gold_entity_semantic_state"
_SILVER_OBSERVATION_TABLE = "silver_semantic_observations"
_GOLD_SOURCE = f"semantic_intelligence.{_GOLD_ENTITY_TABLE}"
_SILVER_SOURCE = f"semantic_intelligence.{_SILVER_OBSERVATION_TABLE}"
_ACTIVE_OBSERVATION_STATUSES = frozenset({"classified", "partial"})
_MAX_PAGE_SIZE = 200
_DEFAULT_PAGE_SIZE = 100
_PAGE_CURSOR_PREFIX = "semantic-offset:"


@dataclass(frozen=True)
class SemanticMemoryRead:
    """Tenant-bound exact entity state and one bounded observation page."""

    gold_state: Optional[dict[str, Any]] = None
    gold_state_state: str = "unknown"
    observations: tuple[dict[str, Any], ...] = ()
    observations_state: str = "unknown"
    observations_complete: bool = False
    observations_truncated: bool = False
    observations_next_offset: Optional[int] = None
    memories: tuple[ResolvedMemoryRecord, ...] = ()
    memories_state: str = "unknown"
    memories_complete: bool = False
    memories_truncated: bool = False
    memories_next_offset: Optional[int] = None
    warnings: tuple[str, ...] = ()


class SemanticMemoryReader(Protocol):
    async def read(
        self,
        tenant_id: str,
        entity_ref: str,
        *,
        offset: int,
        limit: int,
    ) -> SemanticMemoryRead: ...


class RepositorySemanticMemoryReader:
    """Exact tenant-filtered reader over canonical semantic Gold and Silver."""

    def __init__(
        self,
        *,
        gold_repository: Any = None,
        observation_repository: Any = None,
        memory_repository: Any = None,
    ) -> None:
        self._gold_repository = gold_repository
        self._observation_repository = observation_repository
        self._memory_repository = memory_repository

    def _gold_repo(self) -> Any:
        if self._gold_repository is None:
            from intelligence.semantic_intelligence.repositories.base_fact_repo import (
                SemanticFactRepository,
            )

            self._gold_repository = SemanticFactRepository(_GOLD_ENTITY_TABLE, mode="gold")
        return self._gold_repository

    def _observation_repo(self) -> Any:
        if self._observation_repository is None:
            from intelligence.semantic_intelligence.repositories.base_fact_repo import (
                SemanticFactRepository,
            )

            self._observation_repository = SemanticFactRepository(_SILVER_OBSERVATION_TABLE)
        return self._observation_repository

    def _memory_repo(self) -> Any:
        if self._memory_repository is None:
            self._memory_repository = SemanticMemoryRecordRepository()
        return self._memory_repository

    async def read(
        self,
        tenant_id: str,
        entity_ref: str,
        *,
        offset: int,
        limit: int,
    ) -> SemanticMemoryRead:
        warnings: list[str] = []
        gold_state: Optional[dict[str, Any]] = None
        gold_state_state = "unknown"
        try:
            raw_gold_rows = await self._gold_repo().list_by_tenant(tenant_id, entity_ref, limit=2)
        except Exception:  # noqa: BLE001 - missing authority stays unknown
            raw_gold_rows = None
            warnings.append("semantic_entity_gold_read_unavailable")

        if raw_gold_rows is not None:
            exact_gold_rows: list[dict[str, Any]] = []
            scope_mismatch = False
            for raw in raw_gold_rows:
                row = _as_mapping(raw)
                if row is None:
                    scope_mismatch = True
                    continue
                if row.get("tenant_id") != tenant_id or row.get("entity_ref") != entity_ref:
                    scope_mismatch = True
                    continue
                exact_gold_rows.append(row)
            if scope_mismatch:
                warnings.append("semantic_entity_gold_scope_mismatch")
            if len(exact_gold_rows) == 1 and not scope_mismatch:
                gold_state = exact_gold_rows[0]
                gold_state_state = "available"
            elif len(exact_gold_rows) > 1:
                warnings.append("semantic_entity_gold_duplicate_rows")
            elif not scope_mismatch:
                gold_state_state = "empty"

        observations_state = "unknown"
        observations: list[dict[str, Any]] = []
        truncated = False
        observations_complete = False
        next_offset: Optional[int] = None
        try:
            raw_observations = await self._observation_repo().list_by_tenant(
                tenant_id,
                entity_ref,
                limit=limit + 1,
                offset=offset,
            )
        except Exception:  # noqa: BLE001 - observation links can degrade independently
            raw_observations = None
            warnings.append("semantic_observation_read_unavailable")

        if raw_observations is not None:
            scope_mismatch = False
            for raw in raw_observations:
                row = _as_mapping(raw)
                if row is None:
                    scope_mismatch = True
                    continue
                if (
                    row.get("tenant_id") != tenant_id
                    or row.get("primary_subject_ref") != entity_ref
                    or not _text(row.get("observation_id"))
                    or not _text(row.get("source_event_id"))
                ):
                    scope_mismatch = True
                    continue
                observations.append(row)
            if scope_mismatch:
                warnings.append("semantic_observation_scope_or_identity_mismatch")
            truncated = len(observations) > limit
            if truncated:
                observations = observations[:limit]
                next_offset = offset + limit
                warnings.append("semantic_observation_page_truncated")
            observations_state = (
                "degraded"
                if scope_mismatch or truncated
                else "available"
                if observations
                else "empty"
            )
            observations_complete = not scope_mismatch and not truncated and offset == 0

        try:
            memory_page = await self._memory_repo().read_for_subject(
                tenant_id,
                entity_ref,
                offset=offset,
                limit=limit,
            )
        except Exception:  # noqa: BLE001 - memory records degrade independently
            memory_page = MemoryRecordPage(
                state="unknown",
                warnings=("semantic_memory_record_reader_unavailable",),
            )
        warnings.extend(memory_page.warnings)

        return SemanticMemoryRead(
            gold_state=gold_state,
            gold_state_state=gold_state_state,
            observations=tuple(observations),
            observations_state=observations_state,
            observations_complete=observations_complete,
            observations_truncated=truncated,
            observations_next_offset=next_offset,
            memories=memory_page.records,
            memories_state=memory_page.state,
            memories_complete=memory_page.complete,
            memories_truncated=memory_page.truncated,
            memories_next_offset=memory_page.next_offset,
            warnings=tuple(warnings),
        )


class Memory360Provider:
    """Read-only Memory360 projection for semantic memory and card context."""

    projection_id = "memory360"
    contract_version = INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION

    def __init__(self, reader: Optional[SemanticMemoryReader] = None) -> None:
        self._reader = reader

    def _load_reader(self) -> SemanticMemoryReader:
        return self._reader or RepositorySemanticMemoryReader()

    async def project(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
    ) -> ProjectionResult:
        warnings: list[str] = []
        generated_at = datetime.now(timezone.utc).isoformat()
        entity_subject = request.subject.kind in {"semantic_entity", "entity"}
        temporal_request_unsupported = bool(
            request.asOf
            or request.timeRange is not None
            or request.temporalMode in {"as_of", "compare", "relative"}
        )
        if temporal_request_unsupported:
            warnings.append("semantic_gold_historical_or_window_read_not_supported")
            read = SemanticMemoryRead(warnings=tuple(warnings))
        elif entity_subject:
            offset, cursor_error = _cursor_offset(
                request.page.cursor if request.page is not None else None
            )
            if cursor_error:
                warnings.append(cursor_error)
            requested_limit = request.page.limit if request.page is not None else _DEFAULT_PAGE_SIZE
            limit = min(requested_limit, _MAX_PAGE_SIZE)
            if requested_limit > _MAX_PAGE_SIZE:
                warnings.append("semantic_observation_page_size_capped")
            try:
                read = await self._load_reader().read(
                    request.tenantId,
                    request.subject.id,
                    offset=offset,
                    limit=limit,
                )
            except Exception:  # noqa: BLE001 - fail-isolated projection
                read = SemanticMemoryRead(
                    warnings=("semantic_memory_reader_unavailable",),
                )
            warnings.extend(read.warnings)
            if cursor_error:
                read = SemanticMemoryRead(
                    gold_state=read.gold_state,
                    gold_state_state=read.gold_state_state,
                    observations_state="unknown",
                    observations_complete=False,
                    memories_state="unknown",
                    memories_complete=False,
                    warnings=read.warnings,
                )
        else:
            warnings.append("memory_subject_kind_has_no_typed_canonical_reader")
            read = SemanticMemoryRead(warnings=tuple(warnings))

        sections, claims = _render_memory_slots(
            request=request,
            read=read,
            unsupported_subject=not entity_subject,
            temporal_request_unsupported=temporal_request_unsupported,
        )
        if request.includeSections is not None:
            wanted = set(request.includeSections)
            sections = [section for section in sections if section.id in wanted]
            claims = [
                claim
                for claim in claims
                if claim.domainSlotIds and wanted.intersection(claim.domainSlotIds)
            ]
        if request.includeClaims is False:
            claims = []

        available_offsets = [
            value
            for value in (read.observations_next_offset, read.memories_next_offset)
            if value is not None
        ]
        next_offset = max(available_offsets) if available_offsets else None
        page = (
            PageInfo(
                nextCursor=(
                    f"{_PAGE_CURSOR_PREFIX}{next_offset}" if next_offset is not None else None
                ),
                hasNextPage=read.observations_truncated or read.memories_truncated,
            )
            if request.page is not None
            else None
        )
        return ProjectionResult(
            projectionId=self.projection_id,
            tenantId=request.tenantId,
            contractVersion=self.contract_version,
            sections=sections,
            claims=claims,
            dependencyState=context.dependencyState,
            asOf=None,
            generatedAt=generated_at,
            page=page,
            degradedReasons=sorted(set(warnings)),
            temporalMode=request.temporalMode,
        )


def _render_memory_slots(
    *,
    request: ProjectionRequest,
    read: SemanticMemoryRead,
    unsupported_subject: bool,
    temporal_request_unsupported: bool,
) -> tuple[list[ProjectionSection], list[ClaimEnvelope]]:
    state = read.gold_state or {}
    state_ref = _gold_state_ref(state, request.tenantId) if state else None
    observation_rows = [
        row
        for row in read.observations
        if _status_value(row.get("status")) in _ACTIVE_OBSERVATION_STATUSES
    ]
    retracted_count = len(read.observations) - len(observation_rows)
    observation_ref_pairs = [
        (row, ref) for row in observation_rows if (ref := _observation_ref(row)) is not None
    ]
    observation_refs = [ref for _, ref in observation_ref_pairs]
    lineage_refs = _state_lineage_refs(state)
    evidence_refs = _dedupe_refs(
        [ref for ref in (state_ref, *lineage_refs, *observation_refs) if ref is not None]
    )
    gold_observation_count = _nonnegative_int(state.get("observation_count"))
    computed_at = _timestamp(state.get("computed_at"))
    latest_observation_update = max(
        (
            timestamp
            for row in read.observations
            if (timestamp := _timestamp(row.get("updated_at") or row.get("created_at")))
        ),
        default=None,
    )
    aggregate_matches_observations = bool(
        read.observations_complete
        and gold_observation_count is not None
        and gold_observation_count == len(read.observations)
        and not retracted_count
        and (
            latest_observation_update is None
            or computed_at is not None
            and latest_observation_update <= computed_at
        )
    )
    supports_current_state = bool(
        state
        and not temporal_request_unsupported
        and read.gold_state_state == "available"
        and aggregate_matches_observations
    )
    summary = _text(state.get("semantic_summary")) if supports_current_state else None
    summary_supported = bool(summary and summary != "insufficient_data")
    summary_insufficient_data = bool(supports_current_state and summary == "insufficient_data")
    summary_state = (
        "available"
        if summary_supported and state_ref is not None
        else "empty"
        if (read.gold_state_state == "empty" or summary_insufficient_data)
        and not temporal_request_unsupported
        else "unknown"
    )
    summary_refs = [ref for ref in [state_ref, *lineage_refs] if ref is not None]
    summary_content = _slot_content(
        state=summary_state,
        coverage="complete" if summary_state in {"available", "empty"} else "unknown",
        reason=(
            "reducer_produced_gold_summary_with_lineage"
            if summary_state == "available"
            else "semantic_reducer_reports_insufficient_data"
            if summary_insufficient_data
            else "no_semantic_entity_gold_state"
            if summary_state == "empty"
            else "semantic_entity_gold_summary_unavailable_or_historical_read_requested"
        ),
        evidence_refs=summary_refs,
        semanticSummary=summary if summary_supported else None,
        epistemicState="derived" if summary_supported else "unknown",
        summaryStatus="insufficient_data" if summary_insufficient_data else None,
        observationCount=_nonnegative_int(state.get("observation_count"))
        if supports_current_state
        else None,
        uniqueSourceCount=_nonnegative_int(state.get("unique_source_count"))
        if supports_current_state
        else None,
        confidence=_bounded_confidence(state.get("confidence")) if supports_current_state else None,
        window={
            "from": _timestamp(state.get("window_start")),
            "to": _timestamp(state.get("window_end")),
        }
        if supports_current_state
        else None,
        freshness={
            "state": "unknown",
            "reportedState": _text(state.get("freshness")),
            "computedAt": _timestamp(state.get("computed_at")),
            "evaluation": "freshness_threshold_not_configured_by_memory_projection",
        },
    )

    observations_missing = read.observations_state in {"unknown", "degraded"}
    source_links: list[dict[str, Any]] = []
    for row, evidence in observation_ref_pairs:
        source_event_id = _text(row.get("source_event_id"))
        observation_id = _text(row.get("observation_id"))
        if source_event_id is None or observation_id is None:
            continue
        source_links.append(
            {
                "observationId": observation_id,
                "sourceEventId": source_event_id,
                "sourceType": _text(row.get("source_type")),
                "occurredAt": _timestamp(row.get("occurred_at")),
                "modelId": _text(row.get("model_id")),
                "modelVersion": _text(row.get("model_version")),
                "evidenceRefs": [evidence.model_dump(mode="json")],
                "sourceRecordJoined": False,
            }
        )
    source_link_state = (
        "unknown"
        if observations_missing and not source_links
        else "degraded"
        if observations_missing
        else "degraded"
        if source_links
        else "empty"
    )

    topic_items: dict[str, dict[str, Any]] = {}
    for topic in _text_list(state.get("active_topics")) if supports_current_state else []:
        topic_items.setdefault(
            topic,
            {
                "label": topic,
                "origin": "gold_entity_semantic_state.active_topics",
                "epistemicState": "inferred",
                "evidenceRefs": [ref.model_dump(mode="json") for ref in summary_refs],
            },
        )
    for row, evidence in observation_ref_pairs:
        for topic in _text_list(row.get("topics")):
            topic_items.setdefault(
                topic,
                {
                    "label": topic,
                    "origin": "silver_semantic_observations.topics",
                    "epistemicState": "inferred",
                    "evidenceRefs": [evidence.model_dump(mode="json")],
                },
            )
    topic_state = (
        "unknown"
        if not entity_subject_supported(request) or observations_missing and not topic_items
        else "degraded"
        if observations_missing
        else "available"
        if topic_items
        else "empty"
        if read.gold_state_state == "available" or read.observations_state == "empty"
        else "unknown"
    )
    topic_refs = _dedupe_refs(
        [
            ref
            for item in topic_items.values()
            for raw_ref in item["evidenceRefs"]
            if (ref := _to_evidence_ref(raw_ref)) is not None
        ]
    )

    delta = _as_mapping(state.get("semantic_delta")) or {}
    reducer_half_life = _positive_number(delta.get("half_life_days"))
    decay_state = (
        "degraded" if supports_current_state and reducer_half_life is not None else "unknown"
    )
    decay_refs = summary_refs if decay_state == "degraded" else []
    contradiction = delta.get("contradiction")
    conflict_state = (
        "degraded" if supports_current_state and isinstance(contradiction, bool) else "unknown"
    )
    conflict_refs = summary_refs if conflict_state == "degraded" else []

    if unsupported_subject or temporal_request_unsupported:
        summary_content = _unknown_slot_content(
            "subject_kind_has_no_current_semantic_entity_read"
            if unsupported_subject
            else "requested_historical_or_windowed_semantic_state_not_supported"
        )
        topic_state = "unknown"
        topic_items = {}
        topic_refs = []
        source_links = []
        source_link_state = "unknown"
        decay_state = "unknown"
        decay_refs = []
        conflict_state = "unknown"
        conflict_refs = []

    memory_state = read.memories_state
    memory_items: list[dict[str, Any]] = []
    memory_refs: list[EvidenceRef] = []
    policy_decisions: list[dict[str, Any]] = []
    policy_refs: list[EvidenceRef] = []
    policy_join_incomplete = False
    for resolved in read.memories:
        record = resolved.record
        refs = list(resolved.evidence_refs)
        decision_id = _text(getattr(record, "policy_decision_ref", None))
        decision_ref = next(
            (
                ref
                for ref in refs
                if ref.source == "governance.consent_policy_decisions"
                and ref.id == decision_id
                and ref.uri
                == (
                    "store://consent_policy_decisions/"
                    f"{quote(request.tenantId, safe='')}:{quote(decision_id or '', safe='')}"
                )
                and _timestamp(ref.observedAt) is not None
            ),
            None,
        )
        if (
            getattr(record, "tenant_id", None) != request.tenantId
            or getattr(record, "subject_ref", None) != request.subject.id
            or not decision_id
            or getattr(resolved, "policy_outcome", None) != "historical_allow"
            or decision_ref is None
        ):
            policy_join_incomplete = True
            continue
        memory_refs.extend(refs)
        memory_items.append(
            {
                "memoryId": record.memory_id,
                "subjectRef": record.subject_ref,
                "subjectType": record.subject_type.value,
                "memoryKind": record.memory_kind,
                "summary": record.summary,
                "confidence": record.confidence,
                "sourceObservationIds": list(record.source_observation_ids),
                "policyDecisionRef": record.policy_decision_ref,
                "policyDecisionOutcomeAtWrite": resolved.policy_outcome,
                "retentionClass": record.retention_class,
                "createdAt": _timestamp(record.created_at),
                "evidenceRefs": [ref.model_dump(mode="json") for ref in refs],
            }
        )
        policy_refs.append(decision_ref)
        policy_decisions.append(
            {
                "memoryId": record.memory_id,
                "policyDecisionId": decision_id,
                "outcomeAtWrite": "allowed",
                "decidedAt": _timestamp(decision_ref.observedAt),
                "evidenceRefs": [decision_ref.model_dump(mode="json")],
            }
        )
    memory_refs = _dedupe_refs(memory_refs)
    policy_refs = _dedupe_refs(policy_refs)
    if policy_join_incomplete and memory_state != "unknown":
        memory_state = "degraded"
    latest_memory_created_at = max(
        (item["createdAt"] for item in memory_items if item["createdAt"]),
        default=None,
    )
    if unsupported_subject or temporal_request_unsupported:
        memory_state = "unknown"
        memory_items = []
        memory_refs = []
        latest_memory_created_at = None
        policy_decisions = []
        policy_refs = []
        policy_join_incomplete = False
    memory_reason = (
        "exact_tenant_subject_memory_records_with_active_observation_and_policy_joins"
        if memory_state in {"available", "degraded"} and memory_items
        else "no_canonical_semantic_memory_records_for_exact_subject"
        if memory_state == "empty"
        else "memory_record_source_or_policy_join_incomplete"
        if memory_state == "degraded"
        else "subject_kind_or_temporal_read_not_supported"
        if unsupported_subject or temporal_request_unsupported
        else "canonical_semantic_memory_record_read_unavailable"
        if memory_state == "unknown"
        else "subject_kind_or_temporal_read_not_supported"
    )
    memory_coverage = (
        "complete"
        if memory_state in {"available", "empty"} and read.memories_complete
        else "partial"
        if memory_state == "degraded"
        else "unknown"
    )
    memories_content = _slot_content(
        state=memory_state,
        coverage=memory_coverage,
        reason=memory_reason,
        evidence_refs=memory_refs,
        items=memory_items,
        observedCount=len(memory_items),
        freshness={
            "state": "unknown",
            "latestMemoryCreatedAt": latest_memory_created_at,
            "evaluation": "memory_staleness_threshold_not_configured",
        },
    )

    sections_content: dict[str, tuple[str, dict[str, Any]]] = {
        "semantic_summary": (summary_content["state"], summary_content),
        "memories": (memory_state, memories_content),
        "cards": (
            "unknown",
            _unknown_slot_content("no_canonical_context_card_authority"),
        ),
        "topics": (
            topic_state,
            _slot_content(
                state=topic_state,
                coverage=(
                    "complete"
                    if topic_state in {"available", "empty"}
                    else "partial"
                    if topic_state == "degraded"
                    else "unknown"
                ),
                reason=(
                    "reducer_topics_are_model_derived_labels"
                    if topic_state in {"available", "degraded"}
                    else "topic_authority_or_exact_subject_read_unavailable"
                ),
                evidence_refs=topic_refs,
                topics=list(topic_items.values()),
                epistemicState="inferred" if topic_items else "unknown",
            ),
        ),
        "embeddings_meta": (
            "unknown",
            _unknown_slot_content("no_canonical_embedding_metadata_authority"),
        ),
        "source_links": (
            source_link_state,
            _slot_content(
                state=source_link_state,
                coverage=(
                    "complete"
                    if source_link_state == "empty"
                    else "partial"
                    if source_link_state == "degraded"
                    else "unknown"
                ),
                reason=(
                    "exact_tenant_semantic_observation_source_event_references"
                    if source_links
                    else "semantic_observation_source_link_inventory_unavailable"
                    if source_link_state == "unknown"
                    else "no_semantic_observation_source_links_recorded"
                ),
                evidence_refs=observation_refs,
                links=source_links,
                sourceRecordJoinState="unknown",
                observedCount=len(source_links),
                omittedNonActiveObservationCount=retracted_count,
            ),
        ),
        "decay": (
            decay_state,
            _slot_content(
                state=decay_state,
                coverage="partial" if decay_state == "degraded" else "unknown",
                reason=(
                    "reducer_recency_half_life_parameter_only_no_per_memory_decay_score"
                    if decay_state == "degraded"
                    else "semantic_decay_metadata_unavailable"
                ),
                evidence_refs=decay_refs,
                reducerHalfLifeDays=reducer_half_life,
                freshnessReported=_text(state.get("freshness")) if supports_current_state else None,
                computedAt=_timestamp(state.get("computed_at")) if supports_current_state else None,
                decayScore=None,
            ),
        ),
        "conflicts": (
            conflict_state,
            _slot_content(
                state=conflict_state,
                coverage="partial" if conflict_state == "degraded" else "unknown",
                reason=(
                    "reducer_contradiction_signal_without_conflict_objects"
                    if conflict_state == "degraded"
                    else "canonical_conflict_objects_unavailable"
                ),
                evidence_refs=conflict_refs,
                contradictionSignal=contradiction if conflict_state == "degraded" else None,
                conflicts=[],
                epistemicState="derived" if conflict_state == "degraded" else "unknown",
            ),
        ),
        "policy_state": (
            "unknown"
            if read.memories_state == "unknown" or unsupported_subject or temporal_request_unsupported
            else "degraded",
            _slot_content(
                state=(
                    "unknown"
                    if read.memories_state == "unknown"
                    or unsupported_subject
                    or temporal_request_unsupported
                    else "degraded"
                ),
                coverage=(
                    "unknown"
                    if read.memories_state == "unknown"
                    or unsupported_subject
                    or temporal_request_unsupported
                    else "partial"
                ),
                reason=(
                    "historical_write_policy_decision_coverage_partial_current_policy_not_evaluated"
                    if policy_join_incomplete or read.memories_state == "degraded"
                    else "historical_write_policy_decisions_only_current_policy_not_evaluated"
                    if policy_decisions
                    else "no_historical_memory_policy_decisions_current_policy_not_evaluated"
                    if read.memories_state == "empty"
                    else "historical_memory_policy_decisions_unavailable_current_policy_not_evaluated"
                ),
                evidence_refs=policy_refs,
                evaluation="historical_write_decisions_only_current_policy_not_evaluated",
                currentConsentState="unknown",
                currentPolicyState="not_evaluated",
                historicalDecisionCoverage=(
                    "partial"
                    if policy_join_incomplete or read.memories_state == "degraded"
                    else "complete"
                    if read.memories_state in {"available", "empty"}
                    and read.memories_complete
                    else "unknown"
                ),
                historicalDecisionCount=len(policy_decisions),
                historicalDecisions=policy_decisions,
                stateFreshness="unknown",
                sourceStatusesObserved=len(read.observations),
                nonActiveRowsOmitted=retracted_count,
                riskLensState="unknown",
            ),
        ),
        "evidence_trace": (
            "available"
            if evidence_refs
            else "empty"
            if read.gold_state_state == "empty"
            else "unknown",
            _slot_content(
                state="available"
                if evidence_refs
                else "empty"
                if read.gold_state_state == "empty"
                else "unknown",
                coverage="partial"
                if evidence_refs
                else "empty"
                if read.gold_state_state == "empty"
                else "unknown",
                reason=(
                    "semantic_gold_record_lineage_and_active_observation_refs"
                    if evidence_refs
                    else "no_semantic_evidence_records"
                ),
                evidence_refs=evidence_refs,
                goldStateRef=state_ref.model_dump(mode="json") if state_ref is not None else None,
                semanticLineageRefs=[ref.model_dump(mode="json") for ref in lineage_refs],
                sourceObservationRefs=[ref.model_dump(mode="json") for ref in observation_refs],
                sourceRecordJoinState="unknown",
                freshness={
                    "state": "unknown",
                    "evaluation": "source_freshness_threshold_not_configured",
                },
            ),
        ),
    }
    sections = [
        ProjectionSection(
            id=slot_id,
            state=content_state,
            title=_MEMORY_SLOT_TITLES[slot_id],
            content=content,
            warnings=list(read.warnings) or None,
            canonicalAuthorityRefs=(
                ["semantic_memory_records", "consent_policy_decisions", "evidence"]
                if slot_id == "policy_state"
                else
                ["semantic_memory_graph"]
                if slot_id
                in {
                    "semantic_summary",
                    "memories",
                    "topics",
                    "decay",
                    "conflicts",
                    "evidence_trace",
                    "source_links",
                }
                else None
            ),
        )
        for slot_id, (content_state, content) in sections_content.items()
    ]

    claims: list[ClaimEnvelope] = []
    if summary_supported and summary_refs:
        claims.append(
            ClaimEnvelope(
                id=f"memory360:{request.subject.id}:semantic-summary",
                kind="semantic_summary",
                subject=request.subject,
                evidenceRefs=summary_refs,
                claims=["Canonical Gold semantic state contains a reducer-produced summary."],
                claimState=EpistemicStatus.DERIVED,
                domainSlotIds=["semantic_summary"],
            )
        )
    if topic_items:
        claims.append(
            ClaimEnvelope(
                id=f"memory360:{request.subject.id}:topics",
                kind="semantic_topic_labels",
                subject=request.subject,
                evidenceRefs=topic_refs,
                claims=["Canonical semantic records contain model-derived topic labels."],
                claimState=EpistemicStatus.INFERRED,
                domainSlotIds=["topics"],
            )
        )
    for item in memory_items:
        refs = [
            ref
            for raw_ref in item["evidenceRefs"]
            if (ref := _to_evidence_ref(raw_ref)) is not None
        ]
        if not refs:
            continue
        claims.append(
            ClaimEnvelope(
                id=f"memory360:{request.subject.id}:memory:{item['memoryId']}",
                kind="semantic_memory_record",
                subject=request.subject,
                evidenceRefs=refs,
                claims=[
                    "A canonical semantic memory record is linked to exact active source observations and an allowed policy decision recorded at write time."
                ],
                claimState=EpistemicStatus.OBSERVED,
                domainSlotIds=["memories"],
            )
        )
    for link in source_links:
        refs = [ref for ref in observation_refs if ref.id == link["observationId"]]
        if not refs:
            continue
        claims.append(
            ClaimEnvelope(
                id=f"memory360:{request.subject.id}:source-link:{link['observationId']}",
                kind="semantic_source_event_reference",
                subject=request.subject,
                evidenceRefs=refs,
                claims=["A tenant-scoped semantic observation records a source-event reference."],
                claimState=EpistemicStatus.OBSERVED,
                domainSlotIds=["source_links", "evidence_trace"],
            )
        )
    if state_ref is not None:
        claims.append(
            ClaimEnvelope(
                id=f"memory360:{request.subject.id}:gold-evidence",
                kind="semantic_gold_record",
                subject=request.subject,
                evidenceRefs=[state_ref],
                claims=["A tenant-scoped semantic Gold state record exists for this exact entity."],
                claimState=EpistemicStatus.OBSERVED,
                domainSlotIds=["evidence_trace"],
            )
        )
    return sections, claims


def _slot_content(
    *,
    state: str,
    coverage: str,
    reason: str,
    evidence_refs: list[EvidenceRef],
    **values: Any,
) -> dict[str, Any]:
    return {
        "state": state,
        "coverage": coverage,
        "reason": reason,
        "evidenceRefs": [ref.model_dump(mode="json") for ref in evidence_refs],
        **values,
    }


def _unknown_slot_content(reason: str) -> dict[str, Any]:
    return _slot_content(
        state="unknown",
        coverage="unknown",
        reason=reason,
        evidence_refs=[],
        items=[],
    )


def _gold_state_ref(state: dict[str, Any], tenant_id: str) -> Optional[EvidenceRef]:
    state_id = _text(state.get("state_id"))
    entity_ref = _text(state.get("entity_ref"))
    if not state_id or not entity_ref or state.get("tenant_id") != tenant_id:
        return None
    return EvidenceRef(
        id=state_id,
        type="model_output",
        source=_GOLD_SOURCE,
        observedAt=_timestamp(state.get("computed_at")),
        uri=(
            "store://gold_entity_semantic_state/"
            f"{quote(tenant_id, safe='')}:{quote(state_id, safe='')}"
        ),
    )


def _observation_ref(row: dict[str, Any]) -> Optional[EvidenceRef]:
    observation_id = _text(row.get("observation_id"))
    tenant_id = _text(row.get("tenant_id"))
    if not observation_id or not tenant_id:
        return None
    return EvidenceRef(
        id=observation_id,
        type="model_output",
        source=_SILVER_SOURCE,
        observedAt=_timestamp(row.get("processed_at") or row.get("occurred_at")),
        uri=(
            "store://silver_semantic_observations/"
            f"{quote(tenant_id, safe='')}:{quote(observation_id, safe='')}"
        ),
    )


def _state_lineage_refs(state: dict[str, Any]) -> list[EvidenceRef]:
    raw_refs = state.get("evidence_refs")
    if not isinstance(raw_refs, list):
        return []
    refs: list[EvidenceRef] = []
    for raw in raw_refs:
        item = _as_mapping(raw)
        if item is None:
            continue
        evidence_id = _text(item.get("evidence_id"))
        source_type = _text(item.get("source_type"))
        source_ref = _text(item.get("source_ref"))
        if evidence_id is None or source_type is None:
            continue
        refs.append(
            EvidenceRef(
                id=evidence_id,
                type="event",
                source=source_type,
                observedAt=_timestamp(item.get("observed_at")),
                confidence=_bounded_confidence(item.get("confidence")),
                uri=(f"evidence://{quote(source_type, safe='')}/{quote(source_ref, safe='')}")
                if source_ref
                else None,
            )
        )
    return _dedupe_refs(refs)


def _dedupe_refs(refs: list[EvidenceRef]) -> list[EvidenceRef]:
    seen: set[tuple[str, str, str]] = set()
    unique: list[EvidenceRef] = []
    for ref in refs:
        key = (ref.id, ref.type, ref.source)
        if key in seen:
            continue
        seen.add(key)
        unique.append(ref)
    return unique


def _to_evidence_ref(raw: dict[str, Any]) -> Optional[EvidenceRef]:
    try:
        return EvidenceRef.model_validate(raw)
    except Exception:  # noqa: BLE001 - malformed embedded lineage is omitted
        return None


def _cursor_offset(cursor: Optional[str]) -> tuple[int, Optional[str]]:
    if cursor is None:
        return 0, None
    if not cursor.startswith(_PAGE_CURSOR_PREFIX):
        return 0, "semantic_observation_cursor_invalid"
    raw_offset = cursor.removeprefix(_PAGE_CURSOR_PREFIX)
    try:
        offset = int(raw_offset)
    except ValueError:
        return 0, "semantic_observation_cursor_invalid"
    if offset < 0:
        return 0, "semantic_observation_cursor_invalid"
    return offset, None


def _as_mapping(value: Any) -> Optional[dict[str, Any]]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        try:
            dumped = value.model_dump(mode="json")
        except Exception:  # noqa: BLE001 - malformed source object remains unknown
            return None
        return dumped if isinstance(dumped, dict) else None
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return None


def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "value"):
        value = value.value
    text = str(value).strip()
    return text or None


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return list(dict.fromkeys(text for item in value if (text := _text(item)) is not None))


def _status_value(value: Any) -> Optional[str]:
    return _text(value)


def _timestamp(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
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


def _bounded_confidence(value: Any) -> Optional[float]:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    return confidence if 0 <= confidence <= 1 else None


def _nonnegative_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        count = int(value)
    except (TypeError, ValueError):
        return None
    return count if count >= 0 else None


def _positive_number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def entity_subject_supported(request: ProjectionRequest) -> bool:
    return request.subject.kind in {"semantic_entity", "entity"}


def register_provider(registry: ProviderRegistry) -> str:
    """Register Memory360 on the central projection runtime."""
    return registry.register(
        Memory360Provider(),
        source="services/api/intelligence/semantic_intelligence",
    )


__all__ = [
    "Memory360Provider",
    "RepositorySemanticMemoryReader",
    "SemanticMemoryRead",
    "SemanticMemoryReader",
    "register_provider",
]
