"""Focused behavior checks for the read-only Relationship360 provider."""

from __future__ import annotations

from typing import Optional

import pytest

from graph.temporal360.history_replay import SubjectEvent, SubjectHistory
from graph.operational_intelligence.models import EvidenceRef, TimeRangeFilter
from identity.identity.source_subject_scope import SourceSubjectScopeRead
from identity.profile.profile360_provider import IdentityBindingRead
from identity.population360.scope import PopulationScopeRead
from identity.relationship_intelligence.relationship360_provider import (
    OUTPUT_SECTIONS,
    Relationship360Provider,
)
from shared.intelligence_projections.contracts import (
    ProjectionRequest,
    ProjectionSubject,
)
from shared.intelligence_projections.registry import ProviderRegistry

TENANT = "tenant_relationship360"
SUBJECT = "entity-a"
T1 = "2026-03-01T00:00:00+00:00"
T2 = "2026-03-02T00:00:00+00:00"
T3 = "2026-03-03T00:00:00+00:00"


def _event(
    *,
    offset: int,
    kind: str,
    edge_type: Optional[str] = None,
    source: Optional[str] = None,
    target: Optional[str] = None,
    valid_from: Optional[str] = None,
) -> SubjectEvent:
    return SubjectEvent(
        recorded_at={1: T1, 2: T2, 3: T3}[offset],
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
        reason="not rendered",
    )


def _history(
    events: tuple[SubjectEvent, ...] = (),
    *,
    present: bool = True,
    live_edges: tuple[tuple[str, str, str], ...] = (),
    subject_id: str = SUBJECT,
    vertex_kind: str = "entity",
) -> SubjectHistory:
    return SubjectHistory(
        subject_id=subject_id,
        as_of=None,
        present=present,
        vertex={"kind": vertex_kind} if present else None,
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


class _Reader:
    def __init__(self, history: SubjectHistory) -> None:
        self.history = history
        self.calls: list[tuple[str, str, Optional[str]]] = []

    async def subject_history(
        self,
        *,
        tenant_id: str,
        subject_id: str,
        as_of: Optional[str] = None,
    ) -> SubjectHistory:
        self.calls.append((tenant_id, subject_id, as_of))
        if tenant_id != TENANT:
            raise KeyError("tenant is not authorized")
        return self.history


class _PopulationScopeReader:
    def __init__(self, scope: PopulationScopeRead) -> None:
        self.scope = scope
        self.calls: list[tuple[str, str, int]] = []

    async def resolve(self, tenant_id: str, population_id: str, *, limit: int):
        self.calls.append((tenant_id, population_id, limit))
        return self.scope


class _SourceSubjectScopeReader:
    def __init__(self, scope: SourceSubjectScopeRead) -> None:
        self.scope = scope
        self.calls: list[tuple[str, str]] = []

    async def resolve(self, tenant_id: str, source_identity_id: str):
        self.calls.append((tenant_id, source_identity_id))
        return self.scope


class _ProfileIdentityBindingReader:
    def __init__(self, binding: IdentityBindingRead) -> None:
        self.binding = binding
        self.calls: list[tuple[str, str, str]] = []

    async def identity_binding(self, tenant_id: str, subject: ProjectionSubject):
        self.calls.append((tenant_id, subject.kind, subject.id))
        return self.binding


async def _context(request: ProjectionRequest):
    return await ProviderRegistry().build_context("relationship360", request)


def _request(
    *,
    kind: str = "entity",
    subject_id: str = SUBJECT,
    as_of: Optional[str] = None,
    mode: Optional[str] = "window",
    time_range: Optional[TimeRangeFilter] = None,
) -> ProjectionRequest:
    return ProjectionRequest(
        projectionId="relationship360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind=kind, id=subject_id),
        asOf=as_of,
        temporalMode=mode,
        timeRange=time_range,
    )


def _sections(result):
    return {section.id: section for section in result.sections}


@pytest.mark.asyncio
async def test_projects_ledger_edges_with_evidence_and_incomplete_coverage() -> None:
    events = (
        _event(
            offset=1,
            kind="edge_added",
            edge_type="FOLLOWS_SOCIAL",
            source="entity-a",
            target="entity-b",
            valid_from=T1,
        ),
        _event(
            offset=2,
            kind="edge_added",
            edge_type="FOLLOWS_SOCIAL",
            source="entity-a",
            target="entity-c",
            valid_from=T2,
        ),
        _event(
            offset=3,
            kind="edge_revoked",
            edge_type="FOLLOWS_SOCIAL",
            source="entity-a",
            target="entity-c",
            valid_from=T3,
        ),
    )
    reader = _Reader(_history(events, live_edges=(("FOLLOWS_SOCIAL", "entity-a", "entity-b"),)))
    provider = Relationship360Provider(reader=reader)
    request = _request()

    result = await provider.project(request, await _context(request))

    assert [section.id for section in result.sections] == list(OUTPUT_SECTIONS)
    sections = _sections(result)
    assert sections["summary"].state == "degraded"
    assert sections["summary"].content["readAuthority"] == "graph_history_replay"
    assert sections["interactions"].state == "degraded"
    edges = sections["interactions"].content["edges"]
    assert len(edges) == 1
    assert edges[0]["registeredPredicates"] == ["FOLLOWS"]
    assert edges[0]["predicateRegistrationState"] == "registered"
    assert edges[0]["replayedState"] == "present_in_replayed_prefix"
    assert edges[0]["coverage"] == "unknown"
    assert sections["timeline"].state == "degraded"
    assert [event["mutationId"] for event in sections["timeline"].content["events"]] == [
        "mutation-1",
        "mutation-2",
        "mutation-3",
    ]
    assert sections["evidence"].content["count"] == 3
    assert all(claim.evidenceRefs for claim in result.claims)
    assert all(claim.evidenceRefs[0].source == "graph_mutation_ledger" for claim in result.claims)
    assert all(claim.claimState.value == "observed" for claim in result.claims)
    assert all("relationships" in claim.domainSlotIds for claim in result.claims)
    assert "ledger_replay_completeness_is_unknown" in (sections["timeline"].warnings or [])


@pytest.mark.asyncio
async def test_episode_relationship_context_uses_exact_user_binding_and_graph_evidence() -> None:
    profile_id = "profile-episode-1"
    graph_subject_id = f"{TENANT}:user:{profile_id}"
    relation_ref = EvidenceRef(
        id="episode-1",
        type="relationship",
        source="episode_records",
        observedAt=T1,
    )
    binding_reader = _ProfileIdentityBindingReader(
        IdentityBindingRead(
            tenant_id=TENANT,
            resolved_subject=ProjectionSubject(kind="entity", id=profile_id),
            evidence_ref=relation_ref,
            authority="episode_records",
            relationship="episode_user_subject",
            observed_at=T1,
            available=True,
            scope_known=True,
        )
    )
    graph_event = _event(
        offset=1,
        kind="edge_added",
        edge_type="FOLLOWS_SOCIAL",
        source=graph_subject_id,
        target="org-1",
        valid_from=T1,
    )
    history = _history(
        (graph_event,),
        live_edges=(("FOLLOWS_SOCIAL", graph_subject_id, "org-1"),),
        subject_id=graph_subject_id,
        vertex_kind="user",
    )
    reader = _Reader(history)
    provider = Relationship360Provider(
        reader=reader,
        profile_identity_binding_reader=binding_reader,
    )
    request = _request(kind="episode", subject_id="episode-1")

    result = await provider.project(request, await _context(request))

    sections = _sections(result)
    assert binding_reader.calls == [(TENANT, "episode", "episode-1")]
    assert reader.calls == [(TENANT, graph_subject_id, None)]
    assert sections["evidence"].content["subjectIdentityBindingEvidenceRefs"] == [
        relation_ref.model_dump(mode="json", by_alias=True)
    ]
    assert sections["evidence"].content["count"] == 2
    assert sections["evidence"].canonicalAuthorityRefs == [
        "graph",
        "identity",
        "relationship_facts",
    ]
    assert sections["interactions"].canonicalAuthorityRefs == [
        "graph",
        "relationship_facts",
    ]
    assert sections["interactions"].content["edges"][0]["to"] == "org-1"
    assert sections["interactions"].state == "degraded"


@pytest.mark.asyncio
async def test_episode_relationship_join_does_not_use_current_binding_for_bounded_history() -> None:
    binding_reader = _ProfileIdentityBindingReader(
        IdentityBindingRead(
            tenant_id=TENANT,
            resolved_subject=ProjectionSubject(kind="entity", id="profile-episode-1"),
            evidence_ref=EvidenceRef(
                id="episode-1", type="relationship", source="episode_records", observedAt=T1
            ),
            authority="episode_records",
            relationship="episode_user_subject",
            observed_at=T1,
            available=True,
            scope_known=True,
        )
    )
    reader = _Reader(_history())
    provider = Relationship360Provider(
        reader=reader,
        profile_identity_binding_reader=binding_reader,
    )
    request = _request(
        kind="episode",
        subject_id="episode-1",
        time_range=TimeRangeFilter(from_=T1),
    )

    result = await provider.project(request, await _context(request))

    assert binding_reader.calls == []
    assert reader.calls == []
    assert _sections(result)["interactions"].state == "degraded"
    assert "identity_binding_valid_time_unavailable" in result.degradedReasons


@pytest.mark.asyncio
async def test_relationship_subject_and_as_of_use_canonical_pair_and_anchor() -> None:
    events = (
        _event(
            offset=1,
            kind="edge_added",
            edge_type="FOLLOWS_SOCIAL",
            source="entity-a",
            target="entity-b",
            valid_from=T1,
        ),
        _event(
            offset=2,
            kind="edge_added",
            edge_type="FOLLOWS_SOCIAL",
            source="entity-a",
            target="entity-c",
            valid_from=T2,
        ),
    )
    reader = _Reader(
        _history(
            events,
            live_edges=(
                ("FOLLOWS_SOCIAL", "entity-a", "entity-b"),
                ("FOLLOWS_SOCIAL", "entity-a", "entity-c"),
            ),
        )
    )
    provider = Relationship360Provider(reader=reader)
    request = _request(
        kind="relationship",
        subject_id="entity-a::entity-b",
        as_of=T2,
        mode="as_of",
    )

    result = await provider.project(request, await _context(request))

    assert reader.calls == [(TENANT, "entity-a", T2)]
    assert result.asOf == T2
    sections = _sections(result)
    assert sections["interactions"].content["count"] == 1
    assert sections["interactions"].content["edges"][0]["to"] == "entity-b"
    assert sections["timeline"].content["count"] == 1


@pytest.mark.asyncio
async def test_window_filters_by_valid_time_and_excludes_unanchored_events() -> None:
    events = (
        _event(
            offset=1,
            kind="edge_added",
            edge_type="FOLLOWS_SOCIAL",
            source="entity-a",
            target="entity-b",
            valid_from=T1,
        ),
        _event(
            offset=2,
            kind="edge_added",
            edge_type="FOLLOWS_SOCIAL",
            source="entity-a",
            target="entity-c",
            valid_from=None,
        ),
    )
    reader = _Reader(_history(events))
    provider = Relationship360Provider(reader=reader)
    request = _request(
        time_range=TimeRangeFilter(from_=T1, to=T2),
    )

    result = await provider.project(request, await _context(request))

    timeline = _sections(result)["timeline"]
    assert timeline.content["count"] == 1
    assert timeline.content["events"][0]["mutationId"] == "mutation-1"
    assert "events_without_valid_time_excluded_from_window" in (timeline.warnings or [])


@pytest.mark.asyncio
async def test_unknown_subject_does_not_become_definitive_empty_relationship_set() -> None:
    reader = _Reader(_history((), present=False))
    provider = Relationship360Provider(reader=reader)
    request = _request()

    result = await provider.project(request, await _context(request))

    sections = _sections(result)
    assert sections["interactions"].state == "unknown"
    assert sections["evidence"].state == "unknown"
    assert sections["state"].content["dimensions"][2]["state"] == "unknown"
    assert result.claims == []


@pytest.mark.asyncio
async def test_tenant_context_mismatch_prevents_canonical_read() -> None:
    reader = _Reader(_history())
    provider = Relationship360Provider(reader=reader)
    request = _request()
    context = await _context(request)
    context.tenantId = "another-tenant"

    result = await provider.project(request, context)

    assert reader.calls == []
    assert _sections(result)["summary"].state == "degraded"
    assert _sections(result)["findings"].content["findings"][0]["code"] == "tenant_scope_mismatch"


@pytest.mark.asyncio
async def test_agent_subject_reads_graph_history_only_after_canonical_agent_validation() -> None:
    agent_id = "canonical-agent-1"
    event = _event(
        offset=1,
        kind="edge_added",
        edge_type="DELEGATES_TO",
        source=agent_id,
        target="canonical-agent-2",
        valid_from=T1,
    )
    reader = _Reader(
        _history(
            (event,),
            live_edges=(("DELEGATES_TO", agent_id, "canonical-agent-2"),),
            subject_id=agent_id,
            vertex_kind="agent",
        )
    )

    class CanonicalAgentReader:
        async def is_canonical_agent(self, tenant_id: str, subject_id: str) -> bool:
            assert (tenant_id, subject_id) == (TENANT, agent_id)
            return True

    provider = Relationship360Provider(
        reader=reader,
        agent_identity_reader=CanonicalAgentReader(),
    )
    request = _request(kind="agent", subject_id=agent_id)
    result = await provider.project(request, await _context(request))

    assert reader.calls == [(TENANT, agent_id, None)]
    assert _sections(result)["summary"].content["subject"] == {
        "kind": "agent",
        "id": agent_id,
    }
    assert _sections(result)["interactions"].content["edges"][0]["to"] == "canonical-agent-2"
    assert result.claims[0].subject == request.subject


@pytest.mark.asyncio
async def test_agent_spawned_agents_only_exposes_outgoing_spawn_edges_with_exact_claim_mapping() -> None:
    agent_id = "canonical-agent-parent"
    spawned = _event(
        offset=1,
        kind="edge_added",
        edge_type="SPAWNED_SUBAGENT",
        source=agent_id,
        target="canonical-agent-child",
        valid_from=T1,
    )
    delegated = _event(
        offset=2,
        kind="edge_added",
        edge_type="DELEGATES_TO",
        source=agent_id,
        target="canonical-agent-delegate",
        valid_from=T2,
    )
    incoming_spawn = _event(
        offset=3,
        kind="edge_added",
        edge_type="SPAWNED_SUBAGENT",
        source="canonical-agent-other-parent",
        target=agent_id,
        valid_from=T3,
    )
    history = _history(
        (spawned, delegated, incoming_spawn),
        live_edges=(
            ("SPAWNED_SUBAGENT", agent_id, "canonical-agent-child"),
            ("DELEGATES_TO", agent_id, "canonical-agent-delegate"),
            ("SPAWNED_SUBAGENT", "canonical-agent-other-parent", agent_id),
        ),
        subject_id=agent_id,
        vertex_kind="agent",
    )
    reader = _Reader(history)

    class CanonicalAgentReader:
        async def is_canonical_agent(self, tenant_id: str, subject_id: str) -> bool:
            assert (tenant_id, subject_id) == (TENANT, agent_id)
            return True

    provider = Relationship360Provider(
        reader=reader,
        agent_identity_reader=CanonicalAgentReader(),
    )
    request = _request(kind="agent", subject_id=agent_id)
    result = await provider.project(request, await _context(request))

    section = _sections(result)["agent_spawned_agents"]
    assert section.state == "degraded"
    assert section.content["coverage"] == "unknown"
    assert section.content["stateBasis"] == "tenant_graph_mutation_ledger_replay"
    assert "no completeness watermark" in section.content["coverageReason"]
    assert section.warnings == ["spawned_agent_ledger_prefix_incomplete"]
    assert section.canonicalAuthorityRefs == ["graph", "relationship_facts", "temporal"]
    assert [
        (
            entry["parentGraphAgentReference"],
            entry["spawnedGraphAgentReference"],
        )
        for entry in section.content["spawnedAgents"]
    ] == [(agent_id, "canonical-agent-child")]
    evidence = section.content["spawnedAgents"][0]["evidenceRef"]
    assert evidence["id"] == "mutation-1"
    assert evidence["source"] == "graph_mutation_ledger"

    claims_by_mutation = {
        evidence_ref.id: claim
        for claim in result.claims
        for evidence_ref in claim.evidenceRefs
    }
    assert "spawned_agents" in claims_by_mutation["mutation-1"].domainSlotIds
    assert "spawned_agents" not in claims_by_mutation["mutation-2"].domainSlotIds
    assert "spawned_agents" not in claims_by_mutation["mutation-3"].domainSlotIds


@pytest.mark.asyncio
async def test_agent_spawned_agents_stays_unknown_when_only_generic_delegation_is_observed() -> None:
    agent_id = "canonical-agent-parent"
    delegated = _event(
        offset=1,
        kind="edge_added",
        edge_type="DELEGATES_TO",
        source=agent_id,
        target="canonical-agent-delegate",
        valid_from=T1,
    )
    reader = _Reader(
        _history(
            (delegated,),
            live_edges=(("DELEGATES_TO", agent_id, "canonical-agent-delegate"),),
            subject_id=agent_id,
            vertex_kind="agent",
        )
    )

    class CanonicalAgentReader:
        async def is_canonical_agent(self, tenant_id: str, subject_id: str) -> bool:
            return True

    provider = Relationship360Provider(
        reader=reader,
        agent_identity_reader=CanonicalAgentReader(),
    )
    request = _request(kind="agent", subject_id=agent_id)
    result = await provider.project(request, await _context(request))

    section = _sections(result)["agent_spawned_agents"]
    assert section.state == "unknown"
    assert section.content is None
    assert section.warnings == [
        "no_spawned_agent_edge_observed_in_incomplete_ledger_prefix"
    ]
    assert all("spawned_agents" not in claim.domainSlotIds for claim in result.claims)


@pytest.mark.asyncio
async def test_agent_spawned_agents_reports_degraded_when_graph_history_is_unavailable() -> None:
    agent_id = "canonical-agent-parent"

    class FailingReader:
        async def subject_history(
            self,
            *,
            tenant_id: str,
            subject_id: str,
            as_of: Optional[str] = None,
        ) -> SubjectHistory:
            raise RuntimeError("underlying read details are not projected")

    class CanonicalAgentReader:
        async def is_canonical_agent(self, tenant_id: str, subject_id: str) -> bool:
            return True

    provider = Relationship360Provider(
        reader=FailingReader(),
        agent_identity_reader=CanonicalAgentReader(),
    )
    request = _request(kind="agent", subject_id=agent_id)
    result = await provider.project(request, await _context(request))

    section = _sections(result)["agent_spawned_agents"]
    assert section.state == "degraded"
    assert section.content is None
    assert section.warnings == ["spawned_agent_graph_read_unavailable"]
    assert result.degradedReasons == ["graph_history_replay_unavailable"]


@pytest.mark.asyncio
async def test_unresolved_agent_subject_never_reads_graph_history() -> None:
    reader = _Reader(_history())

    class UnresolvedAgentReader:
        async def is_canonical_agent(self, tenant_id: str, subject_id: str) -> bool:
            return False

    provider = Relationship360Provider(
        reader=reader,
        agent_identity_reader=UnresolvedAgentReader(),
    )
    request = _request(kind="agent", subject_id="not-a-canonical-agent")
    result = await provider.project(request, await _context(request))

    assert reader.calls == []
    assert result.degradedReasons == ["agent_canonical_identity_unresolved"]
    assert _sections(result)["summary"].state == "degraded"
    assert result.claims == []


@pytest.mark.asyncio
async def test_population_subject_projects_only_verified_induced_graph_with_membership_evidence():
    internal = _event(
        offset=1,
        kind="edge_added",
        edge_type="FOLLOWS_SOCIAL",
        source="entity-a",
        target="entity-b",
        valid_from=T1,
    )
    external = _event(
        offset=2,
        kind="edge_added",
        edge_type="FOLLOWS_SOCIAL",
        source="entity-a",
        target="entity-outside",
        valid_from=T2,
    )
    history = _history(
        (internal, external),
        live_edges=(
            ("FOLLOWS_SOCIAL", "entity-a", "entity-b"),
            ("FOLLOWS_SOCIAL", "entity-a", "entity-outside"),
        ),
    )
    reader = _Reader(history)
    scope_reader = _PopulationScopeReader(
        PopulationScopeRead(
            TENANT,
            "population-a",
            "available",
            entity_ids=("entity-a", "entity-b"),
            evidence_refs=(
                EvidenceRef(
                    id="population-a",
                    type="entity",
                    source="identity_populations",
                    uri="store://populations/population-a",
                ),
                EvidenceRef(
                    id="membership-a",
                    type="entity",
                    source="identity_population_memberships",
                    uri="store://population_memberships/membership-a",
                ),
            ),
        )
    )
    checked_consent: list[str] = []

    async def consent(tenant_id, subject_id, anonymous_id, purpose):
        assert tenant_id == TENANT
        assert anonymous_id is None
        assert purpose == "analytics"
        checked_consent.append(subject_id)
        return True, None

    provider = Relationship360Provider(
        reader=reader,
        population_scope_reader=scope_reader,
        consent_reader=consent,
    )
    request = _request(kind="population", subject_id="population-a")

    result = await provider.project(request, await _context(request))

    sections = _sections(result)
    assert checked_consent == ["entity-a", "entity-b"]
    assert scope_reader.calls == [(TENANT, "population-a", 200)]
    assert reader.calls == [(TENANT, "entity-a", None), (TENANT, "entity-b", None)]
    assert sections["interactions"].content["count"] == 1
    assert sections["interactions"].content["edges"][0]["to"] == "entity-b"
    assert sections["timeline"].content["count"] == 1
    assert sections["evidence"].content["count"] == 3
    assert sections["evidence"].content["populationMembershipEvidenceRefs"][0]["id"] == (
        "population-a"
    )
    assert sections["summary"].content["populationScope"]["memberCount"] == 2
    assert sections["summary"].content["populationScope"]["relationshipScope"] == (
        "induced_subgraph_within_verified_members"
    )
    assert all("relationship_graph" in claim.domainSlotIds for claim in result.claims)


@pytest.mark.asyncio
async def test_population_relationship_read_fails_closed_on_truncation_or_historical_scope():
    async def allow_consent(*_args):
        return True, None

    truncated_reader = _Reader(_history())
    truncated_scope = _PopulationScopeReader(
        PopulationScopeRead(
            TENANT,
            "population-a",
            "truncated",
            reason="population_membership_read_capped",
        )
    )
    truncated = await Relationship360Provider(
        reader=truncated_reader,
        population_scope_reader=truncated_scope,
        consent_reader=allow_consent,
    ).project(
        _request(kind="population", subject_id="population-a"),
        await _context(_request(kind="population", subject_id="population-a")),
    )
    assert truncated_reader.calls == []
    assert truncated.degradedReasons == ["population_membership_read_capped"]

    historical_reader = _Reader(_history())
    historical_scope = _PopulationScopeReader(
        PopulationScopeRead(TENANT, "population-a", "available", entity_ids=("entity-a",))
    )
    historical_request = _request(
        kind="population", subject_id="population-a", as_of=T2, mode="as_of"
    )
    historical = await Relationship360Provider(
        reader=historical_reader,
        population_scope_reader=historical_scope,
        consent_reader=allow_consent,
    ).project(historical_request, await _context(historical_request))
    assert historical_scope.calls == []
    assert historical_reader.calls == []
    assert historical.degradedReasons == ["population_membership_temporal_scope_unknown"]


@pytest.mark.asyncio
async def test_source_subject_resolves_canonical_entity_checks_consent_and_preserves_binding_evidence():
    canonical_id = "canonical-entity-1"
    event = _event(
        offset=1,
        kind="edge_added",
        edge_type="FOLLOWS_SOCIAL",
        source=canonical_id,
        target="entity-b",
        valid_from=T1,
    )
    reader = _Reader(
        _history(
            (event,),
            live_edges=(("FOLLOWS_SOCIAL", canonical_id, "entity-b"),),
            subject_id=canonical_id,
        )
    )
    binding_ref = EvidenceRef(
        id="source-row-1",
        type="entity",
        source="identity_source_identities",
        uri="store://source-identities/source-row-1",
    )
    scope_reader = _SourceSubjectScopeReader(
        SourceSubjectScopeRead(
            TENANT,
            "source-1",
            "available",
            canonical_entity_id=canonical_id,
            evidence_refs=(binding_ref,),
        )
    )
    consent_calls: list[str] = []

    async def consent(tenant_id, subject_id, anonymous_id, purpose):
        assert tenant_id == TENANT
        assert anonymous_id is None
        assert purpose == "analytics"
        consent_calls.append(subject_id)
        return True, None

    provider = Relationship360Provider(
        reader=reader,
        source_subject_scope_reader=scope_reader,
        consent_reader=consent,
    )
    request = _request(kind="source", subject_id="source-1")

    result = await provider.project(request, await _context(request))

    sections = _sections(result)
    assert scope_reader.calls == [(TENANT, "source-1")]
    assert consent_calls == [canonical_id]
    assert reader.calls == [(TENANT, canonical_id, None)]
    assert sections["summary"].content["subject"] == {"kind": "source", "id": "source-1"}
    assert sections["summary"].content["readAuthority"] == "identity360+graph_history_replay"
    assert sections["summary"].content["sourceIdentityScope"]["canonicalEntityId"] == canonical_id
    assert sections["evidence"].content["sourceIdentityEvidenceRefs"][0]["id"] == "source-row-1"
    assert sections["evidence"].content["count"] == 2
    assert result.claims[0].subject == request.subject


@pytest.mark.asyncio
async def test_unresolved_or_denied_source_subject_never_reads_graph_history():
    async def allow_consent(*_args):
        return True, None

    unresolved_reader = _Reader(_history())
    unresolved_scope = _SourceSubjectScopeReader(
        SourceSubjectScopeRead(
            TENANT, "source-1", "unknown", reason="source_identity_binding_unresolved"
        )
    )
    unresolved_request = _request(kind="source", subject_id="source-1")
    unresolved = await Relationship360Provider(
        reader=unresolved_reader,
        source_subject_scope_reader=unresolved_scope,
        consent_reader=allow_consent,
    ).project(unresolved_request, await _context(unresolved_request))
    assert unresolved_reader.calls == []
    assert unresolved.degradedReasons == ["source_identity_binding_unresolved"]

    denied_reader = _Reader(_history())
    denied_scope = _SourceSubjectScopeReader(
        SourceSubjectScopeRead(
            TENANT, "source-1", "available", canonical_entity_id="canonical-entity-1"
        )
    )

    async def deny_consent(*_args):
        return False, "consent_receipt_missing"

    denied_request = _request(kind="source", subject_id="source-1")
    denied = await Relationship360Provider(
        reader=denied_reader,
        source_subject_scope_reader=denied_scope,
        consent_reader=deny_consent,
    ).project(denied_request, await _context(denied_request))
    assert denied_reader.calls == []
    assert denied.degradedReasons == ["source_subject_consent_not_established"]


@pytest.mark.asyncio
async def test_source_subject_rejects_temporal_scope_before_identity_or_graph_read():
    reader = _Reader(_history())
    scope_reader = _SourceSubjectScopeReader(
        SourceSubjectScopeRead(
            TENANT, "source-1", "available", canonical_entity_id="canonical-entity-1"
        )
    )
    request = _request(
        kind="source",
        subject_id="source-1",
        time_range=TimeRangeFilter(from_=T1, to=T2),
    )

    result = await Relationship360Provider(
        reader=reader,
        source_subject_scope_reader=scope_reader,
    ).project(request, await _context(request))

    assert scope_reader.calls == []
    assert reader.calls == []
    assert result.degradedReasons == ["source_identity_temporal_scope_unknown"]
