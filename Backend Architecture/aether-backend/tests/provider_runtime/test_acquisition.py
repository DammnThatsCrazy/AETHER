"""Tests for acquisition coordination (account discovery + selection)."""

from __future__ import annotations

from typing import Any, Optional

import pytest

from repositories.repos import reset_in_memory_stores
from shared.integration_contracts.acquisition import ProviderAccount
from shared.integration_contracts.lifecycle import ConnectionState
from shared.integration_contracts.results import AdapterResult

from services.provider_runtime.acquisition import (
    AcquisitionCoordinator,
    ProviderAccountRecord,
    ProviderAccountRepository,
)
from services.provider_runtime.connection import ProviderConnection
from services.provider_runtime.errors import PluginIncompatible, ProviderNotInstalled


# ── Test-local account adapter double (protocol-conforming) ──


class _FakeAccount:
    def __init__(
        self,
        discover: Optional[AdapterResult[list[ProviderAccount]]] = None,
        select: Optional[AdapterResult[Any]] = None,
    ) -> None:
        self._discover = discover or AdapterResult.ok(data=[])
        self._select = select or AdapterResult.ok(data={"detail": "ok"})
        self.discover_calls: list[Any] = []
        self.select_calls: list[tuple[Any, str]] = []

    async def discover_accounts(self, context) -> AdapterResult[list[ProviderAccount]]:
        self.discover_calls.append(context)
        return self._discover

    async def select_account(self, context, *, account_id: str) -> AdapterResult[Any]:
        self.select_calls.append((context, account_id))
        return self._select


class _FakePlugin:
    def __init__(self, account: Optional[_FakeAccount] = None) -> None:
        self._account = account or _FakeAccount()

    def account(self) -> _FakeAccount:
        return self._account


@pytest.fixture
def accounts() -> ProviderAccountRepository:
    reset_in_memory_stores()
    return ProviderAccountRepository()


@pytest.fixture
def coordinator(accounts: ProviderAccountRepository) -> AcquisitionCoordinator:
    return AcquisitionCoordinator(accounts=accounts)


def _connection(*, state: ConnectionState = ConnectionState.AVAILABLE) -> ProviderConnection:
    return ProviderConnection(
        connection_id="conn_1",
        tenant_id="tenant-1",
        provider_identity="shopify.orders.catalog",
        state=state,
        config={"shop": "myshop.myshopify.com"},
    )


@pytest.mark.asyncio
async def test_discover_accounts_persists_records(coordinator: AcquisitionCoordinator, accounts: ProviderAccountRepository):
    conn = _connection()
    plugin = _FakeAccount(
        discover=AdapterResult.ok(data=[
            ProviderAccount(account_id="acc_1", display_name="Main Store", currency="USD"),
            ProviderAccount(account_id="acc_2", display_name="EU Store", currency="EUR"),
        ])
    )
    result = await coordinator.discover_accounts(conn, plugin=_FakePlugin(account=plugin))

    assert result.success is True
    stored = await accounts.list_for_connection("conn_1")
    assert {r.account_id for r in stored} == {"conn_1:acc_1", "conn_1:acc_2"}
    assert stored[0].tenant_id == "tenant-1"
    assert stored[0].provider_identity == "shopify.orders.catalog"


@pytest.mark.asyncio
async def test_discover_accounts_builds_context(coordinator: AcquisitionCoordinator):
    conn = _connection()
    account = _FakeAccount(discover=AdapterResult.ok(data=[]))
    await coordinator.discover_accounts(conn, plugin=_FakePlugin(account=account))

    ctx = account.discover_calls[0]
    assert ctx.tenant_id == "tenant-1"
    assert ctx.connection_id == "conn_1"
    assert ctx.config == {"shop": "myshop.myshopify.com"}


@pytest.mark.asyncio
async def test_discover_accounts_failure_persists_nothing(
    coordinator: AcquisitionCoordinator, accounts: ProviderAccountRepository
):
    conn = _connection()
    plugin = _FakeAccount(
        discover=AdapterResult(success=False, status="permanent_error", error_code="not_supported")
    )
    result = await coordinator.discover_accounts(conn, plugin=_FakePlugin(account=plugin))

    assert result.success is False
    assert await accounts.list_for_connection("conn_1") == []


@pytest.mark.asyncio
async def test_select_account_appends_and_advances_state(coordinator: AcquisitionCoordinator):
    conn = _connection(state=ConnectionState.ACCOUNT_SELECTION_REQUIRED)
    updated = await coordinator.select_account(conn, account_id="acc_1", plugin=_FakePlugin())

    assert "acc_1" in updated.selected_accounts
    # ACCOUNT_SELECTION_REQUIRED advances to the next legal step.
    assert updated.state == ConnectionState.INITIAL_SYNC_PENDING
    assert updated.updated_at


@pytest.mark.asyncio
async def test_select_account_forwards_account_id_to_adapter(coordinator: AcquisitionCoordinator):
    conn = _connection(state=ConnectionState.ACCOUNT_SELECTION_REQUIRED)
    account = _FakeAccount()
    await coordinator.select_account(conn, account_id="acc_7", plugin=_FakePlugin(account=account))

    assert account.select_calls[0][1] == "acc_7"
    ctx = account.select_calls[0][0]
    assert ctx.account_id == "acc_7"


@pytest.mark.asyncio
async def test_select_account_enters_account_selection_required_from_verified(
    coordinator: AcquisitionCoordinator,
):
    conn = _connection(state=ConnectionState.VERIFIED)
    updated = await coordinator.select_account(conn, account_id="acc_1", plugin=_FakePlugin())
    # VERIFIED -> ACCOUNT_SELECTION_REQUIRED is a legal transition.
    assert updated.state == ConnectionState.ACCOUNT_SELECTION_REQUIRED
    assert "acc_1" in updated.selected_accounts


@pytest.mark.asyncio
async def test_select_account_failure_does_not_mutate(coordinator: AcquisitionCoordinator):
    conn = _connection(state=ConnectionState.ACCOUNT_SELECTION_REQUIRED)
    plugin = _FakeAccount(
        select=AdapterResult(success=False, status="permanent_error", error_code="invalid_account")
    )
    updated = await coordinator.select_account(conn, account_id="bad", plugin=_FakePlugin(account=plugin))

    assert updated.selected_accounts == []
    assert updated.state == ConnectionState.ACCOUNT_SELECTION_REQUIRED


@pytest.mark.asyncio
async def test_operations_require_plugin(coordinator: AcquisitionCoordinator):
    conn = _connection()
    with pytest.raises(ProviderNotInstalled):
        await coordinator.discover_accounts(conn)
    with pytest.raises(ProviderNotInstalled):
        await coordinator.select_account(conn, account_id="acc_1")


@pytest.mark.asyncio
async def test_plugin_without_account_capability_is_incompatible(
    coordinator: AcquisitionCoordinator,
):
    conn = _connection()

    class _NoAccountPlugin:
        def account(self):
            return None

    with pytest.raises(PluginIncompatible):
        await coordinator.discover_accounts(conn, plugin=_NoAccountPlugin())
    with pytest.raises(PluginIncompatible):
        await coordinator.select_account(conn, account_id="acc_1", plugin=_NoAccountPlugin())


@pytest.mark.asyncio
async def test_account_repo_round_trip(accounts: ProviderAccountRepository):
    rec = ProviderAccountRecord(
        account_id="conn_1:acc_1",
        tenant_id="tenant-1",
        connection_id="conn_1",
        provider_identity="shopify.orders.catalog",
        display_name="Main Store",
        external_id="ext_1",
        currency="USD",
        region="us-east",
    )
    await accounts.upsert(rec)
    found = await accounts.find("conn_1:acc_1")
    assert found is not None
    assert found.display_name == "Main Store"
    assert found.currency == "USD"
    assert found.external_id == "ext_1"
