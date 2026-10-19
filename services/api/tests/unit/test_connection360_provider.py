"""Focused contract tests for the read-only Connection360 provider."""

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

from connectors.provider_runtime.connection360_provider import (  # noqa: E402
    OUTPUT_SECTIONS,
    AuthorityRead,
    Connection360Provider,
    RepositoryConnection360ReadAuthority,
)
from shared.intelligence_projections.contracts import (  # noqa: E402
    ProjectionContext,
    ProjectionDependencyState,
    ProjectionRequest,
    ProjectionSubject,
)

TENANT = "tenant-connection360"
CONNECTION_ID = "conn-1"
PROVIDER_ID = "shopify.admin.orders_read"


def _connection(tenant_id: str = TENANT, **overrides: object) -> dict:
    row = {
        "tenant_id": tenant_id,
        "connection_id": CONNECTION_ID,
        "provider_identity": PROVIDER_ID,
        "display_name": "private display label",
        "state": "connected",
        "credential_ref": "provider:tenant:secret-reference",
        "config": {"api_key": "must-not-appear"},
        "selected_accounts": ["account-private"],
        "created_at": "2026-10-15T09:00:00+00:00",
        "updated_at": "2026-10-16T10:00:00+00:00",
        "last_verified_at": "2026-10-16T09:55:00+00:00",
        "last_successful_sync_at": "2026-10-16T09:00:00+00:00",
    }
    row.update(overrides)
    return row


def _run(
    tenant_id: str = TENANT,
    *,
    run_id: str = "syncrun-1",
    started_at: str = "2026-10-16T10:00:00+00:00",
    completed_at: str | None = "2026-10-16T10:01:00+00:00",
    status: str = "completed",
    **overrides: object,
) -> dict:
    row = {
        "tenant_id": tenant_id,
        "connector_instance_id": CONNECTION_ID,
        "provider": PROVIDER_ID,
        "sync_run_id": run_id,
        "mode": "incremental",
        "status": status,
        "started_at": started_at,
        "completed_at": completed_at,
        "records_received": 3,
        "facts_written": 2,
        "reconciliation_status": "pending",
        "safe_error_code": None,
        "safe_error_detail": "must-not-appear",
        "cursor_before": "private-cursor-before",
        "cursor_after": "private-cursor-after",
        "triggered_by": "system",
    }
    row.update(overrides)
    return row


def _request(**overrides: object) -> ProjectionRequest:
    values: dict[str, object] = {
        "projectionId": "connection360",
        "tenantId": TENANT,
        "subject": ProjectionSubject(kind="connection", id=CONNECTION_ID),
    }
    values.update(overrides)
    return ProjectionRequest(**values)


def _context(
    tenant_id: str = TENANT,
    *,
    dependencies: list[ProjectionDependencyState] | None = None,
) -> ProjectionContext:
    return ProjectionContext(
        projectionId="connection360",
        tenantId=tenant_id,
        registryState="in_flight",
        dependencyState=dependencies or [],
        warnings=[],
    )


class FakeReader:
    def __init__(
        self,
        connections: AuthorityRead | None = None,
        runs: AuthorityRead | None = None,
    ) -> None:
        self.connection_read = connections or AuthorityRead([_connection()], True, True)
        self.run_read = runs or AuthorityRead([_run()], True, True)
        self.connection_calls: list[tuple[str, str, str]] = []
        self.run_calls: list[tuple[str, str]] = []

    async def connections(
        self, *, tenant_id: str, subject_kind: str, subject_id: str, limit: int
    ) -> AuthorityRead:
        self.connection_calls.append((tenant_id, subject_kind, subject_id))
        return self.connection_read

    async def sync_runs(
        self, *, tenant_id: str, connection_id: str, limit: int
    ) -> AuthorityRead:
        self.run_calls.append((tenant_id, connection_id))
        return self.run_read


class FakeConnectionRepository:
    def __init__(self) -> None:
        self.find_filters: list[dict[str, str]] = []
        self.find_limits: list[int] = []
        self.find_result = [_connection()]
        self.list_calls: list[tuple[str, int]] = []

    async def find_many(self, *, filters: dict[str, str], limit: int) -> list[dict]:
        self.find_filters.append(filters)
        self.find_limits.append(limit)
        return [
            row
            for row in self.find_result
            if all(row.get(key) == value for key, value in filters.items())
        ][:limit]

    async def list_for_tenant(self, tenant_id: str, *, limit: int) -> list[dict]:
        self.list_calls.append((tenant_id, limit))
        return [_connection()]


class FakeSyncRunService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int]] = []

    async def list_for_connector(
        self, tenant_id: str, connection_id: str, *, limit: int
    ) -> list[dict]:
        self.calls.append((tenant_id, connection_id, limit))
        return [_run(), _run("tenant-other", run_id="cross-tenant-run")]


def _section(result: object, section_id: str):
    return next(section for section in result.sections if section.id == section_id)


async def test_provider_emits_bound_sections_and_evidence_without_secret_material() -> None:
    reader = FakeReader()
    request = _request(
        includeSections=["summary", "state", "evidence", "health", "coverage"],
        includeClaims=True,
    )
    result = await Connection360Provider(reader).project(request, _context())

    assert [section.id for section in result.sections] == list(OUTPUT_SECTIONS)
    assert result.asOf is not None
    assert result.dependencyState == []
    state = _section(result, "state")
    assert state.content["lifecycleRecords"][0]["state"] == "connected"
    assert state.content["lifecycleRecords"][0]["externalProviderState"] == "not_independently_verified"
    evidence = _section(result, "evidence")
    assert evidence.content["syncRuns"][0]["evidence"].source == "comms_sync_runs"
    health = _section(result, "health")
    assert health.state == "unknown"
    assert health.content["providerHealth"] == "unknown"
    assert health.content["freshness"] == "unknown"
    assert result.claims
    assert all(claim.evidenceRefs for claim in result.claims)
    assert all(claim.domainSlotIds == ["integration_and_sync_context"] for claim in result.claims)

    serialized = json.dumps(result.model_dump(mode="json"))
    for private_value in (
        "must-not-appear",
        "provider:tenant:secret-reference",
        "private-cursor-before",
        "private-cursor-after",
        "account-private",
        "private display label",
    ):
        assert private_value not in serialized


async def test_repository_adapter_uses_tenant_filtered_lifecycle_and_sync_authorities() -> None:
    connections = FakeConnectionRepository()
    sync_runs = FakeSyncRunService()
    authority = RepositoryConnection360ReadAuthority(
        connections=connections,
        sync_runs=sync_runs,
    )

    connection_read = await authority.connections(
        tenant_id=TENANT,
        subject_kind="connection",
        subject_id=CONNECTION_ID,
        limit=100,
    )
    run_read = await authority.sync_runs(
        tenant_id=TENANT,
        connection_id=CONNECTION_ID,
        limit=100,
    )

    assert connections.find_filters == [
        {"tenant_id": TENANT, "connection_id": CONNECTION_ID}
    ]
    assert connections.find_limits == [2]
    assert connection_read.available and connection_read.rows == [_connection()]
    assert sync_runs.calls == [(TENANT, CONNECTION_ID, 101)]
    assert run_read.available
    assert [row["sync_run_id"] for row in run_read.rows] == ["syncrun-1"]


async def test_repository_source_lookup_filters_provider_before_bounding() -> None:
    # A source lookup must not be made incomplete by unrelated tenant
    # connections that happen to precede it in a tenant-wide result page.
    connections = FakeConnectionRepository()
    connections.find_result = [
        _connection(),
        *[
            _connection(
                connection_id=f"other-{index}",
                provider_identity="stripe.payments",
            )
            for index in range(120)
        ],
    ]
    authority = RepositoryConnection360ReadAuthority(connections=connections)

    read = await authority.connections(
        tenant_id=TENANT,
        subject_kind="source",
        subject_id=PROVIDER_ID,
        limit=100,
    )

    assert connections.find_filters == [
        {"tenant_id": TENANT, "provider_identity": PROVIDER_ID}
    ]
    assert connections.find_limits == [101]
    assert connections.list_calls == []
    assert read.available
    assert read.complete
    assert read.rows == [_connection()]


async def test_tenant_mismatch_does_not_read_either_authority() -> None:
    reader = FakeReader()
    result = await Connection360Provider(reader).project(_request(), _context("tenant-other"))

    assert reader.connection_calls == []
    assert reader.run_calls == []
    assert all(section.state == "unknown" for section in result.sections)
    assert "tenant_scope_mismatch" in result.degradedReasons
    assert result.claims == []


async def test_source_subject_lists_only_matching_tenant_connections() -> None:
    reader = FakeReader(
        connections=AuthorityRead(
            [
                _connection(),
                _connection("tenant-other", connection_id="conn-other"),
                _connection(connection_id="conn-unrelated", provider_identity="stripe.payments"),
            ],
            True,
            True,
        )
    )
    request = _request(subject=ProjectionSubject(kind="source", id=PROVIDER_ID))
    result = await Connection360Provider(reader).project(request, _context())

    assert reader.connection_calls == [(TENANT, "source", PROVIDER_ID)]
    assert reader.run_calls == [(TENANT, CONNECTION_ID)]
    assert [row["connectionId"] for row in _section(result, "summary").content["connections"]] == [
        CONNECTION_ID
    ]
    assert all(claim.domainSlotIds == ["integration_and_sync_context"] for claim in result.claims)


async def test_provider_drops_cross_tenant_connection_and_sync_rows() -> None:
    reader = FakeReader(
        connections=AuthorityRead([_connection("tenant-other")], True, True),
        runs=AuthorityRead([_run("tenant-other")], True, True),
    )
    result = await Connection360Provider(reader).project(_request(), _context())

    assert _section(result, "summary").content["connections"] == []
    assert _section(result, "evidence").content["syncRuns"] == []
    assert result.claims == []
    assert "unscoped_connection_authority_rows_dropped" in result.degradedReasons
    assert "unscoped_sync_authority_rows_dropped" in result.degradedReasons


async def test_explicit_connection_reads_sync_ledger_when_lifecycle_read_is_unavailable() -> None:
    reader = FakeReader(
        connections=AuthorityRead(
            [], False, False, "provider_connection_authority_unavailable"
        ),
        runs=AuthorityRead([_run()], True, True),
    )
    result = await Connection360Provider(reader).project(_request(), _context())

    assert reader.connection_calls == [(TENANT, "connection", CONNECTION_ID)]
    assert reader.run_calls == [(TENANT, CONNECTION_ID)]
    assert _section(result, "state").state == "unknown"
    assert _section(result, "summary").content["connections"] == []
    assert _section(result, "summary").content["syncRunCount"] == 1
    assert [
        item["record"]["syncRunId"]
        for item in _section(result, "evidence").content["syncRuns"]
    ] == ["syncrun-1"]
    assert all(claim.kind == "server_recorded_sync_run_status" for claim in result.claims)


async def test_as_of_uses_only_closed_sync_runs_and_omits_mutable_lifecycle() -> None:
    anchor = "2026-10-16T10:05:00+00:00"
    reader = FakeReader(
        runs=AuthorityRead(
            [
                _run(run_id="before-anchor"),
                _run(
                    run_id="after-anchor",
                    started_at="2026-10-16T10:10:00+00:00",
                    completed_at="2026-10-16T10:11:00+00:00",
                ),
                _run(
                    run_id="still-running",
                    status="running",
                    completed_at=None,
                ),
            ],
            True,
            True,
        )
    )
    request = _request(asOf=anchor, temporalMode="as_of")
    result = await Connection360Provider(reader).project(request, _context())

    assert reader.connection_calls == []
    assert reader.run_calls == [(TENANT, CONNECTION_ID)]
    assert result.asOf == "2026-10-16T10:05:00+00:00"
    assert _section(result, "state").state == "unknown"
    assert _section(result, "state").content["lifecycleRecords"] == []
    assert [item["record"]["syncRunId"] for item in _section(result, "evidence").content["syncRuns"]] == [
        "before-anchor"
    ]
    assert all(claim.kind == "server_recorded_sync_run_status" for claim in result.claims)


async def test_as_of_source_does_not_use_current_connections_to_infer_history() -> None:
    reader = FakeReader()
    result = await Connection360Provider(reader).project(
        _request(
            subject=ProjectionSubject(kind="source", id=PROVIDER_ID),
            asOf="2026-10-16T10:05:00+00:00",
            temporalMode="as_of",
        ),
        _context(),
    )

    assert reader.connection_calls == []
    assert reader.run_calls == []
    assert _section(result, "summary").state == "unknown"
    assert _section(result, "evidence").state == "unknown"
    assert "source_connection_membership_history_unavailable" in result.degradedReasons


async def test_relative_without_resolved_range_stays_unknown_and_does_not_read() -> None:
    reader = FakeReader()
    result = await Connection360Provider(reader).project(
        _request(temporalMode="relative"), _context()
    )

    assert reader.connection_calls == []
    assert reader.run_calls == []
    assert all(section.state == "unknown" for section in result.sections)
    assert "relative_time_range_not_resolved" in result.degradedReasons
    assert result.asOf is None
