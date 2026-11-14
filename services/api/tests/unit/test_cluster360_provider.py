"""Focused checks for the tenant-scoped, read-only Cluster360 provider."""

from __future__ import annotations

from typing import Any, Optional

import pytest

from graph.operational_intelligence.models import TimeRangeFilter
from graph.temporal360.history_replay import KnownState, SubjectEvent, SubjectHistory
from graph.cluster.cluster360_provider import (
    OUTPUT_SECTIONS,
    Cluster360Provider,
    register_provider,
)
from shared.graph.graph import Edge, EdgeType, Vertex, VertexType
from shared.graph.mutation_gateway import GraphReplayState
from shared.intelligence_projections.contracts import (
    ProjectionRequest,
    ProjectionSubject,
)
from shared.intelligence_projections.registry import ProviderRegistry

TENANT = "tenant_cluster360"
CLUSTER = "cluster-a"
ENTITY = "entity-a"
POPULATION = "population-a"
T1 = "2026-05-01T00:00:00+00:00"
T2 = "2026-05-02T00:00:00+00:00"


def _event(
    *,
    offset: int,
    kind: str,
    edge_type: str,
    source: str,
    target: str,
    valid_from: Optional[str] = T1,
) -> SubjectEvent:
    return SubjectEvent(
        recorded_at={1: T1, 2: T2}[offset],
        ledger_offset=offset,
        kind=kind,
        operation="edge_created" if kind == "edge_added" else "edge_expired",
        aggregate_type="edge",
        aggregate_id=f"{source}:{edge_type}:{target}",
        mutation_id=f"mutation-{offset}",
        valid_from=valid_from,
        edge_type=edge_type,
        from_vertex_id=source,
        to_vertex_id=target,
    )


def _history(
    subject_id: str,
    events: tuple[SubjectEvent, ...] = (),
    *,
    present: bool = True,
    live_edges: tuple[tuple[str, str, str], ...] = (),
) -> SubjectHistory:
    return SubjectHistory(
        subject_id=subject_id,
        as_of=None,
        present=present,
        vertex={"kind": "entity"} if present else None,
        first_recorded=T1 if events else None,
        last_recorded=events[-1].recorded_at if events else None,
        event_count=len(events),
        events=events,
        live_edges=live_edges,
        vertex_supersessions=0,
        incident_edge_adds=sum(event.kind == "edge_added" for event in events),
        incident_edge_revocations=sum(event.kind == "edge_revoked" for event in events),
        digest="history-digest",
    )


def _known_state(vertices: list[Vertex], edges: list[Edge]) -> KnownState:
    return KnownState(
        as_of="now",
        state=GraphReplayState(
            vertices={vertex.vertex_id: vertex for vertex in vertices},
            edges=edges,
            digest="graph-digest",
        ),
        row_count=len(vertices) + len(edges),
        last_offset=len(vertices) + len(edges),
    )


class _Reader:
    def __init__(
        self,
        state: KnownState,
        histories: dict[str, SubjectHistory],
        *,
        population: Optional[dict[str, Any]] = None,
        populations: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        self.state = state
        self.histories = histories
        self.population_record = population
        self.population_records = populations or []
        self.calls: list[tuple[str, str, Optional[str]]] = []

    async def graph_state(self, *, tenant_id: str, as_of: Optional[str]) -> KnownState:
        self.calls.append(("state", tenant_id, as_of))
        if tenant_id != TENANT:
            raise KeyError("tenant mismatch")
        return self.state

    async def subject_history(
        self, *, tenant_id: str, subject_id: str, as_of: Optional[str]
    ) -> SubjectHistory:
        self.calls.append((subject_id, tenant_id, as_of))
        if tenant_id != TENANT:
            raise KeyError("tenant mismatch")
        return self.histories.get(subject_id, _history(subject_id, present=False))

    async def population(
        self, *, tenant_id: str, population_id: str
    ) -> Optional[dict[str, Any]]:
        self.calls.append(("population", tenant_id, population_id))
        if tenant_id != TENANT:
            raise KeyError("tenant mismatch")
        if self.population_record and self.population_record.get("id") == population_id:
            return self.population_record
        return None

    async def populations(self, *, tenant_id: str) -> list[dict[str, Any]]:
        self.calls.append(("populations", tenant_id, None))
        if tenant_id != TENANT:
            raise KeyError("tenant mismatch")
        return self.population_records


async def _context(request: ProjectionRequest):
    return await ProviderRegistry().build_context("cluster360", request)


def _request(
    *,
    kind: str = "cluster",
    subject_id: str = CLUSTER,
    as_of: Optional[str] = None,
    mode: Optional[str] = "window",
    time_range: Optional[TimeRangeFilter] = None,
) -> ProjectionRequest:
    return ProjectionRequest(
        projectionId="cluster360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind=kind, id=subject_id),
        asOf=as_of,
        temporalMode=mode,
        timeRange=time_range,
    )


def _sections(result):
    return {section.id: section for section in result.sections}


def test_register_provider_is_explicit_and_uses_cluster_domain_source() -> None:
    registry = ProviderRegistry()

    provider = register_provider(registry)

    assert registry.get("cluster360") is provider
    assert registry.sources()["cluster360"] == "services/api/graph/cluster"


@pytest.mark.asyncio
async def test_cluster_membership_is_ledger_evidenced_and_coverage_stays_unknown() -> None:
    edge = Edge(
        edge_type=EdgeType.MEMBER_OF_CLUSTER,
        from_vertex_id=ENTITY,
        to_vertex_id=CLUSTER,
        properties={"confidence": "0.8", "valid_from": T1, "tenant_id": TENANT},
    )
    event = _event(
        offset=1,
        kind="edge_added",
        edge_type=EdgeType.MEMBER_OF_CLUSTER,
        source=ENTITY,
        target=CLUSTER,
    )
    reader = _Reader(
        _known_state(
            [
                Vertex(vertex_type=VertexType.IDENTITY_CLUSTER, vertex_id=CLUSTER),
                Vertex(vertex_type=VertexType.USER, vertex_id=ENTITY),
            ],
            [edge],
        ),
        {
            CLUSTER: _history(
                CLUSTER,
                (event,),
                live_edges=((EdgeType.MEMBER_OF_CLUSTER, ENTITY, CLUSTER),),
            )
        },
    )
    provider = Cluster360Provider(reader=reader)
    request = _request()

    result = await provider.project(request, await _context(request))

    assert [section.id for section in result.sections] == list(OUTPUT_SECTIONS)
    sections = _sections(result)
    assert sections["summary"].state == "degraded"
    assert sections["summary"].content["observedMembershipCount"] == 1
    assert sections["summary"].content["coverage"] == "unknown"
    membership = sections["state"].content["memberships"][0]
    assert membership["groupId"] == CLUSTER
    assert membership["memberId"] == ENTITY
    assert membership["confidence"] == 0.8
    assert membership["evidenceRef"]["id"] == "mutation-1"
    assert sections["evidence"].content["items"][0]["source"] == "graph_mutation_ledger"
    assert result.claims[0].domainSlotIds == ["population_context"]
    assert result.claims[0].claimState.value == "observed"


@pytest.mark.asyncio
async def test_population_subject_honors_as_of_and_tenant_owned_definition() -> None:
    edge = Edge(
        edge_type=EdgeType.MEMBER_OF,
        from_vertex_id=ENTITY,
        to_vertex_id=POPULATION,
        properties={"membership_state": "active", "valid_from": T1},
    )
    event = _event(
        offset=1,
        kind="edge_added",
        edge_type=EdgeType.MEMBER_OF,
        source=ENTITY,
        target=POPULATION,
    )
    reader = _Reader(
        _known_state([Vertex(vertex_type=VertexType.USER, vertex_id=ENTITY)], [edge]),
        {
            POPULATION: _history(
                POPULATION,
                (event,),
                present=False,
                live_edges=((EdgeType.MEMBER_OF, ENTITY, POPULATION),),
            )
        },
        population={
            "id": POPULATION,
            "tenant_id": TENANT,
            "population_type": "cohort",
            "created_at": T1,
        },
    )
    provider = Cluster360Provider(reader=reader)
    request = _request(
        kind="population", subject_id=POPULATION, mode="as_of", as_of=T2
    )

    result = await provider.project(request, await _context(request))

    assert result.asOf == T2
    assert reader.calls[0] == ("state", TENANT, T2)
    assert _sections(result)["state"].content["memberships"][0]["groupKind"] == "population"
    assert _sections(result)["state"].content["memberships"][0]["groupType"] == "cohort"
    assert result.claims[0].evidenceRefs[0].id == "mutation-1"


@pytest.mark.asyncio
async def test_entity_subject_excludes_unrelated_generic_organization_membership() -> None:
    cluster_edge = Edge(
        edge_type=EdgeType.MEMBER_OF_CLUSTER,
        from_vertex_id=ENTITY,
        to_vertex_id=CLUSTER,
    )
    organization_edge = Edge(
        edge_type=EdgeType.MEMBER_OF,
        from_vertex_id=ENTITY,
        to_vertex_id="organization-a",
    )
    history = _history(
        ENTITY,
        (
            _event(
                offset=1,
                kind="edge_added",
                edge_type=EdgeType.MEMBER_OF_CLUSTER,
                source=ENTITY,
                target=CLUSTER,
            ),
            _event(
                offset=2,
                kind="edge_added",
                edge_type=EdgeType.MEMBER_OF,
                source=ENTITY,
                target="organization-a",
                valid_from=T2,
            ),
        ),
        live_edges=(
            (EdgeType.MEMBER_OF_CLUSTER, ENTITY, CLUSTER),
            (EdgeType.MEMBER_OF, ENTITY, "organization-a"),
        ),
    )
    reader = _Reader(
        _known_state(
            [
                Vertex(vertex_type=VertexType.USER, vertex_id=ENTITY),
                Vertex(vertex_type=VertexType.IDENTITY_CLUSTER, vertex_id=CLUSTER),
                Vertex(vertex_type=VertexType.ORGANIZATION, vertex_id="organization-a"),
            ],
            [cluster_edge, organization_edge],
        ),
        {ENTITY: history},
    )
    provider = Cluster360Provider(reader=reader)
    request = _request(kind="entity", subject_id=ENTITY)

    result = await provider.project(request, await _context(request))

    memberships = _sections(result)["state"].content["memberships"]
    assert [membership["groupId"] for membership in memberships] == [CLUSTER]
    assert [claim.claims[0] for claim in result.claims] == [
        f"Entity {ENTITY} has an observed membership edge to cluster {CLUSTER}."
    ]


@pytest.mark.asyncio
async def test_foreign_population_is_unknown_and_does_not_disclose_membership() -> None:
    edge = Edge(
        edge_type=EdgeType.MEMBER_OF,
        from_vertex_id=ENTITY,
        to_vertex_id=POPULATION,
    )
    reader = _Reader(
        _known_state([Vertex(vertex_type=VertexType.USER, vertex_id=ENTITY)], [edge]),
        {},
        population={
            "id": POPULATION,
            "tenant_id": "another-tenant",
            "population_type": "cohort",
            "created_at": T1,
        },
    )
    provider = Cluster360Provider(reader=reader)
    request = _request(kind="population", subject_id=POPULATION)

    result = await provider.project(request, await _context(request))

    sections = _sections(result)
    assert sections["summary"].state == "unknown"
    assert sections["state"].content["memberships"] == []
    assert result.claims == []


@pytest.mark.asyncio
async def test_tenant_context_mismatch_prevents_every_authority_read() -> None:
    reader = _Reader(_known_state([], []), {})
    provider = Cluster360Provider(reader=reader)
    request = _request()
    context = await _context(request)
    context.tenantId = "another-tenant"

    result = await provider.project(request, context)

    assert reader.calls == []
    assert _sections(result)["summary"].state == "degraded"
    assert result.claims == []


@pytest.mark.asyncio
async def test_window_reports_only_valid_time_anchored_membership_transitions() -> None:
    add = _event(
        offset=1,
        kind="edge_added",
        edge_type=EdgeType.MEMBER_OF_CLUSTER,
        source=ENTITY,
        target=CLUSTER,
        valid_from=T1,
    )
    revoke = _event(
        offset=2,
        kind="edge_revoked",
        edge_type=EdgeType.MEMBER_OF_CLUSTER,
        source=ENTITY,
        target=CLUSTER,
        valid_from=T2,
    )
    reader = _Reader(
        _known_state(
            [
                Vertex(vertex_type=VertexType.IDENTITY_CLUSTER, vertex_id=CLUSTER),
                Vertex(vertex_type=VertexType.USER, vertex_id=ENTITY),
            ],
            [],
        ),
        {
            CLUSTER: _history(
                CLUSTER,
                (add, revoke),
                live_edges=(),
            )
        },
    )
    provider = Cluster360Provider(reader=reader)
    request = _request(
        kind="cluster",
        subject_id=CLUSTER,
        mode="window",
        time_range=TimeRangeFilter(from_=T1, to=T2),
    )

    result = await provider.project(request, await _context(request))

    transitions = _sections(result)["findings"].content["membershipTransitions"]
    assert [event["mutationId"] for event in transitions] == ["mutation-1", "mutation-2"]
    assert _sections(result)["findings"].content["temporalInterpretation"].startswith(
        "window filters ledger event valid-time anchors"
    )
