"""Focused route admission, concurrency, tenancy and restart safety checks."""

from __future__ import annotations

import asyncio
import ast
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from services.provider_runtime import tenant_route_repository as route_repo
from services.provider_runtime.tenant_route_repository import (
    RouteAdmissionDenied,
    RouteConflict,
    RouteDecision,
    RouteScope,
    StaleRouteRevision,
    TenantRouteRepository,
    reset_tenant_route_local_stores,
)
from services.provider_runtime.tenant_route_service import TenantRouteService
from shared.integration_contracts.lifecycle import ConnectionState


NOW = datetime(2026, 10, 2, 16, 0, tzinfo=timezone.utc)


class _Managed:
    async def get(self, tenant_id: str, environment_id: str, managed_integration_id: str):
        if (tenant_id, environment_id, managed_integration_id) == ("tenant-a", "staging", "mi-a"):
            return {
                "integration_kind": "connector_aether_hosted",
                "source_ref": "legacy-shopify-1",
            }
        return None


class _Connections:
    def __init__(self, *, tenant_id: str = "tenant-a", state=ConnectionState.CONNECTED):
        self.connection = SimpleNamespace(
            connection_id="conn-native",
            tenant_id=tenant_id,
            provider_identity="shopify.admin.orders_read",
            selected_accounts=["shop-1"],
            state=state,
        )

    async def find(self, connection_ref: str):
        return self.connection if connection_ref == self.connection.connection_id else None


@pytest.fixture(autouse=True)
def _local_repository(monkeypatch: pytest.MonkeyPatch):
    async def no_pool():
        return None

    monkeypatch.setattr(route_repo, "get_pool", no_pool)
    reset_tenant_route_local_stores()
    yield
    reset_tenant_route_local_stores()


def _scope(**changes) -> RouteScope:
    data = dict(
        tenant_id="tenant-a",
        environment_id="staging",
        managed_integration_id="mi-a",
        provider_identity="shopify.admin.orders_read",
        account_id="shop-1",
        stream_id="orders",
        fact_family="commerce.order",
    )
    data.update(changes)
    return RouteScope(**data)


def _decision(*, evidence: str | None = "bundle-1") -> RouteDecision:
    return RouteDecision(
        actor_ref="kyber:operator-1",
        decision_ref="changeset-1",
        evidence_bundle_ref=evidence,
        reason="reviewed tenant migration",
    )


def _service(*, connections=None, admit=True) -> TenantRouteService:
    async def authorize(scope, current, proposal, decision):
        await asyncio.sleep(0)  # expose a CAS interleave in concurrent tests
        return admit

    return TenantRouteService(
        routes=TenantRouteRepository(),
        managed_integrations=_Managed(),
        connections=connections or _Connections(),
        admit=authorize if admit is not None else None,
        clock=lambda: NOW,
    )


@pytest.mark.asyncio
async def test_create_is_scoped_audited_and_defaults_to_legacy_writer():
    service = _service()
    scope = _scope()
    row = await service.create_legacy_route(
        scope, legacy_connection_ref="legacy-shopify-1", decision=_decision()
    )
    assert (row.mode, row.production_writer, row.writer_generation, row.revision) == (
        "legacy_only",
        "legacy",
        1,
        1,
    )
    assert (await TenantRouteRepository().get(scope)).route_id == row.route_id
    assert await TenantRouteRepository().get(_scope(tenant_id="tenant-b")) is None
    assert await TenantRouteRepository().get(_scope(environment_id="production")) is None
    history = await service.routes.transition_history(scope)
    assert len(history) == 1
    assert history[0]["revision"] == 1
    assert history[0]["previous_mode"] is None
    assert history[0]["decision_ref"] == "changeset-1"
    with pytest.raises(RouteConflict):
        await service.create_legacy_route(
            scope, legacy_connection_ref="legacy-shopify-1", decision=_decision()
        )


@pytest.mark.asyncio
async def test_route_creation_requires_existing_scoped_managed_registration_and_admission():
    with pytest.raises(RouteAdmissionDenied):
        await _service().create_legacy_route(
            _scope(tenant_id="tenant-b"),
            legacy_connection_ref="legacy-shopify-1",
            decision=_decision(),
        )
    with pytest.raises(RouteAdmissionDenied):
        await _service(admit=None).create_legacy_route(
            _scope(), legacy_connection_ref="legacy-shopify-1", decision=_decision()
        )
    with pytest.raises(RouteAdmissionDenied):
        await _service().create_legacy_route(
            _scope(), legacy_connection_ref="another-tenant-connection", decision=_decision()
        )
    assert await TenantRouteRepository().get(_scope()) is None


@pytest.mark.asyncio
async def test_shadow_promotion_rollback_changes_writer_generation_and_fences_old_tokens():
    service = _service()
    scope = _scope()
    legacy = await service.create_legacy_route(
        scope, legacy_connection_ref="legacy-shopify-1", decision=_decision()
    )
    shadow = await service.start_shadow(
        scope,
        expected_revision=legacy.revision,
        native_connection_ref="conn-native",
        shadow_namespace="shadow:tenant-a:mi-a:orders",
        decision=_decision(),
    )
    assert (shadow.mode, shadow.writer_generation, shadow.revision) == ("shadow", 2, 2)
    await service.assert_writer(scope, writer="legacy", writer_generation=2)
    await service.assert_shadow(
        scope, writer_generation=2, shadow_namespace="shadow:tenant-a:mi-a:orders"
    )
    with pytest.raises(RouteAdmissionDenied):
        await service.assert_writer(scope, writer="native", writer_generation=2)

    primary = await service.promote_native(
        scope,
        expected_revision=shadow.revision,
        rollback_until=NOW + timedelta(days=7),
        decision=_decision(),
    )
    assert (primary.mode, primary.production_writer, primary.writer_generation) == (
        "new_primary",
        "native",
        3,
    )
    await service.assert_writer(scope, writer="native", writer_generation=3)
    for writer, generation in (("legacy", 2), ("native", 2), ("legacy", 3)):
        with pytest.raises(RouteAdmissionDenied):
            await service.assert_writer(scope, writer=writer, writer_generation=generation)

    rolled_back = await service.rollback_to_shadow(
        scope, expected_revision=primary.revision, decision=_decision()
    )
    assert (rolled_back.mode, rolled_back.production_writer, rolled_back.writer_generation) == (
        "shadow",
        "legacy",
        4,
    )
    with pytest.raises(RouteAdmissionDenied):
        await service.assert_writer(scope, writer="native", writer_generation=3)
    await service.assert_writer(scope, writer="legacy", writer_generation=4)
    assert [r["revision"] for r in await service.routes.transition_history(scope)] == [1, 2, 3, 4]


@pytest.mark.asyncio
async def test_concurrent_transitions_from_one_revision_have_one_winner():
    service_a, service_b = _service(), _service()
    scope = _scope()
    initial = await service_a.create_legacy_route(
        scope, legacy_connection_ref="legacy-shopify-1", decision=_decision()
    )
    shadow = await service_a.start_shadow(
        scope,
        expected_revision=initial.revision,
        native_connection_ref="conn-native",
        shadow_namespace="shadow:tenant-a:orders",
        decision=_decision(),
    )
    results = await asyncio.gather(
        service_a.promote_native(
            scope,
            expected_revision=shadow.revision,
            rollback_until=NOW + timedelta(days=7),
            decision=_decision(),
        ),
        service_b.stop_shadow(scope, expected_revision=shadow.revision, decision=_decision()),
        return_exceptions=True,
    )
    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert sum(isinstance(result, StaleRouteRevision) for result in results) == 1
    current = await TenantRouteRepository().get(scope)
    assert (current.revision, current.writer_generation) == (3, 3)
    assert len(await service_a.routes.transition_history(scope)) == 3


@pytest.mark.asyncio
async def test_native_connection_must_match_tenant_and_account():
    service = _service(connections=_Connections(tenant_id="tenant-b"))
    scope = _scope()
    legacy = await service.create_legacy_route(
        scope, legacy_connection_ref="legacy-shopify-1", decision=_decision()
    )
    with pytest.raises(RouteAdmissionDenied):
        await service.start_shadow(
            scope,
            expected_revision=legacy.revision,
            native_connection_ref="conn-native",
            shadow_namespace="shadow:tenant-a:orders",
            decision=_decision(),
        )
    assert (await service.routes.get(scope)).revision == 1
    assert await service.routes.transition_history(_scope(tenant_id="tenant-b")) == []


@pytest.mark.asyncio
async def test_promotion_requires_evidence_future_rollback_and_connected_native():
    service = _service(connections=_Connections(state=ConnectionState.VERIFIED))
    scope = _scope()
    first = await service.create_legacy_route(
        scope, legacy_connection_ref="legacy-shopify-1", decision=_decision()
    )
    shadow = await service.start_shadow(
        scope,
        expected_revision=first.revision,
        native_connection_ref="conn-native",
        shadow_namespace="shadow:tenant-a:orders",
        decision=_decision(),
    )
    with pytest.raises(RouteAdmissionDenied):
        await service.promote_native(
            scope,
            expected_revision=shadow.revision,
            rollback_until=NOW + timedelta(days=7),
            decision=_decision(evidence=None),
        )
    with pytest.raises(RouteAdmissionDenied):
        await service.promote_native(
            scope,
            expected_revision=shadow.revision,
            rollback_until=NOW,
            decision=_decision(),
        )
    with pytest.raises(RouteAdmissionDenied):
        await service.promote_native(
            scope,
            expected_revision=shadow.revision,
            rollback_until=NOW + timedelta(days=7),
            decision=_decision(),
        )
    assert (await service.routes.get(scope)).mode == "shadow"


@pytest.mark.asyncio
async def test_repository_reinstantiation_reads_same_local_route_and_history():
    """Client recreation is covered locally; the DB test below covers persistence."""
    service = _service()
    scope = _scope()
    created = await service.create_legacy_route(
        scope, legacy_connection_ref="legacy-shopify-1", decision=_decision()
    )
    new_client = TenantRouteRepository()
    assert (await new_client.get(scope)).route_id == created.route_id
    assert len(await new_client.transition_history(scope)) == 1


@pytest.mark.asyncio
async def test_postgres_compare_and_swap_returns_expanded_columns():
    """The durable transition query must interpolate the route column list."""
    scope = _scope()
    now = NOW
    current = route_repo.TenantConnectorRoute(
        route_id="croute-sql-test",
        **scope.model_dump(),
        mode="shadow",
        legacy_connection_ref="legacy-shopify-1",
        native_connection_ref="conn-native",
        shadow_namespace="shadow:tenant-a:orders",
        writer_generation=2,
        revision=2,
        created_at=now,
        updated_at=now,
    )

    class Connection:
        statements: list[str]

        def __init__(self):
            self.statements = []

        @asynccontextmanager
        async def transaction(self):
            yield

        async def fetchrow(self, query: str, *args):
            self.statements.append(query)
            if query.startswith("SELECT"):
                return current.model_dump()
            assert query.startswith("UPDATE")
            assert "RETURNING " + route_repo._ROUTE_COLUMNS in query
            assert "{_ROUTE_COLUMNS}" not in query
            updated = current.model_copy(
                update={
                    "mode": "new_primary",
                    "rollback_until": NOW + timedelta(days=7),
                    "writer_generation": 3,
                    "revision": 3,
                    "updated_at": args[5],
                }
            )
            return updated.model_dump()

        async def execute(self, query: str, *args):
            self.statements.append(query)

    class Pool:
        def __init__(self, connection):
            self.connection = connection

        @asynccontextmanager
        async def acquire(self):
            yield self.connection

    connection = Connection()
    repository = TenantRouteRepository()
    repository._pool = Pool(connection)
    repository._table_ensured = True
    updated = await repository.compare_and_swap(
        scope,
        expected_revision=2,
        mode="new_primary",
        native_connection_ref="conn-native",
        shadow_namespace="shadow:tenant-a:orders",
        rollback_until=NOW + timedelta(days=7),
        decision=_decision(),
    )
    assert (updated.mode, updated.revision, updated.writer_generation) == ("new_primary", 3, 3)
    assert len(connection.statements) == 3


def test_migration_ddl_is_identical_to_repository_ddl():
    path = (
        Path(__file__).resolve().parents[2] / "alembic/versions/20261002_tenant_connector_routes.py"
    )
    tree = ast.parse(path.read_text())
    ddl = next(
        ast.literal_eval(stmt.value)
        for stmt in tree.body
        if isinstance(stmt, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "SCHEMA_SQL" for target in stmt.targets
        )
    )
    assert ddl == route_repo.SCHEMA_SQL
    assert "UNIQUE INDEX IF NOT EXISTS ux_tenant_connector_route_scope" in ddl
    assert "REFERENCES tenant_connector_routes(route_id) ON DELETE RESTRICT" in ddl


@pytest.mark.asyncio
async def test_postgres_route_survives_repository_and_pool_restart(monkeypatch: pytest.MonkeyPatch):
    """Runs only against an isolated test PostgreSQL URL; never a live tenant DB."""
    dsn = os.environ.get("AETHER_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("AETHER_TEST_DATABASE_URL is not configured")
    asyncpg = pytest.importorskip("asyncpg")
    scope = _scope(
        tenant_id=f"route-test-{uuid4().hex}",
        managed_integration_id=f"mi-{uuid4().hex}",
    )
    pool = await asyncpg.create_pool(dsn)
    created = None

    async def get_test_pool():
        return pool

    monkeypatch.setattr(route_repo, "get_pool", get_test_pool)
    try:
        first = TenantRouteRepository()
        created = await first.create_legacy(
            scope, legacy_connection_ref="legacy-test", decision=_decision()
        )
        await pool.close()
        pool = await asyncpg.create_pool(dsn)
        second = TenantRouteRepository()
        recovered = await second.get(scope)
        assert recovered is not None
        assert (recovered.route_id, recovered.writer_generation) == (created.route_id, 1)
        assert len(await second.transition_history(scope)) == 1
    finally:
        if pool.is_closing():
            pool = await asyncpg.create_pool(dsn)
        try:
            if created is not None:
                async with pool.acquire() as conn:
                    await conn.execute(
                        "DELETE FROM tenant_connector_route_transitions WHERE route_id=$1",
                        created.route_id,
                    )
                    await conn.execute(
                        "DELETE FROM tenant_connector_routes WHERE route_id=$1", created.route_id
                    )
        finally:
            await pool.close()
