"""
Tests for tenant isolation in the shared store and repository layers.

Covers:
  - Tenant A cannot access Tenant B's data
  - Empty tenant_id is rejected / returns no cross-tenant leakage
  - Queries are always scoped by tenant
  - Repository find_many filters by tenant_id
"""

from __future__ import annotations

import asyncio
import importlib
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"


@contextmanager
def backend_module_path():
    original_path = list(sys.path)
    original_mods = set(sys.modules.keys())
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original_path
        for name in list(sys.modules):
            if name not in original_mods:
                sys.modules.pop(name, None)


@pytest.fixture()
def store_module(monkeypatch):
    """Import the shared store module in local mode."""
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("AETHER_ALLOW_INMEMORY_STORE", "1")
    monkeypatch.delenv("REDIS_HOST", raising=False)

    with backend_module_path():
        mod = importlib.import_module("shared.store")
        importlib.reload(mod)
        # Clear the singleton cache so tests start fresh
        mod._stores.clear()
        yield mod
        mod._stores.clear()


@pytest.fixture()
def repo_module(monkeypatch):
    """Import the repositories module in local mode."""
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with backend_module_path():
        mod = importlib.import_module("repositories.repos")
        importlib.reload(mod)
        yield mod


# ═══════════════════════════════════════════════════════════════════════════
# SHARED STORE — TENANT ISOLATION
# ═══════════════════════════════════════════════════════════════════════════


class TestStoreTenantisolation:
    """Verify that InMemoryStore.find() scopes results by tenant_id."""

    def test_find_scoped_by_tenant(self, store_module):
        store = store_module.InMemoryStore("test_isolation")

        asyncio.run(store.set("rec-1", {"tenant_id": "tenant-A", "value": "a1"}))
        asyncio.run(store.set("rec-2", {"tenant_id": "tenant-A", "value": "a2"}))
        asyncio.run(store.set("rec-3", {"tenant_id": "tenant-B", "value": "b1"}))

        results_a = asyncio.run(store.find(tenant_id="tenant-A"))
        results_b = asyncio.run(store.find(tenant_id="tenant-B"))

        assert len(results_a) == 2
        assert all(r["tenant_id"] == "tenant-A" for r in results_a)
        assert len(results_b) == 1
        assert results_b[0]["tenant_id"] == "tenant-B"

    def test_tenant_a_cannot_see_tenant_b_data(self, store_module):
        store = store_module.InMemoryStore("test_crossleak")

        asyncio.run(store.set("secret-data", {"tenant_id": "tenant-B", "pii": "ssn-xxx"}))

        results = asyncio.run(store.find(tenant_id="tenant-A"))
        assert len(results) == 0
        # Explicitly verify no tenant-B data leaked
        for r in results:
            assert r.get("tenant_id") != "tenant-B"

    def test_empty_tenant_id_returns_nothing_from_other_tenants(self, store_module):
        store = store_module.InMemoryStore("test_empty_tenant")

        asyncio.run(store.set("rec-1", {"tenant_id": "tenant-A", "value": "secret"}))
        asyncio.run(store.set("rec-2", {"tenant_id": "", "value": "orphan"}))

        results = asyncio.run(store.find(tenant_id=""))
        assert len(results) == 1
        assert results[0]["value"] == "orphan"
        # Must not include tenant-A data
        assert all(r.get("tenant_id") == "" for r in results)

    def test_count_respects_tenant_filter(self, store_module):
        store = store_module.InMemoryStore("test_count_tenant")

        asyncio.run(store.set("r1", {"tenant_id": "t-X", "type": "event"}))
        asyncio.run(store.set("r2", {"tenant_id": "t-X", "type": "event"}))
        asyncio.run(store.set("r3", {"tenant_id": "t-Y", "type": "event"}))

        count_x = asyncio.run(store.count(tenant_id="t-X"))
        count_y = asyncio.run(store.count(tenant_id="t-Y"))
        count_all = asyncio.run(store.count())

        assert count_x == 2
        assert count_y == 1
        assert count_all == 3

    def test_delete_does_not_affect_other_tenant(self, store_module):
        store = store_module.InMemoryStore("test_delete_iso")

        asyncio.run(store.set("shared-key", {"tenant_id": "t-A", "v": 1}))
        asyncio.run(store.set("other-key", {"tenant_id": "t-B", "v": 2}))

        asyncio.run(store.delete("shared-key"))

        assert asyncio.run(store.get("shared-key")) is None
        assert asyncio.run(store.get("other-key")) is not None
        assert asyncio.run(store.get("other-key"))["tenant_id"] == "t-B"


# ═══════════════════════════════════════════════════════════════════════════
# REPOSITORY — TENANT ISOLATION
# ═══════════════════════════════════════════════════════════════════════════


class TestRepositoryTenantIsolation:
    """Verify BaseRepository.find_many scopes by tenant_id in-memory."""

    def test_find_many_filters_by_tenant(self, repo_module):
        repo = repo_module.BaseRepository.__new__(repo_module.BaseRepository)
        repo.table_name = "test_table"
        repo._store = {}
        repo._pool = None
        repo._table_ensured = False

        asyncio.run(repo.insert("id-1", {"tenant_id": "t-A", "name": "Alice"}))
        asyncio.run(repo.insert("id-2", {"tenant_id": "t-A", "name": "Bob"}))
        asyncio.run(repo.insert("id-3", {"tenant_id": "t-B", "name": "Charlie"}))

        results_a = asyncio.run(repo.find_many(filters={"tenant_id": "t-A"}))
        results_b = asyncio.run(repo.find_many(filters={"tenant_id": "t-B"}))

        assert len(results_a) == 2
        assert all(r["tenant_id"] == "t-A" for r in results_a)
        assert len(results_b) == 1
        assert results_b[0]["name"] == "Charlie"

    def test_cross_tenant_find_returns_empty(self, repo_module):
        repo = repo_module.BaseRepository.__new__(repo_module.BaseRepository)
        repo.table_name = "test_cross"
        repo._store = {}
        repo._pool = None
        repo._table_ensured = False

        asyncio.run(repo.insert("id-1", {"tenant_id": "t-A", "secret": "data"}))

        results = asyncio.run(repo.find_many(filters={"tenant_id": "t-NONEXISTENT"}))
        assert len(results) == 0

    def test_count_with_tenant_filter(self, repo_module):
        repo = repo_module.BaseRepository.__new__(repo_module.BaseRepository)
        repo.table_name = "test_count"
        repo._store = {}
        repo._pool = None
        repo._table_ensured = False

        asyncio.run(repo.insert("id-1", {"tenant_id": "t-A"}))
        asyncio.run(repo.insert("id-2", {"tenant_id": "t-A"}))
        asyncio.run(repo.insert("id-3", {"tenant_id": "t-B"}))

        assert asyncio.run(repo.count(filters={"tenant_id": "t-A"})) == 2
        assert asyncio.run(repo.count(filters={"tenant_id": "t-B"})) == 1
        assert asyncio.run(repo.count()) == 3

    def test_delete_by_entity_scoped_correctly(self, repo_module):
        repo = repo_module.BaseRepository.__new__(repo_module.BaseRepository)
        repo.table_name = "test_entity_delete"
        repo._store = {}
        repo._pool = None
        repo._table_ensured = False

        asyncio.run(repo.insert("id-1", {"tenant_id": "t-A", "user_id": "u-1"}))
        asyncio.run(repo.insert("id-2", {"tenant_id": "t-A", "user_id": "u-2"}))
        asyncio.run(repo.insert("id-3", {"tenant_id": "t-B", "user_id": "u-1"}))

        deleted = asyncio.run(repo.delete_by_entity("user_id", "u-1"))
        assert deleted == 2

        # Only u-2 record should remain
        remaining = asyncio.run(repo.find_many())
        assert len(remaining) == 1
        assert remaining[0]["user_id"] == "u-2"


# ═══════════════════════════════════════════════════════════════════════════
# TENANT CONTEXT — PERMISSION ISOLATION
# ═══════════════════════════════════════════════════════════════════════════


class TestTenantContextIsolation:
    """Verify that TenantContext enforces per-tenant permissions."""

    def test_different_tenants_have_independent_permissions(self, monkeypatch):
        monkeypatch.setenv("AETHER_ENV", "local")
        monkeypatch.setenv("JWT_SECRET", "test-secret")

        with backend_module_path():
            common_mod = importlib.import_module("shared.common.common")
            auth_mod = importlib.import_module("shared.auth.auth")

            ctx_a = auth_mod.TenantContext(
                tenant_id="t-A",
                role=auth_mod.Role.VIEWER,
                permissions=["read"],
            )
            ctx_b = auth_mod.TenantContext(
                tenant_id="t-B",
                role=auth_mod.Role.EDITOR,
                permissions=["read", "write"],
            )

            assert ctx_a.has_permission("write") is False
            assert ctx_b.has_permission("write") is True

            with pytest.raises(common_mod.ForbiddenError):
                ctx_a.require_permission("write")

            # Should not raise for tenant B
            ctx_b.require_permission("write")
