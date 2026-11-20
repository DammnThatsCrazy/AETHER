"""The commerce sweeps must find their tenants on the durable store too.

They used to enumerate tenants with ``store.receipts.all_tenants``, which only the
in-memory collection has, so against Postgres every sweep silently did nothing.
"""
from __future__ import annotations

import asyncio
import os

os.environ.setdefault("AETHER_ENV", "local")

from workers.runtime import specs  # noqa: E402
from value.x402.commerce_store import CommerceStore, TenantCollection, _RepoCollection  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


class _Row:
    def __init__(self, rid, tenant):
        self.receipt_id = rid
        self.tenant_id = tenant


def test_in_memory_store_lists_every_tenant_with_state():
    store = CommerceStore()
    assert isinstance(store.receipts, TenantCollection)
    _run(store.receipts.put("t1", _Row("r1", "t1")))
    _run(store.approvals.put("t2", type("A", (), {"approval_id": "a1"})()))
    assert _run(store.known_tenant_ids()) == ["t1", "t2"]


class _FakeRepo:
    def __init__(self, tenants):
        self._tenants = tenants

    async def distinct_tenant_ids(self, limit=10000):
        return list(self._tenants)


def test_durable_collections_report_tenants_from_the_table():
    store = CommerceStore()
    store.receipts = _RepoCollection(_FakeRepo(["t9"]), "receipt_id", object)
    store.approvals = _RepoCollection(_FakeRepo(["t3", "t9"]), "approval_id", object)
    store.entitlements = _RepoCollection(_FakeRepo([]), "entitlement_id", object)
    store.settlements = _RepoCollection(_FakeRepo(["t1"]), "settlement_id", object)
    assert _run(store.known_tenant_ids()) == ["t1", "t3", "t9"]


def _specs(commerce_enabled: bool):
    from types import SimpleNamespace

    settings = SimpleNamespace(
        intelligence_graph=SimpleNamespace(enable_commerce_control_plane=commerce_enabled)
    )
    return {s.name: s for s in specs.build_worker_specs(registry=SimpleNamespace(), settings=settings)}
