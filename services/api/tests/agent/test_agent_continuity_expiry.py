"""Agent continuity review items expire when nobody reviews them (RK-06a)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from identity.identity.pending_review import (
    AGENT_CONTINUITY_EXPIRED,
    PendingIdentityReviewRepository,
)
from intelligence.agent_behavior import scheduler
from repositories.repos import reset_in_memory_stores

T = "tenant-expiry"


@pytest.fixture(autouse=True)
def _clean():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


async def _item(repo, source="src-a", tenant=T, entry_type="agent_continuity_candidate"):
    return await repo.upsert_candidate(
        tenant_id=tenant, identify_source_identity_id=source,
        candidate_source_identity_ids=[f"{source}-other"], reason_codes=["agent_id_reused"],
        evidence=[], entry_type=entry_type)


async def _age(repo, row, days):
    stale = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    stored = await repo._store.find_by_id(row["id"])
    stored["last_seen_at"] = stale
    stored["created_at"] = stale
    await repo._store.update(row["id"], stored)


@pytest.mark.asyncio
async def test_only_open_items_older_than_the_window_expire():
    repo = PendingIdentityReviewRepository()
    stale = await _item(repo, "stale")
    fresh = await _item(repo, "fresh")
    decided = await _item(repo, "decided")
    other_kind = await _item(repo, "late", entry_type="late_binding_candidate")
    for row in (stale, decided, other_kind):
        await _age(repo, row, 45)
    await repo.decide_agent_continuity(tenant_id=T, record_id=decided["id"],
                                       decision="rejected", decided_by="reviewer")

    assert await repo.expire_stale_agent_continuity(T, older_than_days=30) == 1

    expired = await repo.get(T, stale["id"], entry_type="agent_continuity_candidate")
    assert expired["status"] == AGENT_CONTINUITY_EXPIRED
    assert "agent_continuity_expired" in expired["reason_codes"] and expired["expired_at"]
    assert (await repo.get(T, fresh["id"], entry_type="agent_continuity_candidate"))["status"] == "open"
    assert (await repo.get(T, decided["id"], entry_type="agent_continuity_candidate"))["status"] == "rejected"
    assert (await repo.get(T, other_kind["id"]))["status"] == "open"
    # Expired items leave the queue; the reviewer's decision stays visible.
    ids = {r["id"] for r in await repo.list_agent_continuity(T)}
    assert stale["id"] not in ids and {fresh["id"], decided["id"]} <= ids


@pytest.mark.asyncio
async def test_expiry_is_tenant_scoped_and_zero_days_disables_it():
    repo = PendingIdentityReviewRepository()
    row = await _item(repo, "stale")
    await _age(repo, row, 45)
    assert await repo.expire_stale_agent_continuity("another-tenant", older_than_days=30) == 0
    assert await repo.expire_stale_agent_continuity(T, older_than_days=0) == 0
    assert (await repo.get(T, row["id"], entry_type="agent_continuity_candidate"))["status"] == "open"


@pytest.mark.asyncio
async def test_a_new_report_reopens_an_expired_item():
    repo = PendingIdentityReviewRepository()
    row = await _item(repo, "stale")
    await _age(repo, row, 45)
    await repo.expire_stale_agent_continuity(T, older_than_days=30)

    reopened = await _item(repo, "stale")
    assert reopened["id"] == row["id"] and reopened["status"] == "open"
    assert "agent_continuity_expired" not in reopened["reason_codes"]
    assert "expired_at" not in reopened
    assert row["id"] in {r["id"] for r in await repo.list_agent_continuity(T)}


@pytest.mark.asyncio
async def test_a_decision_after_expiry_is_refused():
    repo = PendingIdentityReviewRepository()
    row = await _item(repo, "stale")
    await _age(repo, row, 45)
    await repo.expire_stale_agent_continuity(T, older_than_days=30)
    assert await repo.decide_agent_continuity(tenant_id=T, record_id=row["id"],
                                              decision="confirmed", decided_by="r") is None


@pytest.mark.asyncio
async def test_behavior_pass_expires_items_for_each_tenant_and_reports_the_count():
    repo = PendingIdentityReviewRepository()
    for tenant in (T, "tenant-two"):
        await _age(repo, await _item(repo, "stale", tenant=tenant), 45)

    report = await scheduler.run_once(agents=[], tenants=[T, "tenant-two"])
    assert report.continuity_reviews_expired == 2 and not report.errors

    disabled = scheduler.PassReport(window=("a", "b"))
    await _age(repo, await _item(repo, "later"), 45)
    await scheduler.expire_continuity_reviews(disabled, tenants=[T], expiry_days=0)
    assert disabled.continuity_reviews_expired == 0
