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
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional, Protocol
from urllib.parse import quote
from uuid import UUID

from shared.backend_interpretation.primitives import EpisodeRecord, OutcomeTruthRecord
from shared.backend_interpretation.stores import EpisodeStore
from journeys.measurement.episodes.related_authorities import (
    AuthorityFactRead,
    AuthorityFactSource,
    EpisodeAgentHandoffRecord,
    EpisodeAttributionLinkRecord,
    EpisodeObservationReferenceRecord,
    EpisodeJourneyAuthorityRepository,
    JourneyAcquisitionRole,
    JourneyActionIntentRecord,
    JourneyDropoffRecord,
    JourneySourceRoleMarker,
)
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
    "risk_flags": "Episode risk flags",
    "journey_attribution": "Journey attribution",
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
_JOURNEY_ATTRIBUTION_RUN_SOURCE = "attribution_runs"
_JOURNEY_ATTRIBUTION_CREDIT_SOURCE = "attribution_credits"
_EPISODE_RECORD_SOURCE = "shared.backend_interpretation.stores.EpisodeStore"
_EPISODE_OBSERVATION_SOURCE = "semantic_intelligence.silver_semantic_observations"
_EPISODE_OBSERVATION_REFERENCE_SOURCE = (
    "episode_journey_authority_records:episode_observation_reference"
)
_EPISODE_OBSERVATION_EVENT_REF_SOURCE = (
    "semantic_intelligence.silver_semantic_observations.source_event_id"
)
_EPISODE_OBSERVATION_RECEIPT_REF_SOURCE = (
    "semantic_intelligence.silver_semantic_observations.received_at"
)
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
_JOURNEY_ATTRIBUTION_CREDIT_CAP = 100
_JOURNEY_ATTRIBUTION_REFERENCE_READ_CONCURRENCY = 8
_JOURNEY_EPISODE_CAP = 100
_JOURNEY_AGENT_ACTIVITY_CAP = 200
_JOURNEY_TOUCHPOINT_READ_CONCURRENCY = 8
_EPISODE_PAGE_DEFAULT = 50
_EPISODE_SUBJECT_RELATIONSHIP_CAP = 100
_EPISODE_OBSERVATION_CAP = 200
_EPISODE_TOUCHPOINT_CAP = 200
_EPISODE_OUTCOME_CAP = 100
_EPISODE_RISK_SIGNAL_CAP = 100
_COMMUNICATION_FACT_CAP = 200
_EPISODE_AUTHORITY_CAP = 100
_GRAPH_LEDGER_SOURCE = "graph_mutation_ledger"
_EPISODE_RISK_SIGNAL_SOURCE = "risk360/risk_signals"
_COMMUNICATION_FACT_SOURCE = "services/api/journeys/communication360/communication360_facts"
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
class JourneyAttributionCredit:
    """One canonical credit linked through an exact active attribution run."""

    record: dict[str, Any]
    run_ref: EvidenceRef
    credit_ref: EvidenceRef
    conversion_ref: Optional[EvidenceRef] = None
    touchpoint_ref: Optional[EvidenceRef] = None


@dataclass(frozen=True)
class JourneyAttributionRead:
    """Bounded active credits joined through tenant-scoped journey run keys."""

    credits: tuple[JourneyAttributionCredit, ...] = ()
    state: str = "unknown"
    warnings: tuple[str, ...] = ()
    truncated: bool = False


@dataclass(frozen=True)
class JourneyAuthorityRead:
    """Bounded typed dropoff/action-intent records for one exact journey."""

    action_intents: AuthorityFactRead = AuthorityFactRead()
    dropoffs: AuthorityFactRead = AuthorityFactRead()


@dataclass(frozen=True)
class CommunicationFactLinkRead:
    """Exact tenant-scoped communication facts linked by a typed subject ID."""

    rows: tuple[dict[str, Any], ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = ()
    state: str = "unknown"
    reason: str = "communication_fact_link_not_read"
    complete: bool = False
    truncated: bool = False
    invalid_records: bool = False
    tenant_mismatch: bool = False
    missing_evidence: bool = False
    temporal_state: str = "unknown"


@dataclass(frozen=True)
class JourneyEpisodeRead:
    """Bounded tenant scan for EpisodeRecords that explicitly name a journey."""

    episodes: tuple[EpisodeRecord, ...] = ()
    available: bool = True
    truncated: bool = False
    invalid_records: bool = False
    tenant_mismatch: bool = False
    read_failed: bool = False

    @property
    def scan_complete(self) -> bool:
        return not (
            not self.available
            or self.truncated
            or self.invalid_records
            or self.tenant_mismatch
            or self.read_failed
        )


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
    """Exact tenant + source-namespace reads for recorded Episode observations."""

    requested_ids: tuple[str, ...] = ()
    rows: tuple[dict[str, Any], ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = ()
    reference_links: tuple[tuple[str, str, EvidenceRef], ...] = ()
    available: bool = True
    truncated: bool = False
    invalid_records: bool = False
    tenant_mismatch: bool = False
    inactive_records: bool = False
    timestamps_missing: bool = False
    missing_ids: tuple[str, ...] = ()
    namespace_missing_ids: tuple[str, ...] = ()
    missing_episode_links: tuple[tuple[str, str], ...] = ()
    ambiguous_ids: tuple[str, ...] = ()
    out_of_window_ids: tuple[str, ...] = ()
    temporal_state: str = "unknown"
    temporal_reason: Optional[str] = None
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
            or self.namespace_missing_ids
            or self.missing_episode_links
            or self.ambiguous_ids
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


@dataclass(frozen=True)
class EpisodeRiskFlagRead:
    """Exact-primary-subject risk signals joined to one canonical episode."""

    subject_kind: Optional[str] = None
    subject_id: Optional[str] = None
    signals: tuple[dict[str, Any], ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = ()
    state: str = "unknown"
    reason: str = "episode_risk_signal_read_not_performed"
    truncated: bool = False
    invalid_records: bool = False
    tenant_mismatch: bool = False
    read_failed: bool = False


@dataclass(frozen=True)
class EpisodeTouchpointRead:
    """Exact tenant-bound touchpoints named by canonical episode records."""

    requested_ids: tuple[str, ...] = ()
    rows: tuple[dict[str, Any], ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = ()
    state: str = "unknown"
    warnings: tuple[str, ...] = ()
    missing_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class EpisodeAuthorityRead:
    """Two exact episode association reads; neither proves full inventory."""

    agent_handoffs: AuthorityFactRead = AuthorityFactRead()
    attribution_links: AuthorityFactRead = AuthorityFactRead()


class EpisodeOutcomeSource(Protocol):
    """Exact composite-key reader over canonical outcome truth."""

    async def get(self, tenant_id: str, outcome_id: str) -> Any: ...


class EpisodeRiskSignalSource(Protocol):
    """Bounded tenant + exact typed-subject read over canonical RiskSignals."""

    async def signals(
        self,
        *,
        tenant_id: str,
        subject_kind: str,
        subject_id: str,
        limit: int,
    ) -> list[dict[str, Any]]: ...


class RepositoryEpisodeRiskSignalSource:
    """Adapter over Risk360's tenant-scoped exact-subject signal repository."""

    async def signals(
        self,
        *,
        tenant_id: str,
        subject_kind: str,
        subject_id: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        from intelligence.risk360.store import RiskSignalRepository

        return await RiskSignalRepository().list_by_subject(
            tenant_id,
            subject_kind,
            subject_id,
            limit=limit,
            offset=0,
        )


class EpisodeObservationSource(Protocol):
    """Canonical exact tenant, ID, and namespace lookup for Silver rows."""

    async def find_by_namespaced_ids(
        self, tenant_id: str, namespaces_by_id: dict[str, str]
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

    async def find_by_namespaced_ids(
        self, tenant_id: str, namespaces_by_id: dict[str, str]
    ) -> list[dict[str, Any]]:
        """Read only rows matching an exact tenant, ID, and source namespace."""
        bounded = [
            (observation_id, source_namespace)
            for observation_id, source_namespace in namespaces_by_id.items()
            if observation_id and source_namespace
        ][: _EPISODE_OBSERVATION_CAP]
        if not tenant_id or not bounded:
            return []
        repository = self._observation_repository()
        pool = await repository._pool()
        if pool is None:
            rows = await repository.find_by_ids(
                tenant_id, [observation_id for observation_id, _ in bounded]
            )
            exact_namespace = dict(bounded)
            return [
                row
                for row in rows
                if isinstance(row, dict)
                and row.get("tenant_id") == tenant_id
                and row.get("source_namespace") == exact_namespace.get(
                    _journey_text(row.get("record_id"))
                )
            ]

        ids = [observation_id for observation_id, _ in bounded]
        namespaces = [source_namespace for _, source_namespace in bounded]
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "WITH requested(id, source_namespace) AS ("
                "SELECT * FROM unnest($2::text[], $3::text[])"
                ") SELECT f.id, f.tenant_id, f.subject_ref, f.data "
                "FROM silver_semantic_observations AS f "
                "JOIN requested AS r ON r.id=f.id "
                "AND r.source_namespace=f.data->>'source_namespace' "
                "WHERE f.tenant_id=$1 ORDER BY f.id ASC",
                tenant_id,
                ids,
                namespaces,
            )
        result: list[dict[str, Any]] = []
        for raw in rows:
            data = raw["data"]
            if isinstance(data, str):
                data = json.loads(data)
            if not isinstance(data, dict):
                continue
            normalized = dict(data)
            normalized.setdefault("tenant_id", raw["tenant_id"])
            normalized.setdefault("subject_ref", raw["subject_ref"])
            normalized.setdefault("record_id", raw["id"])
            result.append(normalized)
        return result


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


class JourneyAttributionSource(Protocol):
    """Bounded active-credit read through an exact tenant/journey-version run link."""

    async def list_active_credits_for_journey(
        self,
        tenant_id: str,
        journey_id: str,
        journey_version_id: str,
        *,
        limit: int,
    ) -> list[dict[str, Any]]: ...


class CommunicationFactReferenceSource(Protocol):
    """Read facts by one exact journey or episode reference in one tenant."""

    async def list_for_reference(
        self,
        tenant_id: str,
        subject_kind: str,
        subject_id: str,
        *,
        after: Optional[datetime],
        before: Optional[datetime],
        received_before: Optional[datetime],
        limit: int,
    ) -> tuple[list[dict[str, Any]], bool]: ...


class RepositoryCommunicationFactReferenceSource:
    """Adapter over the canonical communication fact JSONB reference index."""

    def __init__(self, *, repository: Any = None) -> None:
        self._repository = repository

    def _fact_repository(self) -> Any:
        if self._repository is None:
            from journeys.communication360.repository import Communication360FactsRepository

            self._repository = Communication360FactsRepository()
        return self._repository

    async def list_for_reference(
        self,
        tenant_id: str,
        subject_kind: str,
        subject_id: str,
        *,
        after: Optional[datetime],
        before: Optional[datetime],
        received_before: Optional[datetime],
        limit: int,
    ) -> tuple[list[dict[str, Any]], bool]:
        return await self._fact_repository().facts_for_exact_reference(
            tenant_id,
            subject_kind,
            subject_id,
            after=after,
            before=before,
            received_before=received_before,
            limit=limit,
        )


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


class RepositoryJourneyAttributionSource:
    """Adapter over active credits joined to exact-journey attribution runs."""

    def __init__(self, *, repository: Any = None) -> None:
        self._repository = repository

    def _attribution_repository(self) -> Any:
        if self._repository is None:
            from journeys.measurement.repositories.attribution_run_repo import (
                AttributionRunRepository,
            )

            self._repository = AttributionRunRepository()
        return self._repository

    async def list_active_credits_for_journey(
        self,
        tenant_id: str,
        journey_id: str,
        journey_version_id: str,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        try:
            UUID(journey_id)
            UUID(journey_version_id)
        except (TypeError, ValueError, AttributeError) as exc:
            # UUID-keyed SQL lookups return no rows for invalid IDs. Surface
            # invalid current journey keys as unavailable so they cannot be
            # mistaken for an authoritative empty attribution result.
            raise ValueError("canonical journey and version IDs must be UUIDs") from exc
        rows = await self._attribution_repository().list_active_credits_for_journey(
            tenant_id,
            journey_id,
            journey_version_id,
            limit=limit,
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
        touchpoint_source: Optional[JourneyTouchpointSource] = None,
        conversion_source: Optional[JourneyConversionSource] = None,
        subject_relationship_reader: Optional[EpisodeSubjectRelationshipReader] = None,
        observation_source: Optional[EpisodeObservationSource] = None,
        outcome_source: Optional[EpisodeOutcomeSource] = None,
        risk_signal_source: Optional[EpisodeRiskSignalSource] = None,
        attribution_source: Optional[JourneyAttributionSource] = None,
        communication_fact_source: Optional[CommunicationFactReferenceSource] = None,
        episode_authority_source: Optional[AuthorityFactSource] = None,
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
        self._attribution_source = attribution_source
        self._communication_fact_source = communication_fact_source
        self._episode_authority_source = episode_authority_source
        self._risk_signal_source = risk_signal_source
        self._subject_relationship_reader = (
            subject_relationship_reader
            if subject_relationship_reader is not None
            else RepositoryEpisodeSubjectRelationshipReader()
        )

    async def _load_episode_authorities(
        self,
        tenant_id: str,
        episode: EpisodeRecord,
        *,
        as_of: Optional[datetime] = None,
    ) -> EpisodeAuthorityRead:
        """Read explicit typed links by exact tenant + episode reference."""
        source = self._episode_authority_source or EpisodeJourneyAuthorityRepository()
        try:
            handoffs = await source.list_for_subject(
                tenant_id,
                "episode",
                episode.episode_id,
                "episode_agent_handoff",
                limit=_EPISODE_AUTHORITY_CAP,
            )
            attributions = await source.list_for_subject(
                tenant_id,
                "episode",
                episode.episode_id,
                "episode_attribution_link",
                limit=_EPISODE_AUTHORITY_CAP,
            )
        except Exception:  # noqa: BLE001 - optional relation authority fails closed
            unavailable = AuthorityFactRead(
                available=False,
                complete=False,
                read_failed=True,
            )
            return EpisodeAuthorityRead(unavailable, unavailable)

        return EpisodeAuthorityRead(
            agent_handoffs=_episode_authority_read_for_as_of(
                handoffs,
                record_type="episode_agent_handoff",
                tenant_id=tenant_id,
                episode=episode,
                as_of=as_of,
            ),
            attribution_links=_episode_authority_read_for_as_of(
                attributions,
                record_type="episode_attribution_link",
                tenant_id=tenant_id,
                episode=episode,
                as_of=as_of,
            ),
        )

    async def _load_journey_action_intents(
        self, tenant_id: str, journey_id: str
    ) -> JourneyAuthorityRead:
        """Read explicit action intents through an exact tenant + journey key."""
        source = self._episode_authority_source or EpisodeJourneyAuthorityRepository()
        try:
            read = await source.list_for_subject(
                tenant_id,
                "journey",
                journey_id,
                "journey_action_intent",
                limit=_EPISODE_AUTHORITY_CAP,
            )
        except Exception:  # noqa: BLE001 - optional action authority fails closed
            read = AuthorityFactRead(available=False, complete=False, read_failed=True)
        return JourneyAuthorityRead(action_intents=read)

    async def _load_journey_dropoffs(
        self, tenant_id: str, journey_id: str
    ) -> JourneyAuthorityRead:
        """Read bounded canonical dropoff facts for an exact tenant journey."""
        source = self._episode_authority_source or EpisodeJourneyAuthorityRepository()
        try:
            read = await source.list_for_subject(
                tenant_id,
                "journey",
                journey_id,
                "journey_dropoff",
                limit=_EPISODE_AUTHORITY_CAP,
            )
        except Exception:  # noqa: BLE001 - optional dropoff authority fails closed
            read = AuthorityFactRead(available=False, complete=False, read_failed=True)
        return JourneyAuthorityRead(dropoffs=read)

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

    async def _load_journey_episodes(
        self, tenant_id: str, journey_id: str
    ) -> JourneyEpisodeRead:
        """Read explicit links from a bounded, tenant-scoped episode page.

        The episode store has no secondary index for journey associations yet.
        Therefore a full page proves only the records scanned; truncation or an
        unlinked legacy record never establishes that a journey has no episodes.
        """
        store = self._load_store()
        if store is None:
            return JourneyEpisodeRead(available=False)
        try:
            page = await store.list_page_by_tenant(
                tenant_id,
                limit=_JOURNEY_EPISODE_CAP,
            )
        except Exception:  # noqa: BLE001 - episode relation read degrades independently
            return JourneyEpisodeRead(read_failed=True)

        episodes: list[EpisodeRecord] = []
        invalid_records = page.invalid_records
        tenant_mismatch = False
        for value in page.records:
            if not isinstance(value, EpisodeRecord):
                invalid_records = True
                continue
            if value.tenant_id != tenant_id:
                tenant_mismatch = True
                continue
            if value.journey_id == journey_id:
                episodes.append(value)
        episodes.sort(
            key=lambda value: (
                value.occurred_from or value.created_at,
                value.episode_id,
            )
        )
        return JourneyEpisodeRead(
            episodes=tuple(episodes),
            truncated=bool(page.truncated or page.next_cursor),
            invalid_records=invalid_records,
            tenant_mismatch=tenant_mismatch,
        )

    async def _load_episode_observations(
        self,
        tenant_id: str,
        episodes: list[EpisodeRecord],
        *,
        after: Optional[datetime] = None,
        before: Optional[datetime] = None,
        as_of: Optional[datetime] = None,
    ) -> EpisodeObservationRead:
        """Resolve only namespaced observation links explicitly recorded by episodes.

        Bare legacy IDs are not enough to identify a source. An exact typed
        ``episode_observation_reference`` must bind tenant, episode, observation,
        source namespace and source event lineage before the canonical semantic
        row is fetched. Event time constrains windows; an as-of frame also
        requires source receipt, semantic processing, and the typed episode
        association to exist by the anchor.
        """
        requested_ids = _journey_ordered_values(
            [observation_id for episode in episodes for observation_id in episode.observation_ids]
        )
        truncated = len(requested_ids) > _EPISODE_OBSERVATION_CAP
        bounded_ids = requested_ids[:_EPISODE_OBSERVATION_CAP]
        temporal_state = (
            "event_receipt_processing_and_link_time_as_of_applied"
            if as_of is not None
            else "event_time_window_applied"
            if after is not None or before is not None
            else "event_time_order_only"
        )
        if not bounded_ids:
            return EpisodeObservationRead(
                requested_ids=tuple(requested_ids),
                available=True,
                truncated=truncated,
                temporal_state=temporal_state,
            )

        # EpisodeRecord stores bare IDs, so a separate typed authority must
        # supply their source namespace and canonical event lineage. Reads stay
        # bounded to the current Episode page and the shared authority cap.
        authority_source = self._episode_authority_source or EpisodeJourneyAuthorityRepository()
        reference_records: dict[str, EpisodeObservationReferenceRecord] = {}
        reference_records_by_episode: dict[
            tuple[str, str], EpisodeObservationReferenceRecord
        ] = {}
        ambiguous_ids: set[str] = set()
        authority_unavailable = False
        authority_invalid = False
        authority_tenant_mismatch = False
        remaining = _EPISODE_OBSERVATION_CAP
        scanned_episode_ids: set[str] = set()
        scanned_observation_ids: set[str] = set()
        for episode in episodes:
            if remaining <= 0:
                truncated = True
                break
            if episode.tenant_id != tenant_id:
                authority_tenant_mismatch = True
                continue
            scanned_episode_ids.add(episode.episode_id)
            scanned_observation_ids.update(episode.observation_ids)
            try:
                read = await authority_source.list_for_subject(
                    tenant_id,
                    "episode",
                    episode.episode_id,
                    "episode_observation_reference",
                    limit=min(_EPISODE_OBSERVATION_CAP, remaining),
                )
            except Exception:  # noqa: BLE001 - namespace reference authority fails closed
                authority_unavailable = True
                continue
            if not isinstance(read, AuthorityFactRead):
                authority_unavailable = True
                continue
            authority_unavailable = authority_unavailable or not read.available or read.read_failed
            authority_invalid = authority_invalid or read.invalid_records
            authority_tenant_mismatch = authority_tenant_mismatch or read.tenant_mismatch
            truncated = truncated or read.truncated
            if not read.complete and not (
                read.invalid_records
                or read.tenant_mismatch
                or read.truncated
                or read.read_failed
                or not read.available
            ):
                authority_invalid = True
            remaining -= len(read.records)
            episode_ids = set(episode.observation_ids)
            local_seen: dict[str, EpisodeObservationReferenceRecord] = {}
            for raw in read.records:
                try:
                    record = EpisodeObservationReferenceRecord.model_validate(raw)
                except Exception:  # noqa: BLE001 - malformed namespace rows stay unknown
                    authority_invalid = True
                    continue
                if (
                    record.tenant_id != tenant_id
                    or record.episode_id != episode.episode_id
                    or record.record_type != "episode_observation_reference"
                    or record.observation_id not in episode_ids
                    or not _episode_observation_reference_has_evidence(record)
                ):
                    if record.tenant_id != tenant_id:
                        authority_tenant_mismatch = True
                    else:
                        authority_invalid = True
                    continue
                previous = local_seen.get(record.observation_id)
                if previous is not None and previous != record:
                    ambiguous_ids.add(record.observation_id)
                    continue
                local_seen[record.observation_id] = record
                reference_records_by_episode[(episode.episode_id, record.observation_id)] = record
                existing = reference_records.get(record.observation_id)
                if existing is not None and (
                    existing.source_namespace != record.source_namespace
                    or existing.source_event_id != record.source_event_id
                    or existing.occurred_at != record.occurred_at
                    or existing.received_at != record.received_at
                    or existing.recorded_at != record.recorded_at
                ):
                    ambiguous_ids.add(record.observation_id)
                    reference_records.pop(record.observation_id, None)
                    continue
                if existing is None or record.linked_at < existing.linked_at:
                    reference_records[record.observation_id] = record

        bounded_set = set(bounded_ids)
        missing_episode_links = tuple(
            (episode.episode_id, observation_id)
            for episode in episodes
            for observation_id in episode.observation_ids
            if episode.episode_id in scanned_episode_ids
            and observation_id in bounded_set
            and (episode.episode_id, observation_id) not in reference_records_by_episode
        )
        namespace_missing_ids = {
            observation_id
            for observation_id in bounded_ids
            if observation_id in scanned_observation_ids
            and observation_id not in reference_records
            and observation_id not in ambiguous_ids
        }
        ambiguous_ids &= bounded_set
        namespace_missing_ids -= ambiguous_ids

        # The authority row is an explicit namespace assertion, but the source
        # row is read again and checked against it. This prevents a stale or
        # inconsistent namespace association from authorizing a different fact.
        out_of_window_ids: set[str] = set()
        eligible_records: dict[str, EpisodeObservationReferenceRecord] = {}
        for observation_id, record in reference_records.items():
            if observation_id in ambiguous_ids:
                continue
            if as_of is not None and record.linked_at > as_of:
                out_of_window_ids.add(observation_id)
                continue
            if not _episode_observation_time_matches(
                record.occurred_at,
                record.recorded_at,
                record.evidence_refs,
                received_at=record.received_at,
                after=after,
                before=before,
                as_of=as_of,
            ):
                out_of_window_ids.add(observation_id)
                continue
            eligible_records[observation_id] = record
        fetch_ids = [value for value in bounded_ids if value in eligible_records]
        if not fetch_ids:
            return EpisodeObservationRead(
                requested_ids=tuple(requested_ids),
                evidence_refs=(),
                available=not authority_unavailable,
                truncated=truncated,
                invalid_records=authority_invalid,
                tenant_mismatch=authority_tenant_mismatch,
                missing_ids=(),
                namespace_missing_ids=tuple(
                    value for value in bounded_ids if value in namespace_missing_ids
                ),
                missing_episode_links=missing_episode_links,
                ambiguous_ids=tuple(value for value in bounded_ids if value in ambiguous_ids),
                out_of_window_ids=tuple(value for value in bounded_ids if value in out_of_window_ids),
                temporal_state=temporal_state,
                read_failed=authority_unavailable,
            )

        source = self._observation_source or RepositoryEpisodeObservationSource()
        try:
            namespaces_by_id = {
                observation_id: eligible_records[observation_id].source_namespace
                for observation_id in fetch_ids
            }
            raw_rows = await source.find_by_namespaced_ids(
                tenant_id, namespaces_by_id
            )
        except Exception:  # noqa: BLE001 - source observation authority stays isolated
            return EpisodeObservationRead(
                requested_ids=tuple(requested_ids),
                available=False,
                truncated=truncated,
                missing_ids=tuple(fetch_ids),
                namespace_missing_ids=tuple(
                    value for value in bounded_ids if value in namespace_missing_ids
                ),
                missing_episode_links=missing_episode_links,
                ambiguous_ids=tuple(value for value in bounded_ids if value in ambiguous_ids),
                out_of_window_ids=tuple(value for value in bounded_ids if value in out_of_window_ids),
                temporal_state=temporal_state,
                read_failed=True,
            )
        if not isinstance(raw_rows, list):
            return EpisodeObservationRead(
                requested_ids=tuple(requested_ids),
                available=False,
                truncated=truncated,
                missing_ids=tuple(fetch_ids),
                invalid_records=True,
                namespace_missing_ids=tuple(
                    value for value in bounded_ids if value in namespace_missing_ids
                ),
                missing_episode_links=missing_episode_links,
                ambiguous_ids=tuple(value for value in bounded_ids if value in ambiguous_ids),
                out_of_window_ids=tuple(value for value in bounded_ids if value in out_of_window_ids),
                temporal_state=temporal_state,
            )

        requested_set = set(fetch_ids)
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
            reference = eligible_records[record_id]
            if (
                _journey_text(row.get("source_namespace")) != reference.source_namespace
                or _journey_text(row.get("source_event_id")) != reference.source_event_id
            ):
                ambiguous_ids.add(record_id)
                invalid_ids.add(record_id)
                continue
            status = _journey_text(row.get("status"))
            if status not in {"classified", "partial"}:
                inactive_records = True
                continue
            rows_by_id[record_id] = row
            occurred_at = _parse_utc_timestamp(row.get("occurred_at"))
            received_at = _parse_utc_timestamp(row.get("received_at"))
            processed_at = _parse_utc_timestamp(row.get("processed_at"))
            if (
                occurred_at is None
                or processed_at is None
                or (as_of is not None and received_at is None)
            ):
                timestamps_missing = True
                rows_by_id.pop(record_id, None)
                continue
            if occurred_at != reference.occurred_at.astimezone(timezone.utc):
                ambiguous_ids.add(record_id)
                invalid_ids.add(record_id)
                rows_by_id.pop(record_id, None)
                continue
            if (
                received_at != reference.received_at.astimezone(timezone.utc)
                or processed_at != reference.recorded_at.astimezone(timezone.utc)
            ):
                ambiguous_ids.add(record_id)
                invalid_ids.add(record_id)
                rows_by_id.pop(record_id, None)
                continue
            if not _episode_observation_time_matches(
                occurred_at,
                processed_at,
                reference.evidence_refs,
                received_at=received_at,
                after=after,
                before=before,
                as_of=as_of,
            ):
                out_of_window_ids.add(record_id)
                rows_by_id.pop(record_id, None)
                continue

        for invalid_id in invalid_ids:
            if invalid_id in rows_by_id:
                rows_by_id.pop(invalid_id, None)
        missing_ids = [value for value in fetch_ids if value not in rows_by_id and value not in out_of_window_ids]
        ordered_rows = [rows_by_id[value] for value in fetch_ids if value in rows_by_id]
        resolved_ids = set(rows_by_id)
        reference_links = tuple(
            (episode_id, observation_id, _episode_observation_reference_ref(record))
            for (episode_id, observation_id), record in reference_records_by_episode.items()
            if observation_id in resolved_ids and observation_id not in ambiguous_ids
            and (as_of is None or record.linked_at <= as_of)
        )
        evidence_refs = [
            ref
            for row in ordered_rows
            if (ref := _episode_observation_ref(tenant_id, row)) is not None
        ]
        evidence_refs.extend(
            ref
            for row in ordered_rows
            if (ref := _episode_observation_source_event_ref(tenant_id, row)) is not None
        )
        evidence_refs.extend(
            ref
            for row in ordered_rows
            if (ref := _episode_observation_receipt_ref(tenant_id, row)) is not None
        )
        evidence_refs.extend(link_ref for _, _, link_ref in reference_links)
        return EpisodeObservationRead(
            requested_ids=tuple(requested_ids),
            rows=tuple(ordered_rows),
            evidence_refs=tuple(evidence_refs),
            reference_links=reference_links,
            available=not authority_unavailable,
            truncated=truncated,
            invalid_records=bool(invalid_ids) or authority_invalid,
            tenant_mismatch=tenant_mismatch or authority_tenant_mismatch,
            inactive_records=inactive_records,
            timestamps_missing=timestamps_missing,
            missing_ids=tuple(missing_ids),
            namespace_missing_ids=tuple(
                value for value in bounded_ids if value in namespace_missing_ids
            ),
            missing_episode_links=missing_episode_links,
            ambiguous_ids=tuple(value for value in bounded_ids if value in ambiguous_ids),
            out_of_window_ids=tuple(value for value in bounded_ids if value in out_of_window_ids),
            temporal_state=temporal_state,
            read_failed=authority_unavailable,
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

    async def _load_episode_risk_flags(
        self, tenant_id: str, episode: EpisodeRecord
    ) -> EpisodeRiskFlagRead:
        """Read current RiskSignals for an episode's exact typed primary subject.

        The episode-to-subject ``EntityRef`` and RiskSignal's typed subject
        fields form the only admitted join. Risk is not inferred from episode
        observations, outcome type, nearby graph edges, or event labels.
        """
        subject_kind = _journey_text(episode.subject.kind)
        subject_id = _journey_text(episode.subject.id)
        if episode.tenant_id != tenant_id:
            return EpisodeRiskFlagRead(
                subject_kind=subject_kind,
                subject_id=subject_id,
                state="unknown",
                reason="episode_risk_reference_tenant_mismatch",
                tenant_mismatch=True,
            )
        if subject_kind is None or subject_id is None:
            return EpisodeRiskFlagRead(
                state="unknown",
                reason="episode_primary_subject_not_typed_for_risk_lookup",
            )

        source = self._risk_signal_source or RepositoryEpisodeRiskSignalSource()
        try:
            raw_rows = await source.signals(
                tenant_id=tenant_id,
                subject_kind=subject_kind,
                subject_id=subject_id,
                limit=_EPISODE_RISK_SIGNAL_CAP + 1,
            )
        except Exception:  # noqa: BLE001 - risk authority fails closed independently
            return EpisodeRiskFlagRead(
                subject_kind=subject_kind,
                subject_id=subject_id,
                state="unknown",
                reason="episode_risk_signal_authority_unavailable",
                read_failed=True,
            )
        if not isinstance(raw_rows, list):
            return EpisodeRiskFlagRead(
                subject_kind=subject_kind,
                subject_id=subject_id,
                state="unknown",
                reason="episode_risk_signal_authority_returned_invalid_rows",
                invalid_records=True,
            )

        from intelligence.risk360.contracts import RiskSignal

        truncated = len(raw_rows) > _EPISODE_RISK_SIGNAL_CAP
        signals: list[dict[str, Any]] = []
        signal_evidence: list[EvidenceRef] = []
        invalid_records = False
        tenant_mismatch = False
        for value in raw_rows[:_EPISODE_RISK_SIGNAL_CAP]:
            row = _as_mapping(value)
            if row is None:
                invalid_records = True
                continue
            if row.get("tenant_id") != tenant_id:
                tenant_mismatch = True
                continue
            if (
                _journey_text(row.get("subject_kind")) != subject_kind
                or _journey_text(row.get("subject_id")) != subject_id
            ):
                invalid_records = True
                continue
            try:
                signal = RiskSignal.model_validate(row)
            except Exception:  # noqa: BLE001 - malformed canonical rows stay unknown
                invalid_records = True
                continue
            if not signal.evidence_refs:
                invalid_records = True
                continue
            if signal.observed_at is not None and (
                signal.observed_at.tzinfo is None or signal.observed_at.utcoffset() is None
            ):
                invalid_records = True
                continue

            signal_refs = _dedupe_evidence_refs(signal.evidence_refs)
            record_ref = EvidenceRef(
                id=signal.signal_id,
                type="event",
                source=_EPISODE_RISK_SIGNAL_SOURCE,
                observedAt=(signal.observed_at.isoformat() if signal.observed_at else None),
                uri=f"store://risk_signals/{quote(signal.signal_id, safe='')}",
            )
            signal_evidence.extend([record_ref, *signal_refs])
            signals.append(
                {
                    "signalId": signal.signal_id,
                    "subject": {"kind": signal.subject_kind, "id": signal.subject_id},
                    "riskDimension": signal.risk_dimension,
                    "claimState": getattr(signal.claim_state, "value", signal.claim_state),
                    "confidence": signal.confidence,
                    "score": signal.score,
                    "value": signal.value,
                    "source": signal.source,
                    "detectorVersion": signal.detector_version,
                    "observedAt": (
                        signal.observed_at.isoformat() if signal.observed_at is not None else None
                    ),
                    "evidenceRefs": [
                        ref.model_dump(mode="json", exclude_none=True) for ref in signal_refs
                    ],
                }
            )

        evidence_refs = tuple(_dedupe_evidence_refs(signal_evidence))
        if signals:
            reason = (
                "episode_risk_signal_read_truncated_history_policy_and_freshness_unresolved"
                if truncated
                else "episode_risk_signal_read_contains_unscoped_or_invalid_rows"
                if invalid_records or tenant_mismatch
                else "exact_episode_primary_subject_risk_signals_observed_history_policy_and_freshness_unresolved"
            )
            state = "degraded"
        elif truncated or invalid_records or tenant_mismatch:
            reason = "episode_risk_signal_read_incomplete"
            state = "degraded"
        else:
            reason = "no_exact_episode_primary_subject_risk_signal_observed_absence_not_established"
            state = "unknown"
        return EpisodeRiskFlagRead(
            subject_kind=subject_kind,
            subject_id=subject_id,
            signals=tuple(signals),
            evidence_refs=evidence_refs,
            state=state,
            reason=reason,
            truncated=truncated,
            invalid_records=invalid_records,
            tenant_mismatch=tenant_mismatch,
        )

    async def _load_episode_touchpoints(
        self, tenant_id: str, episodes: list[EpisodeRecord]
    ) -> EpisodeTouchpointRead:
        """Resolve only touchpoint IDs explicitly recorded by EpisodeRecord.

        ``None`` is retained for legacy records that predate this typed
        reference inventory; an explicit empty list is distinguishable and
        means only that the record names no touchpoints. It does not establish
        complete journey touchpoint coverage or attribution credit.
        """
        reference_lists_available = True
        malformed_reference = False
        duplicate_reference = False
        requested_ids: list[str] = []
        seen_ids: set[str] = set()
        for episode in episodes:
            raw_ids = episode.journey_touchpoint_ids
            if raw_ids is None:
                reference_lists_available = False
                continue
            if not isinstance(raw_ids, list):
                malformed_reference = True
                continue
            episode_seen: set[str] = set()
            for raw_id in raw_ids:
                touchpoint_id = _journey_text(raw_id)
                if touchpoint_id is None:
                    malformed_reference = True
                    continue
                if touchpoint_id in episode_seen:
                    duplicate_reference = True
                    continue
                episode_seen.add(touchpoint_id)
                if touchpoint_id not in seen_ids:
                    seen_ids.add(touchpoint_id)
                    requested_ids.append(touchpoint_id)

        warnings: list[str] = []
        if not reference_lists_available:
            warnings.append("episode_touchpoint_reference_list_unavailable")
        if malformed_reference:
            warnings.append("episode_touchpoint_reference_invalid")
        if duplicate_reference:
            warnings.append("episode_touchpoint_reference_duplicated")
        if not requested_ids:
            state = "empty" if reference_lists_available and not warnings else "unknown"
            return EpisodeTouchpointRead(state=state, warnings=tuple(warnings))

        truncated = len(requested_ids) > _EPISODE_TOUCHPOINT_CAP
        bounded_ids = requested_ids[:_EPISODE_TOUCHPOINT_CAP]
        if truncated:
            warnings.append("episode_touchpoint_read_truncated")
        source = self._touchpoint_source or RepositoryJourneyTouchpointSource()
        semaphore = asyncio.Semaphore(_JOURNEY_TOUCHPOINT_READ_CONCURRENCY)

        async def read_one(
            touchpoint_id: str,
        ) -> tuple[str, Optional[dict[str, Any]], bool]:
            async with semaphore:
                try:
                    value = await source.get(tenant_id, touchpoint_id)
                except Exception:  # noqa: BLE001 - exact authority failure stays unknown
                    return touchpoint_id, None, True
            return touchpoint_id, _as_mapping(value), False

        results = await asyncio.gather(*(read_one(value) for value in bounded_ids))
        rows: list[dict[str, Any]] = []
        missing_ids: list[str] = []
        read_failed = False
        scope_mismatch = False
        missing_evidence = False
        evidence_refs: list[EvidenceRef] = []
        for touchpoint_id, row, failed in results:
            if failed:
                read_failed = True
                missing_ids.append(touchpoint_id)
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
                missing_evidence = True
                missing_ids.append(touchpoint_id)
                continue
            rows.append(row)
            evidence_refs.append(evidence)

        if read_failed:
            warnings.append("episode_touchpoint_authority_unavailable")
        if scope_mismatch:
            warnings.append("episode_touchpoint_scope_mismatch")
        if missing_ids:
            warnings.append("episode_touchpoint_references_unresolved")
        if missing_evidence:
            warnings.append("episode_touchpoint_evidence_missing")
        state = (
            "available"
            if rows and not warnings and len(rows) == len(requested_ids)
            else "degraded"
            if rows
            else "unknown"
        )
        return EpisodeTouchpointRead(
            requested_ids=tuple(requested_ids),
            rows=tuple(rows),
            evidence_refs=tuple(_dedupe_evidence_refs(evidence_refs)),
            state=state,
            warnings=tuple(dict.fromkeys(warnings)),
            missing_ids=tuple(missing_ids),
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

    async def _load_journey_attribution(
        self, tenant_id: str, journey: dict[str, Any]
    ) -> JourneyAttributionRead:
        """Read only credits reached through the exact active tenant/journey run.

        The credit table itself has no journey key. The repository joins each
        row to its same-tenant attribution run, and this boundary revalidates
        that link before any credit or claim is projected.
        """
        journey_id = _journey_text(journey.get("journey_id"))
        journey_version_id = _journey_text(journey.get("journey_version_id"))
        if journey_id is None or journey_version_id is None:
            return JourneyAttributionRead(
                warnings=("journey_attribution_current_journey_key_missing",)
            )
        source = self._attribution_source or RepositoryJourneyAttributionSource()
        try:
            raw_rows = await source.list_active_credits_for_journey(
                tenant_id,
                journey_id,
                journey_version_id,
                limit=_JOURNEY_ATTRIBUTION_CREDIT_CAP + 1,
            )
        except Exception:  # noqa: BLE001 - attribution outage stays unknown
            return JourneyAttributionRead(
                warnings=("journey_attribution_authority_unavailable",)
            )
        if not isinstance(raw_rows, list):
            return JourneyAttributionRead(
                warnings=("journey_attribution_result_invalid",)
            )

        truncated = len(raw_rows) > _JOURNEY_ATTRIBUTION_CREDIT_CAP
        bounded_rows = raw_rows[:_JOURNEY_ATTRIBUTION_CREDIT_CAP]
        warnings: list[str] = []
        if truncated:
            warnings.append("journey_attribution_credit_read_truncated")
        credits: list[JourneyAttributionCredit] = []
        seen_credit_ids: set[str] = set()
        invalid_records = False
        scope_mismatch = False
        missing_timestamps = False
        for value in bounded_rows:
            row = _as_mapping(value)
            if row is None:
                invalid_records = True
                continue
            if (
                row.get("tenant_id") != tenant_id
                or row.get("linked_tenant_id") != tenant_id
                or _journey_text(row.get("linked_journey_id")) != journey_id
                or _journey_text(row.get("linked_journey_version_id"))
                != journey_version_id
            ):
                scope_mismatch = True
                continue
            if (
                row.get("attribution_run_status") != "complete"
                or row.get("attribution_run_is_active") is not True
            ):
                invalid_records = True
                continue

            credit_id = _journey_text(row.get("credit_id"))
            run_id = _journey_text(row.get("attribution_run_id"))
            conversion_id = _journey_text(row.get("conversion_id"))
            linked_conversion_id = _journey_text(row.get("linked_conversion_id"))
            credit_weight = _journey_decimal_text(row.get("credit_weight"))
            if (
                credit_id is None
                or run_id is None
                or credit_id in seen_credit_ids
                or conversion_id is None
                or conversion_id != linked_conversion_id
                or credit_weight is None
            ):
                invalid_records = True
                continue
            try:
                parsed_weight = Decimal(credit_weight)
            except (InvalidOperation, ValueError):
                invalid_records = True
                continue
            if not parsed_weight.is_finite() or not Decimal("0") <= parsed_weight <= Decimal("1"):
                invalid_records = True
                continue

            run_completed_at = _journey_timestamp(
                row.get("attribution_run_completed_at")
            )
            credit_created_at = _journey_timestamp(row.get("created_at"))
            if run_completed_at is None or credit_created_at is None:
                missing_timestamps = True
            run_ref = EvidenceRef(
                id=run_id,
                type="model_output",
                source=_JOURNEY_ATTRIBUTION_RUN_SOURCE,
                observedAt=run_completed_at,
                uri=f"store://attribution_runs/{run_id}",
            )
            credit_ref = EvidenceRef(
                id=credit_id,
                type="model_output",
                source=_JOURNEY_ATTRIBUTION_CREDIT_SOURCE,
                observedAt=credit_created_at,
                uri=f"store://attribution_credits/{credit_id}",
            )
            seen_credit_ids.add(credit_id)
            record = {
                "creditId": credit_id,
                "attributionRunId": run_id,
                "journeyId": journey_id,
                "journeyVersionId": _journey_text(
                    row.get("linked_journey_version_id")
                ),
                "recordedConversionId": conversion_id,
                "conversionResolutionState": "unknown",
                "recordedTouchpointId": _journey_text(row.get("touchpoint_id")),
                "touchpointResolutionState": (
                    "unknown" if row.get("touchpoint_id") is not None else "not_recorded"
                ),
                "campaignId": _journey_text(row.get("campaign_id")),
                "channel": _journey_text(row.get("channel")),
                "source": _journey_text(row.get("source")),
                "creditWeight": credit_weight,
                "attributedConversionCount": _journey_decimal_text(
                    row.get("attributed_conversion_count")
                ),
                "attributedGrossRevenue": _journey_decimal_text(
                    row.get("attributed_gross_revenue")
                ),
                "attributedNetRevenue": _journey_decimal_text(
                    row.get("attributed_net_revenue")
                ),
                "attributedContributionValue": _journey_decimal_text(
                    row.get("attributed_contribution_value")
                ),
                "modelType": _journey_text(row.get("attribution_model_type")),
                "modelVersion": _journey_text(row.get("attribution_model_version")),
                "dataWatermark": _journey_timestamp(
                    row.get("attribution_data_watermark")
                ),
                "evidenceRefs": [
                    run_ref.model_dump(mode="json", exclude_none=True),
                    credit_ref.model_dump(mode="json", exclude_none=True),
                ],
            }
            credits.append(
                JourneyAttributionCredit(
                    record=record,
                    run_ref=run_ref,
                    credit_ref=credit_ref,
                )
            )

        credits = await self._resolve_attribution_credit_subjects(tenant_id, credits)
        if scope_mismatch:
            warnings.append("journey_attribution_scope_mismatch")
        if invalid_records:
            warnings.append("journey_attribution_rows_invalid_or_ambiguous")
        if missing_timestamps:
            warnings.append("journey_attribution_timestamps_missing_or_invalid")
        state = (
            "degraded"
            if credits and warnings
            else "available"
            if credits
            else "unknown"
            if warnings
            else "empty"
        )
        return JourneyAttributionRead(
            credits=tuple(credits),
            state=state,
            warnings=tuple(dict.fromkeys(warnings)),
            truncated=truncated,
        )

    async def _resolve_attribution_credit_subjects(
        self, tenant_id: str, credits: list[JourneyAttributionCredit]
    ) -> list[JourneyAttributionCredit]:
        """Resolve recorded credit IDs to current canonical rows, never run-time state.

        The bounded credit read has already proved tenant/run/journey/version
        membership. Each distinct conversion and touchpoint is fetched once;
        missing, deleted, invalid, or later-than-run rows remain independent
        unknowns without suppressing the admitted model-output credit.
        """
        if not credits:
            return credits
        conversion_source = self._conversion_source or RepositoryJourneyConversionSource()
        touchpoint_source = self._touchpoint_source or RepositoryJourneyTouchpointSource()
        requested = {
            ("conversion", credit.record["recordedConversionId"])
            for credit in credits
        } | {
            ("touchpoint", touchpoint_id)
            for credit in credits
            if (touchpoint_id := credit.record.get("recordedTouchpointId")) is not None
        }
        semaphore = asyncio.Semaphore(_JOURNEY_ATTRIBUTION_REFERENCE_READ_CONCURRENCY)

        async def read_one(kind: str, record_id: str) -> tuple[tuple[str, str], Optional[dict[str, Any]], bool]:
            source = conversion_source if kind == "conversion" else touchpoint_source
            try:
                async with semaphore:
                    raw = await source.get(tenant_id, record_id)
            except Exception:  # noqa: BLE001 - optional exact authority remains unknown
                return (kind, record_id), None, True
            return (kind, record_id), _as_mapping(raw), False

        resolved = dict(
            (key, (row, failed))
            for key, row, failed in await asyncio.gather(
                *(read_one(kind, record_id) for kind, record_id in sorted(requested))
            )
        )
        result: list[JourneyAttributionCredit] = []
        for credit in credits:
            record = credit.record
            run_completed_at = _parse_utc_timestamp(credit.run_ref.observedAt)
            conversion_id = record["recordedConversionId"]
            conversion_row, conversion_failed = resolved[("conversion", conversion_id)]
            conversion_ref: Optional[EvidenceRef] = None
            if conversion_failed:
                conversion_reason = "canonical_conversion_authority_unavailable"
            elif conversion_row is None:
                conversion_reason = "canonical_conversion_row_missing"
            elif (
                conversion_row.get("tenant_id") != tenant_id
                or _journey_text(conversion_row.get("conversion_id")) != conversion_id
            ):
                conversion_reason = "canonical_conversion_scope_mismatch"
            elif (
                _journey_text(conversion_row.get("conversion_status"))
                not in {"confirmed", "adjusted"}
                or conversion_row.get("attribution_eligible") is False
            ):
                conversion_reason = "canonical_conversion_current_status_ineligible"
            elif (
                run_completed_at is None
                or (occurred := _parse_utc_timestamp(conversion_row.get("occurred_at"))) is None
                or occurred > run_completed_at
            ):
                conversion_reason = "canonical_conversion_run_time_conflict"
            else:
                conversion_ref = _journey_conversion_ref(conversion_row)
                conversion_reason = (
                    "current_exact_tenant_conversion_id"
                    if conversion_ref is not None and conversion_ref.observedAt is not None
                    else "canonical_conversion_evidence_missing"
                )
                if conversion_reason != "current_exact_tenant_conversion_id":
                    conversion_ref = None
            record["conversionResolutionState"] = (
                "current_exact_id" if conversion_ref is not None else "unknown"
            )
            record["conversionResolutionReason"] = conversion_reason

            touchpoint_ref: Optional[EvidenceRef] = None
            touchpoint_id = record.get("recordedTouchpointId")
            if touchpoint_id is not None:
                touchpoint_row, touchpoint_failed = resolved[("touchpoint", touchpoint_id)]
                if touchpoint_failed:
                    touchpoint_reason = "canonical_touchpoint_authority_unavailable"
                elif touchpoint_row is None:
                    touchpoint_reason = "canonical_touchpoint_row_missing"
                elif (
                    touchpoint_row.get("tenant_id") != tenant_id
                    or _journey_text(touchpoint_row.get("touchpoint_id")) != touchpoint_id
                ):
                    touchpoint_reason = "canonical_touchpoint_scope_mismatch"
                elif (
                    touchpoint_row.get("privacy_class") == "deleted"
                    or touchpoint_row.get("attribution_eligible") is False
                ):
                    touchpoint_reason = "canonical_touchpoint_current_status_ineligible"
                elif (
                    record.get("campaignId") is not None
                    and _journey_text(touchpoint_row.get("campaign_id")) != record["campaignId"]
                ):
                    touchpoint_reason = "canonical_touchpoint_campaign_conflict"
                elif (
                    run_completed_at is None
                    or (occurred := _parse_utc_timestamp(touchpoint_row.get("occurred_at"))) is None
                    or occurred > run_completed_at
                ):
                    touchpoint_reason = "canonical_touchpoint_run_time_conflict"
                else:
                    touchpoint_ref = _journey_touchpoint_ref(touchpoint_row)
                    touchpoint_reason = (
                        "current_exact_tenant_touchpoint_id"
                        if touchpoint_ref is not None and touchpoint_ref.observedAt is not None
                        else "canonical_touchpoint_evidence_missing"
                    )
                    if touchpoint_reason != "current_exact_tenant_touchpoint_id":
                        touchpoint_ref = None
                record["touchpointResolutionState"] = (
                    "current_exact_id" if touchpoint_ref is not None else "unknown"
                )
                record["touchpointResolutionReason"] = touchpoint_reason
            if conversion_ref is not None:
                record["evidenceRefs"].append(conversion_ref.model_dump(mode="json", exclude_none=True))
            if touchpoint_ref is not None:
                record["evidenceRefs"].append(touchpoint_ref.model_dump(mode="json", exclude_none=True))
            result.append(
                JourneyAttributionCredit(
                    record=record,
                    run_ref=credit.run_ref,
                    credit_ref=credit.credit_ref,
                    conversion_ref=conversion_ref,
                    touchpoint_ref=touchpoint_ref,
                )
            )
        return result

    async def _load_communication_fact_links(
        self,
        tenant_id: str,
        subject_kind: str,
        subject_id: str,
        *,
        after: Optional[datetime] = None,
        before: Optional[datetime] = None,
        as_of: Optional[datetime] = None,
    ) -> CommunicationFactLinkRead:
        """Join only canonical facts that explicitly name this exact subject.

        Communication messages are not matched by sender, campaign, episode
        timing, thread label, or payload text. The canonical fact store is
        queried by its typed episode_id(s) or journey_id(s) field and each
        returned row is checked again at the projection boundary.
        """
        if subject_kind not in {"episode", "journey"} or not subject_id.strip():
            return CommunicationFactLinkRead(reason="communication_subject_reference_invalid")
        if as_of is not None:
            # Event time and durable receipt time both constrain what was
            # knowable at the requested frame anchor.
            as_of_before = as_of + timedelta(microseconds=1)
            before = min(before, as_of_before) if before is not None else as_of_before
        source = self._communication_fact_source or RepositoryCommunicationFactReferenceSource()
        try:
            result = await source.list_for_reference(
                tenant_id,
                subject_kind,
                subject_id,
                after=after,
                before=before,
                received_before=as_of,
                limit=_COMMUNICATION_FACT_CAP + 1,
            )
        except Exception:  # noqa: BLE001 - communication authority degrades independently
            return CommunicationFactLinkRead(
                state="unknown",
                reason="communication_fact_authority_unavailable",
                temporal_state="unknown",
            )
        if (
            not isinstance(result, tuple)
            or len(result) != 2
            or not isinstance(result[0], list)
            or not isinstance(result[1], bool)
        ):
            return CommunicationFactLinkRead(
                state="unknown",
                reason="communication_fact_authority_returned_invalid_result",
            )

        raw_rows, source_complete = result
        truncated = len(raw_rows) > _COMMUNICATION_FACT_CAP or not source_complete
        bounded_rows = raw_rows[:_COMMUNICATION_FACT_CAP]
        rows: list[dict[str, Any]] = []
        evidence_refs: list[EvidenceRef] = []
        invalid_records = False
        tenant_mismatch = False
        missing_evidence = False
        seen_fact_ids: set[str] = set()
        for value in bounded_rows:
            row = _as_mapping(value)
            if row is None:
                invalid_records = True
                continue
            if row.get("tenant_id") != tenant_id:
                tenant_mismatch = True
                continue
            if not _communication_row_references_subject(row, subject_kind, subject_id):
                invalid_records = True
                continue
            occurred_at = _parse_utc_timestamp(row.get("occurred_at"))
            received_at = _parse_utc_timestamp(row.get("received_at"))
            if occurred_at is None or (as_of is not None and received_at is None):
                invalid_records = True
                continue
            if after is not None and occurred_at <= after:
                continue
            if before is not None and occurred_at >= before:
                continue
            if as_of is not None and (
                occurred_at > as_of or received_at is None or received_at > as_of
            ):
                continue
            reference = _communication_fact_evidence(row)
            if reference is None:
                missing_evidence = True
                continue
            if reference.id in seen_fact_ids:
                invalid_records = True
                continue
            seen_fact_ids.add(reference.id)
            rows.append(row)
            evidence_refs.append(reference)

        complete = source_complete and not truncated
        if tenant_mismatch or invalid_records or missing_evidence:
            reason = (
                "communication_fact_tenant_scope_mismatch"
                if tenant_mismatch
                else "communication_fact_reference_rows_invalid_or_ambiguous"
                if invalid_records
                else "communication_fact_evidence_missing"
            )
            state = "degraded"
        elif truncated:
            reason = "communication_fact_reference_read_truncated"
            state = "degraded"
        elif rows:
            reason = "exact_tenant_communication_facts_explicitly_reference_subject"
            # Positive exact links do not establish complete real-world
            # communication inventory or provider message coverage.
            state = "degraded"
        else:
            reason = "no_exact_communication_reference_observed_inventory_unknown"
            state = "unknown"

        temporal_state = (
            "as_of_event_and_receipt_time_applied"
            if as_of is not None
            else "event_time_window_applied"
            if after is not None or before is not None
            else "event_time_order_only"
        )
        return CommunicationFactLinkRead(
            rows=tuple(rows),
            evidence_refs=tuple(_dedupe_evidence_refs(evidence_refs)),
            state=state,
            reason=reason,
            complete=complete,
            truncated=truncated,
            invalid_records=invalid_records,
            tenant_mismatch=tenant_mismatch,
            missing_evidence=missing_evidence,
            temporal_state=temporal_state,
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
        observation_after, observation_before, observation_time_issue = _journey_time_bounds(request)
        anchor_value = request.asOf or context.asOf
        observation_anchor = _parse_utc_timestamp(anchor_value) if anchor_value else None
        anchor_mismatch = bool(
            request.asOf is not None
            and context.asOf is not None
            and _parse_utc_timestamp(request.asOf) != _parse_utc_timestamp(context.asOf)
        )
        if context.tenantId != request.tenantId:
            observation_read = EpisodeObservationRead(
                requested_ids=tuple(
                    _journey_ordered_values(
                        [
                            observation_id
                            for episode in episodes
                            for observation_id in episode.observation_ids
                        ]
                    )
                ),
                available=False,
                tenant_mismatch=True,
                temporal_state="unknown",
                temporal_reason="projection_context_tenant_mismatch",
            )
        elif observation_time_issue is not None or anchor_mismatch or (
            anchor_value is not None and observation_anchor is None
        ):
            observation_read = EpisodeObservationRead(
                requested_ids=tuple(
                    _journey_ordered_values(
                        [
                            observation_id
                            for episode in episodes
                            for observation_id in episode.observation_ids
                        ]
                    )
                ),
                available=False,
                invalid_records=True,
                temporal_state="unknown",
                temporal_reason=(
                    "episode_observation_as_of_context_mismatch"
                    if anchor_mismatch
                    else observation_time_issue
                    or "episode_observation_as_of_anchor_invalid"
                ),
            )
        else:
            observation_read = await self._load_episode_observations(
                request.tenantId,
                episodes,
                after=observation_after,
                before=observation_before,
                as_of=observation_anchor,
            )
        outcome_read = await self._load_episode_outcomes(request.tenantId, episodes)
        touchpoint_read = await self._load_episode_touchpoints(request.tenantId, episodes)
        risk_read = EpisodeRiskFlagRead(reason="episode_risk_slot_not_requested")
        if (
            (request.includeSections is None or "risk_flags" in request.includeSections)
            and
            request.subject.kind == "episode"
            and len(episodes) == 1
            and episodes[0].episode_id == request.subject.id
            and episodes[0].tenant_id == request.tenantId
        ):
            if context.tenantId != request.tenantId:
                risk_read = EpisodeRiskFlagRead(
                    state="unknown",
                    reason="projection_context_tenant_mismatch",
                    tenant_mismatch=True,
                )
            else:
                risk_read = await self._load_episode_risk_flags(request.tenantId, episodes[0])
        communication_read = CommunicationFactLinkRead(
            reason="exact_episode_subject_record_unavailable"
        )
        episode_authority_read = EpisodeAuthorityRead(
            agent_handoffs=AuthorityFactRead(
                available=False,
                complete=False,
            ),
            attribution_links=AuthorityFactRead(
                available=False,
                complete=False,
            ),
        )
        if (
            request.subject.kind == "episode"
            and len(episodes) == 1
            and episodes[0].episode_id == request.subject.id
            and episodes[0].tenant_id == request.tenantId
        ):
            if context.tenantId != request.tenantId:
                communication_read = CommunicationFactLinkRead(
                    reason="projection_context_tenant_mismatch"
                )
            elif request.asOf is not None and context.asOf is not None:
                request_anchor = _parse_utc_timestamp(request.asOf)
                context_anchor = _parse_utc_timestamp(context.asOf)
                if request_anchor != context_anchor:
                    communication_read = CommunicationFactLinkRead(
                        reason="communication_as_of_context_mismatch"
                    )
                else:
                    after, before, issue = _journey_time_bounds(request)
                    anchor = request_anchor
                    communication_read = (
                        CommunicationFactLinkRead(reason=issue)
                        if issue is not None
                        else await self._load_communication_fact_links(
                            request.tenantId,
                            "episode",
                            request.subject.id,
                            after=after,
                            before=before,
                            as_of=anchor,
                        )
                    )
            else:
                after, before, issue = _journey_time_bounds(request)
                anchor_value = request.asOf or context.asOf
                anchor = _parse_utc_timestamp(anchor_value) if anchor_value else None
                communication_read = (
                    CommunicationFactLinkRead(
                        reason="communication_as_of_anchor_invalid"
                    )
                    if anchor_value is not None and anchor is None
                    else CommunicationFactLinkRead(reason=issue)
                    if issue is not None
                    else await self._load_communication_fact_links(
                        request.tenantId,
                        "episode",
                        request.subject.id,
                        after=after,
                        before=before,
                        as_of=anchor,
                    )
                )
            if context.tenantId != request.tenantId:
                unavailable = AuthorityFactRead(
                    available=False,
                    complete=False,
                    tenant_mismatch=True,
                )
                episode_authority_read = EpisodeAuthorityRead(unavailable, unavailable)
            else:
                anchor_value = request.asOf or context.asOf
                anchor = _parse_utc_timestamp(anchor_value) if anchor_value else None
                if anchor_value is not None and anchor is None:
                    unavailable = AuthorityFactRead(
                        available=False,
                        complete=False,
                        invalid_records=True,
                    )
                    episode_authority_read = EpisodeAuthorityRead(unavailable, unavailable)
                else:
                    episode_authority_read = await self._load_episode_authorities(
                        request.tenantId,
                        episodes[0],
                        as_of=anchor,
                    )
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
        if observation_read.namespace_missing_ids:
            warnings.append("episode_observation_source_namespace_untyped_or_missing")
        if observation_read.missing_episode_links:
            warnings.append("episode_observation_typed_reference_missing_for_episode")
        if observation_read.ambiguous_ids:
            warnings.append("episode_observation_source_namespace_or_lineage_ambiguous")
        if observation_read.temporal_reason:
            warnings.append(observation_read.temporal_reason)
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
        if risk_read.state == "degraded":
            warnings.append(risk_read.reason)
        if communication_read.state in {"unknown", "degraded"}:
            warnings.append(communication_read.reason)
        for slot_id, source_read in (
            ("agent_handoffs", episode_authority_read.agent_handoffs),
            ("attribution_links", episode_authority_read.attribution_links),
        ):
            if source_read.read_failed:
                warnings.append(f"episode_{slot_id}_authority_unavailable")
            elif source_read.truncated:
                warnings.append(f"episode_{slot_id}_authority_read_truncated")
            elif source_read.invalid_records:
                warnings.append(f"episode_{slot_id}_authority_records_invalid")
            elif source_read.tenant_mismatch:
                warnings.append(f"episode_{slot_id}_authority_tenant_mismatch")
        warnings.extend(touchpoint_read.warnings)
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
            touchpoint_read=touchpoint_read,
            risk_read=risk_read,
            communication_read=communication_read,
            episode_authority_read=episode_authority_read,
        )
        section_by_id = {section.id: section for section in sections}
        sections = [section_by_id[section_id] for section_id in _EPISODE360_SECTIONS]
        if request.includeSections is not None:
            wanted_sections = set(request.includeSections)
            sections = [section for section in sections if section.id in wanted_sections]
        claims = self._build_claims(
            request,
            episodes,
            outcome_read,
            touchpoint_read,
            risk_read,
            communication_read,
            episode_authority_read,
        )
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
        stage_context = _journey_stage_context(
            steps=rendered_steps,
            step_refs=step_refs,
            steps_available=steps_available,
            step_inventory_complete=step_inventory_complete,
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

        journey_episodes = _journey_episode_context(
            request,
            journey_id=journey_id,
            read=await self._load_journey_episodes(request.tenantId, journey_id),
        )
        journey_episode_claims = journey_episodes.pop("claims")
        warnings.extend(journey_episodes["warnings"])
        journey_touchpoints = _journey_touchpoint_context(
            await self._load_journey_touchpoints(request.tenantId, journey)
        )
        warnings.extend(journey_touchpoints["warnings"])
        journey_conversions = _journey_conversion_context(
            await self._load_journey_conversions(request.tenantId, journey)
        )
        warnings.extend(journey_conversions["warnings"])
        if request.includeSections is None or "journey_attribution" in request.includeSections:
            journey_attribution_read = await self._load_journey_attribution(
                request.tenantId, journey
            )
        else:
            journey_attribution_read = JourneyAttributionRead(
                warnings=("journey_attribution_slot_not_requested",)
            )
        journey_attribution = _journey_attribution_context(journey_attribution_read)
        warnings.extend(journey_attribution["warnings"])

        communication_read = await self._load_communication_fact_links(
            request.tenantId,
            "journey",
            journey_id,
            after=after,
            before=before,
        )
        if communication_read.state in {"unknown", "degraded"}:
            warnings.append(communication_read.reason)
        journey_communications = _communication_fact_link_context(
            communication_read,
            subject_kind="journey",
        )
        action_intents = _journey_action_intent_context(
            await self._load_journey_action_intents(request.tenantId, journey_id),
            tenant_id=request.tenantId,
            journey=journey,
            step_refs=step_refs,
            after=after,
            before=before,
        )
        warnings.extend(action_intents["warnings"])
        dropoffs = _journey_dropoff_context(
            await self._load_journey_dropoffs(request.tenantId, journey_id),
            tenant_id=request.tenantId,
            journey=journey,
            steps=rendered_steps,
            step_refs=step_refs,
            after=after,
            before=before,
        )
        warnings.extend(dropoffs["warnings"])

        sections = _build_journey_sections(
            request=request,
            journey=journey,
            steps=rendered_steps,
            journey_ref=journey_ref,
            step_refs=step_refs,
            steps_available=steps_available,
            step_inventory_complete=step_inventory_complete,
            stage_context=stage_context,
            truncated=truncated,
            warnings=warnings,
            agent_interventions=agent_interventions,
            episode_context=journey_episodes,
            touchpoint_context=journey_touchpoints,
            conversion_context=journey_conversions,
            attribution_context=journey_attribution,
            communication_context=journey_communications,
            action_intent_context=action_intents,
            dropoff_context=dropoffs,
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
                stage_context,
                journey_touchpoints["claims"],
                journey_conversions["claims"],
                journey_attribution["claims"],
                agent_interventions["claims"],
                journey_episode_claims,
                journey_communications["claims"],
                action_intents["claims"],
                dropoffs["claims"],
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
        touchpoint_read: Optional[EpisodeTouchpointRead] = None,
        risk_read: Optional[EpisodeRiskFlagRead] = None,
        communication_read: Optional[CommunicationFactLinkRead] = None,
        episode_authority_read: Optional[EpisodeAuthorityRead] = None,
    ) -> list[ProjectionSection]:
        complete = availability in {"available", "empty"}
        observation_read = observation_read or EpisodeObservationRead(available=False)
        outcome_read = outcome_read or EpisodeOutcomeRead(available=False, read_failed=True)
        touchpoint_read = touchpoint_read or EpisodeTouchpointRead()
        risk_read = risk_read or EpisodeRiskFlagRead()
        communication_read = communication_read or CommunicationFactLinkRead()
        episode_authority_read = episode_authority_read or EpisodeAuthorityRead(
            AuthorityFactRead(available=False, complete=False),
            AuthorityFactRead(available=False, complete=False),
        )
        conversion_context = _episode_conversion_context(outcome_read)
        touchpoint_context = _episode_touchpoint_context(touchpoint_read, episodes)
        risk_context = _episode_risk_context(risk_read)
        communication_context = _communication_fact_link_context(
            communication_read,
            subject_kind="episode",
        )
        exact_episode = (
            episodes[0]
            if request.subject.kind == "episode"
            and len(episodes) == 1
            and episodes[0].episode_id == request.subject.id
            and episodes[0].tenant_id == request.tenantId
            else None
        )
        handoff_context = (
            _episode_authority_context(
                episode_authority_read.agent_handoffs,
                record_type="episode_agent_handoff",
                tenant_id=request.tenantId,
                episode=exact_episode,
            )
            if exact_episode is not None
            else _unknown_episode_slot("exact_episode_subject_required_for_agent_handoffs")
        )
        attribution_link_context = (
            _episode_authority_context(
                episode_authority_read.attribution_links,
                record_type="episode_attribution_link",
                tenant_id=request.tenantId,
                episode=exact_episode,
            )
            if exact_episode is not None
            else _unknown_episode_slot("exact_episode_subject_required_for_attribution_links")
        )
        by_kind = _kind_counts(episodes)
        by_status = _status_distribution(episodes)
        episode_evidence = _collect_evidence(episodes)
        evidence = _dedupe_evidence_refs(
            episode_evidence
            + list(observation_read.evidence_refs)
            + list(communication_read.evidence_refs)
        )
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
            "communicationReferences": {
                key: value
                for key, value in communication_context.items()
                if key != "claims"
            },
            "agentHandoffEvidence": handoff_context,
            "attributionLinkEvidence": attribution_link_context,
            "observationReferences": {
                "state": _episode_observation_read_state(observation_read),
                "coverage": "recorded_episode_ids_only",
                "requestedCount": len(observation_read.requested_ids),
                "resolvedCount": len(observation_read.rows),
                "observations": [
                    _episode_observation_view(
                        request.tenantId,
                        row,
                        reference_refs=_episode_observation_reference_refs_for_id(
                            _journey_text(row.get("observation_id")), observation_read
                        ),
                    )
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
                            touchpoint_read=touchpoint_read,
                            risk_read=risk_read,
                            communication_read=communication_read,
                            episode_authority_read=episode_authority_read,
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
                        "joinedAuthorities": [
                            _EPISODE_RECORD_SOURCE,
                            _EPISODE_OBSERVATION_REFERENCE_SOURCE,
                            _EPISODE_OBSERVATION_SOURCE,
                        ],
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
                            _episode_observation_view(
                                request.tenantId,
                                row,
                                reference_refs=_episode_observation_reference_refs_for_id(
                                    _journey_text(row.get("observation_id")), observation_read
                                ),
                            )
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
                        key: value
                        for key, value in touchpoint_context.items()
                        if key != "claims"
                    },
                    "communicationContext": {
                        **{
                            key: value
                            for key, value in communication_context.items()
                            if key != "claims"
                        },
                    },
                    "agentHandoffs": {
                        **handoff_context,
                        "handoffs": handoff_context.get("records", []),
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
                        **attribution_link_context,
                        "links": attribution_link_context.get("records", []),
                    },
                    "coverage": "partial" if episodes else availability,
                },
                warnings=warnings or None,
            ),
            ProjectionSection(
                id="risk_flags",
                state=risk_context["state"],
                title=_SECTION_TITLES["risk_flags"],
                content=risk_context,
                canonicalAuthorityRefs=["episode_facts", "risk_outputs"],
                warnings=[risk_context["reason"]]
                if isinstance(risk_context.get("reason"), str)
                else None,
            ),
            ProjectionSection(
                id="journey_attribution",
                state="unknown",
                title=_SECTION_TITLES["journey_attribution"],
                content={
                    "state": "unknown",
                    "reason": "journey_attribution_requires_journey_subject",
                    "evidenceRefs": [],
                },
                warnings=["journey_attribution_requires_journey_subject"],
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
                            _episode_observation_view(
                                request.tenantId,
                                row,
                                reference_refs=_episode_observation_reference_refs_for_id(
                                    _journey_text(row.get("observation_id")), observation_read
                                ),
                            )
                            for row in observation_read.rows
                        ],
                        key=lambda row: (
                            row.get("occurredAt") or "9999-12-31T23:59:59+00:00",
                            row["observationId"],
                        ),
                    ),
                    "orderingSemantics": {
                        "basis": "canonical_observation_occurred_at",
                        "meaning": "chronological_order_only",
                        "causality": {
                            "state": "unknown",
                            "reason": "chronological_order_does_not_establish_causality",
                        },
                    },
                    "observationCoverage": {
                        "state": _episode_observation_read_state(observation_read),
                        "coverage": "recorded_episode_ids_only",
                        "requestedCount": len(observation_read.requested_ids),
                        "resolvedCount": len(observation_read.rows),
                        "sourceNamespaceResolvedCount": len(observation_read.rows),
                        "namespaceMissingCount": len(observation_read.namespace_missing_ids),
                        "missingEpisodeReferenceCount": len(
                            observation_read.missing_episode_links
                        ),
                        "resolvedEpisodeReferenceCount": len(
                            observation_read.reference_links
                        ),
                        "ambiguousReferenceCount": len(observation_read.ambiguous_ids),
                        "outOfWindowCount": len(observation_read.out_of_window_ids),
                        "temporal": {
                            "state": (
                                "unknown"
                                if observation_read.temporal_state == "unknown"
                                else "applied"
                            ),
                            "evaluation": (
                                "not_performed"
                                if observation_read.temporal_state == "unknown"
                                else "applied"
                            ),
                            "semantics": observation_read.temporal_state,
                            "reason": observation_read.temporal_reason,
                        },
                        "causality": {
                            "state": "unknown",
                            "reason": "chronological_order_does_not_establish_causality",
                        },
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
        touchpoint_read: Optional[EpisodeTouchpointRead] = None,
        risk_read: Optional[EpisodeRiskFlagRead] = None,
        communication_read: Optional[CommunicationFactLinkRead] = None,
        episode_authority_read: Optional[EpisodeAuthorityRead] = None,
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
        touchpoint_context = _episode_touchpoint_context(
            touchpoint_read or EpisodeTouchpointRead(), episodes
        )
        for touchpoint_id, evidence_refs, linked_episode_ids in touchpoint_context["claims"]:
            if not evidence_refs or not linked_episode_ids:
                continue
            claims.append(
                ClaimEnvelope(
                    id=f"episode360.touchpoint:{quote(touchpoint_id, safe='')}",
                    kind="episode_referenced_journey_touchpoint",
                    subject=request.subject,
                    evidenceRefs=list(evidence_refs),
                    claims=[
                        f"Episode record(s) {', '.join(linked_episode_ids)} explicitly reference journey touchpoint {touchpoint_id!r}; this does not establish an attribution credit or complete journey touchpoint coverage."
                    ],
                    claimState=EpistemicStatus.OBSERVED,
                    domainSlotIds=["touchpoints", "evidence_trace"],
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
        for signal in (risk_read or EpisodeRiskFlagRead()).signals:
            raw_refs = signal.get("evidenceRefs")
            if not isinstance(raw_refs, list):
                continue
            evidence_refs: list[EvidenceRef] = []
            for raw_ref in raw_refs:
                try:
                    evidence_refs.append(EvidenceRef.model_validate(raw_ref))
                except Exception:  # noqa: BLE001 - malformed claim evidence is omitted
                    continue
            signal_id = _journey_text(signal.get("signalId"))
            subject = signal.get("subject")
            subject_kind = _journey_text(subject.get("kind")) if isinstance(subject, dict) else None
            subject_id = _journey_text(subject.get("id")) if isinstance(subject, dict) else None
            if not signal_id or not subject_kind or not subject_id or not evidence_refs:
                continue
            claim_state = _risk_signal_claim_state(signal.get("claimState"))
            claims.append(
                ClaimEnvelope(
                    id=f"episode360.risk-signal:{quote(signal_id, safe='')}",
                    kind="episode_primary_subject_risk_signal",
                    subject=request.subject,
                    evidenceRefs=evidence_refs,
                    claims=[
                        f"Canonical risk signal {signal_id!r} is recorded for the episode's exact primary subject {subject_kind!r}:{subject_id!r}; it does not establish that the episode caused the risk condition."
                    ],
                    claimState=claim_state,
                    domainSlotIds=["risk_flags", "evidence_trace"],
                )
            )
        communication_read = communication_read or CommunicationFactLinkRead()
        if (
            request.subject.kind == "episode"
            and len(episodes) == 1
            and episodes[0].episode_id == request.subject.id
            and episodes[0].tenant_id == request.tenantId
        ):
            episode = episodes[0]
            episode_ref = _episode_record_ref(episode)
            for fact_id, communication_evidence in _communication_fact_link_context(
                communication_read,
                subject_kind="episode",
            )["claims"]:
                claims.append(
                    ClaimEnvelope(
                        id=f"episode360.communication:{quote(fact_id, safe='')}:{quote(episode.episode_id, safe='')}",
                        kind="explicit_episode_communication_reference",
                        subject=request.subject,
                        evidenceRefs=[episode_ref, communication_evidence],
                        claims=[
                            f"Canonical communication fact {fact_id!r} explicitly references episode {episode.episode_id!r}.",
                            "This typed reference does not establish communication content, causality, or a complete conversation inventory.",
                        ],
                        claimState=EpistemicStatus.OBSERVED,
                        domainSlotIds=["communications", "evidence_trace"],
                    )
                )
            authority_read = episode_authority_read or EpisodeAuthorityRead()
            for record_type, source_read, slot_id, claim_kind in (
                (
                    "episode_agent_handoff",
                    authority_read.agent_handoffs,
                    "agent_handoffs",
                    "episode_agent_execution_delegation_link",
                ),
                (
                    "episode_attribution_link",
                    authority_read.attribution_links,
                    "attribution_links",
                    "episode_outcome_conversion_credit_link",
                ),
            ):
                context = _episode_authority_context(
                    source_read,
                    record_type=record_type,
                    tenant_id=request.tenantId,
                    episode=episode,
                )
                for row in context["records"]:
                    refs = [EvidenceRef.model_validate(value) for value in row["evidence_refs"]]
                    refs.append(
                        EvidenceRef(
                            id=row["record_id"],
                            type="event",
                            source="episode_journey_authority_records",
                            observedAt=row["recorded_at"],
                        )
                    )
                    claims.append(
                        ClaimEnvelope(
                            id=f"episode360.{slot_id}:{quote(row['record_id'], safe='')}",
                            kind=claim_kind,
                            subject=request.subject,
                            evidenceRefs=refs,
                            claims=[
                                f"Explicit {record_type} record {row['record_id']!r} connects exact episode {episode.episode_id!r} to canonical referenced facts; inventory completeness and current authorization remain unknown."
                            ],
                            claimState=EpistemicStatus.OBSERVED,
                            domainSlotIds=[slot_id, "evidence_trace"],
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
    *,
    journey_id: str,
    read: JourneyEpisodeRead,
) -> dict[str, Any]:
    """Project only tenant-scoped episodes that explicitly name this journey."""
    episodes = [
        episode
        for episode in read.episodes
        if episode.tenant_id == request.tenantId
        and episode.journey_id == journey_id
    ]
    evidence_refs = _dedupe_evidence_refs(
        [ref for episode in episodes for ref in _episode_evidence_refs(episode)]
    )
    warnings: list[str] = []
    if read.read_failed or not read.available:
        reason = "journey_episode_authority_unavailable"
        warnings.append(reason)
    elif read.tenant_mismatch:
        reason = "journey_episode_tenant_scope_mismatch"
        warnings.append(reason)
    elif read.invalid_records:
        reason = "journey_episode_records_invalid_or_ambiguous"
        warnings.append(reason)
    elif read.truncated:
        reason = "journey_episode_scan_truncated"
        warnings.append(reason)
    elif episodes:
        reason = "exact_tenant_episode_records_explicitly_reference_journey"
    else:
        # EpisodeRecord writers are not yet required to emit a journey link,
        # so a clean page without matches cannot establish absence.
        reason = "episode_journey_association_not_recorded_or_not_observed"
        warnings.append(reason)

    if episodes and not read.read_failed and not read.tenant_mismatch and not read.invalid_records:
        # This positive set is exact, but neither legacy-writer coverage nor
        # relationship inventory completeness has an authoritative watermark.
        warnings.append("journey_episode_association_completeness_unknown")

    # ProjectionSection has a closed state vocabulary without ``partial``;
    # positive explicit references therefore use degraded plus precise
    # coverage metadata rather than implying a complete episode inventory.
    state = "degraded" if episodes else "unknown"
    return {
        "state": state,
        "coverage": "explicit_episode_journey_id_references" if episodes else "unknown",
        "requestedSubject": {"kind": request.subject.kind, "id": request.subject.id},
        "episodeCount": None,
        "observedEpisodeCount": len(episodes),
        "associationCompleteness": "unknown",
        "episodeStoreScanComplete": read.scan_complete,
        "freshness": {
            "state": "unknown",
            "reason": "episode_store_freshness_watermark_not_available",
        },
        "episodes": [
            {
                "episodeId": episode.episode_id,
                "kind": episode.kind,
                "status": episode.status,
                "occurredFrom": episode.occurred_from,
                "occurredTo": episode.occurred_to,
                "evidenceRefs": [
                    ref.model_dump(mode="json", exclude_none=True)
                    for ref in _episode_evidence_refs(episode)
                ],
            }
            for episode in episodes
        ],
        "evidenceRefs": [
            ref.model_dump(mode="json", exclude_none=True) for ref in evidence_refs
        ],
        "claims": [
            (episode.episode_id, _episode_record_ref(episode)) for episode in episodes
        ],
        "warnings": warnings,
        "reason": reason,
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


def _episode_touchpoint_context(
    read: EpisodeTouchpointRead, episodes: list[EpisodeRecord]
) -> dict[str, Any]:
    """Render exact episode-to-touchpoint links without asserting completeness.

    The episode record is the relationship witness and the touchpoint row is
    the canonical event witness. Keep this separate from attribution credits,
    which answer a different question and are not joined here.
    """
    episode_ids_by_touchpoint: dict[str, list[str]] = {}
    for episode in episodes:
        for touchpoint_id in episode.journey_touchpoint_ids or []:
            normalized = _journey_text(touchpoint_id)
            if normalized is None:
                continue
            linked_episodes = episode_ids_by_touchpoint.setdefault(normalized, [])
            if episode.episode_id not in linked_episodes:
                linked_episodes.append(episode.episode_id)

    touchpoints: list[dict[str, Any]] = []
    claims: list[tuple[str, tuple[EvidenceRef, ...], tuple[str, ...]]] = []
    for row in read.rows:
        touchpoint_id = _journey_text(row.get("touchpoint_id"))
        evidence = _journey_touchpoint_ref(row)
        if touchpoint_id is None or evidence is None:
            continue
        linked_episode_ids = tuple(episode_ids_by_touchpoint.get(touchpoint_id, ()))
        touchpoints.append(
            {
                "touchpointId": touchpoint_id,
                "occurredAt": _journey_timestamp(row.get("occurred_at")),
                "touchpointType": _journey_text(row.get("touchpoint_type")),
                "interactionType": _journey_text(row.get("interaction_type")),
                "channel": _journey_text(row.get("channel")),
                "journeyRole": _journey_text(row.get("journey_role")),
                "episodeIds": list(linked_episode_ids),
                "evidenceRefs": [evidence.model_dump(mode="json")],
            }
        )
        relationship_refs = [
            _episode_record_ref(episode)
            for episode in episodes
            if episode.episode_id in linked_episode_ids
        ]
        claims.append(
            (
                touchpoint_id,
                tuple(_dedupe_evidence_refs([*relationship_refs, evidence])),
                linked_episode_ids,
            )
        )

    if read.state == "available":
        reason = "exact_episode_record_touchpoint_references_resolved"
    elif read.state == "empty":
        reason = "episode_records_explicitly_name_no_journey_touchpoints"
    else:
        reason = read.warnings[0] if read.warnings else "episode_touchpoint_read_unresolved"
    if read.state == "available":
        coverage = "exact_recorded_episode_references_only"
    elif read.state == "empty":
        coverage = "explicit_episode_reference_set_empty"
    elif touchpoints:
        coverage = "partial_exact_episode_references"
    else:
        coverage = "unknown"

    return {
        "state": read.state,
        "coverage": coverage,
        "touchpointIds": list(read.requested_ids),
        "touchpoints": touchpoints,
        "count": len(touchpoints) if read.state in {"available", "empty"} else None,
        "observedCount": len(touchpoints),
        "evidenceRefs": [ref.model_dump(mode="json") for ref in read.evidence_refs],
        "missingTouchpointIds": list(read.missing_ids),
        "warnings": list(read.warnings),
        "reason": reason,
        "relationshipAuthority": _EPISODE_RECORD_SOURCE,
        "touchpointAuthority": _JOURNEY_TOUCHPOINT_SOURCE,
        "freshness": {
            "state": "unknown",
            "evaluation": "not_performed",
            "reason": "episode_and_touchpoint_watermarks_not_compared",
        },
        "policy": {
            "state": "unknown",
            "evaluation": "not_performed",
            "reason": "episode_touchpoint_policy_evaluation_not_performed_by_projection",
        },
        "claims": claims,
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


def _journey_attribution_context(read: JourneyAttributionRead) -> dict[str, Any]:
    """Expose exact active-run credits with explicit history and policy gaps."""
    credits = [credit.record for credit in read.credits]
    evidence_refs = [
        ref.model_dump(mode="json", exclude_none=True)
        for credit in read.credits
        for ref in (
            credit.run_ref,
            credit.credit_ref,
            credit.conversion_ref,
            credit.touchpoint_ref,
        )
        if ref is not None
    ]
    if read.state == "available":
        reason = "active_attribution_credits_resolved_through_exact_tenant_journey_runs"
        coverage = "active_completed_run_links_only"
    elif read.state == "empty":
        reason = "no_active_attribution_credit_rows_for_exact_tenant_journey"
        coverage = "active_completed_run_links_only"
    elif read.warnings:
        reason = read.warnings[0]
        coverage = "partial" if credits else "unknown"
    else:
        reason = "journey_attribution_read_unknown"
        coverage = "unknown"
    return {
        "state": read.state,
        "coverage": coverage,
        "reason": reason,
        "count": len(credits) if read.state in {"available", "empty"} else None,
        "observedCount": len(credits),
        "credits": credits,
        "history": {
            "state": "unknown",
            "reason": "inactive_or_historical_attribution_runs_not_loaded",
        },
        "freshness": {
            "state": "unknown",
            "evaluation": "not_performed",
            "reason": "attribution_freshness_threshold_not_configured",
        },
        "policy": {
            "state": "unknown",
            "evaluation": "not_performed",
            "reason": "journey_attribution_policy_not_evaluated_by_projection",
        },
        "limitations": [
            "credit_weights_are_canonical_model_outputs_not_independent_causal_proof",
            "current_exact_id_subject_reads_do_not_establish_state_at_run_time",
            "unresolved_conversion_and_touchpoint_refs_remain_unknown",
            "inactive_and_historical_attribution_runs_are_not_loaded",
        ],
        "evidenceRefs": evidence_refs,
        "warnings": list(read.warnings),
        "claims": [
            (
                credit.record["creditId"],
                credit.run_ref,
                credit.credit_ref,
                credit.conversion_ref,
                credit.touchpoint_ref,
            )
            for credit in read.credits
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


def _journey_dropoff_context(
    read: JourneyAuthorityRead,
    *,
    tenant_id: str,
    journey: dict[str, Any],
    steps: list[dict[str, Any]],
    step_refs: list[EvidenceRef],
    after: Optional[datetime],
    before: Optional[datetime],
) -> dict[str, Any]:
    """Expose only exact current-version facts backed by journey_abandoned steps."""
    source = read.dropoffs
    journey_id = _journey_text(journey.get("journey_id"))
    version_id = _journey_text(journey.get("journey_version_id"))
    exact_step_refs = {ref.id: ref for ref in step_refs}
    step_rows: dict[str, list[dict[str, Any]]] = {}
    for step in steps:
        step_id = _journey_text(step.get("step_id"))
        if step_id:
            step_rows.setdefault(step_id, []).append(step)

    records: list[dict[str, Any]] = []
    evidence_refs: list[EvidenceRef] = []
    claims: list[tuple[str, list[EvidenceRef]]] = []
    warnings: list[str] = []
    if not source.available or source.read_failed:
        warnings.append("journey_dropoff_authority_unavailable")
    if source.truncated:
        warnings.append("journey_dropoff_authority_read_truncated")
    if source.invalid_records or source.tenant_mismatch:
        warnings.append("journey_dropoff_authority_read_invalid_or_unscoped")
    if not source.complete and not any(
        (source.truncated, source.invalid_records, source.tenant_mismatch, source.read_failed)
    ):
        warnings.append("journey_dropoff_authority_coverage_incomplete")

    for raw in source.records:
        try:
            record = JourneyDropoffRecord.model_validate(raw)
        except Exception:  # noqa: BLE001 - malformed facts cannot support a dropoff claim
            warnings.append("journey_dropoff_record_invalid")
            continue
        if (
            record.tenant_id != tenant_id
            or record.journey_id != journey_id
            or record.journey_version_id != version_id
            or record.activity_type != "journey_abandoned"
            or journey.get("is_current") is not True
        ):
            warnings.append("journey_dropoff_current_version_or_scope_mismatch")
            continue
        if after is not None and record.occurred_at < after:
            continue
        if before is not None and record.occurred_at >= before:
            continue
        matches = step_rows.get(record.step_id, [])
        if (
            len(matches) != 1
            or _journey_text(matches[0].get("activity_id")) != record.activity_id
            or _journey_text(matches[0].get("activity_type")) != "journey_abandoned"
            or _journey_timestamp(matches[0].get("occurred_at")) != record.occurred_at.isoformat()
        ):
            warnings.append("journey_dropoff_step_not_resolved_in_current_projection_page")
            continue
        record_version_ref = any(
            ref.source == _JOURNEY_VERSION_SOURCE
            and ref.id == version_id
            and ref.uri == f"store://journey_versions/{version_id}"
            for ref in record.evidence_refs
        )
        record_step_ref = any(
            ref.source == _JOURNEY_STEP_SOURCE
            and ref.id == record.step_id
            and ref.uri == f"store://journey_steps/{record.step_id}"
            for ref in record.evidence_refs
        )
        canonical_step_ref = exact_step_refs.get(record.step_id)
        if (
            not record_version_ref
            or not record_step_ref
            or canonical_step_ref is None
            or canonical_step_ref.uri != f"store://journey_steps/{record.step_id}"
        ):
            warnings.append("journey_dropoff_canonical_evidence_unresolved")
            continue
        authority_ref = EvidenceRef(
            id=record.record_id,
            type="event",
            source="episode_journey_authority_records",
            observedAt=record.recorded_at.isoformat(),
        )
        refs = _dedupe_evidence_refs(
            [authority_ref, *record.evidence_refs, canonical_step_ref]
        )
        evidence_refs.extend(refs)
        records.append(
            {
                "recordId": record.record_id,
                "journeyId": record.journey_id,
                "journeyVersionId": record.journey_version_id,
                "stepId": record.step_id,
                "activityId": record.activity_id,
                "activityType": record.activity_type,
                "occurredAt": record.occurred_at.isoformat(),
                "recordedAt": record.recorded_at.isoformat(),
                "assertion": "explicit_journey_abandoned_event",
                "evidenceRefs": [ref.model_dump(mode="json") for ref in refs],
            }
        )
        claims.append((record.record_id, refs))

    if records:
        state = "degraded" if warnings else "available"
        reason = (
            warnings[0]
            if warnings
            else "exact_current_journey_version_abandonment_step_joined"
        )
        coverage = "explicit_abandonment_facts_observed"
    else:
        state = "unknown"
        reason = (
            warnings[0]
            if warnings
            else "no_explicit_journey_abandoned_fact_recorded_absence_not_established"
        )
        coverage = "unknown"
    return {
        "state": state,
        "coverage": coverage,
        "reason": reason,
        "authority": "episode_journey_authority_records",
        "joinedAuthorities": [
            "episode_journey_authority_records",
            _JOURNEY_VERSION_SOURCE,
            _JOURNEY_STEP_SOURCE,
        ],
        "records": records,
        "observedCount": len(records),
        "count": len(records) if source.complete and not warnings else None,
        "evidenceRefs": [
            ref.model_dump(mode="json", exclude_none=True)
            for ref in _dedupe_evidence_refs(evidence_refs)
        ],
        "temporal": {
            "state": "bounded_by_journey_request_window",
            "after": after.isoformat() if after is not None else None,
            "before": before.isoformat() if before is not None else None,
        },
        "freshness": {
            "state": "unknown",
            "reason": "journey_dropoff_authority_watermark_unavailable",
        },
        "policy": {
            "state": "unknown",
            "reason": "journey_dropoff_policy_disposition_not_evaluated",
        },
        "sourceReadComplete": source.complete and not warnings,
        "warnings": list(dict.fromkeys(warnings)),
        "claims": claims,
    }


def _journey_action_intent_context(
    read: JourneyAuthorityRead,
    *,
    tenant_id: str,
    journey: dict[str, Any],
    step_refs: list[EvidenceRef],
    after: Optional[datetime],
    before: Optional[datetime],
) -> dict[str, Any]:
    """Expose exact current-version, non-executable intent records only."""
    source = read.action_intents
    journey_id = _journey_text(journey.get("journey_id"))
    version_id = _journey_text(journey.get("journey_version_id"))
    step_ids = {ref.id for ref in step_refs}
    records: list[dict[str, Any]] = []
    refs: list[EvidenceRef] = []
    claims: list[tuple[str, list[EvidenceRef]]] = []
    warnings: list[str] = []
    if not source.available or source.read_failed:
        warnings.append("journey_action_intent_authority_unavailable")
    if source.truncated:
        warnings.append("journey_action_intent_read_truncated")
    if source.invalid_records or source.tenant_mismatch:
        warnings.append("journey_action_intent_read_invalid_or_unscoped")
    for raw in source.records:
        try:
            record = JourneyActionIntentRecord.model_validate(raw)
        except Exception:  # noqa: BLE001 - a malformed intent cannot support a claim
            warnings.append("journey_action_intent_record_invalid")
            continue
        if (
            record.tenant_id != tenant_id
            or record.journey_id != journey_id
            or record.journey_version_id != version_id
            or record.status != "proposed"
            or journey.get("is_current") is not True
        ):
            warnings.append("journey_action_intent_current_version_or_state_unverified")
            continue
        if after is not None and record.occurred_at < after:
            continue
        if before is not None and record.occurred_at >= before:
            continue
        version_refs = [
            ref for ref in record.evidence_refs
            if ref.id == version_id
            and ref.uri == f"store://journey_versions/{version_id}"
        ]
        action_step_refs = [
            ref for ref in record.evidence_refs
            if ref.id in step_ids
            and ref.source == "journey_steps"
            and ref.uri == f"store://journey_steps/{ref.id}"
        ]
        if not version_refs or not action_step_refs:
            warnings.append("journey_action_intent_version_or_page_step_evidence_unresolved")
            continue
        row_ref = EvidenceRef(
            id=record.record_id,
            type="event",
            source="episode_journey_authority_records",
            observedAt=record.recorded_at.isoformat(),
        )
        row_refs = [row_ref, *record.evidence_refs]
        refs.extend(row_refs)
        records.append(
            {
                "recordId": record.record_id,
                "actionIntentId": record.action_intent_id,
                "recommendationId": record.recommendation_id,
                "actionKey": record.action_key,
                "actionType": record.action_type,
                "label": record.label,
                "status": record.status,
                "actorRef": record.actor_ref,
                "policyDecisionRef": record.policy_decision_ref,
                "nonExecutable": True,
                "occurredAt": record.occurred_at.isoformat(),
                "recordedAt": record.recorded_at.isoformat(),
                "evidenceRefs": [ref.model_dump(mode="json") for ref in row_refs],
            }
        )
        claims.append((record.record_id, row_refs))
    if records:
        state = "degraded" if warnings else "available"
        reason = (
            warnings[0]
            if warnings
            else "exact_current_journey_version_action_intents_with_step_evidence"
        )
    else:
        state = "degraded" if warnings else "unknown"
        reason = warnings[0] if warnings else "no_explicit_current_journey_action_intent_recorded"
    return {
        "state": state,
        "coverage": "recorded_non_executable_intents_only" if records else "unknown",
        "reason": reason,
        "records": records,
        "observedCount": len(records),
        "count": len(records) if source.complete and not warnings else None,
        "evidenceRefs": [ref.model_dump(mode="json") for ref in _dedupe_evidence_refs(refs)],
        "policy": {
            "state": "unknown",
            "reason": "action_intent_policy_decision_and_current_authority_not_re_evaluated",
        },
        "freshness": {"state": "unknown", "reason": "action_intent_watermark_unavailable"},
        "inventoryComplete": False,
        "sourceReadComplete": source.complete and not warnings,
        "warnings": list(dict.fromkeys(warnings)),
        "claims": claims,
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
    stage_context: dict[str, Any],
    truncated: bool,
    warnings: list[str],
    agent_interventions: dict[str, Any],
    episode_context: dict[str, Any],
    touchpoint_context: dict[str, Any],
    conversion_context: dict[str, Any],
    attribution_context: dict[str, Any],
    communication_context: dict[str, Any],
    action_intent_context: dict[str, Any],
    dropoff_context: dict[str, Any],
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
    episode_evidence = episode_context["evidenceRefs"]
    touchpoint_evidence = touchpoint_context["evidenceRefs"]
    conversion_evidence = conversion_context["evidenceRefs"]
    attribution_evidence = attribution_context["evidenceRefs"]
    communication_evidence = communication_context["evidenceRefs"]
    required_slot_coverage = _journey_required_slot_coverage(
        journey=journey,
        steps=steps,
        journey_ref=journey_ref,
        step_refs=step_refs,
        steps_available=steps_available,
        step_inventory_complete=step_inventory_complete,
        stage_context=stage_context,
        episode_context=episode_context,
        agent_interventions=agent_interventions,
        touchpoint_context=touchpoint_context,
        conversion_context=conversion_context,
        attribution_context=attribution_context,
        communication_context=communication_context,
        action_intent_context=action_intent_context,
        dropoff_context=dropoff_context,
    )
    complete_evidence = step_state in {"available", "empty"} and episode_context[
        "state"
    ] in {"available", "empty"} and touchpoint_context["state"] in {
        "available",
        "empty",
    } and bool(communication_context.get("sourceReadComplete"))
    outcome_state = conversion_context["state"]
    outcome_content = {
        "recordedConversionIds": conversion_context["conversionIds"],
        "conversionTruthState": conversion_context["state"],
        "conversions": conversion_context["conversions"],
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
            canonicalAuthorityRefs=[
                "episode_journey_authority_records",
                "journey_versions",
                "journey_steps",
            ],
            content={
                "journeyVersion": version_evidence[0],
                "journeySteps": step_evidence,
                "sourceEventIds": _journey_values(journey.get("event_ids")),
                "evidenceRefs": (
                    version_evidence
                    + step_evidence
                    + touchpoint_evidence
                    + conversion_evidence
                    + attribution_evidence
                    + communication_evidence
                    + action_intent_context["evidenceRefs"]
                    + dropoff_context["evidenceRefs"]
                ),
                "rawStepEvidenceSummaryIncluded": False,
                "journeyEpisodes": episode_evidence,
                "journeyTouchpoints": touchpoint_evidence,
                "journeyAttribution": attribution_evidence,
                "recommendedActions": {
                    key: value for key, value in action_intent_context.items() if key != "claims"
                },
                "journeyDropoffs": {
                    key: value for key, value in dropoff_context.items() if key != "claims"
                },
                "journeyCommunications": {
                    key: value
                    for key, value in communication_context.items()
                    if key != "claims"
                },
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
            canonicalAuthorityRefs=[
                "episode_journey_authority_records",
                "journey_steps",
            ],
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
                    "communications": {
                        key: value
                        for key, value in communication_context.items()
                        if key != "claims"
                    },
                    "recommendedActions": {
                        key: value for key, value in action_intent_context.items() if key != "claims"
                    },
                    "dropoffs": {
                        key: value for key, value in dropoff_context.items() if key != "claims"
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
            warnings=conversion_context["warnings"] or None,
        ),
        "journey_attribution": ProjectionSection(
            id="journey_attribution",
            state=attribution_context["state"],
            title=_SECTION_TITLES["journey_attribution"],
            content=attribution_context,
            canonicalAuthorityRefs=[
                "attribution_runs",
                "attribution_credits",
                *(
                    ["canonical_conversions"]
                    if any(
                        credit.get("conversionResolutionState") == "current_exact_id"
                        for credit in attribution_context["credits"]
                    )
                    else []
                ),
                *(
                    ["touchpoints"]
                    if any(
                        credit.get("touchpointResolutionState") == "current_exact_id"
                        for credit in attribution_context["credits"]
                    )
                    else []
                ),
            ],
            warnings=attribution_context["warnings"] or None,
        ),
        "risk_flags": ProjectionSection(
            id="risk_flags",
            state="unknown",
            title=_SECTION_TITLES["risk_flags"],
            content={
                "state": "unknown",
                "reason": "episode_risk_flags_require_exact_episode_subject",
                "evidenceRefs": [],
            },
            warnings=["episode_risk_flags_require_exact_episode_subject"],
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
    """Type supported source-role markers while leaving stage boundaries unknown.

    The current canonical step row carries a versioned source-classifier role.
    Only the closed version-3.0 vocabulary is typed here. The inventory
    completeness flag applies to persisted role markers on the exact current
    journey version; it does not imply complete business-stage coverage.
    """
    refs_by_step_id = {ref.id: ref for ref in step_refs}
    observations: list[dict[str, Any]] = []
    missing_evidence = False
    invalid_role = False
    typed_role_count = 0
    untyped_role_count = 0
    role_marker_count = 0
    for row in steps:
        role = _journey_text(row.get("journey_role"))
        if role is None:
            continue
        role_marker_count += 1
        # Persisted role labels are source evidence, so keep the projection
        # bounded and leave unsupported/open vocabulary untyped.
        if len(role) > 128:
            invalid_role = True
            untyped_role_count += 1
            continue
        step_id = _journey_text(row.get("step_id"))
        evidence = refs_by_step_id.get(step_id or "")
        if evidence is None:
            missing_evidence = True
            untyped_role_count += 1
            continue
        position = _journey_int(row.get("step_position"), -1)
        occurred_at = _parse_utc_timestamp(row.get("occurred_at"))
        typed_marker: Optional[JourneySourceRoleMarker] = None
        try:
            typed_marker = JourneySourceRoleMarker.model_validate(
                {
                    "tenant_id": row.get("tenant_id"),
                    "journey_id": row.get("journey_id"),
                    "journey_version_id": row.get("journey_version_id"),
                    "step_id": step_id,
                    "activity_id": _journey_text(row.get("activity_id")),
                    "step_position": position,
                    "journey_role": role,
                    "source_classifier_version": _journey_text(
                        row.get("source_classifier_version")
                    ),
                    "occurred_at": occurred_at,
                    "evidence_ref": evidence,
                }
            )
        except Exception:  # noqa: BLE001 - unversioned or unsupported labels stay raw
            untyped_role_count += 1
        else:
            typed_role_count += 1
        observations.append(
            {
                "stepId": step_id,
                "position": position if position >= 0 else None,
                "journeyRole": role,
                "typedRole": typed_marker.journey_role.value if typed_marker else None,
                "activityId": (
                    typed_marker.activity_id
                    if typed_marker
                    else _journey_text(row.get("activity_id"))
                ),
                "roleTaxonomy": (
                    {
                        "authority": "services/api/journeys/traffic/classifier.py:SOURCE_CLASSIFIER_VERSION",
                        "version": typed_marker.source_classifier_version,
                    }
                    if typed_marker
                    else None
                ),
                "sourceClassificationId": _journey_text(
                    row.get("source_classification_id")
                ),
                "occurredAt": (
                    typed_marker.occurred_at.isoformat()
                    if typed_marker
                    else _journey_timestamp(row.get("occurred_at"))
                ),
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
    if typed_role_count:
        role_taxonomy_state = "available" if untyped_role_count == 0 else "partial"
    elif role_marker_count:
        role_taxonomy_state = "unknown"
    elif step_inventory_complete:
        role_taxonomy_state = "not_observed"
    else:
        role_taxonomy_state = "unknown"

    marker_inventory_state = (
        "unknown"
        if not steps_available
        else "complete"
        if step_inventory_complete
        else "partial"
    )
    marker_inventory_coverage = (
        "complete_current_version_step_inventory"
        if step_inventory_complete
        else "bounded_or_filtered_current_version_step_page"
        if steps_available
        else "unavailable"
    )
    if not steps_available:
        state = "unknown"
        coverage = "unknown"
        reason = "journey_step_authority_unavailable"
    elif invalid_role or missing_evidence or untyped_role_count:
        state = "degraded"
        coverage = "untyped_source_role_markers"
        reason = (
            "journey_role_marker_invalid_or_missing_exact_step_evidence"
            if invalid_role or missing_evidence
            else "journey_role_taxonomy_version_or_value_unresolved"
        )
    elif observations:
        state = "partial"
        coverage = "typed_source_role_markers"
        reason = (
            "versioned_source_role_markers_joined_to_exact_current_version_steps;"
            "stage_boundaries_and_stage_completeness_are_unresolved"
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
        "authority": _JOURNEY_STEP_SOURCE,
        "roleTaxonomyState": role_taxonomy_state,
        "roleTaxonomyAuthority": "services/api/journeys/traffic/classifier.py:SOURCE_CLASSIFIER_VERSION",
        "roleTaxonomyVersion": "3.0" if typed_role_count else None,
        "stageTaxonomyState": "unknown",
        "stageTaxonomyReason": "source_role_markers_do_not_define_business_stage_boundaries",
        "stageCompletenessState": "unknown",
        "stageCompletenessReason": "no_canonical_business_stage_inventory_or_boundary_authority",
        "inventoryComplete": step_inventory_complete,
        "roleMarkerInventory": {
            "state": marker_inventory_state,
            "coverage": marker_inventory_coverage,
            "authority": _JOURNEY_STEP_SOURCE,
            "observedStepCount": len(steps),
            "stepCount": len(steps) if step_inventory_complete else None,
            "observedRoleMarkerCount": role_marker_count,
            "typedRoleMarkerCount": typed_role_count,
            "untypedRoleMarkerCount": untyped_role_count,
            "evidenceRefs": (
                complete_refs
                if step_inventory_complete
                else observed_refs
            ),
        },
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
    coverage = {
        slot_id: {
            "state": journey_summary_state if slot_id == "journey_summary" else "unknown",
            "coverage": "unknown",
            "reason": reason if slot_id == "journey_summary" else "journey_version_unavailable",
            "evidenceRefs": [],
        }
        for slot_id in _JOURNEY_REQUIRED_SLOT_IDS
    }
    coverage["stages"].update(
        {
            "roleTaxonomyState": "unknown",
            "roleTaxonomyAuthority": "services/api/journeys/traffic/classifier.py:SOURCE_CLASSIFIER_VERSION",
            "roleTaxonomyVersion": None,
            "stageTaxonomyState": "unknown",
            "stageTaxonomyReason": "current_journey_step_authority_unavailable",
            "stageCompletenessState": "unknown",
            "stageCompletenessReason": "no_canonical_business_stage_inventory_or_boundary_authority",
            "roleMarkerInventory": {
                "state": "unknown",
                "coverage": "unavailable",
                "authority": _JOURNEY_STEP_SOURCE,
                "observedStepCount": 0,
                "stepCount": None,
                "observedRoleMarkerCount": 0,
                "typedRoleMarkerCount": 0,
                "untypedRoleMarkerCount": 0,
                "evidenceRefs": [],
            },
        }
    )
    return coverage


def _journey_required_slot_coverage(
    *,
    journey: dict[str, Any],
    steps: list[dict[str, Any]],
    journey_ref: EvidenceRef,
    step_refs: list[EvidenceRef],
    steps_available: bool,
    step_inventory_complete: bool,
    stage_context: dict[str, Any],
    episode_context: dict[str, Any],
    agent_interventions: dict[str, Any],
    touchpoint_context: dict[str, Any],
    conversion_context: dict[str, Any],
    attribution_context: dict[str, Any],
    communication_context: dict[str, Any],
    action_intent_context: dict[str, Any],
    dropoff_context: dict[str, Any],
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
    episode_evidence = [
        ref for ref in episode_context.get("evidenceRefs", []) if isinstance(ref, dict)
    ]
    attribution_evidence = [
        ref for ref in attribution_context.get("evidenceRefs", []) if isinstance(ref, dict)
    ]
    communication_evidence = [
        ref for ref in communication_context.get("evidenceRefs", []) if isinstance(ref, dict)
    ]
    action_intent_evidence = [
        ref for ref in action_intent_context.get("evidenceRefs", []) if isinstance(ref, dict)
    ]
    dropoff_evidence = [
        ref for ref in dropoff_context.get("evidenceRefs", []) if isinstance(ref, dict)
    ]
    all_evidence = (
        version_evidence
        + step_evidence
        + episode_evidence
        + touchpoint_evidence
        + conversion_evidence
        + attribution_evidence
        + communication_evidence
        + action_intent_evidence
        + dropoff_evidence
    )

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

    attribution_slot = {
        "state": attribution_context["state"],
        "coverage": attribution_context["coverage"],
        "reason": attribution_context["reason"],
        "evidenceRefs": attribution_evidence,
    }

    episode_slot = {
        "state": episode_context["state"],
        "coverage": episode_context["coverage"],
        "reason": episode_context["reason"],
        "associationCompleteness": episode_context["associationCompleteness"],
        "evidenceRefs": episode_evidence,
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
            "roleTaxonomyState": stage_context["roleTaxonomyState"],
            "roleTaxonomyAuthority": stage_context["roleTaxonomyAuthority"],
            "roleTaxonomyVersion": stage_context["roleTaxonomyVersion"],
            "stageTaxonomyState": stage_context["stageTaxonomyState"],
            "stageTaxonomyReason": stage_context["stageTaxonomyReason"],
            "stageCompletenessState": stage_context["stageCompletenessState"],
            "stageCompletenessReason": stage_context["stageCompletenessReason"],
            "roleMarkerInventory": stage_context["roleMarkerInventory"],
            "evidenceRefs": stage_context["evidenceRefs"],
        },
        "episodes": episode_slot,
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
            "state": communication_context["state"],
            "coverage": communication_context["coverage"],
            "reason": communication_context["reason"],
            "evidenceRefs": communication_evidence,
            "temporal": communication_context["temporal"],
            "freshness": communication_context["freshness"],
            "policy": communication_context["policy"],
        },
        "dropoffs": {
            "state": dropoff_context["state"],
            "coverage": dropoff_context["coverage"],
            "reason": dropoff_context["reason"],
            "authority": dropoff_context["authority"],
            "joinedAuthorities": dropoff_context["joinedAuthorities"],
            "evidenceRefs": dropoff_evidence,
            "temporal": dropoff_context["temporal"],
            "freshness": dropoff_context["freshness"],
            "policy": dropoff_context["policy"],
        },
        "conversions": conversion_slot,
        "attribution": {
            **attribution_slot,
        },
        "recommended_actions": {
            "state": action_intent_context["state"],
            "coverage": action_intent_context["coverage"],
            "reason": action_intent_context["reason"],
            "evidenceRefs": action_intent_evidence,
            "policy": action_intent_context["policy"],
            "freshness": action_intent_context["freshness"],
        },
        "evidence_trace": {
            "state": "degraded",
            "coverage": "partial",
            "reason": "journey_version_and_exact_reference_row_evidence_available_broader_source_provenance_unresolved",
            "evidenceRefs": all_evidence,
        },
    }


def _build_journey_claims(
    request: ProjectionRequest,
    journey: dict[str, Any],
    steps: list[dict[str, Any]],
    journey_ref: EvidenceRef,
    stage_context: dict[str, Any],
    touchpoint_claims: list[tuple[str, EvidenceRef]],
    conversion_claims: list[tuple[str, EvidenceRef]],
    attribution_claims: list[
        tuple[
            str,
            EvidenceRef,
            EvidenceRef,
            Optional[EvidenceRef],
            Optional[EvidenceRef],
        ]
    ],
    agent_intervention_claims: list[tuple[str, EvidenceRef]],
    episode_claims: list[tuple[str, EvidenceRef]],
    communication_claims: list[tuple[str, EvidenceRef]],
    action_intent_claims: list[tuple[str, list[EvidenceRef]]],
    dropoff_claims: list[tuple[str, list[EvidenceRef]]],
) -> list[ClaimEnvelope]:
    journey_id = _journey_text(journey.get("journey_id")) or request.subject.id
    version_id = _journey_text(journey.get("journey_version_id")) or journey_id
    version_slots = _journey_slot_ids_for_sections({"summary", "state", "evidence"})
    step_slots = _journey_slot_ids_for_sections({"timeline", "interactions", "evidence"})
    stage_slots = _journey_slot_ids_for_sections({"stages"})
    touchpoint_slots = _journey_slot_ids_for_sections({"timeline", "evidence"})
    episode_slots = _journey_slot_ids_for_sections({"episode_context"})
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
    for record_id, refs in dropoff_claims:
        if len(claims) >= 301:
            break
        claims.append(
            ClaimEnvelope(
                id=f"episode360:{journey_id}:{version_id}:dropoff:{quote(record_id, safe='')}",
                kind="journey_explicit_abandonment_fact",
                subject=request.subject,
                evidenceRefs=refs,
                claims=[
                    f"Current journey version {version_id!r} has a canonical dropoff fact linked to an explicit journey_abandoned step ({record_id!r}); the cause, permanence, and absence of later activity are not established."
                ],
                claimState=EpistemicStatus.OBSERVED,
                domainSlotIds=["dropoffs", "evidence_trace"],
            )
        )
    for record_id, refs in action_intent_claims:
        if len(claims) >= 301:
            break
        claims.append(
            ClaimEnvelope(
                id=f"episode360:{journey_id}:{version_id}:action-intent:{quote(record_id, safe='')}",
                kind="journey_recorded_non_executable_action_intent",
                subject=request.subject,
                evidenceRefs=refs,
                claims=[
                    f"Current journey version {version_id!r} has an explicit, non-executable action recommendation record {record_id!r}; execution permission and outcome are not established."
                ],
                claimState=EpistemicStatus.OBSERVED,
                domainSlotIds=["recommended_actions", "evidence_trace"],
            )
        )
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
        for observation in stage_context["stageObservations"]:
            if len(claims) >= 201:
                break
            step_id = observation.get("stepId")
            role = observation.get("journeyRole")
            evidence_refs = observation.get("evidenceRefs")
            if not isinstance(step_id, str) or not isinstance(role, str):
                continue
            try:
                evidence = EvidenceRef.model_validate(evidence_refs[0])
            except (IndexError, TypeError, ValueError):
                continue
            typed_role = observation.get("typedRole")
            version = (
                observation.get("roleTaxonomy", {}).get("version")
                if isinstance(observation.get("roleTaxonomy"), dict)
                else None
            )
            claims_text = (
                f"Persisted journey step {step_id!r} has source-classified acquisition role "
                f"{typed_role!r} under classifier version {version}; this marker does not "
                "define business-stage boundaries or establish stage completeness."
                if isinstance(typed_role, str) and isinstance(version, str)
                else f"Persisted journey step {step_id!r} has explicit journey_role marker "
                f"{role!r}; its taxonomy, stage boundaries, and stage completeness remain unknown."
            )
            claims.append(
                ClaimEnvelope(
                    id=f"episode360:{journey_id}:{version_id}:stage-marker:{step_id}",
                    kind="explicit_journey_role_marker",
                    subject=request.subject,
                    evidenceRefs=[evidence],
                    claims=[claims_text],
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
    for credit_id, run_evidence, credit_evidence, conversion_evidence, touchpoint_evidence in attribution_claims:
        if len(claims) >= 301:
            break
        claims.append(
            ClaimEnvelope(
                id=f"episode360:{journey_id}:{version_id}:attribution-credit:{credit_id}",
                kind="journey_attribution_credit",
                subject=request.subject,
                evidenceRefs=[
                    journey_ref,
                    run_evidence,
                    credit_evidence,
                    *(
                        ref
                        for ref in (conversion_evidence, touchpoint_evidence)
                        if ref is not None
                    ),
                ],
                claims=[
                    "A same-tenant completed active attribution run explicitly links this model-output credit to the canonical journey.",
                    "The credit is not independent causal proof; any exact canonical subject reads establish current references only, not their state at attribution-run time.",
                    "Inactive and historical run completeness, freshness, and policy disposition remain unknown.",
                ],
                claimState=EpistemicStatus.OBSERVED,
                domainSlotIds=["attribution"],
            )
        )
    for episode_id, evidence in episode_claims:
        if len(claims) >= 301:
            break
        claims.append(
            ClaimEnvelope(
                id=f"episode360:{journey_id}:{version_id}:episode:{episode_id}",
                kind="explicit_journey_episode_reference",
                subject=request.subject,
                evidenceRefs=[evidence],
                claims=[
                    f"Tenant-scoped episode record {episode_id!r} explicitly references this journey.",
                    "This recorded link does not prove complete journey episode inventory.",
                ],
                claimState=EpistemicStatus.OBSERVED,
                domainSlotIds=episode_slots,
            )
        )
    for fact_id, communication_evidence in communication_claims:
        if len(claims) >= 401:
            break
        claims.append(
            ClaimEnvelope(
                id=f"episode360:{journey_id}:{version_id}:communication:{quote(fact_id, safe='')}",
                kind="explicit_journey_communication_reference",
                subject=request.subject,
                evidenceRefs=[journey_ref, communication_evidence],
                claims=[
                    f"Canonical communication fact {fact_id!r} explicitly references journey {journey_id!r}.",
                    "This typed reference does not establish communication content, causality, or a complete conversation inventory.",
                ],
                claimState=EpistemicStatus.OBSERVED,
                domainSlotIds=["communications", "evidence_trace"],
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
                # The generic summary/interactions/evidence sections contain
                # many facts. Only their typed authority claims can attest
                # recommendation and dropoff slots.
                if (
                    isinstance(slot_id, str)
                    and slot_id in required_slot_ids
                    and slot_id not in {"recommended_actions", "dropoffs"}
                ):
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


def _journey_decimal_text(value: Any) -> Optional[str]:
    """Serialize finite canonical numeric values without float coercion."""
    if value is None or isinstance(value, bool) or not isinstance(
        value, (str, int, float, Decimal)
    ):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite():
        return None
    return format(parsed, "f")


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


def _parse_utc_timestamp(value: Any) -> Optional[datetime]:
    """Parse a timezone-aware canonical timestamp without assigning a zone."""
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo is not None else None
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None


def _communication_payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload")
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str) and payload.strip():
        import json

        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _communication_row_references_subject(
    row: dict[str, Any], subject_kind: str, subject_id: str
) -> bool:
    """Match only the named typed subject-reference fields, never prose."""
    singular, plural = (
        ("episode_id", "episode_ids")
        if subject_kind == "episode"
        else ("journey_id", "journey_ids")
    )
    payload = _communication_payload(row)

    def has_reference(value: Any) -> bool:
        if isinstance(value, dict):
            for key, child in value.items():
                if key == singular and isinstance(child, str) and child == subject_id:
                    return True
                if key == plural and isinstance(child, (list, tuple)) and subject_id in child:
                    return True
                if has_reference(child):
                    return True
        elif isinstance(value, (list, tuple)):
            return any(has_reference(child) for child in value)
        return False

    return has_reference(row) or has_reference(payload)


def _communication_fact_evidence(row: dict[str, Any]) -> Optional[EvidenceRef]:
    fact_id = row.get("fact_id") or row.get("idempotency_key") or row.get("source_event_id")
    if not isinstance(fact_id, (str, UUID)) or not str(fact_id).strip():
        return None
    return EvidenceRef(
        id=str(fact_id),
        type="event",
        source=_COMMUNICATION_FACT_SOURCE,
        observedAt=_journey_timestamp(row.get("occurred_at")),
        uri=f"store://communication360_facts/{quote(str(fact_id), safe='')}",
    )


def _communication_fact_view(
    row: dict[str, Any],
    reference: EvidenceRef,
    subject_kind: str,
) -> dict[str, Any]:
    """Render only typed metadata; communication bodies remain private."""
    payload = _communication_payload(row)
    singular, plural = (
        ("episode_id", "episode_ids")
        if subject_kind == "episode"
        else ("journey_id", "journey_ids")
    )
    ids: list[str] = []
    for key in (singular, plural):
        value = payload.get(key)
        candidates = value if isinstance(value, (list, tuple)) else [value]
        for candidate in candidates:
            if isinstance(candidate, str) and candidate and candidate not in ids:
                ids.append(candidate)
    return {
        "factId": reference.id,
        "kind": _journey_text(row.get("kind")),
        "occurredAt": _journey_timestamp(row.get("occurred_at")),
        "receivedAt": _journey_timestamp(row.get("received_at")),
        "subjectReferenceIds": ids,
        "evidenceRefs": [reference.model_dump(mode="json", exclude_none=True)],
    }


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


def _episode_observation_source_event_ref(
    tenant_id: str, row: dict[str, Any]
) -> Optional[EvidenceRef]:
    observation_id = _journey_text(row.get("observation_id"))
    source_event_id = _journey_text(row.get("source_event_id"))
    observed_at = _journey_timestamp(row.get("occurred_at"))
    if (
        observation_id is None
        or source_event_id is None
        or row.get("tenant_id") != tenant_id
        or observed_at is None
    ):
        return None
    observation_uri = (
        "store://silver_semantic_observations/"
        f"{quote(tenant_id, safe='')}:{quote(observation_id, safe='')}"
    )
    return EvidenceRef(
        id=source_event_id,
        type="event",
        source=_EPISODE_OBSERVATION_EVENT_REF_SOURCE,
        observedAt=observed_at,
        uri=f"{observation_uri}/source-event/{quote(source_event_id, safe='')}",
    )


def _episode_observation_receipt_ref(
    tenant_id: str, row: dict[str, Any]
) -> Optional[EvidenceRef]:
    observation_id = _journey_text(row.get("observation_id"))
    received_at = _journey_timestamp(row.get("received_at"))
    if observation_id is None or row.get("tenant_id") != tenant_id or received_at is None:
        return None
    observation_uri = (
        "store://silver_semantic_observations/"
        f"{quote(tenant_id, safe='')}:{quote(observation_id, safe='')}"
    )
    return EvidenceRef(
        id=observation_id,
        type="event",
        source=_EPISODE_OBSERVATION_RECEIPT_REF_SOURCE,
        observedAt=received_at,
        uri=f"{observation_uri}/receipt",
    )


def _episode_observation_reference_ref(
    record: EpisodeObservationReferenceRecord,
) -> EvidenceRef:
    return EvidenceRef(
        id=record.record_id,
        type="event",
        source=_EPISODE_OBSERVATION_REFERENCE_SOURCE,
        observedAt=record.linked_at.isoformat(),
        uri=(
            "store://episode_journey_authority_records/"
            f"{quote(record.tenant_id, safe='')}:{quote(record.record_id, safe='')}"
        ),
    )


def _episode_observation_reference_has_evidence(
    record: EpisodeObservationReferenceRecord,
) -> bool:
    observation_uri = (
        "store://silver_semantic_observations/"
        f"{quote(record.tenant_id, safe='')}:{quote(record.observation_id, safe='')}"
    )
    expected = {
        (
            record.observation_id,
            "event",
            _EPISODE_OBSERVATION_SOURCE,
            observation_uri,
        ): record.recorded_at,
        (
            record.source_event_id,
            "event",
            _EPISODE_OBSERVATION_EVENT_REF_SOURCE,
            f"{observation_uri}/source-event/{quote(record.source_event_id, safe='')}",
        ): record.occurred_at,
        (
            record.observation_id,
            "event",
            _EPISODE_OBSERVATION_RECEIPT_REF_SOURCE,
            f"{observation_uri}/receipt",
        ): record.received_at,
    }
    observed_evidence = {
        (ref.id, ref.type, ref.source, ref.uri): _parse_utc_timestamp(ref.observedAt)
        for ref in record.evidence_refs
        if ref.id and ref.source and ref.uri
    }
    return all(observed_evidence.get(key) == value for key, value in expected.items())


def _episode_observation_time_matches(
    occurred_at: datetime,
    processed_at: datetime,
    evidence_refs: tuple[EvidenceRef, ...] | list[EvidenceRef],
    *,
    received_at: Optional[datetime] = None,
    after: Optional[datetime] = None,
    before: Optional[datetime] = None,
    as_of: Optional[datetime] = None,
) -> bool:
    occurred = occurred_at.astimezone(timezone.utc)
    processed = processed_at.astimezone(timezone.utc)
    received = received_at.astimezone(timezone.utc) if received_at is not None else None
    lower = after.astimezone(timezone.utc) if after is not None else None
    upper = before.astimezone(timezone.utc) if before is not None else None
    anchor = as_of.astimezone(timezone.utc) if as_of is not None else None
    if lower is not None and occurred < lower:
        return False
    if upper is not None and occurred > upper:
        return False
    if anchor is None:
        return True
    if occurred > anchor or processed > anchor or received is None or received > anchor:
        return False
    for ref in evidence_refs:
        observed_at = _parse_utc_timestamp(ref.observedAt)
        if observed_at is None or observed_at > anchor:
            return False
    return True


def _episode_observation_view(
    tenant_id: str,
    row: dict[str, Any],
    *,
    reference_refs: tuple[EvidenceRef, ...] = (),
) -> dict[str, Any]:
    evidence = _episode_observation_ref(tenant_id, row)
    source_event_evidence = _episode_observation_source_event_ref(tenant_id, row)
    receipt_evidence = _episode_observation_receipt_ref(tenant_id, row)
    return {
        "observationId": _journey_text(row.get("observation_id")),
        "sourceNamespace": _journey_text(row.get("source_namespace")),
        "sourceEventId": _journey_text(row.get("source_event_id")),
        "sourceType": _journey_text(row.get("source_type")),
        "occurredAt": _journey_timestamp(row.get("occurred_at")),
        "receivedAt": _journey_timestamp(row.get("received_at")),
        "processedAt": _journey_timestamp(row.get("processed_at")),
        "recordStatus": _journey_text(row.get("status")),
        "evidenceRefs": [
            ref.model_dump()
            for ref in (evidence, source_event_evidence, receipt_evidence, *reference_refs)
            if ref is not None
        ],
    }


def _episode_observation_views_for(
    tenant_id: str, episode: EpisodeRecord, read: EpisodeObservationRead
) -> list[dict[str, Any]]:
    rows_by_id = {
        _journey_text(row.get("observation_id")): row
        for row in read.rows
        if _journey_text(row.get("observation_id")) is not None
    }
    links = {
        (episode_id, observation_id): ref
        for episode_id, observation_id, ref in read.reference_links
    }
    return [
        _episode_observation_view(
            tenant_id,
            rows_by_id[observation_id],
            reference_refs=(links[(episode.episode_id, observation_id)],),
        )
        for observation_id in episode.observation_ids
        if observation_id in rows_by_id
        and (episode.episode_id, observation_id) in links
    ]


def _episode_observation_reference_refs_for_id(
    observation_id: Optional[str], read: EpisodeObservationRead
) -> tuple[EvidenceRef, ...]:
    if observation_id is None:
        return ()
    return tuple(
        ref
        for _, linked_observation_id, ref in read.reference_links
        if linked_observation_id == observation_id
    )


def _episode_observation_refs_for(
    episode: EpisodeRecord, read: EpisodeObservationRead
) -> list[EvidenceRef]:
    linked_ids = {
        observation_id
        for episode_id, observation_id, _ in read.reference_links
        if episode_id == episode.episode_id
    }
    source_refs: list[EvidenceRef] = []
    for row in read.rows:
        if _journey_text(row.get("observation_id")) not in linked_ids:
            continue
        for make_ref in (
            _episode_observation_ref,
            _episode_observation_source_event_ref,
            _episode_observation_receipt_ref,
        ):
            if (ref := make_ref(episode.tenant_id, row)) is not None:
                source_refs.append(ref)
    return source_refs + [
        ref
        for episode_id, observation_id, ref in read.reference_links
        if episode_id == episode.episode_id and observation_id in linked_ids
    ]


def _episode_observation_read_state(read: EpisodeObservationRead) -> str:
    if not read.requested_ids:
        return "empty"
    if read.rows and read.complete:
        return "available"
    if read.rows:
        return "degraded"
    if (
        read.out_of_window_ids
        and len(read.out_of_window_ids) == len(read.requested_ids)
        and read.complete
    ):
        return "empty"
    return "unknown"


def _episode_observation_read_reason(read: EpisodeObservationRead) -> str:
    if not read.requested_ids:
        return "episode_record_contains_no_observation_references"
    if read.temporal_reason:
        return read.temporal_reason
    if read.read_failed or not read.available:
        return "episode_observation_namespace_or_semantic_authority_unavailable"
    if read.tenant_mismatch:
        return "semantic_observation_tenant_scope_mismatch"
    if read.ambiguous_ids:
        return "episode_observation_source_namespace_or_lineage_ambiguous"
    if read.namespace_missing_ids:
        return "episode_observation_source_namespace_untyped_or_missing"
    if read.missing_episode_links:
        return "episode_observation_typed_reference_missing_for_episode"
    if read.invalid_records:
        return "episode_observation_namespace_or_semantic_rows_invalid"
    if read.inactive_records:
        return "semantic_observation_non_active_rows_omitted"
    if read.timestamps_missing:
        return "semantic_observation_timestamps_missing_or_invalid"
    if read.out_of_window_ids and not read.rows:
        return "episode_observation_references_outside_requested_temporal_window"
    if read.truncated:
        return "episode_observation_reference_read_truncated"
    if read.missing_ids:
        return "episode_observation_ids_not_found_in_semantic_silver"
    return "exact_tenant_namespace_and_event_evidence_resolved_recorded_episode_references_only"


def _dedupe_evidence_refs(refs: list[EvidenceRef]) -> list[EvidenceRef]:
    unique: dict[tuple[str, str, str, str], EvidenceRef] = {}
    for ref in refs:
        if not isinstance(ref, EvidenceRef) or not ref.id or not ref.source:
            continue
        unique.setdefault((ref.id, ref.type, ref.source, ref.uri or ""), ref)
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
        "journeyId": episode.journey_id,
        "kind": episode.kind,
        "status": episode.status,
        "title": episode.title,
        "occurredFrom": episode.occurred_from,
        "occurredTo": episode.occurred_to,
        "subject": {"kind": episode.subject.kind, "id": episode.subject.id},
        "observationIds": list(episode.observation_ids),
        "journeyTouchpointIds": (
            list(episode.journey_touchpoint_ids)
            if episode.journey_touchpoint_ids is not None
            else None
        ),
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


def _episode_risk_context(read: EpisodeRiskFlagRead) -> dict[str, Any]:
    """Render direct-subject risk observations without implying history or causality."""
    evidence_refs = [ref.model_dump(mode="json", exclude_none=True) for ref in read.evidence_refs]
    has_signals = bool(read.signals)
    return {
        "state": read.state,
        "coverage": "exact_episode_primary_subject_signals_only" if has_signals else "unknown",
        "subject": (
            {"kind": read.subject_kind, "id": read.subject_id}
            if read.subject_kind and read.subject_id
            else None
        ),
        "flags": list(read.signals),
        "count": None,
        "observedCount": len(read.signals),
        "truncated": read.truncated,
        "invalidRecords": read.invalid_records,
        "tenantMismatch": read.tenant_mismatch,
        "evidenceRefs": evidence_refs,
        "reason": read.reason,
        "freshness": {
            "state": "unknown",
            "evaluation": "not_performed",
            "reason": "risk_signal_source_watermark_not_available",
        },
        "policy": {
            "state": "unknown",
            "evaluation": "not_performed",
            "reason": "episode_risk_policy_not_evaluated_by_projection",
        },
        "provenance": {
            "state": "partial" if has_signals else "unknown",
            "authority": _EPISODE_RISK_SIGNAL_SOURCE,
            "referenceAuthority": _EPISODE_RECORD_SOURCE,
            "coverage": "episode_primary_subject_exact_typed_reference_only",
            "reason": read.reason,
        },
    }


def _risk_signal_claim_state(value: Any) -> EpistemicStatus:
    """Keep the canonical RiskSignal epistemic state, defaulting safely to unknown."""
    try:
        return EpistemicStatus(value)
    except (TypeError, ValueError):
        return EpistemicStatus.UNKNOWN


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


def _communication_fact_link_context(
    read: CommunicationFactLinkRead,
    *,
    subject_kind: str,
) -> dict[str, Any]:
    """Expose typed communication metadata without message or interpretation bodies."""
    refs_by_id = {ref.id: ref for ref in read.evidence_refs}
    communications: list[dict[str, Any]] = []
    claims: list[tuple[str, EvidenceRef]] = []
    for row in read.rows:
        reference = _communication_fact_evidence(row)
        if reference is None:
            continue
        canonical_ref = refs_by_id.get(reference.id)
        if canonical_ref is None:
            continue
        communications.append(
            _communication_fact_view(row, canonical_ref, subject_kind)
        )
        claims.append((canonical_ref.id, canonical_ref))
    return {
        "state": read.state,
        "coverage": "exact_reference_facts_only" if communications else (
            "partial" if read.truncated or read.invalid_records else "unknown"
        ),
        "reason": read.reason,
        "requestedSubjectKind": subject_kind,
        "communicationCount": len(communications) if read.complete else None,
        "observedCommunicationCount": len(communications),
        "communications": communications,
        "evidenceRefs": [
            ref.model_dump(mode="json", exclude_none=True)
            for ref in read.evidence_refs
        ],
        "temporal": {
            "state": read.temporal_state,
            "evaluation": "applied" if read.temporal_state != "unknown" else "not_performed",
        },
        "freshness": {
            "state": "unknown",
            "reason": "communication_fact_projection_watermark_not_available",
        },
        "policy": {
            "state": "unknown",
            "evaluation": "not_performed",
            "reason": "communication_fact_policy_not_evaluated_by_episode_projection",
        },
        "sourceReadComplete": read.complete,
        "claims": claims,
    }


def _episode_authority_read_for_as_of(
    read: AuthorityFactRead,
    *,
    record_type: str,
    tenant_id: str,
    episode: EpisodeRecord,
    as_of: Optional[datetime],
) -> AuthorityFactRead:
    """Validate exact Episode associations and apply their recorded-time bound."""
    model = {
        "episode_agent_handoff": EpisodeAgentHandoffRecord,
        "episode_attribution_link": EpisodeAttributionLinkRecord,
    }.get(record_type)
    if model is None:
        return AuthorityFactRead(
            available=False,
            complete=False,
            invalid_records=True,
        )
    if as_of is not None and as_of.tzinfo is None:
        return AuthorityFactRead(
            available=False,
            complete=False,
            invalid_records=True,
        )
    anchor = as_of.astimezone(timezone.utc) if as_of is not None else None
    records: list[dict[str, Any]] = []
    invalid_records = read.invalid_records
    tenant_mismatch = read.tenant_mismatch
    for raw in read.records:
        try:
            record = model.model_validate(raw)
        except Exception:  # noqa: BLE001 - malformed association rows degrade the slot
            invalid_records = True
            continue
        if record.tenant_id != tenant_id:
            tenant_mismatch = True
            continue
        if record.episode_id != episode.episode_id or record.record_type != record_type:
            invalid_records = True
            continue
        if isinstance(record, EpisodeAgentHandoffRecord):
            if (
                episode.subject.kind != "agent"
                or record.agent_id != episode.subject.id
                or record.source_event_id not in set(episode.observation_ids)
            ):
                invalid_records = True
                continue
        elif record.outcome_id not in set(episode.outcome_ids):
            invalid_records = True
            continue
        if anchor is not None:
            evidence_times = [
                _parse_utc_timestamp(ref.observedAt)
                for ref in record.evidence_refs
                if ref.observedAt is not None
            ]
            if (
                record.occurred_at > anchor
                or record.recorded_at > anchor
                or any(value is None or value > anchor for value in evidence_times)
            ):
                continue
        records.append(record.model_dump(mode="json", exclude_none=True))
    complete = (
        read.complete
        and not read.truncated
        and not invalid_records
        and not tenant_mismatch
        and not read.read_failed
    )
    return AuthorityFactRead(
        records=tuple(records),
        available=read.available,
        complete=complete,
        truncated=read.truncated,
        invalid_records=invalid_records,
        tenant_mismatch=tenant_mismatch,
        read_failed=read.read_failed,
    )


def _episode_authority_context(
    read: AuthorityFactRead,
    *,
    record_type: str,
    tenant_id: str,
    episode: EpisodeRecord,
) -> dict[str, Any]:
    """Project positive typed links; an empty relation scan is not absence proof."""
    model = (
        EpisodeAgentHandoffRecord
        if record_type == "episode_agent_handoff"
        else EpisodeAttributionLinkRecord
    )
    records: list[dict[str, Any]] = []
    evidence_refs: list[EvidenceRef] = []
    invalid = read.invalid_records
    tenant_mismatch = read.tenant_mismatch
    for raw in read.records:
        try:
            record = model.model_validate(raw)
        except Exception:  # noqa: BLE001 - malformed relationship rows stay unknown
            invalid = True
            continue
        if (
            record.tenant_id != tenant_id
            or record.episode_id != episode.episode_id
            or record.record_type != record_type
        ):
            tenant_mismatch = tenant_mismatch or record.tenant_id != tenant_id
            invalid = invalid or record.episode_id != episode.episode_id
            continue
        if isinstance(record, EpisodeAgentHandoffRecord) and (
            episode.subject.kind != "agent"
            or record.agent_id != episode.subject.id
            or record.source_event_id not in set(episode.observation_ids)
        ):
            invalid = True
            continue
        if isinstance(record, EpisodeAttributionLinkRecord) and record.outcome_id not in set(
            episode.outcome_ids
        ):
            invalid = True
            continue
        refs: list[EvidenceRef] = []
        for raw_ref in record.evidence_refs:
            try:
                ref = EvidenceRef.model_validate(raw_ref)
            except Exception:  # noqa: BLE001 - invalid evidence cannot support a link
                invalid = True
                continue
            if ref.id and ref.source:
                refs.append(ref)
        if len(refs) < (2 if record_type == "episode_agent_handoff" else 4):
            invalid = True
            continue
        refs.append(
            EvidenceRef(
                id=record.record_id,
                type="event",
                source="episode_journey_authority_records",
                observedAt=record.recorded_at.isoformat(),
            )
        )
        evidence_refs.extend(refs)
        records.append(
            record.model_dump(mode="json", exclude_none=True)
        )
    evidence_refs = _dedupe_evidence_refs(evidence_refs)
    incomplete = (
        not read.available
        or read.truncated
        or invalid
        or tenant_mismatch
        or read.read_failed
    )
    if records:
        state = "degraded" if incomplete else "available"
        coverage = "partial_explicit_links"
        reason = (
            "exact_episode_handoff_links_joined_inventory_incomplete"
            if record_type == "episode_agent_handoff" and incomplete
            else "exact_episode_execution_and_delegation_links_joined"
            if record_type == "episode_agent_handoff"
            else "exact_episode_attribution_credit_links_joined_inventory_incomplete"
            if incomplete
            else "exact_episode_outcome_conversion_and_attribution_credit_links_joined"
        )
    else:
        state = "unknown"
        coverage = "unknown"
        reason = (
            "no_explicit_episode_agent_handoff_link_recorded_absence_not_established"
            if record_type == "episode_agent_handoff"
            else "no_explicit_episode_attribution_link_recorded_absence_not_established"
        )
        if incomplete:
            reason = (
                "episode_agent_handoff_authority_read_incomplete"
                if record_type == "episode_agent_handoff"
                else "episode_attribution_authority_read_incomplete"
            )
    return {
        "state": state,
        "coverage": coverage,
        "reason": reason,
        "records": records,
        "count": len(records) if records else None,
        "observedCount": len(records),
        "evidenceRefs": [
            ref.model_dump(mode="json", exclude_none=True) for ref in evidence_refs
        ],
        "freshness": {
            "state": "unknown",
            "evaluation": "not_performed",
            "reason": "episode_authority_watermark_not_available",
        },
        "policy": {
            "state": "unknown",
            "evaluation": "not_performed",
            "reason": (
                "delegation_authorization_not_re_evaluated_by_episode_projection"
                if record_type == "episode_agent_handoff"
                else "attribution_policy_not_evaluated_by_episode_projection"
            ),
        },
        "inventoryComplete": False,
        "sourceReadComplete": not incomplete,
        "warnings": (
            [reason]
            if incomplete
            else []
        ),
    }


def _episode_required_slot_coverage(
    request: ProjectionRequest,
    episodes: list[EpisodeRecord],
    *,
    availability: str,
    evidence_refs: list[EvidenceRef],
    observation_read: EpisodeObservationRead,
    outcome_read: EpisodeOutcomeRead,
    touchpoint_read: EpisodeTouchpointRead,
    risk_read: EpisodeRiskFlagRead,
    communication_read: CommunicationFactLinkRead,
    episode_authority_read: EpisodeAuthorityRead,
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
    touchpoint_context = _episode_touchpoint_context(touchpoint_read, episodes)
    risk_context = _episode_risk_context(risk_read)
    communication_context = _communication_fact_link_context(
        communication_read,
        subject_kind="episode",
    )
    handoff_context = _episode_authority_context(
        episode_authority_read.agent_handoffs,
        record_type="episode_agent_handoff",
        tenant_id=request.tenantId,
        episode=episode,
    )
    attribution_link_context = _episode_authority_context(
        episode_authority_read.attribution_links,
        record_type="episode_attribution_link",
        tenant_id=request.tenantId,
        episode=episode,
    )
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
            "state": touchpoint_context["state"],
            "coverage": touchpoint_context["coverage"],
            "reason": touchpoint_context["reason"],
            "evidenceRefs": touchpoint_context["evidenceRefs"],
        },
        "communications": {
            "state": communication_context["state"],
            "coverage": communication_context["coverage"],
            "reason": communication_context["reason"],
            "evidenceRefs": communication_context["evidenceRefs"],
            "temporal": communication_context["temporal"],
            "freshness": communication_context["freshness"],
            "policy": communication_context["policy"],
        },
        "agent_handoffs": {
            **handoff_context,
        },
        "conversion_events": {
            "state": conversion_context["state"],
            "coverage": conversion_context["coverage"],
            "reason": conversion_context["reason"],
            "evidenceRefs": conversion_context["evidenceRefs"],
        },
        "attribution_links": {
            **attribution_link_context,
        },
        "risk_flags": {
            "state": risk_context["state"],
            "coverage": risk_context["coverage"],
            "reason": risk_context["reason"],
            "evidenceRefs": risk_context["evidenceRefs"],
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
