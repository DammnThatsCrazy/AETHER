"""Service-level provider-truth pull pipeline.

Exercises ``PaymentRailsService.status_sync`` end to end: the injected
mock-transport pull persists a resume cursor + provider health on the account,
polled events flow through the SAME status-ordered upsert as webhooks (so a
stale poll can never regress a terminal session), duplicate/out-of-order poll
records are absorbed, and freshness/health SLO metrics are emitted. NO live
network — the adapter singleton's HTTP transport is swapped for a mock.
"""

from __future__ import annotations

import dataclasses
import os
import sys
import uuid
from pathlib import Path

import pytest

os.environ.setdefault("AETHER_ENV", "local")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import mock_providers as mp  # noqa: E402

from config.settings import settings  # noqa: E402
from shared.logger.logger import metrics  # noqa: E402
from services.integrations.providers.payment_rails import ADAPTERS  # noqa: E402
from services.integrations.providers.payment_rails.base import (  # noqa: E402
    get_payment_rails_vault,
)
from services.integrations.providers.payment_rails.repository import (  # noqa: E402
    PaymentRailsRepositories,
)
from services.integrations.providers.payment_rails.service import (  # noqa: E402
    PaymentRailsService,
)

pytestmark = pytest.mark.asyncio(loop_scope="function")


class RecordingProducer:
    def __init__(self) -> None:
        self.events = []

    async def publish(self, event) -> None:
        self.events.append(event)

    async def publish_batch(self, events) -> None:
        self.events.extend(events)


async def _noop(_seconds):
    return None


def _tenant() -> str:
    return f"t-{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def _enable_rails(monkeypatch):
    patched = dataclasses.replace(
        settings.payment_rails,
        enabled=True, privy_enabled=True, stripe_enabled=True,
        coinbase_enabled=True, moonpay_enabled=True, bridge_enabled=True,
        kyber_enabled=True,
    )
    monkeypatch.setattr(settings, "payment_rails", patched)


@pytest.fixture()
def service():
    return PaymentRailsService(
        repositories=PaymentRailsRepositories(), producer=RecordingProducer()
    )


def _inject_transport(monkeypatch, provider: str, transport, request):
    """Swap the singleton adapter's HTTP transport + sleeper for the pull."""
    adapter = ADAPTERS[provider]
    monkeypatch.setattr(adapter, "_http_transport", transport)
    monkeypatch.setattr(adapter, "_sleeper", _noop)
    return adapter


# ── records= path: terminal non-regression + dedupe (no network) ─────────────


class TestPollPipeline:
    async def test_poll_never_regresses_terminal_status(self, service):
        tenant_id = _tenant()
        done = mp.coinbase_tx("cbX", "ONRAMP_TRANSACTION_STATUS_SUCCESS")

        res1 = await service.status_sync(tenant_id, "coinbase", records=[done])
        assert res1["events"][0]["status"] == "completed"
        sessions = await service.repos.sessions.list_for_tenant(tenant_id)
        assert len(sessions) == 1
        session_id = sessions[0]["id"]

        # Exact redelivery -> ignored_duplicate.
        res2 = await service.status_sync(tenant_id, "coinbase", records=[done])
        assert res2["events"][0]["disposition"] == "ignored_duplicate"

        # Out-of-order / regressive poll (in_progress after success) -> blocked.
        prog = mp.coinbase_tx("cbX", "ONRAMP_TRANSACTION_STATUS_IN_PROGRESS")
        res3 = await service.status_sync(tenant_id, "coinbase", records=[prog])
        assert res3["events"][0]["disposition"] == "downgrade_blocked"

        final = await service.repos.sessions.get_record(tenant_id, session_id)
        assert final["status"] == "completed"  # never regressed

    async def test_poll_records_redacted_before_storage(self, service):
        tenant_id = _tenant()
        done = mp.coinbase_tx("cbY", "ONRAMP_TRANSACTION_STATUS_SUCCESS")
        await service.status_sync(tenant_id, "coinbase", records=[done])
        stored = await service.repos.events.list_for_tenant(tenant_id, "coinbase")
        import json
        flat = json.dumps(stored)
        assert not [m for m in mp.SENSITIVE_MARKERS if m in flat]


# ── network pull path: cursor + health persistence + metrics ─────────────────


class TestNetworkPull:
    async def test_cursor_and_health_persisted_and_recovered(
        self, service, monkeypatch, request
    ):
        tenant_id = _tenant()
        secret = "br_secret"
        # Vault created/configured while still local (before flipping env).
        await get_payment_rails_vault().store_key(
            tenant_id, "payment_bridge", "payment", secret
        )
        a1 = mp.bridge_activity("act1", "payment_processed")
        transport, server = mp.bridge_transport(secret=secret, pages={None: [a1]})
        _inject_transport(monkeypatch, "bridge", transport, request)
        monkeypatch.setenv("AETHER_ENV", "staging")  # enable the live pull path

        captured: list[tuple] = []
        monkeypatch.setattr(
            metrics, "gauge",
            lambda name, value, labels=None: captured.append((name, labels)),
        )

        result = await service.status_sync(tenant_id, "bridge", customer_id="cust1")
        assert result["poll_health"] == "ok"

        account = await service.repos.accounts.get(tenant_id, "bridge")
        assert account["sync_cursors"]["cust1"] == "act1"  # resume cursor persisted
        assert account["provider_poll_health"] == "ok"
        assert account.get("last_poll_at")
        # Provider poll-health SLO metric emitted.
        assert any(n == "payment_rail_provider_poll_health" for n, _ in captured)

        # A second sweep resumes from the stored cursor.
        server.requests.clear()
        transport2, server2 = mp.bridge_transport(secret=secret, pages={"act1": []})
        monkeypatch.setattr(ADAPTERS["bridge"], "_http_transport", transport2)
        await service.status_sync(tenant_id, "bridge", customer_id="cust1")
        assert server2.param_values("starting_after") == ["act1"]

    async def test_freshness_metric_emitted_by_health(
        self, service, monkeypatch, request
    ):
        tenant_id = _tenant()
        secret = "br_secret"
        await get_payment_rails_vault().store_key(
            tenant_id, "payment_bridge", "payment", secret
        )
        a1 = mp.bridge_activity("act1", "payment_processed")
        transport, _ = mp.bridge_transport(secret=secret, pages={None: [a1]})
        _inject_transport(monkeypatch, "bridge", transport, request)
        monkeypatch.setenv("AETHER_ENV", "staging")
        await service.status_sync(tenant_id, "bridge", customer_id="cust1")

        captured: list[str] = []
        monkeypatch.setattr(
            metrics, "gauge",
            lambda name, value, labels=None: captured.append(name),
        )
        await service.health(tenant_id)
        assert "payment_rail_provider_freshness_seconds" in captured

    async def test_auth_failure_marks_provider_health(
        self, service, monkeypatch, request
    ):
        tenant_id = _tenant()
        await get_payment_rails_vault().store_key(
            tenant_id, "payment_bridge", "payment", "wrong_secret"
        )
        transport, _ = mp.bridge_transport(secret="right_secret", pages={None: []})
        _inject_transport(monkeypatch, "bridge", transport, request)
        monkeypatch.setenv("AETHER_ENV", "staging")

        result = await service.status_sync(tenant_id, "bridge", customer_id="cust1")
        assert result["poll_health"] == "auth_error"
        account = await service.repos.accounts.get(tenant_id, "bridge")
        assert account["provider_poll_health"] == "auth_error"
