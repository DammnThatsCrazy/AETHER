"""
Security tests for attribution tenant isolation.

Verifies that JourneyStore keys on (tenant_id, user_id) so that touchpoints
recorded by Tenant A are never visible to Tenant B, even for the same user_id.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.attribution.resolver import JourneyStore  # noqa: E402


@pytest.fixture()
def store(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    return JourneyStore()


def _tp(channel: str = "social") -> dict:
    return {
        "channel": channel,
        "source": "test",
        "campaign": "",
        "event_type": "click",
        "timestamp": "2026-01-01T00:00:00+00:00",
    }


class TestJourneyStoreTenantIsolation:
    def test_tenant_a_touchpoints_not_visible_to_tenant_b(self, store):
        store.add("tenant_a", "user_1", _tp("organic"))
        assert store.get("tenant_b", "user_1") == []

    def test_tenant_b_touchpoints_not_visible_to_tenant_a(self, store):
        store.add("tenant_b", "user_1", _tp("paid"))
        assert store.get("tenant_a", "user_1") == []

    def test_same_user_different_tenants_independent(self, store):
        store.add("tenant_a", "user_1", _tp("social"))
        store.add("tenant_b", "user_1", _tp("email"))
        assert len(store.get("tenant_a", "user_1")) == 1
        assert store.get("tenant_a", "user_1")[0]["channel"] == "social"
        assert len(store.get("tenant_b", "user_1")) == 1
        assert store.get("tenant_b", "user_1")[0]["channel"] == "email"

    def test_clear_only_affects_own_tenant(self, store):
        store.add("tenant_a", "user_1", _tp())
        store.add("tenant_b", "user_1", _tp())
        store.clear("tenant_a", "user_1")
        assert store.get("tenant_a", "user_1") == []
        assert len(store.get("tenant_b", "user_1")) == 1

    def test_count_is_tenant_scoped(self, store):
        store.add("tenant_a", "user_1", _tp())
        store.add("tenant_a", "user_1", _tp())
        store.add("tenant_b", "user_1", _tp())
        assert store.count("tenant_a", "user_1") == 2
        assert store.count("tenant_b", "user_1") == 1

    def test_all_user_ids_scoped_to_tenant(self, store):
        store.add("tenant_a", "user_1", _tp())
        store.add("tenant_a", "user_2", _tp())
        store.add("tenant_b", "user_3", _tp())
        a_ids = store.all_user_ids("tenant_a")
        assert sorted(a_ids) == ["user_1", "user_2"]
        assert "user_3" not in a_ids

    def test_empty_store_returns_empty_list(self, store):
        assert store.get("tenant_x", "no_such_user") == []

    def test_clear_returns_correct_count(self, store):
        store.add("tenant_a", "user_1", _tp())
        store.add("tenant_a", "user_1", _tp())
        removed = store.clear("tenant_a", "user_1")
        assert removed == 2

    def test_clear_nonexistent_returns_zero(self, store):
        assert store.clear("tenant_a", "ghost_user") == 0


class TestJourneyStoreBlockedOutsideLocal:
    def test_raises_in_non_local_env(self, monkeypatch):
        monkeypatch.setenv("AETHER_ENV", "staging")
        monkeypatch.delenv("AETHER_ALLOW_INMEMORY_JOURNEY_STORE", raising=False)
        with pytest.raises(RuntimeError, match="JourneyStore is disabled"):
            JourneyStore()

    def test_override_allows_in_non_local(self, monkeypatch):
        monkeypatch.setenv("AETHER_ENV", "staging")
        monkeypatch.setenv("AETHER_ALLOW_INMEMORY_JOURNEY_STORE", "1")
        store = JourneyStore()
        store.add("t", "u", _tp())
        assert store.count("t", "u") == 1
