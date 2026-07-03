"""Unit tests — multi-projector Silver dispatch (ADR-C3/C4)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

pytest.importorskip("fastapi", reason="Backend deps not installed")


def _click_event(message_id: str = "evt-click-1") -> dict:
    return {
        "type": "email_clicked",
        "messageId": message_id,
        "userId": "user-1",
        "timestamp": "2026-07-01T12:00:00+00:00",
        "context": {"tenantId": "tenant-mp"},
        "properties": {
            "provider": "klaviyo",
            "provider_account_id": "acct-1",
            "provider_event_id": "kl-777",
            "recipient_email": "user@example.com",
            "external_campaign_id": "camp-1",
            "external_message_id": "msg-1",
            "link_id": "link-1",
        },
    }


@pytest.fixture(autouse=True)
def _clean_stores():
    from services.comms.repository import reset_local_stores
    from services.silver.writer import reset_local_tables
    reset_local_stores()
    reset_local_tables()
    yield
    reset_local_stores()
    reset_local_tables()


class TestFanOut:
    def test_comm_event_reaches_multiple_projectors(self):
        from services.silver.dispatcher import SilverDispatcher
        names = SilverDispatcher().projectors_for("email_clicked")
        assert names == ["CommsProjector", "TouchpointProjector"]

    def test_order_is_deterministic_comms_first(self):
        from services.silver.dispatcher import SilverDispatcher
        d = SilverDispatcher()
        for t in ("email_delivered", "email_opened", "email_clicked", "email_replied"):
            names = d.projectors_for(t)
            assert names[0] == "CommsProjector", f"{t}: {names}"

    def test_single_projector_events_unchanged(self):
        from services.silver.dispatcher import SilverDispatcher
        d = SilverDispatcher()
        assert d.projectors_for("page") == ["TouchpointProjector"]
        # Fan-out fixed a latent bug: order_completed previously reached only
        # the last-registered projector (ConversionProjector), silently
        # dropping revenue facts. Both now run, revenue first.
        assert d.projectors_for("order_completed") == [
            "RevenueProjector", "ConversionProjector",
        ]

    @pytest.mark.asyncio
    async def test_both_results_returned(self):
        from services.silver.dispatcher import SilverDispatcher
        outcome = await SilverDispatcher().project_with_outcome(_click_event())
        tables = [r.table for r in outcome.results]
        assert "silver_comms_facts" in tables
        assert "silver_campaign_touchpoint_facts" in tables


class TestFailureIsolation:
    @pytest.mark.asyncio
    async def test_one_projector_failure_does_not_erase_others(self, monkeypatch):
        from services.silver import dispatcher as dispatcher_module
        from services.silver.dispatcher import SilverDispatcher
        from services.silver.projectors.touchpoint_projector import TouchpointProjector

        def _boom(self, event):
            raise RuntimeError("touchpoint exploded")

        monkeypatch.setattr(TouchpointProjector, "project", _boom)
        outcome = await SilverDispatcher().project_with_outcome(_click_event())

        tables = [r.table for r in outcome.results]
        assert "silver_comms_facts" in tables, "comms projection must survive"
        assert "TouchpointProjector" in outcome.failed_projectors
        statuses = {s["projector"]: s["status"] for s in outcome.projector_status}
        assert statuses["CommsProjector"] == "ok"
        assert statuses["TouchpointProjector"] == "error"


class TestReplaySafety:
    @pytest.mark.asyncio
    async def test_replay_creates_no_duplicate_facts(self):
        from services.silver.dispatcher import SilverDispatcher
        from services.silver.writer import SilverFactWriter
        from services.comms.repository import CommsFactsRepository

        d, w = SilverDispatcher(), SilverFactWriter()
        for _ in range(3):
            outcome = await d.project_with_outcome(_click_event())
            await w.persist(outcome.results)

        rows, _ = await CommsFactsRepository().list_for_entity("tenant-mp", "user-1")
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_replay_creates_no_duplicate_activity(self):
        """ADR-C4: one real-world event → one canonical activity idempotency key."""
        from services.silver.dispatcher import SilverDispatcher
        from services.measurement.silver_adapters import adapt_from_silver

        d = SilverDispatcher()
        keys = set()
        for _ in range(2):
            outcome = await d.project_with_outcome(_click_event())
            comms_result = next(r for r in outcome.results if r.table == "silver_comms_facts")
            activity = adapt_from_silver("silver_comms_facts", comms_result.rows[0])
            keys.add(activity["idempotency_key"])
        assert len(keys) == 1

    @pytest.mark.asyncio
    async def test_touchpoint_activity_suppressed_for_comm_events(self, monkeypatch):
        """Only the CommsProjector emits canonical activity for comm events."""
        from services.silver.dispatcher import SilverDispatcher
        from services.silver.projectors.base import BaseProjector

        emitted_tables: list[str] = []

        async def _spy(self, silver_table, rows):
            emitted_tables.append(silver_table)

        monkeypatch.setattr(BaseProjector, "_emit_to_canonical_activity", _spy)
        await SilverDispatcher().project_with_outcome(_click_event())
        assert emitted_tables == ["silver_comms_facts"]
