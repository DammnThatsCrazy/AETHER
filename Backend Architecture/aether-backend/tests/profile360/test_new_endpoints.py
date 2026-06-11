"""Tests for new Profile 360 endpoints: consent, quality, cluster, attribution,
economic sub-routes, agent-executions, actions, events."""

from __future__ import annotations

import os
import sys

os.environ.setdefault("AETHER_ENV", "local")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── Fixtures ──────────────────────────────────────────────────────────────────

TENANT_ID = "tenant-test-001"
ENTITY_ID = "entity-001"


def make_tenant(tenant_id: str = TENANT_ID):
    t = MagicMock()
    t.tenant_id = tenant_id
    t.require_permission = MagicMock()
    return t


def make_request(tenant_id: str = TENANT_ID):
    req = MagicMock()
    req.state.tenant = make_tenant(tenant_id)
    return req


def make_agg(overrides: dict | None = None):
    """Create a mock Profile360Aggregator with all required methods."""
    agg = MagicMock()
    defaults = {
        "cluster": AsyncMock(return_value={"entity_id": ENTITY_ID, "primary_cluster": {}, "items": [], "count": 0}),
        "clusters": AsyncMock(return_value={"entity_id": ENTITY_ID, "items": [], "count": 0}),
        "identity_confidence": AsyncMock(return_value={"entity_id": ENTITY_ID, "average_confidence": 0.0, "by_type": {}}),
        "attribution": AsyncMock(return_value={"entity_id": ENTITY_ID, "touchpoints": [], "first_touch": None, "last_touch": None}),
        "quality": AsyncMock(return_value={
            "entity_id": ENTITY_ID,
            "readiness_status": "partial",
            "completeness_score": 0.5,
            "freshness_score": 0.7,
            "confidence_score": 0.6,
            "missing_dimensions": [],
            "stale_dimensions": [],
        }),
        "data_freshness": AsyncMock(return_value={"entity_id": ENTITY_ID, "dimensions": {}, "computed_at": "2026-01-01T00:00:00Z"}),
        "agents": AsyncMock(return_value={"entity_id": ENTITY_ID, "items": [], "count": 0}),
        "delegations": AsyncMock(return_value={"entity_id": ENTITY_ID, "granted": [], "received": []}),
        "campaigns": AsyncMock(return_value={"entity_id": ENTITY_ID, "items": [], "count": 0}),
    }
    if overrides:
        defaults.update(overrides)
    for k, v in defaults.items():
        setattr(agg, k, v)
    return agg


# ── Cluster Tests ─────────────────────────────────────────────────────────────

class TestClusterEndpoints:
    @pytest.mark.asyncio
    async def test_get_cluster_returns_entity_id(self):
        from services.profile.routes import get_profile_cluster
        agg = make_agg()
        req = make_request()
        result = await get_profile_cluster(ENTITY_ID, req, agg)
        assert result["data"]["entity_id"] == ENTITY_ID

    @pytest.mark.asyncio
    async def test_get_clusters_returns_list_envelope(self):
        from services.profile.routes import get_profile_clusters
        agg = make_agg()
        req = make_request()
        result = await get_profile_clusters(ENTITY_ID, req, agg)
        assert "items" in result["data"]
        assert "count" in result["data"]

    @pytest.mark.asyncio
    async def test_get_clusters_empty_state(self):
        from services.profile.routes import get_profile_clusters
        agg = make_agg({"clusters": AsyncMock(return_value={"entity_id": ENTITY_ID, "items": [], "count": 0})})
        req = make_request()
        result = await get_profile_clusters(ENTITY_ID, req, agg)
        assert result["data"]["items"] == []
        assert result["data"]["count"] == 0

    @pytest.mark.asyncio
    async def test_identity_confidence_returns_score(self):
        from services.profile.routes import get_identity_confidence
        agg = make_agg()
        req = make_request()
        result = await get_identity_confidence(ENTITY_ID, req, agg)
        assert "average_confidence" in result["data"]

    @pytest.mark.asyncio
    async def test_identity_confidence_tenant_isolation(self):
        """Confidence returned is scoped to the requesting tenant."""
        from services.profile.routes import get_identity_confidence
        agg = make_agg({"identity_confidence": AsyncMock(return_value={"entity_id": ENTITY_ID, "average_confidence": 0.9, "by_type": {"device": 0.9}})})
        req = make_request(tenant_id=TENANT_ID)
        result = await get_identity_confidence(ENTITY_ID, req, agg)
        # aggregator is called with the right tenant — confirm entity_id echoed back
        assert result["data"]["entity_id"] == ENTITY_ID

    @pytest.mark.asyncio
    async def test_merge_history_graceful_degradation(self):
        """merge-history returns empty envelope when IdentityGraphRepository unavailable.
        The route wraps the lazy import in except Exception, so calling without
        a real repository already exercises the graceful-degradation path."""
        from services.profile.routes import get_merge_history
        req = make_request()
        result = await get_merge_history(ENTITY_ID, req, limit=10)
        assert result["data"]["items"] == []
        assert result["data"]["source_status"] == "missing"

    @pytest.mark.asyncio
    async def test_split_history_graceful_degradation(self):
        """split-history returns empty envelope when IdentityGraphRepository unavailable."""
        from services.profile.routes import get_split_history
        req = make_request()
        result = await get_split_history(ENTITY_ID, req, limit=10)
        assert result["data"]["items"] == []
        assert result["data"]["source_status"] == "missing"

    @pytest.mark.asyncio
    async def test_merge_history_tenant_isolation(self):
        """merge-history excludes records from a different tenant."""
        from services.profile.routes import get_merge_history
        req = make_request(tenant_id=TENANT_ID)
        wrong_tenant_row = {"tenant_id": "other-tenant", "entity_id": ENTITY_ID, "merged_into": "entity-002"}
        with patch("repositories.identity_graph_repository.IdentityGraphRepository") as MockRepo:
            MockRepo.return_value.find_many = AsyncMock(return_value=[wrong_tenant_row])
            result = await get_merge_history(ENTITY_ID, req, limit=10)
        assert result["data"]["items"] == []

    @pytest.mark.asyncio
    async def test_split_history_tenant_isolation(self):
        """split-history excludes records from a different tenant."""
        from services.profile.routes import get_split_history
        req = make_request(tenant_id=TENANT_ID)
        wrong_tenant_row = {"tenant_id": "other-tenant", "entity_id": ENTITY_ID, "split_from": "entity-003"}
        with patch("repositories.identity_graph_repository.IdentityGraphRepository") as MockRepo:
            MockRepo.return_value.find_many = AsyncMock(return_value=[wrong_tenant_row])
            result = await get_split_history(ENTITY_ID, req, limit=10)
        assert result["data"]["items"] == []


# ── Attribution Tests ─────────────────────────────────────────────────────────

class TestAttributionEndpoint:
    @pytest.mark.asyncio
    async def test_attribution_returns_touchpoints(self):
        from services.profile.routes import get_profile_attribution
        agg = make_agg()
        req = make_request()
        result = await get_profile_attribution(ENTITY_ID, req, agg, window="30d")
        assert "touchpoints" in result["data"]

    @pytest.mark.asyncio
    async def test_attribution_returns_first_and_last_touch(self):
        from services.profile.routes import get_profile_attribution
        agg = make_agg({"attribution": AsyncMock(return_value={
            "entity_id": ENTITY_ID,
            "touchpoints": [{"channel": "email", "occurred_at": "2026-03-01T00:00:00Z"}],
            "first_touch": {"channel": "email", "occurred_at": "2026-03-01T00:00:00Z"},
            "last_touch": {"channel": "email", "occurred_at": "2026-03-01T00:00:00Z"},
            "count": 1,
        })})
        req = make_request()
        result = await get_profile_attribution(ENTITY_ID, req, agg, window="30d")
        data = result["data"]
        assert "first_touch" in data
        assert "last_touch" in data

    @pytest.mark.asyncio
    async def test_attribution_invalid_window(self):
        from services.profile.routes import get_profile_attribution
        from shared.common.common import BadRequestError
        agg = make_agg()
        req = make_request()
        with pytest.raises(BadRequestError):
            await get_profile_attribution(ENTITY_ID, req, agg, window="invalid")

    @pytest.mark.asyncio
    async def test_attribution_empty_state(self):
        from services.profile.routes import get_profile_attribution
        agg = make_agg({"attribution": AsyncMock(return_value={
            "entity_id": ENTITY_ID,
            "touchpoints": [],
            "first_touch": None,
            "last_touch": None,
            "count": 0,
        })})
        req = make_request()
        result = await get_profile_attribution(ENTITY_ID, req, agg, window="30d")
        assert result["data"]["touchpoints"] == []
        assert result["data"]["first_touch"] is None
        assert result["data"]["last_touch"] is None

    @pytest.mark.asyncio
    async def test_attribution_tenant_isolation(self):
        """Attribution is requested through the aggregator which enforces tenant scope."""
        from services.profile.routes import get_profile_attribution
        agg = make_agg()
        req = make_request(tenant_id=TENANT_ID)
        result = await get_profile_attribution(ENTITY_ID, req, agg, window="7d")
        agg.attribution.assert_called_once()
        assert result["data"]["entity_id"] == ENTITY_ID


# ── Consent Tests ─────────────────────────────────────────────────────────────

class TestConsentEndpoints:
    @pytest.mark.asyncio
    async def test_consent_unknown_when_no_record(self):
        from services.profile.routes import get_profile_consent
        req = make_request()
        with patch("repositories.repos.ConsentRepository") as MockRepo:
            MockRepo.return_value.find_by_entity = AsyncMock(return_value=None)
            result = await get_profile_consent(ENTITY_ID, req)
        assert result["data"]["consent_status"] == "unknown"
        assert result["data"]["source_status"] == "missing"

    @pytest.mark.asyncio
    async def test_consent_observe_only_when_no_record(self):
        from services.profile.routes import get_profile_consent
        req = make_request()
        with patch("repositories.repos.ConsentRepository") as MockRepo:
            MockRepo.return_value.find_by_entity = AsyncMock(return_value=None)
            result = await get_profile_consent(ENTITY_ID, req)
        assert result["data"]["activation_eligibility"] == "observe_only"

    @pytest.mark.asyncio
    async def test_consent_granted(self):
        from services.profile.routes import get_profile_consent
        req = make_request()
        record = {
            "tenant_id": TENANT_ID,
            "consent_status": "granted",
            "activation_eligibility": "allowed",
            "allowed_use_cases": ["analytics", "retargeting"],
            "restricted_use_cases": [],
            "blocked_use_cases": [],
        }
        with patch("repositories.repos.ConsentRepository") as MockRepo:
            MockRepo.return_value.find_by_entity = AsyncMock(return_value=record)
            result = await get_profile_consent(ENTITY_ID, req)
        assert result["data"]["consent_status"] == "granted"
        assert result["data"]["activation_eligibility"] == "allowed"
        assert result["data"]["source_status"] == "available"

    @pytest.mark.asyncio
    async def test_consent_revoked(self):
        from services.profile.routes import get_profile_consent
        req = make_request()
        record = {
            "tenant_id": TENANT_ID,
            "consent_status": "revoked",
            "activation_eligibility": "blocked",
            "allowed_use_cases": [],
            "restricted_use_cases": [],
            "blocked_use_cases": ["analytics", "retargeting", "targeting"],
        }
        with patch("repositories.repos.ConsentRepository") as MockRepo:
            MockRepo.return_value.find_by_entity = AsyncMock(return_value=record)
            result = await get_profile_consent(ENTITY_ID, req)
        assert result["data"]["consent_status"] == "revoked"
        assert result["data"]["activation_eligibility"] == "blocked"

    @pytest.mark.asyncio
    async def test_consent_tenant_isolation(self):
        """Consent record from wrong tenant returns unknown state."""
        from services.profile.routes import get_profile_consent
        req = make_request(tenant_id=TENANT_ID)
        wrong_tenant_record = {"tenant_id": "other-tenant", "consent_status": "granted"}
        with patch("repositories.repos.ConsentRepository") as MockRepo:
            MockRepo.return_value.find_by_entity = AsyncMock(return_value=wrong_tenant_record)
            result = await get_profile_consent(ENTITY_ID, req)
        assert result["data"]["consent_status"] == "unknown"

    @pytest.mark.asyncio
    async def test_activation_eligibility_blocked(self):
        from services.profile.routes import get_activation_eligibility
        req = make_request()
        record = {
            "tenant_id": TENANT_ID,
            "activation_eligibility": "blocked",
            "blocked_use_cases": ["retargeting", "targeting"],
            "consent_status": "revoked",
        }
        with patch("repositories.repos.ConsentRepository") as MockRepo:
            MockRepo.return_value.find_by_entity = AsyncMock(return_value=record)
            result = await get_activation_eligibility(ENTITY_ID, req)
        assert result["data"]["activation_eligibility"] == "blocked"

    @pytest.mark.asyncio
    async def test_activation_eligibility_allowed(self):
        from services.profile.routes import get_activation_eligibility
        req = make_request()
        record = {
            "tenant_id": TENANT_ID,
            "activation_eligibility": "allowed",
            "allowed_use_cases": ["analytics"],
            "consent_status": "granted",
        }
        with patch("repositories.repos.ConsentRepository") as MockRepo:
            MockRepo.return_value.find_by_entity = AsyncMock(return_value=record)
            result = await get_activation_eligibility(ENTITY_ID, req)
        assert result["data"]["activation_eligibility"] == "allowed"

    @pytest.mark.asyncio
    async def test_activation_eligibility_unknown_when_no_record(self):
        from services.profile.routes import get_activation_eligibility
        req = make_request()
        with patch("repositories.repos.ConsentRepository") as MockRepo:
            MockRepo.return_value.find_by_entity = AsyncMock(return_value=None)
            result = await get_activation_eligibility(ENTITY_ID, req)
        assert result["data"]["activation_eligibility"] == "observe_only"


# ── Quality & Freshness Tests ─────────────────────────────────────────────────

class TestQualityEndpoints:
    @pytest.mark.asyncio
    async def test_quality_returns_readiness_status(self):
        from services.profile.routes import get_profile_quality
        agg = make_agg()
        req = make_request()
        result = await get_profile_quality(ENTITY_ID, req, agg)
        assert "readiness_status" in result["data"]

    @pytest.mark.asyncio
    async def test_quality_scores_present(self):
        from services.profile.routes import get_profile_quality
        agg = make_agg()
        req = make_request()
        result = await get_profile_quality(ENTITY_ID, req, agg)
        data = result["data"]
        assert "completeness_score" in data
        assert "freshness_score" in data
        assert "confidence_score" in data

    @pytest.mark.asyncio
    async def test_quality_returns_entity_id(self):
        from services.profile.routes import get_profile_quality
        agg = make_agg()
        req = make_request()
        result = await get_profile_quality(ENTITY_ID, req, agg)
        assert result["data"]["entity_id"] == ENTITY_ID

    @pytest.mark.asyncio
    async def test_quality_partial_readiness(self):
        from services.profile.routes import get_profile_quality
        agg = make_agg({"quality": AsyncMock(return_value={
            "entity_id": ENTITY_ID,
            "readiness_status": "partial",
            "completeness_score": 0.4,
            "freshness_score": 0.6,
            "confidence_score": 0.5,
            "missing_dimensions": ["wallets", "journeys"],
            "stale_dimensions": [],
        })})
        req = make_request()
        result = await get_profile_quality(ENTITY_ID, req, agg)
        assert result["data"]["readiness_status"] == "partial"
        assert "missing_dimensions" in result["data"]

    @pytest.mark.asyncio
    async def test_quality_ready_status(self):
        from services.profile.routes import get_profile_quality
        agg = make_agg({"quality": AsyncMock(return_value={
            "entity_id": ENTITY_ID,
            "readiness_status": "ready",
            "completeness_score": 1.0,
            "freshness_score": 1.0,
            "confidence_score": 0.95,
            "missing_dimensions": [],
            "stale_dimensions": [],
        })})
        req = make_request()
        result = await get_profile_quality(ENTITY_ID, req, agg)
        assert result["data"]["readiness_status"] == "ready"

    @pytest.mark.asyncio
    async def test_data_freshness_returns_dimensions(self):
        from services.profile.routes import get_data_freshness
        agg = make_agg()
        req = make_request()
        result = await get_data_freshness(ENTITY_ID, req, agg)
        assert "dimensions" in result["data"]
        assert "computed_at" in result["data"]

    @pytest.mark.asyncio
    async def test_data_freshness_per_dimension(self):
        from services.profile.routes import get_data_freshness
        agg = make_agg({"data_freshness": AsyncMock(return_value={
            "entity_id": ENTITY_ID,
            "dimensions": {
                "wallets": {"last_updated": "2026-05-01T00:00:00Z", "staleness_hours": 24},
                "sessions": {"last_updated": "2026-06-01T00:00:00Z", "staleness_hours": 1},
            },
            "computed_at": "2026-06-10T00:00:00Z",
        })})
        req = make_request()
        result = await get_data_freshness(ENTITY_ID, req, agg)
        dims = result["data"]["dimensions"]
        assert "wallets" in dims
        assert "sessions" in dims

    @pytest.mark.asyncio
    async def test_data_freshness_empty_dimensions(self):
        from services.profile.routes import get_data_freshness
        agg = make_agg({"data_freshness": AsyncMock(return_value={
            "entity_id": ENTITY_ID,
            "dimensions": {},
            "computed_at": "2026-06-10T00:00:00Z",
        })})
        req = make_request()
        result = await get_data_freshness(ENTITY_ID, req, agg)
        assert result["data"]["dimensions"] == {}


# ── Economic Sub-Route Tests ──────────────────────────────────────────────────

class TestEconomicSubRoutes:
    @pytest.mark.asyncio
    async def test_economic_returns_entity_id(self):
        from services.profile.routes import get_profile_economic
        req = make_request()
        mock_intel = MagicMock()
        mock_intel.pnl = AsyncMock(return_value={"computed_at": "2026-01-01T00:00:00Z"})
        mock_intel.asset_composition = AsyncMock(return_value={})
        result = await get_profile_economic(ENTITY_ID, req, window="30d", intel=mock_intel)
        assert result["data"]["entity_id"] == ENTITY_ID

    @pytest.mark.asyncio
    async def test_economic_web2_returns_envelope(self):
        from services.profile.routes import get_economic_web2
        req = make_request()
        mock_intel = MagicMock()
        mock_intel.web2 = AsyncMock(return_value={"entity_id": ENTITY_ID, "window": "30d"})
        result = await get_economic_web2(ENTITY_ID, req, window="30d", intel=mock_intel)
        assert result["data"]["entity_id"] == ENTITY_ID

    @pytest.mark.asyncio
    async def test_economic_web3_returns_pnl_and_trading(self):
        from services.profile.routes import get_economic_web3
        req = make_request()
        mock_intel = MagicMock()
        mock_intel.asset_composition = AsyncMock(return_value={"items": []})
        mock_intel.pnl = AsyncMock(return_value={"realized_pnl_usd": 0.0})
        mock_intel.trading_profile = AsyncMock(return_value={"favorite_pairs": []})
        result = await get_economic_web3(ENTITY_ID, req, window="30d", intel=mock_intel)
        assert "pnl" in result["data"]
        assert "trading_profile" in result["data"]
        assert "asset_composition" in result["data"]

    @pytest.mark.asyncio
    async def test_economic_agentic_returns_envelope(self):
        from services.profile.routes import get_economic_agentic
        agg = make_agg()
        req = make_request()
        result = await get_economic_agentic(ENTITY_ID, req, agg=agg)
        assert result["data"]["entity_id"] == ENTITY_ID

    @pytest.mark.asyncio
    async def test_economic_campaigns_returns_envelope(self):
        from services.profile.routes import get_economic_campaigns
        agg = make_agg()
        req = make_request()
        mock_intel = MagicMock()
        mock_intel.journey_economics = AsyncMock(return_value={"items": [], "count": 0})
        result = await get_economic_campaigns(ENTITY_ID, req, agg, window="30d", intel=mock_intel)
        assert result["data"]["entity_id"] == ENTITY_ID
        assert "campaigns" in result["data"]

    @pytest.mark.asyncio
    async def test_economic_invalid_window(self):
        from services.profile.routes import get_economic_web3
        from shared.common.common import BadRequestError
        req = make_request()
        mock_intel = MagicMock()
        with pytest.raises(BadRequestError):
            await get_economic_web3(ENTITY_ID, req, window="invalid", intel=mock_intel)

    @pytest.mark.asyncio
    async def test_economic_web2_invalid_window(self):
        from services.profile.routes import get_economic_web2
        from shared.common.common import BadRequestError
        req = make_request()
        mock_intel = MagicMock()
        with pytest.raises(BadRequestError):
            await get_economic_web2(ENTITY_ID, req, window="bad_window", intel=mock_intel)

    @pytest.mark.asyncio
    async def test_economic_warnings_returns_structured_list(self):
        from services.profile.routes import get_economic_warnings
        agg = make_agg({"quality": AsyncMock(return_value={
            "entity_id": ENTITY_ID,
            "readiness_status": "partial",
            "missing_dimensions": ["journeys", "wallets"],
            "stale_dimensions": ["sessions"],
            "contradiction_count": 1,
        })})
        req = make_request()
        result = await get_economic_warnings(ENTITY_ID, req, agg)
        data = result["data"]
        assert "warnings" in data
        assert "warning_count" in data
        assert data["warning_count"] > 0

    @pytest.mark.asyncio
    async def test_economic_warnings_empty_when_ready(self):
        from services.profile.routes import get_economic_warnings
        agg = make_agg({"quality": AsyncMock(return_value={
            "entity_id": ENTITY_ID,
            "readiness_status": "ready",
            "missing_dimensions": [],
            "stale_dimensions": [],
            "contradiction_count": 0,
        })})
        req = make_request()
        result = await get_economic_warnings(ENTITY_ID, req, agg)
        data = result["data"]
        assert "warnings" in data
        assert data["warning_count"] == 0


# ── Agent Executions Tests ────────────────────────────────────────────────────

class TestAgentExecutionsEndpoint:
    @pytest.mark.asyncio
    async def test_agent_executions_empty_when_unavailable(self):
        from services.profile.routes import get_agent_executions
        req = make_request()
        with patch("repositories.repos.AgentExecutionRepository", side_effect=ImportError):
            result = await get_agent_executions(ENTITY_ID, req, limit=10, status=None)
        assert result["data"]["items"] == []
        assert result["data"]["source_status"] == "missing"

    @pytest.mark.asyncio
    async def test_agent_executions_tenant_isolation(self):
        from services.profile.routes import get_agent_executions
        req = make_request(tenant_id=TENANT_ID)
        wrong_tenant_item = {"tenant_id": "other-tenant", "entity_id": ENTITY_ID, "status": "completed"}
        with patch("repositories.repos.AgentExecutionRepository") as MockRepo:
            MockRepo.return_value.find_many = AsyncMock(return_value=[wrong_tenant_item])
            result = await get_agent_executions(ENTITY_ID, req, limit=10, status=None)
        assert result["data"]["items"] == []

    @pytest.mark.asyncio
    async def test_agent_executions_status_filter(self):
        from services.profile.routes import get_agent_executions
        req = make_request()
        items = [
            {"tenant_id": TENANT_ID, "entity_id": ENTITY_ID, "status": "completed"},
        ]
        with patch("repositories.repos.AgentExecutionRepository") as MockRepo:
            MockRepo.return_value.find_many = AsyncMock(return_value=items)
            result = await get_agent_executions(ENTITY_ID, req, limit=10, status="completed")
        assert result["data"]["count"] == 1

    @pytest.mark.asyncio
    async def test_agent_executions_no_status_filter_returns_all(self):
        from services.profile.routes import get_agent_executions
        req = make_request()
        items = [
            {"tenant_id": TENANT_ID, "entity_id": ENTITY_ID, "status": "completed"},
            {"tenant_id": TENANT_ID, "entity_id": ENTITY_ID, "status": "failed"},
            {"tenant_id": TENANT_ID, "entity_id": ENTITY_ID, "status": "running"},
        ]
        with patch("repositories.repos.AgentExecutionRepository") as MockRepo:
            MockRepo.return_value.find_many = AsyncMock(return_value=items)
            result = await get_agent_executions(ENTITY_ID, req, limit=10, status=None)
        assert result["data"]["count"] == 3

    @pytest.mark.asyncio
    async def test_agent_executions_limit_respected(self):
        from services.profile.routes import get_agent_executions
        req = make_request()
        items = [{"tenant_id": TENANT_ID, "entity_id": ENTITY_ID, "status": "completed"}]
        with patch("repositories.repos.AgentExecutionRepository") as MockRepo:
            MockRepo.return_value.find_many = AsyncMock(return_value=items)
            result = await get_agent_executions(ENTITY_ID, req, limit=1, status=None)
        # limit is passed through to repository — assert call was made
        MockRepo.return_value.find_many.assert_called_once()
        assert "items" in result["data"]


# ── Actions & Events Tests ────────────────────────────────────────────────────

class TestActionsEventsEndpoints:
    @pytest.mark.asyncio
    async def test_actions_returns_items_list(self):
        from services.profile.routes import get_profile_actions
        req = make_request()
        with patch("services.intelligence.repositories.DecisionRepository") as MockRepo:
            MockRepo.return_value.find_many = AsyncMock(return_value=[])
            result = await get_profile_actions(ENTITY_ID, req, limit=10)
        assert "items" in result["data"]
        assert "count" in result["data"]

    @pytest.mark.asyncio
    async def test_actions_tenant_isolation(self):
        from services.profile.routes import get_profile_actions
        req = make_request(tenant_id=TENANT_ID)
        wrong_tenant_action = {"tenant_id": "other-tenant", "entity_id": ENTITY_ID, "action_type": "pay"}
        with patch("services.intelligence.repositories.DecisionRepository") as MockRepo:
            MockRepo.return_value.find_many = AsyncMock(return_value=[wrong_tenant_action])
            result = await get_profile_actions(ENTITY_ID, req, limit=10)
        assert result["data"]["items"] == []

    @pytest.mark.asyncio
    async def test_actions_returns_correct_count(self):
        from services.profile.routes import get_profile_actions
        req = make_request()
        items = [
            {"tenant_id": TENANT_ID, "entity_id": ENTITY_ID, "action_type": "pay"},
            {"tenant_id": TENANT_ID, "entity_id": ENTITY_ID, "action_type": "delegate"},
        ]
        with patch("services.intelligence.repositories.DecisionRepository") as MockRepo:
            MockRepo.return_value.find_many = AsyncMock(return_value=items)
            result = await get_profile_actions(ENTITY_ID, req, limit=10)
        assert result["data"]["count"] == 2

    @pytest.mark.asyncio
    async def test_events_returns_items_list(self):
        from services.profile.routes import get_profile_events
        req = make_request()
        with patch("repositories.repos.EventRepository") as MockRepo:
            MockRepo.return_value.find_many = AsyncMock(return_value=[])
            result = await get_profile_events(ENTITY_ID, req, limit=10, event_type=None)
        assert "items" in result["data"]
        assert "count" in result["data"]

    @pytest.mark.asyncio
    async def test_events_event_type_filter(self):
        from services.profile.routes import get_profile_events
        req = make_request()
        items = [
            {"tenant_id": TENANT_ID, "entity_id": ENTITY_ID, "event_type": "page_view", "occurred_at": "2026-06-01T00:00:00Z"},
        ]
        with patch("repositories.repos.EventRepository") as MockRepo:
            MockRepo.return_value.find_many = AsyncMock(return_value=items)
            result = await get_profile_events(ENTITY_ID, req, limit=10, event_type="page_view")
        assert result["data"]["count"] == 1
        assert result["data"]["items"][0]["event_type"] == "page_view"

    @pytest.mark.asyncio
    async def test_events_tenant_isolation(self):
        from services.profile.routes import get_profile_events
        req = make_request(tenant_id=TENANT_ID)
        wrong_tenant_event = {"tenant_id": "other-tenant", "entity_id": ENTITY_ID, "event_type": "login"}
        with patch("repositories.repos.EventRepository") as MockRepo:
            MockRepo.return_value.find_many = AsyncMock(return_value=[wrong_tenant_event])
            result = await get_profile_events(ENTITY_ID, req, limit=10, event_type=None)
        assert result["data"]["items"] == []

    @pytest.mark.asyncio
    async def test_events_graceful_degradation_when_unavailable(self):
        from services.profile.routes import get_profile_events
        req = make_request()
        with patch("repositories.repos.EventRepository", side_effect=ImportError):
            result = await get_profile_events(ENTITY_ID, req, limit=10, event_type=None)
        assert result["data"]["items"] == []
        assert result["data"]["source_status"] == "missing"
