"""Focused behavioral contract for the read-only Profile360 provider."""

from __future__ import annotations

from typing import Optional

import pytest
from types import SimpleNamespace

from graph.operational_intelligence.models import TimeRangeFilter
from graph.temporal360.history_replay import SubjectEvent, SubjectHistory
from journeys.communication360.contracts import (
    CommunicationConsentEvidence,
    CommunicationMessage,
)
from shared.intelligence_projections.composition import compose_experience360_frame
from shared.intelligence_projections.contracts import (
    EvidenceRef,
    Experience360FrameRequest,
    Experience360PolicyDisposition,
    ProjectionRequest,
    ProjectionSubject,
)
from shared.intelligence_projections.registry import ProviderRegistry
from identity.profile.profile360_provider import (
    CanonicalEntityRead,
    CommunicationRead,
    EventRead,
    HistoryRead,
    IdentityBindingRead,
    JourneyRead,
    OUTPUT_SECTIONS,
    Profile360Provider,
    ProfileRead,
    RepositoryProfile360Source,
    SessionIdentityRead,
    SyndicateMembership,
    SyndicateMembershipRead,
)


TENANT = "tenant_profile360"
USER_ID = "user-profile-1"
AS_OF = "2026-06-01T12:00:00Z"
WINDOW_START = "2026-05-01T00:00:00Z"
WINDOW_END = "2026-06-01T00:00:00Z"


def _history(*, present: bool = True, event_count: int = 1) -> SubjectHistory:
    events = (
        SubjectEvent(
            recorded_at="2026-05-20T12:00:00Z",
            ledger_offset=4,
            kind="vertex_superseded",
            operation="node_updated",
            aggregate_type="node",
            aggregate_id=f"{TENANT}:user:{USER_ID}",
            mutation_id="mutation-profile-4",
            valid_from="2026-05-20T12:00:00Z",
            vertex_id=f"{TENANT}:user:{USER_ID}",
            changed={"status": {"before": "new", "after": "active"}},
        ),
    ) if event_count else ()
    return SubjectHistory(
        subject_id=f"{TENANT}:user:{USER_ID}",
        as_of=AS_OF,
        present=present,
        vertex={"status": "active", "tenant_id": TENANT},
        first_recorded="2026-05-20T12:00:00Z" if event_count else None,
        last_recorded="2026-05-20T12:00:00Z" if event_count else None,
        event_count=event_count,
        events=events,
        live_edges=(),
        vertex_supersessions=1 if event_count else 0,
        incident_edge_adds=0,
        incident_edge_revocations=0,
        digest="digest-profile360",
    )


class _FakeProfileSource:
    def __init__(
        self,
        *,
        identity: Optional[ProfileRead] = None,
        entity: Optional[CanonicalEntityRead] = None,
        events: Optional[EventRead] = None,
        history: Optional[HistoryRead] = None,
        binding: Optional[IdentityBindingRead] = None,
        communications: Optional[CommunicationRead] = None,
        syndicates: Optional[SyndicateMembershipRead] = None,
        fail: bool = False,
    ) -> None:
        self.identity = identity or ProfileRead(
            record={
                "tenant_id": TENANT,
                "user_id": USER_ID,
                "display_name": "Test Profile",
                "status": "active",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-05-30T00:00:00Z",
                "email": "private@example.invalid",
            },
            available=True,
            scope_known=True,
        )
        self.entity = entity or CanonicalEntityRead(
            record={
                "tenant_id": TENANT,
                "entity_id": USER_ID,
                "entity_type": "human",
                "display_name": "Canonical Test Name",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-05-29T00:00:00Z",
                "metadata": {"private": "must not escape"},
            },
            available=True,
            scope_known=True,
        )
        self.events = events or EventRead(
            rows=[
                {
                    "tenant_id": TENANT,
                    "canonical_entity_id": USER_ID,
                    "event_id": "event-profile-1",
                    "event_type": "profile_observed",
                    "occurred_at": "2026-05-20T10:00:00Z",
                    "properties": {"private_payload": "must not escape"},
                }
            ],
            available=True,
            scope_known=True,
        )
        self.history = history or HistoryRead(history=_history(), available=True)
        self.binding = binding or IdentityBindingRead(
            tenant_id=TENANT,
            resolved_subject=None,
            evidence_ref=None,
            authority=None,
            relationship=None,
            observed_at=None,
            available=True,
            scope_known=False,
            reason="identity_binding_not_configured",
        )
        self.communications = communications or CommunicationRead(
            rows=[], available=True, scope_known=True
        )
        self.syndicates = syndicates or SyndicateMembershipRead(
            rows=[], available=True, scope_known=True
        )
        self.fail = fail
        self.calls: list[tuple] = []

    async def identity_record(self, tenant_id, subject):
        self.calls.append(("identity", tenant_id, subject.id))
        if self.fail:
            raise RuntimeError("identity database detail must not escape")
        return self.identity

    async def identity_binding(self, tenant_id, subject):
        self.calls.append(("binding", tenant_id, subject.kind, subject.id))
        if self.fail:
            raise RuntimeError("identity binding database detail must not escape")
        return self.binding

    async def canonical_entity(self, tenant_id, subject):
        self.calls.append(("entity", tenant_id, subject.kind, subject.id))
        if self.fail:
            raise RuntimeError("entity database detail must not escape")
        return self.entity

    async def analytics_events(
        self, tenant_id, subject, *, limit, start, end
    ):
        self.calls.append(("events", tenant_id, subject.id, limit, start, end))
        if self.fail:
            raise RuntimeError("analytics database detail must not escape")
        return self.events

    async def subject_history(self, tenant_id, subject_id, *, as_of):
        self.calls.append(("history", tenant_id, subject_id, as_of))
        if self.fail:
            raise RuntimeError("ledger detail must not escape")
        return self.history

    async def communications_for_profile(
        self, tenant_id, subject, *, limit, start
    ):
        self.calls.append(("communications", tenant_id, subject.kind, subject.id, limit, start))
        if self.fail:
            raise RuntimeError("communication database detail must not escape")
        return self.communications

    async def syndicate_memberships(self, tenant_id, subject, *, limit):
        self.calls.append(("syndicates", tenant_id, subject.kind, subject.id, limit))
        if self.fail:
            raise RuntimeError("syndicate authority detail must not escape")
        return self.syndicates


def _request(
    *,
    mode: Optional[str] = None,
    time_range=None,
    include_sections: Optional[list[str]] = None,
    include_claims: Optional[bool] = None,
    subject_kind: str = "entity",
    subject_id: str = USER_ID,
) -> ProjectionRequest:
    return ProjectionRequest(
        projectionId="profile360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind=subject_kind, id=subject_id),
        temporalMode=mode,
        timeRange=time_range,
        includeSections=include_sections,
        includeClaims=include_claims,
    )


async def _project(provider: Profile360Provider, request: ProjectionRequest):
    context = await ProviderRegistry().build_context("profile360", request)
    return await provider.project(request, context)


def _section(result, section_id: str):
    return next(section for section in result.sections if section.id == section_id)


def _communication_message(
    *,
    tenant_id: str = TENANT,
    recipient_entity_id: Optional[str] = USER_ID,
    sender_entity_id: Optional[str] = None,
    binding_id: str = "recipient-binding-1",
    consent_state: str = "recorded",
) -> CommunicationMessage:
    binding_ref = EvidenceRef(
        id=binding_id,
        type="entity",
        source="comms_provider_identities",
        uri=f"store://comms_provider_identities/{binding_id}",
    )
    fact_id = "silver-fact-profile-communication-1"
    fact_ref = EvidenceRef(
        id=fact_id,
        type="event",
        source="services/api/journeys/comms/silver_comms_facts",
        uri=f"store://silver_comms_facts/{fact_id}",
    )
    consent = (
        CommunicationConsentEvidence(
            state="recorded",
            purpose="marketing",
            receipt_id="consent-receipt-1",
            subject_entity_id=recipient_entity_id,
            identity_binding_id=binding_id,
            evidence_refs=[
                EvidenceRef(
                    id="consent-receipt-1",
                    type="event",
                    source="governance.consent.authority",
                    uri="store://consent_receipts/consent-receipt-1",
                ),
                binding_ref,
            ],
        )
        if consent_state == "recorded"
        else CommunicationConsentEvidence(state="unknown")
    )
    return CommunicationMessage(
        message_id="canonical-message-1",
        tenant_id=tenant_id,
        fact_id=fact_id,
        channel="email",
        direction="outbound",
        communication_state="delivered",
        sender_entity_id=sender_entity_id,
        recipient_entity_id=recipient_entity_id,
        recipient_identity_binding_id=binding_id,
        recipient_identity_evidence_ref=binding_ref,
        occurred_at="2026-05-20T10:00:00Z",
        consent_evidence=consent,
        claim_state="observed",
        evidence_refs=[fact_ref],
    )


@pytest.mark.asyncio
async def test_window_projects_catalog_slots_and_evidence_without_raw_payloads():
    source = _FakeProfileSource()
    result = await _project(
        Profile360Provider(source),
        _request(
            mode="window",
            time_range=TimeRangeFilter(**{"from": WINDOW_START, "to": WINDOW_END}),
        ),
    )

    assert tuple(section.id for section in result.sections) == OUTPUT_SECTIONS
    assert result.tenantId == TENANT
    assert result.asOf is None
    assert source.calls[0] == ("identity", TENANT, USER_ID)
    event_call = next(call for call in source.calls if call[0] == "events")
    assert event_call[-2:] == (WINDOW_START, WINDOW_END)
    history_call = next(call for call in source.calls if call[0] == "history")
    assert history_call[2] == f"{TENANT}:user:{USER_ID}"

    summary = _section(result, "summary")
    assert summary.content["identity"]["record"]["displayName"] == "Test Profile"
    assert "email" not in summary.content["identity"]["record"]
    canonical_entity = summary.content["identity"]["canonicalEntity"]
    assert canonical_entity["state"] == "available"
    assert canonical_entity["record"] == {
        "id": USER_ID,
        "type": "human",
        "displayName": "Canonical Test Name",
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-05-29T00:00:00Z",
    }
    assert "private" not in str(canonical_entity)
    assert canonical_entity["freshness"]["state"] == "unknown"
    assert canonical_entity["freshness"]["policy"] == "not_evaluated"
    assert summary.canonicalAuthorityRefs == ["entity_registry", "identity"]
    timeline = _section(result, "timeline")
    assert timeline.content["items"][0]["id"] == "event-profile-1"
    assert "private_payload" not in str(timeline.content)
    assert timeline.canonicalAuthorityRefs == ["graph", "observations", "temporal"]
    assert _section(result, "interactions").state == "unknown"
    dimensions = {
        item["id"]: item for item in _section(result, "state").content["dimensions"]
    }
    assert dimensions["freshness"]["state"] == "unknown"
    assert dimensions["known_unknown_resolution"]["state"] == "available"
    assert dimensions["session_history"]["state"] == "unknown"
    assert "entity_registry" in _section(result, "evidence").canonicalAuthorityRefs

    identity_claim = next(
        claim for claim in result.claims if claim.id == "profile360.identity_record_present"
    )
    assert identity_claim.domainSlotIds == ["identity_spine"]
    assert identity_claim.evidenceRefs[0].source == "identity_profiles"
    activity_claim = next(
        claim for claim in result.claims if claim.id == "profile360.activity_records_observed"
    )
    assert "evidence_trace" in activity_claim.domainSlotIds
    assert activity_claim.evidenceRefs


@pytest.mark.asyncio
async def test_profile_communications_requires_exact_recipient_identity_and_consent():
    source = _FakeProfileSource(
        communications=CommunicationRead(
            rows=[_communication_message()], available=True, scope_known=True
        )
    )
    result = await _project(
        Profile360Provider(source),
        _request(
            mode="window",
            time_range=TimeRangeFilter(**{"from": WINDOW_START, "to": WINDOW_END}),
            include_sections=["interactions"],
        ),
    )

    assert [call[0] for call in source.calls] == ["identity", "entity", "communications"]
    assert source.calls[-1] == (
        "communications", TENANT, "entity", USER_ID, 100, WINDOW_START
    )
    section = _section(result, "interactions")
    assert section.state == "degraded"
    assert section.canonicalAuthorityRefs == ["communication_facts"]
    assert section.content["coverage"] == "recipient_message_spine_with_recorded_consent_only"
    assert section.content["complete"] is False
    item = section.content["items"][0]
    assert item["messageId"] == "canonical-message-1"
    assert item["occurredAt"] == "2026-05-20T10:00:00Z"
    assert item["channel"] == "email"
    assert item["direction"] == "outbound"
    assert item["communicationState"] == "delivered"
    assert item["consentPurpose"] == "marketing"
    assert {
        (ref["source"], ref["id"]) for ref in item["evidenceRefs"]
    } == {
        ("services/api/journeys/comms/silver_comms_facts", "silver-fact-profile-communication-1"),
        ("comms_provider_identities", "recipient-binding-1"),
        ("governance.consent.authority", "consent-receipt-1"),
    }
    claim = result.claims[0]
    assert claim.domainSlotIds == ["communications"]
    assert {ref.source for ref in claim.evidenceRefs} == {
        "services/api/journeys/comms/silver_comms_facts",
        "comms_provider_identities",
        "governance.consent.authority",
    }
    assert "private@example.invalid" not in str(section.content)


@pytest.mark.asyncio
async def test_profile_communications_suppresses_unknown_consent_and_sender_only_links():
    unknown_consent = _communication_message(consent_state="unknown")
    sender_only = _communication_message(
        recipient_entity_id=None,
        sender_entity_id=USER_ID,
        consent_state="unknown",
    )
    source = _FakeProfileSource(
        communications=CommunicationRead(
            rows=[unknown_consent, sender_only], available=True, scope_known=True
        )
    )
    result = await _project(
        Profile360Provider(source), _request(include_sections=["interactions"])
    )

    section = _section(result, "interactions")
    assert section.state == "unknown"
    assert section.content["items"] == []
    assert section.content["reasonCode"] == "profile_communication_consent_evidence_unavailable"
    assert result.claims == []
    assert "canonical-message-1" not in str(section.content)


@pytest.mark.asyncio
async def test_profile_communications_reject_cross_tenant_message_rows():
    source = _FakeProfileSource(
        communications=CommunicationRead(
            rows=[_communication_message(tenant_id="other-tenant")],
            available=True,
            scope_known=True,
        )
    )
    result = await _project(
        Profile360Provider(source), _request(include_sections=["interactions"])
    )

    section = _section(result, "interactions")
    assert section.state == "unknown"
    assert section.content["reasonCode"] == "profile_communication_source_scope_mismatch"
    assert section.content["items"] == []
    assert result.claims == []


@pytest.mark.asyncio
async def test_profile_communications_require_identity_binding_evidence():
    message = _communication_message().model_copy(
        update={"recipient_identity_evidence_ref": None}
    )
    source = _FakeProfileSource(
        communications=CommunicationRead(
            rows=[message], available=True, scope_known=True
        )
    )
    result = await _project(
        Profile360Provider(source), _request(include_sections=["interactions"])
    )

    section = _section(result, "interactions")
    assert section.state == "unknown"
    assert section.content["reasonCode"] == "profile_communication_identity_binding_unproven"
    assert section.content["items"] == []
    assert result.claims == []


@pytest.mark.asyncio
async def test_profile_communications_do_not_read_current_rows_for_historical_request():
    source = _FakeProfileSource(
        communications=CommunicationRead(
            rows=[_communication_message()], available=True, scope_known=True
        )
    )
    request = _request(include_sections=["interactions"]).model_copy(
        update={"temporalMode": "as_of", "asOf": AS_OF}
    )
    result = await _project(Profile360Provider(source), request)

    assert not any(call[0] == "communications" for call in source.calls)
    section = _section(result, "interactions")
    assert section.state == "unknown"
    assert section.content["reasonCode"] == "profile_communication_historical_state_unavailable"


@pytest.mark.asyncio
async def test_repository_profile_communication_read_is_exact_bounded_participant_query(monkeypatch):
    message = _communication_message()

    class _Silver:
        def __init__(self):
            self.calls = []

        async def available(self, tenant_id):
            assert tenant_id == TENANT
            self.calls.append(("available", tenant_id))
            return True

        async def messages(self, tenant_id, *, participant_entity_id, since, limit, **kwargs):
            assert (tenant_id, participant_entity_id, since, limit) == (
                TENANT, USER_ID, WINDOW_START, 4
            )
            self.calls.append(("messages", tenant_id, participant_entity_id, since, limit))
            return [message, message.model_copy(update={"message_id": "canonical-message-2"}),
                    message.model_copy(update={"message_id": "canonical-message-3"}),
                    message.model_copy(update={"message_id": "canonical-message-4"})]

    silver = _Silver()
    monkeypatch.setattr(
        "journeys.communication360.reader.SilverCommsSource", lambda: silver
    )
    read = await RepositoryProfile360Source().communications_for_profile(
        TENANT,
        ProjectionSubject(kind="entity", id=USER_ID),
        limit=3,
        start=WINDOW_START,
    )

    assert silver.calls[0] == ("available", TENANT)
    assert read.available is True
    assert read.scope_known is True
    assert read.truncated is True
    assert [row.message_id for row in read.rows] == [
        "canonical-message-1",
        "canonical-message-2",
        "canonical-message-3",
    ]


@pytest.mark.asyncio
async def test_unresolved_empty_reads_remain_unknown_not_known_empty():
    source = _FakeProfileSource(
        identity=ProfileRead(
            record=None,
            available=True,
            scope_known=False,
            reason="identity_subject_not_resolved",
        ),
        entity=CanonicalEntityRead(
            record=None,
            available=True,
            scope_known=False,
            reason="entity_registry_identity_not_found",
        ),
        events=EventRead(rows=[], available=True, scope_known=True),
        history=HistoryRead(history=_history(present=False, event_count=0), available=True),
    )
    result = await _project(Profile360Provider(source), _request())

    dimensions = {
        item["id"]: item for item in _section(result, "state").content["dimensions"]
    }
    assert dimensions["identity"]["state"] == "unknown"
    assert dimensions["known_unknown_resolution"]["state"] == "unknown"
    assert _section(result, "evidence").content["coverage"]["observations"] == "unknown"


@pytest.mark.asyncio
async def test_identity_only_section_request_skips_activity_and_history_sources():
    source = _FakeProfileSource()
    result = await _project(
        Profile360Provider(source), _request(include_sections=["summary"])
    )

    assert [section.id for section in result.sections] == ["summary"]
    assert {call[0] for call in source.calls} == {"identity", "entity"}
    assert not any(call[0] in {"events", "history"} for call in source.calls)


@pytest.mark.asyncio
async def test_timeline_only_request_skips_profile_attribute_read():
    source = _FakeProfileSource()
    result = await _project(
        Profile360Provider(source), _request(include_sections=["timeline"])
    )

    assert [section.id for section in result.sections] == ["timeline"]
    assert "identity" not in {call[0] for call in source.calls}
    assert {call[0] for call in source.calls} == {"entity", "events", "history"}
    assert source.calls[-1][0] == "history"


@pytest.mark.asyncio
async def test_include_claims_false_omits_claim_payloads():
    result = await _project(
        Profile360Provider(_FakeProfileSource()), _request(include_claims=False)
    )

    assert result.claims == []


@pytest.mark.asyncio
async def test_same_tenant_profile_record_for_a_different_subject_is_rejected():
    source = _FakeProfileSource(
        identity=ProfileRead(
            record={
                "tenant_id": TENANT,
                "user_id": "user-other",
                "display_name": "Wrong Profile",
                "email": "wrong@example.invalid",
            },
            available=True,
            scope_known=True,
        )
    )
    result = await _project(Profile360Provider(source), _request())

    summary = _section(result, "summary")
    assert summary.content["identity"]["record"] is None
    assert summary.content["identity"]["state"] == "unknown"
    assert summary.content["identity"]["reason"] == "identity_record_subject_mismatch"
    assert "Wrong Profile" not in str(result.sections)
    assert "wrong@example.invalid" not in str(result.sections)
    assert not any(claim.id == "profile360.identity_record_present" for claim in result.claims)


@pytest.mark.asyncio
async def test_canonical_entity_row_must_match_exact_tenant_and_subject():
    source = _FakeProfileSource(
        entity=CanonicalEntityRead(
            record={
                "tenant_id": "tenant-other",
                "entity_id": USER_ID,
                "entity_type": "human",
                "display_name": "Foreign Entity",
            },
            available=True,
            scope_known=True,
        )
    )
    result = await _project(Profile360Provider(source), _request())

    identity = _section(result, "summary").content["identity"]
    assert identity["canonicalEntity"]["record"] is None
    assert identity["canonicalEntity"]["state"] == "unknown"
    assert identity["canonicalEntity"]["reason"] == "entity_registry_scope_mismatch"
    assert "Foreign Entity" not in str(result.sections)
    assert not any(claim.id == "profile360.canonical_entity_record_present" for claim in result.claims)


@pytest.mark.asyncio
async def test_repository_canonical_entity_read_filters_tenant_and_exact_id(monkeypatch):
    class _Entities:
        async def find_many(self, *, filters, limit):
            assert filters == {"tenant_id": TENANT, "entity_id": USER_ID}
            assert limit == 2
            return [
                {
                    "tenant_id": TENANT,
                    "entity_id": USER_ID,
                    "entity_type": "human",
                    "display_name": "Canonical Person",
                }
            ]

    monkeypatch.setattr(
        "repositories.repos.EntityRepository",
        lambda: _Entities(),
    )
    entity = await RepositoryProfile360Source().canonical_entity(
        TENANT, ProjectionSubject(kind="entity", id=USER_ID)
    )

    assert entity.available is True
    assert entity.scope_known is True
    assert entity.record["display_name"] == "Canonical Person"


@pytest.mark.asyncio
async def test_current_journey_participation_uses_exact_typed_profile_versions_only():
    class _JourneySource(_FakeProfileSource):
        async def current_journeys(self, tenant_id, subject, *, limit):
            self.calls.append(("journeys", tenant_id, subject.kind, subject.id, limit))
            return JourneyRead(
                rows=[{
                    "tenant_id": TENANT,
                    "profile_id": USER_ID,
                    "journey_type": "profile",
                    "is_current": True,
                    "journey_id": "journey-11",
                    "journey_version_id": "journey-version-11",
                    "journey_state": "open",
                    "computed_at": "2026-05-30T00:00:00Z",
                    "private_note": "must not escape",
                }],
                available=True,
                scope_known=True,
            )

    source = _JourneySource()
    result = await _project(
        Profile360Provider(source), _request(include_sections=["journeys"])
    )

    assert [section.id for section in result.sections] == ["journeys"]
    assert {call[0] for call in source.calls} == {"identity", "entity", "journeys"}
    section = _section(result, "journeys")
    assert section.state == "available"
    assert section.canonicalAuthorityRefs == ["journeys"]
    assert section.content["items"] == [{
        "journeyId": "journey-11",
        "versionId": "journey-version-11",
        "journeyState": "open",
        "computedAt": "2026-05-30T00:00:00Z",
        "evidenceRef": {
            "id": "journey-version-11",
            "type": "document",
            "source": "journey_versions",
            "observedAt": "2026-05-30T00:00:00Z",
                "confidence": None,
                "uri": None,
        },
    }]
    assert "private_note" not in str(result.sections)
    assert len(result.claims) == 1
    assert result.claims[0].domainSlotIds == ["journey_participation"]
    assert result.claims[0].evidenceRefs[0].id == "journey-version-11"


@pytest.mark.asyncio
async def test_current_journey_participation_rejects_cross_tenant_source_row():
    class _JourneySource(_FakeProfileSource):
        async def current_journeys(self, tenant_id, subject, *, limit):
            return JourneyRead(
                rows=[{
                    "tenant_id": "other-tenant",
                    "profile_id": USER_ID,
                    "journey_type": "profile",
                    "is_current": True,
                    "journey_id": "foreign-journey",
                    "journey_version_id": "foreign-version",
                    "private_note": "must not escape",
                }],
                available=True,
                scope_known=True,
            )

    result = await _project(
        Profile360Provider(_JourneySource()), _request(include_sections=["journeys"])
    )
    section = _section(result, "journeys")
    assert section.state == "unknown"
    assert section.content["reasonCode"] == "profile_journey_source_scope_mismatch"
    assert "foreign-journey" not in str(result.sections)
    assert result.claims == []


@pytest.mark.asyncio
async def test_bounded_journey_request_never_reads_current_journey_versions():
    class _JourneySource(_FakeProfileSource):
        async def current_journeys(self, tenant_id, subject, *, limit):
            raise AssertionError("current journey authority must not be read")

    source = _JourneySource()
    result = await _project(
        Profile360Provider(source),
        _request(
            mode="window",
            time_range=TimeRangeFilter(**{"from": WINDOW_START, "to": WINDOW_END}),
            include_sections=["journeys"],
        ),
    )
    assert _section(result, "journeys").state == "unknown"
    assert not any(call[0] in {"journeys", "events", "history"} for call in source.calls)


@pytest.mark.asyncio
async def test_repository_profile_journey_read_uses_typed_identity_and_bounded_query(monkeypatch):
    class _Journeys:
        async def find_current_for_profile(
            self, tenant_id, profile_id, *, identity_type, limit
        ):
            assert (tenant_id, profile_id, identity_type, limit) == (
                TENANT, USER_ID, "profile", 2
            )
            return [
                {
                    "tenant_id": TENANT,
                    "profile_id": USER_ID,
                    "journey_type": "profile",
                    "is_current": True,
                    "journey_id": f"journey-{index}",
                    "journey_version_id": f"version-{index}",
                }
                for index in (1, 2)
            ]

    monkeypatch.setattr(
        "journeys.measurement.repositories.journey_repo.JourneyRepository",
        lambda: _Journeys(),
    )
    read = await RepositoryProfile360Source().current_journeys(
        TENANT, ProjectionSubject(kind="entity", id=USER_ID), limit=1
    )
    assert read.available is True
    assert read.scope_known is True
    assert read.truncated is True
    assert [row["journey_id"] for row in read.rows] == ["journey-1"]


@pytest.mark.asyncio
async def test_profile_journey_result_composes_into_exact_governed_frame_slot():
    class _JourneySource(_FakeProfileSource):
        async def current_journeys(self, tenant_id, subject, *, limit):
            return JourneyRead(
                rows=[{
                    "tenant_id": TENANT,
                    "profile_id": USER_ID,
                    "journey_type": "profile",
                    "is_current": True,
                    "journey_id": "journey-composed",
                    "journey_version_id": "journey-version-composed",
                    "journey_state": "open",
                    "computed_at": "2026-05-30T00:00:00Z",
                }],
                available=True,
                scope_known=True,
            )

    projection = await _project(
        Profile360Provider(_JourneySource()), _request(include_sections=["journeys"])
    )
    allowed = Experience360PolicyDisposition(state="allowed")
    frame = compose_experience360_frame(
        Experience360FrameRequest(
            surfaceId="profile360",
            tenantId=TENANT,
            subject=ProjectionSubject(kind="entity", id=USER_ID),
            requestedSlotIds=["journey_participation"],
            includeEvidence=True,
        ),
        [projection],
        frame_policy=allowed,
        policy_by_slot={"journey_participation": allowed},
    )
    slot = frame.slots[0]
    assert slot.id == "journey_participation"
    assert slot.state in {"available", "degraded"}
    assert slot.evidenceRefs[0].id == "journey-version-composed"
    assert slot.provenance[0].projectionId == "profile360"
    assert [claim.domainSlotIds for claim in slot.claims] == [["journey_participation"]]


@pytest.mark.asyncio
async def test_resolved_session_identity_projects_partial_profile_history_without_raw_session_id():
    class _SessionSource(_FakeProfileSource):
        async def resolved_session_identities(self, tenant_id, subject, *, limit):
            self.calls.append(("session_identities", tenant_id, subject.kind, subject.id, limit))
            return SessionIdentityRead(
                rows=[{
                    "id": "source-identity-11",
                    "tenant_id": TENANT,
                    "canonical_entity_id": USER_ID,
                    "status": "resolved",
                    "source_system_id": "sdk-system",
                    "source_namespace": "sdk:site-a",
                    "session_id": "raw-session-secret",
                    "first_seen_at": "2026-05-01T00:00:00Z",
                    "last_seen_at": "2026-05-02T00:00:00Z",
                    "raw_claim": "must not escape",
                }],
                available=True,
                scope_known=True,
            )

    source = _SessionSource()
    result = await _project(
        Profile360Provider(source), _request(include_sections=["sessions"])
    )
    assert {call[0] for call in source.calls} == {"identity", "entity", "session_identities"}
    section = _section(result, "sessions")
    assert section.state == "degraded"
    assert section.content["complete"] is False
    assert section.content["items"][0]["sourceIdentityId"] == "source-identity-11"
    assert "raw-session-secret" not in str(result)
    assert "raw_claim" not in str(result)
    assert [claim.domainSlotIds for claim in result.claims] == [["session_history"]]

    allowed = Experience360PolicyDisposition(state="allowed")
    frame = compose_experience360_frame(
        Experience360FrameRequest(
            surfaceId="profile360",
            tenantId=TENANT,
            subject=ProjectionSubject(kind="entity", id=USER_ID),
            requestedSlotIds=["session_history"],
            includeEvidence=True,
        ),
        [result],
        frame_policy=allowed,
        policy_by_slot={"session_history": allowed},
    )
    slot = frame.slots[0]
    assert slot.state == "degraded"
    assert slot.evidenceRefs[0].source == "identity_source_identities"
    assert slot.provenance[0].projectionId == "profile360"


@pytest.mark.asyncio
async def test_session_identity_rejects_cross_tenant_row_and_historical_read():
    class _SessionSource(_FakeProfileSource):
        async def resolved_session_identities(self, tenant_id, subject, *, limit):
            self.calls.append(("session_identities", tenant_id, subject.id, limit))
            return SessionIdentityRead(
                rows=[{
                    "id": "foreign-source",
                    "tenant_id": "foreign-tenant",
                    "canonical_entity_id": USER_ID,
                    "status": "resolved",
                    "session_id": "foreign-secret",
                }],
                available=True,
                scope_known=True,
            )

    source = _SessionSource()
    current = await _project(
        Profile360Provider(source), _request(include_sections=["sessions"])
    )
    assert _section(current, "sessions").state == "unknown"
    assert "foreign-secret" not in str(current)
    assert current.claims == []

    source.calls.clear()
    historical = await _project(
        Profile360Provider(source),
        _request(mode="as_of", include_sections=["sessions"]),
    )
    assert _section(historical, "sessions").state == "unknown"
    assert not any(call[0] == "session_identities" for call in source.calls)


@pytest.mark.asyncio
async def test_session_identity_repository_uses_exact_resolved_tenant_scope(monkeypatch):
    class _SourceIdentities:
        async def find_many(self, *, filters, limit):
            assert filters == {
                "tenant_id": TENANT,
                "canonical_entity_id": USER_ID,
                "status": "resolved",
            }
            assert limit == 2
            return [
                {
                    "id": f"source-{index}",
                    **filters,
                    "session_id": f"session-{index}",
                }
                for index in (1, 2)
            ]

    monkeypatch.setattr(
        "identity.identity.repository.IdentityResolutionRepository",
        lambda: SimpleNamespace(_source_identities=_SourceIdentities()),
    )
    read = await RepositoryProfile360Source().resolved_session_identities(
        TENANT, ProjectionSubject(kind="entity", id=USER_ID), limit=1
    )
    assert read.available is True
    assert read.scope_known is True
    assert read.truncated is True
    assert [row["id"] for row in read.rows] == ["source-1"]


def _related_request(kind: str, subject_id: str, *, as_of: Optional[str] = None):
    return ProjectionRequest(
        projectionId="profile360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind=kind, id=subject_id),
        temporalMode="as_of" if as_of is not None else "window",
        asOf=as_of,
    )


def _profile_binding(kind: str = "journey") -> IdentityBindingRead:
    if kind == "journey":
        authority = "journeys"
        relationship = "journey_profile_id"
        evidence_id = "journey-version-7"
    else:
        authority = "episode_facts"
        relationship = "episode_user_subject"
        evidence_id = "episode-7"
    return IdentityBindingRead(
        tenant_id=TENANT,
        resolved_subject=ProjectionSubject(kind="entity", id=USER_ID),
        evidence_ref=EvidenceRef(
            id=evidence_id,
            type="relationship",
            source=authority,
            observedAt="2026-05-30T00:00:00Z",
        ),
        authority=authority,
        relationship=relationship,
        observed_at="2026-05-30T00:00:00Z",
        available=True,
        scope_known=True,
    )


@pytest.mark.asyncio
async def test_journey_entity_context_preserves_journey_subject_and_exact_profile_link():
    source = _FakeProfileSource(binding=_profile_binding("journey"))
    result = await _project(
        Profile360Provider(source), _related_request("journey", "journey-1")
    )

    summary = _section(result, "summary").content
    linked = summary["relatedEntityContext"]
    assert summary["subject"] == {"kind": "journey", "id": "journey-1"}
    assert linked["resolvedEntity"] == {
        "kind": "entity",
        "id": USER_ID,
        "status": "active",
    }
    assert linked["relationship"] == "journey_profile_id"
    assert "not the journey or episode subject" in linked["interpretation"]
    assert source.calls == [
        ("binding", TENANT, "journey", "journey-1"),
        ("identity", TENANT, USER_ID),
    ]
    assert result.claims == []
    assert _section(result, "evidence").content["count"] == 2


@pytest.mark.asyncio
async def test_episode_entity_context_requires_exact_user_subject_binding():
    source = _FakeProfileSource(binding=_profile_binding("episode"))
    result = await _project(
        Profile360Provider(source), _related_request("episode", "episode-1")
    )

    linked = _section(result, "state").content["dimensions"][0]["content"]
    assert linked["state"] == "available"
    assert linked["relationship"] == "episode_user_subject"
    assert source.calls == [
        ("binding", TENANT, "episode", "episode-1"),
        ("identity", TENANT, USER_ID),
    ]


@pytest.mark.asyncio
async def test_related_profile_context_does_not_use_current_link_for_historical_request():
    source = _FakeProfileSource(binding=_profile_binding("journey"))
    result = await _project(
        Profile360Provider(source),
        _related_request("journey", "journey-1", as_of=AS_OF),
    )

    assert source.calls == []
    assert _section(result, "summary").state == "unknown"
    assert _section(result, "summary").content["relatedEntityContext"]["reason"] == (
        "identity_binding_valid_time_unavailable"
    )


@pytest.mark.asyncio
async def test_cross_tenant_related_profile_binding_is_unknown():
    binding = _profile_binding("journey")
    source = _FakeProfileSource(
        binding=IdentityBindingRead(
            **{**binding.__dict__, "tenant_id": "tenant-other"}
        )
    )
    result = await _project(
        Profile360Provider(source), _related_request("journey", "journey-1")
    )

    assert _section(result, "summary").state == "unknown"
    assert _section(result, "summary").content["relatedEntityContext"]["reason"] == (
        "identity_binding_tenant_mismatch"
    )
    assert source.calls == [("binding", TENANT, "journey", "journey-1")]
    assert _section(result, "timeline").state == "not_applicable"
    assert _section(result, "evidence").state == "unknown"
    assert result.claims == []


@pytest.mark.asyncio
async def test_repository_journey_binding_requires_one_exact_current_profile_version(monkeypatch):
    class _Journeys:
        async def list_versions(self, tenant_id, journey_id):
            assert (tenant_id, journey_id) == (TENANT, "journey-1")
            return [
                {
                    "tenant_id": TENANT,
                    "journey_id": "journey-1",
                    "journey_type": "profile",
                    "profile_id": USER_ID,
                    "journey_version_id": "journey-version-7",
                    "is_current": True,
                    "computed_at": "2026-05-30T00:00:00Z",
                }
            ]

    monkeypatch.setattr(
        "journeys.measurement.repositories.journey_repo.JourneyRepository",
        lambda: _Journeys(),
    )
    binding = await RepositoryProfile360Source().identity_binding(
        TENANT, ProjectionSubject(kind="journey", id="journey-1")
    )

    assert binding.tenant_id == TENANT
    assert binding.scope_known is True
    assert binding.resolved_subject == ProjectionSubject(kind="entity", id=USER_ID)
    assert binding.authority == "journey_versions"
    assert binding.evidence_ref is not None
    assert binding.evidence_ref.id == "journey-version-7"


@pytest.mark.asyncio
async def test_repository_journey_binding_rejects_ambiguous_current_versions(monkeypatch):
    class _Journeys:
        async def list_versions(self, tenant_id, journey_id):
            return [
                {
                    "tenant_id": TENANT,
                    "journey_id": journey_id,
                    "journey_type": "profile",
                    "profile_id": USER_ID,
                    "journey_version_id": f"journey-version-{index}",
                    "is_current": True,
                }
                for index in (1, 2)
            ]

    monkeypatch.setattr(
        "journeys.measurement.repositories.journey_repo.JourneyRepository",
        lambda: _Journeys(),
    )
    binding = await RepositoryProfile360Source().identity_binding(
        TENANT, ProjectionSubject(kind="journey", id="journey-1")
    )

    assert binding.scope_known is False
    assert binding.resolved_subject is None
    assert binding.reason == "journey_identity_binding_ambiguous"


@pytest.mark.asyncio
async def test_repository_episode_binding_accepts_only_exact_user_subject(monkeypatch):
    episode = SimpleNamespace(
        tenant_id=TENANT,
        episode_id="episode-1",
        subject=SimpleNamespace(kind="user", id=USER_ID),
        created_at="2026-05-30T00:00:00Z",
    )

    class _Episodes:
        async def get(self, tenant_id, episode_id):
            assert (tenant_id, episode_id) == (TENANT, "episode-1")
            return episode

    monkeypatch.setattr(
        "shared.backend_interpretation.stores.EpisodeStore",
        lambda: _Episodes(),
    )
    binding = await RepositoryProfile360Source().identity_binding(
        TENANT, ProjectionSubject(kind="episode", id="episode-1")
    )

    assert binding.scope_known is True
    assert binding.resolved_subject == ProjectionSubject(kind="entity", id=USER_ID)
    assert binding.relationship == "episode_user_subject"


@pytest.mark.asyncio
async def test_repository_episode_binding_rejects_non_user_subject(monkeypatch):
    episode = SimpleNamespace(
        tenant_id=TENANT,
        episode_id="episode-1",
        subject=SimpleNamespace(kind="agent", id="agent-1"),
        created_at="2026-05-30T00:00:00Z",
    )

    class _Episodes:
        async def get(self, tenant_id, episode_id):
            return episode

    monkeypatch.setattr(
        "shared.backend_interpretation.stores.EpisodeStore",
        lambda: _Episodes(),
    )
    binding = await RepositoryProfile360Source().identity_binding(
        TENANT, ProjectionSubject(kind="episode", id="episode-1")
    )

    assert binding.scope_known is False
    assert binding.resolved_subject is None
    assert binding.reason == "episode_subject_not_exact_user_profile"


@pytest.mark.asyncio
async def test_as_of_reads_only_temporal_authority_and_reports_effective_anchor():
    source = _FakeProfileSource()
    result = await _project(
        Profile360Provider(source),
        _request(mode="as_of", time_range=TimeRangeFilter(**{"from": AS_OF})),
    )

    assert [call[0] for call in source.calls] == ["history"]
    assert source.calls[0][-1] == AS_OF
    assert result.asOf == AS_OF
    assert _section(result, "summary").content["identity"]["state"] == "unknown"
    assert _section(result, "timeline").content["asOf"] == result.asOf
    assert not any(claim.id == "profile360.identity_record_present" for claim in result.claims)


@pytest.mark.asyncio
async def test_source_failures_degrade_instead_of_claiming_empty():
    source = _FakeProfileSource(fail=True)
    result = await _project(Profile360Provider(source), _request())

    assert _section(result, "summary").state == "degraded"
    assert _section(result, "timeline").state == "degraded"
    assert _section(result, "evidence").state == "unknown"
    assert all("database detail" not in str(section.content) for section in result.sections)
    assert result.claims == []


@pytest.mark.asyncio
async def test_relative_mode_without_bounds_is_not_silently_relabelled():
    source = _FakeProfileSource()
    result = await _project(Profile360Provider(source), _request(mode="relative"))

    assert source.calls == []
    assert _section(result, "summary").state == "degraded"
    assert any(
        item["code"] == "temporal_request_not_satisfied"
        for item in _section(result, "findings").content["items"]
    )


class _AgentAuthoritySource:
    """Small canonical Agent360 fixture exercising the real delegation provider."""

    def __init__(self, *, active_scope_mismatch: bool = False) -> None:
        self.actor_identity_calls: list[tuple[str, str]] = []
        self.active_scope_mismatch = active_scope_mismatch
        self.agent_id = "agent-runtime-1"
        self.canonical_agent_id = "agent-entity-1"
        self.grantor_id = "human-entity-1"
        self.delegation = {
            "tenant_id": TENANT,
            "delegation_id": "delegation-1",
            "grantor_entity_id": self.grantor_id,
            "grantee_entity_id": self.canonical_agent_id,
            "scope": {"actions": ["invoke"], "resources": ["capability:search"]},
            "starts_at": "2026-05-01T00:00:00Z",
            "ends_at": None,
            "revoked_at": None,
            "authorization_kind": "capability",
            "capability_id": "search",
        }

    async def agent_configs(self, tenant_id, agent_id):
        return []

    async def actor_identity(self, tenant_id, agent_id):
        from actions.agent.agent360_provider import Agent360ReadBatch

        self.actor_identity_calls.append((tenant_id, agent_id))
        direct_entity = agent_id == self.canonical_agent_id
        return Agent360ReadBatch(
            rows=[
                {
                    "tenant_id": tenant_id,
                    "agent_id": agent_id,
                    "canonical_agent_entity_id": self.canonical_agent_id,
                    "identity_evidence_id": (
                        self.canonical_agent_id if direct_entity else "agent-binding-1"
                    ),
                    "identity_evidence_source": (
                        "entities" if direct_entity else "agent_deployment_identity_bindings"
                    ),
                    "identity_binding_authority": (
                        "canonical_agent_entity" if direct_entity else "tenant_admin_explicit"
                    ),
                    "identity_bound_at": "2026-05-01T00:00:00Z",
                }
            ]
        )

    async def principal_identities(self, tenant_id, principal_user_ids, limit):
        from actions.agent.agent360_provider import Agent360ReadBatch

        return Agent360ReadBatch(rows=[])

    async def executions(self, tenant_id, agent_id, limit):
        return []

    async def incoming_delegations(self, tenant_id, canonical_agent_entity_id, limit):
        return (
            [self.delegation]
            if canonical_agent_entity_id == self.canonical_agent_id
            else []
        )

    async def outgoing_delegations(self, tenant_id, canonical_agent_entity_id, limit):
        return []

    async def active_incoming_delegations(self, tenant_id, canonical_agent_entity_id):
        from actions.agent.agent360_provider import Agent360ReadBatch

        rows = (
            [self.delegation]
            if canonical_agent_entity_id == self.canonical_agent_id
            else []
        )
        return Agent360ReadBatch(
            rows=rows,
            scope_mismatch=self.active_scope_mismatch,
        )

    async def delegation_party_identities(self, tenant_id, party_entity_ids):
        from actions.agent.agent360_provider import Agent360ReadBatch

        return Agent360ReadBatch(
            rows=[
                {
                    "tenant_id": tenant_id,
                    "party_entity_id": entity_id,
                    "party_entity_type": (
                        "agent" if entity_id == self.canonical_agent_id else "human"
                    ),
                    "identity_evidence_id": entity_id,
                    "identity_evidence_source": "entities",
                    "identity_observed_at": "2026-05-01T00:00:00Z",
                }
                for entity_id in sorted(party_entity_ids)
            ]
        )

    async def activities(self, tenant_id, agent_id, limit):
        return []

    async def tools(self, tenant_id, agent_id, limit):
        return []

    async def capability_access_profile(
        self, tenant_id, agent_id, canonical_agent_entity_id
    ):
        from actions.agent.agent360_provider import Agent360ReadBatch

        return Agent360ReadBatch(
            rows=[
                {
                    "tenant_id": tenant_id,
                    "agent_id": agent_id,
                    "canonical_agent_entity_id": canonical_agent_entity_id,
                    "not_applicable": True,
                }
            ]
        )

    async def risk_signals(self, tenant_id, agent_id, limit):
        return []

    async def communications(self, tenant_id, agent_id, limit):
        from actions.agent.agent360_provider import Agent360ReadBatch

        return Agent360ReadBatch(rows=[])


@pytest.mark.asyncio
async def test_agent_delegations_reuses_exact_tenant_scoped_agent360_authority():
    from actions.agent.agent360_provider import Agent360Provider
    from shared.intelligence_projections.generated_registry import (
        INTELLIGENCE_PROJECTION_DEFINITIONS,
    )

    source = _AgentAuthoritySource()
    request = _request(
        include_sections=["agent_delegations"],
        subject_kind="agent",
        subject_id=source.agent_id,
    )
    result = await _project(
        Profile360Provider(
            _FakeProfileSource(), agent_provider=Agent360Provider(source)
        ),
        request,
    )

    section = _section(result, "agent_delegations")
    assert section.state == "available"
    assert section.canonicalAuthorityRefs == [
        "agent_access",
        "agent_executions",
        "identity",
    ]
    assert set(section.canonicalAuthorityRefs) <= set(
        INTELLIGENCE_PROJECTION_DEFINITIONS["agent360"]["canonicalAuthorities"]
    )
    assert source.actor_identity_calls == [(TENANT, source.agent_id)]
    assert section.content["identityBinding"] == {
        "state": "matched",
        "sourceAgentId": source.agent_id,
        "canonicalAgentEntityId": source.canonical_agent_id,
        "evidenceRefs": [
            {
                "id": "agent-binding-1",
                "type": "entity",
                "source": "agent_deployment_identity_bindings",
                "observedAt": "2026-05-01T00:00:00Z",
            }
        ],
    }
    authority = section.content["delegationAuthority"]
    assert authority["state"] == "available"
    assert authority["delegationRecords"][0]["delegationId"] == "delegation-1"
    assert authority["delegationRecords"][0]["granteeEntityId"] == source.canonical_agent_id
    assert authority["delegationRecords"][0]["authorizationDecision"] == "unknown"
    assert authority["effectiveAuthorizationDecision"] == "unknown"
    assert section.content["policy"]["effectiveAuthorizationDecision"] == "unknown"
    assert section.content["freshness"]["state"] == "unknown"
    assert "current_repository_state" in section.content["temporalSemantics"]
    assert result.claims
    assert all(claim.domainSlotIds == ["agent_delegations"] for claim in result.claims)
    assert all(claim.subject == request.subject for claim in result.claims)
    assert all(claim.evidenceRefs for claim in result.claims)


class _PartialAuthorityAgentProvider:
    """Keep Agent360's real evidence while simulating its partial-state contract."""

    def __init__(self, provider) -> None:
        self.provider = provider

    async def project(self, request, context):
        result = await self.provider.project(request, context)
        sections = []
        for section in result.sections:
            if section.id != "state" or not isinstance(section.content, dict):
                sections.append(section)
                continue
            dimensions = [dict(item) for item in section.content.get("dimensions", [])]
            for item in dimensions:
                if item.get("id") == "authority_and_delegation":
                    item["state"] = "partial"
                    item["content"] = {**item["content"], "state": "partial"}
            sections.append(
                section.model_copy(
                    update={
                        "content": {
                            **section.content,
                            "dimensions": dimensions,
                        }
                    }
                )
            )
        return result.model_copy(update={"sections": sections})


@pytest.mark.asyncio
async def test_agent_delegations_preserves_partial_authority_state_and_evidence():
    from actions.agent.agent360_provider import Agent360Provider

    source = _AgentAuthoritySource()
    request = _request(
        include_sections=["agent_delegations"],
        subject_kind="agent",
        subject_id=source.agent_id,
    )
    result = await _project(
        Profile360Provider(
            _FakeProfileSource(),
            agent_provider=_PartialAuthorityAgentProvider(Agent360Provider(source)),
        ),
        request,
    )

    section = _section(result, "agent_delegations")
    assert section.state == "degraded"
    assert section.content["state"] == "degraded"
    authority = section.content["delegationAuthority"]
    assert authority["state"] == "partial"
    assert authority["delegationRecords"][0]["delegationId"] == "delegation-1"
    assert source.actor_identity_calls == [(TENANT, source.agent_id)]


@pytest.mark.asyncio
async def test_agent_delegations_preserves_degraded_authority_evidence():
    from actions.agent.agent360_provider import Agent360Provider

    source = _AgentAuthoritySource(active_scope_mismatch=True)
    request = _request(
        include_sections=["agent_delegations"],
        subject_kind="agent",
        subject_id=source.agent_id,
    )
    result = await _project(
        Profile360Provider(
            _FakeProfileSource(), agent_provider=Agent360Provider(source)
        ),
        request,
    )

    section = _section(result, "agent_delegations")
    assert section.state == "degraded"
    authority = section.content["delegationAuthority"]
    assert authority["state"] == "degraded"
    assert authority["delegationRecords"][0]["delegationId"] == "delegation-1"
    assert section.content["identityBinding"]["state"] == "matched"


@pytest.mark.asyncio
async def test_agent_delegations_accepts_only_the_exact_canonical_agent_entity():
    from actions.agent.agent360_provider import Agent360Provider

    source = _AgentAuthoritySource()
    profile_source = _FakeProfileSource(
        entity=CanonicalEntityRead(
            record={
                "tenant_id": TENANT,
                "entity_id": source.canonical_agent_id,
                "entity_type": "agent",
                "created_at": "2026-05-01T00:00:00Z",
            },
            available=True,
            scope_known=True,
        )
    )
    request = _request(
        include_sections=["agent_delegations"],
        subject_kind="entity",
        subject_id=source.canonical_agent_id,
    )
    result = await _project(
        Profile360Provider(
            profile_source, agent_provider=Agent360Provider(source)
        ),
        request,
    )

    section = _section(result, "agent_delegations")
    assert section.state == "available"
    assert section.content["identityBinding"]["canonicalAgentEntityId"] == (
        source.canonical_agent_id
    )
    assert section.content["delegationAuthority"]["delegationRecords"][0][
        "delegationId"
    ] == "delegation-1"
    assert source.actor_identity_calls == [(TENANT, source.canonical_agent_id)]


@pytest.mark.asyncio
async def test_agent_delegations_keeps_non_agent_entity_unknown():
    from actions.agent.agent360_provider import Agent360Provider

    source = _AgentAuthoritySource()
    profile_source = _FakeProfileSource(
        entity=CanonicalEntityRead(
            record={
                "tenant_id": TENANT,
                "entity_id": source.grantor_id,
                "entity_type": "human",
                "created_at": "2026-05-01T00:00:00Z",
            },
            available=True,
            scope_known=True,
        )
    )
    request = _request(
        include_sections=["agent_delegations"],
        subject_kind="entity",
        subject_id=source.grantor_id,
    )
    result = await _project(
        Profile360Provider(profile_source, agent_provider=Agent360Provider(source)),
        request,
    )

    section = _section(result, "agent_delegations")
    assert section.state == "unknown"
    assert section.content["delegationAuthority"]["state"] == "unknown"
    assert section.canonicalAuthorityRefs is None
    assert not any(
        "agent_delegations" in (claim.domainSlotIds or []) for claim in result.claims
    )
    assert source.actor_identity_calls == []


@pytest.mark.asyncio
async def test_agent_delegations_keeps_unbound_profile_subject_unknown_without_lookup():
    from actions.agent.agent360_provider import Agent360Provider

    source = _AgentAuthoritySource()
    request = _request(
        include_sections=["agent_delegations"],
        subject_kind="profile",
        subject_id=USER_ID,
    )
    result = await _project(
        Profile360Provider(
            _FakeProfileSource(), agent_provider=Agent360Provider(source)
        ),
        request,
    )

    section = _section(result, "agent_delegations")
    assert section.state == "unknown"
    assert section.content["identityBinding"]["reason"] == (
        "profile_subject_has_no_exact_agent_binding"
    )
    assert result.claims == []
    assert source.actor_identity_calls == []


def _syndicate_ledger_row(
    *,
    population_id: str = "population-syndicate-1",
    tenant_id: str = TENANT,
    mutation_id: str = "mutation-membership-1",
    offset: int = 1,
    kind: str = "edge",
    membership_state: str = "active",
):
    payload = {
        "kind": kind,
        "edge_type": "MEMBER_OF",
        "from_vertex_id": USER_ID,
        "to_vertex_id": population_id,
    }
    if kind == "edge":
        payload["properties"] = {
            "tenant_id": tenant_id,
            "membership_state": membership_state,
            "evidence_refs": [],
            "valid_from": "2026-05-21T12:00:00Z",
        }
    return {
        "tenant_id": tenant_id,
        "aggregate_type": "edge",
        "aggregate_id": f"MEMBER_OF:{USER_ID}:{population_id}",
        "operation": "edge_revoked" if kind == "edge_revocation" else "edge_created",
        "recorded_at": "2026-05-21T12:00:00Z",
        "ledger_offset": offset,
        "mutation_id": mutation_id,
        "payload": payload,
    }


def _syndicate_group(population_id: str = "population-syndicate-1"):
    return {
        "id": population_id,
        "tenant_id": TENANT,
        "population_type": "community",
        "metadata": {
            "syndicates_group": True,
            "syndicates_identity_merge_policy": "union",
        },
    }


@pytest.mark.asyncio
async def test_repository_syndicate_read_uses_exact_bounded_live_edge_and_ledger_evidence(
    monkeypatch,
):
    from identity.population import registry as population_registry
    from repositories import graph_mutation_ledger

    class MembershipRepo:
        async def find_many(self, *, filters, limit):
            assert filters == {"tenant_id": TENANT, "entity_id": USER_ID}
            assert limit == 101
            return [
                {
                    "tenant_id": TENANT,
                    "entity_id": USER_ID,
                    "population_id": "population-syndicate-1",
                    "membership_state": "active",
                    # The provider must not synthesize evidence from this row.
                    "evidence_refs": [],
                }
            ]

    class PopulationRepo:
        async def find_by_id(self, population_id):
            assert population_id == "population-syndicate-1"
            return _syndicate_group(population_id)

    class LedgerRepo:
        async def list_records(self, tenant_id, *, aggregate_id, limit):
            assert tenant_id == TENANT
            assert aggregate_id == f"MEMBER_OF:{USER_ID}:population-syndicate-1"
            assert limit == 1_001
            return [_syndicate_ledger_row()]

    monkeypatch.setattr(population_registry, "membership_repo", MembershipRepo())
    monkeypatch.setattr(population_registry, "population_repo", PopulationRepo())
    monkeypatch.setattr(
        graph_mutation_ledger, "GraphMutationLedgerRepository", LedgerRepo
    )

    read = await RepositoryProfile360Source().syndicate_memberships(
        TENANT,
        ProjectionSubject(kind="entity", id=USER_ID),
        limit=100,
    )

    assert read.available is True
    assert read.scope_known is True
    assert read.truncated is False
    assert read.reason is None
    assert len(read.rows) == 1
    membership = read.rows[0]
    assert membership.population_id == "population-syndicate-1"
    assert membership.population_type == "community"
    assert membership.evidence_ref.id == "mutation-membership-1"
    assert membership.evidence_ref.source == "graph_mutation_ledger"


@pytest.mark.asyncio
async def test_repository_syndicate_read_fails_closed_on_candidate_tenant_mismatch(
    monkeypatch,
):
    from identity.population import registry as population_registry

    class MembershipRepo:
        async def find_many(self, *, filters, limit):
            assert filters == {"tenant_id": TENANT, "entity_id": USER_ID}
            return [
                {
                    "tenant_id": "another-tenant",
                    "entity_id": USER_ID,
                    "population_id": "population-syndicate-1",
                    "membership_state": "active",
                }
            ]

    monkeypatch.setattr(population_registry, "membership_repo", MembershipRepo())

    read = await RepositoryProfile360Source().syndicate_memberships(
        TENANT,
        ProjectionSubject(kind="entity", id=USER_ID),
        limit=100,
    )

    assert read.rows == []
    assert read.scope_known is False
    assert read.reason == "profile_syndicate_membership_scope_mismatch"


@pytest.mark.asyncio
async def test_repository_syndicate_read_ignores_inactive_materialized_membership(
    monkeypatch,
):
    from identity.population import registry as population_registry

    class MembershipRepo:
        async def find_many(self, *, filters, limit):
            return [
                {
                    "tenant_id": TENANT,
                    "entity_id": USER_ID,
                    "population_id": "population-syndicate-1",
                    "membership_state": "left",
                }
            ]

    class PopulationRepo:
        async def find_by_id(self, population_id):
            raise AssertionError("inactive membership must not trigger group lookup")

    monkeypatch.setattr(population_registry, "membership_repo", MembershipRepo())
    monkeypatch.setattr(population_registry, "population_repo", PopulationRepo())

    read = await RepositoryProfile360Source().syndicate_memberships(
        TENANT,
        ProjectionSubject(kind="entity", id=USER_ID),
        limit=100,
    )

    assert read.available is True
    assert read.scope_known is True
    assert read.rows == []


@pytest.mark.asyncio
async def test_repository_syndicate_read_does_not_surface_revoked_live_edge(
    monkeypatch,
):
    from identity.population import registry as population_registry
    from repositories import graph_mutation_ledger

    class MembershipRepo:
        async def find_many(self, *, filters, limit):
            return [
                {
                    "tenant_id": TENANT,
                    "entity_id": USER_ID,
                    "population_id": "population-syndicate-1",
                    "membership_state": "active",
                }
            ]

    class PopulationRepo:
        async def find_by_id(self, population_id):
            return _syndicate_group(population_id)

    class LedgerRepo:
        async def list_records(self, tenant_id, *, aggregate_id, limit):
            return [
                _syndicate_ledger_row(offset=1),
                _syndicate_ledger_row(
                    offset=2,
                    mutation_id="mutation-membership-revoked",
                    kind="edge_revocation",
                ),
            ]

    monkeypatch.setattr(population_registry, "membership_repo", MembershipRepo())
    monkeypatch.setattr(population_registry, "population_repo", PopulationRepo())
    monkeypatch.setattr(
        graph_mutation_ledger, "GraphMutationLedgerRepository", LedgerRepo
    )

    read = await RepositoryProfile360Source().syndicate_memberships(
        TENANT,
        ProjectionSubject(kind="entity", id=USER_ID),
        limit=100,
    )

    assert read.rows == []
    assert read.scope_known is True
    assert "profile_syndicate_candidate_edge_not_live" in (read.reason or "")


@pytest.mark.asyncio
async def test_repository_syndicate_read_rejects_missing_population_type(monkeypatch):
    from identity.population import registry as population_registry

    class MembershipRepo:
        async def find_many(self, *, filters, limit):
            return [
                {
                    "tenant_id": TENANT,
                    "entity_id": USER_ID,
                    "population_id": "population-syndicate-1",
                    "membership_state": "active",
                }
            ]

    class PopulationRepo:
        async def find_by_id(self, population_id):
            return {
                **_syndicate_group(population_id),
                "population_type": None,
            }

    monkeypatch.setattr(population_registry, "membership_repo", MembershipRepo())
    monkeypatch.setattr(population_registry, "population_repo", PopulationRepo())

    read = await RepositoryProfile360Source().syndicate_memberships(
        TENANT,
        ProjectionSubject(kind="entity", id=USER_ID),
        limit=100,
    )

    assert read.rows == []
    assert read.scope_known is True
    assert read.reason == "profile_syndicate_population_type_unavailable"


@pytest.mark.asyncio
async def test_repository_syndicate_read_requires_tenant_owned_population(monkeypatch):
    from identity.population import registry as population_registry

    class MembershipRepo:
        async def find_many(self, *, filters, limit):
            return [
                {
                    "tenant_id": TENANT,
                    "entity_id": USER_ID,
                    "population_id": "population-syndicate-1",
                    "membership_state": "active",
                }
            ]

    class PopulationRepo:
        async def find_by_id(self, population_id):
            return {
                **_syndicate_group(population_id),
                "tenant_id": "another-tenant",
            }

    monkeypatch.setattr(population_registry, "membership_repo", MembershipRepo())
    monkeypatch.setattr(population_registry, "population_repo", PopulationRepo())

    read = await RepositoryProfile360Source().syndicate_memberships(
        TENANT,
        ProjectionSubject(kind="entity", id=USER_ID),
        limit=100,
    )

    assert read.rows == []
    assert read.scope_known is False
    assert read.reason == "profile_syndicate_population_scope_unverified"


@pytest.mark.asyncio
async def test_repository_syndicate_read_requires_explicit_syndicates_opt_in(monkeypatch):
    from identity.population import registry as population_registry

    class MembershipRepo:
        async def find_many(self, *, filters, limit):
            return [
                {
                    "tenant_id": TENANT,
                    "entity_id": USER_ID,
                    "population_id": "population-syndicate-1",
                    "membership_state": "active",
                }
            ]

    class PopulationRepo:
        async def find_by_id(self, population_id):
            group = _syndicate_group(population_id)
            group["metadata"] = {}
            return group

    monkeypatch.setattr(population_registry, "membership_repo", MembershipRepo())
    monkeypatch.setattr(population_registry, "population_repo", PopulationRepo())

    read = await RepositoryProfile360Source().syndicate_memberships(
        TENANT,
        ProjectionSubject(kind="entity", id=USER_ID),
        limit=100,
    )

    assert read.rows == []
    assert read.scope_known is True
    assert read.reason is None


@pytest.mark.asyncio
async def test_repository_syndicate_read_rejects_inactive_state_on_live_edge(monkeypatch):
    from identity.population import registry as population_registry
    from repositories import graph_mutation_ledger

    class MembershipRepo:
        async def find_many(self, *, filters, limit):
            return [
                {
                    "tenant_id": TENANT,
                    "entity_id": USER_ID,
                    "population_id": "population-syndicate-1",
                    "membership_state": "active",
                }
            ]

    class PopulationRepo:
        async def find_by_id(self, population_id):
            return _syndicate_group(population_id)

    class LedgerRepo:
        async def list_records(self, tenant_id, *, aggregate_id, limit):
            # The edge is technically live in topology, but its canonical
            # membership state is inactive and must not yield a positive fact.
            return [_syndicate_ledger_row(membership_state="left")]

    monkeypatch.setattr(population_registry, "membership_repo", MembershipRepo())
    monkeypatch.setattr(population_registry, "population_repo", PopulationRepo())
    monkeypatch.setattr(
        graph_mutation_ledger, "GraphMutationLedgerRepository", LedgerRepo
    )

    read = await RepositoryProfile360Source().syndicate_memberships(
        TENANT,
        ProjectionSubject(kind="entity", id=USER_ID),
        limit=100,
    )

    assert read.rows == []
    assert read.scope_known is True
    assert "profile_syndicate_edge_membership_inactive" in (read.reason or "")


@pytest.mark.asyncio
async def test_profile_syndicates_exposes_verified_partial_membership_with_evidence():
    source = _FakeProfileSource(
        syndicates=SyndicateMembershipRead(
            rows=[
                SyndicateMembership(
                    tenant_id=TENANT,
                    entity_id=USER_ID,
                    population_id="population-syndicate-1",
                    population_type="community",
                    joined_at="2026-05-21T12:00:00Z",
                    evidence_ref=EvidenceRef(
                        id="mutation-membership-1",
                        type="relationship",
                        source="graph_mutation_ledger",
                        observedAt="2026-05-21T12:00:00Z",
                    ),
                )
            ],
            available=True,
            scope_known=True,
        )
    )

    result = await _project(
        Profile360Provider(source), _request(include_sections=["syndicates"])
    )

    section = _section(result, "syndicates")
    assert section.state == "degraded"
    assert section.content["memberships"][0]["membershipState"] == "active"
    assert section.content["memberships"][0]["evidenceRef"]["id"] == (
        "mutation-membership-1"
    )
    assert section.content["coverage"] == "unknown"
    assert section.content["complete"] is False
    assert section.content["freshness"]["state"] == "unknown"
    assert section.canonicalAuthorityRefs == [
        "cohort_membership",
        "evidence",
        "population_definitions",
    ]
    assert len(result.claims) == 1
    assert result.claims[0].evidenceRefs[0].id == "mutation-membership-1"
    assert result.claims[0].domainSlotIds == ["syndicates"]
    assert any(call[0] == "syndicates" for call in source.calls)


@pytest.mark.asyncio
async def test_profile_syndicates_frame_policy_deny_suppresses_content_and_evidence(
    monkeypatch,
):
    import shared.intelligence_projections.composition as composition

    source = _FakeProfileSource(
        syndicates=SyndicateMembershipRead(
            rows=[
                SyndicateMembership(
                    tenant_id=TENANT,
                    entity_id=USER_ID,
                    population_id="population-syndicate-1",
                    population_type="community",
                    joined_at="2026-05-21T12:00:00Z",
                    evidence_ref=EvidenceRef(
                        id="mutation-membership-1",
                        type="relationship",
                        source="graph_mutation_ledger",
                        observedAt="2026-05-21T12:00:00Z",
                    ),
                )
            ],
            available=True,
            scope_known=True,
        )
    )
    projection = await _project(
        Profile360Provider(source), _request(include_sections=["syndicates"])
    )
    monkeypatch.setattr(
        composition,
        "_surface_definition",
        lambda _surface_id: {
            "contractStatus": "source_aligned",
            "subjectKinds": ["entity"],
            "domainSlots": [
                {
                    "id": "syndicates",
                    "requirement": "required",
                    "canonicalAuthorityRefs": [
                        "cohort_membership",
                        "evidence",
                        "population_definitions",
                    ],
                    "projectionBindings": [
                        {
                            "projectionId": "profile360",
                            "role": "primary",
                            "sectionIds": ["syndicates"],
                            "subjectKinds": ["entity"],
                        }
                    ],
                }
            ],
        },
    )

    frame = compose_experience360_frame(
        Experience360FrameRequest(
            surfaceId="profile360",
            tenantId=TENANT,
            subject=ProjectionSubject(kind="entity", id=USER_ID),
            requestedSlotIds=["syndicates"],
            includeEvidence=True,
        ),
        [projection],
        frame_policy=Experience360PolicyDisposition(state="allowed"),
        policy_by_slot={
            "syndicates": Experience360PolicyDisposition(
                state="denied", reasonCodes=["profile_syndicates_access_denied"]
            )
        },
    )

    slot = frame.slots[0]
    assert slot.state == "suppressed"
    assert slot.content is None
    assert slot.provenance == []
    assert slot.evidenceRefs == []
    assert slot.claims == []


@pytest.mark.asyncio
async def test_profile_syndicates_is_not_read_when_section_is_not_requested():
    source = _FakeProfileSource()

    await _project(Profile360Provider(source), _request(include_sections=["summary"]))

    assert not any(call[0] == "syndicates" for call in source.calls)


@pytest.mark.asyncio
async def test_profile_syndicates_keeps_current_materialization_unknown_for_temporal_reads():
    source = _FakeProfileSource(
        syndicates=SyndicateMembershipRead(
            rows=[
                SyndicateMembership(
                    tenant_id=TENANT,
                    entity_id=USER_ID,
                    population_id="population-syndicate-1",
                    population_type="community",
                    joined_at="2026-05-21T12:00:00Z",
                    evidence_ref=EvidenceRef(
                        id="mutation-membership-1",
                        type="relationship",
                        source="graph_mutation_ledger",
                    ),
                )
            ],
            available=True,
            scope_known=True,
        )
    )
    as_of_request = _request(include_sections=["syndicates"]).model_copy(
        update={"temporalMode": "as_of", "asOf": AS_OF}
    )
    bounded_request = _request(
        include_sections=["syndicates"],
        mode="window",
        time_range=TimeRangeFilter(**{"from": WINDOW_START, "to": WINDOW_END}),
    )

    as_of_result = await _project(Profile360Provider(source), as_of_request)
    bounded_result = await _project(Profile360Provider(source), bounded_request)

    assert _section(as_of_result, "syndicates").state == "unknown"
    assert _section(bounded_result, "syndicates").state == "unknown"
    assert not any(call[0] == "syndicates" for call in source.calls)
