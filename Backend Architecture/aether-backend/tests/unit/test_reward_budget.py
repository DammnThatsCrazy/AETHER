"""
Unit tests for the concurrency-safe durable budget reservation service (A6).

Proves reserve → commit / release semantics and, critically, that N concurrent
reservations against a budget of K units yield AT MOST K successes — no
oversubscription — on the in-memory backend (single-process asyncio.Lock path;
the PostgreSQL path uses SELECT ... FOR UPDATE for the same guarantee).
"""

from __future__ import annotations

import asyncio
import os
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

os.environ.setdefault("AETHER_ENV", "local")

from repositories.repos import reset_in_memory_stores
from services.rewards.budget import BudgetReservationService, reservation_id
from services.rewards.policy_engine import (
    AttributionResultInput,
    FraudDecisionInput,
    IdentityInput,
    RewardPolicyEngine,
)
from services.rewards.repositories import (
    RewardCampaignRepository,
    RewardDecisionRepository,
    RewardRuleRepository,
)


@pytest.fixture(autouse=True)
def _isolate():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


def _run(coro):
    # Robust against asyncio-auto-mode tests having closed the thread's
    # loop earlier in the same worker: drive on a fresh loop each call.
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(None)


TENANT = "tenant_budget_001"
CAMPAIGN = "camp_budget_001"


# ═══════════════════════════════════════════════════════════════════════════
# reserve / commit / release basics
# ═══════════════════════════════════════════════════════════════════════════

def test_reserve_then_commit_keeps_usage():
    svc = BudgetReservationService()

    async def run():
        r = await svc.reserve(tenant_id=TENANT, campaign_id=CAMPAIGN, amount="10", cap="100", reservation_key="k1")
        assert r.ok and r.state == "reserved"
        c = await svc.commit(r.reservation_id, tenant_id=TENANT)
        assert c.ok and c.state == "committed"
        ledger = await svc.get_ledger(TENANT, CAMPAIGN)
        return ledger

    ledger = _run(run())
    # committed=10, outstanding=0 → used=10
    assert Decimal(ledger["committed"]) == Decimal("10")
    assert Decimal(ledger["outstanding"]) == Decimal("0")


def test_release_frees_budget():
    svc = BudgetReservationService()

    async def run():
        r = await svc.reserve(tenant_id=TENANT, campaign_id=CAMPAIGN, amount="60", cap="100", reservation_key="k1")
        assert r.ok
        # Now only 40 remains; a 60 reservation must fail...
        r2 = await svc.reserve(tenant_id=TENANT, campaign_id=CAMPAIGN, amount="60", cap="100", reservation_key="k2")
        assert not r2.ok and r2.reason == "budget_exceeded"
        # ...until we release the first.
        rel = await svc.release(r.reservation_id, tenant_id=TENANT)
        assert rel.ok and rel.state == "released"
        r3 = await svc.reserve(tenant_id=TENANT, campaign_id=CAMPAIGN, amount="60", cap="100", reservation_key="k3")
        return r3

    r3 = _run(run())
    assert r3.ok


def test_reserve_is_idempotent_per_key():
    svc = BudgetReservationService()

    async def run():
        r1 = await svc.reserve(tenant_id=TENANT, campaign_id=CAMPAIGN, amount="10", cap="100", reservation_key="same")
        r2 = await svc.reserve(tenant_id=TENANT, campaign_id=CAMPAIGN, amount="10", cap="100", reservation_key="same")
        ledger = await svc.get_ledger(TENANT, CAMPAIGN)
        return r1, r2, ledger

    r1, r2, ledger = _run(run())
    assert r1.reservation_id == r2.reservation_id
    assert r2.idempotent is True
    # Only counted ONCE despite two reserve() calls.
    assert Decimal(ledger["outstanding"]) == Decimal("10")


def test_exact_decimal_no_float_artifacts():
    svc = BudgetReservationService()

    async def run():
        # 0.1 + 0.2 must be exactly 0.3 (float would be 0.30000000000000004).
        await svc.reserve(tenant_id=TENANT, campaign_id=CAMPAIGN, amount="0.1", cap="0.3", reservation_key="a")
        await svc.reserve(tenant_id=TENANT, campaign_id=CAMPAIGN, amount="0.2", cap="0.3", reservation_key="b")
        # Exactly at cap: a third tiny reservation must fail.
        r = await svc.reserve(tenant_id=TENANT, campaign_id=CAMPAIGN, amount="0.000001", cap="0.3", reservation_key="c")
        ledger = await svc.get_ledger(TENANT, CAMPAIGN)
        return r, ledger

    r, ledger = _run(run())
    assert not r.ok
    assert Decimal(ledger["outstanding"]) == Decimal("0.3")


# ═══════════════════════════════════════════════════════════════════════════
# CONCURRENCY PROOF: N concurrent reservations against budget K → exactly K
# ═══════════════════════════════════════════════════════════════════════════

def test_concurrent_reservations_never_oversubscribe():
    svc = BudgetReservationService()
    N = 50          # concurrent evaluations
    K = 12          # budget capacity (each reservation = 1 unit)

    async def run():
        async def one(i):
            return await svc.reserve(
                tenant_id=TENANT, campaign_id=CAMPAIGN,
                amount="1", cap=str(K), reservation_key=f"key-{i}",
            )
        results = await asyncio.gather(*[one(i) for i in range(N)])
        ledger = await svc.get_ledger(TENANT, CAMPAIGN)
        return results, ledger

    results, ledger = _run(run())
    granted = [r for r in results if r.ok]
    denied = [r for r in results if not r.ok]
    assert len(granted) == K, f"expected exactly {K} grants, got {len(granted)}"
    assert len(denied) == N - K
    # The ledger's outstanding total must never exceed the cap.
    assert Decimal(ledger["outstanding"]) == Decimal(K)
    assert Decimal(ledger["outstanding"]) <= Decimal(K)


def test_concurrent_fractional_amounts_respect_cap():
    svc = BudgetReservationService()
    N = 40
    amount = Decimal("2.5")
    cap = Decimal("25")   # → exactly 10 fit

    async def run():
        async def one(i):
            return await svc.reserve(
                tenant_id=TENANT, campaign_id=CAMPAIGN,
                amount=str(amount), cap=str(cap), reservation_key=f"f-{i}",
            )
        results = await asyncio.gather(*[one(i) for i in range(N)])
        ledger = await svc.get_ledger(TENANT, CAMPAIGN)
        return results, ledger

    results, ledger = _run(run())
    granted = [r for r in results if r.ok]
    assert len(granted) == 10
    assert Decimal(ledger["outstanding"]) == Decimal("25")


# ═══════════════════════════════════════════════════════════════════════════
# End-to-end through the policy engine: concurrent evaluations, budget-capped
# ═══════════════════════════════════════════════════════════════════════════

async def _seed_budget_campaign(cap: str, per_reward: str):
    cr, rr = RewardCampaignRepository(), RewardRuleRepository()
    campaign = await cr.create(TENANT, {
        "name": "Budget Campaign",
        "status": "active",
        "default_execution_mode": "recommend_only",
        "default_rail": "recommend_only",
        "budget_policy": {"max_total_reward_amount": cap, "enforce": True},
    })
    rule = await rr.create(TENANT, campaign["id"], {
        "name": "Budget Rule",
        "event_types": ["conversion"],
        "min_attribution_weight": 0.0,
        "max_fraud_score": 100.0,
        "cooldown_seconds": 0,
        "max_per_user": 0,          # no per-user cap; budget is the only limit
        "reward_amount": per_reward,
        "reward_unit": "USD",
        "rail": "recommend_only",
        "active": True,
    })
    return cr, rr, campaign, rule


def test_policy_engine_concurrent_eligibility_respects_budget():
    """N concurrent evaluations against a budget of K rewards → exactly K eligible."""
    engine = RewardPolicyEngine()
    budget = BudgetReservationService()
    N = 30
    K = 8  # cap 80 / per_reward 10

    async def run():
        cr, rr, campaign, rule = await _seed_budget_campaign(cap="80", per_reward="10")
        dr = RewardDecisionRepository()

        async def one(i):
            return await engine.evaluate(
                tenant_id=TENANT,
                project_id=None,
                event_type="conversion",
                event_channel="direct",
                event_properties={},
                attribution=AttributionResultInput(
                    attribution_result_id=f"a{i}", attribution_weight=0.9, confidence=0.9, channel="direct",
                ),
                fraud=FraudDecisionInput(fraud_decision_id=f"f{i}", score=1.0, decision="approve"),
                consent=None,
                identity=IdentityInput(user_id=f"user-{i}"),
                idempotency_key=f"idem-{i}",
                campaign_repo=cr,
                rule_repo=rr,
                decision_repo=dr,
                budget_service=budget,
            )

        decisions = await asyncio.gather(*[one(i) for i in range(N)])
        ledger = await budget.get_ledger(TENANT, campaign["id"])
        return decisions, ledger

    decisions, ledger = _run(run())
    eligible = [d for d in decisions if d.eligible]
    blocked = [d for d in decisions if d.decision == "blocked_budget"]
    assert len(eligible) == K, f"expected {K} eligible, got {len(eligible)}"
    assert len(blocked) == N - K
    # Every eligible decision carries a reservation id.
    assert all(d.reservation_id for d in eligible)
    from decimal import Decimal as _D
    assert _D(ledger["outstanding"]) == _D("80")  # 8 * 10, exactly the cap


def test_policy_engine_no_budget_policy_unaffected():
    """Campaigns without an enforced budget policy do not reserve (back-compat)."""
    engine = RewardPolicyEngine()
    budget = BudgetReservationService()

    async def run():
        cr, rr = RewardCampaignRepository(), RewardRuleRepository()
        campaign = await cr.create(TENANT, {
            "name": "No Budget", "status": "active",
            "default_rail": "recommend_only", "budget_policy": {},
        })
        await rr.create(TENANT, campaign["id"], {
            "name": "R", "event_types": ["conversion"], "min_attribution_weight": 0.0,
            "max_fraud_score": 100.0, "cooldown_seconds": 0, "max_per_user": 0,
            "reward_amount": "10", "rail": "recommend_only", "active": True,
        })
        dr = RewardDecisionRepository()
        d = await engine.evaluate(
            tenant_id=TENANT, project_id=None, event_type="conversion", event_channel="direct",
            event_properties={},
            attribution=AttributionResultInput(attribution_result_id="a", attribution_weight=0.9, confidence=0.9),
            fraud=FraudDecisionInput(fraud_decision_id="f", score=1.0, decision="approve"),
            consent=None, identity=IdentityInput(user_id="u1"), idempotency_key="ik",
            campaign_repo=cr, rule_repo=rr, decision_repo=dr, budget_service=budget,
        )
        ledger = await budget.get_ledger(TENANT, campaign["id"])
        return d, ledger

    d, ledger = _run(run())
    assert d.eligible
    assert d.reservation_id is None
    assert ledger is None  # nothing reserved


@pytest.mark.asyncio
async def test_release_stale_skips_reservations_with_live_delivery():
    """N11: release_stale must NOT free a reservation whose reward action is
    still in flight — a recovered outbox would deliver and commit the freed
    reservation as a no-op, letting spend exceed the cap (double-spend)."""
    from services.rewards.repositories import RewardActionRepository

    svc = BudgetReservationService()
    actions = RewardActionRepository()
    tenant = "t-stale"
    campaign = "c-stale"

    r = await svc.reserve(
        tenant_id=tenant, campaign_id=campaign, amount="10", cap="100",
        reservation_key="k-live", decision_id="dec-live",
    )
    assert r.ok
    # A still-in-flight action links to the reservation's decision.
    action = await actions.create(tenant, {"decision_id": "dec-live", "status": "pending", "rail": "internal_credit"})

    # Everything is "stale" (cutoff pushed into the future), but the live
    # delivery must keep its reservation.
    released = await svc.release_stale(max_age_seconds=-3600)
    assert released == 0

    # Once the delivery terminally fails, the budget is legitimately freed.
    await actions.transition(action["id"], tenant, "failed")
    released2 = await svc.release_stale(max_age_seconds=-3600)
    assert released2 == 1


@pytest.mark.asyncio
async def test_release_stale_frees_orphan_reservation():
    """N11: a stale reservation with no linked action (delivery never
    materialized) is still swept — nothing will ever commit it."""
    svc = BudgetReservationService()
    r = await svc.reserve(
        tenant_id="t-orphan", campaign_id="c-orphan", amount="5", cap="100",
        reservation_key="k-orphan", decision_id="dec-orphan-none",
    )
    assert r.ok
    released = await svc.release_stale(max_age_seconds=-3600)
    assert released == 1
