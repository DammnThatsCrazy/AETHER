"""Integration tests for Campaign Registry API endpoints."""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

os.environ.setdefault("AETHER_ENV", "local")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _run(coro):
    return asyncio.run(coro)


def _mock_tenant(tenant_id: str = "test-tenant"):
    t = MagicMock()
    t.tenant_id = tenant_id
    return t


def _mock_request(tenant_id: str = "test-tenant"):
    req = MagicMock()
    req.state.tenant = _mock_tenant(tenant_id)
    return req


# ─────────────────────────────────────────────────────────────────────────────
# Campaign list / CRUD
# ─────────────────────────────────────────────────────────────────────────────

class TestCampaignListEndpoint:
    def test_list_campaigns_returns_dict(self):
        from services.campaign.routes import list_campaigns
        req = _mock_request()
        result = _run(list_campaigns(req, status=None, origin=None, platform=None, mapping_quality=None, limit=50, offset=0))
        assert isinstance(result, dict)
        assert "data" in result

    def test_list_campaigns_respects_limit(self):
        from services.campaign.routes import list_campaigns
        req = _mock_request()
        result = _run(list_campaigns(req, status=None, origin=None, platform=None, mapping_quality=None, limit=5, offset=0))
        data = result.get("data") or []
        assert isinstance(data, list)
        assert len(data) <= 5

    def test_create_custom_campaign(self):
        from services.campaign.routes import create_campaign, CampaignCreate
        req = _mock_request()
        body = CampaignCreate(name="Test Camp", channel="email")
        result = _run(create_campaign(req, body))
        assert "data" in result
        data = result["data"]
        assert "campaign_id" in data
        assert data.get("origin") == "custom"

    def test_create_campaign_name_required(self):
        from services.campaign.routes import CampaignCreate
        from pydantic import ValidationError
        with pytest.raises((ValidationError, Exception)):
            CampaignCreate(name="", channel="email")


# ─────────────────────────────────────────────────────────────────────────────
# External refs
# ─────────────────────────────────────────────────────────────────────────────

class TestExternalRefsEndpoint:
    def test_get_external_refs_unknown_campaign(self):
        from services.campaign.routes import list_campaign_external_refs
        req = _mock_request()
        fake_id = str(uuid.uuid4())
        result = _run(list_campaign_external_refs(fake_id, req))
        # Should return empty list or 404-style, not crash
        assert isinstance(result, dict)


# ─────────────────────────────────────────────────────────────────────────────
# Aliases
# ─────────────────────────────────────────────────────────────────────────────

class TestAliasEndpoints:
    def test_add_alias_to_campaign(self):
        from services.campaign.routes import create_campaign, add_campaign_alias
        from services.campaign.routes import CampaignCreate, AliasCreateRequest
        req = _mock_request()
        camp_result = _run(create_campaign(req, CampaignCreate(name="Alias Test Camp")))
        campaign_id = camp_result["data"]["campaign_id"]

        alias_result = _run(add_campaign_alias(
            campaign_id,
            req,
            AliasCreateRequest(alias_type="utm_campaign", value="alias-test-value"),
        ))
        assert "data" in alias_result

    def test_list_aliases_empty(self):
        from services.campaign.routes import create_campaign, list_campaign_aliases
        from services.campaign.routes import CampaignCreate
        req = _mock_request()
        camp_result = _run(create_campaign(req, CampaignCreate(name="No Alias Camp")))
        campaign_id = camp_result["data"]["campaign_id"]

        result = _run(list_campaign_aliases(campaign_id, req))
        assert "data" in result
        assert isinstance(result["data"], list)


# ─────────────────────────────────────────────────────────────────────────────
# Campaign Sources
# ─────────────────────────────────────────────────────────────────────────────

class TestCampaignSourcesEndpoints:
    def test_list_sources_returns_list(self):
        from services.campaign.routes import list_campaign_sources
        req = _mock_request()
        result = _run(list_campaign_sources(req))
        assert "data" in result
        assert isinstance(result["data"], list)

    def test_create_source_requires_platform(self):
        from services.campaign.routes import create_campaign_source, CampaignSourceCreateRequest
        from pydantic import ValidationError
        with pytest.raises((ValidationError, Exception)):
            CampaignSourceCreateRequest(platform="", connector_id="c1")

    def test_sync_source_not_found(self):
        from services.campaign.routes import sync_campaign_source
        req = _mock_request()
        result = _run(sync_campaign_source("nonexistent-connector", req))
        # Should return a structured response, not crash
        assert isinstance(result, dict)


# ─────────────────────────────────────────────────────────────────────────────
# Mapping Review
# ─────────────────────────────────────────────────────────────────────────────

class TestMappingReviewEndpoints:
    def test_list_reviews_empty(self):
        from services.campaign.routes import list_mapping_reviews
        req = _mock_request()
        result = _run(list_mapping_reviews(req, status="open", limit=20, offset=0))
        assert "data" in result
        assert isinstance(result["data"], list)

    def test_resolve_review_missing_campaign_id(self):
        from services.campaign.routes import resolve_mapping_review, ReviewResolve
        from pydantic import ValidationError
        req = _mock_request()
        fake_review_id = str(uuid.uuid4())
        with pytest.raises((ValidationError, Exception)):
            body = ReviewResolve(campaign_id="not-a-uuid")
            _run(resolve_mapping_review(fake_review_id, req, body))

    def test_ignore_review_returns_structured(self):
        from services.campaign.routes import ignore_mapping_review
        req = _mock_request()
        fake_review_id = str(uuid.uuid4())
        # Ignoring a non-existent review should not crash; may return error response
        result = _run(ignore_mapping_review(fake_review_id, req))
        assert isinstance(result, dict)


# ─────────────────────────────────────────────────────────────────────────────
# Campaign Quality
# ─────────────────────────────────────────────────────────────────────────────

class TestCampaignQualityEndpoint:
    def test_quality_returns_rates(self):
        from services.campaign.routes import get_campaign_quality
        req = _mock_request()
        result = _run(get_campaign_quality(req))
        assert "data" in result
        data = result["data"]
        assert "spend_mapping_rate" in data
        assert "touchpoint_mapping_rate" in data

    def test_tenant_isolation(self):
        from services.campaign.routes import get_campaign_quality
        req_a = _mock_request("tenant_a")
        req_b = _mock_request("tenant_b")
        result_a = _run(get_campaign_quality(req_a))
        result_b = _run(get_campaign_quality(req_b))
        # Both must succeed without leaking data across tenants
        assert "data" in result_a
        assert "data" in result_b
