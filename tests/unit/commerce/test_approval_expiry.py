"""
Unit tests for approval SLA expiry logic.
Creates approvals with real clock, then patches _now for expiry checks.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import os
os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

TENANT = "tenant-expiry-test"


@pytest.fixture(autouse=True)
def reset_store():
    from services.x402.commerce_store import reset_commerce_store
    reset_commerce_store()
    yield
    reset_commerce_store()


@pytest.fixture()
def svc_and_models():
    from services.x402.approvals import ApprovalService
    from services.x402.commerce_models import ApprovalPriority, ApprovalStatus
    return ApprovalService(), ApprovalPriority, ApprovalStatus


async def _make_approval(svc, priority, challenge_id="chg-test"):
    return await svc.request(
        tenant_id=TENANT,
        challenge_id=challenge_id,
        resource_id="res-001",
        requester_id="agent-001",
        requester_type="agent",
        amount_usd=1.0,
        asset_symbol="USDC",
        chain="eip155:8453",
        priority=priority,
    )


def _future_now(seconds: int):
    """Return a _now() replacement that is `seconds` ahead of real time."""
    target = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    return lambda: target


# ── Not-yet-expired (real clock) ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_approval_not_expired_immediately(svc_and_models):
    svc, Priority, _ = svc_and_models
    apr = await _make_approval(svc, Priority.CRITICAL, "chg-fresh-critical")
    assert not svc._is_expired(apr)


@pytest.mark.asyncio
async def test_normal_approval_not_expired_before_sla(svc_and_models):
    svc, Priority, _ = svc_and_models
    apr = await _make_approval(svc, Priority.NORMAL, "chg-fresh-normal")
    assert not svc._is_expired(apr)


# ── Normal SLA (1 hour = 3600s) ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_normal_approval_expires_after_1h(svc_and_models):
    import services.x402.approvals as mod
    svc, Priority, _ = svc_and_models
    apr = await _make_approval(svc, Priority.NORMAL, "chg-normal-exp")
    # Advance _now past expires_at
    with patch.object(mod, "_now", _future_now(3600 + 120)):
        assert svc._is_expired(apr)


# ── High SLA (15 minutes = 900s) ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_high_approval_expires_after_15m(svc_and_models):
    import services.x402.approvals as mod
    svc, Priority, _ = svc_and_models
    apr = await _make_approval(svc, Priority.HIGH, "chg-high-exp")
    with patch.object(mod, "_now", _future_now(900 + 120)):
        assert svc._is_expired(apr)


@pytest.mark.asyncio
async def test_high_approval_not_expired_at_10m(svc_and_models):
    import services.x402.approvals as mod
    svc, Priority, _ = svc_and_models
    apr = await _make_approval(svc, Priority.HIGH, "chg-high-fresh2")
    with patch.object(mod, "_now", _future_now(600)):  # 10 min < 15 min SLA
        assert not svc._is_expired(apr)


# ── Critical SLA (5 minutes = 300s) ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_critical_approval_expires_after_5m(svc_and_models):
    import services.x402.approvals as mod
    svc, Priority, _ = svc_and_models
    apr = await _make_approval(svc, Priority.CRITICAL, "chg-critical-exp")
    with patch.object(mod, "_now", _future_now(300 + 120)):
        assert svc._is_expired(apr)


@pytest.mark.asyncio
async def test_critical_approval_not_expired_at_2m(svc_and_models):
    import services.x402.approvals as mod
    svc, Priority, _ = svc_and_models
    apr = await _make_approval(svc, Priority.CRITICAL, "chg-critical-fresh2")
    with patch.object(mod, "_now", _future_now(120)):  # 2 min < 5 min SLA
        assert not svc._is_expired(apr)


# ── Low SLA (4 hours = 14400s) ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_low_approval_expires_after_4h(svc_and_models):
    import services.x402.approvals as mod
    svc, Priority, _ = svc_and_models
    apr = await _make_approval(svc, Priority.LOW, "chg-low-exp")
    with patch.object(mod, "_now", _future_now(14400 + 120)):
        assert svc._is_expired(apr)


# ── decide() raises on expired ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_decide_on_expired_approval_raises(svc_and_models):
    import services.x402.approvals as mod
    svc, Priority, _ = svc_and_models
    apr = await _make_approval(svc, Priority.CRITICAL, "chg-decide-expired")
    with patch.object(mod, "_now", _future_now(300 + 120)):
        with pytest.raises(ValueError, match="expired"):
            await svc.decide(
                tenant_id=TENANT,
                approval_id=apr.approval_id,
                action="approve",
                decided_by="reviewer-1",
                reason="ok",
            )


# ── sweep_expired() ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sweep_marks_expired_approval(svc_and_models):
    import services.x402.approvals as mod
    svc, Priority, Status = svc_and_models
    apr = await _make_approval(svc, Priority.CRITICAL, "chg-sweep-exp")
    # Run sweep with patched time far in future
    with patch.object(mod, "_now", _future_now(300 + 120)):
        count = await svc.sweep_expired(TENANT)
    assert count >= 1
    updated = await svc.get(TENANT, apr.approval_id)
    assert updated is not None
    assert updated.status == Status.EXPIRED


@pytest.mark.asyncio
async def test_sweep_does_not_mark_fresh_approvals(svc_and_models):
    svc, Priority, Status = svc_and_models
    apr = await _make_approval(svc, Priority.NORMAL, "chg-sweep-fresh")
    count = await svc.sweep_expired(TENANT)
    assert count == 0
    updated = await svc.get(TENANT, apr.approval_id)
    assert updated is not None
    assert updated.status == Status.PENDING
