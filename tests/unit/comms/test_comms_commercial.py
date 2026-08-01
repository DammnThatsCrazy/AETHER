"""Communications commercial wiring (§20) — entitlements, quotas, metering."""

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


# ── entitlement policy (pure) ────────────────────────────────────────────────

def test_hobbyist_has_no_comms():
    from services.comms.entitlements import CommsEntitlementPolicy
    from shared.auth.auth import PlanTier
    d = CommsEntitlementPolicy().evaluate_connection(PlanTier.P1_HOBBYIST)
    assert not d.allowed and d.state == "upgrade_required"


def test_professional_allows_lifecycle_up_to_cap():
    from services.comms.entitlements import CommsEntitlementPolicy
    from shared.auth.auth import PlanTier
    policy = CommsEntitlementPolicy()
    assert policy.evaluate_connection(
        PlanTier.P2_PROFESSIONAL, current_connections=0).state == "allowed"
    # cap is 2 → at 2 it's reached (explicit, not silent)
    d = policy.evaluate_connection(PlanTier.P2_PROFESSIONAL, current_connections=2)
    assert not d.allowed and d.state == "quota_reached"
    assert d.limit == 2 and d.current == 2


def test_premium_family_requires_upgrade_on_professional():
    from services.comms.entitlements import CommsEntitlementPolicy
    from shared.auth.auth import PlanTier
    d = CommsEntitlementPolicy().evaluate_connection(
        PlanTier.P2_PROFESSIONAL, provider_family="mailbox")
    assert not d.allowed and d.state == "upgrade_required"


def test_backfill_window_clamped_never_exceeds_plan():
    from services.comms.entitlements import CommsEntitlementPolicy
    from shared.auth.auth import PlanTier
    policy = CommsEntitlementPolicy()
    days, clamped = policy.clamp_backfill_days(PlanTier.P2_PROFESSIONAL, 365)
    assert days == 30 and clamped is True
    days, clamped = policy.clamp_backfill_days(PlanTier.P4_PROTOCOL_MASTER, 365)
    assert days == 365 and clamped is False


def test_event_volume_states():
    from services.comms.entitlements import CommsEntitlementPolicy
    from shared.auth.auth import PlanTier
    policy = CommsEntitlementPolicy()
    # P2 cap 100k → 85k is approaching, 100k reached
    assert policy.evaluate_event_volume(
        PlanTier.P2_PROFESSIONAL, monthly_events=85_000).state == "quota_approaching"
    assert policy.evaluate_event_volume(
        PlanTier.P2_PROFESSIONAL, monthly_events=100_000).state == "quota_reached"
    assert policy.evaluate_event_volume(
        PlanTier.P4_PROTOCOL_MASTER, monthly_events=10_000_000).state == "allowed"


def test_is_comms_connector():
    from services.comms.entitlements import is_comms_connector
    assert is_comms_connector("klaviyo") is True
    assert is_comms_connector("stripe") is False


# ── metering ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_event_metering_is_dedupe_safe():
    from services.comms.metering import record_event_usage
    from services.metering_evidence.service import MeteringEvidenceRepository

    await record_event_usage("t1", event_type="email_clicked",
                             event_id="klaviyo:ev-1", provider="klaviyo")
    # replay same event → recorded but non-billable (double-bill protection)
    await record_event_usage("t1", event_type="email_clicked",
                             event_id="klaviyo:ev-1", provider="klaviyo")

    rows = await MeteringEvidenceRepository().find_many(
        {"tenant_id": "t1", "usage_dimension": "comms_events"}, limit=100)
    assert len(rows) == 2
    billable = [r for r in rows if r.get("billable")]
    assert len(billable) == 1  # exactly one billable; the replay is excluded


@pytest.mark.asyncio
async def test_reply_metered_on_its_own_dimension():
    from services.comms.metering import record_event_usage
    from services.metering_evidence.service import MeteringEvidenceRepository

    await record_event_usage("t1", event_type="email_replied",
                             event_id="klaviyo:r-1", provider="klaviyo")
    repo = MeteringEvidenceRepository()
    events = await repo.find_many({"tenant_id": "t1", "usage_dimension": "comms_events"})
    replies = await repo.find_many({"tenant_id": "t1", "usage_dimension": "comms_reply_events"})
    assert len(events) == 1 and len(replies) == 1  # same event, two dimensions


@pytest.mark.asyncio
async def test_sync_usage_meters_backfill_and_campaigns():
    from services.comms.metering import record_sync_usage
    from services.metering_evidence.service import MeteringEvidenceRepository

    await record_sync_usage("t1", {
        "sync_run_id": "run-1", "provider": "klaviyo", "mode": "backfill",
        "campaigns_created": 3, "profiles_unresolved": 5, "records_received": 42,
    })
    repo = MeteringEvidenceRepository()
    campaigns = await repo.find_many({"tenant_id": "t1", "usage_dimension": "comms_synced_campaigns"})
    backfill = await repo.find_many({"tenant_id": "t1", "usage_dimension": "comms_backfill_records"})
    assert campaigns and campaigns[0]["quantity"] == 3
    assert backfill and backfill[0]["quantity"] == 42
