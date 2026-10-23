"""episode360 intelligence-projection provider (WS-D item 2 surface).

Projects durable :class:`~shared.backend_interpretation.primitives.EpisodeRecord`
rows into the ``episode360`` registry output sections (``evidence``,
``episode_context``, ``interactions``, ``outcomes``, ``state``, ``summary``,
``timeline``). A 360 is
an intelligence projection over canonical truth — never a competing system of
record — so the provider is ``read_only``. Episode observation IDs are resolved
only through exact tenant-scoped canonical Silver lookups, and those joins remain
partial because the semantic table is not the complete activity inventory.

Registry row ``episode360`` is ``in_flight`` (``implementationBlueprint:
docs/blueprints/episode360.md``); this provider is the WS-D read surface that
row was waiting on. It follows the outcome360 fail-isolated contract: a missing
store degrades sections to typed ``missing``/``empty`` and never raises, so the
plane stays up when the episode store is empty or unavailable.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional, Protocol
from urllib.parse import quote
from uuid import UUID

from shared.backend_interpretation.primitives import EpisodeRecord, OutcomeTruthRecord
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
    "stages": "Journey stage observations",
}

_JOURNEY_VERSION_SOURCE = (
    "services/api/journeys/measurement/repositories/journey_repo.py:journey_versions"
)
_JOURNEY_STEP_SOURCE = (
    "services/api/journeys/measurement/repositories/journey_step_repo.py:journey_steps"
)
_JOURNEY_TOUCHPOINT_SOURCE = (
    "services/api/journeys/measurement/repositories/touchpoint_repo.py:silver_campaign_touchpoint_facts"
)
_JOURNEY_CONVERSION_SOURCE = (
    "services/api/journeys/measurement/repositories/conversion_repo.py:canonical_conversions"
)
_EPISODE_RECORD_SOURCE = "shared.backend_interpretation.stores.EpisodeStore"
_EPISODE_OBSERVATION_SOURCE = "semantic_intelligence.silver_semantic_observations"
_EPISODE_OUTCOME_TRUTH_SOURCE = "shared.backend_interpretation.stores.OutcomeTruthStore"
_EPISODE_AGENT_HANDOFF_GAP_REASON = (
    "episode_records_and_observations_do_not_reference_canonical_agent_execution_or_handoff_id"
)
_EPISODE_CONVERSION_DEFINITION_REFS = frozenset(
    {"campaign_conversion", "journey_completion"}
)
_JOURNEY_STEP_CAP = 200
_JOURNEY_TOUCHPOINT_CAP = 200
_JOURNEY_CONVERSION_CAP = 100
_JOURNEY_AGENT_ACTIVITY_CAP = 200
_JOURNEY_TOUCHPOINT_READ_CONCURRENCY = 8
_EPISODE_PAGE_DEFAULT = 50
_EPISODE_SUBJECT_RELATIONSHIP_CAP = 100
_EPISODE_OBSERVATION_CAP = 200
_EPISODE_OUTCOME_CAP = 100
_GRAPH_LEDGER_SOURCE = "graph_mutation_ledger"
_JOURNEY_REQUIRED_SLOT_IDS = (
    "journey_summary",
    "stages",
    "episodes",
    "touchpoints",
    "agent_interventions",
    "communications",
    "dropoffs",
    "conversions",
    "attribution",
    "recommended_actions",
    "evidence_trace",
)


@dataclass(frozen=True)
class Journey360Read:
    """One tenant-bound current journey version and a bounded step page."""

    journey: Optional[dict[str, Any]]
    steps: list[dict[str, Any]]
    available: bool
    complete: bool
    reason: Optional[str] = None


@dataclass(frozen=True)
class JourneyTouchpointRead:
    """Bounded exact-ID read of touchpoints named by one current journey version."""

    requested_ids: tuple[str, ...] = ()
    rows: tuple[dict[str, Any], ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = ()
    state: str = "unknown"
    warnings: tuple[str, ...] = ()
    missing_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class JourneyConversionRead:
    """Canonical conversions referenced by one exact current journey version."""

    requested_ids: tuple[str, ...] = ()
    rows: tuple[dict[str, Any], ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = ()
    state: str = "unknown"
    warnings: tuple[str, ...] = ()
    truncated: bool = False


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
class EpisodeObservationRead:
    """Exact tenant-bound reads for observation IDs recorded by episodes."""

    requested_ids: tuple[str, ...] = ()
    rows: tuple[dict[str, Any], ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = ()
    available: bool = True
    truncated: bool = False
    invalid_records: bool = False
    tenant_mismatch: bool = False
    inactive_records: bool = False
    timestamps_missing: bool = False
    missing_ids: tuple[str, ...] = ()
    read_failed: bool = False

    @property
    def complete(self) -> bool:
        return not (
            not self.available
            or self.truncated
            or self.invalid_records
            or self.tenant_mismatch
            or self.inactive_records
            or self.timestamps_missing
            or self.missing_ids
            or self.read_failed
        )


@dataclass(frozen=True)
class EpisodeOutcomeRead:
    """Exact tenant-bound outcome records referenced by episode rows."""

    requested_ids: tuple[str, ...] = ()
    resolved_ids: tuple[str, ...] = ()
    conversions: tuple[dict[str, Any], ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = ()
    available: bool = True
    truncated: bool = False
    invalid_records: bool = False
    tenant_mismatch: bool = False
    missing_ids: tuple[str, ...] = ()
    missing_evidence_ids: tuple[str, ...] = ()
    read_failed: bool = False
    disabled: bool = False

    @property
    def complete(self) -> bool:
        return not (
            not self.available
            or self.truncated
            or self.invalid_records
            or self.tenant_mismatch
            or self.missing_ids
            or self.missing_evidence_ids
            or self.read_failed
            or self.disabled
        )


class EpisodeOutcomeSource(Protocol):
    """Exact composite-key reader over canonical outcome truth."""

    async def get(self, tenant_id: str, outcome_id: str) -> Any: ...


class EpisodeObservationSource(Protocol):
    """Canonical exact-ID lookup for semantic Silver observation rows."""

    async def find_by_ids(
        self, tenant_id: str, observation_ids: list[str]
    ) -> list[dict[str, Any]]: ...


class RepositoryEpisodeObservationSource:
    """Adapter over the canonical tenant-keyed semantic Silver authority."""

    def __init__(self, *, repository: Any = None) -> None:
        self._repository = repository

    def _observation_repository(self) -> Any:
        if self._repository is None:
            from intelligence.semantic_intelligence.repositories.base_fact_repo import (
                SemanticFactRepository,
            )

            self._repository = SemanticFactRepository("silver_semantic_observations")
        return self._repository

    async def find_by_ids(
        self, tenant_id: str, observation_ids: list[str]
    ) -> list[dict[str, Any]]:
        return await self._observation_repository().find_by_ids(tenant_id, observation_ids)


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


class JourneyTouchpointSource(Protocol):
    """Tenant-scoped exact read from the canonical touchpoint authority."""

    async def get(self, tenant_id: str, touchpoint_id: str) -> Optional[dict[str, Any]]: ...


class JourneyConversionSource(Protocol):
    """Tenant-scoped exact read from the canonical conversion authority."""

    async def get(self, tenant_id: str, conversion_id: str) -> Optional[dict[str, Any]]: ...


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


class RepositoryJourneyTouchpointSource:
    """Adapter over the tenant-keyed canonical TouchpointRepository read."""

    def __init__(self, *, repository: Any = None) -> None:
        self._repository = repository

    def _touchpoint_repository(self) -> Any:
        if self._repository is None:
            from journeys.measurement.repositories.touchpoint_repo import TouchpointRepository

            self._repository = TouchpointRepository()
        return self._repository

    async def get(self, tenant_id: str, touchpoint_id: str) -> Optional[dict[str, Any]]:
        row = await self._touchpoint_repository().get(tenant_id, touchpoint_id)
        return _as_mapping(row)


class RepositoryJourneyConversionSource:
    """Adapter over canonical conversion IDs recorded on a journey version."""

    def __init__(self, *, repository: Any = None) -> None:
        self._repository = repository

    async def get(self, tenant_id: str, conversion_id: str) -> Optional[dict[str, Any]]:
        if self._repository is None:
            from journeys.measurement.repositories.conversion_repo import ConversionRepository

            self._repository = ConversionRepository()
        row = await self._repository.get(tenant_id, conversion_id)
        return _as_mapping(row)


class Episode360Provider:
    """The ``episode360`` intelligence projection provider (read_only)."""

    projection_id = "episode360"
    contract_version = INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION

    def __init__(
        self,
        episode_store: Optional[EpisodeStore] = None,
        journey_source: Optional[Journey360Source] = None,
        touchpoint_source: Optional[JourneyTouchpointSource] = None,
        conversion_source: Optional[JourneyConversionSource] = None,
        subject_relationship_reader: Optional[EpisodeSubjectRelationshipReader] = None,
        observation_source: Optional[EpisodeObservationSource] = None,
        outcome_source: Optional[EpisodeOutcomeSource] = None,
    ) -> None:
        """``episode_store`` may be injected (tests); defaults to the durable
        :class:`EpisodeStore` (WS-D item 2). Observation rows default to the
        tenant-keyed semantic Silver authority and may also be injected."""
        self._episode_store = episode_store
        self._journey_source = journey_source
        self._touchpoint_source = touchpoint_source
        self._conversion_source = conversion_source
        self._observation_source = observation_source
        self._outcome_source = outcome_source
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

    async def _load_episode_observations(
        self, tenant_id: str, episodes: list[EpisodeRecord]
    ) -> EpisodeObservationRead:
        """Resolve only observation IDs explicitly recorded by these episodes.

        The association is taken from the canonical EpisodeRecord and each fact
        is read with the authenticated tenant plus its exact observation ID.
        The semantic Silver table is one observation authority, so even a full
        match remains partial coverage of the broader episode event inventory.
        """
        requested_ids = _journey_ordered_values(
            [observation_id for episode in episodes for observation_id in episode.observation_ids]
        )
        truncated = len(requested_ids) > _EPISODE_OBSERVATION_CAP
        bounded_ids = requested_ids[:_EPISODE_OBSERVATION_CAP]
        if not bounded_ids:
            return EpisodeObservationRead(
                requested_ids=tuple(requested_ids),
                available=True,
                truncated=truncated,
            )

        source = self._observation_source or RepositoryEpisodeObservationSource()
        try:
            raw_rows = await source.find_by_ids(tenant_id, bounded_ids)
        except Exception:  # noqa: BLE001 - source observation authority stays isolated
            return EpisodeObservationRead(
                requested_ids=tuple(requested_ids),
                available=False,
                truncated=truncated,
                missing_ids=tuple(bounded_ids),
                read_failed=True,
            )
        if not isinstance(raw_rows, list):
            return EpisodeObservationRead(
                requested_ids=tuple(requested_ids),
                available=False,
                truncated=truncated,
                missing_ids=tuple(bounded_ids),
                invalid_records=True,
            )

        requested_set = set(bounded_ids)
        rows_by_id: dict[str, dict[str, Any]] = {}
        seen_ids: set[str] = set()
        invalid_ids: set[str] = set()
        tenant_mismatch = False
        inactive_records = False
        timestamps_missing = False
        for value in raw_rows:
            row = _as_mapping(value)
            if row is None:
                invalid_ids.add("")
                continue
            record_id = _journey_text(row.get("record_id"))
            observation_id = _journey_text(row.get("observation_id"))
            if row.get("tenant_id") != tenant_id:
                tenant_mismatch = True
                if record_id in requested_set:
                    invalid_ids.add(record_id)
                continue
            if (
                record_id is None
                or observation_id is None
                or record_id != observation_id
                or record_id not in requested_set
            ):
                invalid_ids.add(record_id or observation_id or "")
                continue
            if record_id in seen_ids:
                invalid_ids.add(record_id)
                rows_by_id.pop(record_id, None)
                continue
            seen_ids.add(record_id)
            status = _journey_text(row.get("status"))
            if status not in {"classified", "partial"}:
                inactive_records = True
                continue
            rows_by_id[record_id] = row
            if (
                _journey_timestamp(row.get("processed_at"))
                or _journey_timestamp(row.get("occurred_at"))
            ) is None:
                timestamps_missing = True

        for invalid_id in invalid_ids:
            if invalid_id in rows_by_id:
                rows_by_id.pop(invalid_id, None)
        missing_ids = [value for value in bounded_ids if value not in rows_by_id]
        ordered_rows = [rows_by_id[value] for value in bounded_ids if value in rows_by_id]
        evidence_refs = [
            ref
            for row in ordered_rows
            if (ref := _episode_observation_ref(tenant_id, row)) is not None
        ]
        return EpisodeObservationRead(
            requested_ids=tuple(requested_ids),
            rows=tuple(ordered_rows),
            evidence_refs=tuple(evidence_refs),
            available=True,
            truncated=truncated,
            invalid_records=bool(invalid_ids),
            tenant_mismatch=tenant_mismatch,
            inactive_records=inactive_records,
            timestamps_missing=timestamps_missing,
            missing_ids=tuple(missing_ids),
        )

    async def _load_episode_outcomes(
        self, tenant_id: str, episodes: list[EpisodeRecord]
    ) -> EpisodeOutcomeRead:
        """Resolve only canonical outcomes explicitly referenced by episodes.

        ``outcome_ids`` are not treated as conversion IDs. Each exact ID is
        looked up in the tenant-keyed canonical outcome truth store, then only
        outcomes with a registered conversion definition are emitted. The
        episode reference set is incomplete evidence of the broader conversion
        inventory, so this join can only produce a partial slot.
        """
        episode_ids_by_outcome: dict[str, list[str]] = {}
        invalid_references = False
        for episode in episodes:
            episode_seen: set[str] = set()
            for raw_id in episode.outcome_ids:
                outcome_id = _journey_text(raw_id)
                if outcome_id is None:
                    invalid_references = True
                    continue
                if outcome_id in episode_seen:
                    invalid_references = True
                    continue
                episode_seen.add(outcome_id)
                episode_ids_by_outcome.setdefault(outcome_id, []).append(episode.episode_id)

        requested_ids = list(episode_ids_by_outcome)
        truncated = len(requested_ids) > _EPISODE_OUTCOME_CAP
        bounded_ids = requested_ids[:_EPISODE_OUTCOME_CAP]
        if not bounded_ids:
            return EpisodeOutcomeRead(
                available=True,
                invalid_records=invalid_references,
            )

        source = self._outcome_source
        if source is None:
            try:
                from shared.backend_interpretation.flags import outcome_truth_store_enabled

                if not outcome_truth_store_enabled():
                    return EpisodeOutcomeRead(
                        requested_ids=tuple(requested_ids),
                        available=False,
                        truncated=truncated,
                        invalid_records=invalid_references,
                        disabled=True,
                    )
                from shared.backend_interpretation.stores import OutcomeTruthStore

                source = OutcomeTruthStore()
            except Exception:  # noqa: BLE001 - optional authority stays unknown
                return EpisodeOutcomeRead(
                    requested_ids=tuple(requested_ids),
                    available=False,
                    truncated=truncated,
                    invalid_records=invalid_references,
                    read_failed=True,
                )

        semaphore = asyncio.Semaphore(_JOURNEY_TOUCHPOINT_READ_CONCURRENCY)

        async def read_one(outcome_id: str) -> tuple[str, Optional[dict[str, Any]], bool]:
            async with semaphore:
                try:
                    raw = await source.get(tenant_id, outcome_id)
                except Exception:  # noqa: BLE001 - exact authority failures stay unknown
                    return outcome_id, None, True
            return outcome_id, _as_mapping(raw), False

        results = await asyncio.gather(*(read_one(value) for value in bounded_ids))
        missing_ids: list[str] = []
        missing_evidence_ids: list[str] = []
        resolved_ids: list[str] = []
        conversions: list[dict[str, Any]] = []
        evidence_refs: list[EvidenceRef] = []
        tenant_mismatch = False
        read_failed = False
        invalid_records = invalid_references

        for outcome_id, row, failed in results:
            if failed:
                read_failed = True
                continue
            if row is None:
                missing_ids.append(outcome_id)
                continue
            try:
                canonical_outcome = OutcomeTruthRecord.model_validate(row)
            except Exception:  # noqa: BLE001 - malformed canonical rows stay unknown
                invalid_records = True
                continue
            row = canonical_outcome.model_dump(mode="json")
            if row.get("tenant_id") != tenant_id:
                tenant_mismatch = True
                continue
            if _journey_text(row.get("outcome_id")) != outcome_id:
                invalid_records = True
                continue

            resolved_ids.append(outcome_id)
            outcome_refs: list[EvidenceRef] = []
            raw_refs = row.get("evidence_refs")
            if not isinstance(raw_refs, list):
                raw_refs = []
            for raw_ref in raw_refs:
                try:
                    ref = EvidenceRef.model_validate(raw_ref)
                except Exception:  # noqa: BLE001 - malformed source lineage is omitted
                    invalid_records = True
                    continue
                if ref.id and ref.source:
                    outcome_refs.append(ref)
            outcome_refs = _dedupe_evidence_refs(outcome_refs)
            if not outcome_refs:
                missing_evidence_ids.append(outcome_id)
                continue
            evidence_refs.extend(outcome_refs)

            definition_ref = _journey_text(row.get("definition_ref"))
            if definition_ref not in _EPISODE_CONVERSION_DEFINITION_REFS:
                continue
            conversions.append(
                {
                    "outcomeId": outcome_id,
                    "episodeIds": episode_ids_by_outcome[outcome_id],
                    "conversionType": definition_ref,
                    "outcomeState": _journey_text(row.get("state")),
                    "claimType": _journey_text(row.get("claim_type")),
                    "occurredAt": (
                        _journey_timestamp(row.get("achieved_at"))
                        or _journey_timestamp(row.get("observed_at"))
                    ),
                    "evidenceRefs": [
                        ref.model_dump(mode="json", exclude_none=True)
                        for ref in outcome_refs
                    ],
                }
            )

        return EpisodeOutcomeRead(
            requested_ids=tuple(requested_ids),
            resolved_ids=tuple(resolved_ids),
            conversions=tuple(conversions),
            evidence_refs=tuple(_dedupe_evidence_refs(evidence_refs)),
            available=True,
            truncated=truncated,
            invalid_records=invalid_records,
            tenant_mismatch=tenant_mismatch,
            missing_ids=tuple(missing_ids),
            missing_evidence_ids=tuple(missing_evidence_ids),
            read_failed=read_failed,
        )

    async def _load_journey_touchpoints(
        self,
        tenant_id: str,
        journey: dict[str, Any],
    ) -> JourneyTouchpointRead:
        raw_ids = journey.get("touchpoint_ids")
        reference_list_available = isinstance(raw_ids, (list, tuple))
        touchpoint_ids = _journey_ordered_values(raw_ids) if reference_list_available else []
        endpoint_reference_mismatch = False
        for field in ("entry_touchpoint_id", "exit_touchpoint_id"):
            touchpoint_id = _journey_text(journey.get(field))
            if touchpoint_id is not None and touchpoint_id not in touchpoint_ids:
                endpoint_reference_mismatch = reference_list_available
                touchpoint_ids.append(touchpoint_id)
        if not touchpoint_ids:
            if reference_list_available:
                return JourneyTouchpointRead(state="empty")
            return JourneyTouchpointRead(
                state="unknown",
                warnings=("journey_touchpoint_reference_list_unavailable",),
            )

        truncated = len(touchpoint_ids) > _JOURNEY_TOUCHPOINT_CAP
        requested_ids = touchpoint_ids[:_JOURNEY_TOUCHPOINT_CAP]
        source = self._touchpoint_source or RepositoryJourneyTouchpointSource()
        semaphore = asyncio.Semaphore(_JOURNEY_TOUCHPOINT_READ_CONCURRENCY)

        async def read_one(touchpoint_id: str) -> tuple[str, Optional[dict[str, Any]], bool]:
            async with semaphore:
                try:
                    value = await source.get(tenant_id, touchpoint_id)
                except Exception:  # noqa: BLE001 - exact row failure remains unknown
                    return touchpoint_id, None, True
            return touchpoint_id, _as_mapping(value), False

        results = await asyncio.gather(*(read_one(value) for value in requested_ids))
        rows: list[dict[str, Any]] = []
        missing_ids: list[str] = []
        read_failed = False
        scope_mismatch = False
        evidence_refs: list[EvidenceRef] = []
        for touchpoint_id, row, failed in results:
            if failed:
                read_failed = True
                continue
            if row is None:
                missing_ids.append(touchpoint_id)
                continue
            if (
                str(row.get("tenant_id") or "") != tenant_id
                or _journey_text(row.get("touchpoint_id")) != touchpoint_id
            ):
                scope_mismatch = True
                missing_ids.append(touchpoint_id)
                continue
            evidence = _journey_touchpoint_ref(row)
            if evidence is None:
                missing_ids.append(touchpoint_id)
                continue
            rows.append(row)
            evidence_refs.append(evidence)

        warnings: list[str] = []
        if not reference_list_available:
            warnings.append("journey_touchpoint_reference_list_unavailable")
        if endpoint_reference_mismatch:
            warnings.append("journey_touchpoint_endpoint_reference_not_in_list")
        if truncated:
            warnings.append("journey_touchpoint_read_truncated")
        if read_failed:
            warnings.append("journey_touchpoint_source_unavailable")
        if missing_ids:
            warnings.append("journey_touchpoint_rows_missing")
        if scope_mismatch:
            warnings.append("journey_touchpoint_scope_mismatch")
        complete = not warnings and len(rows) == len(touchpoint_ids)
        state = "available" if complete else "degraded" if rows else "unknown"
        return JourneyTouchpointRead(
            requested_ids=tuple(touchpoint_ids),
            rows=tuple(rows),
            evidence_refs=tuple(evidence_refs),
            state=state,
            warnings=tuple(warnings),
            missing_ids=tuple(missing_ids),
        )

    async def _load_journey_conversions(
        self, tenant_id: str, journey: dict[str, Any]
    ) -> JourneyConversionRead:
        raw_ids = journey.get("conversion_ids")
        if not isinstance(raw_ids, (list, tuple)):
            return JourneyConversionRead(
                warnings=("journey_conversion_reference_list_unavailable",)
            )
        conversion_ids = _journey_ordered_values(raw_ids)
        if not conversion_ids:
            return JourneyConversionRead(state="empty")
        truncated = len(conversion_ids) > _JOURNEY_CONVERSION_CAP
        source = self._conversion_source or RepositoryJourneyConversionSource()
        semaphore = asyncio.Semaphore(_JOURNEY_TOUCHPOINT_READ_CONCURRENCY)

        async def read_one(conversion_id: str) -> tuple[Optional[dict[str, Any]], bool]:
            async with semaphore:
                try:
                    row = await source.get(tenant_id, conversion_id)
                except Exception:  # noqa: BLE001 - exact authority failure remains unknown
                    return None, True
            return _as_mapping(row), False

        results = await asyncio.gather(
            *(read_one(value) for value in conversion_ids[:_JOURNEY_CONVERSION_CAP])
        )
        rows: list[dict[str, Any]] = []
        evidence_refs: list[EvidenceRef] = []
        warnings: list[str] = []
        if truncated:
            warnings.append("journey_conversion_read_truncated")
        for conversion_id, (row, failed) in zip(conversion_ids, results):
            if failed:
                warnings.append("journey_conversion_authority_unavailable")
                continue
            if row is None:
                warnings.append("journey_conversion_row_missing")
                continue
            if (
                str(row.get("tenant_id") or "") != tenant_id
                or _journey_text(row.get("conversion_id")) != conversion_id
            ):
                warnings.append("journey_conversion_scope_mismatch")
                continue
            evidence = _journey_conversion_ref(row)
            if evidence is None:
                warnings.append("journey_conversion_evidence_missing")
                continue
            rows.append(row)
            evidence_refs.append(evidence)
        state = (
            "available"
            if rows and not warnings and len(rows) == len(conversion_ids)
            else "degraded"
            if rows
            else "unknown"
        )
        return JourneyConversionRead(
            requested_ids=tuple(conversion_ids),
            rows=tuple(rows),
            evidence_refs=tuple(evidence_refs),
            state=state,
            warnings=tuple(dict.fromkeys(warnings)),
            truncated=truncated,
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
        observation_read = await self._load_episode_observations(request.tenantId, episodes)
        outcome_read = await self._load_episode_outcomes(request.tenantId, episodes)
        warnings: list[str] = []
        if read.truncated:
            warnings.append("episode_page_truncated")
        if read.invalid_records:
            warnings.append("episode_page_contains_invalid_rows")
        if read.tenant_mismatch:
            warnings.append("episode_page_tenant_mismatch")
        if read.read_failed:
            warnings.append("episode_store_read_unavailable")
        if observation_read.read_failed:
            warnings.append("episode_observation_authority_unavailable")
        if observation_read.truncated:
            warnings.append("episode_observation_read_truncated")
        if observation_read.invalid_records:
            warnings.append("episode_observation_rows_invalid_or_ambiguous")
        if observation_read.tenant_mismatch:
            warnings.append("episode_observation_tenant_mismatch")
        if observation_read.inactive_records:
            warnings.append("episode_observation_non_active_rows_omitted")
        if observation_read.timestamps_missing:
            warnings.append("episode_observation_timestamps_missing_or_invalid")
        if observation_read.missing_ids:
            warnings.append("episode_observation_references_unresolved")
        if outcome_read.disabled:
            warnings.append("episode_outcome_truth_store_disabled")
        if outcome_read.read_failed:
            warnings.append("episode_outcome_truth_authority_unavailable")
        if outcome_read.truncated:
            warnings.append("episode_outcome_reference_read_truncated")
        if outcome_read.invalid_records:
            warnings.append("episode_outcome_rows_invalid_or_ambiguous")
        if outcome_read.tenant_mismatch:
            warnings.append("episode_outcome_tenant_scope_mismatch")
        if outcome_read.missing_ids:
            warnings.append("episode_outcome_references_unresolved")
        if outcome_read.missing_evidence_ids:
            warnings.append("episode_outcome_lineage_unavailable")
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
            request,
            episodes,
            availability,
            warnings,
            subject_relationship_context=subject_relationship_context,
            observation_read=observation_read,
            outcome_read=outcome_read,
        )
        section_by_id = {section.id: section for section in sections}
        sections = [section_by_id[section_id] for section_id in _EPISODE360_SECTIONS]
        claims = self._build_claims(request, episodes, outcome_read)
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
        # The repository query is tenant-scoped and filters to is_current=TRUE,
        # but injected adapters and alternate persistence implementations must
        # still prove the same contract in the returned row. Do not label a
        # stale or marker-less version as the current Journey360 subject.
        if journey.get("is_current") is not True:
            return _journey_unavailable_result(
                request,
                context,
                generated_at,
                temporal_mode,
                "journey_current_version_not_proven",
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
        # The reader was asked for one look-ahead row. Count truncation before
        # dropping mismatched rows; otherwise an out-of-scope row at the page
        # boundary could hide that the canonical journey still has later steps.
        truncated = len(raw_steps) > page_limit
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
        if len(step_refs) != len(rendered_steps):
            warnings.append("journey_step_evidence_missing")
        step_inventory_complete = (
            steps_available
            and not truncated
            and not scope_mismatch
            and len(step_refs) == len(rendered_steps)
            and cursor is None
            and after is None
            and before is None
        )

        agent_interventions = _journey_agent_intervention_context(
            journey=journey,
            steps=rendered_steps,
            journey_ref=journey_ref,
            steps_available=steps_available,
            step_inventory_complete=step_inventory_complete,
            scope_mismatch=scope_mismatch,
        )
        warnings.extend(agent_interventions["warnings"])

        journey_episodes = _journey_episode_context(request)
        warnings.extend(journey_episodes["warnings"])
        journey_touchpoints = _journey_touchpoint_context(
            await self._load_journey_touchpoints(request.tenantId, journey)
        )
        warnings.extend(journey_touchpoints["warnings"])
        journey_conversions = _journey_conversion_context(
            await self._load_journey_conversions(request.tenantId, journey)
        )
        warnings.extend(journey_conversions["warnings"])

        sections = _build_journey_sections(
            request=request,
            journey=journey,
            steps=rendered_steps,
            journey_ref=journey_ref,
            step_refs=step_refs,
            steps_available=steps_available,
            step_inventory_complete=step_inventory_complete,
            truncated=truncated,
            warnings=warnings,
            agent_interventions=agent_interventions,
            episode_context=journey_episodes,
            touchpoint_context=journey_touchpoints,
            conversion_context=journey_conversions,
        )
        if request.includeSections is not None:
            wanted = set(request.includeSections)
            sections = [section for section in sections if section.id in wanted]
        claims = (
            _build_journey_claims(
                request,
                journey,
                rendered_steps,
                journey_ref,
                journey_touchpoints["claims"],
                journey_conversions["claims"],
                agent_interventions["claims"],
            )
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
        request: ProjectionRequest,
        episodes: list[EpisodeRecord],
        availability: str,
        warnings: Optional[list[str]] = None,
        *,
        subject_relationship_context: Optional[dict[str, Any]] = None,
        observation_read: Optional[EpisodeObservationRead] = None,
        outcome_read: Optional[EpisodeOutcomeRead] = None,
    ) -> list[ProjectionSection]:
        complete = availability in {"available", "empty"}
        observation_read = observation_read or EpisodeObservationRead(available=False)
        outcome_read = outcome_read or EpisodeOutcomeRead(available=False, read_failed=True)
        conversion_context = _episode_conversion_context(outcome_read)
        by_kind = _kind_counts(episodes)
        by_status = _status_distribution(episodes)
        episode_evidence = _collect_evidence(episodes)
        evidence = _dedupe_evidence_refs(episode_evidence + list(observation_read.evidence_refs))
        evidence_complete = complete and observation_read.complete
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
            "evidenceCount": len(evidence) if evidence_complete else None,
            "observedEvidenceCount": len(evidence),
            "coverage": "complete_for_recorded_references" if evidence_complete else "partial",
            "evidenceTrace": {
                "state": (
                    "available"
                    if evidence and evidence_complete
                    else "degraded"
                    if evidence
                    else "unknown"
                ),
                "coverage": "complete_for_recorded_references"
                if evidence_complete
                else "partial"
                if evidence
                else "unknown",
                "evidenceRefs": [ref.model_dump() for ref in evidence],
                "sourceProvenanceState": "partial" if episodes else "unknown",
                "reason": (
                    _episode_observation_read_reason(observation_read)
                    if episodes and not observation_read.complete
                    else "episode_and_exact_tenant_observation_refs_joined_broader_source_provenance_unresolved"
                    if episodes
                    else "episode_evidence_unavailable"
                ),
            },
            "observationReferences": {
                "state": _episode_observation_read_state(observation_read),
                "coverage": "recorded_episode_ids_only",
                "requestedCount": len(observation_read.requested_ids),
                "resolvedCount": len(observation_read.rows),
                "observations": [
                    _episode_observation_view(request.tenantId, row)
                    for row in observation_read.rows
                ],
                "evidenceRefs": [ref.model_dump() for ref in observation_read.evidence_refs],
                "reason": _episode_observation_read_reason(observation_read),
                "freshness": {
                    "state": "unknown",
                    "evaluation": "not_performed",
                    "reason": "semantic_observation_source_watermark_not_available",
                },
                "policy": {
                    "state": "unknown",
                    "evaluation": "not_performed",
                    "reason": "observation_policy_disposition_not_evaluated_by_episode_projection",
                },
            },
            "episodeSubjects": [
                {
                    "episodeId": episode.episode_id,
                    "subject": {"kind": episode.subject.kind, "id": episode.subject.id},
                }
                for episode in episodes
            ],
            "freshness": {
                "state": "unknown",
                "evaluation": "not_performed",
                "reason": "episode_store_freshness_watermark_not_available",
            },
            "policy": {
                "state": "unknown",
                "evaluation": "not_performed",
                "reason": "episode_policy_evaluation_not_performed_by_projection",
            },
            "provenance": {
                "state": "partial" if episodes else "unknown",
                "authority": _EPISODE_RECORD_SOURCE,
                "reason": "episode_source_event_and_lens_provenance_not_joined",
            },
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
                id="stages",
                state="unknown",
                title=_SECTION_TITLES["stages"],
                content=None,
                warnings=["typed_journey_stage_authority_requires_journey_subject"],
            ),
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
                    "episodes": [_episode_view(episode) for episode in episodes],
                    "episodeSummary": (
                        _episode_view(episodes[0])
                        if request.subject.kind == "episode" and len(episodes) == 1
                        else None
                    ),
                    "primarySubject": (
                        _episode_participant(episodes[0])
                        if len(episodes) == 1
                        else None
                    ),
                    "participants": _episode_participant_context(request, episodes),
                    "evidenceRefs": [ref.model_dump() for ref in evidence],
                    "requiredSlotCoverage": (
                        _episode_required_slot_coverage(
                            request,
                            episodes,
                            availability=availability,
                            evidence_refs=evidence,
                            observation_read=observation_read,
                            outcome_read=outcome_read,
                        )
                        if request.subject.kind == "episode"
                        else None
                    ),
                    "freshness": {
                        "state": "unknown",
                        "evaluation": "not_performed",
                        "reason": "episode_store_freshness_watermark_not_available",
                    },
                    "policy": {
                        "state": "unknown",
                        "evaluation": "not_performed",
                        "reason": "episode_policy_evaluation_not_performed_by_projection",
                    },
                    "provenance": {
                        "state": "partial" if episodes else "unknown",
                        "authority": _EPISODE_RECORD_SOURCE,
                        "joinedAuthorities": [_EPISODE_RECORD_SOURCE, _EPISODE_OBSERVATION_SOURCE],
                        "reason": (
                            _episode_observation_read_reason(observation_read)
                            if episodes and not observation_read.complete
                            else "semantic_observation_refs_joined; broader_activity_and_lens_provenance_unresolved"
                            if episodes
                            else "episode_source_unavailable"
                        ),
                    },
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
                    "episodeStatuses": [
                        {
                            "episodeId": episode.episode_id,
                            "status": episode.status,
                            "evidenceRefs": [
                                ref.model_dump() for ref in _episode_evidence_refs(episode)
                            ],
                        }
                        for episode in episodes
                    ],
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
                state=(
                    "degraded"
                    if episodes
                    else "unknown"
                    if not episodes and availability not in {"empty", "missing"}
                    else availability
                ),
                title=_SECTION_TITLES["interactions"],
                content={
                    "interactionCount": interaction_count if complete else None,
                    "observedInteractionCount": interaction_count,
                    "resolvedObservationCount": len(observation_read.rows),
                    "observationIds": _flatten(e.observation_ids for e in episodes),
                    "observationReferences": {
                        "state": _episode_observation_read_state(observation_read),
                        "coverage": "recorded_episode_ids_only",
                        "requestedCount": len(observation_read.requested_ids),
                        "resolvedCount": len(observation_read.rows),
                        "observationIds": _flatten(e.observation_ids for e in episodes),
                        "observations": [
                            _episode_observation_view(request.tenantId, row)
                            for row in observation_read.rows
                        ],
                        "evidenceRefs": [
                            ref.model_dump() for ref in observation_read.evidence_refs
                        ],
                        "reason": _episode_observation_read_reason(observation_read),
                        "freshness": {
                            "state": "unknown",
                            "evaluation": "not_performed",
                            "reason": "semantic_observation_source_watermark_not_available",
                        },
                        "policy": {
                            "state": "unknown",
                            "evaluation": "not_performed",
                            "reason": "observation_policy_disposition_not_evaluated_by_episode_projection",
                        },
                    },
                    "sessionContext": _episode_session_context(request, episodes),
                    "touchpointContext": {
                        **_unknown_episode_slot(
                            "episode_record_contract_has_no_touchpoint_references"
                        ),
                        "touchpoints": [],
                    },
                    "communicationContext": {
                        **_unknown_episode_slot(
                            "episode_record_contract_has_no_communication_references"
                        ),
                        "communications": [],
                    },
                    "agentHandoffs": {
                        **_unknown_episode_slot(_EPISODE_AGENT_HANDOFF_GAP_REASON),
                        "handoffs": [],
                    },
                    "policy": {
                        "state": "unknown",
                        "evaluation": "not_performed",
                        "reason": "episode_policy_evaluation_not_performed_by_projection",
                    },
                    "coverage": "partial" if episodes else availability,
                },
                warnings=warnings or None,
            ),
            ProjectionSection(
                id="outcomes",
                state=(
                    "degraded"
                    if episodes
                    else "unknown"
                    if not episodes and availability not in {"empty", "missing"}
                    else availability
                ),
                title=_SECTION_TITLES["outcomes"],
                content={
                    "outcomeCount": outcome_count if complete else None,
                    "observedOutcomeCount": outcome_count,
                    "outcomeIds": _flatten(e.outcome_ids for e in episodes),
                    "recordedOutcomeReferences": [
                        {
                            "episodeId": episode.episode_id,
                            "outcomeIds": list(episode.outcome_ids),
                            "evidenceRefs": [
                                ref.model_dump() for ref in _episode_evidence_refs(episode)
                            ],
                            "outcomeTruthState": "unknown",
                        }
                        for episode in episodes
                        if episode.outcome_ids
                    ],
                    "conversionEvents": {
                        **conversion_context,
                    },
                    "attributionLinks": {
                        **_unknown_episode_slot("episode_attribution_authority_not_joined"),
                        "links": [],
                    },
                    "riskFlags": {
                        **_unknown_episode_slot("episode_risk_authority_not_joined"),
                        "flags": [],
                    },
                    "coverage": "partial" if episodes else availability,
                },
                warnings=warnings or None,
            ),
            ProjectionSection(
                id="timeline",
                state=(
                    "degraded"
                    if episodes
                    else "unknown"
                    if availability not in {"empty", "missing"}
                    else availability
                ),
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
                            "observationIds": list(e.observation_ids),
                            "observations": _episode_observation_views_for(
                                request.tenantId, e, observation_read
                            ),
                            "evidenceRefs": [
                                ref.model_dump()
                                for ref in _dedupe_evidence_refs(
                                    _episode_evidence_refs(e)
                                    + _episode_observation_refs_for(e, observation_read)
                                )
                            ],
                        }
                        for e in sorted(
                            episodes,
                            key=lambda e: e.occurred_from or e.created_at or "",
                        )
                    ],
                    "observationTimeline": sorted(
                        [
                            _episode_observation_view(request.tenantId, row)
                            for row in observation_read.rows
                        ],
                        key=lambda row: (
                            row.get("occurredAt") or "9999-12-31T23:59:59+00:00",
                            row["observationId"],
                        ),
                    ),
                    "observationCoverage": {
                        "state": _episode_observation_read_state(observation_read),
                        "coverage": "recorded_episode_ids_only",
                        "requestedCount": len(observation_read.requested_ids),
                        "resolvedCount": len(observation_read.rows),
                        "evidenceRefs": [
                            ref.model_dump() for ref in observation_read.evidence_refs
                        ],
                        "reason": _episode_observation_read_reason(observation_read),
                        "freshness": {
                            "state": "unknown",
                            "evaluation": "not_performed",
                            "reason": "semantic_observation_source_watermark_not_available",
                        },
                        "policy": {
                            "state": "unknown",
                            "evaluation": "not_performed",
                            "reason": "observation_policy_disposition_not_evaluated_by_episode_projection",
                        },
                    },
                    "coverage": "partial" if episodes else availability,
                },
                warnings=warnings or None,
            ),
        ]

    def _build_claims(
        self,
        request: ProjectionRequest,
        episodes: list[EpisodeRecord],
        outcome_read: Optional[EpisodeOutcomeRead] = None,
    ) -> list[ClaimEnvelope]:
        claims: list[ClaimEnvelope] = []
        for episode in episodes:
            evidence_refs = _episode_evidence_refs(episode)
            claims.append(
                ClaimEnvelope(
                    id=f"episode.{episode.episode_id}.span",
                    kind="episode",
                    subject=request.subject,
                    evidenceRefs=evidence_refs,
                    claims=[
                        f"episode {episode.episode_id!r} ({episode.kind!r}) "
                        f"spans {episode.observation_ids and len(episode.observation_ids) or 0} "
                        f"observations and is {episode.status}"
                    ],
                    claimState=EpistemicStatus.OBSERVED,
                    domainSlotIds=["episode_summary", "timeline", "evidence_trace"],
                )
            )
            claims.append(
                ClaimEnvelope(
                    id=f"episode.{episode.episode_id}.primary-subject",
                    kind="episode_primary_subject",
                    subject=request.subject,
                    evidenceRefs=evidence_refs,
                    claims=[
                        f"episode {episode.episode_id!r} records primary subject "
                        f"{episode.subject.kind!r}:{episode.subject.id!r}"
                    ],
                    claimState=EpistemicStatus.OBSERVED,
                    domainSlotIds=["episode_summary", "evidence_trace"],
                )
            )
            if episode.subject.kind in {"user", "agent"}:
                claims.append(
                    ClaimEnvelope(
                        id=f"episode.{episode.episode_id}.participant:{episode.subject.kind}:{episode.subject.id}",
                        kind="episode_primary_participant",
                        subject=request.subject,
                        evidenceRefs=evidence_refs,
                        claims=[
                            f"episode {episode.episode_id!r} names "
                            f"{episode.subject.kind!r}:{episode.subject.id!r} "
                            "as its primary subject; other participants are unresolved"
                        ],
                        claimState=EpistemicStatus.OBSERVED,
                        domainSlotIds=["participants", "evidence_trace"],
                    )
                )
            if episode.subject.kind == "session":
                claims.append(
                    ClaimEnvelope(
                        id=f"episode.{episode.episode_id}.session:{episode.subject.id}",
                        kind="episode_primary_session",
                        subject=request.subject,
                        evidenceRefs=evidence_refs,
                        claims=[
                            f"episode {episode.episode_id!r} records primary session "
                            f"{episode.subject.id!r}; session inventory completeness is unknown"
                        ],
                        claimState=EpistemicStatus.OBSERVED,
                        domainSlotIds=["sessions", "evidence_trace"],
                    )
                )
            if episode.observation_ids:
                claims.append(
                    ClaimEnvelope(
                        id=f"episode.{episode.episode_id}.observation-references",
                        kind="episode_observation_references",
                        subject=request.subject,
                        evidenceRefs=evidence_refs,
                        claims=[
                            f"episode record references {len(episode.observation_ids)} "
                            "observation identifiers; observation records are not joined"
                        ],
                        claimState=EpistemicStatus.OBSERVED,
                        domainSlotIds=["timeline", "evidence_trace"],
                    )
                )
        for conversion in (outcome_read or EpisodeOutcomeRead()).conversions:
            evidence_refs: list[EvidenceRef] = []
            raw_refs = conversion.get("evidenceRefs")
            if isinstance(raw_refs, list):
                for raw_ref in raw_refs:
                    try:
                        evidence_refs.append(EvidenceRef.model_validate(raw_ref))
                    except Exception:  # noqa: BLE001 - invalid claim evidence is omitted
                        continue
            if not evidence_refs:
                continue
            outcome_id = str(conversion["outcomeId"])
            claim_type = conversion.get("claimType")
            claim_state = (
                EpistemicStatus.OBSERVED
                if claim_type == "observed"
                else EpistemicStatus.DERIVED
                if claim_type == "derived"
                else EpistemicStatus.UNKNOWN
            )
            claims.append(
                ClaimEnvelope(
                    id=f"episode360.conversion:{quote(outcome_id, safe='')}",
                    kind="episode_referenced_canonical_conversion_outcome",
                    subject=request.subject,
                    evidenceRefs=evidence_refs,
                    claims=[
                        f"Episode record(s) {', '.join(conversion['episodeIds'])} reference canonical outcome {outcome_id!r}, whose registered definition is {conversion['conversionType']!r}; this does not establish complete conversion coverage or causal attribution."
                    ],
                    claimState=claim_state,
                    domainSlotIds=["conversion_events", "evidence_trace"],
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
            content=(
                {"requiredSlotCoverage": _unknown_journey_slot_coverage(reason)}
                if section_id == "summary"
                else None
            ),
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
            content=(
                {
                    "requiredSlotCoverage": _unknown_journey_slot_coverage(
                        "tenant_scoped_journey_not_found",
                        journey_summary_state="missing",
                    )
                }
                if section_id == "summary"
                else None
            ),
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


def _journey_episode_context(
    request: ProjectionRequest,
) -> dict[str, Any]:
    """Keep the episode slot unresolved until a typed journey association exists.

    EpisodeRecord subjects are constrained to graph EntityRef kinds and do
    not carry a journey id. Joining by profile id or coincident opaque IDs
    would attach unrelated episodes to a journey, so this provider does not
    scan EpisodeStore for journey subjects.
    """
    return {
        "state": "unknown",
        "coverage": "unknown",
        "requestedSubject": {"kind": request.subject.kind, "id": request.subject.id},
        "episodeCount": None,
        "observedEpisodeCount": None,
        "episodes": [],
        "evidenceRefs": [],
        "warnings": ["journey_episode_subject_binding_unavailable"],
        "reason": "episode_record_contract_has_no_typed_journey_subject_reference",
    }


def _journey_agent_intervention_context(
    *,
    journey: dict[str, Any],
    steps: list[dict[str, Any]],
    journey_ref: EvidenceRef,
    steps_available: bool,
    step_inventory_complete: bool,
    scope_mismatch: bool,
) -> dict[str, Any]:
    """Resolve only agent activity IDs explicitly recorded on this journey version.

    Journey compiler versions carry ``agent_activity_ids`` from canonical
    activity rows. A returned step contributes only when its exact
    ``activity_id`` matches one of those IDs and the persisted step classifies
    it as the ``agent`` activity family. Actor labels and nearby metadata do
    not create a join or prove agent identity/authority.
    """
    raw_ids = journey.get("agent_activity_ids")
    if not isinstance(raw_ids, (list, tuple)):
        return {
            "state": "unknown",
            "coverage": "unknown",
            "reason": "journey_version_agent_activity_reference_list_unavailable",
            "recordedActivityIds": [],
            "resolvedActivityIds": [],
            "unresolvedActivityIds": [],
            "evidenceRefs": [],
            "activities": [],
            "claims": [],
            "warnings": ["journey_agent_activity_reference_list_unavailable"],
        }

    recorded_ids: list[str] = []
    malformed_reference = False
    duplicate_reference = False
    seen_ids: set[str] = set()
    for value in raw_ids:
        if not isinstance(value, (str, UUID)):
            malformed_reference = True
            continue
        activity_id = _journey_text(value)
        if activity_id is None:
            malformed_reference = True
            continue
        if activity_id in seen_ids:
            duplicate_reference = True
            continue
        seen_ids.add(activity_id)
        recorded_ids.append(activity_id)

    truncated = len(recorded_ids) > _JOURNEY_AGENT_ACTIVITY_CAP
    bounded_ids = recorded_ids[:_JOURNEY_AGENT_ACTIVITY_CAP]
    requested = set(bounded_ids)
    rows_by_activity_id: dict[str, list[dict[str, Any]]] = {}
    for row in steps:
        activity_id = _journey_text(row.get("activity_id"))
        if activity_id in requested:
            rows_by_activity_id.setdefault(activity_id, []).append(row)

    warnings: list[str] = []
    if malformed_reference:
        warnings.append("journey_agent_activity_reference_invalid")
    if duplicate_reference:
        warnings.append("journey_agent_activity_reference_duplicated")
    if truncated:
        warnings.append("journey_agent_activity_references_truncated")
    if not steps_available:
        warnings.append("journey_step_authority_unavailable")
    if scope_mismatch:
        warnings.append("unscoped_journey_step_rows_dropped")
    if bounded_ids and not step_inventory_complete:
        warnings.append("journey_agent_activity_step_inventory_incomplete")

    activities: list[dict[str, Any]] = []
    claims: list[tuple[str, EvidenceRef]] = []
    resolved_ids: list[str] = []
    unresolved_ids: list[str] = list(recorded_ids[_JOURNEY_AGENT_ACTIVITY_CAP:])
    ambiguous = False
    family_mismatch = False
    restricted = False
    for activity_id in bounded_ids:
        matches = rows_by_activity_id.get(activity_id, [])
        if len(matches) != 1:
            if len(matches) > 1:
                ambiguous = True
            unresolved_ids.append(activity_id)
            continue
        row = matches[0]
        if _journey_text(row.get("activity_family")) != "agent":
            family_mismatch = True
            unresolved_ids.append(activity_id)
            continue
        if _journey_text(row.get("activity_status")) in {
            "tombstoned",
            "deleted",
            "consent_restricted",
        }:
            restricted = True
            unresolved_ids.append(activity_id)
            continue
        step_evidence = _journey_step_ref(row)
        if step_evidence is None:
            unresolved_ids.append(activity_id)
            continue

        resolved_ids.append(activity_id)
        claims.append((activity_id, step_evidence))
        activities.append(
            {
                "activity": {
                    "stepId": _journey_text(row.get("step_id")),
                    "agentId": _journey_text(row.get("agent_id")),
                    "actorType": _journey_text(row.get("actor_type")),
                    "activityId": activity_id,
                    "activityType": _journey_text(row.get("activity_type")),
                    "occurredAt": _journey_timestamp(row.get("occurred_at")),
                    "evidenceRefs": [step_evidence.model_dump(mode="json", exclude_none=True)],
                },
                "evidenceRefs": [step_evidence.model_dump(mode="json", exclude_none=True)],
            }
        )

    if ambiguous:
        warnings.append("journey_agent_activity_step_reference_ambiguous")
    if family_mismatch:
        warnings.append("journey_agent_activity_step_family_mismatch")
    if restricted:
        warnings.append("journey_agent_activity_step_restricted")
    if unresolved_ids and not any(
        warning in warnings
        for warning in (
            "journey_agent_activity_reference_invalid",
            "journey_agent_activity_reference_duplicated",
            "journey_agent_activity_references_truncated",
            "journey_agent_activity_step_reference_ambiguous",
            "journey_agent_activity_step_family_mismatch",
            "journey_agent_activity_step_restricted",
            "journey_agent_activity_step_inventory_incomplete",
            "journey_step_authority_unavailable",
            "unscoped_journey_step_rows_dropped",
        )
    ):
        warnings.append("journey_agent_activity_step_reference_unresolved")

    evidence_refs: list[EvidenceRef] = [journey_ref]
    for _, evidence in claims:
        if all(
            existing.id != evidence.id or existing.source != evidence.source
            for existing in evidence_refs
        ):
            evidence_refs.append(evidence)

    if not recorded_ids and step_inventory_complete and not warnings:
        state = "empty"
        coverage = "explicit_current_version_reference_set_empty"
        reason = "current_journey_version_records_no_agent_activity_references"
        evidence_refs = [journey_ref]
    elif resolved_ids:
        state = "degraded"
        coverage = (
            "exact_activity_id_references_resolved"
            if not unresolved_ids and not warnings
            else "partial_exact_activity_id_references_resolved"
        )
        reason = "exact_journey_agent_activity_references_resolved_actor_authority_not_joined"
    else:
        state = "unknown"
        coverage = "unknown"
        reason = (
            warnings[0]
            if warnings
            else "journey_agent_activity_references_not_resolved_in_current_step_page"
            if recorded_ids
            else "journey_step_inventory_incomplete_for_agent_activity"
        )

    return {
        "state": state,
        "coverage": coverage,
        "reason": reason,
        "recordedActivityIds": recorded_ids,
        "resolvedActivityIds": resolved_ids,
        "unresolvedActivityIds": list(dict.fromkeys(unresolved_ids)),
        "evidenceRefs": [ref.model_dump(mode="json", exclude_none=True) for ref in evidence_refs],
        "activities": activities,
        "claims": claims,
        "warnings": warnings,
    }


def _journey_touchpoint_context(read: JourneyTouchpointRead) -> dict[str, Any]:
    touchpoints = [
        _journey_touchpoint_view(row)
        for row in read.rows
        if _journey_touchpoint_ref(row) is not None
    ]
    return {
        "state": read.state,
        "coverage": "complete"
        if read.state in {"available", "empty"}
        else "partial"
        if touchpoints
        else "unknown",
        "touchpointIds": list(read.requested_ids),
        "touchpoints": touchpoints,
        "count": len(touchpoints) if read.state in {"available", "empty"} else None,
        "observedCount": len(touchpoints),
        "evidenceRefs": [ref.model_dump(mode="json") for ref in read.evidence_refs],
        "missingTouchpointIds": list(read.missing_ids),
        "warnings": list(read.warnings),
        "reason": (
            "touchpoints_resolved_from_journey_version_references"
            if read.state == "available"
            else "journey_version_records_no_touchpoint_references"
            if read.state == "empty"
            else read.warnings[0] if read.warnings else "journey_touchpoint_read_unresolved"
        ),
        # Internal evidence pairs feed observed claims; only the public fields
        # above are copied into ProjectionSection content.
        "claims": [
            (_journey_text(row.get("touchpoint_id")) or "", ref)
            for row in read.rows
            if (ref := _journey_touchpoint_ref(row)) is not None
        ],
    }


def _journey_conversion_context(read: JourneyConversionRead) -> dict[str, Any]:
    conversions = [
        {
            "conversionId": _journey_text(row.get("conversion_id")),
            "conversionType": _journey_text(row.get("conversion_type")),
            "conversionStatus": _journey_text(row.get("conversion_status")),
            "occurredAt": _journey_timestamp(row.get("occurred_at")),
            "evidenceRefs": [ref.model_dump(mode="json")],
        }
        for row, ref in zip(read.rows, read.evidence_refs)
    ]
    return {
        "state": read.state,
        "coverage": "referenced_ids_only",
        "conversionIds": list(read.requested_ids),
        "conversions": conversions,
        "count": len(conversions) if read.state in {"available", "empty"} else None,
        "observedCount": len(conversions),
        "evidenceRefs": [ref.model_dump(mode="json") for ref in read.evidence_refs],
        "warnings": list(read.warnings),
        "reason": (
            "canonical_conversions_resolved_from_journey_version_references"
            if read.state == "available"
            else "current_journey_version_has_no_conversion_references"
            if read.state == "empty"
            else read.warnings[0] if read.warnings else "journey_conversion_read_unresolved"
        ),
        "claims": [
            (_journey_text(row.get("conversion_id")) or "", ref)
            for row, ref in zip(read.rows, read.evidence_refs)
        ],
    }


def _journey_ordered_values(value: Any) -> list[str]:
    """Return stable, non-empty string IDs without inventing joins."""
    if not isinstance(value, (list, tuple)):
        return []
    values: list[str] = []
    seen: set[str] = set()
    for item in value:
        normalized = _journey_text(item)
        if normalized is not None and normalized not in seen:
            seen.add(normalized)
            values.append(normalized)
    return values


def _journey_touchpoint_ref(row: dict[str, Any]) -> Optional[EvidenceRef]:
    touchpoint_id = _journey_text(row.get("touchpoint_id"))
    if touchpoint_id is None:
        return None
    return EvidenceRef(
        id=touchpoint_id,
        type="event",
        source=_JOURNEY_TOUCHPOINT_SOURCE,
        observedAt=_journey_timestamp(row.get("occurred_at")),
        uri=f"store://silver_campaign_touchpoint_facts/{touchpoint_id}",
    )


def _journey_conversion_ref(row: dict[str, Any]) -> Optional[EvidenceRef]:
    conversion_id = _journey_text(row.get("conversion_id"))
    observed_at = _journey_timestamp(row.get("observed_at") or row.get("occurred_at"))
    if conversion_id is None or observed_at is None:
        return None
    return EvidenceRef(
        id=conversion_id,
        type="event",
        source=_JOURNEY_CONVERSION_SOURCE,
        observedAt=observed_at,
        uri=f"store://canonical_conversions/{conversion_id}",
    )


def _journey_touchpoint_view(row: dict[str, Any]) -> dict[str, Any]:
    """Expose only journey-relevant classification fields from a touchpoint."""
    evidence = _journey_touchpoint_ref(row)
    eligible = row.get("attribution_eligible")
    return {
        "touchpointId": _journey_text(row.get("touchpoint_id")),
        "occurredAt": _journey_timestamp(row.get("occurred_at")),
        "touchpointType": _journey_text(row.get("touchpoint_type")),
        "interactionType": _journey_text(row.get("interaction_type")),
        "channel": _journey_text(row.get("channel")),
        "source": _journey_text(row.get("source")),
        "medium": _journey_text(row.get("medium")),
        "sourceClass": _journey_text(row.get("source_class")),
        "trafficOrigin": _journey_text(row.get("traffic_origin")),
        "economicClass": _journey_text(row.get("economic_class")),
        "channelFamily": _journey_text(row.get("channel_family")),
        "entryMethod": _journey_text(row.get("entry_method")),
        "proofLevel": _journey_text(row.get("proof_level")),
        "actorType": _journey_text(row.get("actor_type")),
        "journeyRole": _journey_text(row.get("journey_role")),
        "campaignId": _journey_text(row.get("campaign_id")),
        "agentId": _journey_text(row.get("agent_id")),
        "attributionEligible": eligible if isinstance(eligible, bool) else None,
        "verificationLevel": _journey_text(row.get("verification_level")),
        "evidenceRefs": [evidence.model_dump(mode="json")] if evidence is not None else [],
    }


def _build_journey_sections(
    *,
    request: ProjectionRequest,
    journey: dict[str, Any],
    steps: list[dict[str, Any]],
    journey_ref: EvidenceRef,
    step_refs: list[EvidenceRef],
    steps_available: bool,
    step_inventory_complete: bool,
    truncated: bool,
    warnings: list[str],
    agent_interventions: dict[str, Any],
    episode_context: dict[str, Any],
    touchpoint_context: dict[str, Any],
    conversion_context: dict[str, Any],
) -> list[ProjectionSection]:
    time_window = {
        "from": request.timeRange.from_ if request.timeRange is not None else None,
        "to": request.timeRange.to if request.timeRange is not None else None,
    }
    step_state = (
        "unknown"
        if not steps_available
        else "degraded"
        if truncated
        or "unscoped_journey_step_rows_dropped" in warnings
        or "journey_step_evidence_missing" in warnings
        else "available"
        if steps
        else "empty"
    )
    summary_state = "degraded" if step_state in {"unknown", "degraded"} else "available"
    step_evidence = [ref.model_dump(mode="json") for ref in step_refs]
    version_evidence = [journey_ref.model_dump(mode="json")]
    journey_view = _journey_view(journey)
    timeline = [_journey_step_view(row) for row in steps]
    stage_context = _journey_stage_context(
        steps=steps,
        step_refs=step_refs,
        steps_available=steps_available,
        step_inventory_complete=step_inventory_complete,
    )
    episode_evidence = episode_context["evidenceRefs"]
    touchpoint_evidence = touchpoint_context["evidenceRefs"]
    conversion_evidence = conversion_context["evidenceRefs"]
    required_slot_coverage = _journey_required_slot_coverage(
        journey=journey,
        steps=steps,
        journey_ref=journey_ref,
        step_refs=step_refs,
        steps_available=steps_available,
        step_inventory_complete=step_inventory_complete,
        stage_context=stage_context,
        agent_interventions=agent_interventions,
        touchpoint_context=touchpoint_context,
        conversion_context=conversion_context,
    )
    complete_evidence = step_state not in {"unknown", "degraded"} and episode_context[
        "state"
    ] not in {"unknown", "degraded"} and touchpoint_context["state"] in {
        "available",
        "empty",
    }
    outcome_state = conversion_context["state"]
    outcome_content = {
        "recordedConversionIds": conversion_context["conversionIds"],
        "conversionTruthState": conversion_context["state"],
        "conversions": conversion_context["conversions"],
        "attributionState": "unknown",
        "journeyVersionEvidenceRefs": version_evidence,
        "evidenceRefs": version_evidence + conversion_evidence,
        "reason": conversion_context["reason"],
    }
    output: dict[str, ProjectionSection] = {
        "stages": ProjectionSection(
            id="stages",
            state=(
                "degraded"
                if stage_context["state"] in {"partial", "degraded"}
                else "empty"
                if stage_context["state"] == "empty"
                else "unknown"
            ),
            title=_SECTION_TITLES["stages"],
            content=stage_context,
            canonicalAuthorityRefs=["journeys"],
            warnings=[stage_context["reason"]]
            if isinstance(stage_context.get("reason"), str)
            else None,
        ),
        "summary": ProjectionSection(
            id="summary",
            state=summary_state,
            title=_SECTION_TITLES["summary"],
            content={
                "journey": journey_view,
                "stepCount": len(steps) if step_state in {"available", "empty"} else None,
                "observedStepCount": len(steps),
                "touchpointCount": touchpoint_context["count"],
                "observedTouchpointCount": touchpoint_context["observedCount"],
                "timeWindow": time_window,
                "evidenceRefs": version_evidence,
                "continuity": {
                    "state": "unknown",
                    "identityVersion": journey_view["identityVersion"],
                    "reason": "journey_identity_continuity_not_evaluated",
                },
                "freshness": {
                    "state": "unknown",
                    "computedAt": journey_view["computedAt"],
                    "dataWatermark": journey_view["dataWatermark"],
                    "evaluation": "not_performed",
                    "reason": "journey_freshness_window_not_evaluated",
                },
                "policy": {
                    "state": "unknown",
                    "evaluation": "not_performed",
                    "reason": "journey_policy_evaluation_not_performed_by_projection",
                },
                "provenance": {
                    "state": "partial",
                    "authority": "journey_versions_and_journey_steps",
                    "reason": "source_provenance_authority_not_joined",
                },
                "requiredSlotCoverage": required_slot_coverage,
            },
            warnings=warnings or None,
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
            state="degraded" if not complete_evidence else "available",
            title=_SECTION_TITLES["evidence"],
            content={
                "journeyVersion": version_evidence[0],
                "journeySteps": step_evidence,
                "sourceEventIds": _journey_values(journey.get("event_ids")),
                "evidenceRefs": version_evidence + step_evidence + touchpoint_evidence + conversion_evidence,
                "rawStepEvidenceSummaryIncluded": False,
                "journeyEpisodes": episode_evidence,
                "journeyTouchpoints": touchpoint_evidence,
                "coverage": "complete" if complete_evidence else "partial",
            },
            warnings=sorted(
                set(warnings + episode_context["warnings"] + touchpoint_context["warnings"])
            )
            or None,
        ),
        "episode_context": ProjectionSection(
            id="episode_context",
            state=episode_context["state"],
            title=_SECTION_TITLES["episode_context"],
            content=episode_context,
            warnings=episode_context["warnings"] or None,
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
                    "agentActivities": [
                        item["activity"] for item in agent_interventions["activities"]
                    ],
                    "agentActivityCoverage": agent_interventions["coverage"],
                    "agentInterventionReferences": {
                        key: value
                        for key, value in agent_interventions.items()
                        if key not in {"activities", "claims", "warnings"}
                    },
                    "evidenceRefs": step_evidence,
                }
                if steps_available
                else None
            ),
            warnings=warnings or None,
        ),
        "outcomes": ProjectionSection(
            id="outcomes",
            state=outcome_state,
            title=_SECTION_TITLES["outcomes"],
            content=outcome_content,
            warnings=conversion_context["warnings"] or ["journey_attribution_authority_not_joined"],
        ),
        "timeline": ProjectionSection(
            id="timeline",
            state=step_state,
            title=_SECTION_TITLES["timeline"],
            content=(
                {
                    "journey": journey_view,
                    "timeline": timeline,
                    "stageObservations": stage_context,
                    "evidenceRefs": (
                        version_evidence
                        + step_evidence
                        + episode_evidence
                        + touchpoint_evidence
                    ),
                    "touchpointReferences": {
                        **{
                            key: value
                            for key, value in touchpoint_context.items()
                            if key != "claims"
                        },
                        "entryTouchpointId": journey_view["entryTouchpointId"],
                        "exitTouchpointId": journey_view["exitTouchpointId"],
                        "journeyVersionEvidenceRefs": version_evidence,
                    },
                }
                if steps_available
                else None
            ),
            warnings=warnings or None,
        ),
    }
    return [output[section_id] for section_id in _EPISODE360_SECTIONS]


def _journey_stage_context(
    *,
    steps: list[dict[str, Any]],
    step_refs: list[EvidenceRef],
    steps_available: bool,
    step_inventory_complete: bool,
) -> dict[str, Any]:
    """Project explicit journey-role markers without inventing stage boundaries.

    ``journey_role`` is persisted on canonical journey steps by the source
    classifier. It can identify observed markers such as entry, campaign, or
    handoff, but it is not a typed stage definition or a completeness claim.
    Each marker therefore remains attached to its exact journey step and the
    slot stays partial until a governed stage taxonomy/authority exists.
    """
    refs_by_step_id = {ref.id: ref for ref in step_refs}
    observations: list[dict[str, Any]] = []
    missing_evidence = False
    invalid_role = False
    for row in steps:
        role = _journey_text(row.get("journey_role"))
        if role is None:
            continue
        # Persisted journey roles are labels rather than an open-ended payload.
        # Bound their projection size while marking malformed rows explicitly.
        if len(role) > 128:
            invalid_role = True
            continue
        step_id = _journey_text(row.get("step_id"))
        evidence = refs_by_step_id.get(step_id or "")
        if evidence is None:
            missing_evidence = True
            continue
        observations.append(
            {
                "stepId": step_id,
                "position": _journey_int(row.get("step_position"), 0),
                "journeyRole": role,
                "occurredAt": _journey_timestamp(row.get("occurred_at")),
                "activityFamily": _journey_text(row.get("activity_family")),
                "activityType": _journey_text(row.get("activity_type")),
                "evidenceRefs": [evidence.model_dump(mode="json", exclude_none=True)],
            }
        )

    observed_refs = [
        evidence
        for observation in observations
        for evidence in observation["evidenceRefs"]
    ]
    complete_refs = [ref.model_dump(mode="json", exclude_none=True) for ref in step_refs]
    if not steps_available:
        state = "unknown"
        coverage = "unknown"
        reason = "journey_step_authority_unavailable"
    elif invalid_role or missing_evidence:
        state = "degraded"
        coverage = "partial"
        reason = "journey_role_marker_invalid_or_missing_exact_step_evidence"
    elif observations:
        state = "partial"
        coverage = "observed_role_markers"
        reason = (
            "explicit_journey_role_markers_loaded_from_exact_current_version_steps;"
            "stage_taxonomy_and_stage_completeness_are_unresolved"
        )
    elif step_inventory_complete:
        state = "empty"
        coverage = "complete_for_explicit_role_markers"
        reason = "complete_current_journey_step_inventory_has_no_explicit_role_markers"
    else:
        state = "unknown"
        coverage = "unknown"
        reason = "incomplete_journey_step_inventory_cannot_establish_role_marker_absence"

    return {
        "state": state,
        "coverage": coverage,
        "reason": reason,
        "authority": "tenant_scoped_current_journey_version_steps",
        "stageTaxonomyState": "unknown",
        "inventoryComplete": step_inventory_complete,
        "stageObservations": observations,
        # A complete empty step inventory is evidence only that this source
        # recorded no explicit role markers; it does not prove no stages exist.
        "evidenceRefs": observed_refs if observations else complete_refs if step_inventory_complete else [],
    }


def _unknown_journey_slot_coverage(
    reason: str,
    *,
    journey_summary_state: str = "unknown",
) -> dict[str, dict[str, Any]]:
    """Give every blueprint slot an explicit state when the exact journey read fails."""
    return {
        slot_id: {
            "state": journey_summary_state if slot_id == "journey_summary" else "unknown",
            "coverage": "unknown",
            "reason": reason if slot_id == "journey_summary" else "journey_version_unavailable",
            "evidenceRefs": [],
        }
        for slot_id in _JOURNEY_REQUIRED_SLOT_IDS
    }


def _journey_required_slot_coverage(
    *,
    journey: dict[str, Any],
    steps: list[dict[str, Any]],
    journey_ref: EvidenceRef,
    step_refs: list[EvidenceRef],
    steps_available: bool,
    step_inventory_complete: bool,
    stage_context: dict[str, Any],
    agent_interventions: dict[str, Any],
    touchpoint_context: dict[str, Any],
    conversion_context: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Expose SSOT slot states using only tenant/version-bound canonical evidence.

    This records supported row coverage without inferring stage transitions,
    episode associations, communication joins, conversions, attribution, or
    actions from opaque IDs and neighboring projections.
    """
    version_evidence = [journey_ref.model_dump(mode="json", exclude_none=True)]
    step_evidence = [ref.model_dump(mode="json", exclude_none=True) for ref in step_refs]
    touchpoint_evidence = [
        ref for ref in touchpoint_context.get("evidenceRefs", []) if isinstance(ref, dict)
    ]
    conversion_evidence = [
        ref for ref in conversion_context.get("evidenceRefs", []) if isinstance(ref, dict)
    ]
    all_evidence = version_evidence + step_evidence + touchpoint_evidence + conversion_evidence

    touchpoint_state = touchpoint_context.get("state")
    if touchpoint_state == "available":
        touchpoint_slot = {
            "state": "available",
            "coverage": "complete",
            "reason": "exact_tenant_touchpoints_resolved_from_current_journey_version",
            "evidenceRefs": touchpoint_evidence,
        }
    elif touchpoint_state == "empty":
        touchpoint_slot = {
            "state": "empty",
            "coverage": "complete",
            "reason": "current_journey_version_has_no_touchpoint_references",
            "evidenceRefs": version_evidence,
        }
    elif touchpoint_state == "degraded" and touchpoint_evidence:
        touchpoint_slot = {
            "state": "degraded",
            "coverage": "partial",
            "reason": touchpoint_context.get("reason") or "journey_touchpoint_read_incomplete",
            "evidenceRefs": touchpoint_evidence,
        }
    else:
        touchpoint_slot = {
            "state": "unknown",
            "coverage": "unknown",
            "reason": touchpoint_context.get("reason") or "journey_touchpoint_read_incomplete",
            "evidenceRefs": [],
        }

    conversion_slot = {
        "state": conversion_context["state"],
        "coverage": conversion_context["coverage"],
        "reason": conversion_context["reason"],
        "evidenceRefs": version_evidence + conversion_evidence,
    }

    return {
        "journey_summary": {
            "state": "available",
            "coverage": "persisted_version_fields",
            "reason": "tenant_scoped_current_journey_version_loaded_by_exact_key",
            "evidenceRefs": version_evidence,
        },
        "stages": {
            "state": stage_context["state"],
            "coverage": stage_context["coverage"],
            "reason": stage_context["reason"],
            "evidenceRefs": stage_context["evidenceRefs"],
        },
        "episodes": {
            "state": "unknown",
            "coverage": "unknown",
            "reason": "episode_record_contract_has_no_typed_journey_subject_reference",
            "evidenceRefs": [],
        },
        "touchpoints": touchpoint_slot,
        "agent_interventions": {
            "state": agent_interventions["state"],
            "coverage": agent_interventions["coverage"],
            "reason": agent_interventions["reason"],
            "recordedActivityIds": agent_interventions["recordedActivityIds"],
            "resolvedActivityIds": agent_interventions["resolvedActivityIds"],
            "unresolvedActivityIds": agent_interventions["unresolvedActivityIds"],
            "evidenceRefs": agent_interventions["evidenceRefs"],
        },
        "communications": {
            "state": "unknown",
            "coverage": "unknown",
            "reason": "journey_communication_fact_join_not_implemented",
            "evidenceRefs": [],
        },
        "dropoffs": {
            "state": "unknown",
            "coverage": "unknown",
            "reason": "journey_dropoff_authority_not_available",
            "evidenceRefs": [],
        },
        "conversions": conversion_slot,
        "attribution": {
            "state": "unknown",
            "coverage": "unknown",
            "reason": "immutable_attribution_credit_authority_not_joined",
            "evidenceRefs": [],
        },
        "recommended_actions": {
            "state": "unknown",
            "coverage": "unknown",
            "reason": "journey_action_recommendation_authority_not_available",
            "evidenceRefs": [],
        },
        "evidence_trace": {
            "state": "degraded",
            "coverage": "partial",
            "reason": "journey_version_and_linked_row_evidence_available_source_provenance_not_joined",
            "evidenceRefs": all_evidence,
        },
    }


def _build_journey_claims(
    request: ProjectionRequest,
    journey: dict[str, Any],
    steps: list[dict[str, Any]],
    journey_ref: EvidenceRef,
    touchpoint_claims: list[tuple[str, EvidenceRef]],
    conversion_claims: list[tuple[str, EvidenceRef]],
    agent_intervention_claims: list[tuple[str, EvidenceRef]],
) -> list[ClaimEnvelope]:
    journey_id = _journey_text(journey.get("journey_id")) or request.subject.id
    version_id = _journey_text(journey.get("journey_version_id")) or journey_id
    version_slots = _journey_slot_ids_for_sections({"summary", "state", "evidence"})
    step_slots = _journey_slot_ids_for_sections({"timeline", "interactions", "evidence"})
    stage_slots = _journey_slot_ids_for_sections({"stages"})
    touchpoint_slots = _journey_slot_ids_for_sections({"timeline", "evidence"})
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
    for row in steps:
        step_id = _journey_text(row.get("step_id"))
        evidence = _journey_step_ref(row)
        if not step_id or evidence is None:
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
    for activity_id, step_evidence in agent_intervention_claims:
        if len(claims) >= 301:
            break
        claims.append(
            ClaimEnvelope(
                id=f"episode360:{journey_id}:{version_id}:agent-activity:{activity_id}",
                kind="journey_agent_activity_reference",
                subject=request.subject,
                evidenceRefs=[journey_ref, step_evidence],
                claims=[
                    f"Current journey version explicitly references agent activity {activity_id!r}.",
                    "An exact current-version journey step records that activity in the agent family.",
                    "Agent identity, authority, and intervention outcome are not evaluated by this reference join.",
                ],
                claimState=EpistemicStatus.OBSERVED,
                domainSlotIds=["agent_interventions"],
            )
        )
    if stage_slots:
        for row in steps:
            if len(claims) >= 201:
                break
            step_id = _journey_text(row.get("step_id"))
            role = _journey_text(row.get("journey_role"))
            evidence = _journey_step_ref(row)
            if (
                not step_id
                or role is None
                or len(role) > 128
                or evidence is None
            ):
                continue
            claims.append(
                ClaimEnvelope(
                    id=f"episode360:{journey_id}:{version_id}:stage-marker:{step_id}",
                    kind="explicit_journey_role_marker",
                    subject=request.subject,
                    evidenceRefs=[evidence],
                    claims=[
                        f"Persisted journey step {step_id!r} has explicit journey_role marker "
                        f"{role!r}; stage taxonomy and stage completeness remain unknown."
                    ],
                    claimState=EpistemicStatus.OBSERVED,
                    domainSlotIds=stage_slots,
                )
            )
    for touchpoint_id, evidence in touchpoint_claims:
        if len(claims) >= 101:
            break
        claims.append(
            ClaimEnvelope(
                id=f"episode360:{journey_id}:{version_id}:touchpoint:{touchpoint_id}",
                kind="server_recorded_journey_touchpoint",
                subject=request.subject,
                evidenceRefs=[journey_ref, evidence],
                claims=["A persisted tenant-scoped touchpoint is referenced by this journey version."],
                claimState=EpistemicStatus.OBSERVED,
                domainSlotIds=touchpoint_slots,
            )
        )
    for conversion_id, evidence in conversion_claims:
        if len(claims) >= 201:
            break
        claims.append(
            ClaimEnvelope(
                id=f"episode360:{journey_id}:{version_id}:conversion:{conversion_id}",
                kind="canonical_journey_conversion",
                subject=request.subject,
                evidenceRefs=[journey_ref, evidence],
                claims=["A canonical conversion is referenced by this current journey version."],
                claimState=EpistemicStatus.OBSERVED,
                domainSlotIds=["conversions"],
            )
        )
    return claims


def _journey_slot_ids_for_sections(section_ids: set[str]) -> list[str]:
    slot_ids: set[str] = set()
    surface = PRODUCT_360_SURFACE_DEFINITIONS.get("journey360")
    if not isinstance(surface, dict) or "journey" not in surface.get("subjectKinds", []):
        return []
    blueprint = surface.get("blueprintContract", {})
    required_slot_ids = set(blueprint.get("requiredSlotIds", [])) if isinstance(blueprint, dict) else set()
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
                if isinstance(slot_id, str) and slot_id in required_slot_ids:
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
        "accountId": _journey_text(row.get("account_id")),
        "organizationId": _journey_text(row.get("organization_id")),
        "walletId": _journey_text(row.get("wallet_id")),
        "agentId": _journey_text(row.get("agent_id")),
        "entryTouchpointId": _journey_text(row.get("entry_touchpoint_id")),
        "exitTouchpointId": _journey_text(row.get("exit_touchpoint_id")),
        "campaignIds": _journey_values(row.get("campaign_ids")),
        "touchpointIds": _journey_values(row.get("touchpoint_ids")),
        "sessionIds": _journey_values(row.get("session_ids")),
        "deviceIds": _journey_values(row.get("device_ids")),
        "channelSequence": _journey_values(row.get("channel_sequence")),
        "conversionIds": _journey_values(row.get("conversion_ids")),
        "eventIds": _journey_values(row.get("event_ids")),
        "agentActivityIds": _journey_values(row.get("agent_activity_ids")),
        "web3ActivityIds": _journey_values(row.get("web3_activity_ids")),
        "x402ActivityIds": _journey_values(row.get("x402_activity_ids")),
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
        "domain": _journey_text(row.get("domain")),
        "appId": _journey_text(row.get("app_id")),
        "dappId": _journey_text(row.get("dapp_id")),
        "transitionType": _journey_text(row.get("transition_type")),
        "actorType": _journey_text(row.get("actor_type")),
        "channel": _journey_text(row.get("channel")),
        "source": _journey_text(row.get("source")),
        "sourceClass": _journey_text(row.get("source_class")),
        "trafficOrigin": _journey_text(row.get("traffic_origin")),
        "economicClass": _journey_text(row.get("economic_class")),
        "channelFamily": _journey_text(row.get("channel_family")),
        "proofLevel": _journey_text(row.get("proof_level")),
        "journeyRole": _journey_text(row.get("journey_role")),
        "campaignId": _journey_text(row.get("campaign_id")),
        "conversionId": _journey_text(row.get("conversion_id")),
        "agentId": _journey_text(row.get("agent_id")),
        "walletId": _journey_text(row.get("wallet_id")),
        "sessionId": _journey_text(row.get("session_id")),
        "deviceId": _journey_text(row.get("device_id")),
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
    seen: set[tuple[str, str, str]] = set()
    refs: list[Any] = []
    for e in episodes:
        for ref in _episode_evidence_refs(e):
            key = (ref.id, ref.type, ref.source)
            if key in seen:
                continue
            seen.add(key)
            refs.append(ref)
    return refs


def _episode_record_ref(episode: EpisodeRecord) -> EvidenceRef:
    episode_id = episode.episode_id
    return EvidenceRef(
        id=episode_id,
        type="entity",
        source=_EPISODE_RECORD_SOURCE,
        observedAt=_journey_timestamp(episode.created_at or episode.occurred_to),
        uri=f"store://episode_records/{quote(episode_id, safe='')}",
    )


def _episode_observation_ref(
    tenant_id: str, row: dict[str, Any]
) -> Optional[EvidenceRef]:
    observation_id = _journey_text(row.get("observation_id"))
    if observation_id is None or row.get("tenant_id") != tenant_id:
        return None
    return EvidenceRef(
        id=observation_id,
        type="event",
        source=_EPISODE_OBSERVATION_SOURCE,
        observedAt=(
            _journey_timestamp(row.get("processed_at"))
            or _journey_timestamp(row.get("occurred_at"))
        ),
        uri=(
            "store://silver_semantic_observations/"
            f"{quote(tenant_id, safe='')}:{quote(observation_id, safe='')}"
        ),
    )


def _episode_observation_view(tenant_id: str, row: dict[str, Any]) -> dict[str, Any]:
    evidence = _episode_observation_ref(tenant_id, row)
    return {
        "observationId": _journey_text(row.get("observation_id")),
        "sourceType": _journey_text(row.get("source_type")),
        "occurredAt": _journey_timestamp(row.get("occurred_at")),
        "recordStatus": _journey_text(row.get("status")),
        "evidenceRefs": [evidence.model_dump()] if evidence is not None else [],
    }


def _episode_observation_views_for(
    tenant_id: str, episode: EpisodeRecord, read: EpisodeObservationRead
) -> list[dict[str, Any]]:
    rows_by_id = {
        _journey_text(row.get("observation_id")): row
        for row in read.rows
        if _journey_text(row.get("observation_id")) is not None
    }
    return [
        _episode_observation_view(tenant_id, rows_by_id[observation_id])
        for observation_id in episode.observation_ids
        if observation_id in rows_by_id
    ]


def _episode_observation_refs_for(
    episode: EpisodeRecord, read: EpisodeObservationRead
) -> list[EvidenceRef]:
    wanted = set(episode.observation_ids)
    return [
        ref
        for ref in read.evidence_refs
        if ref.id in wanted and ref.source == _EPISODE_OBSERVATION_SOURCE
    ]


def _episode_observation_read_state(read: EpisodeObservationRead) -> str:
    if not read.requested_ids:
        return "empty"
    if read.rows and read.complete:
        return "available"
    if read.rows:
        return "degraded"
    return "unknown"


def _episode_observation_read_reason(read: EpisodeObservationRead) -> str:
    if not read.requested_ids:
        return "episode_record_contains_no_observation_references"
    if read.read_failed or not read.available:
        return "semantic_observation_authority_unavailable"
    if read.tenant_mismatch:
        return "semantic_observation_tenant_scope_mismatch"
    if read.invalid_records:
        return "semantic_observation_rows_invalid_or_ambiguous"
    if read.inactive_records:
        return "semantic_observation_non_active_rows_omitted"
    if read.timestamps_missing:
        return "semantic_observation_timestamps_missing_or_invalid"
    if read.truncated:
        return "episode_observation_reference_read_truncated"
    if read.missing_ids:
        return "episode_observation_ids_not_found_in_semantic_silver"
    return "exact_tenant_observation_rows_resolved_recorded_episode_references_only"


def _dedupe_evidence_refs(refs: list[EvidenceRef]) -> list[EvidenceRef]:
    unique: dict[tuple[str, str, str], EvidenceRef] = {}
    for ref in refs:
        if not isinstance(ref, EvidenceRef) or not ref.id or not ref.source:
            continue
        unique.setdefault((ref.id, ref.type, ref.source), ref)
    return list(unique.values())


def _episode_evidence_refs(episode: EpisodeRecord) -> list[EvidenceRef]:
    unique: dict[tuple[str, str, str], EvidenceRef] = {}
    for ref in [_episode_record_ref(episode), *episode.evidence_refs]:
        if not isinstance(ref, EvidenceRef) or not ref.id or not ref.source:
            continue
        unique.setdefault((ref.id, ref.type, ref.source), ref)
    return list(unique.values())


def _episode_view(episode: EpisodeRecord) -> dict[str, Any]:
    return {
        "episodeId": episode.episode_id,
        "kind": episode.kind,
        "status": episode.status,
        "title": episode.title,
        "occurredFrom": episode.occurred_from,
        "occurredTo": episode.occurred_to,
        "subject": {"kind": episode.subject.kind, "id": episode.subject.id},
        "observationIds": list(episode.observation_ids),
        "outcomeIds": list(episode.outcome_ids),
        "modelVersion": episode.model_version,
        "createdAt": _journey_timestamp(episode.created_at),
        "closedAt": episode.closed_at,
        "evidenceRefs": [ref.model_dump() for ref in _episode_evidence_refs(episode)],
    }


def _episode_participant(episode: EpisodeRecord) -> Optional[dict[str, Any]]:
    if episode.subject.kind not in {"user", "agent"}:
        return None
    evidence_refs = [ref.model_dump() for ref in _episode_evidence_refs(episode)]
    return {
        "entity": {"kind": episode.subject.kind, "id": episode.subject.id},
        "role": "primary_subject",
        "coverage": "partial",
        "evidenceRefs": evidence_refs,
        "reason": "episode_record_has_no_additional_participant_inventory",
    }


def _episode_participant_context(
    request: ProjectionRequest,
    episodes: list[EpisodeRecord],
) -> dict[str, Any]:
    if request.subject.kind != "episode" or len(episodes) != 1:
        return _unknown_episode_slot("exact_episode_subject_record_unavailable") | {
            "participants": []
        }
    participant = _episode_participant(episodes[0])
    if participant is None:
        return _unknown_episode_slot("episode_subject_kind_does_not_identify_a_participant") | {
            "participants": []
        }
    return {
        "state": "degraded",
        "coverage": "partial",
        "participants": [participant],
        "count": None,
        "observedCount": 1,
        "reason": "episode_record_has_no_additional_participant_inventory",
    }


def _episode_session_context(
    request: ProjectionRequest,
    episodes: list[EpisodeRecord],
) -> dict[str, Any]:
    if request.subject.kind != "episode" or len(episodes) != 1:
        return _unknown_episode_slot("episode_record_has_no_session_inventory")
    episode = episodes[0]
    if episode.subject.kind != "session":
        return _unknown_episode_slot("episode_record_subject_is_not_a_session")
    return {
        "state": "degraded",
        "coverage": "partial",
        "sessions": [
            {
                "sessionId": episode.subject.id,
                "role": "primary_episode_subject",
                "evidenceRefs": [
                    ref.model_dump() for ref in _episode_evidence_refs(episode)
                ],
            }
        ],
        "count": None,
        "observedCount": 1,
        "reason": "episode_records_one_session_subject_without_session_inventory",
    }


def _unknown_episode_slot(reason: str) -> dict[str, Any]:
    return {"state": "unknown", "coverage": "unknown", "items": [], "reason": reason}


def _episode_conversion_context(
    read: EpisodeOutcomeRead,
) -> dict[str, Any]:
    """Render only conversion outcomes joined through explicit episode IDs."""
    events = list(read.conversions)
    if not read.requested_ids:
        state = "unknown"
        coverage = "unknown"
        reason = "episode_record_has_no_outcome_references"
    elif read.disabled:
        state = "unknown"
        coverage = "unknown"
        reason = "canonical_outcome_truth_store_disabled"
    elif read.read_failed or not read.available:
        state = "degraded" if events else "unknown"
        coverage = "partial" if events else "unknown"
        reason = "canonical_outcome_truth_read_incomplete"
    elif read.tenant_mismatch:
        state = "degraded" if events else "unknown"
        coverage = "partial" if events else "unknown"
        reason = "canonical_outcome_truth_scope_mismatch"
    elif read.invalid_records:
        state = "degraded" if events else "unknown"
        coverage = "partial" if events else "unknown"
        reason = "canonical_outcome_truth_rows_invalid_or_ambiguous"
    elif read.missing_evidence_ids:
        state = "degraded" if events else "unknown"
        coverage = "partial" if events else "unknown"
        reason = "canonical_outcome_truth_lineage_missing"
    elif read.missing_ids:
        state = "degraded" if events else "unknown"
        coverage = "partial" if events else "unknown"
        reason = "episode_outcome_references_not_found_in_canonical_outcome_truth"
    elif read.truncated:
        state = "degraded" if events else "unknown"
        coverage = "partial" if events else "unknown"
        reason = "episode_outcome_reference_read_truncated"
    elif events:
        state = "degraded"
        coverage = "exact_episode_outcome_ids_only"
        reason = "registered_conversion_outcomes_resolved_from_explicit_episode_references"
    else:
        state = "degraded"
        coverage = "exact_episode_outcome_ids_only"
        reason = "episode_outcome_references_resolved_without_registered_conversion_definitions"

    evidence = [ref.model_dump(mode="json", exclude_none=True) for ref in read.evidence_refs]
    return {
        "state": state,
        "coverage": coverage,
        "count": None,
        "observedCount": len(events),
        "requestedOutcomeIds": list(read.requested_ids),
        "resolvedOutcomeIds": list(read.resolved_ids),
        "events": events,
        "evidenceRefs": evidence,
        "reason": reason,
        "freshness": {
            "state": "unknown",
            "evaluation": "not_performed",
            "reason": "canonical_outcome_truth_source_watermark_not_available",
        },
        "policy": {
            "state": "unknown",
            "evaluation": "not_performed",
            "reason": "episode_conversion_outcome_policy_not_evaluated_by_projection",
        },
        "provenance": {
            "state": "partial" if read.resolved_ids else "unknown",
            "authority": _EPISODE_OUTCOME_TRUTH_SOURCE,
            "referenceAuthority": _EPISODE_RECORD_SOURCE,
            "coverage": "episode_record_outcome_ids_only",
            "reason": reason,
        },
    }


def _episode_required_slot_coverage(
    request: ProjectionRequest,
    episodes: list[EpisodeRecord],
    *,
    availability: str,
    evidence_refs: list[EvidenceRef],
    observation_read: EpisodeObservationRead,
    outcome_read: EpisodeOutcomeRead,
) -> dict[str, dict[str, Any]]:
    """Expose the SSOT slot status without promoting partial sources to complete."""
    evidence = [ref.model_dump() for ref in evidence_refs]
    if (
        request.subject.kind != "episode"
        or len(episodes) != 1
        or episodes[0].episode_id != request.subject.id
        or episodes[0].tenant_id != request.tenantId
    ):
        summary_state = "empty" if availability == "empty" else "unknown"
        summary_reason = (
            "tenant_scoped_episode_not_found"
            if availability == "empty"
            else "episode_record_read_incomplete"
        )
        return {
            slot_id: {
                "state": summary_state if slot_id == "episode_summary" else "unknown",
                "coverage": "empty" if summary_state == "empty" and slot_id == "episode_summary" else "unknown",
                "reason": summary_reason
                if slot_id == "episode_summary"
                else "episode_subject_record_unavailable",
                "evidenceRefs": evidence,
            }
            for slot_id in _EPISODE_REQUIRED_SLOT_IDS
        }

    episode = episodes[0]
    subject_evidence = evidence
    participant_state = (
        "degraded" if episode.subject.kind in {"user", "agent"} else "unknown"
    )
    participant_reason = (
        "only_primary_episode_subject_is_recorded"
        if participant_state == "degraded"
        else "episode_subject_kind_does_not_identify_a_participant"
    )
    session_state = "degraded" if episode.subject.kind == "session" else "unknown"
    conversion_context = _episode_conversion_context(outcome_read)
    return {
        "episode_summary": {
            "state": "available",
            "coverage": "complete",
            "reason": "tenant_scoped_episode_record_loaded_by_exact_composite_key",
            "evidenceRefs": subject_evidence,
        },
        "timeline": {
            "state": "degraded",
            "coverage": "partial",
            "reason": _episode_observation_read_reason(observation_read),
            "evidenceRefs": [
                ref.model_dump()
                for ref in _dedupe_evidence_refs(
                    [*evidence_refs, *_episode_observation_refs_for(episode, observation_read)]
                )
            ],
        },
        "participants": {
            "state": participant_state,
            "coverage": "partial" if participant_state == "degraded" else "unknown",
            "reason": participant_reason,
            "evidenceRefs": subject_evidence if participant_state == "degraded" else [],
        },
        "sessions": {
            "state": session_state,
            "coverage": "partial" if session_state == "degraded" else "unknown",
            "reason": (
                "episode_record_names_one_session_without_session_inventory"
                if session_state == "degraded"
                else "episode_record_has_no_session_inventory"
            ),
            "evidenceRefs": subject_evidence if session_state == "degraded" else [],
        },
        "touchpoints": {
            "state": "unknown",
            "coverage": "unknown",
            "reason": "episode_record_contract_has_no_touchpoint_references",
            "evidenceRefs": [],
        },
        "communications": {
            "state": "unknown",
            "coverage": "unknown",
            "reason": "episode_record_contract_has_no_communication_references",
            "evidenceRefs": [],
        },
        "agent_handoffs": {
            "state": "unknown",
            "coverage": "unknown",
            "reason": _EPISODE_AGENT_HANDOFF_GAP_REASON,
            "evidenceRefs": [],
        },
        "conversion_events": {
            "state": conversion_context["state"],
            "coverage": conversion_context["coverage"],
            "reason": conversion_context["reason"],
            "evidenceRefs": conversion_context["evidenceRefs"],
        },
        "attribution_links": {
            "state": "unknown",
            "coverage": "unknown",
            "reason": "episode_attribution_authority_not_joined",
            "evidenceRefs": [],
        },
        "risk_flags": {
            "state": "unknown",
            "coverage": "unknown",
            "reason": "episode_risk_authority_not_joined",
            "evidenceRefs": [],
        },
        "evidence_trace": {
            "state": "degraded",
            "coverage": "partial",
            "reason": (
                _episode_observation_read_reason(observation_read)
                if not observation_read.complete
                else "episode_and_exact_tenant_observation_refs_joined_broader_provenance_unresolved"
            ),
            "evidenceRefs": [
                ref.model_dump()
                for ref in _dedupe_evidence_refs([*evidence_refs, *observation_read.evidence_refs])
            ],
        },
    }


_EPISODE_REQUIRED_SLOT_IDS = (
    "episode_summary",
    "timeline",
    "participants",
    "sessions",
    "touchpoints",
    "communications",
    "agent_handoffs",
    "conversion_events",
    "attribution_links",
    "risk_flags",
    "evidence_trace",
)


def _flatten(lists: Any) -> list[str]:
    result: list[str] = []
    for item in lists:
        for value in item:
            if value not in result:
                result.append(value)
    return result


__all__ = [
    "Episode360Provider",
    "EpisodeOutcomeRead",
    "EpisodeOutcomeSource",
    "EpisodeObservationRead",
    "EpisodeObservationSource",
    "EpisodeSubjectGraphRead",
    "EpisodeSubjectRelationshipReader",
    "Journey360Read",
    "Journey360Source",
    "RepositoryEpisodeSubjectRelationshipReader",
    "RepositoryEpisodeObservationSource",
    "RepositoryJourney360Source",
    "register_provider",
]
