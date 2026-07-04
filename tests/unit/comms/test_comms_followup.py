"""Unit tests — follow-up slice: initiatives, comms population, coalesced
rebuilds, DSR erasure, and dispatcher burst behavior."""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

pytest.importorskip("fastapi", reason="Backend deps not installed")


def _fact(event_type: str, recipient: str, **extra) -> dict:
    return {
        "tenant_id": "tenant-f",
        "campaign_id": "camp-f",
        "source_event_type": event_type,
        "source_event_id": extra.pop("source_event_id", f"{event_type}-{recipient}"),
        "idempotency_key": extra.pop("idempotency_key", f"{event_type}:{recipient}"),
        "recipient_alias_id": recipient,
        "profile_id": extra.pop("profile_id", f"ent-{recipient}"),
        "channel": "email",
        "occurred_at": "2026-07-04T00:00:00+00:00",
        **extra,
    }


@pytest.fixture(autouse=True)
def _clean():
    from services.comms.repository import reset_local_stores
    from services.comms.initiatives import reset_local_initiatives
    reset_local_stores()
    reset_local_initiatives()
    yield
    reset_local_stores()
    reset_local_initiatives()


class TestInitiatives:
    @pytest.mark.asyncio
    async def test_create_add_members_and_rollup(self):
        from services.comms.initiatives import InitiativeRepository, InitiativeRollupService
        from services.comms.repository import CommsFactsRepository

        repo = InitiativeRepository()
        initiative = await repo.create("tenant-f", "Product Launch",
                                       description="Cross-channel launch")
        assert await repo.add_member("tenant-f", initiative["initiative_id"], "camp-f")
        # duplicate add is a no-op
        assert not await repo.add_member("tenant-f", initiative["initiative_id"], "camp-f")

        facts = CommsFactsRepository()
        await facts.upsert(_fact("email_delivered", "r1"))
        await facts.upsert(_fact("email_clicked", "r1"))
        await facts.upsert(_fact("email_replied", "r1"))

        rollup = await InitiativeRollupService().rollup("tenant-f", initiative["initiative_id"])
        assert rollup["member_count"] == 1
        assert rollup["totals"]["delivered"] == 1
        assert rollup["totals"]["human_clicks"] == 1
        assert rollup["totals"]["replies"] == 1
        # cross-channel dedupe limitation is stated, not hidden
        assert any("not deduplicated" in n for n in rollup["notes"])

    @pytest.mark.asyncio
    async def test_rollup_unknown_initiative_returns_none(self):
        from services.comms.initiatives import InitiativeRollupService
        assert await InitiativeRollupService().rollup("tenant-f", "nope") is None

    @pytest.mark.asyncio
    async def test_tenant_isolation(self):
        from services.comms.initiatives import InitiativeRepository
        repo = InitiativeRepository()
        initiative = await repo.create("tenant-f", "Mine")
        assert await repo.get("tenant-other", initiative["initiative_id"]) is None


class TestCommsPopulation:
    @pytest.mark.asyncio
    async def test_stage_classification(self):
        from services.comms.repository import CommsFactsRepository
        facts = CommsFactsRepository()
        # r1: replied; r2: engaged (click); r3: delivered only; r4: attempted only
        await facts.upsert(_fact("email_delivered", "r1"))
        await facts.upsert(_fact("email_replied", "r1"))
        await facts.upsert(_fact("email_delivered", "r2"))
        await facts.upsert(_fact("email_clicked", "r2"))
        await facts.upsert(_fact("email_delivered", "r3"))
        await facts.upsert(_fact("email_sent", "r4"))

        rows = await facts.campaign_population("tenant-f", "camp-f")
        stages = {r["recipient_key"]: r["stage"] for r in rows}
        assert stages == {"r1": "replied", "r2": "engaged",
                          "r3": "delivered", "r4": "attempted"}

    @pytest.mark.asyncio
    async def test_machine_click_does_not_engage(self):
        from services.comms.repository import CommsFactsRepository
        facts = CommsFactsRepository()
        await facts.upsert(_fact("email_delivered", "r5"))
        await facts.upsert(_fact("email_clicked", "r5", suspected_machine_activity=True))
        rows = await facts.campaign_population("tenant-f", "camp-f")
        assert rows[0]["stage"] == "delivered"
        assert rows[0]["human_clicks"] == 0

    @pytest.mark.asyncio
    async def test_flag_filters_compose(self):
        from services.comms.repository import CommsFactsRepository
        facts = CommsFactsRepository()
        await facts.upsert(_fact("email_delivered", "r6"))
        await facts.upsert(_fact("email_bounced", "r6", bounce_type="hard"))
        await facts.upsert(_fact("email_delivered", "r7"))
        await facts.upsert(_fact("unsubscribe_observed", "r7"))

        bounced = await facts.campaign_population("tenant-f", "camp-f", bounced=True)
        assert [r["recipient_key"] for r in bounced] == ["r6"]
        unsub = await facts.campaign_population("tenant-f", "camp-f", unsubscribed=True)
        assert [r["recipient_key"] for r in unsub] == ["r7"]

    @pytest.mark.asyncio
    async def test_rows_link_to_profile360_without_raw_addresses(self):
        from services.comms.repository import CommsFactsRepository
        facts = CommsFactsRepository()
        await facts.upsert(_fact("email_delivered", "r8", recipient_display="j***@e***.com"))
        rows = await facts.campaign_population("tenant-f", "camp-f")
        assert rows[0]["profile360"] == "/v1/profile/ent-r8"
        assert "@" not in str(rows[0]).replace("j***@e***.com", "")


class TestRebuildCoalescer:
    @pytest.mark.asyncio
    async def test_burst_coalesces_to_one_rebuild(self):
        from services.comms.rebuild_coalescer import JourneyRebuildCoalescer
        coalescer = JourneyRebuildCoalescer(window_seconds=60)
        for i in range(25):
            await coalescer.request_rebuild("tenant-f", "ent-1", reason=f"e{i}")
        assert coalescer.pending_count == 1
        outcome = await coalescer.flush_key(("tenant-f", "ent-1"))
        assert outcome["coalesced_events"] == 25
        assert outcome["state_rebuilt"] is True
        assert coalescer.pending_count == 0

    @pytest.mark.asyncio
    async def test_distinct_profiles_do_not_coalesce(self):
        from services.comms.rebuild_coalescer import JourneyRebuildCoalescer
        coalescer = JourneyRebuildCoalescer(window_seconds=60)
        await coalescer.request_rebuild("tenant-f", "ent-a")
        await coalescer.request_rebuild("tenant-f", "ent-b")
        await coalescer.request_rebuild("tenant-g", "ent-a")
        assert coalescer.pending_count == 3
        assert await coalescer.flush_all() == 3

    @pytest.mark.asyncio
    async def test_window_flush_fires_automatically(self):
        import asyncio
        from services.comms.rebuild_coalescer import JourneyRebuildCoalescer
        coalescer = JourneyRebuildCoalescer(window_seconds=0.05)
        await coalescer.request_rebuild("tenant-f", "ent-t")
        await asyncio.sleep(0.2)
        assert coalescer.pending_count == 0


class TestDsrErasure:
    @pytest.mark.asyncio
    async def test_tombstone_removes_facts_and_state(self):
        from services.comms.repository import CommsFactsRepository
        from services.comms.state import CommunicationStateService

        facts = CommsFactsRepository()
        await facts.upsert(_fact("email_delivered", "r9", profile_id="ent-dsr"))
        await facts.upsert(_fact("email_clicked", "r9", profile_id="ent-dsr"))
        await CommunicationStateService().rebuild_for_entity("tenant-f", "ent-dsr")

        removed = await facts.tombstone_by_profile("tenant-f", "ent-dsr")
        assert removed == 2
        rows, _ = await facts.list_for_entity("tenant-f", "ent-dsr")
        assert rows == []
        assert await CommunicationStateService().get("tenant-f", "ent-dsr") is None

    @pytest.mark.asyncio
    async def test_tombstone_is_tenant_scoped(self):
        from services.comms.repository import CommsFactsRepository
        facts = CommsFactsRepository()
        await facts.upsert(_fact("email_delivered", "r10", profile_id="ent-x"))
        removed = await facts.tombstone_by_profile("tenant-other", "ent-x")
        assert removed == 0
        rows, _ = await facts.list_for_entity("tenant-f", "ent-x")
        assert len(rows) == 1


class TestDispatcherBurst:
    """Bounded load check: a webhook-scale burst projects without duplicates
    and inside a sane time budget (local in-memory mode)."""

    @pytest.mark.asyncio
    async def test_burst_of_500_events_projects_cleanly(self):
        from services.silver.dispatcher import SilverDispatcher
        from services.silver.writer import SilverFactWriter
        from services.comms.repository import CommsFactsRepository

        dispatcher, writer = SilverDispatcher(), SilverFactWriter()
        started = time.monotonic()
        for i in range(500):
            event = {
                "type": "email_delivered",
                "messageId": f"burst-{i}",
                "userId": f"user-{i % 50}",
                "timestamp": "2026-07-04T00:00:00+00:00",
                "context": {"tenantId": "tenant-f"},
                "properties": {
                    "provider": "webhook", "provider_event_id": f"burst-{i}",
                    "recipient_email": f"user{i % 50}@example.com",
                },
            }
            outcome = await dispatcher.project_with_outcome(event)
            await writer.persist(outcome.results)
        elapsed = time.monotonic() - started
        assert elapsed < 30, f"burst took {elapsed:.1f}s"

        rows, _ = await CommsFactsRepository().list_for_entity(
            "tenant-f", "user-0", limit=200,
        )
        assert len(rows) == 10  # 500 events / 50 recipients, no duplicates
