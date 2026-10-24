"""Focused contract tests for Support360 callback authority and projection joins."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from journeys.support360.callbacks import (  # noqa: E402
    SupportCallbackAuthorityError,
    SupportCallbackEventInput,
    SupportCallbackEventType,
    SupportCallbackIngestionService,
    SupportCallbackNotFound,
    SupportCallbackRead,
    SupportCallbackRepository,
    SupportCallbackTransitionError,
    reset_local_support_callback_store,
)
from journeys.support360.cases import (  # noqa: E402
    SupportCaseEventInput,
    SupportCaseEventType,
    SupportCaseIngestionService,
    SupportCaseRepository,
    reset_local_support_case_store,
)
from journeys.support360.provider import Support360Provider, SupportFactsRead  # noqa: E402
from shared.intelligence_projections import (  # noqa: E402
    ProjectionContext,
    ProjectionRequest,
    ProjectionSubject,
)

TENANT_A = "tenant-callback-a"
TENANT_B = "tenant-callback-b"
CONNECTION_A = "connection-callback-a"
CONNECTION_B = "connection-callback-b"
NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


class FakeConnections:
    def __init__(self, rows: dict[str, SimpleNamespace]) -> None:
        self.rows = rows

    async def find(self, connection_id: str):
        return self.rows.get(connection_id)


class EmptyCommsSource:
    async def support_facts_for_case(
        self,
        tenant_id: str,
        connection_id: str,
        source_case_id: str,
        *,
        limit: int,
        after: str | None = None,
        before: str | None = None,
        cursor: str | None = None,
    ) -> SupportFactsRead:
        return SupportFactsRead(
            rows=[],
            available=True,
            complete=True,
            subject_join="support_case_connection_and_source_case_id_exact_match",
            canonical_authority_refs=("communication_facts", "support_cases", "evidence"),
        )


def _connection(
    tenant_id: str = TENANT_A,
    connection_id: str = CONNECTION_A,
    *,
    state: str = "verified",
    provider_identity: str = "desk-provider",
) -> SimpleNamespace:
    return SimpleNamespace(
        tenant_id=tenant_id,
        connection_id=connection_id,
        provider_identity=provider_identity,
        state=state,
        last_verified_at="2026-10-20T12:00:00Z",
    )


def _case_event(event_id: str = "case-source-created") -> SupportCaseEventInput:
    return SupportCaseEventInput(
        source_case_id="source-case-88",
        source_event_id=event_id,
        event_type=SupportCaseEventType.CREATED,
        occurred_at=NOW,
    )


def _callback_event(
    event_id: str,
    event_type: SupportCallbackEventType,
    case_id: str,
    *,
    source_callback_id: str = "source-callback-3",
    occurred_at: datetime = NOW + timedelta(minutes=1),
    scheduled_for: datetime | None = None,
) -> SupportCallbackEventInput:
    return SupportCallbackEventInput(
        case_id=case_id,
        source_callback_id=source_callback_id,
        source_event_id=event_id,
        event_type=event_type,
        occurred_at=occurred_at,
        scheduled_for=scheduled_for,
    )


async def _case_and_service(*, connection: SimpleNamespace | None = None):
    case_repo = SupportCaseRepository()
    connection = connection or _connection()
    connections = FakeConnections({connection.connection_id: connection})
    case_service = SupportCaseIngestionService(cases=case_repo, connections=connections)
    case = await case_service.ingest(
        connection.tenant_id,
        connection.connection_id,
        _case_event(),
    )
    callback_repo = SupportCallbackRepository()
    callback_service = SupportCallbackIngestionService(
        callbacks=callback_repo,
        cases=case_repo,
        connections=connections,
    )
    return case_repo, callback_repo, callback_service, case


@pytest.fixture(autouse=True)
def clear_local_authorities():
    reset_local_support_case_store()
    reset_local_support_callback_store()
    yield
    reset_local_support_case_store()
    reset_local_support_callback_store()


def test_schedule_events_require_explicit_offset_aware_schedule_time() -> None:
    case_id = "d4a7decc-e391-4e84-bd70-f1a14c9ec047"
    with pytest.raises(ValidationError, match="scheduled_for is required"):
        _callback_event("event-1", SupportCallbackEventType.SCHEDULED, case_id)
    with pytest.raises(ValidationError, match="timezone"):
        _callback_event(
            "event-2",
            SupportCallbackEventType.SCHEDULED,
            case_id,
            scheduled_for=datetime(2026, 10, 22, 12),
        )


@pytest.mark.asyncio
async def test_schedule_execution_is_append_only_idempotent_and_case_provider_scoped() -> None:
    case_repo, callback_repo, service, case = await _case_and_service()
    scheduled = _callback_event(
        "callback-scheduled-1",
        SupportCallbackEventType.SCHEDULED,
        case["case_id"],
        scheduled_for=NOW + timedelta(minutes=30),
    )
    initial = await service.ingest(TENANT_A, CONNECTION_A, scheduled)
    replay = await service.ingest(TENANT_A, CONNECTION_A, scheduled)
    attempted = await service.ingest(
        TENANT_A,
        CONNECTION_A,
        _callback_event(
            "callback-attempt-1",
            SupportCallbackEventType.ATTEMPTED,
            case["case_id"],
            occurred_at=NOW + timedelta(minutes=5),
        ),
    )
    completed = await service.ingest(
        TENANT_A,
        CONNECTION_A,
        _callback_event(
            "callback-complete-1",
            SupportCallbackEventType.COMPLETED,
            case["case_id"],
            occurred_at=NOW + timedelta(minutes=10),
        ),
    )

    assert initial["callback_id"] == replay["callback_id"] == attempted["callback_id"]
    assert completed["callback_state"] == "completed"
    assert completed["event_count"] == 3
    case_read = await case_repo.get_case(TENANT_A, case["case_id"])
    case_event = next(
        row for row in case_read.events if row["source_event_id"] == "case-source-created"
    )
    assert case_event["event_type"] == SupportCaseEventType.CREATED.value
    read = await callback_repo.list_for_case(TENANT_A, case["case_id"], now=NOW + timedelta(days=1))
    assert read.available and read.complete and len(read.callbacks) == 1
    callback = read.callbacks[0]
    assert callback["callback_id"] == completed["callback_id"]
    assert [row["event_type"] for row in callback["events"]] == [
        SupportCallbackEventType.COMPLETED.value,
        SupportCallbackEventType.ATTEMPTED.value,
        SupportCallbackEventType.SCHEDULED.value,
    ]
    refs = callback["events"][0]["evidence_refs"]
    assert {ref["source"] for ref in refs} == {
        "desk-provider",
        "provider_connections",
        "support_callbacks",
        "support_cases",
    }
    assert {ref["id"] for ref in refs} >= {
        completed["callback_id"],
        case["case_id"],
        "case-source-created",
        "callback-complete-1",
        CONNECTION_A,
    }
    assert await callback_repo.list_for_case(
        TENANT_B, case["case_id"], now=NOW + timedelta(days=1)
    ) == type(read)([], True, True)


@pytest.mark.asyncio
async def test_stale_event_is_retained_without_reverting_current_callback_state() -> None:
    _case_repo, callback_repo, service, case = await _case_and_service()
    await service.ingest(
        TENANT_A,
        CONNECTION_A,
        _callback_event(
            "schedule",
            SupportCallbackEventType.SCHEDULED,
            case["case_id"],
            scheduled_for=NOW + timedelta(minutes=30),
        ),
    )
    completed = await service.ingest(
        TENANT_A,
        CONNECTION_A,
        _callback_event(
            "complete",
            SupportCallbackEventType.COMPLETED,
            case["case_id"],
            occurred_at=NOW + timedelta(minutes=3),
        ),
    )
    stale = await service.ingest(
        TENANT_A,
        CONNECTION_A,
        _callback_event(
            "late-old-attempt",
            SupportCallbackEventType.ATTEMPTED,
            case["case_id"],
            occurred_at=NOW + timedelta(minutes=2),
        ),
    )
    read = await callback_repo.list_for_case(TENANT_A, case["case_id"], now=NOW + timedelta(days=1))
    events = read.callbacks[0]["events"]
    stale_row = next(event for event in events if event["source_event_id"] == "late-old-attempt")
    assert stale["callback_state"] == completed["callback_state"] == "completed"
    assert stale_row["state_applied"] is False
    assert read.callbacks[0]["event_count"] == 3


@pytest.mark.asyncio
async def test_invalid_transition_and_event_id_reuse_are_rejected() -> None:
    _case_repo, _callback_repo, service, case = await _case_and_service()
    await service.ingest(
        TENANT_A,
        CONNECTION_A,
        _callback_event(
            "schedule",
            SupportCallbackEventType.SCHEDULED,
            case["case_id"],
            scheduled_for=NOW + timedelta(minutes=30),
        ),
    )
    await service.ingest(
        TENANT_A,
        CONNECTION_A,
        _callback_event("complete", SupportCallbackEventType.COMPLETED, case["case_id"]),
    )
    with pytest.raises(SupportCallbackTransitionError):
        await service.ingest(
            TENANT_A,
            CONNECTION_A,
            _callback_event(
                "after-terminal",
                SupportCallbackEventType.ATTEMPTED,
                case["case_id"],
                occurred_at=NOW + timedelta(minutes=2),
            ),
        )
    with pytest.raises(SupportCallbackAuthorityError, match="replay payload"):
        await service.ingest(
            TENANT_A,
            CONNECTION_A,
            _callback_event(
                "complete",
                SupportCallbackEventType.COMPLETED,
                case["case_id"],
                occurred_at=NOW + timedelta(minutes=3),
            ),
        )


@pytest.mark.asyncio
async def test_connection_cannot_attach_callback_to_other_tenant_or_provider_case() -> None:
    case_repo, callback_repo, service, case = await _case_and_service()
    other_connection = _connection(
        tenant_id=TENANT_A,
        connection_id="another-connection",
        provider_identity="other-provider",
    )
    other_service = SupportCallbackIngestionService(
        callbacks=callback_repo,
        cases=case_repo,
        connections=FakeConnections({other_connection.connection_id: other_connection}),
    )
    with pytest.raises(SupportCallbackAuthorityError, match="canonical support case"):
        await other_service.ingest(
            TENANT_A,
            other_connection.connection_id,
            _callback_event(
                "schedule-wrong-provider",
                SupportCallbackEventType.SCHEDULED,
                case["case_id"],
                scheduled_for=NOW + timedelta(minutes=30),
            ),
        )
    with pytest.raises(SupportCallbackAuthorityError, match="verified tenant provider connection"):
        await service.ingest(
            TENANT_B,
            CONNECTION_A,
            _callback_event(
                "schedule-wrong-tenant",
                SupportCallbackEventType.SCHEDULED,
                case["case_id"],
                scheduled_for=NOW + timedelta(minutes=30),
            ),
        )


def _request(subject_kind: str, subject_id: str, tenant_id: str = TENANT_A) -> ProjectionRequest:
    return ProjectionRequest(
        projectionId="support360",
        tenantId=tenant_id,
        subject=ProjectionSubject(kind=subject_kind, id=subject_id),
    )


def _context(request: ProjectionRequest) -> ProjectionContext:
    return ProjectionContext(
        projectionId="support360",
        tenantId=request.tenantId,
        registryState="in_flight",
        dependencyState=[],
        warnings=[],
    )


@pytest.mark.asyncio
async def test_callback_ingest_route_requires_tenant_write_permission(monkeypatch) -> None:
    from fastapi import Request

    from shared.auth.auth import Permissions
    from shared.common.common import ForbiddenError
    from journeys.support360 import routes

    received: list[tuple[str, str, SupportCallbackEventInput]] = []

    class CapturingIngestionService:
        async def ingest(
            self, tenant_id: str, connection_id: str, event: SupportCallbackEventInput
        ):
            received.append((tenant_id, connection_id, event))
            return {
                "callback_id": "canonical-callback",
                "case_id": event.case_id,
                "callback_state": "scheduled",
                "scheduled_for": NOW + timedelta(minutes=30),
                "last_observed_at": NOW,
                "retention_expires_at": NOW + timedelta(days=365),
            }

    monkeypatch.setattr(routes, "SupportCallbackIngestionService", CapturingIngestionService)

    def request_for(permissions: set[str]) -> Request:
        request = Request(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": "/v1/support/cases/callbacks/ingest",
                "raw_path": b"/v1/support/cases/callbacks/ingest",
                "query_string": b"",
                "headers": [],
                "client": ("test", 1),
                "server": ("test", 80),
            }
        )

        def require_permission(permission: str) -> None:
            if permission not in permissions:
                raise ForbiddenError("missing write permission")

        request.state.tenant = SimpleNamespace(
            tenant_id=TENANT_A,
            require_permission=require_permission,
        )
        return request

    body = routes.SupportCallbackIngestBody(
        connection_id=CONNECTION_A,
        case_id="d4a7decc-e391-4e84-bd70-f1a14c9ec047",
        source_callback_id="source-callback-route",
        source_event_id="callback-route-event",
        event_type=SupportCallbackEventType.SCHEDULED,
        occurred_at=NOW,
        scheduled_for=NOW + timedelta(minutes=30),
    )
    response = await routes.ingest_support_callback_event(
        request_for({Permissions.WRITE}),
        body,
    )

    assert response["data"]["accepted"] is True
    assert response["data"]["callback_id"] == "canonical-callback"
    assert received[0][0:2] == (TENANT_A, CONNECTION_A)
    with pytest.raises(ForbiddenError):
        await routes.ingest_support_callback_event(request_for({Permissions.READ}), body)
    assert len(received) == 1


@pytest.mark.asyncio
async def test_support_case_and_callback_subjects_project_exact_schedule_execution_evidence() -> (
    None
):
    case_repo, callback_repo, service, case = await _case_and_service()
    await service.ingest(
        TENANT_A,
        CONNECTION_A,
        _callback_event(
            "schedule",
            SupportCallbackEventType.SCHEDULED,
            case["case_id"],
            scheduled_for=NOW + timedelta(minutes=30),
        ),
    )
    callback = await service.ingest(
        TENANT_A,
        CONNECTION_A,
        _callback_event("attempt", SupportCallbackEventType.ATTEMPTED, case["case_id"]),
    )
    provider = Support360Provider(
        source=EmptyCommsSource(),
        case_repository=case_repo,
        callback_repository=callback_repo,
    )

    case_request = _request("support_case", case["case_id"])
    case_result = await provider.project(case_request, _context(case_request))
    case_slots = next(section for section in case_result.sections if section.id == "state").content[
        "requiredSlots"
    ]
    callback_slot = case_slots["callbacks"]
    assert callback_slot["state"] == "degraded"
    assert callback_slot["sourceHistoryComplete"] is False
    assert callback_slot["freshness"]["state"] == "unknown"
    assert callback_slot["readCompleteness"] == "complete_current_store_read"
    assert callback_slot["callbacks"][0]["callbackId"] == callback["callback_id"]
    assert callback_slot["callbacks"][0]["canonicalCaseId"] == case["case_id"]
    assert any(
        claim.domainSlotIds == ["callbacks", "evidence_trace"] for claim in case_result.claims
    )

    callback_request = _request("callback", callback["callback_id"])
    callback_result = await provider.project(callback_request, _context(callback_request))
    callback_state = next(
        section for section in callback_result.sections if section.id == "state"
    ).content
    assert (
        callback_state["requiredSlots"]["callbacks"]["callbacks"][0]["callbackId"]
        == callback["callback_id"]
    )
    assert callback_result.claims[0].subject.kind == "callback"
    assert "support_callback_source_history_coverage_unverified" in callback_result.degradedReasons


@pytest.mark.asyncio
async def test_callback_provider_scope_mismatch_returns_unknown_without_callback_values() -> None:
    case_repo, callback_repo, service, case = await _case_and_service()
    callback = await service.ingest(
        TENANT_A,
        CONNECTION_A,
        _callback_event(
            "schedule",
            SupportCallbackEventType.SCHEDULED,
            case["case_id"],
            scheduled_for=NOW + timedelta(minutes=30),
        ),
    )

    class CrossTenantCallbacks(SupportCallbackRepository):
        async def get_callback(
            self, tenant_id: str, callback_id: str, *, limit: int = 50, now=None
        ):
            result = await super().get_callback(tenant_id, callback_id, limit=limit, now=now)
            if result.record is not None:
                return result.__class__(
                    {**result.record, "tenant_id": TENANT_B},
                    result.events,
                    result.available,
                    result.complete,
                    result.expired,
                    result.reason,
                    result.scope_known,
                )
            return result

    provider = Support360Provider(
        source=EmptyCommsSource(),
        case_repository=case_repo,
        callback_repository=CrossTenantCallbacks(),
    )
    request = _request("callback", callback["callback_id"])
    result = await provider.project(request, _context(request))
    required_slots = next(section for section in result.sections if section.id == "state").content[
        "requiredSlots"
    ]
    assert required_slots["callbacks"]["state"] == "unknown"
    assert (
        required_slots["callbacks"]["reasonCode"]
        == "support_callback_tenant_case_provider_scope_mismatch"
    )
    assert required_slots["callbacks"].get("callbacks") is None


@pytest.mark.asyncio
async def test_callback_provider_rejects_case_event_id_without_matching_receipt() -> None:
    case_repo, callback_repo, service, case = await _case_and_service()
    callback = await service.ingest(
        TENANT_A,
        CONNECTION_A,
        _callback_event(
            "schedule",
            SupportCallbackEventType.SCHEDULED,
            case["case_id"],
            scheduled_for=NOW + timedelta(minutes=30),
        ),
    )

    class OrphanCaseEventRepository(SupportCallbackRepository):
        async def get_callback(
            self, tenant_id: str, callback_id: str, *, limit: int = 50, now=None
        ):
            read = await super().get_callback(tenant_id, callback_id, limit=limit, now=now)
            if not read.record or not read.events:
                return read
            event = dict(read.events[0])
            event["case_source_event_id"] = "orphan-case-event"
            return SupportCallbackRead(
                read.record,
                [event, *read.events[1:]],
                read.available,
                read.complete,
                read.expired,
                read.reason,
                read.scope_known,
            )

    provider = Support360Provider(
        source=EmptyCommsSource(),
        case_repository=case_repo,
        callback_repository=OrphanCaseEventRepository(),
    )
    request = _request("callback", callback["callback_id"])
    result = await provider.project(request, _context(request))

    assert result.sections[0].state == "unknown"
    assert result.degradedReasons == ["support_callback_event_evidence_unavailable"]
