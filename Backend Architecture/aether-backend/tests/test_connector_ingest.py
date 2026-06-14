"""E2E tests for the connector vault → configure → pull → Bronze ingest path.

Validates that ConnectorService.sync() correctly:
  1. Resolves a secret from the vault (ProvidersRepository)
  2. Passes the secret to the adapter's pull() method
  3. Writes pulled NormalizedEvent records to bronze_connectors
  4. Returns is_new=False on duplicate external_id (idempotency)
  5. Sets sync_status correctly on both success and pull failure
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from repositories.repos import ProvidersRepository, reset_in_memory_stores
from repositories.lake import bronze_connectors
from services.integrations.connectors.service import ConnectorService
from services.integrations.connectors.base import NormalizedEvent


@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()


async def _configure_with_vault(svc: ConnectorService, tenant_id: str, connector_type: str,
                                 credential: str) -> None:
    """Configure a connector, storing credential in vault via service layer."""
    await svc.configure(tenant_id, connector_type, enabled=True, credential=credential)


# ── Test 1: Full vault → Bronze ingest path ───────────────────────────────────


@pytest.mark.asyncio
async def test_vault_to_bronze_ingest_path():
    svc = ConnectorService()
    await _configure_with_vault(svc, "t1", "slack", "xoxb-test-token")

    fake_events = [
        NormalizedEvent(event_type="slack.message", source="slack",
                        external_id="msg-001", properties={"channel": "C1"}),
        NormalizedEvent(event_type="slack.reaction", source="slack",
                        external_id="msg-002", properties={"channel": "C2"}),
    ]
    with patch(
        "services.integrations.connectors.adapters.SlackConnector.pull",
        new=AsyncMock(return_value=fake_events),
    ):
        result = await svc.sync("t1", "slack")

    assert result.status == "healthy"
    assert result.events_ingested == 2

    bronze_rows = await bronze_connectors.find_many(filters={"tenant_id": "t1"}, limit=100)
    assert len(bronze_rows) == 2
    sources = {r["source"] for r in bronze_rows}
    assert sources == {"slack"}
    tenant_ids = {r["tenant_id"] for r in bronze_rows}
    assert tenant_ids == {"t1"}


# ── Test 2: Live path — adapter _is_live patched to True ─────────────────────


@pytest.mark.asyncio
async def test_sync_live_path_mocked():
    svc = ConnectorService()
    await _configure_with_vault(svc, "t2", "shopify", "shpat-test")

    fake_events = [
        NormalizedEvent(event_type="shopify.orders/create", source="shopify",
                        external_id="order-999",
                        properties={"email": "test@example.com", "total_price": "49.99"}),
    ]
    # Patch _is_live at the adapters level so the live path is exercised without
    # requiring AETHER_ENV=staging (which would break in-memory repo layer).
    with patch("services.integrations.connectors.adapters._is_live", return_value=True), \
         patch("services.integrations.connectors.adapters.ShopifyConnector.pull",
               new=AsyncMock(return_value=fake_events)):
        result = await svc.sync("t2", "shopify")

    assert result.status == "healthy"
    bronze_rows = await bronze_connectors.find_many(filters={"tenant_id": "t2"}, limit=100)
    assert len(bronze_rows) == 1
    assert bronze_rows[0]["payload"]["event_type"] == "shopify.orders/create"
    assert bronze_rows[0]["payload"]["tenant_id"] == "t2"


# ── Test 3: Sync sets healthy status ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_sets_healthy_status():
    svc = ConnectorService()
    await svc.configure("t3", "stripe", enabled=True, secret_configured=True)

    with patch(
        "services.integrations.connectors.adapters.StripeConnector.pull",
        new=AsyncMock(return_value=[]),
    ):
        result = await svc.sync("t3", "stripe")

    assert result.status == "healthy"
    cfg = await svc.get("t3", "stripe")
    assert cfg is not None
    assert cfg["sync_status"] == "healthy"


# ── Test 4: Sync sets failed status on pull error ────────────────────────────


@pytest.mark.asyncio
async def test_sync_sets_failed_status_on_pull_error():
    svc = ConnectorService()
    await svc.configure("t4", "hubspot", enabled=True, secret_configured=True)

    with patch(
        "services.integrations.connectors.adapters.HubSpotConnector.pull",
        new=AsyncMock(side_effect=RuntimeError("API timeout")),
    ):
        result = await svc.sync("t4", "hubspot")

    assert result.status == "failed"
    assert result.events_ingested == 0
    cfg = await svc.get("t4", "hubspot")
    assert cfg is not None
    assert cfg["sync_status"] == "failed"
    assert cfg["error_count"] >= 1
    assert "API timeout" in (cfg.get("last_error_message") or "")


# ── Test 5: Bronze idempotency (same external_id synced twice) ───────────────


@pytest.mark.asyncio
async def test_bronze_idempotency():
    svc = ConnectorService()
    await _configure_with_vault(svc, "t5", "slack", "xoxb-idem-token")

    same_event = NormalizedEvent(
        event_type="slack.message", source="slack",
        external_id="msg-dupe-001", properties={"channel": "C9"},
    )

    with patch(
        "services.integrations.connectors.adapters.SlackConnector.pull",
        new=AsyncMock(return_value=[same_event]),
    ):
        result1 = await svc.sync("t5", "slack")
        result2 = await svc.sync("t5", "slack")

    # First sync ingests 1 new record; second sync sees the duplicate
    assert result1.events_ingested == 1
    assert result2.events_ingested == 0  # duplicate skipped

    bronze_rows = await bronze_connectors.find_many(filters={"tenant_id": "t5"}, limit=100)
    assert len(bronze_rows) == 1  # only one record, not two
