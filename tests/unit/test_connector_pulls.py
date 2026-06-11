"""Tests for connector pull() and test_connection() methods with mocked HTTP.

These tests exercise the real adapter logic by patching _http_get / _http_post so
no external network calls are made.  Setting AETHER_ENV=staging makes _is_live()
return True, allowing the live-path branches to run.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

# ---------------------------------------------------------------------------
# Module path helper (mirrors test_connectors.py approach)
# ---------------------------------------------------------------------------
_PREFIXES = ("config", "services", "shared", "middleware", "dependencies", "repositories")


def _insert_backend_path() -> None:
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))


def _purge_backend_modules() -> None:
    for prefix in _PREFIXES:
        for name in list(sys.modules):
            if name == prefix or name.startswith(f"{prefix}."):
                sys.modules.pop(name, None)


# ---------------------------------------------------------------------------
# Session-scoped import of adapter + base modules
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def adapters_mod():
    _purge_backend_modules()
    _insert_backend_path()
    mod = importlib.import_module("services.integrations.connectors.adapters")
    base = importlib.import_module("services.integrations.connectors.base")
    yield mod, base
    _purge_backend_modules()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
ADAPTERS_PATH = "services.integrations.connectors.adapters"


def make_config(base, connector_type: str, extra: dict | None = None):
    """Build a minimal enabled ConnectorConfig with secret_configured=True."""
    cfg = base.ConnectorConfig(
        tenant_id="test-tenant",
        connector_type=connector_type,
        enabled=True,
        secret_configured=True,
        config=extra or {},
    )
    return cfg


def assert_no_secrets(data: Any, secret: str = "test-secret-xyz") -> None:
    """Recursively assert the secret value does not appear in the response."""
    text = str(data)
    assert secret not in text, f"Secret found in response: {text[:200]}"


# ---------------------------------------------------------------------------
# ShopifyConnector.pull()
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_shopify_pull_returns_normalized_events(adapters_mod, monkeypatch):
    mod, base = adapters_mod
    monkeypatch.setenv("AETHER_ENV", "staging")

    shopify_orders_response = {
        "orders": [
            {"id": 111, "email": "alice@example.com", "total_price": "99.00",
             "financial_status": "paid", "updated_at": "2024-01-01T00:00:00Z"},
            {"id": 222, "email": "bob@example.com", "total_price": "49.50",
             "financial_status": "pending", "updated_at": "2024-01-02T00:00:00Z"},
        ]
    }

    with patch(f"{ADAPTERS_PATH}._http_get", new=AsyncMock(return_value=(200, shopify_orders_response))):
        connector = mod.ShopifyConnector()
        cfg = make_config(base, "shopify", {"shop_domain": "mystore.myshopify.com"})
        events = await connector.pull(cfg, secret="test-secret-xyz")

    assert len(events) == 2
    for ev in events:
        assert ev.event_type == "shopify.order"
        assert ev.source == "shopify"
    assert events[0].external_id == "111"
    assert events[1].external_id == "222"
    assert_no_secrets(events)


@pytest.mark.asyncio
async def test_shopify_pull_local_mode_returns_empty(adapters_mod, monkeypatch):
    mod, base = adapters_mod
    monkeypatch.setenv("AETHER_ENV", "local")

    http_mock = AsyncMock()
    with patch(f"{ADAPTERS_PATH}._http_get", new=http_mock):
        connector = mod.ShopifyConnector()
        cfg = make_config(base, "shopify", {"shop_domain": "mystore.myshopify.com"})
        events = await connector.pull(cfg, secret="test-secret-xyz")

    assert events == []
    http_mock.assert_not_called()


@pytest.mark.asyncio
async def test_shopify_pull_api_error_returns_empty(adapters_mod, monkeypatch):
    mod, base = adapters_mod
    monkeypatch.setenv("AETHER_ENV", "staging")

    with patch(f"{ADAPTERS_PATH}._http_get", new=AsyncMock(return_value=(401, {"error": "unauthorized"}))):
        connector = mod.ShopifyConnector()
        cfg = make_config(base, "shopify", {"shop_domain": "mystore.myshopify.com"})
        events = await connector.pull(cfg, secret="test-secret-xyz")

    assert events == []


# ---------------------------------------------------------------------------
# ShopifyConnector.test_connection()
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_shopify_test_connection_success(adapters_mod, monkeypatch):
    mod, base = adapters_mod
    monkeypatch.setenv("AETHER_ENV", "staging")

    shop_response = {"shop": {"name": "My Test Store", "domain": "mystore.myshopify.com"}}

    with patch(f"{ADAPTERS_PATH}._http_get", new=AsyncMock(return_value=(200, shop_response))):
        connector = mod.ShopifyConnector()
        cfg = make_config(base, "shopify", {"shop_domain": "mystore.myshopify.com"})
        result = await connector.test_connection(cfg, secret="test-secret-xyz")

    assert result.ok is True
    assert "My Test Store" in result.detail
    assert_no_secrets(result)


@pytest.mark.asyncio
async def test_shopify_test_connection_auth_failure(adapters_mod, monkeypatch):
    mod, base = adapters_mod
    monkeypatch.setenv("AETHER_ENV", "staging")

    with patch(f"{ADAPTERS_PATH}._http_get", new=AsyncMock(return_value=(401, {}))):
        connector = mod.ShopifyConnector()
        cfg = make_config(base, "shopify", {"shop_domain": "mystore.myshopify.com"})
        result = await connector.test_connection(cfg, secret="test-secret-xyz")

    assert result.ok is False
    assert_no_secrets(result)


# ---------------------------------------------------------------------------
# HubSpotConnector.pull()
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_hubspot_pull_returns_normalized_events(adapters_mod, monkeypatch):
    mod, base = adapters_mod
    monkeypatch.setenv("AETHER_ENV", "staging")

    hubspot_response = {
        "results": [
            {"id": "101", "updatedAt": "2024-01-01T00:00:00Z",
             "properties": {"email": "alice@acme.com", "firstname": "Alice", "lastname": "Smith"}},
            {"id": "102", "updatedAt": "2024-01-02T00:00:00Z",
             "properties": {"email": "bob@acme.com", "firstname": "Bob", "lastname": "Jones"}},
        ]
    }

    with patch(f"{ADAPTERS_PATH}._http_get", new=AsyncMock(return_value=(200, hubspot_response))):
        connector = mod.HubSpotConnector()
        cfg = make_config(base, "hubspot")
        events = await connector.pull(cfg, secret="test-secret-xyz")

    assert len(events) == 2
    for ev in events:
        assert ev.event_type == "hubspot.contact"
        assert ev.source == "hubspot"
    assert events[0].external_id == "101"
    assert events[1].external_id == "102"
    assert_no_secrets(events)


@pytest.mark.asyncio
async def test_hubspot_pull_local_mode_returns_empty(adapters_mod, monkeypatch):
    mod, base = adapters_mod
    monkeypatch.setenv("AETHER_ENV", "local")

    http_mock = AsyncMock()
    with patch(f"{ADAPTERS_PATH}._http_get", new=http_mock):
        connector = mod.HubSpotConnector()
        cfg = make_config(base, "hubspot")
        events = await connector.pull(cfg, secret="test-secret-xyz")

    assert events == []
    http_mock.assert_not_called()


@pytest.mark.asyncio
async def test_hubspot_pull_api_error_returns_empty(adapters_mod, monkeypatch):
    mod, base = adapters_mod
    monkeypatch.setenv("AETHER_ENV", "staging")

    with patch(f"{ADAPTERS_PATH}._http_get", new=AsyncMock(return_value=(403, {"message": "Forbidden"}))):
        connector = mod.HubSpotConnector()
        cfg = make_config(base, "hubspot")
        events = await connector.pull(cfg, secret="test-secret-xyz")

    assert events == []


# ---------------------------------------------------------------------------
# PostHogConnector.pull()
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_posthog_pull_returns_normalized_events(adapters_mod, monkeypatch):
    mod, base = adapters_mod
    monkeypatch.setenv("AETHER_ENV", "staging")

    posthog_response = {
        "results": [
            {"id": "ph-001", "created_at": "2024-01-01T00:00:00Z",
             "distinct_ids": ["user-1"], "properties": {"email": "user1@co.com"}},
            {"id": "ph-002", "created_at": "2024-01-02T00:00:00Z",
             "distinct_ids": ["user-2"], "properties": {}},
        ]
    }

    with patch(f"{ADAPTERS_PATH}._http_get", new=AsyncMock(return_value=(200, posthog_response))):
        connector = mod.PostHogConnector()
        cfg = make_config(base, "posthog", {"project_id": "proj-123"})
        events = await connector.pull(cfg, secret="test-secret-xyz")

    assert len(events) == 2
    for ev in events:
        assert ev.event_type == "posthog.person"
        assert ev.source == "posthog"
    assert events[0].external_id == "ph-001"
    assert_no_secrets(events)


@pytest.mark.asyncio
async def test_posthog_pull_missing_project_id_returns_empty(adapters_mod, monkeypatch):
    mod, base = adapters_mod
    monkeypatch.setenv("AETHER_ENV", "staging")

    http_mock = AsyncMock()
    with patch(f"{ADAPTERS_PATH}._http_get", new=http_mock):
        connector = mod.PostHogConnector()
        # No project_id in config
        cfg = make_config(base, "posthog", {})
        events = await connector.pull(cfg, secret="test-secret-xyz")

    assert events == []
    http_mock.assert_not_called()


@pytest.mark.asyncio
async def test_posthog_pull_local_mode_returns_empty(adapters_mod, monkeypatch):
    mod, base = adapters_mod
    monkeypatch.setenv("AETHER_ENV", "local")

    http_mock = AsyncMock()
    with patch(f"{ADAPTERS_PATH}._http_get", new=http_mock):
        connector = mod.PostHogConnector()
        cfg = make_config(base, "posthog", {"project_id": "proj-123"})
        events = await connector.pull(cfg, secret="test-secret-xyz")

    assert events == []
    http_mock.assert_not_called()


# ---------------------------------------------------------------------------
# SlackConnector.test_connection()
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_slack_test_connection_success(adapters_mod, monkeypatch):
    mod, base = adapters_mod
    monkeypatch.setenv("AETHER_ENV", "staging")

    slack_response = {"ok": True, "team": "Acme Corp", "user": "bot"}

    with patch(f"{ADAPTERS_PATH}._http_get", new=AsyncMock(return_value=(200, slack_response))):
        connector = mod.SlackConnector()
        cfg = make_config(base, "slack")
        result = await connector.test_connection(cfg, secret="test-secret-xyz")

    assert result.ok is True
    assert "Acme Corp" in result.detail
    assert_no_secrets(result)


@pytest.mark.asyncio
async def test_slack_test_connection_auth_failure_ok_false(adapters_mod, monkeypatch):
    mod, base = adapters_mod
    monkeypatch.setenv("AETHER_ENV", "staging")

    # Slack returns 200 but ok=False when the token is invalid
    slack_error_response = {"ok": False, "error": "invalid_auth"}

    with patch(f"{ADAPTERS_PATH}._http_get", new=AsyncMock(return_value=(200, slack_error_response))):
        connector = mod.SlackConnector()
        cfg = make_config(base, "slack")
        result = await connector.test_connection(cfg, secret="test-secret-xyz")

    assert result.ok is False
    assert result.detail == "invalid_auth"
    assert_no_secrets(result)


@pytest.mark.asyncio
async def test_slack_test_connection_http_failure(adapters_mod, monkeypatch):
    mod, base = adapters_mod
    monkeypatch.setenv("AETHER_ENV", "staging")

    with patch(f"{ADAPTERS_PATH}._http_get", new=AsyncMock(return_value=(500, {}))):
        connector = mod.SlackConnector()
        cfg = make_config(base, "slack")
        result = await connector.test_connection(cfg, secret="test-secret-xyz")

    assert result.ok is False
    assert_no_secrets(result)


@pytest.mark.asyncio
async def test_slack_test_connection_local_mode_skips_http(adapters_mod, monkeypatch):
    mod, base = adapters_mod
    monkeypatch.setenv("AETHER_ENV", "local")

    http_mock = AsyncMock()
    with patch(f"{ADAPTERS_PATH}._http_get", new=http_mock):
        connector = mod.SlackConnector()
        cfg = make_config(base, "slack")
        result = await connector.test_connection(cfg, secret="test-secret-xyz")

    # In local mode _is_live() is False → falls back to base mocked ok
    assert result.ok is True
    http_mock.assert_not_called()


# ---------------------------------------------------------------------------
# NormalizedEvent field correctness
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_normalized_event_fields_shopify(adapters_mod, monkeypatch):
    mod, base = adapters_mod
    monkeypatch.setenv("AETHER_ENV", "staging")

    order = {"id": 999, "email": "check@example.com", "total_price": "10.00",
              "financial_status": "paid", "updated_at": "2024-06-01T12:00:00Z"}

    with patch(f"{ADAPTERS_PATH}._http_get", new=AsyncMock(return_value=(200, {"orders": [order]}))):
        connector = mod.ShopifyConnector()
        cfg = make_config(base, "shopify", {"shop_domain": "check.myshopify.com"})
        events = await connector.pull(cfg, secret="test-secret-xyz")

    assert len(events) == 1
    ev = events[0]
    assert ev.event_type == "shopify.order"
    assert ev.source == "shopify"
    assert ev.external_id == "999"
    assert ev.properties["email"] == "check@example.com"
    assert ev.properties["total"] == "10.00"
    assert ev.properties["status"] == "paid"
    # Secret must not appear in properties
    assert "test-secret-xyz" not in str(ev.properties)


@pytest.mark.asyncio
async def test_normalized_event_fields_hubspot(adapters_mod, monkeypatch):
    mod, base = adapters_mod
    monkeypatch.setenv("AETHER_ENV", "staging")

    record = {"id": "hs-77", "updatedAt": "2024-05-01T00:00:00Z",
               "properties": {"email": "contact@example.com", "firstname": "Jane"}}

    with patch(f"{ADAPTERS_PATH}._http_get", new=AsyncMock(return_value=(200, {"results": [record]}))):
        connector = mod.HubSpotConnector()
        cfg = make_config(base, "hubspot")
        events = await connector.pull(cfg, secret="test-secret-xyz")

    assert len(events) == 1
    ev = events[0]
    assert ev.event_type == "hubspot.contact"
    assert ev.source == "hubspot"
    assert ev.external_id == "hs-77"
    assert ev.properties.get("email") == "contact@example.com"
    assert "test-secret-xyz" not in str(ev.properties)


# ---------------------------------------------------------------------------
# ConnectionTestResult secret leakage guard
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_connection_result_no_secret_leak_shopify(adapters_mod, monkeypatch):
    mod, base = adapters_mod
    monkeypatch.setenv("AETHER_ENV", "staging")

    with patch(f"{ADAPTERS_PATH}._http_get", new=AsyncMock(return_value=(200, {"shop": {"name": "Safe Store"}}))):
        connector = mod.ShopifyConnector()
        cfg = make_config(base, "shopify", {"shop_domain": "safe.myshopify.com"})
        result = await connector.test_connection(cfg, secret="test-secret-xyz")

    assert "test-secret-xyz" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_connection_result_no_secret_leak_slack(adapters_mod, monkeypatch):
    mod, base = adapters_mod
    monkeypatch.setenv("AETHER_ENV", "staging")

    with patch(f"{ADAPTERS_PATH}._http_get", new=AsyncMock(return_value=(200, {"ok": True, "team": "SafeTeam"}))):
        connector = mod.SlackConnector()
        cfg = make_config(base, "slack")
        result = await connector.test_connection(cfg, secret="test-secret-xyz")

    assert "test-secret-xyz" not in result.model_dump_json()


# ---------------------------------------------------------------------------
# GA4Connector.pull() — uses _http_post
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ga4_pull_returns_normalized_events(adapters_mod, monkeypatch):
    mod, base = adapters_mod
    monkeypatch.setenv("AETHER_ENV", "staging")

    ga4_response = {
        "rows": [
            {"dimensionValues": [{"value": "page_view"}], "metricValues": [{"value": "500"}]},
            {"dimensionValues": [{"value": "click"}], "metricValues": [{"value": "120"}]},
        ]
    }

    with patch(f"{ADAPTERS_PATH}._http_post", new=AsyncMock(return_value=(200, ga4_response))):
        connector = mod.GA4Connector()
        cfg = make_config(base, "ga4", {"property_id": "12345"})
        events = await connector.pull(cfg, secret="test-secret-xyz")

    assert len(events) == 2
    for ev in events:
        assert ev.event_type == "ga4.event"
        assert ev.source == "ga4"
    assert events[0].properties["event_name"] == "page_view"
    assert events[1].properties["event_name"] == "click"
    assert_no_secrets(events)


@pytest.mark.asyncio
async def test_ga4_pull_local_mode_returns_empty(adapters_mod, monkeypatch):
    mod, base = adapters_mod
    monkeypatch.setenv("AETHER_ENV", "local")

    http_mock = AsyncMock()
    with patch(f"{ADAPTERS_PATH}._http_post", new=http_mock):
        connector = mod.GA4Connector()
        cfg = make_config(base, "ga4", {"property_id": "12345"})
        events = await connector.pull(cfg, secret="test-secret-xyz")

    assert events == []
    http_mock.assert_not_called()


# ---------------------------------------------------------------------------
# No-secret → _is_live() returns False guard
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_pull_without_secret_returns_empty(adapters_mod, monkeypatch):
    """All connectors must return empty and not hit the network when secret=None."""
    mod, base = adapters_mod
    monkeypatch.setenv("AETHER_ENV", "staging")

    http_mock = AsyncMock()
    with patch(f"{ADAPTERS_PATH}._http_get", new=http_mock), \
         patch(f"{ADAPTERS_PATH}._http_post", new=http_mock):

        for cls in [mod.ShopifyConnector, mod.HubSpotConnector, mod.PostHogConnector]:
            connector = cls()
            cfg = make_config(base, connector.connector_type)
            events = await connector.pull(cfg, secret=None)
            assert events == [], f"{cls.__name__}.pull() with secret=None should return []"

    http_mock.assert_not_called()
