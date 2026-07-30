"""Tests for the connector framework — base adapter, adapters, and service."""
from __future__ import annotations

import pytest

from repositories.repos import reset_in_memory_stores
from services.integrations.connectors.base import (
    BaseConnector,
    ConnectorConfig,
    NormalizedEvent,
)
from services.integrations.connectors.adapters import (
    ALL_CONNECTORS,
    ShopifyConnector,
    SlackConnector,
    StripeConnector,
    SegmentConnector,
    WebhookConnector,
)
from services.integrations.connectors.registry import CONNECTORS, list_descriptors
from services.integrations.connectors.service import ConnectorService


@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()


def _cfg(connector_type: str, *, enabled: bool = True, secret: bool = True, extra: dict | None = None) -> ConnectorConfig:
    return ConnectorConfig(
        tenant_id="t1",
        connector_type=connector_type,  # type: ignore[arg-type]
        enabled=enabled,
        secret_configured=secret,
        config=extra or {},
    )


# ── Registry ──────────────────────────────────────────────────────────────


def test_registry_covers_every_declared_connector():
    from services.integrations.connectors.adapters import ALL_CONNECTORS

    # A duplicate connector_type would silently collapse in the registry dict.
    assert len(CONNECTORS) == len(ALL_CONNECTORS)
    assert set(CONNECTORS) == {c.connector_type for c in ALL_CONNECTORS}


def test_list_descriptors_returns_all():
    descs = list_descriptors()
    assert len(descs) == len(CONNECTORS)
    types = {d["connector_type"] for d in descs}
    assert "slack" in types
    assert "shopify" in types
    assert "stripe" in types
    assert "dune" in types


# ── BaseConnector ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_disabled_connector_fails_test():
    conn = SlackConnector()
    result = await conn.test_connection(_cfg("slack", enabled=False))
    assert not result.ok
    assert result.status == "disabled"


@pytest.mark.asyncio
async def test_missing_secret_fails_test():
    conn = SlackConnector()
    result = await conn.test_connection(_cfg("slack", secret=False))
    assert not result.ok
    assert result.status == "not_configured"


@pytest.mark.asyncio
async def test_local_mode_fails_closed_when_secret_cannot_be_resolved():
    conn = SlackConnector()
    result = await conn.test_connection(_cfg("slack"))
    assert not result.ok
    assert result.status == "not_configured"


@pytest.mark.asyncio
async def test_pull_default_is_unavailable_not_empty_success():
    conn = SlackConnector()
    with pytest.raises(NotImplementedError):
        await conn.pull(_cfg("slack"))


# ── Webhook parsing ────────────────────────────────────────────────────────


def test_slack_parse_webhook():
    conn = SlackConnector()
    payload = {"event": {"type": "message", "channel": "C1", "user": "U1"}, "event_id": "ev1"}
    events = conn.parse_webhook(payload)
    assert len(events) == 1
    assert events[0].event_type == "slack.message"
    assert events[0].properties["channel"] == "C1"


def test_shopify_parse_webhook():
    conn = ShopifyConnector()
    payload = {"topic": "orders/create", "id": 123, "email": "a@b.com", "total_price": "99.99"}
    events = conn.parse_webhook(payload)
    assert events[0].event_type == "shopify.orders/create"
    assert events[0].external_id == "123"


def test_segment_parse_webhook():
    conn = SegmentConnector()
    payload = {"type": "track", "messageId": "msg1", "event": "Button Clicked", "userId": "u1"}
    events = conn.parse_webhook(payload)
    assert events[0].event_type == "segment.track"
    assert events[0].external_id == "msg1"


def test_stripe_parse_webhook():
    conn = StripeConnector()
    payload = {"type": "payment_intent.succeeded", "id": "evt_1", "data": {"object": {"object": "payment_intent"}}}
    events = conn.parse_webhook(payload)
    assert events[0].event_type == "stripe.payment_intent.succeeded"


@pytest.mark.asyncio
async def test_webhook_connector_configured_with_secret():
    conn = WebhookConnector()
    result = await conn.test_connection(_cfg("webhook"), secret="my-hmac-secret")
    assert result.ok


# ── ConnectorService ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_service_configure_and_list():
    svc = ConnectorService()
    await svc.configure("t1", "slack", name="Workspace Slack", enabled=True, secret_configured=True)
    items = await svc.list_for_tenant("t1")
    slack = next((i for i in items if i["connector_type"] == "slack"), None)
    assert slack is not None
    assert slack["enabled"] is True
    assert slack["name"] == "Workspace Slack"


@pytest.mark.asyncio
async def test_service_test_disabled_connector():
    svc = ConnectorService()
    result = await svc.test("t1", "stripe")
    assert not result.ok
    assert result.status == "disabled"


@pytest.mark.asyncio
async def test_service_sync_disabled_returns_disabled_status():
    svc = ConnectorService()
    result = await svc.sync("t1", "shopify")
    assert result.status == "disabled"


@pytest.mark.asyncio
async def test_service_ingest_webhook_disabled():
    svc = ConnectorService()
    result = await svc.ingest_webhook("slack", "t1", raw_body=b'{"event": {}}')
    assert not result["accepted"]
    assert result["reason"] == "connector disabled"


@pytest.mark.asyncio
async def test_service_ingest_webhook_enabled():
    svc = ConnectorService()
    await svc.configure("t1", "slack", enabled=True, secret_configured=True)
    result = await svc.ingest_webhook(
        "slack", "t1",
        raw_body=b'{"event": {"type": "message", "channel": "C1", "user": "U1"}, "event_id": "e1"}',
    )
    assert result["accepted"] is True
    assert result["events_ingested"] == 1


@pytest.mark.asyncio
async def test_service_secret_resolves_from_vault():
    from repositories.repos import ProvidersRepository
    vault = ProvidersRepository()
    await vault.insert("ref:t1:slack", {
        "id": "ref:t1:slack",
        "tenant_id": "t1",
        "api_key": "xoxb-test-token",
    })

    svc = ConnectorService()
    await svc.configure("t1", "slack", enabled=True, secret_configured=True)
    # Update secret_ref in the config
    from services.integrations.connectors.service import _configs, _key
    cfg_record = await _configs.find_by_id(_key("t1", "slack"))
    assert cfg_record is not None
    cfg_record["secret_ref"] = "ref:t1:slack"
    await _configs.insert(_key("t1", "slack"), cfg_record)

    resolved = await svc._resolve_secret(
        __import__("services.integrations.connectors.base", fromlist=["ConnectorConfig"]).ConnectorConfig(
            tenant_id="t1", connector_type="slack", secret_ref="ref:t1:slack", enabled=True, secret_configured=True  # type: ignore[arg-type]
        )
    )
    assert resolved == "xoxb-test-token"
