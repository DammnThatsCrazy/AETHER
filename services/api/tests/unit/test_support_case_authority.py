"""Focused tests for durable tenant-scoped support case lifecycle authority."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from journeys.support360.cases import (  # noqa: E402
    SupportCaseAuthorityError,
    SupportCaseEventInput,
    SupportCaseEventType,
    SupportCaseIngestionService,
    SupportCaseLifecycle,
    SupportCaseNotFound,
    SupportCaseRepository,
    SupportCaseTransitionError,
    reset_local_support_case_store,
    _row_dict,
)

TENANT_A = "tenant-support-a"
TENANT_B = "tenant-support-b"
CONNECTION_A = "connection-support-a"
CONNECTION_B = "connection-support-b"
VERIFIED_AT = "2026-10-20T12:00:00Z"
OBSERVED_AT = datetime(2026, 10, 20, 12, 5, tzinfo=timezone.utc)


class FakeConnections:
    def __init__(self, rows: dict[str, SimpleNamespace]) -> None:
        self.rows = rows

    async def find(self, connection_id: str):
        return self.rows.get(connection_id)


def _connection(
    tenant_id: str = TENANT_A,
    *,
    state: str = "verified",
    provider_identity: str = "support-desk",
) -> SimpleNamespace:
    return SimpleNamespace(
        tenant_id=tenant_id,
        connection_id=CONNECTION_A if tenant_id == TENANT_A else CONNECTION_B,
        provider_identity=provider_identity,
        state=state,
        last_verified_at=VERIFIED_AT,
    )


def _event(
    event_id: str,
    event_type: SupportCaseEventType,
    *,
    source_case_id: str = "external-case-77",
    occurred_at: datetime = OBSERVED_AT,
) -> SupportCaseEventInput:
    return SupportCaseEventInput(
        source_case_id=source_case_id,
        source_event_id=event_id,
        event_type=event_type,
        occurred_at=occurred_at,
    )


@pytest.fixture(autouse=True)
def clear_case_store():
    reset_local_support_case_store()
    yield
    reset_local_support_case_store()


@pytest.mark.asyncio
async def test_ingest_mints_tenant_case_id_and_replays_lifecycle_events_idempotently() -> None:
    repo = SupportCaseRepository()
    service = SupportCaseIngestionService(
        cases=repo,
        connections=FakeConnections({CONNECTION_A: _connection()}),
    )

    created = await service.ingest(
        TENANT_A,
        CONNECTION_A,
        _event("event-create-1", SupportCaseEventType.CREATED),
    )
    replayed_create = await service.ingest(
        TENANT_A,
        CONNECTION_A,
        _event("event-create-1", SupportCaseEventType.CREATED),
    )
    resolved = await service.ingest(
        TENANT_A,
        CONNECTION_A,
        _event(
            "event-resolve-1",
            SupportCaseEventType.RESOLVED,
            occurred_at=OBSERVED_AT + timedelta(minutes=2),
        ),
    )
    replayed_resolve = await service.ingest(
        TENANT_A,
        CONNECTION_A,
        _event(
            "event-resolve-1",
            SupportCaseEventType.RESOLVED,
            occurred_at=OBSERVED_AT + timedelta(minutes=2),
        ),
    )
    reopened = await service.ingest(
        TENANT_A,
        CONNECTION_A,
        _event(
            "event-reopen-1",
            SupportCaseEventType.REOPENED,
            occurred_at=OBSERVED_AT + timedelta(minutes=4),
        ),
    )

    assert created["case_id"] != "external-case-77"
    assert created["case_id"] == replayed_create["case_id"] == resolved["case_id"]
    assert resolved["lifecycle_state"] == SupportCaseLifecycle.RESOLVED.value
    assert replayed_resolve["lifecycle_state"] == SupportCaseLifecycle.RESOLVED.value
    assert reopened["lifecycle_state"] == SupportCaseLifecycle.OPEN.value
    assert reopened["resolved_at"] is None
    assert reopened["source_case_id"] == "external-case-77"
    assert reopened["source_provider_identity"] == "support-desk"
    assert reopened["retention_class"] == "standard"
    expiry = datetime.fromisoformat(reopened["retention_expires_at"])
    last_observation = datetime.fromisoformat(reopened["last_observed_at"])
    assert expiry - last_observation == timedelta(days=repo.retention_policy()[1])

    read = await repo.get_case(TENANT_A, created["case_id"])
    assert read.available is True
    assert read.complete is True
    assert read.record["lifecycle_state"] == "open"
    assert len(read.events) == 3
    evidence = read.events[0]["evidence_refs"]
    assert {item["source"] for item in evidence} == {
        "support-desk",
        "provider_connections",
    }
    assert {item["id"] for item in evidence} == {"event-reopen-1", CONNECTION_A}


@pytest.mark.asyncio
async def test_same_external_case_id_isolated_by_tenant_and_connection() -> None:
    service = SupportCaseIngestionService(
        cases=SupportCaseRepository(),
        connections=FakeConnections(
            {
                CONNECTION_A: _connection(TENANT_A),
                CONNECTION_B: _connection(TENANT_B),
            }
        ),
    )

    first = await service.ingest(
        TENANT_A,
        CONNECTION_A,
        _event("tenant-a-event", SupportCaseEventType.CREATED),
    )
    second = await service.ingest(
        TENANT_B,
        CONNECTION_B,
        _event("tenant-b-event", SupportCaseEventType.CREATED),
    )

    assert first["case_id"] != second["case_id"]
    assert await SupportCaseRepository().get_case(TENANT_A, second["case_id"]) == read_unknown()


def read_unknown():
    from journeys.support360.cases import SupportCaseAuthorityRead

    return SupportCaseAuthorityRead(None, [], True, True)


@pytest.mark.asyncio
async def test_connection_must_be_verified_and_owned_by_request_tenant() -> None:
    unverified = _connection(state="available")
    wrong_tenant = _connection(TENANT_B)
    service = SupportCaseIngestionService(
        cases=SupportCaseRepository(),
        connections=FakeConnections(
            {
                "connection-unverified": unverified,
                CONNECTION_B: wrong_tenant,
            }
        ),
    )

    for tenant_id, connection_id in (
        (TENANT_A, "connection-unverified"),
        (TENANT_A, CONNECTION_B),
    ):
        with pytest.raises(SupportCaseAuthorityError):
            await service.ingest(
                tenant_id,
                connection_id,
                _event("rejected-event", SupportCaseEventType.CREATED),
            )


@pytest.mark.asyncio
async def test_source_event_replay_collision_across_cases_is_rejected() -> None:
    service = SupportCaseIngestionService(
        cases=SupportCaseRepository(),
        connections=FakeConnections({CONNECTION_A: _connection()}),
    )
    await service.ingest(
        TENANT_A,
        CONNECTION_A,
        _event("reused-event", SupportCaseEventType.CREATED, source_case_id="case-one"),
    )

    with pytest.raises(SupportCaseAuthorityError):
        await service.ingest(
            TENANT_A,
            CONNECTION_A,
            _event("reused-event", SupportCaseEventType.CREATED, source_case_id="case-two"),
        )


@pytest.mark.asyncio
async def test_same_case_event_id_replay_rejects_changed_event_payload() -> None:
    repo = SupportCaseRepository()
    service = SupportCaseIngestionService(
        cases=repo,
        connections=FakeConnections({CONNECTION_A: _connection()}),
    )
    created = await service.ingest(
        TENANT_A,
        CONNECTION_A,
        _event("immutable-event-id", SupportCaseEventType.CREATED),
    )

    with pytest.raises(SupportCaseAuthorityError, match="replay payload does not match"):
        await service.ingest(
            TENANT_A,
            CONNECTION_A,
            _event(
                "immutable-event-id",
                SupportCaseEventType.RESOLVED,
                occurred_at=OBSERVED_AT + timedelta(minutes=1),
            ),
        )

    read = await repo.get_case(TENANT_A, created["case_id"])
    assert read.record["lifecycle_state"] == SupportCaseLifecycle.OPEN.value
    assert len(read.events) == 1


@pytest.mark.asyncio
async def test_update_event_refreshes_observed_lifecycle_without_changing_state() -> None:
    repo = SupportCaseRepository()
    service = SupportCaseIngestionService(
        cases=repo,
        connections=FakeConnections({CONNECTION_A: _connection()}),
    )
    created = await service.ingest(
        TENANT_A,
        CONNECTION_A,
        _event("event-create", SupportCaseEventType.CREATED),
    )
    updated = await service.ingest(
        TENANT_A,
        CONNECTION_A,
        _event(
            "event-update",
            SupportCaseEventType.UPDATED,
            occurred_at=OBSERVED_AT + timedelta(minutes=2),
        ),
    )

    assert updated["case_id"] == created["case_id"]
    assert updated["lifecycle_state"] == SupportCaseLifecycle.OPEN.value
    assert updated["lifecycle_observed_at"] == (
        OBSERVED_AT + timedelta(minutes=2)
    ).isoformat()
    assert updated["last_source_event_id"] == "event-update"


@pytest.mark.asyncio
async def test_out_of_order_lifecycle_observation_is_retained_but_not_applied() -> None:
    repo = SupportCaseRepository()
    service = SupportCaseIngestionService(
        cases=repo,
        connections=FakeConnections({CONNECTION_A: _connection()}),
    )
    created = await service.ingest(
        TENANT_A,
        CONNECTION_A,
        _event("event-create", SupportCaseEventType.CREATED),
    )
    resolved = await service.ingest(
        TENANT_A,
        CONNECTION_A,
        _event(
            "event-resolve",
            SupportCaseEventType.RESOLVED,
            occurred_at=OBSERVED_AT + timedelta(minutes=5),
        ),
    )
    delayed_escalation = await service.ingest(
        TENANT_A,
        CONNECTION_A,
        _event(
            "event-delayed-escalate",
            SupportCaseEventType.ESCALATED,
            occurred_at=OBSERVED_AT + timedelta(minutes=1),
        ),
    )

    assert resolved["lifecycle_state"] == SupportCaseLifecycle.RESOLVED.value
    assert delayed_escalation["lifecycle_state"] == SupportCaseLifecycle.RESOLVED.value
    read = await repo.get_case(TENANT_A, created["case_id"])
    delayed_event = next(
        row for row in read.events if row["source_event_id"] == "event-delayed-escalate"
    )
    assert delayed_event["lifecycle_applied"] is False


@pytest.mark.asyncio
async def test_invalid_transition_and_missing_create_fail_closed() -> None:
    service = SupportCaseIngestionService(
        cases=SupportCaseRepository(),
        connections=FakeConnections({CONNECTION_A: _connection()}),
    )
    with pytest.raises(SupportCaseNotFound):
        await service.ingest(
            TENANT_A,
            CONNECTION_A,
            _event("event-resolve-first", SupportCaseEventType.RESOLVED),
        )
    await service.ingest(
        TENANT_A,
        CONNECTION_A,
        _event("event-create", SupportCaseEventType.CREATED),
    )
    with pytest.raises(SupportCaseTransitionError):
        await service.ingest(
            TENANT_A,
            CONNECTION_A,
            _event(
                "event-close-open",
                SupportCaseEventType.CLOSED,
                occurred_at=OBSERVED_AT + timedelta(minutes=1),
            ),
        )


def test_ingest_contract_rejects_unzoned_time_and_arbitrary_payload() -> None:
    base = {
        "source_case_id": "external-case-77",
        "source_event_id": "event-create-1",
        "event_type": SupportCaseEventType.CREATED,
    }
    with pytest.raises(ValidationError):
        SupportCaseEventInput(**base, occurred_at="2026-10-20T12:00:00")
    with pytest.raises(ValidationError):
        SupportCaseEventInput(
            **base,
            occurred_at=OBSERVED_AT,
            description="private message body should never enter this authority",
        )


@pytest.mark.asyncio
async def test_retention_expiry_hides_case_and_purge_removes_it() -> None:
    from shared.storage.lifecycle import StorageLifecycle

    repo = SupportCaseRepository()
    created = await repo.ingest_event(
        tenant_id=TENANT_A,
        connection_id=CONNECTION_A,
        provider_identity="support-desk",
        connection_verified_at=VERIFIED_AT,
        event=_event("event-create", SupportCaseEventType.CREATED),
        observed_at=OBSERVED_AT,
    )
    expiry = datetime.fromisoformat(created["retention_expires_at"])
    assert expiry - datetime.fromisoformat(created["last_observed_at"]) == timedelta(
        days=repo.retention_policy()[1]
    )
    held = await repo.ingest_event(
        tenant_id=TENANT_A,
        connection_id=CONNECTION_A,
        provider_identity="support-desk",
        connection_verified_at=VERIFIED_AT,
        event=_event(
            "held-case-event",
            SupportCaseEventType.CREATED,
            source_case_id="held-external-case",
        ),
        observed_at=OBSERVED_AT,
    )
    storage_lifecycle = StorageLifecycle()
    legal_hold = await storage_lifecycle.place_hold(
        TENANT_A,
        resource_type="support_case_events",
        subject_ref="held-case-event",
        reason="retention authority test",
        placed_by="test",
    )

    expired = await repo.get_case(TENANT_A, created["case_id"], now=expiry)
    held_read = await repo.get_case(TENANT_A, held["case_id"], now=expiry)
    assert expired.expired is True
    assert expired.record is None
    assert held_read.expired is False
    assert held_read.record["case_id"] == held["case_id"]
    assert await repo.purge_expired(now=expiry) == 1
    assert (await repo.get_case(TENANT_A, created["case_id"])).record is None
    assert (await repo.get_case(TENANT_A, held["case_id"])).record is not None
    await storage_lifecycle.release_hold(legal_hold["hold_id"], released_by="test")
    assert await repo.purge_expired(now=expiry) == 1
    assert (await repo.get_case(TENANT_A, held["case_id"])).record is None


@pytest.mark.asyncio
async def test_scheduled_retention_pass_invokes_support_case_hard_purge(monkeypatch) -> None:
    from governance.security import retention_worker
    from journeys.support360 import cases as support_cases

    calls: list[bool] = []

    class CountingCaseRepository:
        async def purge_expired(self) -> int:
            calls.append(True)
            return 3

    monkeypatch.setattr(support_cases, "SupportCaseRepository", CountingCaseRepository)

    assert await retention_worker.support_case_retention_pass() == 3
    assert calls == [True]


def test_database_naive_datetimes_are_serialized_as_utc() -> None:
    row = _row_dict({"received_at": datetime(2026, 10, 22, 12, 30)})
    assert row["received_at"] == "2026-10-22T12:30:00+00:00"


@pytest.mark.asyncio
async def test_durable_case_read_is_exactly_tenant_scoped() -> None:
    case_id = "case-owned-by-tenant-b"
    record = {
        "tenant_id": TENANT_B,
        "case_id": case_id,
        "lifecycle_state": "open",
        "lifecycle_observed_at": OBSERVED_AT,
        "retention_expires_at": OBSERVED_AT + timedelta(days=365),
    }

    class TenantReadPool:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[object, ...]]] = []

        async def fetchrow(self, query, *args):
            self.calls.append((query, args))
            assert "where tenant_id=$1 and case_id=$2" in " ".join(query.lower().split())
            tenant_id, requested_case_id = args
            return record if (tenant_id, requested_case_id) == (TENANT_B, case_id) else None

        async def fetch(self, query, *args):
            self.calls.append((query, args))
            return []

    pool = TenantReadPool()
    repo = SupportCaseRepository(pool=pool)

    cross_tenant = await repo.get_case(TENANT_A, case_id, now=OBSERVED_AT)
    owner_read = await repo.get_case(TENANT_B, case_id, now=OBSERVED_AT)

    assert cross_tenant.record is None
    assert cross_tenant.events == []
    assert owner_read.record["case_id"] == case_id
    assert owner_read.record["tenant_id"] == TENANT_B
    case_reads = [
        args[:2]
        for query, args in pool.calls
        if len(args) >= 2 and "from support_cases" in query.lower()
    ]
    assert case_reads == [
        (TENANT_A, case_id),
        (TENANT_B, case_id),
    ]


@pytest.mark.asyncio
async def test_durable_retention_deletes_by_tenant_and_canonical_case_id() -> None:
    expired_cases = [
        {
            "tenant_id": TENANT_A,
            "case_id": "tenant-a-expired-case",
            "source_case_id": "external-case-a",
        },
        {
            "tenant_id": TENANT_B,
            "case_id": "tenant-b-expired-case",
            "source_case_id": "external-case-b",
        },
    ]

    class Transaction:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

    class Connection:
        def __init__(self) -> None:
            self.deleted: list[tuple[str, tuple[object, ...]]] = []

        def transaction(self):
            return Transaction()

        async def fetch(self, query, *args):
            normalized_query = " ".join(query.lower().split())
            if normalized_query.startswith("select tenant_id, case_id, source_case_id"):
                assert "for update skip locked" in normalized_query
                return expired_cases
            if normalized_query.startswith("select source_event_id from support_case_events"):
                return []
            raise AssertionError(f"unexpected SQL: {normalized_query}")

        async def execute(self, query, *args):
            normalized_query = " ".join(query.lower().split())
            assert normalized_query.startswith("delete from support_cases")
            assert "where tenant_id=$1 and case_id=$2" in normalized_query
            self.deleted.append((normalized_query, args))
            return "DELETE 1"

    class Acquire:
        def __init__(self, connection):
            self.connection = connection

        async def __aenter__(self):
            return self.connection

        async def __aexit__(self, *_exc):
            return False

    class Pool:
        def __init__(self, connection):
            self.connection = connection

        def acquire(self):
            return Acquire(self.connection)

    connection = Connection()
    repo = SupportCaseRepository(pool=Pool(connection))

    deleted = await repo.purge_expired(now=OBSERVED_AT + timedelta(days=366))

    assert deleted == 2
    assert [args[:2] for _, args in connection.deleted] == [
        (TENANT_A, "tenant-a-expired-case"),
        (TENANT_B, "tenant-b-expired-case"),
    ]


@pytest.mark.asyncio
async def test_concurrent_source_event_id_collision_cannot_update_second_case() -> None:
    first_case_id = "canonical-case-one"
    second_case = {
        "tenant_id": TENANT_A,
        "case_id": "canonical-case-two",
        "source_connection_id": CONNECTION_A,
        "source_provider_identity": "support-desk",
        "source_case_id": "case-two",
        "lifecycle_state": "open",
        "lifecycle_observed_at": OBSERVED_AT,
        "first_observed_at": OBSERVED_AT,
        "last_observed_at": OBSERVED_AT,
        "last_source_event_id": "previous-event",
        "retention_expires_at": OBSERVED_AT + timedelta(days=365),
    }

    class Transaction:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

    class Connection:
        def __init__(self) -> None:
            self.event_lookups = 0
            self.executed: list[tuple[str, tuple[object, ...]]] = []

        def transaction(self):
            return Transaction()

        async def fetchrow(self, query, *args):
            normalized_query = " ".join(query.lower().split())
            if normalized_query.startswith("select * from support_cases"):
                return second_case
            if normalized_query.startswith(
                "select case_id, event_type, source_occurred_at from support_case_events"
            ):
                self.event_lookups += 1
                if self.event_lookups == 1:
                    return None
                return {"case_id": first_case_id}
            if normalized_query.startswith("insert into support_case_events"):
                return None  # Another transaction won the unique event key.
            raise AssertionError(f"unexpected SQL: {normalized_query}")

        async def execute(self, query, *args):
            self.executed.append((query, args))

    class Acquire:
        def __init__(self, connection):
            self.connection = connection

        async def __aenter__(self):
            return self.connection

        async def __aexit__(self, *_exc):
            return False

    class Pool:
        def __init__(self, connection):
            self.connection = connection

        def acquire(self):
            return Acquire(self.connection)

    connection = Connection()
    repo = SupportCaseRepository(pool=Pool(connection))

    with pytest.raises(SupportCaseAuthorityError, match="reused for another case"):
        await repo.ingest_event(
            tenant_id=TENANT_A,
            connection_id=CONNECTION_A,
            provider_identity="support-desk",
            connection_verified_at=VERIFIED_AT,
            event=_event(
                "concurrent-reused-event",
                SupportCaseEventType.UPDATED,
                source_case_id="case-two",
                occurred_at=OBSERVED_AT + timedelta(minutes=1),
            ),
            observed_at=OBSERVED_AT + timedelta(minutes=2),
        )

    assert connection.event_lookups == 2
    assert connection.executed == []


@pytest.mark.asyncio
async def test_support_case_route_requires_write_and_uses_authenticated_tenant(monkeypatch) -> None:
    from fastapi import Request

    from journeys.support360 import routes
    from shared.auth.auth import Permissions
    from shared.common.common import ForbiddenError

    received: list[tuple[str, str, str]] = []

    class CapturingIngestionService:
        async def ingest(self, tenant_id, connection_id, event):
            received.append((tenant_id, connection_id, event.source_case_id))
            return {
                "case_id": "canonical-case",
                "lifecycle_state": "open",
                "last_observed_at": OBSERVED_AT.isoformat(),
                "retention_expires_at": (OBSERVED_AT + timedelta(days=365)).isoformat(),
            }

    monkeypatch.setattr(routes, "SupportCaseIngestionService", CapturingIngestionService)

    def request_for(permissions: set[str]) -> Request:
        request = Request(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": "/v1/support/cases/ingest",
                "raw_path": b"/v1/support/cases/ingest",
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

    body = routes.SupportCaseIngestBody(
        connection_id=CONNECTION_A,
        source_case_id="source-case-private",
        source_event_id="event-route-1",
        event_type=SupportCaseEventType.CREATED,
        occurred_at=OBSERVED_AT,
    )
    response = await routes.ingest_support_case_event(
        request_for({Permissions.WRITE}),
        body,
    )

    assert response["data"]["case_id"] == "canonical-case"
    assert received == [(TENANT_A, CONNECTION_A, "source-case-private")]
    with pytest.raises(ForbiddenError):
        await routes.ingest_support_case_event(request_for({Permissions.READ}), body)
    assert received == [(TENANT_A, CONNECTION_A, "source-case-private")]


def test_support_case_ingest_route_is_mounted_in_the_application() -> None:
    from main import create_app

    app = create_app()
    mounted = [
        path
        for path in app.openapi()["paths"]
        if path == "/v1/support/cases/ingest"
    ]
    assert len(mounted) == 1
    assert set(app.openapi()["paths"][mounted[0]]) == {"post"}
