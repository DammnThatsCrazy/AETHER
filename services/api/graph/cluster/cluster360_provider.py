"""Read-only Cluster360 projection over tenant-scoped graph history.

The provider assembles only graph membership edges that are present in the
canonical mutation-ledger replay. Cluster economics, risk, and timeline
summaries exposed by older HTTP routes are not treated as authoritative inputs:
they include graph-property rollups and legacy event fallbacks that are not
bound to canonical economic or evidence authorities.

Ledger replay is bounded but does not report whether its row ceiling was hit.
Every result therefore reports coverage as unknown, including an observed zero;
it never turns an empty replay prefix into a definitive absence claim. The
provider has no write surface and does not create membership or cluster truth.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional, Protocol

from graph.operational_intelligence.models import EvidenceRef, PageInfo
from graph.temporal360.history_replay import (
    GraphHistoryReplay,
    KnownState,
    SubjectEvent,
    SubjectHistory,
)
from shared.contracts_models.epistemic import EpistemicStatus
from shared.graph.graph import Edge, EdgeType, Vertex, VertexType
from shared.graph.mutation_gateway import GraphReplayState
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
from shared.intelligence_projections.registry import ProviderRegistry

PROJECTION_ID = "cluster360"
OUTPUT_SECTIONS: tuple[str, ...] = (
    "summary",
    "state",
    "evidence",
    "findings",
    "health",
)
SUPPORTED_TEMPORAL_MODES: frozenset[str] = frozenset({"as_of", "window"})

# Keep this in step with the graph cluster taxonomy in graph/cluster/routes.py.
CLUSTER_VERTEX_TYPES: frozenset[str] = frozenset(
    {
        VertexType.IDENTITY_CLUSTER,
        VertexType.HOUSEHOLD_CLUSTER,
        VertexType.ORG_CLUSTER,
        VertexType.DEVICE_CLUSTER,
        VertexType.WALLET_CLUSTER,
        VertexType.BEHAVIORAL_CLUSTER,
        VertexType.GEOGRAPHIC_CLUSTER,
        VertexType.ECONOMIC_SEGMENT,
        VertexType.ECONOMIC_CLUSTER,
        VertexType.CAMPAIGN_COHORT,
        VertexType.JOURNEY_CLUSTER,
        VertexType.FRAUD_NETWORK_CLUSTER,
        VertexType.RISK_CLUSTER,
        VertexType.DORMANT_COHORT,
        VertexType.REACTIVATED_COHORT,
        VertexType.UNRESOLVED_CLUSTER,
    }
)
MEMBERSHIP_EDGE_TYPES: frozenset[str] = frozenset(
    {EdgeType.MEMBER_OF_CLUSTER, EdgeType.MEMBER_OF}
)

_MAX_MEMBERSHIPS = 200
_MAX_TRANSITIONS = 100
_MAX_EVIDENCE_REFS = 200
_MAX_CLAIMS = 100
_CATALOG_POPULATION_SLOT = "population_context"
_LEDGER_SOURCE = "graph_mutation_ledger"


class ClusterReadAuthority(Protocol):
    """Read seams over the graph ledger and tenant-owned population registry."""

    async def graph_state(
        self, *, tenant_id: str, as_of: Optional[str]
    ) -> KnownState:
        ...

    async def subject_history(
        self,
        *,
        tenant_id: str,
        subject_id: str,
        as_of: Optional[str],
    ) -> SubjectHistory:
        ...

    async def population(
        self, *, tenant_id: str, population_id: str
    ) -> Optional[dict[str, Any]]:
        ...

    async def populations(self, *, tenant_id: str) -> list[dict[str, Any]]:
        ...


class LedgerClusterReadAuthority:
    """Default read implementation over the graph ledger and population rows.

    Population row lookup is limited to tenant ownership and stable ID/type
    context. Membership remains sourced from the graph ledger, which the
    population governance path writes through GraphMutationGateway.
    """

    def __init__(self, replay: Optional[GraphHistoryReplay] = None) -> None:
        self._replay = replay if replay is not None else GraphHistoryReplay()

    async def graph_state(
        self, *, tenant_id: str, as_of: Optional[str]
    ) -> KnownState:
        if as_of is None:
            return await self._replay.known_now(tenant_id)
        return await self._replay.known_as_of(tenant_id, as_of)

    async def subject_history(
        self,
        *,
        tenant_id: str,
        subject_id: str,
        as_of: Optional[str],
    ) -> SubjectHistory:
        return await self._replay.subject_history(
            tenant_id, subject_id, as_of=as_of
        )

    async def population(
        self, *, tenant_id: str, population_id: str
    ) -> Optional[dict[str, Any]]:
        from identity.population.registry import population_repo

        population = await population_repo.find_by_id(population_id)
        if population is None or population.get("tenant_id") != tenant_id:
            return None
        return population

    async def populations(self, *, tenant_id: str) -> list[dict[str, Any]]:
        from identity.population.registry import population_repo

        return await population_repo.query_populations(tenant_id, limit=1000)


@dataclass(frozen=True)
class _TemporalAnchor:
    mode: str
    as_of: Optional[str]
    warning: Optional[str]


@dataclass(frozen=True)
class _Membership:
    edge: Edge
    group_id: str
    group_kind: str
    group_type: str
    member_id: str
    member_type: str
    valid_from: Optional[str]
    evidence: Optional[EvidenceRef]


class Cluster360Provider:
    """Tenant-scoped Cluster360 projection with read-only graph semantics."""

    projection_id = PROJECTION_ID
    contract_version = INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION
    graph_mutation_policy = "read_only"

    def __init__(self, reader: Optional[ClusterReadAuthority] = None) -> None:
        self._reader = reader if reader is not None else LedgerClusterReadAuthority()

    async def project(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
    ) -> ProjectionResult:
        now = datetime.now(timezone.utc).isoformat()
        anchor = _resolve_anchor(request)
        warnings: list[str] = ["graph_ledger_replay_completeness_is_unknown"]
        if anchor.warning:
            warnings.append(anchor.warning)
        if context.registryState == "in_flight":
            warnings.append("cluster360_registry_implementation_state_is_in_flight")
        population_dependency = next(
            (
                dependency
                for dependency in context.dependencyState
                if dependency.projectionId == "population360"
            ),
            None,
        )
        if population_dependency is None or population_dependency.state != "available":
            warnings.append("population360_projection_dependency_not_available")
        warnings.extend(
            [
                "exploration_fabric_filters_not_integrated",
                "computation_substrate_not_integrated",
            ]
        )

        state: Optional[GraphReplayState] = None
        history: Optional[SubjectHistory] = None
        population_row: Optional[dict[str, Any]] = None
        populations: list[dict[str, Any]] = []
        read_error: Optional[str] = None

        # Authenticated runtime tenant scope is authoritative. A mismatched
        # direct invocation must not even touch either read authority.
        if context.tenantId != request.tenantId:
            read_error = "tenant_scope_mismatch"
        elif request.subject.kind not in {"entity", "cluster", "population"}:
            read_error = "cluster_subject_kind_unsupported"
        else:
            try:
                snapshot = await self._reader.graph_state(
                    tenant_id=request.tenantId, as_of=anchor.as_of
                )
                state = snapshot.state
                history = await self._reader.subject_history(
                    tenant_id=request.tenantId,
                    subject_id=request.subject.id,
                    as_of=anchor.as_of,
                )
            except Exception:  # noqa: BLE001 - errors become content-free states
                state = None
                history = None
                read_error = "cluster_authority_unavailable"
            if read_error is None and request.subject.kind in {"cluster", "population"}:
                try:
                    population_row = await self._reader.population(
                        tenant_id=request.tenantId,
                        population_id=request.subject.id,
                    )
                except Exception:  # noqa: BLE001 - no registry diagnostics in output
                    if request.subject.kind == "population":
                        read_error = "population_authority_unavailable"
                    else:
                        warnings.append("population_registry_unavailable_cluster_fallback_unknown")
            if read_error is None and request.subject.kind == "entity":
                try:
                    populations = await self._reader.populations(
                        tenant_id=request.tenantId
                    )
                    if len(populations) >= 1000:
                        warnings.append("population_registry_cap_may_apply")
                except Exception:  # noqa: BLE001 - population links remain unresolved
                    populations = []
                    warnings.append("population_registry_unavailable_population_links_unresolved")

        subject_vertex = (
            state.vertices.get(request.subject.id) if state is not None else None
        )
        population_row = _population_as_of(
            _tenant_owned_population(population_row, request.tenantId),
            anchor.as_of,
        )
        population_index = _population_index(
            populations, request.tenantId, anchor.as_of
        )
        if population_row is not None and population_row.get("id"):
            population_index[str(population_row["id"])] = population_row
        subject_kind = _resolved_subject_kind(
            request.subject.kind,
            subject_vertex,
            population_row,
        )
        subject_known = _subject_known(
            request.subject.kind,
            subject_vertex,
            population_row,
        )
        if read_error is None and not subject_known:
            warnings.append("subject_not_found_in_tenant_scoped_authorities")

        memberships: list[_Membership] = []
        if read_error is None and state is not None and history is not None and subject_known:
            memberships = _resolve_memberships(
                request.subject.kind,
                request.subject.id,
                subject_kind,
                state,
                history,
                population_index,
            )

        if len(memberships) > _MAX_MEMBERSHIPS:
            warnings.append("membership_output_cap_applied")
        page_memberships, page_info, page_warnings = _page_memberships(
            memberships, request
        )
        warnings.extend(page_warnings)

        membership_payload = [
            _membership_payload(item) for item in page_memberships
        ]
        evidence_refs = _unique_evidence(
            item.evidence for item in page_memberships if item.evidence is not None
        )
        transitions = _window_transitions(
            request,
            memberships,
            history,
            state,
            subject_kind,
            population_index,
        )

        if read_error is not None:
            primary_state = "degraded"
            evidence_state = "unknown"
        elif not subject_known:
            primary_state = "unknown"
            evidence_state = "unknown"
        else:
            # Even a populated replay is an observed prefix: the ledger API
            # exposes no completeness watermark or truncation bit.
            primary_state = "degraded"
            evidence_state = "degraded" if evidence_refs else "unknown"

        sections = [
            ProjectionSection(
                id="summary",
                state=primary_state,
                title="Cluster membership summary",
                content={
                    "subject": {
                        "kind": request.subject.kind,
                        "id": request.subject.id,
                        "resolvedKind": subject_kind,
                        "type": _vertex_type(subject_vertex),
                    },
                    "readAuthority": "graph_history_replay",
                    "knowledgeTime": "KNOWN_THEN" if anchor.as_of else "KNOWN_NOW",
                    "asOf": anchor.as_of,
                    "observedMembershipCount": len(memberships),
                    "returnedMembershipCount": len(page_memberships),
                    "coverage": "unknown",
                    "membershipRecords": membership_payload,
                    "limitations": _limitations(warnings, read_error),
                },
                warnings=warnings or None,
            ),
            ProjectionSection(
                id="state",
                state=primary_state,
                title="Membership state",
                content={
                    "dimensions": [
                        {
                            "id": "cluster_membership",
                            "state": "unknown" if not subject_known else "degraded",
                            "coverage": "unknown",
                            "observedCount": len(memberships),
                            "readAuthority": "graph_history_replay",
                        }
                    ],
                    "memberships": membership_payload,
                    "temporalMode": anchor.mode,
                    "asOf": anchor.as_of,
                },
                warnings=warnings or None,
            ),
            ProjectionSection(
                id="evidence",
                state=evidence_state,
                title="Membership evidence",
                content={
                    "count": len(evidence_refs),
                    "coverage": "unknown",
                    "items": [ref.model_dump(by_alias=True) for ref in evidence_refs],
                },
                warnings=warnings or None,
            ),
            ProjectionSection(
                id="findings",
                state="degraded" if subject_known and read_error is None else primary_state,
                title="Coverage and temporal findings",
                content={
                    "coverage": "unknown",
                    "warnings": warnings,
                    "membershipTransitions": transitions,
                    "temporalInterpretation": (
                        (
                            "window filters ledger event valid-time anchors; "
                            f"snapshot remains {'KNOWN_THEN' if anchor.as_of else 'KNOWN_NOW'}"
                        )
                        if anchor.mode == "window"
                        else (
                            "missing as-of anchor; current KNOWN_NOW state was served"
                            if anchor.as_of is None
                            else "as_of reconstructs graph knowledge at the requested ledger time"
                        )
                    ),
                },
                warnings=warnings or None,
            ),
            ProjectionSection(
                id="health",
                state="degraded" if read_error is None else "missing",
                title="Projection health",
                content={
                    "coverage": "unknown",
                    "freshness": "unknown",
                    "lastSubjectLedgerEventAt": history.last_recorded if history else None,
                    "authorityState": "unavailable" if read_error else "readable_bounded_replay",
                    "reasonCodes": [read_error] if read_error else warnings,
                },
                warnings=warnings or None,
            ),
        ]

        claims = _claims(
            request,
            page_memberships,
            subject_kind,
            subject_known=subject_known and read_error is None,
        )
        return ProjectionResult(
            projectionId=PROJECTION_ID,
            tenantId=request.tenantId,
            contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
            sections=sections,
            claims=claims,
            dependencyState=context.dependencyState,
            asOf=anchor.as_of,
            generatedAt=now,
            page=page_info,
            degradedReasons=[],
            temporalMode=anchor.mode,
            lensIds=request.lensIds,
        )


def register_provider(registry: ProviderRegistry) -> Cluster360Provider:
    """Register explicitly; shared projection boot wiring owns invocation."""
    provider = Cluster360Provider()
    registry.register(provider, source="services/api/graph/cluster")
    return provider


def _resolve_anchor(request: ProjectionRequest) -> _TemporalAnchor:
    mode = request.temporalMode or "window"
    if request.asOf is not None:
        return _TemporalAnchor(mode=mode, as_of=request.asOf, warning=None)
    if mode == "as_of":
        anchor = request.timeRange.from_ if request.timeRange else None
        if anchor is not None:
            return _TemporalAnchor(mode=mode, as_of=anchor, warning=None)
        return _TemporalAnchor(
            mode="as_of",
            as_of=None,
            warning="as_of_anchor_missing_known_now_served",
        )
    if mode != "window":
        return _TemporalAnchor(
            mode="window",
            as_of=None,
            warning="unsupported_temporal_mode_known_now_served",
        )
    return _TemporalAnchor(mode=mode, as_of=None, warning=None)


def _population_as_of(
    population: Optional[dict[str, Any]], as_of: Optional[str]
) -> Optional[dict[str, Any]]:
    if population is None or as_of is None:
        return population
    created_at = _parse_instant(population.get("created_at"))
    anchor = _parse_instant(as_of)
    if created_at is None or anchor is None or created_at > anchor:
        return None
    return population


def _population_index(
    populations: list[dict[str, Any]], tenant_id: str, as_of: Optional[str]
) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for population in populations:
        population = _tenant_owned_population(population, tenant_id)
        if population is None:
            continue
        population = _population_as_of(population, as_of)
        if population is None or not population.get("id"):
            continue
        index[str(population["id"])] = population
    return index


def _tenant_owned_population(
    population: Optional[dict[str, Any]], tenant_id: str
) -> Optional[dict[str, Any]]:
    if population is None or population.get("tenant_id") != tenant_id:
        return None
    return population


def _resolved_subject_kind(
    requested_kind: str,
    vertex: Optional[Vertex],
    population: Optional[dict[str, Any]],
) -> str:
    if requested_kind == "population" or (
        requested_kind == "cluster" and population is not None and vertex is None
    ):
        return "population"
    if requested_kind == "cluster":
        return "cluster"
    return "entity"


def _subject_known(
    requested_kind: str,
    vertex: Optional[Vertex],
    population: Optional[dict[str, Any]],
) -> bool:
    if requested_kind == "entity":
        return vertex is not None and vertex.vertex_type not in CLUSTER_VERTEX_TYPES
    if requested_kind == "cluster":
        return (vertex is not None and vertex.vertex_type in CLUSTER_VERTEX_TYPES) or (
            vertex is None and population is not None
        )
    if requested_kind == "population":
        return population is not None
    return False


def _resolve_memberships(
    requested_kind: str,
    subject_id: str,
    resolved_kind: str,
    state: GraphReplayState,
    history: SubjectHistory,
    populations: dict[str, dict[str, Any]],
) -> list[_Membership]:
    edges = [
        edge
        for edge in state.edges
        if edge.edge_type in MEMBERSHIP_EDGE_TYPES
        and subject_id in {edge.from_vertex_id, edge.to_vertex_id}
    ]
    event_refs = _live_edge_evidence(history)
    memberships: list[_Membership] = []
    seen: set[tuple[str, str, str]] = set()

    for edge in edges:
        edge_key = (edge.edge_type, edge.from_vertex_id, edge.to_vertex_id)
        if edge_key in seen:
            continue
        seen.add(edge_key)
        other_id = (
            edge.to_vertex_id if edge.from_vertex_id == subject_id else edge.from_vertex_id
        )
        other_vertex = state.vertices.get(other_id)

        if requested_kind == "entity":
            group_vertex = other_vertex
            if edge.edge_type == EdgeType.MEMBER_OF_CLUSTER:
                if group_vertex is None or group_vertex.vertex_type not in CLUSTER_VERTEX_TYPES:
                    continue
                group_kind = "cluster"
                group_type = group_vertex.vertex_type
            elif edge.edge_type == EdgeType.MEMBER_OF:
                if group_vertex is not None and group_vertex.vertex_type in CLUSTER_VERTEX_TYPES:
                    group_kind = "cluster"
                    group_type = group_vertex.vertex_type
                elif other_id in populations:
                    group_kind = "population"
                    group_type = str(populations[other_id].get("population_type") or "unknown")
                else:
                    continue
            else:  # defensive against future taxonomy expansion
                continue
            member_id = subject_id
            member_vertex = state.vertices.get(subject_id)
            member_type = member_vertex.vertex_type if member_vertex else "unknown"
            group_id = other_id
        else:
            # Cluster/population subjects return their observed member set.
            if requested_kind == "population" or resolved_kind == "population":
                if edge.edge_type != EdgeType.MEMBER_OF:
                    continue
            elif edge.edge_type == EdgeType.MEMBER_OF:
                # Generic MEMBER_OF is admitted for a graph cluster only when
                # the subject itself is a typed cluster; organization edges are
                # otherwise not reinterpreted as cluster membership.
                if not any(
                    edge_vertex.vertex_id == subject_id
                    and edge_vertex.vertex_type in CLUSTER_VERTEX_TYPES
                    for edge_vertex in (state.vertices.get(subject_id),)
                    if edge_vertex is not None
                ):
                    continue
            member_vertex = other_vertex
            if member_vertex is None:
                continue
            group_id = subject_id
            group_kind = resolved_kind
            if resolved_kind == "population":
                group_type = str(populations.get(subject_id, {}).get("population_type") or "unknown")
            else:
                group_vertex = state.vertices.get(subject_id)
                group_type = group_vertex.vertex_type if group_vertex else "unknown"
            member_id = other_id
            member_type = member_vertex.vertex_type

        memberships.append(
            _Membership(
                edge=edge,
                group_id=group_id,
                group_kind=group_kind,
                group_type=group_type,
                member_id=member_id,
                member_type=member_type,
                valid_from=_edge_valid_from(edge),
                evidence=event_refs.get(edge_key),
            )
        )

    return sorted(
        memberships,
        key=lambda item: (
            item.group_id,
            item.member_id,
            item.edge.edge_type,
        ),
    )


def _live_edge_evidence(
    history: SubjectHistory,
) -> dict[tuple[str, str, str], EvidenceRef]:
    live = set(history.live_edges)
    evidence: dict[tuple[str, str, str], EvidenceRef] = {}
    for event in history.events:
        if (
            event.kind != "edge_added"
            or event.edge_type is None
            or event.from_vertex_id is None
            or event.to_vertex_id is None
        ):
            continue
        key = (event.edge_type, event.from_vertex_id, event.to_vertex_id)
        if key not in live:
            continue
        evidence[key] = EvidenceRef(
            id=event.mutation_id,
            type="relationship",
            source=_LEDGER_SOURCE,
            observedAt=event.recorded_at or None,
        )
    return evidence


def _membership_payload(item: _Membership) -> dict[str, Any]:
    return {
        "membershipId": _membership_id(item.edge),
        "membershipType": item.edge.edge_type,
        "groupId": item.group_id,
        "groupKind": item.group_kind,
        "groupType": item.group_type,
        "memberId": item.member_id,
        "memberType": item.member_type,
        "validFrom": item.valid_from,
        "confidence": _confidence(item.edge.properties.get("confidence")),
        "evidenceRef": item.evidence.model_dump(by_alias=True) if item.evidence else None,
    }


def _claims(
    request: ProjectionRequest,
    memberships: list[_Membership],
    subject_kind: str,
    *,
    subject_known: bool,
) -> list[ClaimEnvelope]:
    if not subject_known:
        return []
    claims: list[ClaimEnvelope] = []
    for item in memberships[:_MAX_CLAIMS]:
        if item.evidence is None:
            continue
        if request.subject.kind == "entity":
            statement = (
                f"Entity {item.member_id} has an observed membership edge to "
                f"{item.group_kind} {item.group_id}."
            )
        else:
            statement = (
                f"Entity {item.member_id} has an observed membership edge in "
                f"{subject_kind} {item.group_id}."
            )
        claims.append(
            ClaimEnvelope(
                id=_membership_id(item.edge),
                kind="cluster_membership",
                subject=request.subject,
                evidenceRefs=[item.evidence],
                claims=[statement],
                confidence=_confidence(item.edge.properties.get("confidence")),
                claimState=EpistemicStatus.OBSERVED,
                domainSlotIds=[_CATALOG_POPULATION_SLOT],
            )
        )
    return claims


def _page_memberships(
    memberships: list[_Membership], request: ProjectionRequest
) -> tuple[list[_Membership], PageInfo, list[str]]:
    requested_limit = request.page.limit if request.page is not None else 50
    page_size = min(requested_limit, _MAX_MEMBERSHIPS)
    warnings: list[str] = []
    offset = 0
    cursor = request.page.cursor if request.page is not None else None
    if cursor:
        try:
            offset = max(0, int(cursor))
        except (TypeError, ValueError):
            warnings.append("invalid_membership_cursor_ignored")
    selected = memberships[offset : offset + page_size]
    next_offset = offset + page_size
    has_next = next_offset < len(memberships)
    page = PageInfo(
        nextCursor=str(next_offset) if has_next else None,
        previousCursor=str(max(0, offset - page_size)) if offset > 0 else None,
        hasNextPage=has_next,
        hasPreviousPage=offset > 0,
        # Replay coverage is unknown; this is not a tenant-wide estimate.
        totalEstimate=None,
    )
    return selected, page, warnings


def _window_transitions(
    request: ProjectionRequest,
    memberships: list[_Membership],
    history: Optional[SubjectHistory],
    state: Optional[GraphReplayState],
    resolved_subject_kind: str,
    populations: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    if (
        (request.temporalMode or "window") != "window"
        or request.timeRange is None
        or history is None
        or state is None
    ):
        return []
    start = _parse_instant(request.timeRange.from_)
    end = _parse_instant(request.timeRange.to)
    known_edges = {
        (item.edge.edge_type, item.edge.from_vertex_id, item.edge.to_vertex_id)
        for item in memberships
    }
    relevant_types = MEMBERSHIP_EDGE_TYPES
    transitions: list[dict[str, Any]] = []
    for event in history.events:
        if event.kind not in {"edge_added", "edge_revoked"}:
            continue
        if event.edge_type not in relevant_types or not event.from_vertex_id or not event.to_vertex_id:
            continue
        key = (event.edge_type, event.from_vertex_id, event.to_vertex_id)
        touches_subject = request.subject.id in {event.from_vertex_id, event.to_vertex_id}
        if not touches_subject:
            continue
        if request.subject.kind == "entity" and event.edge_type == EdgeType.MEMBER_OF:
            other_id = event.to_vertex_id if event.from_vertex_id == request.subject.id else event.from_vertex_id
            other = state.vertices.get(other_id)
            if (
                (other is None or other.vertex_type not in CLUSTER_VERTEX_TYPES)
                and other_id not in populations
            ):
                continue
        if request.subject.kind in {"cluster", "population"} and key not in known_edges:
            # Historical/revoked population membership can still be relevant;
            # graph vertex type plus edge taxonomy constrains cluster edges.
            other_id = event.to_vertex_id if event.from_vertex_id == request.subject.id else event.from_vertex_id
            other = state.vertices.get(other_id)
            if request.subject.kind == "cluster" and resolved_subject_kind == "population" and event.edge_type == EdgeType.MEMBER_OF:
                pass
            elif request.subject.kind == "cluster" and (
                event.edge_type == EdgeType.MEMBER_OF_CLUSTER
                or (other is not None and other.vertex_type in CLUSTER_VERTEX_TYPES)
            ):
                pass
            elif request.subject.kind == "population" and event.edge_type == EdgeType.MEMBER_OF:
                pass
            else:
                continue
        valid_at = _parse_instant(event.valid_from)
        if valid_at is None or (start is not None and valid_at < start) or (end is not None and valid_at > end):
            continue
        transitions.append(
            {
                "kind": event.kind,
                "edgeType": event.edge_type,
                "from": event.from_vertex_id,
                "to": event.to_vertex_id,
                "validFrom": event.valid_from,
                "recordedAt": event.recorded_at,
                "mutationId": event.mutation_id,
            }
        )
    transitions.sort(key=lambda row: (row["validFrom"] or "", row["mutationId"]))
    return transitions[:_MAX_TRANSITIONS]


def _unique_evidence(refs: Any) -> list[EvidenceRef]:
    result: list[EvidenceRef] = []
    seen: set[tuple[str, str]] = set()
    for ref in refs:
        key = (ref.source, ref.id)
        if key in seen:
            continue
        seen.add(key)
        result.append(ref)
        if len(result) >= _MAX_EVIDENCE_REFS:
            break
    return result


def _membership_id(edge: Edge) -> str:
    identity = f"{edge.edge_type}:{edge.from_vertex_id}:{edge.to_vertex_id}"
    return "cluster-membership-" + hashlib.sha256(identity.encode()).hexdigest()[:24]


def _edge_valid_from(edge: Edge) -> Optional[str]:
    value = edge.properties.get("valid_from") or edge.properties.get("validFrom")
    return str(value) if value is not None else None


def _vertex_type(vertex: Optional[Vertex]) -> Optional[str]:
    return vertex.vertex_type if vertex is not None else None


def _confidence(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if 0 <= parsed <= 1 else None


def _parse_instant(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _limitations(warnings: list[str], read_error: Optional[str]) -> list[str]:
    limitations = list(dict.fromkeys(warnings))
    if read_error:
        limitations.append(read_error)
    limitations.extend(
        [
            "graph_history_replay_has_no_completeness_watermark",
            "population_membership_history_is_read_from_graph_edges",
            "cluster_economic_rollups_are_not_read_from_the_legacy_route",
            "population_definitions_are_used_only_for_tenant_and_subject_validation",
        ]
    )
    return list(dict.fromkeys(limitations))
