"""Focused tests for the bounded canonical Support360 provider."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from journeys.support360.provider import (  # noqa: E402
    OUTPUT_SECTIONS,
    PROJECTION_ID,
    RepositorySupportAgentIdentityReader,
    RepositorySupport360Source,
    Support360Provider,
    SupportFactsRead,
    _REASON_CASE_AUTHORITY_MISSING,
    _REASON_CASE_NOT_FOUND,
    _REASON_CONVERSATION_AUTHORITY_MISSING,
    _REASON_CALLBACK_AUTHORITY_MISSING,
    _REASON_CALLBACK_NOT_FOUND,
    _REASON_JOURNEY_JOIN_MISSING,
    _REASON_PARTIAL_ENTITY_JOIN,
    _REASON_RESOLUTION_AUTHORITY_MISSING,
    _REASON_SUPPORT_BUSINESS_OUTCOME_MISSING,
    _REASON_SOURCE_UNAVAILABLE,
    _REASON_UNSUPPORTED_SUBJECT,
    _REASON_TICKET_CASE_JOIN_MISSING,
    _REQUIRED_SUPPORT_SLOT_IDS,
)
from graph.operational_intelligence.models import EvidenceRef  # noqa: E402
from journeys.support360.cases import (  # noqa: E402
    SupportCaseAuthorityRead,
    SupportCaseEventInput,
    SupportCaseEventType,
    SupportCaseRepository,
    reset_local_support_case_store,
)
from shared.intelligence_projections import (  # noqa: E402
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
    ProjectionContext,
    ProjectionRequest,
    ProjectionSubject,
    ProviderRegistry,
)

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"
ENTITY_ID = "entity-customer-1"


class FakeSource:
    def __init__(self, read: SupportFactsRead) -> None:
        self.read = read
        self.calls: list[tuple[str, str, str | None, str | None, str | None, int]] = []

    async def support_facts_for_entity(
        self,
        tenant_id: str,
        entity_id: str,
        *,
        limit: int,
        after: str | None = None,
        before: str | None = None,
        cursor: str | None = None,
    ) -> SupportFactsRead:
        self.calls.append((tenant_id, entity_id, after, before, cursor, limit))
        return self.read


class SelectedSupportConnection:
    async def find(self, connection_id: str):
        return {
            "tenant_id": TENANT_A,
            "connection_id": connection_id,
            "provider_identity": "support-desk",
            "state": "verified",
            "last_verified_at": "2026-10-17T10:00:00Z",
            "selected_accounts": ["support-account-1"],
        }


def _row(
    fact_id: str,
    *,
    tenant_id: str = TENANT_A,
    entity_id: str = ENTITY_ID,
    category: str = "support",
    support_case_id: str | None = None,
) -> dict[str, Any]:
    return {
        "fact_id": fact_id,
        "tenant_id": tenant_id,
        "profile_id": None,
        "recipient_entity_id": entity_id,
        "user_id": None,
        "provider": "support-desk",
        "provider_account_id": "support-account-1",
        "external_thread_id": "provider-thread-1",
        "message_category": category,
        "source_event_type": "support_message_received",
        "support_case_id": support_case_id,
        "direction": "inbound",
        "communication_state": "received",
        "occurred_at": "2026-10-17T12:00:00Z",
        "received_at": "2026-10-17T12:00:01Z",
        # Deliberately sensitive payload: Support360 must not copy it.
        "payload": {"body": "private customer message", "email": "person@example.test"},
    }


def _request(
    subject_kind: str = "entity",
    subject_id: str = ENTITY_ID,
    *,
    tenant_id: str = TENANT_A,
    time_range: dict[str, str] | None = None,
    as_of: str | None = None,
    temporal_mode: str | None = None,
    page: dict[str, Any] | None = None,
) -> ProjectionRequest:
    return ProjectionRequest(
        projectionId=PROJECTION_ID,
        tenantId=tenant_id,
        subject=ProjectionSubject(kind=subject_kind, id=subject_id),
        timeRange=time_range,
        asOf=as_of,
        temporalMode=temporal_mode,
        page=page,
    )


def _context(request: ProjectionRequest) -> ProjectionContext:
    return ProjectionContext(
        projectionId=PROJECTION_ID,
        tenantId=request.tenantId,
        registryState="in_flight",
        dependencyState=[],
        warnings=[],
    )


def _sections(result) -> dict[str, Any]:
    assert [section.id for section in result.sections] == list(OUTPUT_SECTIONS)
    return {section.id: section for section in result.sections}


@pytest.mark.asyncio
async def test_entity_projection_filters_tenant_category_and_exact_subject() -> None:
    source = FakeSource(
        SupportFactsRead(
            rows=[
                _row("exact-support"),
                _row("other-tenant", tenant_id=TENANT_B),
                _row("wrong-category", category="marketing"),
                _row("wrong-entity", entity_id="entity-other"),
                {
                    **_row("profile-id-is-not-an-entity-join"),
                    "recipient_entity_id": None,
                    "profile_id": ENTITY_ID,
                },
            ],
            available=True,
        )
    )
    request = _request()

    result = await Support360Provider(source).project(request, _context(request))

    sections = _sections(result)
    timeline = sections["timeline"].content
    assert result.tenantId == TENANT_A
    assert timeline["entryCount"] == 1
    assert timeline["entries"][0]["factId"] == "exact-support"
    assert sections["summary"].content["observedSupportCommunicationCount"] == 1
    assert _REASON_PARTIAL_ENTITY_JOIN in sections["summary"].content["reasonCodes"]
    required_slots = sections["state"].content["requiredSlots"]
    assert tuple(required_slots) == _REQUIRED_SUPPORT_SLOT_IDS
    assert required_slots["conversation_history"]["state"] == "degraded"
    assert required_slots["conversation_history"]["contentMode"] == "metadata_only"
    assert required_slots["conversation_history"]["contentAccessState"] == "unknown"
    assert required_slots["conversation_history"]["messageBodyState"] == "suppressed"
    assert required_slots["evidence_trace"]["state"] == "degraded"
    assert all(
        required_slots[slot_id]["state"] == "unknown"
        for slot_id in (
            "case_summary",
            "callbacks",
            "participants",
            "sla",
            "journey_links",
            "risk",
            "resolution",
        )
    )
    assert len(result.claims) == 1
    assert result.claims[0].domainSlotIds == ["conversation_history", "evidence_trace"]
    assert result.claims[0].claimState.value == "observed"
    assert {ref.id for ref in result.claims[0].evidenceRefs} == {"exact-support"}
    assert "private customer message" not in repr(result.model_dump())
    assert "person@example.test" not in repr(result.model_dump())
    assert source.calls == [(TENANT_A, ENTITY_ID, None, None, None, 100)]


@pytest.mark.asyncio
async def test_entity_projection_applies_canonical_window_bounds() -> None:
    source = FakeSource(
        SupportFactsRead(
            rows=[
                _row("inside-window"),
                {
                    **_row("outside-window"),
                    "occurred_at": "2026-10-15T12:00:00Z",
                },
            ],
            available=True,
        )
    )
    request = _request(
        time_range={
            "from": "2026-10-17T11:00:00-01:00",
            "to": "2026-10-17T13:00:00Z",
        }
    )

    result = await Support360Provider(source).project(request, _context(request))

    sections = _sections(result)
    assert sections["timeline"].content["entryCount"] == 1
    assert sections["timeline"].content["entries"][0]["factId"] == "inside-window"
    assert source.calls == [
        (TENANT_A, ENTITY_ID, "2026-10-17T12:00:00+00:00", "2026-10-17T13:00:00+00:00", None, 100)
    ]


@pytest.mark.asyncio
async def test_as_of_and_ambiguous_window_fail_closed() -> None:
    source = FakeSource(SupportFactsRead(rows=[_row("should-not-read")], available=True))
    as_of_request = _request(as_of="2026-10-17T12:00:00Z")
    local_time_request = _request(time_range={"from": "2026-10-17T12:00:00"})
    missing_bounds_request = _request(temporal_mode="window")

    as_of_result = await Support360Provider(source).project(as_of_request, _context(as_of_request))
    local_time_result = await Support360Provider(source).project(
        local_time_request,
        _context(local_time_request),
    )
    missing_bounds_result = await Support360Provider(source).project(
        missing_bounds_request,
        _context(missing_bounds_request),
    )

    assert as_of_result.degradedReasons == ["support_as_of_read_unavailable"]
    assert local_time_result.degradedReasons == ["support_window_timestamp_timezone_required"]
    assert missing_bounds_result.degradedReasons == ["support_window_bounds_required"]
    assert source.calls == []


@pytest.mark.asyncio
async def test_pagination_cursor_and_truncation_are_preserved() -> None:
    source = FakeSource(
        SupportFactsRead(
            rows=[_row("page-row")],
            available=True,
            truncated=True,
            next_cursor="next-page-token",
        )
    )
    request = _request(page={"limit": 1, "cursor": "incoming-page-token"})

    result = await Support360Provider(source).project(request, _context(request))

    assert result.page.nextCursor == "next-page-token"
    assert result.page.hasNextPage is True
    assert result.sections[0].state == "degraded"
    assert "support_communication_read_truncated" in result.degradedReasons
    assert source.calls == [(TENANT_A, ENTITY_ID, None, None, "incoming-page-token", 1)]


@pytest.mark.asyncio
async def test_support_case_id_stays_source_reported_and_unresolved() -> None:
    source = FakeSource(
        SupportFactsRead(
            rows=[
                _row("fact-case-1", support_case_id="case:source-42"),
                _row("fact-case-2", support_case_id="bad\ncase"),
            ],
            available=True,
        )
    )
    request = _request()

    result = await Support360Provider(source).project(request, _context(request))

    sections = _sections(result)
    state = sections["state"].content
    assert state["supportCases"]["state"] == "unknown"
    assert state["supportCases"]["reasonCode"] == _REASON_CASE_AUTHORITY_MISSING
    assert state["supportCases"]["sourceReportedReferenceCount"] == 1
    assert state["supportCases"]["sourceReportedReferencesAreCanonical"] is False
    assert state["requiredSlots"]["case_summary"]["state"] == "unknown"
    assert state["requiredSlots"]["case_summary"]["sourceReportedReferencesAreCanonical"] is False
    assert state["requiredSlots"]["journey_links"]["reasonCode"] == _REASON_JOURNEY_JOIN_MISSING
    source_refs = sections["timeline"].content["entries"]
    assert source_refs[0]["sourceReportedSupportCaseRef"] == "case:source-42"
    assert source_refs[0]["canonicalSupportCaseResolved"] is False
    assert source_refs[1]["sourceReportedSupportCaseRef"] is None
    assert state["journeyLinkage"]["state"] == "unknown"
    assert state["journeyLinkage"]["reasonCode"] == _REASON_JOURNEY_JOIN_MISSING
    assert sections["outcomes"].content is None
    assert sections["state"].content["measuredOutcomes"]["state"] == "unknown"


@pytest.mark.parametrize(
    "subject_kind",
    ["campaign"],
)
@pytest.mark.asyncio
async def test_unsupported_subject_kinds_fail_closed(subject_kind: str) -> None:
    source = FakeSource(SupportFactsRead(rows=[_row("should-not-read")], available=True))
    request = _request(subject_kind=subject_kind, subject_id=f"{subject_kind}-1")

    result = await Support360Provider(source).project(request, _context(request))

    sections = _sections(result)
    assert result.degradedReasons == [_REASON_UNSUPPORTED_SUBJECT]
    assert sections["summary"].state == "unknown"
    assert sections["summary"].content is None
    assert sections["state"].state == "degraded"
    assert sections["state"].content["supportCommunications"]["state"] == "unknown"
    assert sections["state"].content["supportCases"]["reasonCode"] == _REASON_CASE_AUTHORITY_MISSING
    assert sections["state"].content["journeyLinkage"]["reasonCode"] == _REASON_JOURNEY_JOIN_MISSING
    required_slots = sections["state"].content["requiredSlots"]
    assert tuple(required_slots) == _REQUIRED_SUPPORT_SLOT_IDS
    assert all(slot["state"] == "unknown" for slot in required_slots.values())
    assert result.claims == []
    assert source.calls == []


@pytest.mark.parametrize(
    ("subject_kind", "expected_reason"),
    [
        ("support_case", _REASON_CASE_NOT_FOUND),
        ("callback", _REASON_CALLBACK_NOT_FOUND),
        ("conversation", _REASON_CONVERSATION_AUTHORITY_MISSING),
        ("ticket", _REASON_TICKET_CASE_JOIN_MISSING),
    ],
)
@pytest.mark.asyncio
async def test_ssot_subject_kinds_fail_closed_with_typed_authority_gaps(
    subject_kind: str,
    expected_reason: str,
) -> None:
    source = FakeSource(SupportFactsRead(rows=[_row("must-not-read")], available=True))
    request = _request(subject_kind=subject_kind, subject_id=f"{subject_kind}-1")

    result = await Support360Provider(source).project(request, _context(request))

    sections = _sections(result)
    assert result.degradedReasons == [expected_reason]
    assert sections["summary"].state == "unknown"
    assert sections["summary"].content is None
    assert sections["state"].content["supportCommunications"] == {
        "state": "unknown",
        "reasonCode": expected_reason,
    }
    required_slots = sections["state"].content["requiredSlots"]
    assert tuple(required_slots) == _REQUIRED_SUPPORT_SLOT_IDS
    assert all(slot["state"] == "unknown" for slot in required_slots.values())
    assert result.claims == []
    assert source.calls == []


@pytest.mark.asyncio
async def test_canonical_support_case_subject_reads_exact_case_summary_with_evidence() -> None:
    from datetime import datetime, timezone

    from journeys.support360.cases import SupportCaseLifecycle

    repository = SupportCaseRepository()
    record = await repository.ingest_event(
        tenant_id=TENANT_A,
        connection_id="support-connection-a",
        provider_identity="support-desk",
        connection_verified_at="2026-10-17T11:00:00Z",
        event=SupportCaseEventInput(
            source_case_id="source-case-private-42",
            source_event_id="support-case-created-42",
            event_type=SupportCaseEventType.CREATED,
            occurred_at=datetime(2026, 10, 17, 12, tzinfo=timezone.utc),
        ),
    )
    source = FakeSource(SupportFactsRead(rows=[_row("must-not-read")], available=True))
    request = _request("support_case", record["case_id"])

    result = await Support360Provider(source, case_repository=repository).project(
        request,
        _context(request),
    )

    sections = _sections(result)
    slots = sections["state"].content["requiredSlots"]
    assert result.tenantId == TENANT_A
    assert sections["summary"].content["canonicalCaseId"] == record["case_id"]
    assert sections["summary"].content["lifecycle"]["state"] == SupportCaseLifecycle.OPEN.value
    assert sections["summary"].content["lifecycle"]["claimState"] == "observed"
    assert sections["summary"].content["freshness"]["state"] == "unknown"
    assert slots["case_summary"]["state"] == "degraded"
    assert slots["case_summary"]["canonicalCaseId"] == record["case_id"]
    assert slots["evidence_trace"]["state"] == "degraded"
    assert slots["callbacks"]["state"] == "empty"
    assert slots["callbacks"]["count"] == 0
    assert slots["conversation_history"]["state"] == "unknown"
    assert slots["participants"]["state"] == "unknown"
    assert slots["sla"]["state"] == "empty"
    assert slots["journey_links"]["state"] == "empty"
    assert "episode_facts" not in sections["state"].canonicalAuthorityRefs
    assert "episode_facts" not in sections["evidence"].canonicalAuthorityRefs
    assert slots["risk"]["state"] == "unknown"
    assert slots["resolution"]["state"] == "observed"
    assert slots["agents"]["state"] == "degraded"
    assert slots["agents"]["count"] == 0
    assert slots["agents"]["sourceHistoryComplete"] is False
    assert result.claims[0].domainSlotIds == ["case_summary", "resolution", "evidence_trace"]
    assert result.claims[0].claimState.value == "observed"
    assert {ref.id for ref in result.claims[0].evidenceRefs} == {
        record["case_id"],
        "support-case-created-42",
        "support-connection-a",
    }
    assert "source-case-private-42" not in repr(result.model_dump())
    assert source.calls == []


@pytest.mark.asyncio
async def test_support_case_history_keeps_only_exact_event_evidence_on_each_entry() -> None:
    from datetime import datetime, timezone

    reset_local_support_case_store()
    repository = SupportCaseRepository()
    event_at = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)
    record = await repository.ingest_event(
        tenant_id=TENANT_A,
        connection_id="support-connection-event-evidence",
        provider_identity="support-desk",
        connection_verified_at="2026-10-17T10:00:00Z",
        event=SupportCaseEventInput(
            source_case_id="source-case-event-evidence",
            source_event_id="support-case-created-event-evidence",
            event_type=SupportCaseEventType.CREATED,
            occurred_at=event_at,
        ),
        observed_at=event_at,
    )

    class RepositoryWithUnrelatedEvidence:
        async def get_case(self, tenant_id: str, case_id: str, *, limit: int):
            read = await repository.get_case(tenant_id, case_id, limit=limit)
            events = [dict(event) for event in read.events]
            events[0]["evidence_refs"] = [
                *events[0]["evidence_refs"],
                EvidenceRef(
                    id="unrelated-event",
                    type="event",
                    source="untrusted_source",
                    uri="https://example.test/unrelated-event",
                ),
            ]
            return SupportCaseAuthorityRead(
                read.record,
                events,
                read.available,
                read.complete,
                expired=read.expired,
                reason=read.reason,
            )

    request = _request("support_case", record["case_id"])
    result = await Support360Provider(
        FakeSource(SupportFactsRead(rows=[], available=True)),
        case_repository=RepositoryWithUnrelatedEvidence(),
    ).project(request, _context(request))

    sections = _sections(result)
    timeline_entry = sections["timeline"].content["entries"][0]
    assert {reference.id for reference in timeline_entry["evidenceRefs"]} == {
        "support-case-created-event-evidence",
        "support-connection-event-evidence",
    }
    all_evidence = sections["evidence"].content["evidenceRefs"]
    assert "unrelated-event" not in {reference.id for reference in all_evidence}
    assert {reference.id for reference in result.claims[0].evidenceRefs} == {
        record["case_id"],
        "support-case-created-event-evidence",
        "support-connection-event-evidence",
    }
    reset_local_support_case_store()


@pytest.mark.asyncio
async def test_canonical_case_joins_only_same_tenant_connection_and_source_case_communications(
    monkeypatch: pytest.MonkeyPatch,
):
    from datetime import datetime, timezone

    from journeys.comms.repository import CommsFactsRepository, reset_local_stores

    reset_local_support_case_store()
    reset_local_stores()
    case_repository = SupportCaseRepository()
    case_record = await case_repository.ingest_event(
        tenant_id=TENANT_A,
        connection_id="case-connection-a",
        provider_identity="support-desk",
        connection_verified_at="2026-10-17T10:00:00Z",
        event=SupportCaseEventInput(
            source_case_id="private-source-case-a",
            source_event_id="case-created-a",
            event_type=SupportCaseEventType.CREATED,
            occurred_at=datetime(2026, 10, 17, 11, tzinfo=timezone.utc),
        ),
    )
    facts_repository = CommsFactsRepository()

    async def local_pool():
        return None

    monkeypatch.setattr(facts_repository, "_pool", local_pool)
    await facts_repository.upsert(
        {
            **_row("case-message-exact", support_case_id="private-source-case-a"),
            "idempotency_key": "case-message-exact",
            "source_connector_id": "case-connection-a",
            "sender_entity_id": "entity-support-agent-unresolved",
        }
    )
    await facts_repository.upsert(
        {
            **_row("case-message-other-case", support_case_id="private-source-case-b"),
            "idempotency_key": "case-message-other-case",
            "source_connector_id": "case-connection-a",
        }
    )
    await facts_repository.upsert(
        {
            **_row("case-message-other-connection", support_case_id="private-source-case-a"),
            "idempotency_key": "case-message-other-connection",
            "source_connector_id": "case-connection-b",
        }
    )
    await facts_repository.upsert(
        {
            **_row(
                "case-message-other-tenant",
                tenant_id=TENANT_B,
                support_case_id="private-source-case-a",
            ),
            "idempotency_key": "case-message-other-tenant",
            "source_connector_id": "case-connection-a",
        }
    )
    source = RepositorySupport360Source(
        facts=facts_repository,
        connections=SelectedSupportConnection(),
    )
    request = _request("support_case", case_record["case_id"])

    result = await Support360Provider(source, case_repository=case_repository).project(
        request,
        _context(request),
    )

    sections = _sections(result)
    slots = sections["state"].content["requiredSlots"]
    history = slots["conversation_history"]
    assert history["state"] == "degraded"
    assert history["messageBodyState"] == "suppressed"
    assert history["sourceHistoryComplete"] is False
    assert history["entryCount"] == 1
    entry = history["entries"]["entries"][0]
    assert entry["factId"] == "case-message-exact"
    assert entry["canonicalSupportCaseId"] == case_record["case_id"]
    assert {reference.id for reference in entry["caseJoinEvidenceRefs"]} >= {
        case_record["case_id"],
        "case-created-a",
        "case-connection-a",
    }
    assert "sourceReportedSupportCaseRef" not in entry
    assert slots["participants"]["state"] == "empty"
    assert "support_case_participant_source_roster_history_unverified" in slots["participants"]["reasonCodes"]
    assert {reference.id for reference in sections["evidence"].content["evidenceRefs"]} >= {
        case_record["case_id"],
        "case-created-a",
        "case-connection-a",
        "case-message-exact",
    }
    assert "private customer message" not in repr(result.model_dump())
    assert "private-source-case-a" not in repr(result.model_dump())
    assert "entity-support-agent-unresolved" not in repr(result.model_dump())
    assert ENTITY_ID not in repr(result.model_dump())
    assert result.page.hasNextPage is False
    assert any(
        claim.kind == "support_case_communication_metadata"
        and "conversation_history" in claim.domainSlotIds
        and "participants" not in claim.domainSlotIds
        for claim in result.claims
    )
    reset_local_support_case_store()
    reset_local_stores()


@pytest.mark.asyncio
async def test_support_case_participants_join_only_exact_canonical_provider_conversations(
    monkeypatch: pytest.MonkeyPatch,
):
    from datetime import datetime, timezone

    from journeys.communication360.repository import (
        Communication360FactsRepository,
        reset_local_stores as reset_communication360_stores,
    )
    from journeys.comms.repository import CommsFactsRepository, reset_local_stores

    reset_local_support_case_store()
    reset_local_stores()
    reset_communication360_stores()
    case_repository = SupportCaseRepository()
    case_record = await case_repository.ingest_event(
        tenant_id=TENANT_A,
        connection_id="case-connection-participants",
        provider_identity="support-desk",
        connection_verified_at="2026-10-17T10:00:00Z",
        event=SupportCaseEventInput(
            source_case_id="private-source-case-participants",
            source_event_id="case-created-participants",
            event_type=SupportCaseEventType.CREATED,
            occurred_at=datetime(2026, 10, 17, 11, tzinfo=timezone.utc),
        ),
    )
    silver = CommsFactsRepository()
    participant_facts = Communication360FactsRepository()

    async def local_pool():
        return None

    monkeypatch.setattr(silver, "_pool", local_pool)
    monkeypatch.setattr(participant_facts, "_pool", local_pool)
    await silver.upsert(
        {
            **_row("case-message-thread-match", support_case_id="private-source-case-participants"),
            "idempotency_key": "case-message-thread-match",
            "source_connector_id": "case-connection-participants",
        }
    )
    participant_payload = {
        "provider": "support-desk",
        "provider_account_id": "support-account-1",
        "provider_conversation_id": "provider-thread-1",
        "communication_scope_kind": "provider_conversation",
        "communication_scope": "provider-thread-1",
    }
    await participant_facts.upsert(
        {
            "tenant_id": TENANT_A,
            "kind": "participant_binding",
            "source_event_id": "roster-event-match",
            "occurred_at": "2026-10-17T11:30:00Z",
            "idempotency_key": "participant-match",
            "payload": participant_payload,
        }
    )
    for suffix, changes in (
        ("wrong-account", {"provider_account_id": "other-account"}),
        ("wrong-conversation", {"provider_conversation_id": "other-thread", "communication_scope": "other-thread"}),
        ("wrong-provider", {"provider": "other-provider"}),
    ):
        await participant_facts.upsert(
            {
                "tenant_id": TENANT_A,
                "kind": "participant_binding",
                "source_event_id": f"roster-event-{suffix}",
                "occurred_at": "2026-10-17T11:31:00Z",
                "idempotency_key": f"participant-{suffix}",
                "payload": participant_payload | changes,
            }
        )
    await participant_facts.upsert(
        {
            "tenant_id": TENANT_B,
            "kind": "participant_binding",
            "source_event_id": "roster-event-other-tenant",
            "occurred_at": "2026-10-17T11:32:00Z",
            "idempotency_key": "participant-other-tenant",
            "payload": participant_payload,
        }
    )

    read = await RepositorySupport360Source(
        facts=silver,
        communication360_facts=participant_facts,
        connections=SelectedSupportConnection(),
    ).support_participants_for_case(
        TENANT_A,
        "case-connection-participants",
        "private-source-case-participants",
        "support-desk",
        limit=100,
    )

    assert read.available and read.scope_known and read.complete
    assert read.conversation_scopes == (
        ("support-desk", "support-account-1", "provider-thread-1"),
    )
    assert len(read.rows) == 1
    assert read.rows[0]["source_event_id"] == "roster-event-match"
    assert read.subject_join == (
        "support_case_connection_source_case_to_provider_account_conversation_exact_match"
    )
    reset_local_support_case_store()
    reset_local_stores()
    reset_communication360_stores()


@pytest.mark.asyncio
async def test_canonical_case_skips_communication_read_without_allowed_interaction_section():
    from datetime import datetime, timezone

    reset_local_support_case_store()
    case_repository = SupportCaseRepository()
    case_record = await case_repository.ingest_event(
        tenant_id=TENANT_A,
        connection_id="case-connection-policy",
        provider_identity="support-desk",
        connection_verified_at="2026-10-17T10:00:00Z",
        event=SupportCaseEventInput(
            source_case_id="private-source-case-policy",
            source_event_id="case-created-policy",
            event_type=SupportCaseEventType.CREATED,
            occurred_at=datetime(2026, 10, 17, 11, tzinfo=timezone.utc),
        ),
    )

    class CaseReadSpy(FakeSource):
        def __init__(self) -> None:
            super().__init__(SupportFactsRead(rows=[_row("must-not-read")], available=True))
            self.case_calls: list[tuple[str, str, str]] = []

        async def support_facts_for_case(
            self,
            tenant_id: str,
            connection_id: str,
            source_case_id: str,
            **_kwargs: Any,
        ) -> SupportFactsRead:
            self.case_calls.append((tenant_id, connection_id, source_case_id))
            return self.read

    source = CaseReadSpy()
    request = _request("support_case", case_record["case_id"]).model_copy(
        update={"includeSections": ["state"]}
    )

    result = await Support360Provider(source, case_repository=case_repository).project(
        request,
        _context(request),
    )

    state = _sections(result)["state"].content
    assert source.case_calls == []
    assert state["requiredSlots"]["conversation_history"]["state"] == "unknown"
    assert state["requiredSlots"]["conversation_history"]["entries"] is None
    assert "must-not-read" not in repr(result.model_dump())
    reset_local_support_case_store()


@pytest.mark.asyncio
async def test_support_case_resolution_joins_exact_applied_lifecycle_event_evidence() -> None:
    from datetime import datetime, timezone

    reset_local_support_case_store()
    repository = SupportCaseRepository()
    created_at = datetime(2026, 10, 17, 11, tzinfo=timezone.utc)
    resolved_at = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)
    record = await repository.ingest_event(
        tenant_id=TENANT_A,
        connection_id="support-connection-resolution",
        provider_identity="support-desk",
        connection_verified_at="2026-10-17T10:00:00Z",
        event=SupportCaseEventInput(
            source_case_id="source-case-resolution",
            source_event_id="support-case-created-resolution",
            event_type=SupportCaseEventType.CREATED,
            occurred_at=created_at,
        ),
        observed_at=created_at,
    )
    record = await repository.ingest_event(
        tenant_id=TENANT_A,
        connection_id="support-connection-resolution",
        provider_identity="support-desk",
        connection_verified_at="2026-10-17T10:00:00Z",
        event=SupportCaseEventInput(
            source_case_id="source-case-resolution",
            source_event_id="support-case-resolved-resolution",
            event_type=SupportCaseEventType.RESOLVED,
            occurred_at=resolved_at,
        ),
        observed_at=resolved_at,
    )
    request = _request("support_case", record["case_id"])

    result = await Support360Provider(
        FakeSource(SupportFactsRead(rows=[], available=True)),
        case_repository=repository,
    ).project(request, _context(request))

    sections = _sections(result)
    resolution = sections["state"].content["requiredSlots"]["resolution"]
    assert resolution["state"] == "degraded"
    assert resolution["resolutionState"] == "resolved"
    assert resolution["claimState"] == "observed"
    assert resolution["sourceOccurredAt"] == "2026-10-17T12:00:00+00:00"
    assert resolution["reasonCode"] == _REASON_SUPPORT_BUSINESS_OUTCOME_MISSING
    assert {(reference.source, reference.id) for reference in resolution["evidenceRefs"]} == {
        ("support-desk", "support-case-resolved-resolution"),
        ("provider_connections", "support-connection-resolution"),
    }
    assert result.claims[0].domainSlotIds == ["case_summary", "resolution", "evidence_trace"]
    assert sections["outcomes"].state == "unknown"
    assert sections["outcomes"].warnings == ["support_business_outcome_authority_unavailable"]
    reset_local_support_case_store()


@pytest.mark.asyncio
async def test_support_case_resolution_does_not_infer_from_event_label_without_exact_evidence() -> None:
    from datetime import datetime, timezone

    reset_local_support_case_store()
    canonical_repository = SupportCaseRepository()
    observed_at = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)
    record = await canonical_repository.ingest_event(
        tenant_id=TENANT_A,
        connection_id="support-connection-unlinked-resolution",
        provider_identity="support-desk",
        connection_verified_at="2026-10-17T10:00:00Z",
        event=SupportCaseEventInput(
            source_case_id="source-case-unlinked-resolution",
            source_event_id="support-case-created-unlinked-resolution",
            event_type=SupportCaseEventType.CREATED,
            occurred_at=observed_at,
        ),
        observed_at=observed_at,
    )
    await canonical_repository.ingest_event(
        tenant_id=TENANT_A,
        connection_id="support-connection-unlinked-resolution",
        provider_identity="support-desk",
        connection_verified_at="2026-10-17T10:00:00Z",
        event=SupportCaseEventInput(
            source_case_id="source-case-unlinked-resolution",
            source_event_id="support-case-resolved-unlinked-resolution",
            event_type=SupportCaseEventType.RESOLVED,
            occurred_at=observed_at,
        ),
        observed_at=observed_at,
    )

    class MissingEventEvidenceRepository:
        async def get_case(self, tenant_id: str, case_id: str, *, limit: int):
            read = await canonical_repository.get_case(tenant_id, case_id, limit=limit)
            events = [dict(event) for event in read.events]
            for event in events:
                if event.get("event_type") == SupportCaseEventType.RESOLVED.value:
                    event["evidence_refs"] = [
                        {
                            "id": "different-source-event",
                            "type": "event",
                            "source": "support-desk",
                            "observedAt": observed_at.isoformat(),
                            "uri": "provider-event://support-connection-unlinked-resolution/different-source-event",
                        },
                        {
                            "id": "support-connection-unlinked-resolution",
                            "type": "entity",
                            "source": "provider_connections",
                            "uri": "store://provider_connections/support-connection-unlinked-resolution",
                        },
                    ]
            return SupportCaseAuthorityRead(
                read.record,
                events,
                read.available,
                read.complete,
                expired=read.expired,
                reason=read.reason,
            )

    request = _request("support_case", record["case_id"])
    result = await Support360Provider(
        FakeSource(SupportFactsRead(rows=[], available=True)),
        case_repository=MissingEventEvidenceRepository(),
    ).project(request, _context(request))

    resolution = _sections(result)["state"].content["requiredSlots"]["resolution"]
    assert resolution["state"] == "unknown"
    assert resolution["reasonCode"] == _REASON_RESOLUTION_AUTHORITY_MISSING
    assert "evidenceRefs" not in resolution
    assert "resolution" not in result.claims[0].domainSlotIds
    reset_local_support_case_store()


class _ResolvedAgentIdentity:
    state = "resolved"
    canonical_agent_entity_id = "canonical-agent-7"
    evidence = (
        EvidenceRef(
            id="agent-binding-7",
            type="entity",
            source="agent_deployment_identity_bindings",
            observedAt="2026-10-17T11:00:00Z",
        ),
    )


class _ResolvedAgentReader:
    async def resolve(self, tenant_id: str, source_agent_ref: str):
        assert tenant_id == TENANT_A
        assert source_agent_ref == "source-agent-7"
        return _ResolvedAgentIdentity()


class _SubjectSource:
    def __init__(self, **reads: SupportFactsRead) -> None:
        self.reads = reads
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def support_facts_for_entity(self, tenant_id: str, subject_id: str, **kwargs):
        self.calls.append(("entity", (tenant_id, subject_id), kwargs))
        return self.reads["entity"]

    async def support_facts_for_agent(
        self, tenant_id: str, canonical_agent_entity_id: str, **kwargs
    ):
        self.calls.append(("agent", (tenant_id, canonical_agent_entity_id), kwargs))
        return self.reads["agent"]

    async def support_facts_for_episode(self, tenant_id: str, episode_id: str, **kwargs):
        self.calls.append(("episode", (tenant_id, episode_id), kwargs))
        return self.reads["episode"]

    async def support_facts_for_source(self, tenant_id: str, source_id: str, **kwargs):
        self.calls.append(("source", (tenant_id, source_id), kwargs))
        return self.reads["source"]


@pytest.mark.asyncio
async def test_agent_support_uses_exact_sender_binding_and_preserves_join_evidence(
    monkeypatch: pytest.MonkeyPatch,
):
    from journeys.comms.repository import CommsFactsRepository, reset_local_stores

    reset_local_stores()
    repository = CommsFactsRepository()

    async def local_pool():
        return None

    monkeypatch.setattr(repository, "_pool", local_pool)
    await repository.upsert(
        {
            **_row("agent-support-fact", tenant_id=TENANT_A),
            "source_event_id": "agent-support-event",
            "idempotency_key": "agent-support-good",
            "sender_entity_id": "canonical-agent-7",
            "sender_identity_binding_id": "agent-binding-7",
        }
    )
    await repository.upsert(
        {
            **_row("agent-unbound-fact", tenant_id=TENANT_A),
            "source_event_id": "agent-unbound-event",
            "idempotency_key": "agent-support-unbound",
            "sender_entity_id": "canonical-agent-7",
            "sender_identity_binding_id": "unverified-binding",
        }
    )
    await repository.upsert(
        {
            **_row("agent-other-tenant", tenant_id=TENANT_B),
            "source_event_id": "agent-other-tenant-event",
            "idempotency_key": "agent-support-other-tenant",
            "sender_entity_id": "canonical-agent-7",
            "sender_identity_binding_id": "agent-binding-7",
        }
    )
    source = RepositorySupport360Source(facts=repository)
    provider = Support360Provider(source, agent_identity_reader=_ResolvedAgentReader())
    request = _request("agent", "source-agent-7")

    result = await provider.project(request, _context(request))

    sections = _sections(result)
    communications = sections["state"].content["supportCommunications"]
    assert sections["timeline"].content["entryCount"] == 1
    assert sections["timeline"].content["entries"][0]["factId"] == "agent-support-fact"
    assert communications["subjectJoin"] == "sender_entity_id_and_identity_binding_id_exact_match"
    assert communications["readCompleteness"] == "complete"
    refs = sections["evidence"].content["evidenceRefs"]
    assert {(ref.source, ref.id) for ref in refs} == {
        ("agent_deployment_identity_bindings", "agent-binding-7"),
        ("services/api/journeys/comms/silver_comms_facts", "agent-support-fact"),
    }
    assert sections["summary"].content["freshness"]["state"] == "unknown"
    assert "support_agent_join_requires_bound_sender_identity_evidence" in result.degradedReasons
    reset_local_stores()


@pytest.mark.asyncio
async def test_episode_support_uses_canonical_episode_event_reference_and_tenant_scope(
    monkeypatch: pytest.MonkeyPatch,
):
    from graph.operational_intelligence.models import EntityRef
    from journeys.comms.repository import CommsFactsRepository, reset_local_stores
    from shared.backend_interpretation.primitives import EpisodeRecord

    reset_local_stores()
    repository = CommsFactsRepository()

    async def local_pool():
        return None

    monkeypatch.setattr(repository, "_pool", local_pool)
    await repository.upsert(
        {
            **_row("episode-support-fact", tenant_id=TENANT_A),
            "source_event_id": "episode-support-event",
            "idempotency_key": "episode-support-good",
        }
    )
    await repository.upsert(
        {
            **_row("episode-other-tenant", tenant_id=TENANT_B),
            "source_event_id": "episode-support-event",
            "idempotency_key": "episode-support-other-tenant",
        }
    )
    episode = EpisodeRecord(
        episode_id="episode-support-1",
        tenant_id=TENANT_A,
        subject=EntityRef(kind="user", id=ENTITY_ID),
        kind="support",
        source_event_id="episode-support-event",
        evidence_refs=[
            EvidenceRef(
                id="episode-support-fact",
                type="event",
                source="services/api/journeys/comms/silver_comms_facts",
                uri="store://silver_comms_facts/episode-support-fact",
                observedAt="2026-10-17T12:00:00Z",
            )
        ],
    )

    class EpisodeStore:
        async def get(self, tenant_id: str, episode_id: str):
            assert (tenant_id, episode_id) == (TENANT_A, "episode-support-1")
            return episode

    source = RepositorySupport360Source(facts=repository, episodes=EpisodeStore())
    request = _request("episode", "episode-support-1")
    result = await Support360Provider(source).project(request, _context(request))

    sections = _sections(result)
    state = sections["state"].content["supportCommunications"]
    assert state["subjectJoin"] == "episode_record_event_evidence_exact_match"
    assert state["joinState"] == "resolved"
    assert sections["timeline"].content["entryCount"] == 1
    evidence = sections["evidence"].content["evidenceRefs"]
    assert {ref.id for ref in evidence} == {
        "episode-support-1",
        "episode-support-fact",
        "episode-support-event",
    }
    assert {ref.source for ref in evidence} >= {
        "shared.backend_interpretation.stores.EpisodeStore",
        "services/api/journeys/comms/silver_comms_facts",
    }
    assert sections["summary"].content["freshness"]["newestObservedAt"] == "2026-10-17T12:00:01Z"
    reset_local_stores()


@pytest.mark.asyncio
async def test_source_support_uses_current_tenant_provider_connection_join(
    monkeypatch: pytest.MonkeyPatch,
):
    from journeys.comms.repository import CommsFactsRepository, reset_local_stores

    reset_local_stores()
    repository = CommsFactsRepository()

    async def local_pool():
        return None

    monkeypatch.setattr(repository, "_pool", local_pool)
    await repository.upsert(
        {
            **_row("source-support-fact", tenant_id=TENANT_A),
            "source_event_id": "source-support-event",
            "idempotency_key": "source-support-good",
            "source_connector_id": "connection-a",
        }
    )
    await repository.upsert(
        {
            **_row("source-other-connection", tenant_id=TENANT_A),
            "source_event_id": "source-other-connection-event",
            "idempotency_key": "source-support-other-connection",
            "source_connector_id": "connection-b",
        }
    )

    class Connections:
        async def find_many(self, *, filters, sort_by, sort_order, limit):
            assert filters == {"tenant_id": TENANT_A, "provider_identity": "crm-source"}
            assert (sort_by, sort_order, limit) == ("created_at", "desc", 101)
            return [
                {
                    "tenant_id": TENANT_A,
                    "connection_id": "connection-a",
                    "provider_identity": "crm-source",
                    "created_at": "2026-10-16T12:00:00Z",
                    "updated_at": "2026-10-17T12:00:00Z",
                },
            ]

    source = RepositorySupport360Source(facts=repository, connections=Connections())
    request = _request("source", "crm-source")
    result = await Support360Provider(source).project(request, _context(request))

    sections = _sections(result)
    assert sections["timeline"].content["entryCount"] == 1
    assert sections["timeline"].content["entries"][0]["factId"] == "source-support-fact"
    state = sections["state"].content["supportCommunications"]
    assert (
        state["subjectJoin"] == "provider_identity_to_connection_to_source_connector_id_exact_match"
    )
    assert state["readCompleteness"] == "partial"
    refs = sections["evidence"].content["evidenceRefs"]
    assert {ref.id for ref in refs} == {"connection-a", "source-support-fact"}
    assert {ref.source for ref in refs} == {
        "provider_connections",
        "services/api/journeys/comms/silver_comms_facts",
    }
    assert (
        "support_source_join_uses_current_provider_connection_membership" in result.degradedReasons
    )

    class CrossTenantConnections(Connections):
        async def find_many(self, *, filters, sort_by, sort_order, limit):
            return [
                {
                    "tenant_id": TENANT_B,
                    "connection_id": "connection-foreign",
                    "provider_identity": "crm-source",
                }
            ]

    isolated_source = RepositorySupport360Source(
        facts=repository,
        connections=CrossTenantConnections(),
    )
    isolated_result = await Support360Provider(isolated_source).project(
        request,
        _context(request),
    )
    isolated_sections = _sections(isolated_result)
    assert isolated_sections["summary"].state == "unknown"
    assert isolated_sections["timeline"].content is None
    assert "support_source_connection_tenant_scope_mismatch" in isolated_result.degradedReasons
    reset_local_stores()


@pytest.mark.asyncio
async def test_source_failure_is_unknown_without_leaking_exception_details() -> None:
    source = FakeSource(
        SupportFactsRead(
            rows=[],
            available=False,
            reason="database password must not be emitted",
        )
    )
    request = _request()

    result = await Support360Provider(source).project(request, _context(request))

    sections = _sections(result)
    assert result.degradedReasons == [_REASON_SOURCE_UNAVAILABLE, _REASON_PARTIAL_ENTITY_JOIN]
    assert sections["summary"].state == "unknown"
    assert sections["summary"].content is None
    assert sections["state"].content["supportCommunications"]["state"] == "unknown"
    assert "password" not in repr(result.model_dump()).lower()


@pytest.mark.asyncio
async def test_repository_source_uses_exact_tenant_entity_and_support_filter(monkeypatch) -> None:
    from journeys.comms.repository import CommsFactsRepository

    calls: list[tuple[Any, ...]] = []

    async def list_for_entity(self, tenant_id, entity_id, **kwargs):
        calls.append((tenant_id, entity_id, kwargs))
        return [_row("source-row")], None

    monkeypatch.setattr(CommsFactsRepository, "list_for_entity", list_for_entity)
    read = await RepositorySupport360Source().support_facts_for_entity(
        TENANT_A,
        ENTITY_ID,
        limit=17,
        after="2026-10-17T12:00:00+00:00",
        before="2026-10-18T12:00:00+00:00",
        cursor="cursor-1",
    )

    assert read.available is True
    assert read.truncated is False
    assert calls == [
        (
            TENANT_A,
            ENTITY_ID,
            {
                "category": "support",
                "after": "2026-10-17T12:00:00+00:00",
                "before": "2026-10-18T12:00:00+00:00",
                "limit": 17,
                "cursor": "cursor-1",
            },
        )
    ]


@pytest.mark.asyncio
async def test_communication_repository_case_read_uses_exact_scope_predicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from journeys.comms.repository import CommsFactsRepository

    class Connection:
        query = ""
        params: tuple[Any, ...] = ()

        async def fetch(self, query: str, *params: Any):
            self.query = query
            self.params = params
            return []

    class Acquire:
        def __init__(self, connection: Connection) -> None:
            self.connection = connection

        async def __aenter__(self) -> Connection:
            return self.connection

        async def __aexit__(self, *_args: Any) -> None:
            return None

    connection = Connection()

    class Pool:
        def acquire(self) -> Acquire:
            return Acquire(connection)

    async def get_pool_for_test():
        return Pool()

    repository = CommsFactsRepository()
    monkeypatch.setattr(repository, "_pool", get_pool_for_test)

    rows, next_cursor = await repository.list_for_support_case(
        TENANT_A,
        "case-connection-a",
        "private-source-case-a",
        category="support",
        after="2026-10-17T11:00:00Z",
        before="2026-10-17T13:00:00Z",
        limit=17,
    )

    assert rows == []
    assert next_cursor is None
    assert "tenant_id = $1" in connection.query
    assert "source_connector_id = $2" in connection.query
    assert "support_case_id = $3" in connection.query
    assert "message_category = $4" in connection.query
    assert connection.params[:4] == (
        TENANT_A,
        "case-connection-a",
        "private-source-case-a",
        "support",
    )
    assert connection.params[4].isoformat() == "2026-10-17T11:00:00+00:00"
    assert connection.params[5].isoformat() == "2026-10-17T13:00:00+00:00"
    assert "LIMIT 18" in connection.query


def test_support360_is_an_in_flight_projection_id_when_contract_is_generated() -> None:
    from shared.intelligence_projections.generated_registry import (
        INTELLIGENCE_PROJECTION_DEFINITIONS,
    )

    definition = INTELLIGENCE_PROJECTION_DEFINITIONS[PROJECTION_ID]
    assert definition["implementationState"] == "in_flight"
    assert set(definition["outputSections"]) == set(OUTPUT_SECTIONS)
    assert len(definition["outputSections"]) == len(OUTPUT_SECTIONS)
    registry = ProviderRegistry()
    from journeys.support360.provider import register_provider

    register_provider(registry)
    assert registry.get(PROJECTION_ID) is not None
    assert registry.availability()[PROJECTION_ID]["registryState"] == "in_flight"
    assert INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION
