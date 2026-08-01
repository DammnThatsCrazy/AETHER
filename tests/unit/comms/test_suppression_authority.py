"""Canonical suppression authority (§16) — recording, state separation,
fail-closed enforcement, idempotency, and observe-only reconciliation."""

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
    from services.comms.repository import _local_suppressions
    _IN_MEMORY_STORES.clear()
    _local_suppressions.clear()
    yield
    _IN_MEMORY_STORES.clear()
    _local_suppressions.clear()


@pytest.mark.asyncio
async def test_record_sets_state_separation_and_is_observe_only():
    from services.comms.suppression_authority import SuppressionAuthorityService

    svc = SuppressionAuthorityService()
    rec = await svc.record(
        "t1", reason="unsubscribe", scope="marketing_channel",
        recipient_alias_id="aliashash", provider="klaviyo",
        provider_account_id="acct-1",
    )
    assert rec["provider_enforcement_state"] == "provider_reported"
    # Write-back off by default → Aether records canonically, never mutates provider.
    assert rec["aether_enforcement_state"] == "write_back_disabled"
    assert rec["active"] is True


@pytest.mark.asyncio
async def test_record_is_idempotent():
    from services.comms.suppression_authority import SuppressionAuthorityService

    svc = SuppressionAuthorityService()
    a = await svc.record("t1", reason="spam_complaint", scope="provider_account",
                         recipient_alias_id="h1", provider="klaviyo")
    b = await svc.record("t1", reason="spam_complaint", scope="provider_account",
                         recipient_alias_id="h1", provider="klaviyo")
    assert a["suppression_id"] == b["suppression_id"]
    rows = await svc.list_for_tenant("t1")
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_record_from_event_maps_signals():
    from services.comms.suppression_authority import SuppressionAuthorityService

    svc = SuppressionAuthorityService()

    # Unsubscribe → recorded
    unsub = await svc.record_from_event("t1", {
        "event_type": "unsubscribe_observed",
        "properties": {"provider": "klaviyo", "recipient_email": "a@example.com",
                       "unsubscribe_scope": "list", "provider_account_id": "acct-1"},
    })
    assert unsub is not None and unsub["scope"] == "list"
    assert unsub["recipient_alias_id"] and "@" not in unsub["recipient_alias_id"]

    # Soft bounce → no suppression
    soft = await svc.record_from_event("t1", {
        "event_type": "email_bounced",
        "properties": {"provider": "klaviyo", "bounce_type": "soft",
                       "recipient_email": "b@example.com"},
    })
    assert soft is None

    # Hard bounce → suppression
    hard = await svc.record_from_event("t1", {
        "event_type": "email_bounced",
        "properties": {"provider": "klaviyo", "bounce_type": "hard",
                       "recipient_email": "c@example.com"},
    })
    assert hard is not None and hard["reason"] == "hard_bounce"

    # Non-suppression event → None
    assert await svc.record_from_event("t1", {"event_type": "email_delivered"}) is None


@pytest.mark.asyncio
async def test_is_suppressed_fails_closed():
    from services.comms.suppression_authority import SuppressionAuthorityService

    svc = SuppressionAuthorityService()
    # No subject → cannot prove not-suppressed → fail closed.
    assert await svc.is_suppressed("t1") is True

    await svc.record("t1", reason="unsubscribe", scope="marketing_channel",
                     recipient_alias_id="hh", provider="klaviyo")
    assert await svc.is_suppressed("t1", recipient_alias_id="hh") is True
    assert await svc.is_suppressed("t1", recipient_alias_id="other") is False


@pytest.mark.asyncio
async def test_reconcile_reports_drift_without_write_back():
    from services.comms.suppression_authority import SuppressionAuthorityService

    svc = SuppressionAuthorityService()
    await svc.record("t1", reason="unsubscribe", scope="marketing_channel",
                     recipient_alias_id="in_both", provider="klaviyo")
    result = await svc.reconcile("t1", provider="klaviyo", provider_reported=[
        {"recipient_alias_id": "in_both"},
        {"recipient_alias_id": "only_provider"},
    ])
    assert result["in_sync"] is False
    assert result["only_in_provider"] == ["only_provider"]
    assert result["write_back_enabled"] is False  # observe-only default
