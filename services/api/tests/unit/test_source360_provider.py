"""Focused contract tests for the read-only Source360 provider."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from connectors.provider_runtime.source360_provider import (  # noqa: E402
    OUTPUT_SECTIONS,
    ProviderRecordsRead,
    RepositoryIdentityLineageReader,
    RepositorySource360Source,
    Source360Provider,
    SourceRowsRead,
)
from graph.operational_intelligence.models import EvidenceRef  # noqa: E402
from identity.identity.identity360_provider import (  # noqa: E402
    Identity360Result,
    Identity360Slot,
)
from tenancy.rights_authority.source_lineage import SourceAuthorityTrace  # noqa: E402
from shared.integration_contracts.events import make_raw_record  # noqa: E402
from shared.intelligence_projections.contracts import (  # noqa: E402
    Experience360FrameRequest,
    Experience360PolicyDisposition,
    Experience360PolicyEvaluation,
    ProjectionContext,
    ProjectionDependencyState,
    ProjectionRequest,
    ProjectionResult,
    ProjectionSection,
    ProjectionSubject,
)
from shared.intelligence_projections.generated_registry import (  # noqa: E402
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
)
from shared.intelligence_projections.composition import (  # noqa: E402
    compose_experience360_frame,
)
from shared.intelligence_projections.frame_runtime import (  # noqa: E402
    build_experience360_frame,
)

TENANT = "tenant-source360"
OTHER_TENANT = "tenant-other"
CONNECTION_ID = "conn-source-1"
PROVIDER_ID = "example.crm.contacts_read"


def _connection(tenant_id: str = TENANT, **overrides: object) -> dict:
    row = {
        "tenant_id": tenant_id,
        "connection_id": CONNECTION_ID,
        "provider_identity": PROVIDER_ID,
        "display_name": "Private connection label",
        "state": "connected",
        "credential_ref": "secret-ref",
        "config": {"api_key": "private-secret"},
        "created_at": "2026-10-15T09:00:00+00:00",
        "updated_at": "2026-10-16T10:00:00+00:00",
        "last_verified_at": "2026-10-16T09:55:00+00:00",
    }
    row.update(overrides)
    return row


def _provider_record(
    tenant_id: str = TENANT,
    *,
    connection_id: str = CONNECTION_ID,
    record_id: str = "record-1",
    admitted: bool = True,
) -> dict:
    source_id = f"provider-account:{connection_id}:account-1"
    record = make_raw_record(
        provider_identity=PROVIDER_ID,
        provider_record_id=record_id,
        payload={"access_token": "private-secret", "name": "Contact A"},
        tenant_id=tenant_id,
        connection_id=connection_id,
        account_id="account-1",
        observed_at="2026-10-16T09:58:00+00:00",
        metadata=(
            {
                "aether_rights_admission": {
                    "tenant_id": tenant_id,
                    "source_id": source_id,
                    "source_grant_ref": "drg_source360",
                    "rights_decision_ref": "rdec_source360",
                    "decision_identity": f"identity:{tenant_id}:{connection_id}:account-1",
                    "requested_use": "tenant_lake",
                    "purpose": "provider_raw_ingestion",
                    "destination": "tenant_lake",
                    "policy_version": "rights-policy-v1",
                    "evaluated_at": "2026-10-16T09:58:00+00:00",
                    "source_relationship": "organization_system",
                }
            }
            if admitted
            else {}
        ),
    )
    return {
        "id": record_id,
        "tenant_id": tenant_id,
        "source": PROVIDER_ID,
        "provenance_status": "valid" if admitted else "unverified",
        "license_status": "tenant_rights_granted" if admitted else "unknown",
        "terms_status": "active_grant" if admitted else "unknown",
        "quarantine_status": "not_quarantined",
        "created_at": "2026-10-16T09:58:00+00:00",
        "payload": record.model_dump(mode="json"),
    }


def _request(**overrides: object) -> ProjectionRequest:
    values: dict[str, object] = {
        "projectionId": "source360",
        "tenantId": TENANT,
        "subject": ProjectionSubject(kind="source", id=PROVIDER_ID),
    }
    values.update(overrides)
    return ProjectionRequest(**values)


def _context(
    tenant_id: str = TENANT,
    *,
    dependencies: list[ProjectionDependencyState] | None = None,
) -> ProjectionContext:
    return ProjectionContext(
        projectionId="source360",
        tenantId=tenant_id,
        registryState="in_flight",
        dependencyState=dependencies or [],
        warnings=[],
    )


class FakeSource:
    def __init__(
        self,
        *,
        connections: SourceRowsRead | None = None,
        records: ProviderRecordsRead | None = None,
    ) -> None:
        self.connection_read = connections or SourceRowsRead([_connection()], True, True)
        self.record_read = records or ProviderRecordsRead([_provider_record()], 1, True, True)
        self.connection_calls: list[tuple[str, str, str]] = []
        self.record_calls: list[tuple[str, str]] = []
        self.authority_calls: list[tuple[str, str]] = []

    async def connections(
        self,
        *,
        tenant_id: str,
        subject_kind: str,
        subject_id: str,
        limit: int,
    ) -> SourceRowsRead:
        self.connection_calls.append((tenant_id, subject_kind, subject_id))
        return self.connection_read

    async def provider_records(
        self,
        *,
        tenant_id: str,
        provider_identity: str,
        limit: int,
    ) -> ProviderRecordsRead:
        self.record_calls.append((tenant_id, provider_identity))
        return self.record_read

    async def source_authority(
        self, rights_decision_ref: str, *, tenant_id: str
    ) -> SourceAuthorityTrace | None:
        self.authority_calls.append((rights_decision_ref, tenant_id))
        if rights_decision_ref != "rdec_source360" or tenant_id != TENANT:
            return None
        return SourceAuthorityTrace(
            tenant_id=TENANT,
            rights_decision_ref="rdec_source360",
            source_grant_ref="drg_source360",
            source_id=f"provider-account:{CONNECTION_ID}:account-1",
            source_relationship="organization_system",
            provider_identity=PROVIDER_ID,
            rights_source_class="tenant_byod_data",
        )


class FakeIdentityLineageReader:
    def __init__(self, *, state: str = "available") -> None:
        self.state = state
        self.calls: list[tuple[str, str, str]] = []

    async def read(self, tenant_id: str, subject_kind: str, subject_id: str):
        self.calls.append((tenant_id, subject_kind, subject_id))
        slot = Identity360Slot(
            id="source_identifier_lineage",
            state=self.state,
            content={
                "sourceIdentities": [
                    {
                        "id": "source-identity-1",
                        "sourceKind": "connector",
                        "sourceNamespace": "crm:contacts",
                        "status": "resolved",
                        "canonicalEntityId": subject_id,
                        "identifierTypes": ["user_id"],
                        "externalId": "must-not-render",
                    }
                ],
                "coverage": {
                    "sourceIdentities": {
                        "state": "available",
                        "returned": 1,
                        "truncated": False,
                    }
                },
            },
            evidence_refs=(
                EvidenceRef(
                    id="source-identity-1",
                    type="annotation",
                    source="identity_source_identities",
                ),
                EvidenceRef(
                    id="entity-1",
                    type="entity",
                    source="entity_registry",
                ),
            ),
        )
        return Identity360Result(
            tenant_id=tenant_id,
            subject_kind=subject_kind,
            subject_id=subject_id,
            state="available",
            slots=(slot,),
            generated_at="2026-10-16T10:00:00+00:00",
        )


class FakeConnectionRepository:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.calls: list[tuple[dict[str, str], int]] = []

    async def find_many(
        self,
        *,
        filters: dict[str, str],
        limit: int,
        sort_by: str | None = None,
        sort_order: str | None = None,
    ) -> list[dict]:
        self.calls.append((filters, limit))
        return [
            row for row in self.rows if all(row.get(key) == value for key, value in filters.items())
        ][:limit]


class FakeBronzeRepository:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.calls: list[tuple[dict[str, str], int]] = []

    async def count(self, *, filters: dict[str, str]) -> int:
        return sum(
            all(row.get(key) == value for key, value in filters.items()) for row in self.rows
        )

    async def find_many(
        self, *, filters: dict[str, str], sort_by: str, sort_order: str, limit: int
    ) -> list[dict]:
        assert sort_by == "created_at"
        assert sort_order == "desc"
        self.calls.append((filters, limit))
        return [
            row for row in self.rows if all(row.get(key) == value for key, value in filters.items())
        ][:limit]


def _section(result: object, section_id: str):
    return next(section for section in result.sections if section.id == section_id)


async def test_source_projection_emits_admitted_evidence_without_raw_or_secret_data() -> None:
    source = FakeSource()
    result = await Source360Provider(source).project(_request(includeClaims=True), _context())

    assert [section.id for section in result.sections] == list(OUTPUT_SECTIONS)
    assert source.connection_calls == [(TENANT, "source", PROVIDER_ID)]
    assert source.record_calls == [(TENANT, PROVIDER_ID)]
    assert _section(result, "evidence").state == "available"
    assert _section(result, "health").state == "unknown"
    assert _section(result, "coverage").state == "unknown"
    assert result.claims
    assert all(claim.evidenceRefs for claim in result.claims)
    lineage = _section(result, "evidence").content["sourceAuthorityLineage"]
    assert lineage == [
        {
            "recordEvidenceId": "record-1",
            "state": "available",
            "sourceRelationship": "organization_system",
            "rightsSourceClass": "tenant_byod_data",
            "providerIdentity": PROVIDER_ID,
            "rightsDecisionEvidence": {
                "id": "rdec_source360",
                "type": "record",
                "source": "services/api/tenancy/rights_authority/repositories.py:rights_decisions",
            },
            "sourceGrantEvidence": {
                "id": "drg_source360",
                "type": "record",
                "source": "services/api/connectors/integrations/data_rights/repository.py:data_rights_grants",
            },
        }
    ]
    assert source.authority_calls == [("rdec_source360", TENANT)]

    serialized = json.dumps(result.model_dump(mode="json"))
    for private_value in ("private-secret", "secret-ref", "credential_ref", '"config"'):
        assert private_value not in serialized


async def test_unresolved_entity_subject_stays_unknown_without_provider_join_guess() -> None:
    source = FakeSource()
    result = await Source360Provider(source).project(
        _request(subject=ProjectionSubject(kind="entity", id="entity-1")),
        _context(),
    )

    assert source.connection_calls == []
    assert source.record_calls == []
    assert all(section.state == "unknown" for section in result.sections)
    assert result.claims == []
    assert "identity_subject_not_resolved" in result.degradedReasons


@pytest.mark.asyncio
@pytest.mark.parametrize("subject_kind", ["entity", "agent"])
async def test_identity_subject_projects_canonical_source_lineage_without_provider_inference(
    subject_kind: str,
) -> None:
    source = FakeSource()
    identity_reader = FakeIdentityLineageReader()
    provider = Source360Provider(source, identity_lineage_reader=identity_reader)
    subject_id = "entity-1" if subject_kind == "entity" else "agent-1"
    result = await provider.project(
        _request(subject=ProjectionSubject(kind=subject_kind, id=subject_id)),
        _context(),
    )

    assert identity_reader.calls == [(TENANT, subject_kind, subject_id)]
    assert source.connection_calls == []
    assert source.record_calls == []
    assert _section(result, "summary").state == "available"
    summary = _section(result, "summary").content
    assert summary["sourceIdentityAuthority"] == "identity360.source_identifier_lineage"
    assert summary["sourceIdentities"] == [
        {
            "id": "source-identity-1",
            "sourceKind": "connector",
            "sourceNamespace": "crm:contacts",
            "status": "resolved",
            "canonicalEntityId": subject_id,
            "identifierTypes": ["user_id"],
        }
    ]
    assert summary["providerRegistryJoin"] == "unknown"
    assert _section(result, "state").state == "unknown"
    evidence = _section(result, "evidence").content["identitySourceEvidence"]
    assert len(evidence) == 1
    assert evidence[0]["id"] == "source-identity-1"
    assert evidence[0]["source"] == "identity_source_identities"
    assert len(result.claims) == 1
    assert result.claims[0].domainSlotIds == ["source_identifier_lineage"]
    assert "must-not-render" not in json.dumps(result.model_dump(mode="json"))

    frame = compose_experience360_frame(
        Experience360FrameRequest(
            surfaceId="identity360",
            tenantId=TENANT,
            subject=ProjectionSubject(kind=subject_kind, id=subject_id),
            requestedSlotIds=["source_identifier_lineage"],
            includeEvidence=True,
        ),
        [result],
        frame_policy=Experience360PolicyDisposition(state="allowed"),
    )
    lineage_slot = frame.slots[0]
    assert lineage_slot.state == "available"
    assert lineage_slot.evidenceRefs[0].source == "identity_source_identities"


@pytest.mark.asyncio
async def test_identity_source_lineage_temporal_query_remains_unknown() -> None:
    source = FakeSource()
    identity_reader = FakeIdentityLineageReader()
    result = await Source360Provider(source, identity_lineage_reader=identity_reader).project(
        _request(
            subject=ProjectionSubject(kind="entity", id="entity-1"),
            timeRange={"from": "2026-10-01T00:00:00Z"},
        ),
        _context(),
    )

    assert identity_reader.calls == []
    assert all(section.state == "unknown" for section in result.sections)
    assert result.claims == []
    assert "source_identity_temporal_history_unavailable" in result.degradedReasons


@pytest.mark.asyncio
async def test_agent360_source_evidence_binding_executes_source360_for_exact_agent() -> None:
    source = FakeSource()
    identity_reader = FakeIdentityLineageReader()
    source_provider = Source360Provider(source, identity_lineage_reader=identity_reader)
    projection_calls: list[tuple[str, str, tuple[str, ...]]] = []

    class AllowPolicy:
        async def evaluate(self, request: Experience360FrameRequest):
            return Experience360PolicyEvaluation(
                surfaceId=request.surfaceId,
                tenantId=request.tenantId,
                evaluatedAt="2026-10-18T12:02:00Z",
                frameDisposition=Experience360PolicyDisposition(state="allowed"),
                slotDispositions={
                    "source_evidence_lineage": Experience360PolicyDisposition(state="allowed")
                },
            )

    class Runtime:
        async def execute_projection(self, request, **kwargs):
            sections = tuple(request.includeSections or ())
            projection_calls.append((request.projectionId, request.subject.kind, sections))
            if request.projectionId == "source360":
                return await source_provider.project(
                    request,
                    ProjectionContext(
                        projectionId="source360",
                        tenantId=request.tenantId,
                        registryState="in_flight",
                        dependencyState=[],
                        warnings=[],
                    ),
                )
            return ProjectionResult(
                projectionId=request.projectionId,
                tenantId=request.tenantId,
                contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
                sections=[
                    ProjectionSection(id=section_id, state="unknown", title="unavailable")
                    for section_id in sections
                ],
            )

    frame = await build_experience360_frame(
        Experience360FrameRequest(
            surfaceId="agent360",
            tenantId=TENANT,
            subject=ProjectionSubject(kind="agent", id="agent-source-1"),
            requestedSlotIds=["source_evidence_lineage"],
            includeEvidence=True,
        ),
        policy_evaluator=AllowPolicy(),
        projection_runtime=Runtime(),
        generated_at="2026-10-18T12:03:00Z",
    )

    assert (
        "source360",
        "agent",
        ("coverage", "evidence"),
    ) in projection_calls
    assert identity_reader.calls == [(TENANT, "agent", "agent-source-1")]
    slot = frame.slots[0]
    assert {ref.id for ref in slot.evidenceRefs} == {"source-identity-1"}
    assert any(item.sectionId == "evidence" for item in slot.provenance)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "connection_read",
    [
        SourceRowsRead([], False, False, "provider_connection_authority_unavailable"),
        SourceRowsRead([], True, False, "provider_connection_read_incomplete"),
        SourceRowsRead([_connection(OTHER_TENANT)], True, True),
    ],
)
async def test_unavailable_or_incomplete_connection_lookup_is_not_reported_missing(
    connection_read: SourceRowsRead,
) -> None:
    source = FakeSource(connections=connection_read)
    result = await Source360Provider(source).project(
        _request(subject=ProjectionSubject(kind="connection", id=CONNECTION_ID)),
        _context(),
    )

    assert _section(result, "summary").state == "unknown"
    assert _section(result, "state").state == "unknown"
    assert result.claims == []
    assert source.record_calls == []
    assert (
        connection_read.reason or "unscoped_connection_authority_rows_dropped"
    ) in result.degradedReasons


async def test_tenant_mismatch_does_not_read_either_authority() -> None:
    source = FakeSource()
    result = await Source360Provider(source).project(_request(), _context(OTHER_TENANT))

    assert source.connection_calls == []
    assert source.record_calls == []
    assert all(section.state == "unknown" for section in result.sections)
    assert "source_request_scope_or_identifier_invalid" in result.degradedReasons


async def test_unadmitted_bronze_record_is_not_exposed_as_evidence() -> None:
    source = FakeSource(
        records=ProviderRecordsRead([_provider_record(admitted=False)], 1, True, True)
    )
    result = await Source360Provider(source).project(_request(), _context())

    assert _section(result, "evidence").state == "unknown"
    assert _section(result, "evidence").content["providerRecordEvidence"] == []
    assert all(claim.kind == "tenant_provider_connection_record" for claim in result.claims)
    assert "provider_record_provenance_mismatch" in result.degradedReasons


async def test_source_rights_lineage_must_match_the_tenant_provider_and_admission_scope() -> None:
    source = FakeSource()

    async def cross_tenant_trace(rights_decision_ref: str, *, tenant_id: str):
        source.authority_calls.append((rights_decision_ref, tenant_id))
        return SourceAuthorityTrace(
            tenant_id=OTHER_TENANT,
            rights_decision_ref=rights_decision_ref,
            source_grant_ref="drg_source360",
            source_id=f"provider-account:{CONNECTION_ID}:account-1",
            source_relationship="organization_system",
            provider_identity=PROVIDER_ID,
            rights_source_class="tenant_byod_data",
        )

    source.source_authority = cross_tenant_trace  # type: ignore[method-assign]
    result = await Source360Provider(source).project(_request(), _context())

    evidence = _section(result, "evidence")
    assert evidence.state == "degraded"
    assert evidence.content["sourceAuthorityLineageState"] == "degraded"
    assert evidence.content["sourceAuthorityLineage"] == [
        {
            "recordEvidenceId": "record-1",
            "state": "unknown",
            "reason": "provider_rights_authority_trace_unavailable",
        }
    ]
    assert "provider_rights_lineage_unavailable" in result.degradedReasons


async def test_admission_source_scope_must_match_provider_record_scope() -> None:
    row = _provider_record()
    payload = row["payload"]
    payload["metadata"]["aether_rights_admission"]["source_id"] = (
        "provider-account:another-connection:account-1"
    )
    source = FakeSource(records=ProviderRecordsRead([row], 1, True, True))
    result = await Source360Provider(source).project(_request(), _context())

    evidence = _section(result, "evidence")
    assert evidence.state == "unknown"
    assert evidence.content["providerRecordEvidence"] == []
    assert source.authority_calls == []
    assert "provider_record_provenance_mismatch" in result.degradedReasons


async def test_as_of_request_stays_unknown_without_source_history_authority() -> None:
    source = FakeSource()
    result = await Source360Provider(source).project(
        _request(asOf="2026-10-16T10:00:00+00:00", temporalMode="as_of"),
        _context(),
    )

    assert source.connection_calls == []
    assert source.record_calls == []
    assert all(section.state == "unknown" for section in result.sections)
    assert "historical_source_snapshot_unavailable" in result.degradedReasons


async def test_repository_adapter_filters_connection_and_bronze_reads_by_tenant_source_and_rights() -> (
    None
):
    connections = FakeConnectionRepository(
        [_connection(), _connection(OTHER_TENANT, connection_id="conn-other")]
    )
    admitted = _provider_record()
    other = _provider_record(OTHER_TENANT, connection_id="conn-other", record_id="other")
    bronze = FakeBronzeRepository([admitted, other])
    source = RepositorySource360Source(connections=connections, bronze=bronze)

    connection_read = await source.connections(
        tenant_id=TENANT,
        subject_kind="connection",
        subject_id=CONNECTION_ID,
        limit=20,
    )
    source_read = await source.connections(
        tenant_id=TENANT,
        subject_kind="source",
        subject_id=PROVIDER_ID,
        limit=20,
    )
    record_read = await source.provider_records(
        tenant_id=TENANT,
        provider_identity=PROVIDER_ID,
        limit=20,
    )

    assert connections.calls == [
        ({"tenant_id": TENANT, "connection_id": CONNECTION_ID}, 2),
        ({"tenant_id": TENANT, "provider_identity": PROVIDER_ID}, 21),
    ]
    assert connection_read.available and connection_read.rows == [_connection()]
    assert source_read.available and source_read.complete
    assert source_read.rows == [_connection()]
    assert record_read.available and record_read.total_count == 1
    assert record_read.rows == [admitted]
    filters, limit = bronze.calls[0]
    assert filters == {
        "tenant_id": TENANT,
        "source": PROVIDER_ID,
        "provenance_status": "valid",
        "license_status": "tenant_rights_granted",
        "terms_status": "active_grant",
        "quarantine_status": "not_quarantined",
    }
    assert limit == 501
