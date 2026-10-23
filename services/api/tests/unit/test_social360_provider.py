from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from shared.intelligence_projections.contracts import (  # noqa: E402
    Experience360FrameRequest,
    Experience360PolicyDisposition,
    ProjectionContext,
    ProjectionRequest,
    ProjectionSubject,
)
from shared.contracts_models.epistemic import EpistemicStatus  # noqa: E402
from graph.operational_intelligence.models import EvidenceRef, TimeRangeFilter  # noqa: E402
from shared.graph.graph import Edge, GraphClient, Vertex  # noqa: E402
from shared.intelligence_projections.composition import (  # noqa: E402
    compose_experience360_frame,
)
from identity.population360.scope import PopulationScopeRead  # noqa: E402
from identity.identity.source_subject_scope import SourceSubjectScopeRead  # noqa: E402
from services.social360.provider import (  # noqa: E402
    AgentSubjectScopeRead,
    OUTPUT_SECTIONS,
    RepositorySocialRelationshipFidelityReader,
    Social360FactRead,
    SocialGraphPathRead,
    SocialObservedPath,
    Social360Provider,
    SocialRelationshipFidelityRead,
    RepositorySocialGraphPathReader,
    RepositorySocialSyndicateMembershipReader,
    SocialSyndicateMembership,
    SocialSyndicateMembershipRead,
    _domain_slot_ids,
)


TENANT = "tenant-social-360"


class FakeSocialSource:
    def __init__(
        self,
        rows: dict[str, list[dict]] | None = None,
        *,
        unavailable: set[str] | None = None,
    ) -> None:
        self.rows = rows or {}
        self.unavailable = unavailable or set()
        self.calls: list[tuple[str, str, int]] = []

    async def read(self, fact_family: str, tenant_id: str, *, limit: int):
        self.calls.append((fact_family, tenant_id, limit))
        rows = self.rows.get(fact_family, [])
        available = fact_family not in self.unavailable
        return Social360FactRead(
            rows=list(rows),
            available=available,
            truncated=len(rows) >= 500,
            reason=None if available else f"{fact_family}_source_unavailable",
        )


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


class FakeSocialGraphPathReader:
    def __init__(self, result: SocialGraphPathRead) -> None:
        self.result = result
        self.calls: list[tuple[str, str]] = []

    async def read_paths(self, tenant_id: str, start_entity_id: str):
        self.calls.append((tenant_id, start_entity_id))
        return self.result


class FakeSocialRelationshipFidelityReader:
    def __init__(self, reads: dict[tuple[str, str], SocialRelationshipFidelityRead]):
        self.reads = reads
        self.calls: list[tuple[str, str, str]] = []

    async def read(self, tenant_id: str, source_entity_id: str, target_entity_id: str):
        self.calls.append((tenant_id, source_entity_id, target_entity_id))
        return self.reads.get(
            (source_entity_id, target_entity_id),
            SocialRelationshipFidelityRead(
                tenant_id,
                f"{source_entity_id}::{target_entity_id}",
                "unknown",
                reason="relationship_fidelity_not_persisted",
            ),
        )


class FakeSocialSyndicateMembershipReader:
    def __init__(self, result: SocialSyndicateMembershipRead) -> None:
        self.result = result
        self.calls: list[tuple[str, str, int]] = []

    async def read(self, tenant_id: str, entity_id: str, *, limit: int):
        self.calls.append((tenant_id, entity_id, limit))
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


def _syndicate_membership(
    *, tenant_id: str = TENANT, entity_id: str = "entity-a", population_id: str = "syndicate-a"
):
    return SocialSyndicateMembership(
        tenant_id=tenant_id,
        entity_id=entity_id,
        population_id=population_id,
        population_type="cluster",
        joined_at="2026-10-18T09:00:00Z",
        evidence_ref=EvidenceRef(
            id=f"member-of-{population_id}",
            type="relationship",
            source="graph_mutation_ledger",
            observedAt="2026-10-18T09:00:00Z",
        ),
    )


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
    coverage = evidence.content["sourceCoverage"]
    assert coverage["state"] == "degraded"
    assert coverage["countsAreScopedToRequestedSubject"] is True
    assert coverage["temporalScopeState"] == "not_requested"
    assert coverage["temporalScope"] == "unbounded"
    assert coverage["families"]["identity"]["scopedObservationCount"] == 1
    assert coverage["families"]["metric"]["scopedObservationCount"] == 1
    assert coverage["families"]["metric"]["sourceTimestampedCount"] == 1
    assert coverage["families"]["metric"]["receivedAtCount"] == 0
    identity_claim = next(
        claim for claim in result.claims if claim.id == "social360.identity.identity-fact-a"
    )
    assert identity_claim.evidenceRefs[0].id == "identity-fact-a"
    assert identity_claim.domainSlotIds == _domain_slot_ids("entity", "identity")
    assert source.calls[0] == ("identity", TENANT, 500)


@pytest.mark.asyncio
async def test_syndicates_slot_requires_exact_active_ledger_evidence_and_stays_partial():
    membership = _syndicate_membership()
    reader = FakeSocialSyndicateMembershipReader(
        SocialSyndicateMembershipRead(
            tenant_id=TENANT,
            entity_id="entity-a",
            rows=[membership],
            available=True,
            scope_known=True,
        )
    )
    provider = Social360Provider(
        source=FakeSocialSource({"identity": [_identity("identity-a", "entity-a", "social-a")]}),
        consent_reader=_allow_consent,
        syndicate_membership_reader=reader,
    )

    result = await provider.project(_request(include_sections=["syndicates"]), _context())

    section = next(section for section in result.sections if section.id == "syndicates")
    assert section.state == "degraded"
    assert section.content["coverage"] == "unknown"
    assert section.content["complete"] is False
    assert section.content["memberships"] == [
        {
            "populationId": "syndicate-a",
            "populationType": "cluster",
            "membershipState": "active",
            "joinedAt": "2026-10-18T09:00:00Z",
            "evidenceRef": membership.evidence_ref.model_dump(mode="json"),
        }
    ]
    assert section.content["freshness"]["state"] == "unknown"
    assert section.canonicalAuthorityRefs == [
        "cohort_membership",
        "evidence",
        "graph",
        "population_definitions",
    ]
    claim = next(claim for claim in result.claims if "syndicates" in (claim.domainSlotIds or []))
    assert claim.evidenceRefs == [membership.evidence_ref]
    assert claim.claimState == "observed"
    assert reader.calls == [(TENANT, "entity-a", 100)]


@pytest.mark.asyncio
async def test_repository_syndicate_reader_requires_canonical_entity_before_membership_read():
    membership = _syndicate_membership()

    class FakeProfileSyndicateSource:
        def __init__(self, *, canonical_scope_known: bool = True) -> None:
            self.canonical_scope_known = canonical_scope_known
            self.canonical_calls = []
            self.membership_calls = []

        async def canonical_entity(self, tenant_id, subject):
            self.canonical_calls.append((tenant_id, subject.kind, subject.id))
            return SimpleNamespace(
                record={"tenant_id": tenant_id, "entity_id": subject.id},
                available=True,
                scope_known=self.canonical_scope_known,
                reason=None,
            )

        async def syndicate_memberships(self, tenant_id, subject, *, limit):
            self.membership_calls.append((tenant_id, subject.kind, subject.id, limit))
            return SimpleNamespace(
                rows=[membership],
                available=True,
                scope_known=True,
                truncated=False,
                reason=None,
            )

    source = FakeProfileSyndicateSource()
    reader = RepositorySocialSyndicateMembershipReader(source=source)
    result = await reader.read(TENANT, "entity-a", limit=500)
    assert result.available is True
    assert result.scope_known is True
    assert result.rows == [membership]
    assert source.canonical_calls == [(TENANT, "entity", "entity-a")]
    assert source.membership_calls == [(TENANT, "entity", "entity-a", 100)]

    unresolved_source = FakeProfileSyndicateSource(canonical_scope_known=False)
    unresolved = await RepositorySocialSyndicateMembershipReader(
        source=unresolved_source
    ).read(TENANT, "entity-a", limit=100)
    assert unresolved.available is True
    assert unresolved.scope_known is False
    assert unresolved_source.membership_calls == []


@pytest.mark.asyncio
async def test_syndicates_slot_keeps_missing_membership_unknown_and_rejects_foreign_scope():
    empty_reader = FakeSocialSyndicateMembershipReader(
        SocialSyndicateMembershipRead(
            tenant_id=TENANT,
            entity_id="entity-a",
            rows=[],
            available=True,
            scope_known=True,
        )
    )
    empty_result = await Social360Provider(
        source=FakeSocialSource(),
        consent_reader=_allow_consent,
        syndicate_membership_reader=empty_reader,
    ).project(_request(include_sections=["syndicates"]), _context())
    empty_section = next(section for section in empty_result.sections if section.id == "syndicates")
    assert empty_section.state == "unknown"
    assert empty_section.content["memberships"] == []
    assert empty_section.content["observedMembershipCount"] is None
    assert empty_section.content["reasonCode"] == (
        "social_syndicate_membership_not_observed_completeness_unknown"
    )
    assert not [claim for claim in empty_result.claims if "syndicates" in (claim.domainSlotIds or [])]

    foreign_reader = FakeSocialSyndicateMembershipReader(
        SocialSyndicateMembershipRead(
            tenant_id="tenant-other",
            entity_id="entity-a",
            rows=[_syndicate_membership(tenant_id="tenant-other")],
            available=True,
            scope_known=True,
        )
    )
    foreign_result = await Social360Provider(
        source=FakeSocialSource(),
        consent_reader=_allow_consent,
        syndicate_membership_reader=foreign_reader,
    ).project(_request(include_sections=["syndicates"]), _context())
    foreign_section = next(
        section for section in foreign_result.sections if section.id == "syndicates"
    )
    assert foreign_section.state == "unknown"
    assert foreign_section.content["memberships"] == []
    assert foreign_section.content["reasonCode"] == "social_syndicate_membership_scope_mismatch"
    assert foreign_result.claims == []


@pytest.mark.asyncio
async def test_syndicates_slot_requires_consent_and_does_not_claim_historical_membership():
    reader = FakeSocialSyndicateMembershipReader(
        SocialSyndicateMembershipRead(
            tenant_id=TENANT,
            entity_id="entity-a",
            rows=[_syndicate_membership()],
            available=True,
            scope_known=True,
        )
    )

    async def denied_consent(tenant_id: str, subject_id: str, anonymous_id, purpose: str):
        return False, "consent_receipt_missing"

    denied = await Social360Provider(
        source=FakeSocialSource(),
        consent_reader=denied_consent,
        syndicate_membership_reader=reader,
    ).project(_request(include_sections=["syndicates"]), _context())
    assert denied.sections[0].state == "suppressed"
    assert reader.calls == []

    historical = await Social360Provider(
        source=FakeSocialSource(),
        consent_reader=_allow_consent,
        syndicate_membership_reader=reader,
    ).project(
        _request(include_sections=["syndicates"], temporal_mode="relative"),
        _context(),
    )
    section = next(section for section in historical.sections if section.id == "syndicates")
    assert section.state == "unknown"
    assert section.content["reasonCode"] == "social_syndicate_historical_replay_unavailable"
    assert section.content["memberships"] == []
    assert reader.calls == []


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
    unsupported_graph_slots = {
        "relationship_graph",
        "multi_hop_paths",
        "syndicates",
        "influence_paths",
        "propagation",
        "social_contagion",
        "trust_edges",
        "risk_edges",
    }
    assert all(
        not unsupported_graph_slots.intersection(claim.domainSlotIds or [])
        for claim in result.claims
    )
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
async def test_unavailable_identity_source_is_degraded_and_does_not_join_partial_rows():
    source = FakeSocialSource(
        {
            "identity": [_identity("partial-identity", "entity-a", "social-a")],
            "metric": [
                {
                    "fact_id": "metric-from-partial-identity",
                    "tenant_id": TENANT,
                    "social_identity_ref": "social-a",
                    "metric_name": "followers",
                    "value": 999,
                    "observed_at": "2026-10-18T09:00:00Z",
                }
            ],
        },
        unavailable={"identity"},
    )

    result = await Social360Provider(source=source, consent_reader=_allow_consent).project(
        _request(), _context()
    )

    sections = {section.id: section for section in result.sections}
    assert source.calls == [("identity", TENANT, 500)]
    assert all(
        section.state == "degraded"
        for section_id, section in sections.items()
        if section_id not in {"paths", "propagation", "influence", "syndicates"}
    )
    assert sections["paths"].state == "unknown"
    assert sections["propagation"].state == "unknown"
    assert sections["influence"].state == "unknown"
    assert sections["summary"].content["coverage"] == "unavailable"
    coverage = sections["evidence"].content["sourceCoverage"]
    assert coverage["state"] == "unavailable"
    assert coverage["identityBindingState"] == "unavailable"
    assert coverage["scopeState"] == "degraded"
    assert coverage["families"]["identity"]["readState"] == "unavailable"
    assert coverage["families"]["identity"]["scopedObservationCount"] is None
    assert coverage["families"]["metric"]["readState"] == "not_read"
    assert coverage["families"]["metric"]["scopedObservationCount"] is None
    assert "metric-from-partial-identity" not in result.model_dump_json()
    assert result.claims == []


@pytest.mark.asyncio
async def test_identity_id_with_unresolved_duplicate_binding_is_excluded_from_joins():
    source = FakeSocialSource(
        {
            "identity": [
                _identity("identity-resolved", "entity-a", "social-shared"),
                {
                    **_identity("identity-unresolved", "entity-a", "social-shared"),
                    "canonical_entity_ref": None,
                    "resolution_state": "unresolved",
                },
            ],
            "metric": [
                {
                    "fact_id": "metric-should-not-join",
                    "tenant_id": TENANT,
                    "social_identity_ref": "social-shared",
                    "metric_name": "followers",
                    "value": 77,
                }
            ],
        }
    )

    result = await Social360Provider(source=source, consent_reader=_allow_consent).project(
        _request(), _context()
    )

    sections = {section.id: section for section in result.sections}
    assert sections["state"].state == "degraded"
    assert sections["summary"].content["identityCount"] is None
    assert sections["state"].content["identities"] == []
    assert sections["state"].content["metrics"] == []
    assert sections["evidence"].content["sourceCoverage"]["identityBindingState"] == "degraded"
    assert result.claims == []
    assert "metric-should-not-join" not in result.model_dump_json()


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
            include_sections=["state", "evidence"],
            temporal_mode="as_of",
            as_of="2026-10-17T10:00:00Z",
        ),
        _context(),
    )

    state = next(section for section in result.sections if section.id == "state")
    assert state.state == "degraded"
    assert [row["social_identity_id"] for row in state.content["identities"]] == ["social-a"]
    assert "temporal_fact_coverage_incomplete" in result.degradedReasons
    evidence = next(section for section in result.sections if section.id == "evidence")
    assert evidence.content["sourceCoverage"]["temporalScope"] == "bounded"
    assert evidence.content["sourceCoverage"]["temporalScopeState"] == "incomplete"


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
    for claim in result.claims:
        family = claim.kind.removeprefix("social_").removesuffix("_fact_observation")
        assert claim.domainSlotIds == _domain_slot_ids("population", family)


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
    assert {
        section.state
        for section in empty.sections
        if section.id not in {"paths", "propagation", "influence", "syndicates"}
    } == {"empty"}
    assert next(section for section in empty.sections if section.id == "paths").state == "unknown"
    assert next(section for section in empty.sections if section.id == "influence").state == "unknown"
    assert next(section for section in empty.sections if section.id == "propagation").state == "unknown"

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
    for claim in result.claims:
        family = claim.kind.removeprefix("social_").removesuffix("_fact_observation")
        assert claim.domainSlotIds == _domain_slot_ids("source", family)


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


def _observed_edge(
    from_id: str,
    to_id: str,
    evidence_id: str | None = None,
    *,
    tenant_id: str = TENANT,
    observed_at: str | None = None,
) -> Edge:
    properties = {
        "tenant_id": tenant_id,
        "relationship_predicate": "FOLLOWS",
        "idempotency_key": f"follow:{from_id}:{to_id}",
        "valid_from": "2026-10-20T10:00:00Z",
    }
    if observed_at is not None:
        properties["observed_at"] = observed_at
    if evidence_id is not None:
        properties["evidence_refs"] = [evidence_id]
    return Edge(
        edge_type="FOLLOWS_SOCIAL",
        from_vertex_id=from_id,
        to_vertex_id=to_id,
        properties=properties,
    )


def _fidelity_read(
    source_entity_id: str,
    target_entity_id: str,
    evidence_id: str,
    *,
    tenant_id: str = TENANT,
    computed_at: str = "2026-10-22T10:00:00Z",
    **dimensions: float,
) -> SocialRelationshipFidelityRead:
    relationship_ref = f"{source_entity_id}::{target_entity_id}"
    return SocialRelationshipFidelityRead(
        tenant_id=tenant_id,
        relationship_ref=relationship_ref,
        state="available",
        vector={
            "relationship_ref": relationship_ref,
            "status": "current",
            "observation_count": 1,
            **dimensions,
        },
        vector_evidence_refs=(
            EvidenceRef(
                id=evidence_id,
                type="event",
                source="relationship_fidelity",
            ),
        ),
        run_evidence_ref=EvidenceRef(
            id=f"run:{source_entity_id}:{target_entity_id}",
            type="model_output",
            source="computation_substrate",
            observedAt=computed_at,
        ),
        computed_at=computed_at,
    )


@pytest.mark.asyncio
async def test_repository_social_path_reader_returns_only_bounded_tenant_follows_paths():
    client = GraphClient()
    await client.connect()
    for entity_id, tenant_id in (
        ("entity-a", TENANT),
        ("entity-b", TENANT),
        ("entity-c", TENANT),
        ("entity-d", TENANT),
        ("entity-x", TENANT),
        ("entity-foreign", "tenant-other"),
    ):
        await client.add_vertex(
            Vertex(
                vertex_type="Entity",
                vertex_id=entity_id,
                properties={"tenantId": tenant_id},
            )
        )
    await client.add_edge(_observed_edge("entity-a", "entity-b", "observation-ab"))
    await client.add_edge(_observed_edge("entity-b", "entity-c", "observation-bc"))
    # Missing source evidence blocks this edge from contributing to a path.
    await client.add_edge(_observed_edge("entity-c", "entity-d"))
    await client.add_edge(
        Edge(
            edge_type="RELATED",
            from_vertex_id="entity-a",
            to_vertex_id="entity-d",
            properties={"tenant_id": TENANT},
        )
    )
    await client.add_edge(
        Edge(
            edge_type="FOLLOWS_SOCIAL",
            from_vertex_id="entity-a",
            to_vertex_id="entity-x",
            properties={
                **_observed_edge("entity-a", "entity-x", "unused").properties,
                "relationship_predicate": "MUTUAL_SOCIAL_CONNECTION",
            },
        )
    )
    await client.add_edge(_observed_edge("entity-c", "entity-foreign", "foreign-edge"))

    result = await RepositorySocialGraphPathReader(graph_client=client).read_paths(
        TENANT, "entity-a"
    )

    assert result.available is True
    assert [(path.entity_ids, len(path.edge_evidence_refs)) for path in result.paths] == [
        (("entity-a", "entity-b", "entity-c"), 2)
    ]
    assert [
        (edge.from_vertex_id, edge.to_vertex_id) for edge in result.paths[0].graph_edges
    ] == [("entity-a", "entity-b"), ("entity-b", "entity-c")]
    assert result.paths[0].edge_observed_at == (None, None)
    refs = {ref.id for edge in result.paths[0].edge_evidence_refs for ref in edge}
    assert {
        "follow:entity-a:entity-b",
        "observation-ab",
        "follow:entity-b:entity-c",
        "observation-bc",
    } == refs
    graph_refs = [
        ref
        for edge_refs in result.paths[0].edge_evidence_refs
        for ref in edge_refs
        if ref.source == "entity_graph"
    ]
    fact_refs = [
        ref
        for edge_refs in result.paths[0].edge_evidence_refs
        for ref in edge_refs
        if ref.source == "relationship_facts"
    ]
    assert len(graph_refs) == len(fact_refs) == 2
    assert all(ref.observedAt == "2026-10-20T10:00:00+00:00" for ref in graph_refs)
    # Graph validity time is not a substitute for the source observation time.
    assert all(ref.observedAt is None for ref in fact_refs)
    assert "entity-foreign" not in {entity for path in result.paths for entity in path.entity_ids}

    projected = await Social360Provider(
        source=FakeSocialSource(),
        consent_reader=_allow_consent,
        social_graph_path_reader=RepositorySocialGraphPathReader(graph_client=client),
    ).project(_request(include_sections=["propagation"]), _context())
    propagation = projected.sections[0].content["propagation"]
    assert propagation["paths"][0]["entityPath"] == ["entity-a", "entity-b", "entity-c"]
    assert propagation["paths"][0]["timeOrderState"] == "unknown"
    assert propagation["paths"][0]["propagationAuthority"][
        "certifiedForPropagationAnalysis"
    ]
    assert {ref.id for ref in propagation["evidenceRefs"]} == refs
    await client.close()


@pytest.mark.asyncio
async def test_multi_hop_paths_has_exact_claim_evidence_and_composes_to_its_slot():
    source = FakeSocialSource()
    edge_ab = (
        EvidenceRef(
            id="follow:entity-a:entity-b",
            type="relationship",
            source="entity_graph",
            observedAt="2026-10-20T10:00:00Z",
        ),
        EvidenceRef(
            id="observation-ab",
            type="event",
            source="relationship_facts",
            observedAt="2026-10-20T10:00:00Z",
        ),
    )
    edge_bc = (
        EvidenceRef(
            id="follow:entity-b:entity-c",
            type="relationship",
            source="entity_graph",
            observedAt="2026-10-20T10:00:00Z",
        ),
        EvidenceRef(
            id="observation-bc",
            type="event",
            source="relationship_facts",
            observedAt="2026-10-20T10:00:00Z",
        ),
    )
    path_reader = FakeSocialGraphPathReader(
        SocialGraphPathRead(
            TENANT,
            "entity-a",
            paths=(SocialObservedPath(("entity-a", "entity-b", "entity-c"), (edge_ab, edge_bc)),),
        )
    )
    result = await Social360Provider(
        source=source,
        consent_reader=_allow_consent,
        social_graph_path_reader=path_reader,
    ).project(_request(include_sections=["paths"]), _context())

    section = next(section for section in result.sections if section.id == "paths")
    assert section.state == "available"
    assert section.canonicalAuthorityRefs == ["graph", "relationship_facts"]
    path_content = section.content["multiHopPaths"]
    assert path_content["coverage"] == "bounded_observed_paths_only"
    assert path_content["completeness"] == "unknown"
    assert path_content["freshness"] == "unknown"
    assert path_content["pathSemantics"]["transitiveRelationshipClaim"] is False
    assert path_content["pathSemantics"]["trustInferred"] is False
    assert path_content["pathSemantics"]["influenceInferred"] is False
    path_claims = [
        claim for claim in result.claims if "multi_hop_paths" in (claim.domainSlotIds or [])
    ]
    assert len(path_claims) == 1
    claim = path_claims[0]
    assert claim.domainSlotIds == ["multi_hop_paths"]
    assert claim.claimState.value == "observed"
    assert {ref.id for ref in claim.evidenceRefs} == {
        "follow:entity-a:entity-b",
        "observation-ab",
        "follow:entity-b:entity-c",
        "observation-bc",
    }
    assert path_reader.calls == [(TENANT, "entity-a")]

    frame = compose_experience360_frame(
        Experience360FrameRequest(
            surfaceId="social360",
            tenantId=TENANT,
            subject=ProjectionSubject(kind="entity", id="entity-a"),
            requestedSlotIds=["multi_hop_paths"],
            includeEvidence=True,
        ),
        [result],
        frame_policy=Experience360PolicyDisposition(state="allowed"),
    )
    slot = next(slot for slot in frame.slots if slot.id == "multi_hop_paths")
    assert slot.state == "degraded"
    assert "slot_partial_implementation" in slot.reasonCodes
    assert slot.claims == [claim]
    assert {ref.id for ref in slot.evidenceRefs} == {ref.id for ref in claim.evidenceRefs}
    assert slot.freshness.state == "unknown"
    assert slot.policyDisposition.state == "allowed"
    assert frame.degradation is not None
    assert frame.degradation.level == "partial"
    assert "multi_hop_paths:slot_partial_implementation" in frame.degradation.reasons


@pytest.mark.asyncio
async def test_propagation_slot_uses_exact_graph_path_and_governed_authority_without_scores():
    edge_ab = _observed_edge("entity-a", "entity-b", "observation-ab")
    edge_bc = _observed_edge("entity-b", "entity-c", "observation-bc")
    edge_refs = (
        (
            EvidenceRef(
                id="follow:entity-a:entity-b", type="relationship", source="entity_graph"
            ),
            EvidenceRef(id="observation-ab", type="event", source="relationship_facts"),
        ),
        (
            EvidenceRef(
                id="follow:entity-b:entity-c", type="relationship", source="entity_graph"
            ),
            EvidenceRef(id="observation-bc", type="event", source="relationship_facts"),
        ),
    )
    path_reader = FakeSocialGraphPathReader(
        SocialGraphPathRead(
            TENANT,
            "entity-a",
            paths=(
                SocialObservedPath(
                    ("entity-a", "entity-b", "entity-c"),
                    edge_refs,
                    (edge_ab, edge_bc),
                    (None, None),
                ),
            ),
        )
    )

    result = await Social360Provider(
        source=FakeSocialSource(),
        consent_reader=_allow_consent,
        social_graph_path_reader=path_reader,
    ).project(_request(include_sections=["propagation"]), _context())

    section = result.sections[0]
    assert section.id == "propagation"
    assert section.state == "degraded"
    assert section.canonicalAuthorityRefs == [
        "graph",
        "relationship_facts",
        "relationship_predicate_registry",
        "influence_propagation",
    ]
    propagation = section.content["propagation"]
    assert propagation["coverage"] == "bounded_observed_propagation_eligible_paths"
    assert propagation["completeness"] == "unknown"
    assert propagation["freshness"] == "unknown"
    assert propagation["componentValuesIncluded"] is False
    assert propagation["causalContagionEstablished"] is False
    path = propagation["paths"][0]
    assert path["entityPath"] == ["entity-a", "entity-b", "entity-c"]
    assert path["timeOrderState"] == "unknown"
    assert path["propagationAuthority"]["certifiedForPropagationAnalysis"] is True
    assert path["propagationAuthority"]["decision"] == "pass"
    assert all(
        component["state"] in {"insufficient_data", "not_applicable"}
        for component in path["componentCoverage"]
    )
    assert all(component["measuredHopCount"] == 0 for component in path["componentCoverage"])
    assert all("value" not in component for component in path["componentCoverage"])
    assert {ref.id for ref in propagation["evidenceRefs"]} == {
        "follow:entity-a:entity-b",
        "observation-ab",
        "follow:entity-b:entity-c",
        "observation-bc",
    }
    claim = next(claim for claim in result.claims if "propagation" in claim.domainSlotIds)
    assert claim.domainSlotIds == ["propagation"]
    assert {ref.id for ref in claim.evidenceRefs} == {
        "follow:entity-a:entity-b",
        "observation-ab",
        "follow:entity-b:entity-c",
        "observation-bc",
    }
    assert "does not establish" in claim.claims[0]


@pytest.mark.asyncio
async def test_propagation_slot_rejects_cross_tenant_graph_hops_before_emitting_evidence():
    edge_ab = _observed_edge(
        "entity-a", "entity-b", "observation-ab", tenant_id="tenant-other"
    )
    edge_bc = _observed_edge("entity-b", "entity-c", "observation-bc")
    edge_refs = (
        (
            EvidenceRef(
                id="follow:entity-a:entity-b", type="relationship", source="entity_graph"
            ),
            EvidenceRef(id="observation-ab", type="event", source="relationship_facts"),
        ),
        (
            EvidenceRef(
                id="follow:entity-b:entity-c", type="relationship", source="entity_graph"
            ),
            EvidenceRef(id="observation-bc", type="event", source="relationship_facts"),
        ),
    )
    path_reader = FakeSocialGraphPathReader(
        SocialGraphPathRead(
            TENANT,
            "entity-a",
            paths=(
                SocialObservedPath(
                    ("entity-a", "entity-b", "entity-c"),
                    edge_refs,
                    (edge_ab, edge_bc),
                    (None, None),
                ),
            ),
        )
    )

    result = await Social360Provider(
        source=FakeSocialSource(),
        consent_reader=_allow_consent,
        social_graph_path_reader=path_reader,
    ).project(_request(include_sections=["propagation"]), _context())

    section = result.sections[0]
    assert section.id == "propagation"
    assert section.state == "degraded"
    assert section.content is None
    assert section.warnings == ["canonical_social_propagation_path_validation_failed"]
    assert result.claims == []


@pytest.mark.asyncio
async def test_propagation_time_order_requires_explicit_source_observation_times():
    edge_ab = _observed_edge(
        "entity-a",
        "entity-b",
        "observation-ab",
        observed_at="2026-10-19T10:00:00Z",
    )
    edge_bc = _observed_edge(
        "entity-b",
        "entity-c",
        "observation-bc",
        observed_at="2026-10-20T10:00:00Z",
    )
    edge_refs = (
        (
            EvidenceRef(
                id="follow:entity-a:entity-b", type="relationship", source="entity_graph"
            ),
            EvidenceRef(id="observation-ab", type="event", source="relationship_facts"),
        ),
        (
            EvidenceRef(
                id="follow:entity-b:entity-c", type="relationship", source="entity_graph"
            ),
            EvidenceRef(id="observation-bc", type="event", source="relationship_facts"),
        ),
    )
    path_reader = FakeSocialGraphPathReader(
        SocialGraphPathRead(
            TENANT,
            "entity-a",
            paths=(
                SocialObservedPath(
                    ("entity-a", "entity-b", "entity-c"),
                    edge_refs,
                    (edge_ab, edge_bc),
                    ("2026-10-19T10:00:00+00:00", "2026-10-20T10:00:00+00:00"),
                ),
            ),
        )
    )

    result = await Social360Provider(
        source=FakeSocialSource(),
        consent_reader=_allow_consent,
        social_graph_path_reader=path_reader,
    ).project(_request(include_sections=["propagation"]), _context())

    path = result.sections[0].content["propagation"]["paths"][0]
    assert path["sourceObservedAtByEdge"] == [
        "2026-10-19T10:00:00+00:00",
        "2026-10-20T10:00:00+00:00",
    ]
    assert path["timeOrderState"] == "ordered"
    assert "social_propagation_source_observation_time_missing" not in (
        result.sections[0].warnings or []
    )


@pytest.mark.asyncio
async def test_multi_hop_paths_is_unknown_when_no_bounded_path_is_observed():
    path_reader = FakeSocialGraphPathReader(
        SocialGraphPathRead(
            TENANT,
            "entity-a",
            paths=(),
            reason_codes=("no_bounded_observed_follows_paths",),
        )
    )
    result = await Social360Provider(
        source=FakeSocialSource(),
        consent_reader=_allow_consent,
        social_graph_path_reader=path_reader,
    ).project(_request(include_sections=["paths"]), _context())

    section = result.sections[0]
    assert section.id == "paths"
    assert section.state == "unknown"
    assert section.content is None
    assert section.warnings == ["no_bounded_observed_follows_paths"]
    assert result.claims == []


@pytest.mark.asyncio
async def test_multi_hop_paths_require_consent_for_every_path_endpoint():
    edge_refs = (
        EvidenceRef(id="edge-ab", type="relationship", source="entity_graph"),
        EvidenceRef(id="evidence-ab", type="event", source="relationship_facts"),
    )
    edge_refs_bc = (
        EvidenceRef(id="edge-bc", type="relationship", source="entity_graph"),
        EvidenceRef(id="evidence-bc", type="event", source="relationship_facts"),
    )
    path_reader = FakeSocialGraphPathReader(
        SocialGraphPathRead(
            TENANT,
            "entity-a",
            paths=(
                SocialObservedPath(
                    ("entity-a", "entity-b", "entity-c"),
                    (edge_refs, edge_refs_bc),
                ),
            ),
        )
    )
    checked: list[str] = []

    async def deny_intermediate(tenant_id: str, subject_id: str, anonymous_id, purpose: str):
        assert tenant_id == TENANT
        assert anonymous_id is None
        assert purpose == "analytics"
        checked.append(subject_id)
        return subject_id != "entity-b", "consent_receipt_missing"

    result = await Social360Provider(
        source=FakeSocialSource(),
        consent_reader=deny_intermediate,
        social_graph_path_reader=path_reader,
    ).project(_request(include_sections=["paths"]), _context())

    section = result.sections[0]
    assert checked == ["entity-a", "entity-b", "entity-c"]
    assert section.state == "unknown"
    assert section.content is None
    assert section.warnings == ["social_path_endpoint_consent_restricted"]
    assert result.claims == []


@pytest.mark.asyncio
async def test_influence_paths_join_exact_graph_edges_to_tenant_fidelity_and_preserve_gaps():
    edge_ab = _observed_edge(
        "entity-a", "entity-b", "observation-ab", observed_at="2026-10-20T10:00:00Z"
    )
    edge_bc = _observed_edge(
        "entity-b", "entity-c", "observation-bc", observed_at="2026-10-21T10:00:00Z"
    )
    graph_fact_refs = (
        (
            EvidenceRef(
                id="follow:entity-a:entity-b", type="relationship", source="entity_graph"
            ),
            EvidenceRef(id="observation-ab", type="event", source="relationship_facts"),
        ),
        (
            EvidenceRef(
                id="follow:entity-b:entity-c", type="relationship", source="entity_graph"
            ),
            EvidenceRef(id="observation-bc", type="event", source="relationship_facts"),
        ),
    )
    path_reader = FakeSocialGraphPathReader(
        SocialGraphPathRead(
            TENANT,
            "entity-a",
            paths=(
                SocialObservedPath(
                    ("entity-a", "entity-b", "entity-c"),
                    graph_fact_refs,
                    (edge_ab, edge_bc),
                    ("2026-10-20T10:00:00+00:00", "2026-10-21T10:00:00+00:00"),
                ),
            ),
        )
    )
    fidelity_reader = FakeSocialRelationshipFidelityReader(
        {
            ("entity-a", "entity-b"): _fidelity_read(
                "entity-a",
                "entity-b",
                "observation-ab",
                interaction_frequency=0.8,
                interaction_depth=0.6,
                persistence=0.7,
                reciprocity=0.9,
            ),
            ("entity-b", "entity-c"): _fidelity_read(
                "entity-b",
                "entity-c",
                "observation-bc",
                interaction_frequency=0.5,
                interaction_depth=0.9,
                persistence=0.4,
                reciprocity=0.3,
            ),
        }
    )

    result = await Social360Provider(
        source=FakeSocialSource(),
        consent_reader=_allow_consent,
        social_graph_path_reader=path_reader,
        relationship_fidelity_reader=fidelity_reader,
    ).project(_request(include_sections=["influence"]), _context())

    section = result.sections[0]
    assert section.id == "influence"
    assert section.state == "degraded"
    assert section.canonicalAuthorityRefs == [
        "computation",
        "graph",
        "influence_propagation",
        "relationship_facts",
        "relationship_fidelity",
        "relationship_predicate_registry",
    ]
    influence = section.content["influencePaths"]
    assert influence["coverage"] == "bounded_evidence_backed_influence_analysis_paths"
    assert influence["completeness"] == influence["freshness"] == "unknown"
    assert influence["influenceSemantics"]["actualInfluenceEstablished"] is False
    path = influence["paths"][0]
    assert path["entityPath"] == ["entity-a", "entity-b", "entity-c"]
    assert path["fidelityCoverage"] == {
        "state": "complete",
        "measuredHopCount": 2,
        "materialHopCount": 2,
        "completeness": "unknown",
        "freshness": "unknown",
        "evidenceJoin": "all_vector_evidence_refs_must_match_exact_path_edge",
    }
    assert path["influenceAuthority"]["certifiedForInfluenceAnalysis"] is True
    assert path["componentValuesIncluded"] is True
    assert path["actualInfluenceEstablished"] is False
    assert path["causalContagionEstablished"] is False
    components = {row["componentId"]: row for row in path["components"]}
    assert components["raw_attention"]["state"] == "available"
    assert components["raw_attention"]["value"] == 0.7
    assert components["relationship_weighted_attention"]["value"] == 0.35
    assert components["novel_attention"]["state"] == "insufficient_data"
    evidence_ids = {ref.id for ref in path["evidenceRefs"]}
    assert {
        "follow:entity-a:entity-b",
        "observation-ab",
        "run:entity-a:entity-b",
        "follow:entity-b:entity-c",
        "observation-bc",
        "run:entity-b:entity-c",
    } <= evidence_ids
    claim = next(claim for claim in result.claims if "influence_paths" in claim.domainSlotIds)
    assert claim.domainSlotIds == ["influence_paths"]
    assert claim.claimState == EpistemicStatus.DERIVED
    assert "does not establish actual influence" in claim.claims[0]
    assert fidelity_reader.calls == [
        (TENANT, "entity-a", "entity-b"),
        (TENANT, "entity-b", "entity-c"),
    ]


@pytest.mark.asyncio
async def test_influence_paths_reject_fidelity_without_exact_edge_evidence_join():
    edge_ab = _observed_edge(
        "entity-a", "entity-b", "observation-ab", observed_at="2026-10-20T10:00:00Z"
    )
    edge_bc = _observed_edge(
        "entity-b", "entity-c", "observation-bc", observed_at="2026-10-21T10:00:00Z"
    )
    edge_refs = (
        (
            EvidenceRef(
                id="follow:entity-a:entity-b", type="relationship", source="entity_graph"
            ),
            EvidenceRef(id="observation-ab", type="event", source="relationship_facts"),
        ),
        (
            EvidenceRef(
                id="follow:entity-b:entity-c", type="relationship", source="entity_graph"
            ),
            EvidenceRef(id="observation-bc", type="event", source="relationship_facts"),
        ),
    )
    path_reader = FakeSocialGraphPathReader(
        SocialGraphPathRead(
            TENANT,
            "entity-a",
            paths=(
                SocialObservedPath(
                    ("entity-a", "entity-b", "entity-c"),
                    edge_refs,
                    (edge_ab, edge_bc),
                    ("2026-10-20T10:00:00+00:00", "2026-10-21T10:00:00+00:00"),
                ),
            ),
        )
    )
    fidelity_reader = FakeSocialRelationshipFidelityReader(
        {
            ("entity-a", "entity-b"): _fidelity_read(
                "entity-a",
                "entity-b",
                "unrelated-observation",
                interaction_frequency=0.95,
            )
        }
    )

    result = await Social360Provider(
        source=FakeSocialSource(),
        consent_reader=_allow_consent,
        social_graph_path_reader=path_reader,
        relationship_fidelity_reader=fidelity_reader,
    ).project(_request(include_sections=["influence"]), _context())

    section = result.sections[0]
    path = section.content["influencePaths"]["paths"][0]
    assert path["fidelityCoverage"]["state"] == "unavailable"
    assert path["componentValuesIncluded"] is False
    assert all(component["value"] is None for component in path["components"])
    assert path["hopMeasurements"][0]["reasonCode"] == (
        "relationship_fidelity_evidence_not_bound_to_path_edge"
    )
    evidence_ids = {ref.id for ref in path["evidenceRefs"]}
    assert "unrelated-observation" not in evidence_ids
    assert "run:entity-a:entity-b" not in evidence_ids
    claim = next(claim for claim in result.claims if "influence_paths" in claim.domainSlotIds)
    assert claim.claimState == EpistemicStatus.OBSERVED
    assert "0 of 2 path hops" in claim.claims[0]


@pytest.mark.asyncio
async def test_influence_paths_preserve_consent_filter_and_missing_path_unknown():
    edge_ab = _observed_edge(
        "entity-a", "entity-b", "observation-ab", observed_at="2026-10-20T10:00:00Z"
    )
    edge_bc = _observed_edge(
        "entity-b", "entity-c", "observation-bc", observed_at="2026-10-21T10:00:00Z"
    )
    edge_refs = (
        (
            EvidenceRef(
                id="follow:entity-a:entity-b", type="relationship", source="entity_graph"
            ),
            EvidenceRef(id="observation-ab", type="event", source="relationship_facts"),
        ),
        (
            EvidenceRef(
                id="follow:entity-b:entity-c", type="relationship", source="entity_graph"
            ),
            EvidenceRef(id="observation-bc", type="event", source="relationship_facts"),
        ),
    )
    path_reader = FakeSocialGraphPathReader(
        SocialGraphPathRead(
            TENANT,
            "entity-a",
            paths=(
                SocialObservedPath(
                    ("entity-a", "entity-b", "entity-c"),
                    edge_refs,
                    (edge_ab, edge_bc),
                    ("2026-10-20T10:00:00+00:00", "2026-10-21T10:00:00+00:00"),
                ),
            ),
        )
    )
    fidelity_reader = FakeSocialRelationshipFidelityReader({})
    checked: list[str] = []

    async def deny_intermediate(tenant_id: str, subject_id: str, anonymous_id, purpose: str):
        checked.append(subject_id)
        return subject_id != "entity-b", "consent_receipt_missing"

    denied = await Social360Provider(
        source=FakeSocialSource(),
        consent_reader=deny_intermediate,
        social_graph_path_reader=path_reader,
        relationship_fidelity_reader=fidelity_reader,
    ).project(_request(include_sections=["influence"]), _context())
    denied_section = denied.sections[0]
    assert checked == ["entity-a", "entity-b", "entity-c"]
    assert denied_section.state == "unknown"
    assert denied_section.content is None
    assert denied_section.warnings == ["social_path_endpoint_consent_restricted"]
    assert fidelity_reader.calls == []
    assert denied.claims == []

    no_paths = await Social360Provider(
        source=FakeSocialSource(),
        consent_reader=_allow_consent,
        social_graph_path_reader=FakeSocialGraphPathReader(
            SocialGraphPathRead(
                TENANT,
                "entity-a",
                paths=(),
                reason_codes=("no_bounded_observed_follows_paths",),
            )
        ),
        relationship_fidelity_reader=fidelity_reader,
    ).project(_request(include_sections=["influence"]), _context())
    no_path_section = no_paths.sections[0]
    assert no_path_section.state == "unknown"
    assert no_path_section.content is None
    assert no_path_section.warnings == ["no_bounded_observed_follows_paths"]
    assert no_paths.claims == []


@pytest.mark.asyncio
async def test_repository_social_fidelity_reader_uses_exact_tenant_directed_pair(monkeypatch):
    from identity.relationship_intelligence import reads as relationship_reads

    calls: list[tuple[str, str]] = []
    fidelity_vector = {
        "fidelity_vector_id": "fid-social-pair",
        "relationship_ref": "entity-a::entity-b",
        "status": "current",
        "observation_count": 1,
        "evidence_refs": ["observation-ab"],
        "computed_at": "2026-10-22T10:00:00Z",
        "interaction_frequency": 0.8,
    }

    async def read_latest_fidelity(tenant_id: str, relationship_ref: str):
        calls.append((tenant_id, relationship_ref))
        return {
            "kind": "fidelity_vector_surface",
            "relationship_ref": relationship_ref,
            "status": "completed",
            "run_id": "run-fidelity-ab",
            "vector": fidelity_vector,
        }

    monkeypatch.setattr(relationship_reads, "read_latest_fidelity", read_latest_fidelity)
    result = await RepositorySocialRelationshipFidelityReader().read(
        TENANT, "entity-a", "entity-b"
    )

    assert calls == [(TENANT, "entity-a::entity-b")]
    assert result.state == "available"
    assert result.relationship_ref == "entity-a::entity-b"
    assert result.vector["interaction_frequency"] == 0.8
    assert [ref.id for ref in result.vector_evidence_refs] == ["observation-ab"]
    assert result.run_evidence_ref.id == "run-fidelity-ab"
