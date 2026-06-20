"""Connector vault→pull→ingest E2E integration tests.

Tests the full pipeline: credential store → connector pull → Bronze ingest,
using in-memory repos (AETHER_ENV=local) and monkeypatched HTTP adapters.
"""
from __future__ import annotations

import asyncio
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

BACKEND_ROOT = Path(__file__).parent.parent.parent / "Backend Architecture" / "aether-backend"


@contextmanager
def backend_module_path():
    """Isolate backend imports for each test."""
    original = list(sys.path)
    original_modules = dict(sys.modules)

    for prefix in ("config", "services", "shared", "middleware", "dependencies", "repositories"):
        sys.modules.pop(prefix, None)
        for name in list(sys.modules):
            if name == prefix or name.startswith(f"{prefix}."):
                sys.modules.pop(name, None)

    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original
        sys.modules.clear()
        sys.modules.update(original_modules)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def connector_svc(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    with backend_module_path():
        from services.integrations.connectors.service import ConnectorService
        yield ConnectorService()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(external_id: str = "evt-001"):
    """Build a minimal NormalizedEvent-like object."""
    with backend_module_path():
        from services.integrations.connectors.base import NormalizedEvent
        return NormalizedEvent(
            external_id=external_id,
            event_type="purchase",
            occurred_at="2025-01-01T00:00:00Z",
            payload={"amount": 99.0},
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def _run_shopify_pipeline(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret")

    with backend_module_path():
        from services.integrations.connectors.service import ConnectorService
        from services.integrations.connectors.base import NormalizedEvent, SyncResult

        svc = ConnectorService()
        tenant_id = "test-tenant-shopify"

        # Step 1 — configure connector with a fake credential
        await svc.configure(
            tenant_id,
            "shopify",
            name="E2E Shopify",
            enabled=True,
            credential="fake-shopify-secret",
            actor_id="test",
        )

        # Step 2 — mock the adapter pull and Bronze ingest
        fake_event = NormalizedEvent(
            source="shopify",
            event_type="order_created",
            external_id="order-001",
            occurred_at="2025-01-01T00:00:00Z",
            properties={"total": 150.0},
        )

        async def fake_pull(config, *, since=None, secret=None):
            return [fake_event]

        ingest_calls = []

        async def fake_ingest(*, source, source_tag, provider_record_id, payload, tenant_id):
            ingest_calls.append({"source": source, "payload": payload})
            return ("row-id", True)

        import services.integrations.connectors.registry as reg
        shopify = reg.get_connector("shopify")
        original_pull = shopify.pull
        shopify.pull = fake_pull

        import repositories.lake as lake_mod
        original_ingest = lake_mod.bronze_connectors.ingest
        lake_mod.bronze_connectors.ingest = fake_ingest

        try:
            result = await svc.sync(tenant_id, "shopify", actor_id="test")
        finally:
            shopify.pull = original_pull
            lake_mod.bronze_connectors.ingest = original_ingest

        assert result.status == "healthy", f"Expected healthy, got {result.status}"
        assert result.events_ingested == 1
        assert len(ingest_calls) == 1
        assert ingest_calls[0]["source"] == "shopify"


async def _run_stripe_pipeline(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret")

    with backend_module_path():
        from services.integrations.connectors.service import ConnectorService
        from services.integrations.connectors.base import NormalizedEvent

        svc = ConnectorService()
        tenant_id = "test-tenant-stripe"

        await svc.configure(
            tenant_id,
            "stripe",
            name="E2E Stripe",
            enabled=True,
            credential="fake-stripe-key",
            actor_id="test",
        )

        fake_event = NormalizedEvent(
            source="stripe",
            event_type="charge_succeeded",
            external_id="ch-001",
            occurred_at="2025-01-01T00:00:00Z",
            properties={"amount": 5000},
        )

        ingest_calls = []

        async def fake_pull(config, *, since=None, secret=None):
            return [fake_event]

        async def fake_ingest(*, source, source_tag, provider_record_id, payload, tenant_id):
            ingest_calls.append(source)
            return ("row-id", True)

        import services.integrations.connectors.registry as reg
        stripe = reg.get_connector("stripe")
        original_pull = stripe.pull
        stripe.pull = fake_pull

        import repositories.lake as lake_mod
        original_ingest = lake_mod.bronze_connectors.ingest
        lake_mod.bronze_connectors.ingest = fake_ingest

        try:
            result = await svc.sync(tenant_id, "stripe", actor_id="test")
        finally:
            stripe.pull = original_pull
            lake_mod.bronze_connectors.ingest = original_ingest

        assert result.status == "healthy"
        assert result.events_ingested == 1
        assert "stripe" in ingest_calls


async def _run_slack_pipeline(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret")

    with backend_module_path():
        from services.integrations.connectors.service import ConnectorService
        from services.integrations.connectors.base import NormalizedEvent

        svc = ConnectorService()
        tenant_id = "test-tenant-slack"

        await svc.configure(
            tenant_id,
            "slack",
            name="E2E Slack",
            enabled=True,
            credential="fake-slack-token",
            actor_id="test",
        )

        fake_event = NormalizedEvent(
            source="slack",
            event_type="message_posted",
            external_id="msg-001",
            occurred_at="2025-01-01T00:00:00Z",
            properties={"channel": "#general"},
        )

        ingest_calls = []

        async def fake_pull(config, *, since=None, secret=None):
            return [fake_event]

        async def fake_ingest(*, source, source_tag, provider_record_id, payload, tenant_id):
            ingest_calls.append(source)
            return ("row-id", True)

        import services.integrations.connectors.registry as reg
        slack = reg.get_connector("slack")
        original_pull = slack.pull
        slack.pull = fake_pull

        import repositories.lake as lake_mod
        original_ingest = lake_mod.bronze_connectors.ingest
        lake_mod.bronze_connectors.ingest = fake_ingest

        try:
            result = await svc.sync(tenant_id, "slack", actor_id="test")
        finally:
            slack.pull = original_pull
            lake_mod.bronze_connectors.ingest = original_ingest

        assert result.status == "healthy"
        assert result.events_ingested == 1
        assert "slack" in ingest_calls


def test_shopify_vault_pull_ingest(monkeypatch):
    """Shopify: credential→pull→Bronze ingest pipeline."""
    asyncio.run(_run_shopify_pipeline(monkeypatch))


def test_stripe_vault_pull_ingest(monkeypatch):
    """Stripe: credential→pull→Bronze ingest pipeline."""
    asyncio.run(_run_stripe_pipeline(monkeypatch))


def test_slack_vault_pull_ingest(monkeypatch):
    """Slack: credential→pull→Bronze ingest pipeline."""
    asyncio.run(_run_slack_pipeline(monkeypatch))


def test_disabled_connector_skips_sync(monkeypatch):
    """Disabled connector returns 'disabled' status without calling pull."""
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret")

    async def run():
        with backend_module_path():
            from services.integrations.connectors.service import ConnectorService

            svc = ConnectorService()
            tenant_id = "test-tenant-disabled"

            await svc.configure(
                tenant_id,
                "shopify",
                enabled=False,
                actor_id="test",
            )
            result = await svc.sync(tenant_id, "shopify", actor_id="test")
            assert result.status == "disabled"
            assert result.events_ingested == 0

    asyncio.run(run())
