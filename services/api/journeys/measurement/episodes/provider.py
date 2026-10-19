"""episode360 intelligence-projection provider (WS-D item 2 surface).

Projects durable :class:`~shared.backend_interpretation.primitives.EpisodeRecord`
rows into the six ``episode360`` registry output sections (``evidence``,
``interactions``, ``outcomes``, ``state``, ``summary``, ``timeline``). A 360 is
an intelligence projection over canonical truth — never a competing system of
record — so the provider is ``read_only`` and every claim stays grounded in the
episode's own :class:`EvidenceRef` lineage.

Registry row ``episode360`` is ``in_flight`` (``implementationBlueprint:
docs/blueprints/episode360.md``); this provider is the WS-D read surface that
row was waiting on. It follows the outcome360 fail-isolated contract: a missing
store degrades sections to typed ``missing``/``empty`` and never raises, so the
plane stays up when the episode store is empty or unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional, Protocol
from uuid import UUID

from shared.backend_interpretation.primitives import EpisodeRecord
from shared.backend_interpretation.stores import EpisodeStore
from shared.contracts_models.epistemic import EpistemicStatus
from graph.operational_intelligence.models import EvidenceRef, PageInfo
from shared.intelligence_projections.contracts import (
    ClaimEnvelope,
    ProjectionContext,
    ProjectionRequest,
    ProjectionResult,
    ProjectionSection,
)
from shared.intelligence_projections.generated_registry import (
    INTELLIGENCE_PROJECTION_DEFINITIONS,
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
    PRODUCT_360_SURFACE_DEFINITIONS,
)
from shared.intelligence_projections.provider import IntelligenceProjectionProvider
from shared.intelligence_projections.registry import ProviderRegistry

_EPISODE360_SECTIONS = tuple(INTELLIGENCE_PROJECTION_DEFINITIONS["episode360"]["outputSections"])

_SECTION_TITLES = {
    "summary": "Episode summary",
    "state": "Episode state distribution",
    "evidence": "Episode evidence",
    "episode_context": "Episode subject and graph context",
    "interactions": "Episode interactions",
    "outcomes": "Episode outcomes",
    "timeline": "Episode timeline",
}

_JOURNEY_VERSION_SOURCE = (
    "services/api/journeys/measurement/repositories/journey_repo.py:journey_versions"
)
_JOURNEY_STEP_SOURCE = (
    "services/api/journeys/measurement/repositories/journey_step_repo.py:journey_steps"
)
_JOURNEY_STEP_CAP = 200
_EPISODE_PAGE_DEFAULT = 50
_EPISODE_SUBJECT_RELATIONSHIP_CAP = 100
_GRAPH_LEDGER_SOURCE = "graph_mutation_ledger"


@dataclass(frozen=True)
class Journey360Read:
    """One tenant-bound current journey version and a bounded step page."""

    journey: Optional[dict[str, Any]]
    steps: list[dict[str, Any]]
    available: bool
    complete: bool
    reason: Optional[str] = None


@dataclass(frozen=True)
class Episode360Read:
    """One bounded tenant page and whether it can support complete absence."""

    episodes: tuple[EpisodeRecord, ...] = ()
    available: bool = True
    truncated: bool = False
    invalid_records: bool = False
    tenant_mismatch: bool = False
    next_cursor: Optional[str] = None
    read_failed: bool = False

    @property
    def complete(self) -> bool:
        return not (
            not self.available
            or self.truncated
            or self.invalid_records
            or self.tenant_mismatch
            or self.read_failed
        )


@dataclass(frozen=True)
class EpisodeSubjectGraphRead:
    """Tenant-bound graph replay result for one exact episode subject id."""

    tenant_id: str
    subject_id: str
    events: tuple[Any, ...] = ()
    live_edges: tuple[tuple[str, str, str], ...] = ()


class EpisodeSubjectRelationshipReader(Protocol):
    """Canonical subject-scoped graph history read used for relationship context."""

    async def subject_history(
        self, *, tenant_id: str, subject_id: str
    ) -> EpisodeSubjectGraphRead: ...


class RepositoryEpisodeSubjectRelationshipReader:
    """Adapter over the read-only canonical graph mutation ledger replay."""

    async def subject_history(
        self, *, tenant_id: str, subject_id: str
    ) -> EpisodeSubjectGraphRead:
        from graph.temporal360.history_replay import GraphHistoryReplay

        history = await GraphHistoryReplay().subject_history(tenant_id, subject_id)
        return EpisodeSubjectGraphRead(
            tenant_id=tenant_id,
            subject_id=history.subject_id,
            events=history.events,
            live_edges=history.live_edges,
        )


class Journey360Source(Protocol):
    """Canonical journey and step authorities consumed by Episode360."""

    async def current_journey(
        self, *, tenant_id: str, journey_id: str
    ) -> Optional[dict[str, Any]]: ...

    async def steps(
        self,
        *,
        tenant_id: str,
        journey_id: str,
        journey_version_id: str,
        limit: int,
        cursor: Optional[str],
        after: Optional[datetime],
        before: Optional[datetime],
    ) -> list[dict[str, Any]]: ...


class RepositoryJourney360Source:
    """Adapter over the canonical versioned journey and ordered-step stores."""

    def __init__(self, *, journeys: Any = None, steps: Any = None) -> None:
        self._journeys = journeys
        self._steps = steps

    def _journey_repository(self) -> Any:
        if self._journeys is None:
            from journeys.measurement.repositories.journey_repo import JourneyRepository

            self._journeys = JourneyRepository()
        return self._journeys

    def _step_repository(self) -> Any:
        if self._steps is None:
            from journeys.measurement.repositories.journey_step_repo import (
                JourneyStepRepository,
            )

            self._steps = JourneyStepRepository()
        return self._steps

    async def current_journey(self, *, tenant_id: str, journey_id: str) -> Optional[dict[str, Any]]:
        row = await self._journey_repository().get_current(tenant_id, journey_id)
        return _as_mapping(row)

    async def steps(
        self,
        *,
        tenant_id: str,
        journey_id: str,
        journey_version_id: str,
        limit: int,
        cursor: Optional[str],
        after: Optional[datetime],
        before: Optional[datetime],
    ) -> list[dict[str, Any]]:
        rows = await self._step_repository().list_by_version(
            tenant_id,
            journey_version_id,
            limit=limit,
            cursor=cursor,
            after=after,
            before=before,
        )
        return [row for value in rows if (row := _as_mapping(value)) is not None]


class Episode360Provider:
    """The ``episode360`` intelligence projection provider (read_only)."""

    projection_id = "episode360"
    contract_version = INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION

    def __init__(
        self,
        episode_store: Optional[EpisodeStore] = None,
        journey_source: Optional[Journey360Source] = None,
        subject_relationship_reader: Optional[EpisodeSubjectRelationshipReader] = None,
    ) -> None:
        """``episode_store`` may be injected (tests); defaults to the durable
        :class:`EpisodeStore` (WS-D item 2)."""
        self._episode_store = episode_store
        self._journey_source = journey_source
        self._subject_relationship_reader = (
            subject_relationship_reader
            if subject_relationship_reader is not None
            else RepositoryEpisodeSubjectRelationshipReader()
        )

    def _load_store(self) -> Optional[EpisodeStore]:
        if self._episode_store is not None:
            return self._episode_store
        try:
            return EpisodeStore()
        except Exception:  # noqa: BLE001 - fail-isolated: never crash the plane
            return None

    async def _load_episodes(self, request: ProjectionRequest) -> Episode360Read:
        from shared.backend_interpretation.stores import subject_matches_request

        store = self._load_store()
        if store is None:
            return Episode360Read(available=False)
        if request.subject.kind == "episode":
            try:
                episode = await store.get(request.tenantId, request.subject.id)
            except Exception:  # noqa: BLE001 - exact source failure stays unavailable
                return Episode360Read(available=False, read_failed=True)
            if episode is None:
                # This exact composite-key lookup can establish known absence.
                return Episode360Read()
            if (
                not isinstance(episode, EpisodeRecord)
                or episode.tenant_id != request.tenantId
                or episode.episode_id != request.subject.id
            ):
                return Episode360Read(tenant_mismatch=True)
            return Episode360Read(episodes=(episode,))

        page_request = request.page
        limit = page_request.limit if page_request is not None else _EPISODE_PAGE_DEFAULT
        cursor = page_request.cursor if page_request is not None else None
        try:
            page = await store.list_page_by_tenant(
                request.tenantId,
                limit=limit,
                cursor=cursor,
            )
        except Exception:  # noqa: BLE001 - the projection stays available on store failure
            return Episode360Read(read_failed=True)

        subject = request.subject
        episodes: list[EpisodeRecord] = []
        tenant_mismatch = False
        for episode in page.records:
            if episode.tenant_id != request.tenantId:
                tenant_mismatch = True
                continue
            if subject_matches_request(episode.subject, subject.kind, subject.id):
                episodes.append(episode)
        return Episode360Read(
            episodes=tuple(episodes),
            truncated=page.truncated,
            invalid_records=page.invalid_records,
            tenant_mismatch=tenant_mismatch,
            next_cursor=page.next_cursor,
        )

    async def project(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
    ) -> ProjectionResult:
        """Run one tenant-scoped episode360 projection."""
        if request.subject.kind == "journey":
            return await self._project_journey(request, context)
        read = await self._load_episodes(request)
        episodes = list(read.episodes)
        warnings: list[str] = []
        if read.truncated:
            warnings.append("episode_page_truncated")
        if read.invalid_records:
            warnings.append("episode_page_contains_invalid_rows")
        if read.tenant_mismatch:
            warnings.append("episode_page_tenant_mismatch")
        if read.read_failed:
            warnings.append("episode_store_read_unavailable")
        if not read.available:
            availability = "missing"
        elif not read.complete:
            availability = "degraded" if episodes else "unknown"
        else:
            availability = _availability(read.available, bool(episodes))
        subject_relationship_context = None
        if request.subject.kind == "episode":
            if len(episodes) == 1:
                subject_relationship_context = await self._read_subject_relationship_context(
                    request, context, episodes[0]
                )
            else:
                reason = (
                    "episode_subject_read_incomplete"
                    if not read.complete
                    else "episode_subject_record_not_found"
                )
                subject_relationship_context = _unknown_subject_context(
                    request.subject.kind,
                    request.subject.id,
                    reason,
                )
        elif request.subject.kind == "entity":
            subject_relationship_context = await self._read_entity_subject_relationship_context(
                request,
                context,
                episodes,
                read_complete=read.complete,
            )
        elif request.subject.kind == "campaign":
            subject_relationship_context = _unknown_subject_context(
                request.subject.kind,
                request.subject.id,
                "campaign_entity_relationship_authority_unavailable",
            )
        else:
            subject_relationship_context = _unknown_subject_context(
                request.subject.kind,
                request.subject.id,
                "episode_subject_kind_not_bound_to_entity_context",
            )
        if subject_relationship_context.get("state") in {"unknown", "degraded"}:
            reason = subject_relationship_context.get("reason")
            if isinstance(reason, str) and reason not in warnings:
                warnings.append(reason)
        sections = self._build_sections(
            episodes,
            availability,
            warnings,
            subject_relationship_context=subject_relationship_context,
        )
        section_by_id = {section.id: section for section in sections}
        sections = [section_by_id[section_id] for section_id in _EPISODE360_SECTIONS]
        claims = self._build_claims(request, episodes)
        return ProjectionResult(
            projectionId=self.projection_id,
            tenantId=request.tenantId,
            contractVersion=self.contract_version,
            sections=sections,
            claims=claims,
            dependencyState=context.dependencyState,
            asOf=context.asOf,
            generatedAt=datetime.now(timezone.utc).isoformat(),
            page=PageInfo(
                nextCursor=read.next_cursor,
                hasNextPage=read.truncated,
                totalEstimate=(
                    len(episodes) if request.page.cursor is None and read.complete else None
                ),
            )
            if request.page is not None
            else None,
            degradedReasons=warnings,
            temporalMode=request.temporalMode or "window",
        )

    async def _read_entity_subject_relationship_context(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
        episodes: list[EpisodeRecord],
        *,
        read_complete: bool,
    ) -> dict[str, Any]:
        """Bind entity graph history only through an exact canonical episode subject.

        ``entity`` is a coarse projection subject. The tenant-scoped EpisodeRecord
        read supplies the precise EntityRef kind and confirms that the requested
        id is the exact persisted subject before graph history is queried.
        """
        candidates = [
            episode
            for episode in episodes
            if episode.tenant_id == request.tenantId and episode.subject.id == request.subject.id
        ]
        subject_keys = {(episode.subject.kind, episode.subject.id) for episode in candidates}
        if len(subject_keys) > 1:
            return _unknown_subject_context(
                request.subject.kind,
                request.subject.id,
                "episode_subject_kind_ambiguous",
            )
        if not candidates:
            reason = (
                "episode_subject_read_incomplete"
                if not read_complete
                else "episode_subject_record_not_found"
            )
            return _unknown_subject_context(request.subject.kind, request.subject.id, reason)

        # All matching rows have the same exact typed subject; replay the graph
        # once and retain the bounded set of episode witnesses that selected it.
        relationship_context = await self._read_subject_relationship_context(
            request,
            context,
            candidates[0],
            associated_episode_ids=[episode.episode_id for episode in candidates],
            association_complete=read_complete,
        )
        return relationship_context

    async def _read_subject_relationship_context(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
        episode: EpisodeRecord,
        *,
        associated_episode_ids: Optional[list[str]] = None,
        association_complete: bool = True,
    ) -> dict[str, Any]:
        """Read bounded graph context through the exact persisted episode subject.

        Relationship evidence is returned separately from the episode's own
        evidence lineage. The replay API does not expose a completeness
        watermark, so even an empty result remains unknown rather than proving
        that the subject has no graph relationships.
        """
        subject = episode.subject
        subject_ref = {"kind": subject.kind, "id": subject.id}
        base: dict[str, Any] = {
            "episodeId": episode.episode_id,
            "subject": subject_ref,
            "coverage": "unknown",
            "observedRelationships": [],
            "relationshipEvidenceRefs": [],
        }
        if associated_episode_ids is not None:
            base["episodeIds"] = sorted(set(associated_episode_ids))
            base["episodeAssociationCoverage"] = (
                "complete" if association_complete else "partial"
            )
        mode = request.temporalMode or "window"
        has_window = request.timeRange is not None and (
            request.timeRange.from_ is not None or request.timeRange.to is not None
        )
        if context.tenantId != request.tenantId:
            return {
                **base,
                "state": "unknown",
                "reason": "tenant_scope_mismatch",
            }
        if request.asOf is not None or context.asOf is not None or mode != "window" or has_window:
            return {
                **base,
                "state": "unknown",
                "reason": "episode_subject_relationship_temporal_scope_unsupported",
            }
        try:
            result = await self._subject_relationship_reader.subject_history(
                tenant_id=request.tenantId,
                subject_id=subject.id,
            )
        except Exception:  # noqa: BLE001 - graph context fails closed independently
            return {
                **base,
                "state": "unknown",
                "reason": "episode_subject_graph_read_unavailable",
            }
        if (
            not isinstance(result, EpisodeSubjectGraphRead)
            or result.tenant_id != request.tenantId
            or result.subject_id != subject.id
        ):
            return {
                **base,
                "state": "unknown",
                "reason": "episode_subject_graph_scope_mismatch",
            }

        live_edges = set(result.live_edges)
        current_events: dict[tuple[str, str, str], Any] = {}
        for event in result.events:
            if getattr(event, "kind", None) != "edge_added":
                continue
            edge_type = getattr(event, "edge_type", None)
            from_id = getattr(event, "from_vertex_id", None)
            to_id = getattr(event, "to_vertex_id", None)
            mutation_id = getattr(event, "mutation_id", None)
            if not all(isinstance(value, str) and value for value in (edge_type, from_id, to_id)):
                continue
            key = (edge_type, from_id, to_id)
            if key in live_edges and subject.id in (from_id, to_id) and mutation_id:
                current_events[key] = event

        relationships: list[dict[str, Any]] = []
        evidence_refs: list[EvidenceRef] = []
        for key, event in sorted(
            current_events.items(),
            key=lambda item: (
                int(getattr(item[1], "ledger_offset", 0) or 0),
                str(getattr(item[1], "mutation_id", "")),
            ),
        )[-_EPISODE_SUBJECT_RELATIONSHIP_CAP:]:
            mutation_id = str(event.mutation_id)
            evidence_ref = EvidenceRef(
                id=mutation_id,
                type="relationship",
                source=_GRAPH_LEDGER_SOURCE,
                observedAt=getattr(event, "recorded_at", None) or None,
            )
            evidence_refs.append(evidence_ref)
            relationships.append(
                {
                    "edgeType": key[0],
                    "fromEntityId": key[1],
                    "toEntityId": key[2],
                    "state": "active",
                    "recordedAt": getattr(event, "recorded_at", None) or None,
                    "evidenceRefId": mutation_id,
                }
            )
        return {
            **base,
            "state": "degraded" if relationships else "unknown",
            "reason": "graph_history_replay_has_no_completeness_watermark",
            "observedRelationships": relationships,
            "relationshipEvidenceRefs": [ref.model_dump() for ref in evidence_refs],
            "truncated": len(current_events) > _EPISODE_SUBJECT_RELATIONSHIP_CAP,
        }

    async def _project_journey(
        self, request: ProjectionRequest, context: ProjectionContext
    ) -> ProjectionResult:
        generated_at = datetime.now(timezone.utc).isoformat()
        temporal_mode = request.temporalMode or "window"
        if context.tenantId != request.tenantId:
            return _journey_unavailable_result(
                request, context, generated_at, temporal_mode, "tenant_scope_mismatch"
            )
        if request.asOf is not None or temporal_mode not in {"window", "relative"}:
            return _journey_unavailable_result(
                request,
                context,
                generated_at,
                temporal_mode,
                "journey_temporal_mode_unsupported",
            )
        if temporal_mode == "relative" and request.timeRange is None:
            return _journey_unavailable_result(
                request,
                context,
                generated_at,
                temporal_mode,
                "relative_time_range_not_resolved",
            )

        after, before, range_issue = _journey_time_bounds(request)
        if range_issue is not None:
            return _journey_unavailable_result(
                request, context, generated_at, temporal_mode, range_issue
            )

        source = self._journey_source or RepositoryJourney360Source()
        try:
            raw_journey = await source.current_journey(
                tenant_id=request.tenantId,
                journey_id=request.subject.id,
            )
        except Exception:  # noqa: BLE001 - persistence diagnostics stay private
            return _journey_unavailable_result(
                request,
                context,
                generated_at,
                temporal_mode,
                "journey_authority_unavailable",
            )
        journey = _as_mapping(raw_journey)
        if journey is None:
            return _journey_missing_result(request, context, generated_at, temporal_mode)

        journey_id = _journey_text(journey.get("journey_id"))
        version_id = _journey_text(journey.get("journey_version_id"))
        if (
            journey.get("tenant_id") != request.tenantId
            or journey_id != request.subject.id
            or not version_id
        ):
            return _journey_unavailable_result(
                request,
                context,
                generated_at,
                temporal_mode,
                "journey_authority_scope_mismatch",
            )

        page_limit = min(
            _JOURNEY_STEP_CAP,
            max(1, request.page.limit if request.page is not None else 100),
        )
        cursor = request.page.cursor if request.page is not None else None
        try:
            raw_steps = await source.steps(
                tenant_id=request.tenantId,
                journey_id=journey_id,
                journey_version_id=version_id,
                limit=page_limit + 1,
                cursor=cursor,
                after=after,
                before=before,
            )
        except Exception:  # noqa: BLE001 - step read may degrade independently
            raw_steps = []
            steps_available = False
        else:
            steps_available = True

        scoped_steps: list[dict[str, Any]] = []
        scope_mismatch = False
        for value in raw_steps:
            row = _as_mapping(value)
            if row is None:
                scope_mismatch = True
                continue
            if (
                row.get("tenant_id") != request.tenantId
                or _journey_text(row.get("journey_id")) != journey_id
                or _journey_text(row.get("journey_version_id")) != version_id
            ):
                scope_mismatch = True
                continue
            scoped_steps.append(row)
        scoped_steps.sort(key=lambda row: _journey_int(row.get("step_position"), 0))
        truncated = len(scoped_steps) > page_limit
        rendered_steps = scoped_steps[:page_limit]
        journey_ref = _journey_version_ref(journey)
        step_refs = [
            reference for row in rendered_steps if (reference := _journey_step_ref(row)) is not None
        ]
        warnings: list[str] = []
        if not steps_available:
            warnings.append("journey_step_authority_unavailable")
        if truncated:
            warnings.append("journey_steps_truncated")
        if scope_mismatch:
            warnings.append("unscoped_journey_step_rows_dropped")

        sections = _build_journey_sections(
            request=request,
            journey=journey,
            steps=rendered_steps,
            journey_ref=journey_ref,
            step_refs=step_refs,
            steps_available=steps_available,
            truncated=truncated,
            warnings=warnings,
        )
        if request.includeSections is not None:
            wanted = set(request.includeSections)
            sections = [section for section in sections if section.id in wanted]
        claims = (
            _build_journey_claims(request, journey, rendered_steps, journey_ref, step_refs)
            if request.includeClaims is not False and steps_available and not scope_mismatch
            else []
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
            page=PageInfo(
                hasNextPage=truncated,
                totalEstimate=None if cursor is not None or truncated else len(scoped_steps),
            )
            if request.page is not None
            else None,
            degradedReasons=sorted(set(warnings)),
            temporalMode=temporal_mode,
        )

    # ── Rendering ────────────────────────────────────────────────────────────

    def _build_sections(
        self,
        episodes: list[EpisodeRecord],
        availability: str,
        warnings: Optional[list[str]] = None,
        *,
        subject_relationship_context: Optional[dict[str, Any]] = None,
    ) -> list[ProjectionSection]:
        complete = availability in {"available", "empty"}
        by_kind = _kind_counts(episodes)
        by_status = _status_distribution(episodes)
        evidence = _collect_evidence(episodes)
        interaction_count = sum(len(e.observation_ids) for e in episodes)
        outcome_count = sum(len(e.outcome_ids) for e in episodes)
        open_count = by_status.get("open", 0)
        evidence_availability = (
            availability
            if availability in {"degraded", "unknown"}
            else _availability(availability != "missing", bool(evidence))
        )
        evidence_content: dict[str, Any] = {
            "evidence": [ref.model_dump() for ref in evidence],
            "evidenceCount": len(evidence) if complete else None,
            "observedEvidenceCount": len(evidence),
            "coverage": "complete" if complete else availability,
            "episodeSubjects": [
                {
                    "episodeId": episode.episode_id,
                    "subject": {"kind": episode.subject.kind, "id": episode.subject.id},
                }
                for episode in episodes
            ],
        }
        if subject_relationship_context is not None:
            evidence_content["subjectRelationshipContext"] = subject_relationship_context
        subject_relationship_refs = subject_relationship_context or {}
        subject_relationship_section_state = (
            "available"
            if subject_relationship_refs.get("observedRelationships")
            and subject_relationship_refs.get("relationshipEvidenceRefs")
            else subject_relationship_refs.get("state", "not_applicable")
        )
        subject_relationship_reason = subject_relationship_refs.get("reason")
        subject_relationship_warnings = (
            [subject_relationship_reason]
            if isinstance(subject_relationship_reason, str)
            else None
        )
        return [
            ProjectionSection(
                id="summary",
                state=availability,
                title=_SECTION_TITLES["summary"],
                content={
                    "episodeCount": len(episodes) if complete else None,
                    "observedEpisodeCount": len(episodes),
                    "openCount": open_count if complete else None,
                    "observedOpenCount": open_count,
                    "interactionCount": interaction_count if complete else None,
                    "observedInteractionCount": interaction_count,
                    "outcomeCount": outcome_count if complete else None,
                    "observedOutcomeCount": outcome_count,
                    "kinds": by_kind if complete else None,
                    "observedKinds": by_kind,
                    "stateDistribution": by_status if complete else None,
                    "observedStateDistribution": by_status,
                    "coverage": "complete" if complete else availability,
                },
                warnings=warnings or None,
            ),
            ProjectionSection(
                id="state",
                state=availability,
                title=_SECTION_TITLES["state"],
                content={
                    "distribution": by_status if complete else None,
                    "observedDistribution": by_status,
                    "coverage": "complete" if complete else availability,
                },
                warnings=warnings or None,
            ),
            ProjectionSection(
                id="evidence",
                state=evidence_availability,
                title=_SECTION_TITLES["evidence"],
                content=evidence_content,
                warnings=warnings or None,
            ),
            ProjectionSection(
                id="episode_context",
                state=subject_relationship_section_state,
                title=_SECTION_TITLES["episode_context"],
                content=subject_relationship_context,
                warnings=subject_relationship_warnings,
            ),
            ProjectionSection(
                id="interactions",
                state=availability,
                title=_SECTION_TITLES["interactions"],
                content={
                    "interactionCount": interaction_count if complete else None,
                    "observedInteractionCount": interaction_count,
                    "observationIds": _flatten(e.observation_ids for e in episodes),
                    "coverage": "complete" if complete else availability,
                },
                warnings=warnings or None,
            ),
            ProjectionSection(
                id="outcomes",
                state=availability,
                title=_SECTION_TITLES["outcomes"],
                content={
                    "outcomeCount": outcome_count if complete else None,
                    "observedOutcomeCount": outcome_count,
                    "outcomeIds": _flatten(e.outcome_ids for e in episodes),
                    "coverage": "complete" if complete else availability,
                },
                warnings=warnings or None,
            ),
            ProjectionSection(
                id="timeline",
                state=availability,
                title=_SECTION_TITLES["timeline"],
                content={
                    "timeline": [
                        {
                            "episodeId": e.episode_id,
                            "kind": e.kind,
                            "status": e.status,
                            "occurredFrom": e.occurred_from,
                            "occurredTo": e.occurred_to,
                            "observationCount": len(e.observation_ids),
                            "outcomeCount": len(e.outcome_ids),
                        }
                        for e in sorted(
                            episodes,
                            key=lambda e: e.occurred_from or e.created_at or "",
                        )
                    ],
                    "coverage": "complete" if complete else availability,
                },
                warnings=warnings or None,
            ),
        ]

    def _build_claims(
        self, request: ProjectionRequest, episodes: list[EpisodeRecord]
    ) -> list[ClaimEnvelope]:
        claims: list[ClaimEnvelope] = []
        for episode in episodes:
            claims.append(
                ClaimEnvelope(
                    id=f"episode.{episode.episode_id}.span",
                    kind="episode",
                    subject=request.subject,
                    evidenceRefs=episode.evidence_refs,
                    claims=[
                        f"episode {episode.episode_id!r} ({episode.kind!r}) "
                        f"spans {episode.observation_ids and len(episode.observation_ids) or 0} "
                        f"observations and is {episode.status}"
                    ],
                )
            )
        return claims


def register_provider(registry: ProviderRegistry) -> str:
    """Register the Episode360 provider on a ``ProviderRegistry`` instance."""
    return registry.register(
        Episode360Provider(),
        source="services/api/journeys/measurement/episodes",
    )


# ── Module helpers ───────────────────────────────────────────────────────────


def _journey_unavailable_result(
    request: ProjectionRequest,
    context: ProjectionContext,
    generated_at: str,
    temporal_mode: str,
    reason: str,
) -> ProjectionResult:
    sections = [
        ProjectionSection(
            id=section_id,
            state="unknown",
            title=_SECTION_TITLES[section_id],
            warnings=[reason],
        )
        for section_id in _EPISODE360_SECTIONS
    ]
    if request.includeSections is not None:
        wanted = set(request.includeSections)
        sections = [section for section in sections if section.id in wanted]
    return ProjectionResult(
        projectionId="episode360",
        tenantId=request.tenantId,
        contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
        sections=sections,
        claims=[],
        dependencyState=context.dependencyState,
        generatedAt=generated_at,
        degradedReasons=[reason],
        temporalMode=temporal_mode,
    )


def _journey_missing_result(
    request: ProjectionRequest,
    context: ProjectionContext,
    generated_at: str,
    temporal_mode: str,
) -> ProjectionResult:
    sections = [
        ProjectionSection(
            id=section_id,
            state="missing",
            title=_SECTION_TITLES[section_id],
            warnings=["tenant_scoped_journey_not_found"],
        )
        for section_id in _EPISODE360_SECTIONS
    ]
    if request.includeSections is not None:
        wanted = set(request.includeSections)
        sections = [section for section in sections if section.id in wanted]
    return ProjectionResult(
        projectionId="episode360",
        tenantId=request.tenantId,
        contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
        sections=sections,
        claims=[],
        dependencyState=context.dependencyState,
        generatedAt=generated_at,
        degradedReasons=["tenant_scoped_journey_not_found"],
        temporalMode=temporal_mode,
    )


def _journey_time_bounds(
    request: ProjectionRequest,
) -> tuple[Optional[datetime], Optional[datetime], Optional[str]]:
    time_range = request.timeRange
    if time_range is None:
        return None, None, None

    def parse(value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("timestamp must be a string")
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone is required")
        return parsed.astimezone(timezone.utc)

    try:
        after = parse(time_range.from_)
        before = parse(time_range.to)
    except (AttributeError, TypeError, ValueError):
        return None, None, "journey_time_range_invalid"
    if after is not None and before is not None and before < after:
        return None, None, "journey_time_range_reversed"
    return after, before, None


def _build_journey_sections(
    *,
    request: ProjectionRequest,
    journey: dict[str, Any],
    steps: list[dict[str, Any]],
    journey_ref: EvidenceRef,
    step_refs: list[EvidenceRef],
    steps_available: bool,
    truncated: bool,
    warnings: list[str],
) -> list[ProjectionSection]:
    time_window = {
        "from": request.timeRange.from_ if request.timeRange is not None else None,
        "to": request.timeRange.to if request.timeRange is not None else None,
    }
    step_state = (
        "unknown"
        if not steps_available
        else "degraded"
        if truncated or "unscoped_journey_step_rows_dropped" in warnings
        else "available"
        if steps
        else "empty"
    )
    step_evidence = [ref.model_dump(mode="json") for ref in step_refs]
    version_evidence = [journey_ref.model_dump(mode="json")]
    journey_view = _journey_view(journey)
    timeline = [_journey_step_view(row) for row in steps]
    output: dict[str, ProjectionSection] = {
        "summary": ProjectionSection(
            id="summary",
            state="available",
            title=_SECTION_TITLES["summary"],
            content={
                "journey": journey_view,
                "stepCount": len(steps),
                "timeWindow": time_window,
                "evidenceRefs": version_evidence,
            },
        ),
        "state": ProjectionSection(
            id="state",
            state="available",
            title=_SECTION_TITLES["state"],
            content={
                "journeyId": journey_view["journeyId"],
                "journeyVersionId": journey_view["journeyVersionId"],
                "journeyState": journey_view["journeyState"],
                "isCurrent": journey_view["isCurrent"],
                "computedAt": journey_view["computedAt"],
                "evidenceRefs": version_evidence,
            },
        ),
        "evidence": ProjectionSection(
            id="evidence",
            state="available",
            title=_SECTION_TITLES["evidence"],
            content={
                "journeyVersion": version_evidence[0],
                "journeySteps": step_evidence,
                "sourceEventIds": _journey_values(journey.get("event_ids")),
                "evidenceRefs": version_evidence + step_evidence,
                "rawStepEvidenceSummaryIncluded": False,
            },
            warnings=warnings or None,
        ),
        "episode_context": ProjectionSection(
            id="episode_context",
            state="not_applicable",
            title=_SECTION_TITLES["episode_context"],
            content={
                "state": "not_applicable",
                "coverage": "not_applicable",
                "reason": "journey_subject_has_no_episode_entity_binding",
                "observedRelationships": [],
                "relationshipEvidenceRefs": [],
            },
        ),
        "interactions": ProjectionSection(
            id="interactions",
            state=step_state,
            title=_SECTION_TITLES["interactions"],
            content=(
                {
                    "interactionCount": len(steps),
                    "activities": [
                        {
                            "activityId": _journey_text(row.get("activity_id")),
                            "activityType": _journey_text(row.get("activity_type")),
                            "activityFamily": _journey_text(row.get("activity_family")),
                            "occurredAt": _journey_timestamp(row.get("occurred_at")),
                            "evidenceRefs": [ref.model_dump(mode="json")]
                            if (ref := _journey_step_ref(row)) is not None
                            else [],
                        }
                        for row in steps
                    ],
                    "evidenceRefs": step_evidence,
                }
                if steps_available
                else None
            ),
            warnings=warnings or None,
        ),
        "outcomes": ProjectionSection(
            id="outcomes",
            state="unknown",
            title=_SECTION_TITLES["outcomes"],
            warnings=["journey_outcome_truth_join_unavailable"],
        ),
        "timeline": ProjectionSection(
            id="timeline",
            state=step_state,
            title=_SECTION_TITLES["timeline"],
            content=(
                {
                    "journey": journey_view,
                    "timeline": timeline,
                    "evidenceRefs": version_evidence + step_evidence,
                }
                if steps_available
                else None
            ),
            warnings=warnings or None,
        ),
    }
    return [output[section_id] for section_id in _EPISODE360_SECTIONS]


def _build_journey_claims(
    request: ProjectionRequest,
    journey: dict[str, Any],
    steps: list[dict[str, Any]],
    journey_ref: EvidenceRef,
    step_refs: list[EvidenceRef],
) -> list[ClaimEnvelope]:
    journey_id = _journey_text(journey.get("journey_id")) or request.subject.id
    version_id = _journey_text(journey.get("journey_version_id")) or journey_id
    version_slots = _journey_slot_ids_for_sections({"summary", "state", "evidence"})
    step_slots = _journey_slot_ids_for_sections({"timeline", "interactions", "evidence"})
    claims = [
        ClaimEnvelope(
            id=f"episode360:{journey_id}:{version_id}:journey-version",
            kind="server_recorded_journey_version",
            subject=request.subject,
            evidenceRefs=[journey_ref],
            claims=["A tenant-scoped journey version is persisted."],
            claimState=EpistemicStatus.OBSERVED,
            domainSlotIds=version_slots,
        )
    ]
    for row, evidence in zip(steps, step_refs, strict=False):
        step_id = _journey_text(row.get("step_id"))
        if not step_id:
            continue
        claims.append(
            ClaimEnvelope(
                id=f"episode360:{journey_id}:{version_id}:step:{step_id}",
                kind="server_recorded_journey_step",
                subject=request.subject,
                evidenceRefs=[evidence],
                claims=["A persisted activity step belongs to this journey version."],
                claimState=EpistemicStatus.OBSERVED,
                domainSlotIds=step_slots,
            )
        )
        if len(claims) >= 101:
            break
    return claims


def _journey_slot_ids_for_sections(section_ids: set[str]) -> list[str]:
    slot_ids: set[str] = set()
    for surface in PRODUCT_360_SURFACE_DEFINITIONS.values():
        if not isinstance(surface, dict) or "journey" not in surface.get("subjectKinds", []):
            continue
        for slot in surface.get("domainSlots", []):
            if not isinstance(slot, dict):
                continue
            for binding in slot.get("projectionBindings", []):
                if (
                    isinstance(binding, dict)
                    and binding.get("projectionId") == "episode360"
                    and "journey" in binding.get("subjectKinds", [])
                    and section_ids.intersection(binding.get("sectionIds", []))
                ):
                    slot_id = slot.get("id")
                    if isinstance(slot_id, str):
                        slot_ids.add(slot_id)
    return sorted(slot_ids)


def _journey_version_ref(journey: dict[str, Any]) -> EvidenceRef:
    version_id = _journey_text(journey.get("journey_version_id")) or "unknown-version"
    return EvidenceRef(
        id=version_id,
        type="entity",
        source=_JOURNEY_VERSION_SOURCE,
        observedAt=_journey_timestamp(journey.get("computed_at")),
        uri=f"store://journey_versions/{version_id}",
    )


def _journey_step_ref(row: dict[str, Any]) -> Optional[EvidenceRef]:
    step_id = _journey_text(row.get("step_id"))
    if not step_id:
        return None
    return EvidenceRef(
        id=step_id,
        type="event",
        source=_JOURNEY_STEP_SOURCE,
        observedAt=_journey_timestamp(row.get("occurred_at")),
        uri=f"store://journey_steps/{step_id}",
    )


def _journey_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "journeyId": _journey_text(row.get("journey_id")),
        "journeyVersionId": _journey_text(row.get("journey_version_id")),
        "journeyType": _journey_text(row.get("journey_type")),
        "journeyState": _journey_text(row.get("journey_state")),
        "isCurrent": row.get("is_current") if isinstance(row.get("is_current"), bool) else None,
        "profileId": _journey_text(row.get("profile_id")),
        "clusterId": _journey_text(row.get("cluster_id")),
        "agentId": _journey_text(row.get("agent_id")),
        "campaignIds": _journey_values(row.get("campaign_ids")),
        "channelSequence": _journey_values(row.get("channel_sequence")),
        "conversionIds": _journey_values(row.get("conversion_ids")),
        "eventIds": _journey_values(row.get("event_ids")),
        "startedAt": _journey_timestamp(row.get("started_at")),
        "endedAt": _journey_timestamp(row.get("ended_at")),
        "convertedAt": _journey_timestamp(row.get("converted_at")),
        "computedAt": _journey_timestamp(row.get("computed_at")),
        "dataWatermark": _journey_timestamp(row.get("data_watermark")),
        "identityVersion": _journey_text(row.get("identity_version")),
        "compilerVersion": _journey_text(row.get("compiler_version")),
    }


def _journey_step_view(row: dict[str, Any]) -> dict[str, Any]:
    evidence = _journey_step_ref(row)
    return {
        "stepId": _journey_text(row.get("step_id")),
        "position": _journey_int(row.get("step_position"), 0),
        "occurredAt": _journey_timestamp(row.get("occurred_at")),
        "activityId": _journey_text(row.get("activity_id")),
        "activityFamily": _journey_text(row.get("activity_family")),
        "activityType": _journey_text(row.get("activity_type")),
        "transitionType": _journey_text(row.get("transition_type")),
        "actorType": _journey_text(row.get("actor_type")),
        "channel": _journey_text(row.get("channel")),
        "sourceClass": _journey_text(row.get("source_class")),
        "trafficOrigin": _journey_text(row.get("traffic_origin")),
        "economicClass": _journey_text(row.get("economic_class")),
        "channelFamily": _journey_text(row.get("channel_family")),
        "proofLevel": _journey_text(row.get("proof_level")),
        "journeyRole": _journey_text(row.get("journey_role")),
        "campaignId": _journey_text(row.get("campaign_id")),
        "conversionId": _journey_text(row.get("conversion_id")),
        "agentId": _journey_text(row.get("agent_id")),
        "activityStatus": _journey_text(row.get("activity_status")),
        "evidenceRefs": [evidence.model_dump(mode="json")] if evidence is not None else [],
    }


def _journey_values(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    values = {_journey_text(item) for item in value}
    return sorted(item for item in values if item is not None)


def _journey_text(value: Any) -> Optional[str]:
    if hasattr(value, "value"):
        value = value.value
    if isinstance(value, (str, int)):
        text = str(value).strip()
        return text or None
    if isinstance(value, UUID):
        return str(value)
    return None


def _unknown_subject_context(subject_kind: str, subject_id: str, reason: str) -> dict[str, Any]:
    """Return an explicit unresolved state without treating a request as canonical."""
    return {
        "state": "unknown",
        "coverage": "unknown",
        "requestedSubject": {"kind": subject_kind, "id": subject_id},
        "subject": None,
        "observedRelationships": [],
        "relationshipEvidenceRefs": [],
        "reason": reason,
    }


def _journey_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _journey_timestamp(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return None
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc).isoformat()
    return None


def _as_mapping(value: Any) -> Optional[dict[str, Any]]:
    if isinstance(value, dict):
        return dict(value)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            return dump(mode="json")
        except TypeError:
            try:
                return dump()
            except Exception:  # noqa: BLE001 - malformed repository row stays unknown
                return None
        except Exception:  # noqa: BLE001 - malformed repository row stays unknown
            return None
    return None


def _availability(store_present: bool, present: bool) -> str:
    if present:
        return "available"
    return "empty" if store_present else "missing"


def _kind_counts(episodes: list[EpisodeRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for e in episodes:
        counts[e.kind] = counts.get(e.kind, 0) + 1
    return dict(sorted(counts.items()))


def _status_distribution(episodes: list[EpisodeRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for e in episodes:
        counts[e.status] = counts.get(e.status, 0) + 1
    return dict(sorted(counts.items()))


def _collect_evidence(episodes: list[EpisodeRecord]) -> list[Any]:
    seen: set[str] = set()
    refs: list[Any] = []
    for e in episodes:
        for ref in e.evidence_refs:
            if ref.id in seen:
                continue
            seen.add(ref.id)
            refs.append(ref)
    return refs


def _flatten(lists: Any) -> list[str]:
    result: list[str] = []
    for item in lists:
        for value in item:
            if value not in result:
                result.append(value)
    return result


__all__ = [
    "Episode360Provider",
    "EpisodeSubjectGraphRead",
    "EpisodeSubjectRelationshipReader",
    "Journey360Read",
    "Journey360Source",
    "RepositoryEpisodeSubjectRelationshipReader",
    "RepositoryJourney360Source",
    "register_provider",
]
