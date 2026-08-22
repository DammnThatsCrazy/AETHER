"""Tests for connection orchestration and the lifecycle state machine."""

from __future__ import annotations

from typing import Any, Optional
from unittest import mock

import pytest
from pydantic import SecretStr

from repositories.repos import reset_in_memory_stores
from shared.credentials.in_memory import InMemoryCredentialBackend
from shared.credentials.service import CredentialService
from shared.credentials.types import ApiKeyCredential
from shared.integration_contracts.lifecycle import ConnectionState, can_transition
from shared.integration_contracts.results import AdapterResult

from services.provider_runtime.connection import (
    ConnectionOrchestrator,
    ProviderConnection,
    ProviderConnectionRepository,
)
from services.provider_runtime.credential_broker import CredentialBroker
from services.provider_runtime.errors import (
    ConnectionStateViolation,
    PluginIncompatible,
    ProviderNotInstalled,
)


# ── Test-local plugin doubles (protocol-conforming; Team C owns the real plugin) ──


class _FakeAuth:
    def __init__(self, result: Optional[AdapterResult[Any]] = None) -> None:
        self._result = result or AdapterResult.ok(data={"detail": "ok"})
        self.calls: list[Any] = []

    async def test(self, context) -> AdapterResult[Any]:
        self.calls.append(context)
        return self._result


class _FakePlugin:
    def __init__(self, auth: Optional[_FakeAuth] = None) -> None:
        self._auth = auth or _FakeAuth()

    def auth(self) -> _FakeAuth:
        return self._auth


@pytest.fixture
def connections() -> ProviderConnectionRepository:
    reset_in_memory_stores()
    return ProviderConnectionRepository()


@pytest.fixture
def broker() -> CredentialBroker:
    return CredentialBroker(service=CredentialService(backend=InMemoryCredentialBackend(store={})))


@pytest.fixture
def orchestrator(
    connections: ProviderConnectionRepository, broker: CredentialBroker
) -> ConnectionOrchestrator:
    return ConnectionOrchestrator(connections=connections, broker=broker)


@pytest.mark.asyncio
async def test_create_connection_defaults_to_available(orchestrator: ConnectionOrchestrator):
    conn = await orchestrator.create_connection(
        tenant_id="tenant-1", provider_identity="shopify.orders.catalog", display_name="Shop"
    )
    assert conn.state == ConnectionState.AVAILABLE
    assert conn.tenant_id == "tenant-1"
    assert conn.provider_identity == "shopify.orders.catalog"
    assert conn.created_at and conn.updated_at


@pytest.mark.asyncio
async def test_create_connection_is_persisted(orchestrator: ConnectionOrchestrator, connections: ProviderConnectionRepository):
    conn = await orchestrator.create_connection(
        tenant_id="tenant-1", provider_identity="shopify.orders.catalog"
    )
    found = await connections.find(conn.connection_id)
    assert found is not None
    assert found.connection_id == conn.connection_id
    assert found.tenant_id == "tenant-1"


@pytest.mark.asyncio
async def test_store_credential_moves_to_credentials_received(
    orchestrator: ConnectionOrchestrator,
):
    conn = await orchestrator.create_connection(
        tenant_id="tenant-1", provider_identity="shopify.orders.catalog"
    )
    cred = ApiKeyCredential(api_key=SecretStr("sk_live_abc"))
    updated = await orchestrator.store_credential(conn, cred)

    assert updated.credential_ref == "provider:tenant-1:shopify.orders.catalog"
    assert updated.state == ConnectionState.CREDENTIALS_RECEIVED
    # Ref is stored, secret is not.
    assert "sk_live_abc" not in updated.credential_ref


@pytest.mark.asyncio
async def test_store_credential_resolves_through_broker(
    orchestrator: ConnectionOrchestrator,
):
    conn = await orchestrator.create_connection(
        tenant_id="tenant-1", provider_identity="shopify.orders.catalog"
    )
    await orchestrator.store_credential(conn, ApiKeyCredential(api_key=SecretStr("sk_live_abc")))
    resolved = await orchestrator.broker.resolve(conn.tenant_id, conn.credential_ref)
    assert resolved is not None
    assert resolved.api_key.get_secret_value() == "sk_live_abc"


@pytest.mark.asyncio
async def test_test_connection_success_reaches_verified(orchestrator: ConnectionOrchestrator):
    conn = await orchestrator.create_connection(
        tenant_id="tenant-1", provider_identity="shopify.orders.catalog"
    )
    await orchestrator.store_credential(conn, ApiKeyCredential(api_key=SecretStr("sk_live_abc")))

    plugin = _FakePlugin(auth=_FakeAuth(result=AdapterResult.ok(data={"detail": "ok"})))
    result = await orchestrator.test_connection(conn, plugin=plugin)

    assert result.success is True
    assert conn.state == ConnectionState.VERIFIED
    assert conn.last_verified_at is not None
    assert plugin.auth().calls, "auth().test should have been invoked with a context"


@pytest.mark.asyncio
async def test_test_connection_builds_acquisition_context(orchestrator: ConnectionOrchestrator):
    conn = await orchestrator.create_connection(
        tenant_id="tenant-1",
        provider_identity="shopify.orders.catalog",
        config={"shop": "myshop.myshopify.com"},
    )
    await orchestrator.store_credential(conn, ApiKeyCredential(api_key=SecretStr("sk_live_abc")))

    auth = _FakeAuth(result=AdapterResult.ok(data={"detail": "ok"}))
    await orchestrator.test_connection(conn, plugin=_FakePlugin(auth=auth))

    ctx = auth.calls[0]
    assert ctx.tenant_id == "tenant-1"
    assert ctx.provider_identity == "shopify.orders.catalog"
    assert ctx.connection_id == conn.connection_id
    assert ctx.config == {"shop": "myshop.myshopify.com"}
    assert ctx.credential is not None


@pytest.mark.asyncio
async def test_test_connection_failure_moves_to_failed(orchestrator: ConnectionOrchestrator):
    conn = await orchestrator.create_connection(
        tenant_id="tenant-1", provider_identity="shopify.orders.catalog"
    )
    await orchestrator.store_credential(conn, ApiKeyCredential(api_key=SecretStr("sk_live_abc")))

    plugin = _FakePlugin(
        auth=_FakeAuth(
            result=AdapterResult(
                success=False, status="permanent_error", error_code="invalid_credentials"
            )
        )
    )
    result = await orchestrator.test_connection(conn, plugin=plugin)
    assert result.success is False
    assert conn.state == ConnectionState.FAILED


@pytest.mark.asyncio
async def test_test_connection_requires_plugin(orchestrator: ConnectionOrchestrator):
    conn = await orchestrator.create_connection(
        tenant_id="tenant-1", provider_identity="shopify.orders.catalog"
    )
    with pytest.raises(ProviderNotInstalled):
        await orchestrator.test_connection(conn)


@pytest.mark.asyncio
async def test_test_connection_plugin_without_auth_is_incompatible(
    orchestrator: ConnectionOrchestrator,
):
    conn = await orchestrator.create_connection(
        tenant_id="tenant-1", provider_identity="shopify.orders.catalog"
    )
    class _NoAuthPlugin:
        def auth(self):
            return None
    with pytest.raises(PluginIncompatible):
        await orchestrator.test_connection(conn, plugin=_NoAuthPlugin())


@pytest.mark.asyncio
async def test_test_connection_retest_refreshes_last_verified_at(
    orchestrator: ConnectionOrchestrator,
):
    conn = await orchestrator.create_connection(
        tenant_id="tenant-1", provider_identity="shopify.orders.catalog"
    )
    await orchestrator.store_credential(conn, ApiKeyCredential(api_key=SecretStr("sk_live_abc")))
    plugin = _FakePlugin(auth=_FakeAuth(result=AdapterResult.ok(data={"detail": "ok"})))
    await orchestrator.test_connection(conn, plugin=plugin)
    assert conn.state == ConnectionState.VERIFIED
    first = conn.last_verified_at
    await orchestrator.test_connection(conn, plugin=plugin)  # re-test while VERIFIED
    assert conn.last_verified_at is not None
    assert conn.last_verified_at >= first


def test_transition_guards_illegal_moves(orchestrator: ConnectionOrchestrator):
    conn = ProviderConnection(
        connection_id="conn_x",
        tenant_id="tenant-1",
        provider_identity="shopify.orders.catalog",
        state=ConnectionState.VERIFIED,
    )
    with pytest.raises(ConnectionStateViolation):
        orchestrator.transition(conn, ConnectionState.VERIFYING)  # illegal: VERIFIED -> VERIFYING


def test_transition_allows_legal_moves(orchestrator: ConnectionOrchestrator):
    conn = ProviderConnection(
        connection_id="conn_x",
        tenant_id="tenant-1",
        provider_identity="shopify.orders.catalog",
        state=ConnectionState.CREDENTIALS_RECEIVED,
    )
    updated = orchestrator.transition(conn, ConnectionState.VERIFYING)
    assert updated.state == ConnectionState.VERIFYING
    assert updated.updated_at


def test_connection_state_transition_table_has_expected_paths():
    assert can_transition(ConnectionState.AVAILABLE, ConnectionState.CREDENTIALS_RECEIVED)
    assert can_transition(ConnectionState.CREDENTIALS_RECEIVED, ConnectionState.VERIFYING)
    assert can_transition(ConnectionState.VERIFYING, ConnectionState.VERIFIED)


@pytest.mark.asyncio
async def test_run_sync_delegates_to_pull_scheduler(orchestrator: ConnectionOrchestrator):
    """The D↔E seam: run_sync lazy-imports Team E's PullScheduler and delegates."""
    conn = await orchestrator.create_connection(
        tenant_id="tenant-1", provider_identity="shopify.orders.catalog"
    )
    captured: dict = {}

    class _FakeScheduler:
        async def run(self, *, connection, since=None):
            captured["connection_id"] = connection.connection_id
            captured["since"] = since
            return {"status": "completed"}

    with mock.patch(
        "services.provider_runtime.scheduler.PullScheduler", _FakeScheduler
    ):
        result = await orchestrator.run_sync(conn, since="2026-08-08T00:00:00+00:00")

    assert captured["connection_id"] == conn.connection_id
    assert captured["since"] == "2026-08-08T00:00:00+00:00"
    assert result == {"status": "completed"}


@pytest.mark.asyncio
async def test_list_for_tenant(connections: ProviderConnectionRepository):
    reset_in_memory_stores()
    repo = ProviderConnectionRepository()
    c1 = ProviderConnection(connection_id="c1", tenant_id="tenant-1", provider_identity="a.x.y")
    c2 = ProviderConnection(connection_id="c2", tenant_id="tenant-1", provider_identity="b.x.y")
    c3 = ProviderConnection(connection_id="c3", tenant_id="tenant-2", provider_identity="a.x.y")
    for c in (c1, c2, c3):
        await repo.upsert(c)
    rows = await repo.list_for_tenant("tenant-1")
    assert {r.connection_id for r in rows} == {"c1", "c2"}


@pytest.mark.asyncio
async def test_upsert_preserves_created_at_on_update(connections: ProviderConnectionRepository):
    reset_in_memory_stores()
    repo = ProviderConnectionRepository()
    conn = ProviderConnection(
        connection_id="c1",
        tenant_id="tenant-1",
        provider_identity="a.x.y",
        created_at="2026-08-08T00:00:00+00:00",
    )
    await repo.upsert(conn)
    conn.display_name = "Renamed"
    conn.updated_at = ""
    await repo.upsert(conn)
    stored = await repo.find("c1")
    assert stored is not None
    assert stored.display_name == "Renamed"
    assert stored.created_at == "2026-08-08T00:00:00+00:00"
