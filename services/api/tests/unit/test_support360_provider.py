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
    RepositorySupport360Source,
    Support360Provider,
    SupportFactsRead,
    _REASON_CASE_AUTHORITY_MISSING,
    _REASON_JOURNEY_JOIN_MISSING,
    _REASON_PARTIAL_ENTITY_JOIN,
    _REASON_SOURCE_UNAVAILABLE,
    _REASON_UNSUPPORTED_SUBJECT,
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
    assert source.calls == [
        (TENANT_A, ENTITY_ID, None, None, "incoming-page-token", 1)
    ]


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
    source_refs = sections["timeline"].content["entries"]
    assert source_refs[0]["sourceReportedSupportCaseRef"] == "case:source-42"
    assert source_refs[0]["canonicalSupportCaseResolved"] is False
    assert source_refs[1]["sourceReportedSupportCaseRef"] is None
    assert state["journeyLinkage"]["state"] == "unknown"
    assert state["journeyLinkage"]["reasonCode"] == _REASON_JOURNEY_JOIN_MISSING
    assert sections["outcomes"].content is None
    assert sections["state"].content["measuredOutcomes"]["state"] == "unknown"


@pytest.mark.parametrize("subject_kind", ["agent", "episode", "source"])
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
    assert source.calls == []


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
