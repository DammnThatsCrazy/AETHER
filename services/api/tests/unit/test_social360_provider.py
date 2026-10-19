from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from shared.intelligence_projections.contracts import (  # noqa: E402
    ProjectionContext,
    ProjectionRequest,
    ProjectionSubject,
)
from graph.operational_intelligence.models import EvidenceRef, TimeRangeFilter  # noqa: E402
from identity.population360.scope import PopulationScopeRead  # noqa: E402
from identity.identity.source_subject_scope import SourceSubjectScopeRead  # noqa: E402
from services.social360.provider import (  # noqa: E402
    AgentSubjectScopeRead,
    OUTPUT_SECTIONS,
    Social360FactRead,
    Social360Provider,
)


TENANT = "tenant-social-360"


class FakeSocialSource:
    def __init__(self, rows: dict[str, list[dict]] | None = None) -> None:
        self.rows = rows or {}
        self.calls: list[tuple[str, str, int]] = []

    async def read(self, fact_family: str, tenant_id: str, *, limit: int):
        self.calls.append((fact_family, tenant_id, limit))
        rows = self.rows.get(fact_family, [])
        return Social360FactRead(rows=list(rows), truncated=len(rows) >= 500)


class FakePopulationScopeReader:
    def __init__(self, result: PopulationScopeRead) -> None:
        self.result = result
        self.calls: list[tuple[str, str, int]] = []

    async def resolve(self, tenant_id: str, population_id: str, *, limit: int):
        self.calls.append((tenant_id, population_id, limit))
        return self.result


class FakeSourceSubjectScopeReader:
    def __init__(self, result: SourceSubjectScopeRead) -> None:
        self.result = result
        self.calls: list[tuple[str, str]] = []

    async def resolve(self, tenant_id: str, source_identity_id: str):
        self.calls.append((tenant_id, source_identity_id))
        return self.result


class FakeAgentSubjectScopeReader:
    def __init__(self, result: AgentSubjectScopeRead) -> None:
        self.result = result
        self.calls: list[tuple[str, str]] = []

    async def resolve(self, tenant_id: str, agent_id: str):
        self.calls.append((tenant_id, agent_id))
        return self.result


def _population_scope(
    state: str = "available", entity_ids: tuple[str, ...] = ("entity-a", "entity-b")
) -> PopulationScopeRead:
    return PopulationScopeRead(
        TENANT,
        "population-a",
        state,  # type: ignore[arg-type]
        entity_ids=entity_ids,
        evidence_refs=(
            EvidenceRef(
                id="population-a",
                type="entity",
                source="identity_populations",
                uri="store://populations/population-a",
            ),
        ),
        reason="population_membership_read_capped" if state == "truncated" else None,
    )


async def _allow_consent(tenant_id: str, subject_id: str, anonymous_id, purpose: str):
    assert tenant_id == TENANT
    assert anonymous_id is None
    assert purpose == "analytics"
    return True, None


def _context(tenant_id: str = TENANT, *, as_of: str | None = None):
    return ProjectionContext(
        projectionId="social360",
        tenantId=tenant_id,
        registryState="in_flight",
        dependencyState=[],
        warnings=[],
        asOf=as_of,
    )


def _request(
    subject_kind: str = "entity",
    subject_id: str = "entity-a",
    *,
    include_sections: list[str] | None = None,
    temporal_mode: str | None = None,
    as_of: str | None = None,
    time_range: TimeRangeFilter | None = None,
):
    return ProjectionRequest(
        projectionId="social360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind=subject_kind, id=subject_id),
        includeSections=include_sections,
        temporalMode=temporal_mode,
        asOf=as_of,
        timeRange=time_range,
    )


def _identity(
    fact_id: str,
    entity_id: str,
    social_identity_id: str,
    *,
    tenant_id: str = TENANT,
    received_at: str = "2026-10-18T10:00:00Z",
):
    return {
        "fact_id": fact_id,
        "tenant_id": tenant_id,
        "canonical_entity_ref": entity_id,
        "social_identity_id": social_identity_id,
        "provider_identity": "provider-x",
        "resolution_state": "resolved",
        "identity_evidence_refs": ["untyped-source-evidence-1"],
        "received_at": received_at,
    }


@pytest.mark.asyncio
async def test_entity_projection_is_tenant_scoped_and_emits_typed_fact_evidence():
    source = FakeSocialSource(
        {
            "identity": [
                _identity("identity-fact-a", "entity-a", "social-a"),
                _identity("foreign-fact", "entity-a", "social-foreign", tenant_id="tenant-other"),
                _identity("other-entity-fact", "entity-b", "social-b"),
            ],
            "metric": [
                {
                    "fact_id": "metric-fact-a",
                    "tenant_id": TENANT,
                    "metric_observation_id": "metric-a",
                    "social_identity_ref": "social-a",
                    "metric_name": "followers",
                    "value": None,
                    "status": "unavailable",
                    "observed_at": "2026-10-18T09:00:00Z",
                    "evidence_refs": ["external-ref-1"],
                },
                {
                    "fact_id": "metric-fact-b",
                    "tenant_id": TENANT,
                    "metric_observation_id": "metric-b",
                    "social_identity_ref": "social-b",
                    "metric_name": "followers",
                    "value": 500,
                },
            ],
        }
    )
    provider = Social360Provider(source=source, consent_reader=_allow_consent)

    result = await provider.project(
        _request(include_sections=["evidence", "state", "summary"]), _context()
    )

    state = next(section for section in result.sections if section.id == "state")
    assert state.state == "degraded"  # the cross-tenant row was rejected
    assert [row["metric_observation_id"] for row in state.content["metrics"]] == ["metric-a"]
    assert state.content["identities"][0]["social_identity_id"] == "social-a"
    assert state.content["metrics"][0]["value"] is None
    assert state.content["metrics"][0]["status"] == "unavailable"
    evidence = next(section for section in result.sections if section.id == "evidence")
    assert {ref.id for ref in evidence.content["evidenceRefs"]} == {
        "identity-fact-a",
        "metric-fact-a",
    }
    assert evidence.content["evidenceRefs"][0].source.endswith("silver_social_identity_facts")
    identity_claim = next(
        claim for claim in result.claims if claim.id == "social360.identity.identity-fact-a"
    )
    assert identity_claim.evidenceRefs[0].id == "identity-fact-a"
    assert identity_claim.domainSlotIds == [
        "evidence_and_coverage",
        "social_observations_and_sources",
    ]
    assert source.calls[0] == ("identity", TENANT, 500)


@pytest.mark.asyncio
async def test_agent_subject_uses_canonical_agent_identity_and_consent_scope():
    source = FakeSocialSource(
        {"identity": [_identity("social-identity-agent", "canonical-agent-1", "social-agent")]}
    )
    agent_identity_evidence = EvidenceRef(
        id="agent-binding-1",
        type="entity",
        source="agent_deployment_identity_bindings",
    )
    scope_reader = FakeAgentSubjectScopeReader(
        AgentSubjectScopeRead(
            TENANT,
            "deployment-agent-1",
            "available",
            canonical_agent_entity_id="canonical-agent-1",
            evidence_refs=(agent_identity_evidence,),
        )
    )
    consented_subjects: list[str] = []

    async def consent_reader(tenant_id: str, subject_id: str, anonymous_id, purpose: str):
        assert tenant_id == TENANT
        assert anonymous_id is None
        assert purpose == "analytics"
        consented_subjects.append(subject_id)
        return True, None

    provider = Social360Provider(
        source=source,
        consent_reader=consent_reader,
        agent_subject_scope_reader=scope_reader,
    )
    result = await provider.project(_request("agent", "deployment-agent-1"), _context())

    assert scope_reader.calls == [(TENANT, "deployment-agent-1")]
    assert consented_subjects == ["canonical-agent-1"]
    identity_read = next(call for call in source.calls if call[0] == "identity")
    assert identity_read == ("identity", TENANT, 500)
    assert next(section for section in result.sections if section.id == "summary").content[
        "agentIdentityScope"
    ] == {"state": "available", "canonicalAgentEntityId": "canonical-agent-1"}
    evidence = next(section for section in result.sections if section.id == "evidence")
    evidence_ids = {ref.id for ref in evidence.content["evidenceRefs"]}
    assert evidence_ids == {"agent-binding-1", "social-identity-agent"}
    assert result.claims == []


@pytest.mark.asyncio
async def test_agent_social_read_fails_closed_without_canonical_identity():
    source = FakeSocialSource({"identity": [_identity("social-identity-agent", "agent-1", "s1")]})
    scope_reader = FakeAgentSubjectScopeReader(
        AgentSubjectScopeRead(
            TENANT,
            "deployment-agent-1",
            "unknown",
            reason="agent_canonical_identity_unresolved",
        )
    )
    consent_calls: list[str] = []

    async def consent_reader(tenant_id: str, subject_id: str, anonymous_id, purpose: str):
        consent_calls.append(subject_id)
        return True, None

    result = await Social360Provider(
        source=source,
        consent_reader=consent_reader,
        agent_subject_scope_reader=scope_reader,
    ).project(_request("agent", "deployment-agent-1"), _context())

    assert source.calls == []
    assert consent_calls == []
    assert result.claims == []
    assert all(section.state == "unknown" for section in result.sections)
    assert "agent_canonical_identity_unresolved" in result.degradedReasons


@pytest.mark.asyncio
async def test_relationship_subject_uses_exact_canonical_endpoint_pair():
    source = FakeSocialSource(
        {
            "identity": [
                _identity("identity-a", "entity-a", "social-a"),
                _identity("identity-b", "entity-b", "social-b"),
                _identity("identity-c", "entity-c", "social-c"),
            ],
            "connection": [
                {
                    "fact_id": "connection-a-b",
                    "tenant_id": TENANT,
                    "source_social_identity_ref": "social-a",
                    "target_social_identity_ref": "social-b",
                    "connection_type": "follows",
                    "evidence_refs": ["ref-ab"],
                },
                {
                    "fact_id": "connection-a-c",
                    "tenant_id": TENANT,
                    "source_social_identity_ref": "social-a",
                    "target_social_identity_ref": "social-c",
                    "connection_type": "follows",
                },
            ],
            "interaction": [
                {
                    "fact_id": "interaction-b-a",
                    "tenant_id": TENANT,
                    "actor_social_identity_ref": "social-b",
                    "target_social_identity_ref": "social-a",
                    "interaction_type": "reply",
                    "observed_at": "2026-10-18T10:00:00Z",
                },
                {
                    "fact_id": "interaction-a-c",
                    "tenant_id": TENANT,
                    "actor_social_identity_ref": "social-a",
                    "target_social_identity_ref": "social-c",
                    "interaction_type": "reply",
                },
            ],
        }
    )
    provider = Social360Provider(source=source, consent_reader=_allow_consent)

    result = await provider.project(
        _request(
            "relationship", "entity-a::entity-b", include_sections=["findings", "interactions"]
        ),
        _context(),
    )

    findings = next(section for section in result.sections if section.id == "findings")
    interactions = next(section for section in result.sections if section.id == "interactions")
    assert [row["connection_type"] for row in findings.content["relationships"]] == ["follows"]
    assert [row["interaction_type"] for row in interactions.content["interactions"]] == ["reply"]
    assert "connection-a-c" not in {ref.id for claim in result.claims for ref in claim.evidenceRefs}
    assert len([call for call in source.calls if call[0] == "identity"]) == 1


@pytest.mark.asyncio
async def test_denied_consent_suppresses_without_reading_social_facts():
    source = FakeSocialSource()

    async def deny(*args):
        return False, "consent_receipt_missing"

    result = await Social360Provider(source=source, consent_reader=deny).project(
        _request(), _context()
    )

    assert source.calls == []
    assert result.claims == []
    assert result.degradedReasons == ["consent_required"]
    assert {section.state for section in result.sections} == {"suppressed"}
    assert {section.id for section in result.sections} == set(OUTPUT_SECTIONS)


@pytest.mark.asyncio
async def test_relationship_requires_consent_for_both_entities():
    source = FakeSocialSource()
    checked: list[str] = []

    async def deny_second(tenant_id: str, subject_id: str, anonymous_id, purpose: str):
        checked.append(subject_id)
        return subject_id == "entity-a", "consent_receipt_missing"

    result = await Social360Provider(source=source, consent_reader=deny_second).project(
        _request("relationship", "entity-a::entity-b"), _context()
    )

    assert checked == ["entity-a", "entity-b"]
    assert source.calls == []
    assert {section.state for section in result.sections} == {"suppressed"}


@pytest.mark.asyncio
async def test_unresolved_relationship_or_non_entity_subject_does_not_read_facts():
    source = FakeSocialSource()
    provider = Social360Provider(source=source, consent_reader=_allow_consent)

    result = await provider.project(_request("relationship", "entity-a-only"), _context())

    assert source.calls == []
    assert result.degradedReasons == ["social_subject_binding_unsupported"]
    assert {section.state for section in result.sections} == {"unknown"}


@pytest.mark.asyncio
async def test_as_of_uses_received_time_and_omits_unanchored_facts():
    source = FakeSocialSource(
        {
            "identity": [
                _identity(
                    "identity-before", "entity-a", "social-a", received_at="2026-10-16T10:00:00Z"
                ),
                _identity(
                    "identity-after", "entity-a", "social-b", received_at="2026-10-18T10:00:00Z"
                ),
                {**_identity("identity-unanchored", "entity-a", "social-c"), "received_at": None},
            ]
        }
    )
    provider = Social360Provider(source=source, consent_reader=_allow_consent)

    result = await provider.project(
        _request(
            include_sections=["state"],
            temporal_mode="as_of",
            as_of="2026-10-17T10:00:00Z",
        ),
        _context(),
    )

    state = result.sections[0]
    assert state.state == "degraded"
    assert [row["social_identity_id"] for row in state.content["identities"]] == ["social-a"]
    assert "temporal_fact_coverage_incomplete" in result.degradedReasons


@pytest.mark.asyncio
async def test_population_projection_uses_verified_members_and_internal_social_edges():
    source = FakeSocialSource(
        {
            "identity": [
                _identity("identity-a", "entity-a", "social-a"),
                _identity("identity-b", "entity-b", "social-b"),
                _identity("identity-outside", "entity-c", "social-c"),
            ],
            "connection": [
                {
                    "fact_id": "connection-internal",
                    "tenant_id": TENANT,
                    "source_social_identity_ref": "social-a",
                    "target_social_identity_ref": "social-b",
                    "connection_type": "follows",
                },
                {
                    "fact_id": "connection-outside",
                    "tenant_id": TENANT,
                    "source_social_identity_ref": "social-a",
                    "target_social_identity_ref": "social-c",
                    "connection_type": "follows",
                },
            ],
            "interaction": [
                {
                    "fact_id": "interaction-internal",
                    "tenant_id": TENANT,
                    "actor_social_identity_ref": "social-b",
                    "target_social_identity_ref": "social-a",
                    "interaction_type": "reply",
                },
                {
                    "fact_id": "interaction-outside",
                    "tenant_id": TENANT,
                    "actor_social_identity_ref": "social-a",
                    "target_social_identity_ref": "social-c",
                    "interaction_type": "reply",
                },
            ],
        }
    )
    scope_reader = FakePopulationScopeReader(_population_scope())
    checked_consent: list[str] = []

    async def consent(tenant_id: str, subject_id: str, anonymous_id, purpose: str):
        assert tenant_id == TENANT
        assert anonymous_id is None
        assert purpose == "analytics"
        checked_consent.append(subject_id)
        return True, None

    result = await Social360Provider(
        source=source,
        consent_reader=consent,
        population_scope_reader=scope_reader,
    ).project(
        _request(
            "population",
            "population-a",
            include_sections=["evidence", "findings", "interactions", "summary"],
        ),
        _context(),
    )

    assert checked_consent == ["entity-a", "entity-b"]
    assert scope_reader.calls == [(TENANT, "population-a", 500)]
    findings = next(section for section in result.sections if section.id == "findings")
    interactions = next(section for section in result.sections if section.id == "interactions")
    evidence = next(section for section in result.sections if section.id == "evidence")
    summary = next(section for section in result.sections if section.id == "summary")
    assert [row["evidenceRefs"][0].id for row in findings.content["relationships"]] == [
        "connection-internal"
    ]
    assert [row["evidenceRefs"][0].id for row in interactions.content["interactions"]] == [
        "interaction-internal"
    ]
    assert {ref.id for ref in evidence.content["evidenceRefs"]} >= {
        "population-a",
        "identity-a",
        "identity-b",
        "connection-internal",
        "interaction-internal",
    }
    assert summary.content["populationScope"] == {
        "state": "available",
        "memberCount": 2,
        "relationshipScope": "internal_to_verified_population_members",
    }
    assert all("social_observations_and_sources" in claim.domainSlotIds for claim in result.claims)


@pytest.mark.asyncio
async def test_population_consent_denial_suppresses_before_social_fact_reads():
    source = FakeSocialSource()
    checked: list[str] = []

    async def deny_second(tenant_id: str, subject_id: str, anonymous_id, purpose: str):
        checked.append(subject_id)
        return subject_id == "entity-a", "consent_receipt_missing"

    result = await Social360Provider(
        source=source,
        consent_reader=deny_second,
        population_scope_reader=FakePopulationScopeReader(_population_scope()),
    ).project(_request("population", "population-a"), _context())

    assert checked == ["entity-a", "entity-b"]
    assert source.calls == []
    assert {section.state for section in result.sections} == {"suppressed"}


@pytest.mark.asyncio
async def test_population_truncation_empty_membership_and_historical_scope_are_explicit():
    truncated_source = FakeSocialSource()
    truncated_scope = FakePopulationScopeReader(_population_scope("truncated", ()))
    truncated = await Social360Provider(
        source=truncated_source,
        consent_reader=_allow_consent,
        population_scope_reader=truncated_scope,
    ).project(_request("population", "population-a"), _context())
    assert truncated_source.calls == []
    assert truncated.degradedReasons == ["population_membership_read_capped"]
    assert {section.state for section in truncated.sections} == {"unknown"}

    empty_source = FakeSocialSource()
    empty = await Social360Provider(
        source=empty_source,
        consent_reader=_allow_consent,
        population_scope_reader=FakePopulationScopeReader(_population_scope("empty", ())),
    ).project(_request("population", "population-a"), _context())
    assert empty_source.calls == []
    assert {section.state for section in empty.sections} == {"empty"}

    temporal_source = FakeSocialSource()
    temporal_scope = FakePopulationScopeReader(_population_scope())
    temporal = await Social360Provider(
        source=temporal_source,
        consent_reader=_allow_consent,
        population_scope_reader=temporal_scope,
    ).project(
        _request("population", "population-a", temporal_mode="as_of", as_of="2026-10-18T10:00:00Z"),
        _context(),
    )
    assert temporal_scope.calls == []
    assert temporal_source.calls == []
    assert temporal.degradedReasons == ["population_membership_temporal_scope_unknown"]


@pytest.mark.asyncio
async def test_source_subject_uses_identity360_binding_and_limits_social_facts_to_entity():
    source = FakeSocialSource(
        {
            "identity": [
                _identity("identity-canonical", "canonical-entity-1", "social-canonical"),
                _identity("identity-other", "entity-other", "social-other"),
            ],
            "metric": [
                {
                    "fact_id": "metric-canonical",
                    "tenant_id": TENANT,
                    "metric_observation_id": "metric-canonical-observation",
                    "social_identity_ref": "social-canonical",
                    "metric_name": "followers",
                    "value": 12,
                },
                {
                    "fact_id": "metric-other",
                    "tenant_id": TENANT,
                    "metric_observation_id": "metric-other-observation",
                    "social_identity_ref": "social-other",
                    "metric_name": "followers",
                    "value": 999,
                },
            ],
        }
    )
    source_ref = EvidenceRef(
        id="source-row-1",
        type="entity",
        source="identity_source_identities",
        uri="store://source-identities/source-row-1",
    )
    scope_reader = FakeSourceSubjectScopeReader(
        SourceSubjectScopeRead(
            TENANT,
            "source-1",
            "available",
            canonical_entity_id="canonical-entity-1",
            evidence_refs=(source_ref,),
        )
    )
    consented: list[str] = []

    async def consent(tenant_id: str, subject_id: str, anonymous_id, purpose: str):
        assert tenant_id == TENANT
        assert anonymous_id is None
        assert purpose == "analytics"
        consented.append(subject_id)
        return True, None

    result = await Social360Provider(
        source=source,
        consent_reader=consent,
        source_subject_scope_reader=scope_reader,
    ).project(
        _request("source", "source-1", include_sections=["evidence", "state", "summary"]),
        _context(),
    )

    sections = {section.id: section for section in result.sections}
    assert scope_reader.calls == [(TENANT, "source-1")]
    assert consented == ["canonical-entity-1"]
    assert source.calls[0] == ("identity", TENANT, 500)
    assert [row["social_identity_id"] for row in sections["state"].content["identities"]] == [
        "social-canonical"
    ]
    assert [
        (row["metric_observation_id"], row["value"]) for row in sections["state"].content["metrics"]
    ] == [("metric-canonical-observation", 12)]
    evidence_ids = {ref.id for ref in sections["evidence"].content["evidenceRefs"]}
    assert {"source-row-1", "identity-canonical", "metric-canonical"}.issubset(evidence_ids)
    assert "metric-other" not in evidence_ids
    assert sections["summary"].content["sourceIdentityScope"] == {
        "state": "available",
        "canonicalEntityId": "canonical-entity-1",
    }
    assert all("social_observations_and_sources" in claim.domainSlotIds for claim in result.claims)


@pytest.mark.asyncio
async def test_unresolved_source_subject_does_not_read_social_facts():
    source = FakeSocialSource()
    scope_reader = FakeSourceSubjectScopeReader(
        SourceSubjectScopeRead(
            TENANT, "source-1", "unknown", reason="source_identity_binding_unresolved"
        )
    )

    result = await Social360Provider(
        source=source,
        consent_reader=_allow_consent,
        source_subject_scope_reader=scope_reader,
    ).project(_request("source", "source-1"), _context())

    assert scope_reader.calls == [(TENANT, "source-1")]
    assert source.calls == []
    assert result.degradedReasons == ["source_identity_binding_unresolved"]
    assert {section.state for section in result.sections} == {"unknown"}


@pytest.mark.asyncio
async def test_source_subject_rejects_temporal_scope_before_identity_or_social_reads():
    source = FakeSocialSource()
    scope_reader = FakeSourceSubjectScopeReader(
        SourceSubjectScopeRead(
            TENANT, "source-1", "available", canonical_entity_id="canonical-entity-1"
        )
    )
    result = await Social360Provider(
        source=source,
        consent_reader=_allow_consent,
        source_subject_scope_reader=scope_reader,
    ).project(
        _request(
            "source",
            "source-1",
            time_range=TimeRangeFilter(from_="2026-10-01T00:00:00Z"),
        ),
        _context(),
    )

    assert scope_reader.calls == []
    assert source.calls == []
    assert result.degradedReasons == ["source_identity_temporal_scope_unknown"]
