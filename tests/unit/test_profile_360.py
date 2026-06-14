"""Unit tests for the Profile 360 aggregator and credit consent gate.

Covers:
- Profile360Aggregator.wallets() — envelope shape, tenant isolation
- Profile360Aggregator.summary() — envelope shape, graceful degradation
- Profile360Aggregator.quality() — completeness scoring, readiness_status
- Profile360Aggregator.data_freshness() — dimension array, stale flags
- Profile360Aggregator.delegations() — granted + received with direction
- Profile360Aggregator.agents() — agent configs with execution counts
- Pagination shape on all paginated methods
- Credit consent hard gate on /web2 and /economic/web2 routes (HTTP 403 / 200)
"""
from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
_PREFIXES = ("config", "services", "shared", "middleware", "dependencies", "repositories")


@contextmanager
def backend_module_path():
    original = list(sys.path)
    for prefix in _PREFIXES:
        for name in list(sys.modules):
            if name == prefix or name.startswith(f"{prefix}."):
                sys.modules.pop(name, None)
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original
        for prefix in _PREFIXES:
            for name in list(sys.modules):
                if name == prefix or name.startswith(f"{prefix}."):
                    sys.modules.pop(name, None)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture()
def agg(monkeypatch):
    """Fresh Profile360Aggregator backed by isolated in-memory repositories."""
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    with backend_module_path():
        repos_mod = importlib.import_module("repositories.repos")
        repos_mod.reset_in_memory_stores()
        mod = importlib.import_module("services.profile.aggregator")
        yield mod.Profile360Aggregator()
        repos_mod.reset_in_memory_stores()


# ── Wallets ───────────────────────────────────────────────────────────────────


class TestWallets:
    async def test_returns_envelope_shape(self, agg):
        result = await agg.wallets("ent_1", "tenant_a")
        assert result["kind"] == "wallets"
        assert "items" in result
        assert "summary" in result
        assert "pagination" in result
        assert "provenance" in result
        assert "computed_at" in result

    async def test_pagination_keys_present(self, agg):
        result = await agg.wallets("ent_1", "tenant_a", limit=10)
        p = result["pagination"]
        assert "limit" in p
        assert "count" in p
        assert "has_more" in p

    async def test_empty_entity_returns_empty_items(self, agg):
        result = await agg.wallets("no_such_entity", "tenant_a")
        assert result["items"] == []
        assert result["summary"]["wallet_count"] == 0

    async def test_wallet_shows_up_for_correct_tenant(self, agg):
        await agg._wallets.link_wallet(
            "w1", "ent_1", "tenant_a", chain="ethereum", address="0xAAA"
        )
        result = await agg.wallets("ent_1", "tenant_a")
        assert len(result["items"]) == 1
        assert result["items"][0]["address"] == "0xAAA"

    async def test_tenant_isolation_wallet(self, agg):
        await agg._wallets.link_wallet(
            "w2", "ent_1", "tenant_b", chain="ethereum", address="0xBBB"
        )
        # tenant_a query must not see tenant_b's wallet
        result = await agg.wallets("ent_1", "tenant_a")
        addresses = [i["address"] for i in result["items"]]
        assert "0xBBB" not in addresses

    async def test_has_more_false_when_below_limit(self, agg):
        result = await agg.wallets("ent_2", "tenant_a", limit=100)
        assert result["pagination"]["has_more"] is False


# ── Summary ───────────────────────────────────────────────────────────────────


class TestSummary:
    async def test_returns_expected_top_level_keys(self, agg):
        result = await agg.summary("ent_1", "tenant_a")
        assert result["kind"] == "summary"
        assert "snapshot" in result
        assert "entity_id" in result
        assert "tenant_id" in result
        assert "computed_at" in result
        assert "provenance" in result

    async def test_snapshot_has_counts_block(self, agg):
        result = await agg.summary("ent_1", "tenant_a")
        snap = result["snapshot"]
        assert "counts" in snap
        counts = snap["counts"]
        for key in ("agents", "wallets", "transfers", "delegations_granted",
                    "delegations_received", "active_delegations_granted",
                    "active_delegations_received", "journey_chains", "agent_executions"):
            assert key in counts

    async def test_graceful_degradation_on_wallet_repo_failure(self, agg, monkeypatch):
        broken = AsyncMock()
        broken.find_many = AsyncMock(side_effect=Exception("db down"))
        # Patch the internal wallet repo
        agg._wallets = broken
        result = await agg.summary("ent_1", "tenant_a")
        # Must still return a valid summary, not raise
        assert result["kind"] == "summary"
        assert result["snapshot"]["counts"]["wallets"] == 0

    async def test_summary_entity_tenant_guard(self, agg):
        # Insert entity under tenant_b; summary for tenant_a must not expose it
        await agg._entities.create_entity("ent_cross", "tenant_b", "human", "Cross-tenant")
        result = await agg.summary("ent_cross", "tenant_a")
        # The normalized entity dict should reflect tenant_a (not the foreign
        # tenant_b row), and `known` should be False because no entity was found
        entity_block = result["snapshot"].get("entity", {})
        assert entity_block.get("known") is False


# ── Quality ───────────────────────────────────────────────────────────────────


class TestQuality:
    async def test_empty_entity_has_zero_completeness(self, agg):
        result = await agg.quality("ghost_entity", "tenant_a")
        assert result["completeness"] == 0.0
        assert result["readiness_status"] == "incomplete"
        assert result["kind"] == "quality"

    async def test_fully_populated_entity_has_high_completeness(self, agg):
        eid = "ent_full"
        tid = "tenant_a"
        # Entity
        await agg._entities.create_entity(eid, tid, "human", "Full Entity")
        # Behavior
        await agg._behavior.insert(eid, {"entity_id": eid, "tenant_id": tid, "risk_score": 0.1})
        # Wallet
        await agg._wallets.link_wallet("wf1", eid, tid, "ethereum", "0xFFF")
        # Transfer
        await agg._transfers.insert("tf1", {"from_entity_id": eid, "tenant_id": tid, "amount": 100})
        result = await agg.quality(eid, tid)
        assert result["completeness"] == 1.0
        assert result["readiness_status"] == "ready"

    async def test_quality_missing_dimensions_listed(self, agg):
        eid = "ent_partial"
        tid = "tenant_a"
        # Only entity row, nothing else
        await agg._entities.create_entity(eid, tid, "human", "Partial Entity")
        result = await agg.quality(eid, tid)
        assert "entity" in result["present_dimensions"]
        for dim in ("behavior", "wallets", "transfers"):
            assert dim in result["missing_dimensions"]

    async def test_quality_has_required_keys(self, agg):
        result = await agg.quality("any_ent", "tenant_a")
        for key in ("kind", "completeness", "present_dimensions", "missing_dimensions",
                    "readiness_status", "computed_at", "provenance"):
            assert key in result


# ── Data Freshness ────────────────────────────────────────────────────────────


class TestDataFreshness:
    async def test_returns_dict_with_dimensions_key(self, agg):
        result = await agg.data_freshness("ent_1", "tenant_a")
        assert isinstance(result, dict)
        assert "dimensions" in result

    async def test_empty_entity_has_empty_dimensions(self, agg):
        result = await agg.data_freshness("no_data_entity", "tenant_a")
        assert result["dimensions"] == []

    async def test_dimension_has_required_keys(self, agg):
        eid = "ent_fresh"
        tid = "tenant_a"
        await agg._entities.create_entity(eid, tid, "human", "Fresh Entity")
        result = await agg.data_freshness(eid, tid)
        assert len(result["dimensions"]) >= 1
        dim = result["dimensions"][0]
        assert "dimension" in dim
        assert "stale" in dim
        assert "source" in dim


# ── Delegations ───────────────────────────────────────────────────────────────


class TestDelegations:
    async def test_returns_envelope(self, agg):
        result = await agg.delegations("ent_1", "tenant_a")
        assert result["kind"] == "delegations"
        assert "items" in result
        assert "pagination" in result

    async def test_delegation_direction_field_present(self, agg):
        eid = "ent_del"
        tid = "tenant_a"
        await agg._delegations.insert("del1", {
            "delegation_id": "del1",
            "grantor_entity_id": eid,
            "grantee_entity_id": "ent_grantee",
            "tenant_id": tid,
            "scope": ["read"],
            "created_at": _now_iso(),
        })
        result = await agg.delegations(eid, tid)
        assert len(result["items"]) >= 1
        item = next((i for i in result["items"] if i.get("id") == "del1"), None)
        assert item is not None
        assert "direction" in item

    async def test_delegations_pagination_shape(self, agg):
        result = await agg.delegations("ent_x", "tenant_a")
        p = result["pagination"]
        assert "limit" in p
        assert "count" in p
        assert "has_more" in p


# ── Agents ────────────────────────────────────────────────────────────────────


class TestAgents:
    async def test_returns_envelope(self, agg):
        result = await agg.agents("ent_1", "tenant_a")
        assert result["kind"] == "agents"
        assert "items" in result

    async def test_agent_config_appears_in_items(self, agg):
        eid = "ent_agent_owner"
        tid = "tenant_a"
        await agg._agent_configs.insert("ac1", {
            "agent_id": "ac1",
            "owner_entity_id": eid,
            "tenant_id": tid,
            "agent_name": "MyAgent",
            "created_at": _now_iso(),
        })
        result = await agg.agents(eid, tid)
        ids = [i.get("id") for i in result["items"]]
        assert "ac1" in ids


# ── Credit Consent Gate ───────────────────────────────────────────────────────


class TestCreditConsentGate:
    """Verify the hard credit-consent gate on /web2 and /economic/web2 routes."""

    def _make_tenant(self, tenant_id: str, permissions=("read",)):
        from unittest.mock import MagicMock
        t = MagicMock()
        t.tenant_id = tenant_id
        t.require_permission = MagicMock()
        return t

    def _make_request(self, tenant):
        from unittest.mock import MagicMock
        req = MagicMock()
        req.state.tenant = tenant
        return req

    async def test_web2_returns_403_without_credit_consent(self, monkeypatch):
        monkeypatch.setenv("AETHER_ENV", "local")
        monkeypatch.setenv("JWT_SECRET", "test-secret")
        with backend_module_path():
            from fastapi import HTTPException
            from services.profile.routes import get_web2
            from repositories.repos import ConsentRepository
            from services.profile.intelligence import IntelligenceAggregator

            # Consent repo with no records (deny-by-default)
            consent_repo = ConsentRepository()
            intel = IntelligenceAggregator()
            tenant = self._make_tenant("tenant_a")
            request = self._make_request(tenant)

            with pytest.raises(HTTPException) as exc_info:
                await get_web2(
                    user_id="user_no_credit",
                    request=request,
                    window="30d",
                    intel=intel,
                    consent_repo=consent_repo,
                )
            assert exc_info.value.status_code == 403
            assert "credit" in exc_info.value.detail.lower()

    async def test_web2_returns_data_with_credit_consent(self, monkeypatch):
        monkeypatch.setenv("AETHER_ENV", "local")
        monkeypatch.setenv("JWT_SECRET", "test-secret")
        with backend_module_path():
            from services.profile.routes import get_web2
            from repositories.repos import ConsentRepository
            from services.profile.intelligence import IntelligenceAggregator

            consent_repo = ConsentRepository()
            # Grant credit consent
            await consent_repo.insert(f"tenant_a:user_with_credit", {
                "tenant_id": "tenant_a",
                "user_id": "user_with_credit",
                "granted": True,
                "purposes": ["credit"],
            })

            intel = IntelligenceAggregator()
            tenant = self._make_tenant("tenant_a")
            request = self._make_request(tenant)

            # Should NOT raise; returns an APIResponse dict
            result = await get_web2(
                user_id="user_with_credit",
                request=request,
                window="30d",
                intel=intel,
                consent_repo=consent_repo,
            )
            assert result is not None

    async def test_economic_web2_returns_403_without_credit_consent(self, monkeypatch):
        monkeypatch.setenv("AETHER_ENV", "local")
        monkeypatch.setenv("JWT_SECRET", "test-secret")
        with backend_module_path():
            from fastapi import HTTPException
            from services.profile.routes import get_economic_web2
            from repositories.repos import ConsentRepository
            from services.profile.intelligence import IntelligenceAggregator

            consent_repo = ConsentRepository()
            intel = IntelligenceAggregator()
            tenant = self._make_tenant("tenant_a")
            request = self._make_request(tenant)

            with pytest.raises(HTTPException) as exc_info:
                await get_economic_web2(
                    user_id="user_no_credit",
                    request=request,
                    window="30d",
                    intel=intel,
                    consent_repo=consent_repo,
                )
            assert exc_info.value.status_code == 403
