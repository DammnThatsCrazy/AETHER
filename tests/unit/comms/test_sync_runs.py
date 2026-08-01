"""Durable sync-run ledger (§12.4) — lifecycle, counts, connector-service wiring."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

pytest.importorskip("fastapi", reason="Backend deps not installed")


@pytest.fixture(autouse=True)
def _clean():
    from repositories.repos import _IN_MEMORY_STORES
    _IN_MEMORY_STORES.clear()
    yield
    _IN_MEMORY_STORES.clear()


@pytest.mark.asyncio
async def test_open_complete_list_lifecycle():
    from services.comms.sync_runs import SyncRunService

    svc = SyncRunService()
    run = await svc.open_run(
        tenant_id="t1", connector_instance_id="conn_a", provider="klaviyo",
        mode="backfill", requested_window="2026-06-01T00:00:00Z",
        cursor_before=None, triggered_by="user-1",
    )
    assert run.status == "running" and run.mode == "backfill"
    assert run.effective_window == "2026-06-01T00:00:00Z"

    await svc.complete_run(
        run, status="completed", cursor_after="2026-07-01T00:00:00Z",
        counts={"records_received": 10, "facts_written": 7, "replies_correlated": 2},
    )
    runs = await svc.list_for_connector("t1", "conn_a")
    assert len(runs) == 1
    r = runs[0]
    assert r["status"] == "completed"
    assert r["cursor_after"] == "2026-07-01T00:00:00Z"
    assert r["records_received"] == 10 and r["facts_written"] == 7
    assert r["replies_correlated"] == 2


@pytest.mark.asyncio
async def test_failed_run_records_safe_error():
    from services.comms.sync_runs import SyncRunService

    svc = SyncRunService()
    run = await svc.open_run(
        tenant_id="t1", connector_instance_id="conn_a", provider="klaviyo",
    )
    await svc.complete_run(
        run, status="failed",
        safe_error_code="provider_pull_failed",
        safe_error_detail="HTTP 500 upstream",
    )
    r = (await svc.list_for_connector("t1", "conn_a"))[0]
    assert r["status"] == "failed"
    assert r["safe_error_code"] == "provider_pull_failed"
    assert r["completed_at"] is not None


def test_derive_sync_counts_is_deterministic():
    from services.comms.sync_runs import derive_sync_counts
    from services.integrations.connectors.base import NormalizedEvent

    events = [
        NormalizedEvent(event_type="email_sent", source="klaviyo"),
        NormalizedEvent(event_type="email_replied", source="klaviyo"),
        NormalizedEvent(event_type="unsubscribe_observed", source="klaviyo"),
        NormalizedEvent(event_type="email_spam_complaint", source="klaviyo"),
        NormalizedEvent(event_type="klaviyo.campaign", source="klaviyo"),
        NormalizedEvent(event_type="klaviyo.flow", source="klaviyo"),
        NormalizedEvent(event_type="klaviyo.profile", source="klaviyo"),
    ]
    counts = derive_sync_counts(
        events, {"communications": 4, "catalog": 2, "skipped": 1}, ingested=6
    )
    assert counts["records_received"] == 7
    assert counts["records_deduplicated"] == 1  # 7 received - 6 ingested
    assert counts["facts_written"] == 4
    assert counts["campaigns_created"] == 2  # campaign + flow
    assert counts["replies_correlated"] == 1
    assert counts["suppressions_updated"] == 2  # unsubscribe + complaint
    assert counts["profiles_unresolved"] == 1


@pytest.mark.asyncio
async def test_connector_service_sync_records_run(monkeypatch):
    """A real connector sync opens and closes a durable sync-run entry."""
    from services.integrations.connectors.service import connector_service
    from services.integrations.connectors.klaviyo import KlaviyoConnector
    from services.integrations.connectors.base import NormalizedEvent

    async def fake_pull(self, config, since=None, secret=None):
        return [
            NormalizedEvent(event_type="email_sent", source="klaviyo",
                            external_id="e1", properties={"provider": "klaviyo"}),
            NormalizedEvent(event_type="email_replied", source="klaviyo",
                            external_id="e2", properties={"provider": "klaviyo"}),
        ]

    monkeypatch.setattr(KlaviyoConnector, "pull", fake_pull)

    await connector_service.configure(
        "tenant-x", "klaviyo", name="Klaviyo", enabled=True,
        credential="pk_test_key", actor_id="user-1",
    )
    result = await connector_service.sync("tenant-x", "klaviyo", actor_id="user-1")
    assert result.status == "healthy"

    runs = await connector_service.list_sync_runs("tenant-x", "klaviyo")
    assert len(runs) == 1
    run = runs[0]
    assert run["status"] == "completed"
    assert run["provider"] == "klaviyo"
    assert run["triggered_by"] == "user-1"
    assert run["records_received"] == 2
    assert run["replies_correlated"] == 1
    assert run["cursor_after"] is not None
