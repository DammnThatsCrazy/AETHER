"""
Unit tests for PolicyEngine:
  evaluate() → ALLOW / DENY / REQUIRE_APPROVAL
  Budget policy enforcement (per_transaction_cap_usd).
  Asset/chain compatibility checks.
  Mandatory approval posture (Day-1 GA).
  simulate() dry-run mode.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

TENANT = "tenant-policy-test"
AGENT = "agent-policy-001"


@pytest.fixture(autouse=True)
def reset():
    from services.x402.commerce_store import reset_commerce_store
    reset_commerce_store()
    yield
    reset_commerce_store()


@pytest.fixture()
def engine():
    from services.x402.policies import PolicyEngine
    return PolicyEngine()


def _make_resource(
    resource_id: str = "res-001",
    price_usd: float = 5.0,
    accepted_assets: list | None = None,
    accepted_chains: list | None = None,
    approval_required: bool = True,
):
    from services.x402.commerce_models import ProtectedResource, ResourceClass
    return ProtectedResource(
        resource_id=resource_id,
        tenant_id=TENANT,
        name="Test Resource",
        resource_class=ResourceClass.API,
        price_usd=price_usd,
        accepted_assets=accepted_assets or [],
        accepted_chains=accepted_chains or [],
        approval_required=approval_required,
    )


# ── Mandatory approval (Day-1 GA) ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_default_outcome_is_require_approval(engine):
    """Day-1 GA: all evaluations produce REQUIRE_APPROVAL by default."""
    from services.x402.commerce_models import PolicyOutcome
    resource = _make_resource()
    decision = await engine.evaluate(
        tenant_id=TENANT,
        challenge_id="chg-001",
        resource=resource,
        requester_id=AGENT,
        amount_usd=5.0,
        asset_symbol="USDC",
        chain="eip155:8453",
    )
    assert decision.outcome == PolicyOutcome.REQUIRE_APPROVAL
    assert decision.requires_approval is True


@pytest.mark.asyncio
async def test_mandatory_approval_can_be_disabled(engine):
    """When mandatory approval is disabled and no other rule triggers, outcome is ALLOW."""
    from services.x402.commerce_models import PolicyOutcome
    engine.set_mandatory_approval(False)
    resource = _make_resource(approval_required=False)
    decision = await engine.evaluate(
        tenant_id=TENANT,
        challenge_id="chg-allow",
        resource=resource,
        requester_id=AGENT,
        amount_usd=5.0,
        asset_symbol="USDC",
        chain="eip155:8453",
    )
    assert decision.outcome == PolicyOutcome.ALLOW
    assert decision.requires_approval is False


# ── Asset / chain compatibility ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_deny_unsupported_asset(engine):
    """Asset not in accepted_assets → DENY."""
    from services.x402.commerce_models import PolicyOutcome
    resource = _make_resource(accepted_assets=["USDC"])
    decision = await engine.evaluate(
        tenant_id=TENANT,
        challenge_id="chg-asset",
        resource=resource,
        requester_id=AGENT,
        amount_usd=5.0,
        asset_symbol="DAI",       # not accepted
        chain="eip155:8453",
    )
    assert decision.outcome == PolicyOutcome.DENY
    assert "asset_compatibility" in decision.active_rules
    assert decision.denial_reason is not None


@pytest.mark.asyncio
async def test_allow_accepted_asset(engine):
    """Asset in accepted_assets passes the asset check."""
    from services.x402.commerce_models import PolicyOutcome
    resource = _make_resource(accepted_assets=["USDC"], approval_required=False)
    engine.set_mandatory_approval(False)
    decision = await engine.evaluate(
        tenant_id=TENANT,
        challenge_id="chg-asset-ok",
        resource=resource,
        requester_id=AGENT,
        amount_usd=5.0,
        asset_symbol="USDC",
        chain="eip155:8453",
    )
    assert decision.outcome == PolicyOutcome.ALLOW


@pytest.mark.asyncio
async def test_deny_unsupported_chain(engine):
    """Chain not in accepted_chains → DENY."""
    from services.x402.commerce_models import PolicyOutcome
    resource = _make_resource(accepted_chains=["eip155:8453"])
    decision = await engine.evaluate(
        tenant_id=TENANT,
        challenge_id="chg-chain",
        resource=resource,
        requester_id=AGENT,
        amount_usd=5.0,
        asset_symbol="USDC",
        chain="solana:mainnet",   # not accepted
    )
    assert decision.outcome == PolicyOutcome.DENY
    assert "chain_compatibility" in decision.active_rules


@pytest.mark.asyncio
async def test_empty_accepted_assets_skips_asset_check(engine):
    """Empty accepted_assets list means no asset restriction."""
    from services.x402.commerce_models import PolicyOutcome
    resource = _make_resource(accepted_assets=[])
    decision = await engine.evaluate(
        tenant_id=TENANT,
        challenge_id="chg-open-asset",
        resource=resource,
        requester_id=AGENT,
        amount_usd=5.0,
        asset_symbol="ANYTHING",
        chain="eip155:8453",
    )
    # Should not be denied for asset reason
    assert decision.outcome != PolicyOutcome.DENY or "asset_compatibility" not in decision.active_rules


# ── Budget policy ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_deny_exceeds_per_transaction_cap(engine):
    """Amount exceeding per_transaction_cap_usd → DENY."""
    from services.x402.commerce_models import BudgetPolicy, PolicyOutcome
    from services.x402.commerce_store import get_commerce_store

    store = get_commerce_store()
    policy = BudgetPolicy(
        tenant_id=TENANT,
        subject_id=AGENT,
        per_transaction_cap_usd=10.0,
    )
    await store.put_budget_policy(policy)

    resource = _make_resource()
    decision = await engine.evaluate(
        tenant_id=TENANT,
        challenge_id="chg-budget",
        resource=resource,
        requester_id=AGENT,
        amount_usd=50.0,           # exceeds cap of 10
        asset_symbol="USDC",
        chain="eip155:8453",
    )
    assert decision.outcome == PolicyOutcome.DENY
    assert "budget_per_transaction_cap" in decision.active_rules


@pytest.mark.asyncio
async def test_allow_within_per_transaction_cap(engine):
    """Amount within per_transaction_cap_usd passes budget check."""
    from services.x402.commerce_models import BudgetPolicy, PolicyOutcome
    from services.x402.commerce_store import get_commerce_store

    store = get_commerce_store()
    policy = BudgetPolicy(
        tenant_id=TENANT,
        subject_id=AGENT,
        per_transaction_cap_usd=100.0,
    )
    await store.put_budget_policy(policy)

    resource = _make_resource()
    decision = await engine.evaluate(
        tenant_id=TENANT,
        challenge_id="chg-budget-ok",
        resource=resource,
        requester_id=AGENT,
        amount_usd=5.0,            # within cap
        asset_symbol="USDC",
        chain="eip155:8453",
    )
    # May be REQUIRE_APPROVAL (Day-1), but not DENY
    assert decision.outcome != PolicyOutcome.DENY


@pytest.mark.asyncio
async def test_no_budget_policy_skips_budget_check(engine):
    """No BudgetPolicy → budget check skipped, outcome based on other rules."""
    from services.x402.commerce_models import PolicyOutcome
    resource = _make_resource()
    decision = await engine.evaluate(
        tenant_id=TENANT,
        challenge_id="chg-no-budget",
        resource=resource,
        requester_id="agent-no-budget",
        amount_usd=999.0,   # no cap → should not trigger budget deny
        asset_symbol="USDC",
        chain="eip155:8453",
    )
    # Without a budget policy, should be REQUIRE_APPROVAL (Day-1), not DENY
    assert decision.outcome != PolicyOutcome.DENY


# ── Policy decision persisted ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_evaluate_persists_decision(engine):
    """evaluate() stores PolicyDecision in the commerce store."""
    from services.x402.commerce_store import get_commerce_store
    resource = _make_resource()
    decision = await engine.evaluate(
        tenant_id=TENANT,
        challenge_id="chg-persist",
        resource=resource,
        requester_id=AGENT,
        amount_usd=5.0,
        asset_symbol="USDC",
        chain="eip155:8453",
    )
    store = get_commerce_store()
    stored = await store.get_policy_decision(TENANT, decision.decision_id)
    assert stored is not None
    assert stored.decision_id == decision.decision_id


# ── simulate() dry-run ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_simulate_does_not_persist(engine):
    """simulate() runs evaluation but does NOT persist the PolicyDecision."""
    from services.x402.commerce_store import get_commerce_store
    resource = _make_resource()
    decision = await engine.simulate(
        tenant_id=TENANT,
        resource=resource,
        requester_id=AGENT,
        amount_usd=5.0,
        asset_symbol="USDC",
        chain="eip155:8453",
    )
    # Decision object is returned
    assert decision is not None
    assert decision.decision_id is not None
    # But NOT stored in the commerce store
    store = get_commerce_store()
    stored = await store.get_policy_decision(TENANT, decision.decision_id)
    assert stored is None
