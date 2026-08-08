"""Tests for the reconciliation engine (snapshot → per-type + aggregate checks)."""

from __future__ import annotations

from typing import Any, Optional

import pytest

from services.provider_runtime.errors import (
    ProviderNotInstalled,
    ReconciliationFailed,
)
from services.provider_runtime.reconciliation import ReconciliationEngine
from shared.integration_contracts.events import make_raw_record
from shared.integration_contracts.lifecycle import ConnectionState
from shared.integration_contracts.results import AdapterResult, AdapterStatus

IDENTITY = "shopify.orders.catalog"


class FakeRegistry:
    def __init__(self, plugins: dict[str, Any]) -> None:
        self._plugins = dict(plugins)

    def get(self, identity_key: str) -> Any:
        return self._plugins.get(identity_key)


class FakeBroker:
    async def reveal(self, tenant_id: str, ref: str) -> Any:
        return None


class FakeRawStore:
    """Matches RawProviderRecordStore.ingest(iterable) / count(*, tenant_id, ...)."""

    def __init__(self) -> None:
        self.records: list[Any] = []

    async def ingest(self, records, *, tenant_id=None) -> list[tuple[Any, bool]]:
        for record in records:
            self.records.append(record)
        return [(record, True) for record in records]

    async def count(self, *, tenant_id, provider_identity, provider_record_type=None) -> int:
        return sum(
            1
            for r in self.records
            if r.tenant_id == tenant_id
            and r.provider_identity == provider_identity
            and (provider_record_type is None or r.provider_record_type == provider_record_type)
        )


class FakeReconciliation:
    def __init__(self, result: AdapterResult[Any]) -> None:
        self._result = result
        self.snapshot_calls: list[tuple[Any, Any]] = []

    async def snapshot(self, context, since=None):
        self.snapshot_calls.append((context, since))
        return self._result


class FakePlugin:
    def __init__(self, *, reconciliation: Any = None) -> None:
        self._reconciliation = reconciliation

    def reconciliation(self) -> Any:
        return self._reconciliation


def make_connection() -> Any:
    from services.provider_runtime.connection import ProviderConnection
    return ProviderConnection(
        connection_id="conn_1",
        tenant_id="tenant-1",
        provider_identity=IDENTITY,
        state=ConnectionState.CONNECTED,
        credential_ref="provider:tenant-1:shopify.orders.catalog",
        selected_accounts=["acc_1"],
        config={"shop": "myshop.myshopify.com"},
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


def make_record(*, record_id: str, provider_record_type: str = "order") -> Any:
    return make_raw_record(
        provider_identity=IDENTITY,
        provider_record_id=record_id,
        provider_record_type=provider_record_type,
        payload={"id": record_id},
        tenant_id="tenant-1",
        connection_id="conn_1",
        account_id="acc_1",
        acquisition_mode="reconciliation",
    )


def make_engine(*, plugin: Any, raw_store: Any = None) -> ReconciliationEngine:
    return ReconciliationEngine(
        registry=FakeRegistry({IDENTITY: plugin}),
        raw_store=raw_store or FakeRawStore(),
        broker=FakeBroker(),
    )


@pytest.mark.asyncio
async def test_reconciliation_passes_when_counts_match():
    records = [make_record(record_id="o1"), make_record(record_id="o2")]
    plugin = FakePlugin(
        reconciliation=FakeReconciliation(AdapterResult.ok(records)),
    )
    raw_store = FakeRawStore()
    await raw_store.ingest(records)
    report = await make_engine(plugin=plugin, raw_store=raw_store).run(make_connection())

    assert report.passed is True
    assert report.provider_identity == IDENTITY
    assert report.account_id == "acc_1"
    assert report.run_at
    names = {c.name for c in report.checks}
    assert names == {"provider_record_type:order", "raw_store_aggregate"}
    for check in report.checks:
        assert check.status == "matched"


@pytest.mark.asyncio
async def test_reconciliation_detects_mismatched_counts():
    plugin = FakePlugin(
        reconciliation=FakeReconciliation(AdapterResult.ok([make_record(record_id="o1")])),
    )
    raw_store = FakeRawStore()
    await raw_store.ingest([
        make_record(record_id="o1"), make_record(record_id="o2"), make_record(record_id="o3"),
    ])
    report = await make_engine(plugin=plugin, raw_store=raw_store).run(make_connection())

    assert report.passed is False
    order_check = next(c for c in report.checks if c.name == "provider_record_type:order")
    assert order_check.status == "mismatched"
    assert order_check.expected == 3
    assert order_check.found == 1


@pytest.mark.asyncio
async def test_reconciliation_marks_snapshot_only_type_extra():
    snapshot = [
        make_record(record_id="o1", provider_record_type="order"),
        make_record(record_id="c1", provider_record_type="customer"),
    ]
    plugin = FakePlugin(reconciliation=FakeReconciliation(AdapterResult.ok(snapshot)))
    raw_store = FakeRawStore()
    await raw_store.ingest([make_record(record_id="o1", provider_record_type="order")])
    report = await make_engine(plugin=plugin, raw_store=raw_store).run(make_connection())

    customer_check = next(c for c in report.checks if c.name == "provider_record_type:customer")
    assert customer_check.status == "extra"  # provider has it, runtime does not
    assert customer_check.expected == 0
    assert customer_check.found == 1
    assert report.passed is False


@pytest.mark.asyncio
async def test_reconciliation_marks_runtime_only_records_missing():
    plugin = FakePlugin(
        reconciliation=FakeReconciliation(AdapterResult.ok([])),
    )
    raw_store = FakeRawStore()
    await raw_store.ingest([make_record(record_id="o1"), make_record(record_id="o2")])
    report = await make_engine(plugin=plugin, raw_store=raw_store).run(make_connection())

    aggregate = next(c for c in report.checks if c.name == "raw_store_aggregate")
    assert aggregate.status == "missing"  # runtime expected records, snapshot has none
    assert aggregate.expected == 2
    assert aggregate.found == 0
    assert report.passed is False


@pytest.mark.asyncio
async def test_reconciliation_passes_for_empty_account():
    plugin = FakePlugin(reconciliation=FakeReconciliation(AdapterResult.ok([])))
    raw_store = FakeRawStore()
    report = await make_engine(plugin=plugin, raw_store=raw_store).run(make_connection())
    assert report.passed is True
    assert report.checks  # the aggregate check still exists


@pytest.mark.asyncio
async def test_reconciliation_without_capability_fails():
    plugin = FakePlugin(reconciliation=None)
    with pytest.raises(ReconciliationFailed):
        await make_engine(plugin=plugin).run(make_connection())


@pytest.mark.asyncio
async def test_reconciliation_missing_plugin_raises():
    engine = ReconciliationEngine(
        registry=FakeRegistry({}), raw_store=FakeRawStore(), broker=FakeBroker(),
    )
    with pytest.raises(ProviderNotInstalled):
        await engine.run(make_connection())


@pytest.mark.asyncio
async def test_reconciliation_snapshot_failure_fails():
    plugin = FakePlugin(
        reconciliation=FakeReconciliation(
            AdapterResult(
                success=False, status=AdapterStatus.PERMANENT_ERROR, error_code="boom",
            )
        ),
    )
    with pytest.raises(ReconciliationFailed):
        await make_engine(plugin=plugin).run(make_connection())
