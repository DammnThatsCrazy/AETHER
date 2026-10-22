"""Read-only Relationship360 projection over the canonical graph ledger.

The relationship predicate registry defines which graph edge types carry
registered relationship semantics. ``GraphHistoryReplay`` reconstructs the
tenant-scoped graph state from ``graph_mutation_ledger`` and supplies each edge
transition's mutation id, recorded time, and valid-time anchor. This provider
projects only that evidence; it does not promote predicates, compute new
fidelity, or mutate the graph.

The replay reader is intentionally treated as bounded. KNOWN_NOW is capped and
KNOWN_THEN uses the ledger repository's bounded prefix API; neither interface
currently returns a completeness watermark. A successful read therefore does
not prove the relationship set is exhaustive. The provider emits the observed
ledger prefix with degraded/unknown coverage semantics instead of asserting a
complete graph or a definitive absence of relationships.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from typing import Any, Optional, Protocol

from shared.contracts_models.epistemic import EpistemicStatus
from shared.intelligence_projections.contracts import (
    ClaimEnvelope,
    ProjectionContext,
    ProjectionRequest,
    ProjectionResult,
    ProjectionSection,
)
from shared.intelligence_projections.composition import PRODUCT_360_SURFACE_DEFINITIONS
from shared.intelligence_projections.generated_registry import (
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
)
from shared.intelligence_projections.registry import ProviderRegistry
from graph.operational_intelligence.models import EvidenceRef, PageInfo
from shared.temporal.instant import coerce_utc_lenient
from graph.temporal360.history_replay import (
    GraphHistoryReplay,
    SubjectEvent,
    SubjectHistory,
)
from identity.population360.scope import (
    PopulationScopeRead,
    PopulationScopeReader,
    RepositoryPopulationScopeReader,
)
from identity.identity.source_subject_scope import (
    RepositorySourceSubjectScopeReader,
    SourceSubjectScopeRead,
    SourceSubjectScopeReader,
)
from governance.consent.authority import evaluate_consent

PROJECTION_ID = "relationship360"
OUTPUT_SECTIONS: tuple[str, ...] = (
    "evidence",
    "findings",
    "interactions",
    "state",
    "summary",
    "timeline",
    "agent_spawned_agents",
)
SUPPORTED_TEMPORAL_MODES: frozenset[str] = frozenset({"as_of", "relative", "window"})

_MAX_TIMELINE_ITEMS = 200
_MAX_INTERACTION_EDGES = 500
_MAX_EVIDENCE_REFS = 100
_MAX_CLAIMS = 50
_LEDGER_SOURCE = "graph_mutation_ledger"
_SPAWNED_SUBAGENT_EDGE = "SPAWNED_SUBAGENT"


class RelationshipRead(Protocol):
    """Canonical temporal graph read seam, injectable for deterministic tests."""

    async def subject_history(
        self,
        *,
        tenant_id: str,
        subject_id: str,
        as_of: Optional[str] = None,
    ) -> SubjectHistory: ...


class CanonicalAgentReader(Protocol):
    """Tenant-scoped identity authority used for Agent graph subjects."""

    async def is_canonical_agent(self, tenant_id: str, agent_id: str) -> Optional[bool]:
        """True for a canonical Agent, False for mismatch, None on authority outage."""
        ...


class RepositoryCanonicalAgentReader:
    """Validate an Agent subject through the canonical tenant Entity store."""

    async def is_canonical_agent(self, tenant_id: str, agent_id: str) -> Optional[bool]:
        try:
            from repositories.repos import EntityRepository

            entity = await EntityRepository().find_by_id(agent_id)
        except Exception:  # noqa: BLE001 - identity authority failures stay unknown
            return None
        return bool(
            isinstance(entity, dict)
            and entity.get("tenant_id") == tenant_id
            and entity.get("entity_type") == "agent"
            and entity.get("entity_id") == agent_id
        )


class ProfileIdentityBindingReader(Protocol):
    """Resolve exact, current journey/episode links to a tenant user profile."""

    async def identity_binding(self, tenant_id: str, subject: Any) -> Any: ...


class RepositoryProfileIdentityBindingReader:
    """Reuse the canonical current-only journey/episode identity binding adapter."""

    async def identity_binding(self, tenant_id: str, subject: Any) -> Any:
        # Import lazily: Relationship360 and Profile360 are peer projections.
        from identity.profile.profile360_provider import RepositoryProfile360Source

        return await RepositoryProfile360Source().identity_binding(tenant_id, subject)


class LedgerRelationshipReader:
    """Read relationship history from the canonical graph mutation ledger."""

    def __init__(self, replay: Optional[GraphHistoryReplay] = None) -> None:
        self._replay = replay if replay is not None else GraphHistoryReplay()

    async def subject_history(
        self,
        *,
        tenant_id: str,
        subject_id: str,
        as_of: Optional[str] = None,
    ) -> SubjectHistory:
        return await self._replay.subject_history(tenant_id, subject_id, as_of=as_of)


class Relationship360Provider:
    """Tenant-scoped Relationship360 projection with no graph write surface."""

    projection_id = PROJECTION_ID
    contract_version = INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION
    graph_mutation_policy = "read_only"

    def __init__(
        self,
        reader: Optional[RelationshipRead] = None,
        *,
        agent_identity_reader: Optional[CanonicalAgentReader] = None,
        population_scope_reader: Optional[PopulationScopeReader] = None,
        source_subject_scope_reader: Optional[SourceSubjectScopeReader] = None,
        profile_identity_binding_reader: Optional[ProfileIdentityBindingReader] = None,
        consent_reader: Any = None,
    ) -> None:
        self._reader = reader if reader is not None else LedgerRelationshipReader()
        self._agent_identity = (
            agent_identity_reader
            if agent_identity_reader is not None
            else RepositoryCanonicalAgentReader()
        )
        self._population_scope = (
            population_scope_reader
            if population_scope_reader is not None
            else RepositoryPopulationScopeReader()
        )
        self._source_subject_scope = (
            source_subject_scope_reader
            if source_subject_scope_reader is not None
            else RepositorySourceSubjectScopeReader()
        )
        self._profile_identity_binding = (
            profile_identity_binding_reader
            if profile_identity_binding_reader is not None
            else RepositoryProfileIdentityBindingReader()
        )
        self._consent_reader = consent_reader or evaluate_consent

    async def project(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
    ) -> ProjectionResult:
        now = _utc_now_iso()
        mode = request.temporalMode or "window"
        anchor, degraded_reason = _resolve_anchor(request, mode)
        identity_binding_refs: tuple[EvidenceRef, ...] = ()

        # Runtime context is the authenticated tenant boundary. Do not read if
        # a malformed/direct caller supplies a different tenant in the request.
        if context.tenantId != request.tenantId:
            history = None
            read_error = "tenant_scope_mismatch"
            population_scope = None
            source_scope = None
        elif request.subject.kind == "population":
            source_scope = None
            if mode != "window" or (
                request.timeRange is not None
                and (request.timeRange.from_ is not None or request.timeRange.to is not None)
            ):
                history = None
                read_error = "population_membership_temporal_scope_unknown"
                population_scope = None
            else:
                history, read_error, population_scope = await self._read_population_history(
                    tenant_id=request.tenantId,
                    population_id=request.subject.id,
                    anchor=anchor,
                )
        elif request.subject.kind == "source":
            population_scope = None
            source_scope = None
            has_temporal_filter = (
                mode != "window"
                or request.asOf is not None
                or context.asOf is not None
                or (
                    request.timeRange is not None
                    and (request.timeRange.from_ is not None or request.timeRange.to is not None)
                )
            )
            if has_temporal_filter:
                history = None
                read_error = "source_identity_temporal_scope_unknown"
            else:
                try:
                    source_scope = await self._source_subject_scope.resolve(
                        request.tenantId, request.subject.id
                    )
                except Exception:  # noqa: BLE001 - canonical identity is fail-closed
                    source_scope = SourceSubjectScopeRead(
                        request.tenantId,
                        request.subject.id,
                        "degraded",
                        reason="source_identity_authority_unavailable",
                    )
                if (
                    source_scope.tenant_id != request.tenantId
                    or source_scope.source_identity_id != request.subject.id
                ):
                    history = None
                    read_error = "source_identity_scope_mismatch"
                elif source_scope.state != "available" or not source_scope.canonical_entity_id:
                    history = None
                    read_error = source_scope.reason or "source_identity_binding_unresolved"
                else:
                    try:
                        consent = await self._consent_reader(
                            request.tenantId,
                            source_scope.canonical_entity_id,
                            None,
                            "analytics",
                        )
                    except Exception:  # noqa: BLE001 - consent is fail-closed
                        consent = False, "consent_authority_unavailable"
                    if not _consent_allowed(consent):
                        history = None
                        read_error = "source_subject_consent_not_established"
                    else:
                        history, read_error = await self._read_history(
                            tenant_id=request.tenantId,
                            subject_id=source_scope.canonical_entity_id,
                            anchor=None,
                        )
        elif request.subject.kind in {"episode", "journey"}:
            population_scope = None
            source_scope = None
            has_temporal_filter = (
                mode != "window"
                or request.asOf is not None
                or context.asOf is not None
                or (
                    request.timeRange is not None
                    and (request.timeRange.from_ is not None or request.timeRange.to is not None)
                )
            )
            if has_temporal_filter:
                history = None
                read_error = "identity_binding_valid_time_unavailable"
            else:
                try:
                    binding = await self._profile_identity_binding.identity_binding(
                        request.tenantId, request.subject
                    )
                except Exception:  # noqa: BLE001 - identity joins fail closed
                    binding = None
                resolved_subject = getattr(binding, "resolved_subject", None)
                binding_evidence = getattr(binding, "evidence_ref", None)
                if (
                    binding is None
                    or getattr(binding, "tenant_id", None) != request.tenantId
                    or not getattr(binding, "available", False)
                    or not getattr(binding, "scope_known", False)
                    or getattr(resolved_subject, "kind", None) != "entity"
                    or not isinstance(getattr(resolved_subject, "id", None), str)
                    or not resolved_subject.id
                    or not isinstance(binding_evidence, EvidenceRef)
                    or not binding_evidence.id.strip()
                    or not binding_evidence.source.strip()
                ):
                    history = None
                    read_error = (
                        getattr(binding, "reason", None)
                        if binding is not None
                        and getattr(binding, "tenant_id", None) == request.tenantId
                        else "identity_binding_unresolved_or_scope_mismatched"
                    ) or "identity_binding_unresolved_or_unproven"
                else:
                    # This binding is specifically to a user profile. The graph
                    # stores tenant-prefixed user vertices, while profile IDs
                    # are natural user IDs.
                    from shared.graph.graph import user_vertex_id

                    graph_subject_id = user_vertex_id(request.tenantId, resolved_subject.id)
                    identity_binding_refs = (binding_evidence,)
                    history, read_error = await self._read_history(
                        tenant_id=request.tenantId,
                        subject_id=graph_subject_id,
                        anchor=anchor,
                    )
        else:
            population_scope = None
            source_scope = None
            if request.subject.kind == "agent":
                try:
                    canonical_agent = await self._agent_identity.is_canonical_agent(
                        request.tenantId, request.subject.id
                    )
                except Exception:  # noqa: BLE001 - fail closed on identity authority errors
                    canonical_agent = None
                if canonical_agent is not True:
                    history = None
                    read_error = (
                        "agent_identity_authority_unavailable"
                        if canonical_agent is None
                        else "agent_canonical_identity_unresolved"
                    )
                else:
                    subject_id = request.subject.id
                    history, read_error = await self._read_history(
                        tenant_id=request.tenantId,
                        subject_id=subject_id,
                        anchor=anchor,
                    )
            else:
                subject_id = _history_subject_id(request.subject.kind, request.subject.id)
                if subject_id is None:
                    history = None
                    read_error = "relationship_subject_reference_unresolved"
                else:
                    history, read_error = await self._read_history(
                        tenant_id=request.tenantId,
                        subject_id=subject_id,
                        anchor=anchor,
                    )

        pair = _relationship_pair(request.subject.kind, request.subject.id)
        edge_events = _subject_edge_events(history, pair)
        visible_events, temporal_warnings = _window_events(edge_events, request, mode)
        bounded_events, page, page_warnings = _page_events(visible_events, request)
        spawned_agent_events = [
            event
            for event in visible_events
            if event.edge_type == _SPAWNED_SUBAGENT_EDGE
            and event.from_vertex_id == request.subject.id
        ]
        event_refs = _evidence_refs(edge_events)
        live_edges = _live_edge_views(history, edge_events, pair)

        sections = [
            _evidence_section(
                event_refs,
                history,
                read_error,
                population_scope.evidence_refs if population_scope is not None else (),
                source_scope.evidence_refs if source_scope is not None else (),
                identity_binding_refs,
            ),
            _findings_section(
                history,
                read_error,
                degraded_reason,
                [*temporal_warnings, *page_warnings],
            ),
            _interactions_section(live_edges, history, read_error),
            _state_section(history, edge_events, read_error),
            _summary_section(
                request,
                history,
                edge_events,
                live_edges,
                read_error,
                anchor,
                population_scope,
                source_scope,
            ),
            _timeline_section(
                bounded_events,
                history,
                read_error,
                [*temporal_warnings, *page_warnings],
            ),
            _agent_spawned_agents_section(
                spawned_agent_events,
                history,
                read_error,
            ),
        ]
        claims = _claims(request, edge_events, event_refs)
        if identity_binding_refs:
            section_authorities = {
                "evidence": ["graph", "identity", "relationship_facts"],
                "interactions": ["graph", "relationship_facts"],
            }
            sections = [
                section.model_copy(
                    update={"canonicalAuthorityRefs": section_authorities[section.id]}
                )
                if section.id in section_authorities
                else section
                for section in sections
            ]

        return ProjectionResult(
            projectionId=self.projection_id,
            tenantId=request.tenantId,
            contractVersion=self.contract_version,
            sections=sections,
            claims=claims,
            dependencyState=list(context.dependencyState),
            asOf=anchor or now,
            generatedAt=now,
            page=page,
            degradedReasons=[read_error] if read_error else [],
            temporalMode=mode,
            lensIds=request.lensIds,
        )

    async def _read_history(
        self, *, tenant_id: str, subject_id: str, anchor: Optional[str]
    ) -> tuple[Optional[SubjectHistory], Optional[str]]:
        try:
            history = await self._reader.subject_history(
                tenant_id=tenant_id,
                subject_id=subject_id,
                as_of=anchor,
            )
            return history, None
        except Exception:  # noqa: BLE001 - authority failure is typed below
            return None, "graph_history_replay_unavailable"

    async def _read_population_history(
        self,
        *,
        tenant_id: str,
        population_id: str,
        anchor: Optional[str],
    ) -> tuple[Optional[SubjectHistory], Optional[str], PopulationScopeRead]:
        try:
            scope = await self._population_scope.resolve(tenant_id, population_id, limit=200)
        except Exception:  # noqa: BLE001 - population authority is fail-closed
            scope = PopulationScopeRead(
                tenant_id,
                population_id,
                "degraded",
                reason="population_membership_authority_unavailable",
            )
        if scope.tenant_id != tenant_id or scope.population_id != population_id:
            return (
                None,
                "population_membership_scope_mismatch",
                PopulationScopeRead(
                    tenant_id,
                    population_id,
                    "conflicted",
                    reason="population_membership_scope_mismatch",
                ),
            )
        if not scope.complete:
            return (
                None,
                scope.reason or "population_membership_scope_unavailable",
                PopulationScopeRead(
                    tenant_id,
                    population_id,
                    scope.state,
                    reason=scope.reason or "population_membership_scope_unavailable",
                ),
            )

        member_ids = set(scope.entity_ids)
        if not member_ids:
            return (
                _aggregate_population_history(population_id, anchor, [], member_ids),
                None,
                scope,
            )

        for entity_id in scope.entity_ids:
            try:
                consent = await self._consent_reader(tenant_id, entity_id, None, "analytics")
            except Exception:  # noqa: BLE001 - consent is a fail-closed member gate
                consent = False, "consent_authority_unavailable"
            if not _consent_allowed(consent):
                reason = "population_member_consent_not_established"
                return (
                    None,
                    reason,
                    PopulationScopeRead(
                        tenant_id,
                        population_id,
                        "degraded",
                        reason=reason,
                    ),
                )

        semaphore = asyncio.Semaphore(8)

        async def read_member(entity_id: str):
            async with semaphore:
                return entity_id, await self._read_history(
                    tenant_id=tenant_id,
                    subject_id=entity_id,
                    anchor=anchor,
                )

        reads = await asyncio.gather(*(read_member(entity_id) for entity_id in scope.entity_ids))
        histories = [history for _, (history, _) in reads if history is not None]
        has_failures = any(error is not None for _, (_, error) in reads)
        history = _aggregate_population_history(population_id, anchor, histories, member_ids)
        return (
            history,
            "population_member_graph_read_incomplete" if has_failures else None,
            scope,
        )


def register_provider(registry: ProviderRegistry) -> Relationship360Provider:
    """Explicit registration helper; importing the module has no side effect."""
    provider = Relationship360Provider()
    registry.register(
        provider,
        source="services/api/identity/relationship_intelligence",
    )
    return provider


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _consent_allowed(result: Any) -> bool:
    if isinstance(result, tuple) and result:
        return result[0] is True
    return getattr(result, "allowed", False) is True


def _resolve_anchor(request: ProjectionRequest, mode: str) -> tuple[Optional[str], Optional[str]]:
    if request.asOf is not None:
        return request.asOf, None
    if mode in ("window", "relative"):
        return None, None
    if mode == "as_of":
        anchor = request.asOf or (request.timeRange.from_ if request.timeRange else None)
        if anchor:
            return anchor, None
        return None, "as_of_anchor_missing_known_now_served"
    return None, "unsupported_temporal_mode_known_now_served"


def _history_subject_id(kind: str, subject_id: str) -> Optional[str]:
    if kind in {"agent", "entity"}:
        return subject_id
    pair = _relationship_pair(kind, subject_id)
    return pair[0] if pair is not None else None


def _relationship_pair(kind: str, subject_id: str) -> Optional[tuple[str, str]]:
    if kind != "relationship":
        return None
    source, delimiter, target = subject_id.partition("::")
    if not delimiter or not source.strip() or not target.strip() or "::" in target:
        return None
    return source, target


def _aggregate_population_history(
    population_id: str,
    anchor: Optional[str],
    histories: list[SubjectHistory],
    member_ids: set[str],
) -> SubjectHistory:
    """Build an induced population subgraph from canonical member replays."""
    events_by_id: dict[str, SubjectEvent] = {}
    live_edges: set[tuple[str, str, str]] = set()
    for history in histories:
        for event in history.events:
            if (
                not event.kind.startswith("edge_")
                or event.from_vertex_id not in member_ids
                or event.to_vertex_id not in member_ids
            ):
                continue
            events_by_id.setdefault(event.mutation_id, event)
        live_edges.update(
            edge for edge in history.live_edges if edge[1] in member_ids and edge[2] in member_ids
        )
    events = tuple(
        sorted(events_by_id.values(), key=lambda event: (event.ledger_offset, event.mutation_id))
    )
    first_recorded = min((event.recorded_at for event in events), default=None)
    last_recorded = max((event.recorded_at for event in events), default=None)
    digest_material = "\n".join(sorted(history.digest for history in histories))
    digest = hashlib.sha256(digest_material.encode("utf-8")).hexdigest()
    return SubjectHistory(
        subject_id=population_id,
        as_of=anchor,
        present=True,
        vertex=None,
        first_recorded=first_recorded,
        last_recorded=last_recorded,
        event_count=len(events),
        events=events,
        live_edges=tuple(sorted(live_edges)),
        vertex_supersessions=sum(history.vertex_supersessions for history in histories),
        incident_edge_adds=sum(event.kind == "edge_added" for event in events),
        incident_edge_revocations=sum(event.kind == "edge_revoked" for event in events),
        digest=digest,
    )


def _subject_edge_events(
    history: Optional[SubjectHistory],
    pair: Optional[tuple[str, str]],
) -> list[SubjectEvent]:
    if history is None:
        return []
    events = [event for event in history.events if event.kind.startswith("edge_")]
    if pair is not None:
        source, target = pair
        events = [
            event
            for event in events
            if event.from_vertex_id == source and event.to_vertex_id == target
        ]
    return sorted(events, key=lambda event: (event.ledger_offset, event.mutation_id))


def _page_events(
    events: list[SubjectEvent], request: ProjectionRequest
) -> tuple[list[SubjectEvent], PageInfo, list[str]]:
    page_size = min(
        request.page.limit if request.page is not None else 50,
        _MAX_TIMELINE_ITEMS,
    )
    offset = 0
    warnings: list[str] = []
    cursor = request.page.cursor if request.page is not None else None
    if cursor:
        try:
            offset = max(0, int(cursor))
        except (TypeError, ValueError):
            warnings.append("invalid_timeline_cursor_ignored")
    selected = events[offset : offset + page_size]
    next_offset = offset + page_size
    has_next = next_offset < len(events)
    page = PageInfo(
        nextCursor=str(next_offset) if has_next else None,
        previousCursor=str(max(0, offset - page_size)) if offset > 0 else None,
        hasNextPage=has_next,
        hasPreviousPage=offset > 0,
        # Replay completeness is unknown, so this must not read as a tenant-wide
        # or relationship-wide total.
        totalEstimate=None,
    )
    if len(events) > _MAX_TIMELINE_ITEMS:
        warnings.append("timeline_read_cap_applied")
    return selected, page, warnings


def _window_events(
    events: list[SubjectEvent], request: ProjectionRequest, mode: str
) -> tuple[list[SubjectEvent], list[str]]:
    """Apply an explicit valid-time window without guessing missing timestamps."""
    time_range = request.timeRange
    if mode not in ("window", "relative") or time_range is None:
        return events, []
    window_from = time_range.from_
    window_to = time_range.to
    if window_from is None and window_to is None:
        return events, []
    lower = coerce_utc_lenient(window_from) if window_from is not None else None
    upper = coerce_utc_lenient(window_to) if window_to is not None else None
    invalid_bound = (window_from is not None and lower is None) or (
        window_to is not None and upper is None
    )
    included: list[SubjectEvent] = []
    for event in events:
        event_time = coerce_utc_lenient(event.valid_from)
        if event_time is None:
            continue
        if lower is not None and event_time < lower:
            continue
        if upper is not None and event_time > upper:
            continue
        included.append(event)
    warnings = (
        ["events_without_valid_time_excluded_from_window"] if len(included) < len(events) else []
    )
    if invalid_bound:
        warnings.append("invalid_valid_time_window_bound_ignored")
    return included, warnings


def _edge_key(event: SubjectEvent) -> tuple[str, str, str]:
    return (
        str(event.edge_type or ""),
        str(event.from_vertex_id or ""),
        str(event.to_vertex_id or ""),
    )


def _registered_predicates_by_edge_type() -> dict[str, list[str]]:
    from shared.relationship_spine.relationship_registry import (
        all_predicates,
        live_graph_edge_type,
    )

    result: dict[str, list[str]] = {}
    for entry in all_predicates():
        if entry.get("graphRegistrationState") != "REGISTERED":
            continue
        edge_type = entry.get("graphEdgeType")
        predicate = entry.get("predicate")
        # The relationship registry's public helper verifies the declared edge
        # still exists in the graph EdgeType authority; fail closed on stale or
        # inconsistent registrations.
        if edge_type and predicate and live_graph_edge_type(str(predicate)) == edge_type:
            result.setdefault(str(edge_type), []).append(str(predicate))
    return {key: sorted(values) for key, values in result.items()}


def _live_edge_views(
    history: Optional[SubjectHistory],
    events: list[SubjectEvent],
    pair: Optional[tuple[str, str]],
) -> list[dict[str, Any]]:
    if history is None:
        return []
    live_keys = set(history.live_edges)
    if pair is not None:
        source, target = pair
        live_keys = {key for key in live_keys if key[1] == source and key[2] == target}
    latest_by_key: dict[tuple[str, str, str], SubjectEvent] = {}
    for event in events:
        latest_by_key[_edge_key(event)] = event
    predicates = _registered_predicates_by_edge_type()
    output: list[dict[str, Any]] = []
    for key in sorted(live_keys):
        edge_type, source, target = key
        latest = latest_by_key.get(key)
        output.append(
            {
                "edgeType": edge_type,
                "from": source,
                "to": target,
                "registeredPredicates": predicates.get(edge_type, []),
                "predicateRegistrationState": (
                    "registered" if predicates.get(edge_type) else "unmapped_graph_edge_type"
                ),
                "replayedState": "present_in_replayed_prefix",
                "lastMutationId": latest.mutation_id if latest else None,
                "recordedAt": latest.recorded_at if latest else None,
                "validFrom": latest.valid_from if latest else None,
                "coverage": "unknown",
            }
        )
    return output


def _evidence_refs(events: list[SubjectEvent]) -> list[EvidenceRef]:
    seen: set[str] = set()
    refs: list[EvidenceRef] = []
    for event in events:
        mutation_id = event.mutation_id.strip()
        if not mutation_id or mutation_id in seen:
            continue
        seen.add(mutation_id)
        refs.append(
            EvidenceRef(
                id=mutation_id,
                type="relationship",
                source=_LEDGER_SOURCE,
                observedAt=event.recorded_at or None,
            )
        )
        if len(refs) >= _MAX_EVIDENCE_REFS:
            break
    return refs


def _section_state(
    history: Optional[SubjectHistory],
    has_data: bool,
    read_error: Optional[str],
) -> str:
    if read_error:
        return "degraded"
    if history is None or not (history.present or history.event_count):
        return "unknown"
    if not has_data:
        return "unknown"
    # The canonical replay APIs do not expose a completeness watermark.
    return "degraded"


def _evidence_section(
    refs: list[EvidenceRef],
    history: Optional[SubjectHistory],
    read_error: Optional[str],
    population_scope_refs: tuple[EvidenceRef, ...] = (),
    source_scope_refs: tuple[EvidenceRef, ...] = (),
    identity_binding_refs: tuple[EvidenceRef, ...] = (),
) -> ProjectionSection:
    all_refs = [*refs, *population_scope_refs, *source_scope_refs, *identity_binding_refs]
    return ProjectionSection(
        id="evidence",
        state=_section_state(history, bool(all_refs), read_error),  # type: ignore[arg-type]
        title="Relationship evidence and provenance",
        content={
            "items": [ref.model_dump(mode="json", by_alias=True) for ref in all_refs],
            "count": len(all_refs),
            "source": (
                "population_membership_materialization+graph_mutation_ledger"
                if population_scope_refs
                else "identity360+graph_mutation_ledger"
                if source_scope_refs
                else _LEDGER_SOURCE
            ),
            "populationMembershipEvidenceRefs": [
                ref.model_dump(mode="json", by_alias=True) for ref in population_scope_refs
            ],
            "sourceIdentityEvidenceRefs": [
                ref.model_dump(mode="json", by_alias=True) for ref in source_scope_refs
            ],
            "subjectIdentityBindingEvidenceRefs": [
                ref.model_dump(mode="json", by_alias=True) for ref in identity_binding_refs
            ],
            "coverage": "unknown",
            "sourceEvidenceCoverage": "unknown",
            "coverageReason": (
                "GraphHistoryReplay and the ledger prefix reads do not expose a completeness watermark or expand mutation evidence_refs."
            ),
        },
        warnings=["evidence_refs_capped"] if len(refs) >= _MAX_EVIDENCE_REFS else None,
    )


def _findings_section(
    history: Optional[SubjectHistory],
    read_error: Optional[str],
    temporal_warning: Optional[str],
    page_warnings: list[str],
) -> ProjectionSection:
    findings: list[dict[str, Any]] = []
    if history is not None:
        findings.append(
            {
                "code": "relationship_ledger_coverage_unknown",
                "level": "info",
                "message": "The replayed tenant ledger prefix has no completeness watermark; absence and total coverage remain unknown.",
            }
        )
    if read_error:
        findings.append(
            {
                "code": read_error,
                "level": "warning",
                "message": "The relationship graph read could not be completed.",
            }
        )
    if temporal_warning:
        findings.append(
            {
                "code": temporal_warning,
                "level": "warning",
                "message": "The requested temporal mode could not be fully honored.",
            }
        )
    findings.extend(
        {
            "code": warning,
            "level": "info",
            "message": "A bounded timeline read was adjusted; inspect the section warning.",
        }
        for warning in page_warnings
    )
    state = "degraded" if history is not None or read_error or temporal_warning else "unknown"
    return ProjectionSection(
        id="findings",
        state=state,  # type: ignore[arg-type]
        title="Relationship findings and limitations",
        content={"findings": findings},
    )


def _interactions_section(
    live_edges: list[dict[str, Any]],
    history: Optional[SubjectHistory],
    read_error: Optional[str],
) -> ProjectionSection:
    rendered_edges = live_edges[:_MAX_INTERACTION_EDGES]
    warnings = (
        ["edge_state_is_limited_to_the_replayed_ledger_prefix"] if history is not None else []
    )
    if len(live_edges) > _MAX_INTERACTION_EDGES:
        warnings.append("live_relationship_edge_cap_applied")
    return ProjectionSection(
        id="interactions",
        state=_section_state(history, bool(live_edges), read_error),  # type: ignore[arg-type]
        title="Replayed relationship edges",
        content={
            "edges": rendered_edges,
            "count": len(live_edges),
            "renderedCount": len(rendered_edges),
            "truncated": len(rendered_edges) < len(live_edges),
            "stateBasis": "GraphHistoryReplay over the tenant graph mutation ledger",
            "coverage": "unknown",
        },
        warnings=warnings or None,
    )


def _state_section(
    history: Optional[SubjectHistory],
    edge_events: list[SubjectEvent],
    read_error: Optional[str],
) -> ProjectionSection:
    subject_known = bool(history and (history.present or history.event_count))
    ledger_state = "degraded" if read_error else ("available" if history else "unknown")
    relationship_state = (
        "unknown" if not edge_events else "degraded"
    )  # relation set completeness is not exposed by replay
    dims = [
        {
            "id": "canonical_graph_read",
            "state": ledger_state,
            "reason": read_error,
        },
        {
            "id": "subject_presence",
            "state": "available" if subject_known else "unknown",
            "reason": None if subject_known else "subject_not_observed_in_replayed_ledger_prefix",
        },
        {
            "id": "relationship_event_coverage",
            "state": relationship_state,
            "reason": "ledger_replay_has_no_completeness_watermark",
        },
        {
            "id": "freshness",
            "state": "unknown",
            "reason": "no relationship freshness SLA or complete source watermark is supplied",
        },
        {
            "id": "graph_mutation_policy",
            "state": "available",
            "reason": "read_only_projection_no_graph_mutations",
        },
    ]
    overall = "degraded" if history is not None or read_error else "unknown"
    return ProjectionSection(
        id="state",
        state=overall,  # type: ignore[arg-type]
        title="Relationship coverage state",
        content={"dimensions": dims, "relationshipEventCount": len(edge_events)},
    )


def _summary_section(
    request: ProjectionRequest,
    history: Optional[SubjectHistory],
    edge_events: list[SubjectEvent],
    live_edges: list[dict[str, Any]],
    read_error: Optional[str],
    anchor: Optional[str],
    population_scope: Optional[PopulationScopeRead] = None,
    source_scope: Optional[SourceSubjectScopeRead] = None,
) -> ProjectionSection:
    has_subject = bool(history and (history.present or history.event_count))
    state = "degraded" if read_error or history is not None else "unknown"
    return ProjectionSection(
        id="summary",
        state=state,  # type: ignore[arg-type]
        title="Relationship graph summary",
        content={
            "subject": {"kind": request.subject.kind, "id": request.subject.id},
            "subjectObserved": has_subject,
            "knowledgeAnchor": anchor or "known_now",
            "relationshipEventCount": len(edge_events),
            "replayedLiveEdgeCount": len(live_edges),
            "coverage": "unknown",
            "freshness": {
                "state": "unknown",
                "latestRecordedAt": _latest_recorded_at(edge_events),
                "sourceTimestamps": "preserved",
                "reason": "no relationship freshness SLA or complete source watermark is supplied",
            },
            "readAuthority": (
                "population_membership_materialization+graph_history_replay"
                if population_scope is not None
                else "identity360+graph_history_replay"
                if source_scope is not None
                else "graph_history_replay"
            ),
            "populationScope": (
                {
                    "state": population_scope.state,
                    "memberCount": len(population_scope.entity_ids),
                    "relationshipScope": "induced_subgraph_within_verified_members",
                    "evidenceRefs": [
                        ref.model_dump(mode="json", by_alias=True)
                        for ref in population_scope.evidence_refs
                    ],
                    "reason": population_scope.reason,
                }
                if population_scope is not None
                else None
            ),
            "sourceIdentityScope": (
                {
                    "state": source_scope.state,
                    "canonicalEntityId": source_scope.canonical_entity_id,
                    "evidenceRefs": [
                        ref.model_dump(mode="json", by_alias=True)
                        for ref in source_scope.evidence_refs
                    ],
                    "reason": source_scope.reason,
                }
                if source_scope is not None
                else None
            ),
        },
        warnings=(
            ["ledger_replay_completeness_is_unknown"]
            if history is not None
            else ([read_error] if read_error else None)
        ),
    )


def _latest_recorded_at(events: list[SubjectEvent]) -> Optional[str]:
    stamped = [
        (coerce_utc_lenient(event.recorded_at), event.recorded_at)
        for event in events
        if event.recorded_at
    ]
    stamped = [(instant, raw) for instant, raw in stamped if instant is not None]
    if not stamped:
        return None
    return max(stamped, key=lambda item: item[0])[1]


def _timeline_section(
    events: list[SubjectEvent],
    history: Optional[SubjectHistory],
    read_error: Optional[str],
    page_warnings: list[str],
) -> ProjectionSection:
    views = [
        {
            "kind": event.kind,
            "operation": event.operation,
            "edgeType": event.edge_type,
            "from": event.from_vertex_id,
            "to": event.to_vertex_id,
            "recordedAt": event.recorded_at,
            "validFrom": event.valid_from,
            "mutationId": event.mutation_id,
            "aggregateId": event.aggregate_id,
            # Free-form revocation reasons are not copied into the projection.
        }
        for event in events
    ]
    return ProjectionSection(
        id="timeline",
        state=_section_state(history, bool(events), read_error),  # type: ignore[arg-type]
        title="Relationship edge history",
        content={
            "events": views,
            "count": len(views),
            "coverage": "unknown",
            "temporalBasis": "recordedAt is knowledge time; validFrom is valid time",
        },
        warnings=page_warnings or (["ledger_replay_completeness_is_unknown"] if history else None),
    )


def _claims(
    request: ProjectionRequest,
    edge_events: list[SubjectEvent],
    refs: list[EvidenceRef],
) -> list[ClaimEnvelope]:
    ref_by_id = {ref.id: ref for ref in refs}
    base_domain_slot_ids = _domain_slot_ids(request.subject.kind)
    claims: list[ClaimEnvelope] = []
    for index, event in enumerate(edge_events):
        ref = ref_by_id.get(event.mutation_id)
        if ref is None:
            continue
        domain_slot_ids = list(base_domain_slot_ids)
        if (
            event.edge_type == _SPAWNED_SUBAGENT_EDGE
            and event.from_vertex_id == request.subject.id
            and "spawned_agents" not in domain_slot_ids
        ):
            domain_slot_ids.append("spawned_agents")
        edge = f"{event.from_vertex_id} -[{event.edge_type}]-> {event.to_vertex_id}"
        claims.append(
            ClaimEnvelope(
                id=f"relationship.edge_event.{index}",
                kind="relationship_graph_event",
                subject=request.subject,
                evidenceRefs=[ref],
                claims=[
                    f"canonical graph mutation ledger records {event.kind} for {edge}",
                    f"recordedAt={event.recorded_at}; validFrom={event.valid_from or 'unknown'}",
                ],
                claimState=EpistemicStatus.OBSERVED,
                domainSlotIds=domain_slot_ids or None,
            )
        )
        if len(claims) >= _MAX_CLAIMS:
            break
    return claims


def _domain_slot_ids(subject_kind: str) -> list[str]:
    slot_ids: set[str] = set()
    for surface in PRODUCT_360_SURFACE_DEFINITIONS.values():
        if not isinstance(surface, dict):
            continue
        for slot in surface.get("domainSlots", []):
            if not isinstance(slot, dict):
                continue
            for binding in slot.get("projectionBindings", []):
                if (
                    isinstance(binding, dict)
                    and binding.get("projectionId") == PROJECTION_ID
                    and subject_kind in binding.get("subjectKinds", [])
                    and isinstance(slot.get("id"), str)
                    and slot.get("id") != "spawned_agents"
                ):
                    slot_ids.add(slot["id"])
    return sorted(slot_ids)


def _agent_spawned_agents_section(
    events: list[SubjectEvent],
    history: Optional[SubjectHistory],
    read_error: Optional[str],
) -> ProjectionSection:
    """Expose only outgoing SPAWNED_SUBAGENT edges with ledger evidence.

    The history reader is a bounded ledger-prefix replay without a completeness
    watermark. A recorded edge can be shown as present in that replay, but an
    empty result cannot prove that no child agents exist.
    """
    refs_by_id = {ref.id: ref for ref in _evidence_refs(events)}
    live_edges = set(history.live_edges) if history is not None else set()
    spawned_agents: list[dict[str, Any]] = []
    for event in events:
        if (
            event.edge_type != _SPAWNED_SUBAGENT_EDGE
            or event.kind not in {"edge_added", "edge_revoked"}
            or not event.from_vertex_id
            or not event.to_vertex_id
        ):
            continue
        evidence_ref = refs_by_id.get(event.mutation_id)
        if evidence_ref is None:
            continue
        edge_key = (
            _SPAWNED_SUBAGENT_EDGE,
            event.from_vertex_id,
            event.to_vertex_id,
        )
        spawned_agents.append(
            {
                "parentGraphAgentReference": event.from_vertex_id,
                "spawnedGraphAgentReference": event.to_vertex_id,
                "relationshipState": (
                    "live_in_replayed_prefix"
                    if edge_key in live_edges
                    else "revoked_in_replayed_prefix"
                ),
                "recordedAt": event.recorded_at,
                "validFrom": event.valid_from,
                "evidenceRef": evidence_ref.model_dump(mode="json", by_alias=True),
            }
        )

    if read_error:
        state = "degraded"
        content = None
        warnings = ["spawned_agent_graph_read_unavailable"]
    elif spawned_agents:
        state = "degraded"
        content = {
            "spawnedAgents": spawned_agents,
            "stateBasis": "tenant_graph_mutation_ledger_replay",
            "coverage": "unknown",
            "coverageReason": "the replayed ledger prefix has no completeness watermark",
        }
        warnings = ["spawned_agent_ledger_prefix_incomplete"]
    else:
        state = "unknown"
        content = None
        warnings = ["no_spawned_agent_edge_observed_in_incomplete_ledger_prefix"]

    return ProjectionSection(
        id="agent_spawned_agents",
        state=state,  # type: ignore[arg-type]
        title="Observed spawned-agent relationships",
        content=content,
        warnings=warnings,
        canonicalAuthorityRefs=["graph", "relationship_facts", "temporal"],
    )


__all__ = [
    "OUTPUT_SECTIONS",
    "SUPPORTED_TEMPORAL_MODES",
    "LedgerRelationshipReader",
    "Relationship360Provider",
    "RelationshipRead",
    "register_provider",
]
