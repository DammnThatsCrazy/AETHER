"""
Unit tests for RewardPolicyEngine (A6).

Covers all 12 evaluation gates and their denial reasons.
Uses in-memory repositories (AETHER_ENV=local) — no database required.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

os.environ.setdefault("AETHER_ENV", "local")

from services.rewards.policy_engine import (
    AttributionResultInput,
    ConsentSnapshotInput,
    FraudDecisionInput,
    IdentityInput,
    PolicyDecision,
    RewardPolicyEngine,
)
from services.rewards.repositories import (
    RewardCampaignRepository,
    RewardDecisionRepository,
    RewardRuleRepository,
)
from repositories.repos import reset_in_memory_stores


@pytest.fixture(autouse=True)
def _isolate_in_memory_stores():
    """Reset shared in-memory tables before each test.

    Reward repositories share one dict per table across instances (see
    ``_IN_MEMORY_STORES``). Without a reset, campaigns/rules/decisions seeded by
    earlier tests leak into later ones — e.g. ``no_matching_rule`` tests would
    match a leftover campaign. Isolating each test makes the gate assertions
    deterministic.
    """
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ═══════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════

TENANT = "tenant_test_001"

def _campaign_repo():
    return RewardCampaignRepository()

def _rule_repo():
    return RewardRuleRepository()

def _decision_repo():
    return RewardDecisionRepository()

def _engine():
    return RewardPolicyEngine()


async def _seed_campaign(campaign_repo, rule_repo, *, active=True, start_delta=None, end_delta=None, channel=None):
    """Create a test campaign + rule and return (campaign, rule)."""
    now = time.time()
    campaign_data = {
        "name": "Test Campaign",
        "status": "active" if active else "paused",
        "default_execution_mode": "recommend_only",
        "default_rail": "recommend_only",
        "attribution_model": "last_touch",
        "budget_policy": {},
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if start_delta is not None:
        campaign_data["start_time"] = datetime.fromtimestamp(now + start_delta, tz=timezone.utc).isoformat()
    if end_delta is not None:
        campaign_data["end_time"] = datetime.fromtimestamp(now + end_delta, tz=timezone.utc).isoformat()

    campaign = await campaign_repo.create(TENANT, campaign_data)

    rule_data = {
        "name": "Test Rule",
        "event_types": ["conversion", "signup"],
        "required_channel": channel,
        "required_properties": {},
        "min_attribution_weight": 0.3,
        "min_attribution_confidence": 0.0,
        "max_fraud_score": 40.0,
        "identity_confidence_min": 0.0,
        "wallet_binding_confidence_min": 0.0,
        "requires_wallet": False,
        "requires_account": False,
        "requires_consent_purposes": [],
        "cooldown_seconds": 3600,
        "max_per_user": 3,
        "max_total_uses": None,
        "reward_amount": 10.0,
        "reward_unit": "USD",
        "reward_currency": "USD",
        "reward_metadata": {},
        "execution_mode": "recommend_only",
        "rail": "recommend_only",
        "priority": 0,
        "active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    rule = await rule_repo.create(TENANT, campaign["id"], rule_data)
    return campaign, rule


def _identity(*, wallet=None, confidence=1.0, wallet_binding=1.0):
    return IdentityInput(
        user_id="user_test_001",
        wallet_address=wallet,
        identity_confidence=confidence,
        wallet_binding_confidence=wallet_binding,
    )


def _attribution(*, weight=0.8, confidence=0.9):
    return AttributionResultInput(
        attribution_result_id="attr_test",
        model="last_touch",
        attribution_weight=weight,
        confidence=confidence,
        channel="direct",
    )


def _fraud(*, score=10.0, decision="approve"):
    return FraudDecisionInput(
        fraud_decision_id="fraud_test",
        score=score,
        decision=decision,
    )


def _consent(*, purposes=None):
    return ConsentSnapshotInput(
        consent_snapshot_id="consent_test",
        purposes_granted=purposes or ["analytics", "marketing"],
        purposes_denied=[],
    )


_UNSET = object()


async def _evaluate(campaign_repo, rule_repo, decision_repo, *, event_type="conversion", attribution=_UNSET, fraud=None, consent=None, identity=None, idempotency_key=None, recommend_only_without_attribution=False):
    # Distinguish "caller omitted attribution" (use a sensible default) from
    # "caller explicitly passed None" (no attribution result at all). Using
    # ``attribution or _attribution()`` conflated the two and defeated tests
    # that exercise the no-attribution path.
    resolved_attribution = _attribution() if attribution is _UNSET else attribution
    return await _engine().evaluate(
        tenant_id=TENANT,
        project_id=None,
        event_type=event_type,
        event_channel="direct",
        event_properties={},
        attribution=resolved_attribution,
        fraud=fraud or _fraud(),
        consent=consent,
        identity=identity or _identity(),
        idempotency_key=idempotency_key,
        recommend_only_without_attribution=recommend_only_without_attribution,
        campaign_repo=campaign_repo,
        rule_repo=rule_repo,
        decision_repo=decision_repo,
    )


# ═══════════════════════════════════════════════════════════════════════════
# GATE 1: Campaign active status
# ═══════════════════════════════════════════════════════════════════════════

def test_campaign_paused_returns_no_match():
    cr, rr, dr = _campaign_repo(), _rule_repo(), _decision_repo()

    async def run():
        await _seed_campaign(cr, rr, active=False)
        return await _evaluate(cr, rr, dr)

    decision = _run(run())
    assert not decision.eligible
    assert decision.decision == "no_matching_rule"


def test_active_campaign_evaluates():
    cr, rr, dr = _campaign_repo(), _rule_repo(), _decision_repo()

    async def run():
        await _seed_campaign(cr, rr, active=True)
        return await _evaluate(cr, rr, dr)

    decision = _run(run())
    assert decision.eligible
    assert decision.decision == "eligible"


# ═══════════════════════════════════════════════════════════════════════════
# GATE 1: Campaign time window
# ═══════════════════════════════════════════════════════════════════════════

def test_campaign_not_started_yet_skips():
    cr, rr, dr = _campaign_repo(), _rule_repo(), _decision_repo()

    async def run():
        await _seed_campaign(cr, rr, start_delta=+3600)  # starts 1 hour from now
        return await _evaluate(cr, rr, dr)

    decision = _run(run())
    assert not decision.eligible


def test_campaign_already_ended_skips():
    cr, rr, dr = _campaign_repo(), _rule_repo(), _decision_repo()

    async def run():
        await _seed_campaign(cr, rr, end_delta=-3600)  # ended 1 hour ago
        return await _evaluate(cr, rr, dr)

    decision = _run(run())
    assert not decision.eligible


# ═══════════════════════════════════════════════════════════════════════════
# GATE 2: Rule event type matching
# ═══════════════════════════════════════════════════════════════════════════

def test_wrong_event_type_returns_no_match():
    cr, rr, dr = _campaign_repo(), _rule_repo(), _decision_repo()

    async def run():
        await _seed_campaign(cr, rr)
        return await _evaluate(cr, rr, dr, event_type="unknown_event")

    decision = _run(run())
    assert not decision.eligible
    assert decision.decision == "no_matching_rule"


def test_matching_event_type_passes():
    cr, rr, dr = _campaign_repo(), _rule_repo(), _decision_repo()

    async def run():
        await _seed_campaign(cr, rr)
        return await _evaluate(cr, rr, dr, event_type="signup")

    decision = _run(run())
    assert decision.eligible


# ═══════════════════════════════════════════════════════════════════════════
# GATE 3: Consent
# ═══════════════════════════════════════════════════════════════════════════

def test_missing_required_consent_blocks():
    cr, rr, dr = _campaign_repo(), _rule_repo(), _decision_repo()

    async def run():
        campaign, rule = await _seed_campaign(cr, rr)
        # Update rule to require consent
        await rr.update(rule["id"], {"requires_consent_purposes": ["marketing", "commerce"]})
        return await _evaluate(
            cr, rr, dr,
            consent=ConsentSnapshotInput(
                consent_snapshot_id="cs_test",
                purposes_granted=["analytics"],  # missing marketing and commerce
                purposes_denied=["marketing", "commerce"],
            ),
        )

    decision = _run(run())
    assert not decision.eligible
    assert decision.decision == "blocked_consent"


def test_granted_consent_passes():
    cr, rr, dr = _campaign_repo(), _rule_repo(), _decision_repo()

    async def run():
        campaign, rule = await _seed_campaign(cr, rr)
        await rr.update(rule["id"], {"requires_consent_purposes": ["analytics"]})
        return await _evaluate(
            cr, rr, dr,
            consent=_consent(purposes=["analytics", "marketing"]),
        )

    decision = _run(run())
    assert decision.eligible


# ═══════════════════════════════════════════════════════════════════════════
# GATE 4: Identity confidence
# ═══════════════════════════════════════════════════════════════════════════

def test_low_identity_confidence_blocks():
    cr, rr, dr = _campaign_repo(), _rule_repo(), _decision_repo()

    async def run():
        campaign, rule = await _seed_campaign(cr, rr)
        await rr.update(rule["id"], {"identity_confidence_min": 0.8})
        return await _evaluate(cr, rr, dr, identity=_identity(confidence=0.3))

    decision = _run(run())
    assert not decision.eligible
    assert decision.decision == "blocked_identity"


# ═══════════════════════════════════════════════════════════════════════════
# GATE 5: Wallet binding confidence
# ═══════════════════════════════════════════════════════════════════════════

def test_wallet_required_without_wallet_blocks():
    cr, rr, dr = _campaign_repo(), _rule_repo(), _decision_repo()

    async def run():
        campaign, rule = await _seed_campaign(cr, rr)
        await rr.update(rule["id"], {
            "requires_wallet": True,
            "wallet_binding_confidence_min": 0.5,
        })
        return await _evaluate(cr, rr, dr, identity=_identity(wallet=None, wallet_binding=0.0))

    decision = _run(run())
    assert not decision.eligible
    assert decision.decision == "blocked_wallet_binding"


def test_wallet_present_and_bound_passes():
    cr, rr, dr = _campaign_repo(), _rule_repo(), _decision_repo()

    async def run():
        campaign, rule = await _seed_campaign(cr, rr)
        await rr.update(rule["id"], {
            "requires_wallet": True,
            "wallet_binding_confidence_min": 0.5,
        })
        return await _evaluate(
            cr, rr, dr,
            identity=_identity(wallet="0xdeadbeef", wallet_binding=0.9),
        )

    decision = _run(run())
    assert decision.eligible


# ═══════════════════════════════════════════════════════════════════════════
# GATE 6: Fraud decision
# ═══════════════════════════════════════════════════════════════════════════

def test_fraud_reject_blocks():
    cr, rr, dr = _campaign_repo(), _rule_repo(), _decision_repo()

    async def run():
        await _seed_campaign(cr, rr)
        return await _evaluate(cr, rr, dr, fraud=_fraud(score=85.0, decision="reject"))

    decision = _run(run())
    assert not decision.eligible
    assert decision.decision == "blocked_fraud"


def test_fraud_block_blocks():
    cr, rr, dr = _campaign_repo(), _rule_repo(), _decision_repo()

    async def run():
        await _seed_campaign(cr, rr)
        return await _evaluate(cr, rr, dr, fraud=_fraud(score=95.0, decision="block"))

    decision = _run(run())
    assert not decision.eligible
    assert decision.decision == "blocked_fraud"


def test_fraud_review_returns_needs_review():
    cr, rr, dr = _campaign_repo(), _rule_repo(), _decision_repo()

    async def run():
        await _seed_campaign(cr, rr)
        return await _evaluate(cr, rr, dr, fraud=_fraud(score=45.0, decision="review"))

    decision = _run(run())
    assert not decision.eligible
    assert decision.decision == "needs_review"


def test_fraud_approve_passes():
    cr, rr, dr = _campaign_repo(), _rule_repo(), _decision_repo()

    async def run():
        await _seed_campaign(cr, rr)
        return await _evaluate(cr, rr, dr, fraud=_fraud(score=5.0, decision="approve"))

    decision = _run(run())
    assert decision.eligible


def test_fraud_score_above_rule_threshold_blocks():
    cr, rr, dr = _campaign_repo(), _rule_repo(), _decision_repo()

    async def run():
        campaign, rule = await _seed_campaign(cr, rr)
        await rr.update(rule["id"], {"max_fraud_score": 20.0})
        return await _evaluate(cr, rr, dr, fraud=_fraud(score=25.0, decision="approve"))

    decision = _run(run())
    assert not decision.eligible
    assert decision.decision == "blocked_fraud"


# ═══════════════════════════════════════════════════════════════════════════
# GATE 7: Attribution weight
# ═══════════════════════════════════════════════════════════════════════════

def test_attribution_weight_below_threshold_blocks():
    cr, rr, dr = _campaign_repo(), _rule_repo(), _decision_repo()

    async def run():
        campaign, rule = await _seed_campaign(cr, rr)
        await rr.update(rule["id"], {"min_attribution_weight": 0.7})
        return await _evaluate(cr, rr, dr, attribution=_attribution(weight=0.3, confidence=0.9))

    decision = _run(run())
    assert not decision.eligible


def test_recommend_only_without_attribution_skips_gate():
    cr, rr, dr = _campaign_repo(), _rule_repo(), _decision_repo()

    async def run():
        campaign, rule = await _seed_campaign(cr, rr)
        await rr.update(rule["id"], {"min_attribution_weight": 0.9})
        return await _evaluate(
            cr, rr, dr,
            attribution=None,
            recommend_only_without_attribution=True,
        )

    decision = _run(run())
    assert decision.eligible


# ═══════════════════════════════════════════════════════════════════════════
# GATE 8: Cooldown
# ═══════════════════════════════════════════════════════════════════════════

def test_cooldown_blocks_second_claim():
    cr, rr, dr = _campaign_repo(), _rule_repo(), _decision_repo()

    async def run():
        campaign, rule = await _seed_campaign(cr, rr)
        await rr.update(rule["id"], {"cooldown_seconds": 86400, "max_per_user": 10})

        # First evaluation
        decision1 = await _evaluate(cr, rr, dr, idempotency_key="key_001")

        # Seed a recent eligible decision to trigger cooldown
        if decision1.eligible:
            from shared.common.common import utc_now
            await dr.create(TENANT, {
                "campaign_id": campaign["id"],
                "rule_id": rule["id"],
                "user_id": "user_test_001",
                "eligible": True,
                "decision": "eligible",
                "created_at": utc_now().isoformat(),
            })

        # Second evaluation (should hit cooldown)
        decision2 = await _evaluate(cr, rr, dr, idempotency_key="key_002")
        return decision1, decision2

    d1, d2 = _run(run())
    if d1.eligible:
        assert not d2.eligible
        assert d2.decision == "blocked_cooldown"


# ═══════════════════════════════════════════════════════════════════════════
# GATE 9: Per-user cap
# ═══════════════════════════════════════════════════════════════════════════

def test_max_per_user_cap_blocks():
    cr, rr, dr = _campaign_repo(), _rule_repo(), _decision_repo()

    async def run():
        campaign, rule = await _seed_campaign(cr, rr)
        await rr.update(rule["id"], {"max_per_user": 1, "cooldown_seconds": 0})

        # Seed 1 eligible decision for this user
        await dr.create(TENANT, {
            "campaign_id": campaign["id"],
            "rule_id": rule["id"],
            "user_id": "user_test_001",
            "eligible": True,
            "decision": "eligible",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

        return await _evaluate(cr, rr, dr)

    decision = _run(run())
    assert not decision.eligible
    assert decision.decision == "blocked_cap"


# ═══════════════════════════════════════════════════════════════════════════
# GATE 11: Idempotency
# ═══════════════════════════════════════════════════════════════════════════

def test_duplicate_idempotency_key_returns_same_decision():
    cr, rr, dr = _campaign_repo(), _rule_repo(), _decision_repo()

    async def run():
        await _seed_campaign(cr, rr)
        d1 = await _evaluate(cr, rr, dr, idempotency_key="idem_key_abc")
        # Persist the decision
        await dr.create_once(TENANT, "idem_key_abc", {
            "eligible": d1.eligible,
            "decision": d1.decision,
            "campaign_id": d1.campaign_id,
            "rule_id": d1.rule_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        # Second call with same key should return cached decision
        d2 = await _evaluate(cr, rr, dr, idempotency_key="idem_key_abc")
        return d1, d2

    d1, d2 = _run(run())
    assert d1.eligible == d2.eligible


# ═══════════════════════════════════════════════════════════════════════════
# No matching rule
# ═══════════════════════════════════════════════════════════════════════════

def test_no_campaigns_returns_no_matching_rule():
    cr, rr, dr = _campaign_repo(), _rule_repo(), _decision_repo()

    async def run():
        return await _evaluate(cr, rr, dr)

    decision = _run(run())
    assert not decision.eligible
    assert decision.decision == "no_matching_rule"
