"""Scoped route fences serialize cooperating graph writes and route changes."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from connectors.provider_runtime import tenant_route_repository as route_repo
from connectors.provider_runtime.connector_graph_writer import ConnectorGraphWriter
from connectors.provider_runtime.tenant_route_repository import (
    RouteAdmissionDenied,
    RouteDecision,
    RouteScope,
    TenantRouteRepository,
    reset_tenant_route_local_stores,
)
from shared.graph.graph import Edge, Vertex
from shared.graph.mutation_gateway import MutationIntent, MutationOutcome


def _scope(**changes: str) -> RouteScope:
    values = {
        "tenant_id": "tenant-a",
        "environment_id": "staging",
        "managed_integration_id": "mi-a",
        "provider_identity": "shopify.admin.orders_read",
        "account_id": "shop-a",
        "stream_id": "orders",
        "fact_family": "commerce.order",
    }
    values.update(changes)
    return RouteScope(**values)


def _decision() -> RouteDecision:
    return RouteDecision(
        actor_ref="kyber:operator-1",
        decision_ref="changeset-1",
        reason="reviewed transition",
    )


def _intent(
    *, tenant_id: str = "tenant-a", source_event_id: str = "cevt_v1_source"
) -> MutationIntent:
    return MutationIntent(
        operation="node_created",
        tenant_id=tenant_id,
        vertex=Vertex("CommerceOrder", properties={"tenant_id": tenant_id}),
        source_event_id=source_event_id,
    )


@pytest.fixture(autouse=True)
def _local_repository(monkeypatch: pytest.MonkeyPatch):
    async def no_pool():
        return None

    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(route_repo, "get_pool", no_pool)
    reset_tenant_route_local_stores()
    yield
    reset_tenant_route_local_stores()


@pytest.mark.asyncio
async def test_in_flight_legacy_write_blocks_promotion_and_stale_generation():
    routes = TenantRouteRepository()
    scope = _scope()
    await routes.create_legacy(scope, legacy_connection_ref="legacy-a", decision=_decision())
    started = asyncio.Event()
    release = asyncio.Event()

    class Gateway:
        async def apply(self, intent, *, mode_override):
            assert intent.tenant_id == scope.tenant_id
            assert mode_override == "enforce"
            started.set()
            await release.wait()
            return MutationOutcome(mode="enforce", applied=True)

    writer = ConnectorGraphWriter(routes=routes, gateway=Gateway())
    first = asyncio.create_task(
        writer.apply(
            _intent(),
            scope=scope,
            writer="legacy",
            writer_generation=1,
            connection_ref="legacy-a",
        )
    )
    await asyncio.wait_for(started.wait(), timeout=2)
    transition = asyncio.create_task(
        routes.compare_and_swap(
            scope,
            expected_revision=1,
            mode="new_primary",
            native_connection_ref="native-a",
            shadow_namespace=None,
            rollback_until=None,
            decision=_decision(),
        )
    )
    try:
        await asyncio.sleep(0.02)
        assert not transition.done()
    finally:
        release.set()
    assert (await first).applied
    promoted = await transition
    assert (promoted.mode, promoted.writer_generation) == ("new_primary", 2)

    with pytest.raises(RouteAdmissionDenied):
        await writer.apply(
            _intent(),
            scope=scope,
            writer="legacy",
            writer_generation=1,
            connection_ref="legacy-a",
        )
    assert (
        await writer.apply(
            _intent(),
            scope=scope,
            writer="native",
            writer_generation=2,
            connection_ref="native-a",
        )
    ).applied


@pytest.mark.asyncio
async def test_writer_checks_full_scope_connection_and_tenant_before_gateway():
    routes = TenantRouteRepository()
    scope = _scope()
    await routes.create_legacy(scope, legacy_connection_ref="legacy-a", decision=_decision())

    class Gateway:
        calls = 0

        async def apply(self, intent, *, mode_override):
            self.calls += 1
            return MutationOutcome(mode="enforce", applied=True)

    gateway = Gateway()
    writer = ConnectorGraphWriter(routes=routes, gateway=gateway)
    for rejected_scope, rejected_intent, generation, connection_ref in (
        (scope, _intent(tenant_id="tenant-b"), 1, "legacy-a"),
        (scope, _intent(source_event_id=" "), 1, "legacy-a"),
        (_scope(tenant_id="tenant-b"), _intent(tenant_id="tenant-b"), 1, "legacy-a"),
        (_scope(stream_id="refunds"), _intent(), 1, "legacy-a"),
        (scope, _intent(), 2, "legacy-a"),
        (scope, _intent(), 1, "other-connection"),
        (
            scope,
            MutationIntent(
                operation="node_created",
                tenant_id="tenant-a",
                vertex=Vertex("CommerceOrder", properties={"tenant_id": "tenant-b"}),
                source_event_id="cevt_v1_source",
            ),
            1,
            "legacy-a",
        ),
        (
            scope,
            MutationIntent(
                operation="edge_created",
                tenant_id="tenant-a",
                edge=Edge(
                    "PURCHASED",
                    "consumer-a",
                    "order-a",
                    properties={"tenant_id": "tenant-a", "source_event_id": "other-event"},
                ),
                source_event_id="cevt_v1_source",
            ),
            1,
            "legacy-a",
        ),
    ):
        with pytest.raises(RouteAdmissionDenied):
            await writer.apply(
                rejected_intent,
                scope=rejected_scope,
                writer="legacy",
                writer_generation=generation,
                connection_ref=connection_ref,
            )
    with pytest.raises(RouteAdmissionDenied):
        await writer.apply(
            _intent(),
            scope=scope,
            writer="native",
            writer_generation=1,
            connection_ref="legacy-a",
        )
    assert gateway.calls == 0


@pytest.mark.asyncio
async def test_nonlocal_route_repository_fails_closed_without_postgres(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("AETHER_ENV", "production")
    routes = TenantRouteRepository()
    with pytest.raises(RuntimeError, match="PostgreSQL is required"):
        await routes.get(_scope())
    with pytest.raises(RuntimeError, match="PostgreSQL is required"):
        async with routes.writer_fence(
            _scope(), writer="legacy", writer_generation=1, connection_ref="legacy-a"
        ):
            pytest.fail("writer fence admitted without PostgreSQL")


@pytest.mark.asyncio
async def test_configured_local_database_cannot_fall_back_to_memory(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("DATABASE_URL", "postgresql://unavailable/test")
    with pytest.raises(RuntimeError, match="PostgreSQL is required"):
        await TenantRouteRepository().get(_scope())


@pytest.mark.asyncio
async def test_gateway_timeout_releases_route_fence_for_transition():
    routes = TenantRouteRepository()
    scope = _scope()
    await routes.create_legacy(scope, legacy_connection_ref="legacy-a", decision=_decision())

    class Gateway:
        async def apply(self, intent, *, mode_override):
            await asyncio.Event().wait()

    writer = ConnectorGraphWriter(routes=routes, gateway=Gateway(), mutation_timeout_seconds=0.01)
    with pytest.raises(TimeoutError):
        await writer.apply(
            _intent(),
            scope=scope,
            writer="legacy",
            writer_generation=1,
            connection_ref="legacy-a",
        )
    changed = await asyncio.wait_for(
        routes.compare_and_swap(
            scope,
            expected_revision=1,
            mode="new_primary",
            native_connection_ref="native-a",
            shadow_namespace=None,
            rollback_until=None,
            decision=_decision(),
        ),
        timeout=1,
    )
    assert changed.writer_generation == 2


@pytest.mark.asyncio
async def test_writer_timeout_bounds_wait_for_route_fence():
    routes = TenantRouteRepository()
    scope = _scope()
    await routes.create_legacy(scope, legacy_connection_ref="legacy-a", decision=_decision())

    class Gateway:
        calls = 0

        async def apply(self, intent, *, mode_override):
            self.calls += 1
            return MutationOutcome(mode="enforce", applied=True)

    gateway = Gateway()
    writer = ConnectorGraphWriter(routes=routes, gateway=gateway, mutation_timeout_seconds=0.01)
    await route_repo._LOCAL_ROUTE_LOCK.acquire()
    try:
        with pytest.raises(TimeoutError):
            await writer.apply(
                _intent(),
                scope=scope,
                writer="legacy",
                writer_generation=1,
                connection_ref="legacy-a",
            )
    finally:
        route_repo._LOCAL_ROUTE_LOCK.release()
    assert gateway.calls == 0
    assert (
        await writer.apply(
            _intent(),
            scope=scope,
            writer="legacy",
            writer_generation=1,
            connection_ref="legacy-a",
        )
    ).applied


@pytest.mark.asyncio
async def test_postgres_lock_transaction_spans_gateway_call():
    scope = _scope()
    row = route_repo.TenantConnectorRoute(
        route_id="croute-test",
        **scope.model_dump(),
        mode="legacy_only",
        legacy_connection_ref="legacy-a",
        writer_generation=1,
        revision=1,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    class Connection:
        locked = False
        statements: list[str]

        def __init__(self):
            self.statements = []

        @asynccontextmanager
        async def transaction(self):
            self.locked = True
            try:
                yield
            finally:
                self.locked = False

        async def execute(self, sql):
            self.statements.append(sql)

        async def fetchrow(self, sql, *args):
            assert self.locked
            assert sql.endswith("FOR UPDATE")
            assert args == scope.key()
            self.statements.append(sql)
            return row.model_dump()

    class Pool:
        def __init__(self, conn):
            self.conn = conn

        @asynccontextmanager
        async def acquire(self):
            yield self.conn

    conn = Connection()
    routes = TenantRouteRepository()
    routes._pool = Pool(conn)
    routes._table_ensured = True

    class Gateway:
        async def apply(self, intent, *, mode_override):
            assert conn.locked
            assert mode_override == "enforce"
            await asyncio.sleep(0)
            assert conn.locked
            return MutationOutcome(mode="enforce", applied=True)

    result = await ConnectorGraphWriter(routes=routes, gateway=Gateway()).apply(
        _intent(),
        scope=scope,
        writer="legacy",
        writer_generation=1,
        connection_ref="legacy-a",
    )
    assert result.applied
    assert not conn.locked
    assert conn.statements[0] == "SET LOCAL idle_in_transaction_session_timeout = 0"
    assert "FOR UPDATE" in conn.statements[1]


def test_mutation_timeout_is_bounded():
    for invalid in (-1, 0, 46):
        with pytest.raises(ValueError, match="timeout"):
            ConnectorGraphWriter(mutation_timeout_seconds=invalid)


@pytest.mark.asyncio
async def test_postgres_writer_fence_blocks_transition_until_graph_returns(
    monkeypatch: pytest.MonkeyPatch,
):
    """Optional isolated PostgreSQL race check, never run against tenant data."""
    dsn = os.environ.get("AETHER_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("AETHER_TEST_DATABASE_URL is not configured")
    asyncpg = pytest.importorskip("asyncpg")
    scope = _scope(tenant_id=f"writer-test-{uuid4().hex}")
    pool = await asyncpg.create_pool(dsn, min_size=2, max_size=2)

    async def get_test_pool():
        return pool

    monkeypatch.setattr(route_repo, "get_pool", get_test_pool)
    routes = TenantRouteRepository()
    created = None
    release = asyncio.Event()
    started = asyncio.Event()

    class Gateway:
        async def apply(self, intent, *, mode_override):
            assert mode_override == "enforce"
            started.set()
            await release.wait()
            return MutationOutcome(mode="enforce", applied=True)

    try:
        created = await routes.create_legacy(
            scope, legacy_connection_ref="legacy-a", decision=_decision()
        )
        writer_task = asyncio.create_task(
            ConnectorGraphWriter(routes=routes, gateway=Gateway()).apply(
                _intent(tenant_id=scope.tenant_id),
                scope=scope,
                writer="legacy",
                writer_generation=1,
                connection_ref="legacy-a",
            )
        )
        await asyncio.wait_for(started.wait(), timeout=5)
        transition_task = asyncio.create_task(
            routes.compare_and_swap(
                scope,
                expected_revision=1,
                mode="new_primary",
                native_connection_ref="native-a",
                shadow_namespace=None,
                rollback_until=None,
                decision=_decision(),
            )
        )
        try:
            await asyncio.sleep(0.05)
            assert not transition_task.done()
        finally:
            release.set()
        assert (await writer_task).applied
        assert (await transition_task).writer_generation == 2
    finally:
        if created is not None:
            async with pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM tenant_connector_route_transitions WHERE route_id=$1",
                    created.route_id,
                )
                await conn.execute(
                    "DELETE FROM tenant_connector_routes WHERE route_id=$1",
                    created.route_id,
                )
        await pool.close()
