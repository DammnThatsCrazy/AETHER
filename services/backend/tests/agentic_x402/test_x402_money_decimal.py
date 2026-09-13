"""x402 money-path decimal precision regression tests.

Canonical money rule (financial normalization): amounts are decimal / decimal
strings. Float money must never reach a rollup sum, a money product (unit price
x quantity / discount / fee rate), or an economic-graph leg.

These tests lock the fix in the x402 pricing / interceptor / policies /
settlement / economic-graph paths: fractional USDC/USD amounts price, verify,
and settle with exact decimal results — no binary-float artifacts such as
0.30000000000000004 — and economic-graph legs carry decimal-string amounts.

Runs fully in-memory (AETHER_ENV=local); no external services.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from services.x402.commerce_models import (
    BudgetPolicy,
    PolicyOutcome,
    ProtectedResource,
    ResourceClass,
)

TENANT = "t-money"


@pytest.fixture(autouse=True)
def _reset():
    """Reset all in-memory stores and x402 service singletons between tests."""
    from services.x402 import (
        approvals as apv,
        commerce_store as cs,
        control_plane as cp,
        entitlements as ent,
        facilitators as fac,
        idempotency as idem,
        policies as pol,
        resources as res,
        settlement as stl,
        verification as ver,
    )

    cs.reset_commerce_store()
    idem.reset_idempotency_store()
    cp.reset_control_plane()
    # Reset service singletons so they pick up the new store.
    res._registry = None
    fac._facilitator_registry = None
    fac._asset_registry = None
    apv._service = None
    ver._engine = None
    stl._tracker = None
    ent._service = None
    pol._engine = None
    yield


def _resource(tenant_id: str, price_usd: float) -> ProtectedResource:
    return ProtectedResource(
        tenant_id=tenant_id,
        name="fractional priced resource",
        resource_class=ResourceClass.PRICED_ENDPOINT,
        path_pattern="/v1/test/fractional",
        owner_service="test",
        description="fractional-priced test resource",
        price_usd=price_usd,
        accepted_assets=["USDC"],
        accepted_chains=["eip155:8453"],
    )


# ─── Pricing: unit price x quantity / plan discount is exact Decimal ─────────

async def _register_and_resolve(engine, tenant_id, price_usd, quantity=1, plan_code=None):
    from services.x402.resources import get_resource_registry

    registry = get_resource_registry()
    resource = _resource(tenant_id, price_usd)
    await registry.register(resource)
    return await engine.resolve_price(
        tenant_id, resource.resource_id, plan_code=plan_code, quantity=quantity
    )


@pytest.mark.asyncio
async def test_resolve_price_fractional_quantity_is_exact_decimal():
    """0.10 x 3 must be exactly 0.30 — never 0.30000000000000004."""
    from services.x402.pricing import PricingEngine

    quote = await _register_and_resolve(PricingEngine(), TENANT, 0.10, quantity=3)
    assert Decimal(str(quote["total_usd"])) == Decimal("0.30")
    assert Decimal(str(quote["unit_price_usd"])) == Decimal("0.10")
    # No binary-float artifact (0.1 * 3 === 0.30000000000000004 in float).
    assert json.dumps(quote["total_usd"]) == "0.3"


@pytest.mark.asyncio
async def test_resolve_price_fractional_with_plan_discount_is_exact_decimal():
    """Plan-discount + quantity products stay exact (0.30*0.60 and 0.07*0.80*7)."""
    from services.x402.pricing import PricingEngine

    engine = PricingEngine()

    # enterprise (0.60) on $0.30 = $0.18 exactly.
    quote = await _register_and_resolve(
        engine, TENANT, 0.30, plan_code="enterprise"
    )
    assert Decimal(str(quote["total_usd"])) == Decimal("0.18")
    assert Decimal(str(quote["unit_price_usd"])) == Decimal("0.18")
    assert json.dumps(quote["total_usd"]) == "0.18"

    # 0.07 x 0.80 = 0.056/unit, x7 = 0.392 exactly (float 0.07*0.8*7 drifts).
    quote_b = await _register_and_resolve(
        engine, TENANT + "-b", 0.07, quantity=7, plan_code="pro"
    )
    assert Decimal(str(quote_b["total_usd"])) == Decimal("0.392")
    assert Decimal(str(quote_b["unit_price_usd"])) == Decimal("0.056")


# ─── Interceptor: fee rate product is exact Decimal ─────────────────────────

@pytest.mark.asyncio
async def test_interceptor_fee_elimination_fractional_is_exact():
    """$0.05 * 2.9% == $0.00145 -> half-even round at 4dp == $0.0014.

    The legacy float path computes round(0.05 * 0.029, 4) where the binary
    product is 0.0014500000000000001 and wrongly rounds UP to $0.0015.
    """
    from services.x402.interceptor import X402Interceptor
    from services.x402.models import PaymentTerms

    ic = X402Interceptor()
    terms = PaymentTerms(
        amount=0.05, token="USDC", chain="eip155:8453", recipient="aether:t1"
    )
    tx = await ic.capture(
        payer_agent_id="ag-fee",
        payee_service_id="svc-fee",
        terms=terms,
        request_url="/v1/test/fractional",
        request_method="GET",
    )
    assert tx.fee_eliminated_usd == float(Decimal("0.0014"))
    assert tx.fee_eliminated_usd != float(Decimal("0.0015"))
    assert json.dumps(tx.fee_eliminated_usd) == "0.0014"


# ─── Economic graph: rollup sums never accumulate float drift ───────────────

@pytest.mark.asyncio
async def test_economic_graph_node_totals_have_no_float_drift():
    """Three $0.10 payments must total exactly $0.30 — not 0.30000000000000004."""
    from services.x402.economic_graph import X402EconomicGraph
    from services.x402.models import CapturedX402Transaction, PaymentTerms

    graph = X402EconomicGraph(graph_client=object())  # node-only; no snapshot
    for i in range(3):
        tx = CapturedX402Transaction(
            capture_id=f"drift-{i}",
            payer_agent_id="agent-drift",
            payee_service_id="svc-drift",
            terms=PaymentTerms(
                amount=0.10, token="USDC", chain="eip155:8453", recipient="aether:t1"
            ),
            amount_usd=0.10,
            fee_eliminated_usd=float(Decimal("0.0014")),
        )
        await graph.add_payment(tx, tenant_id=TENANT)

    snap = graph.get_graph_snapshot(tenant_id=TENANT)
    node = snap["nodes"][f"{TENANT}:agent-drift"]
    assert node["total_paid_usd"] == 0.3
    assert json.dumps(node["total_paid_usd"]) == "0.3"
    assert snap["total_volume_usd"] == 0.3
    assert json.dumps(snap["total_volume_usd"]) == "0.3"

    summary = graph.get_spending_patterns("agent-drift", tenant_id=TENANT)
    assert summary.total_spent_usd == 0.3
    assert summary.avg_payment_usd == 0.1
    assert json.dumps(summary.total_spent_usd) == "0.3"


@pytest.mark.asyncio
async def test_economic_graph_pays_edge_amount_is_decimal_string():
    """The PAYS economic-graph leg carries a decimal-string amount, never a
    JSON number that carries float drift."""
    from services.x402.economic_graph import X402EconomicGraph
    from services.x402.models import CapturedX402Transaction, PaymentTerms

    tenant = "t-pays-str"
    graph = X402EconomicGraph(graph_client=None)  # in-memory GraphClient
    tx = CapturedX402Transaction(
        capture_id="cap-str-1",
        payer_agent_id="agent-pays",
        payee_service_id="svc-pays",
        terms=PaymentTerms(
            amount=0.10, token="USDC", chain="eip155:8453", recipient="aether:t1"
        ),
        amount_usd=0.10,
        fee_eliminated_usd=0.0014,
    )
    await graph.add_payment(tx, tenant_id=tenant)
    await graph.snapshot_to_graph()

    edges = await graph._graph.get_edges(f"{tenant}:agent-pays")
    pays = [
        e for e in edges
        if str((e.properties or {}).get("edge_id", "")).endswith(":pays")
    ]
    assert len(pays) == 1
    amount = pays[0].properties["amount"]
    assert isinstance(amount, str)
    assert Decimal(amount) == Decimal("0.10")
    assert amount == "0.1"


# ─── Economic graph mutations: every money leg is a decimal string ──────────

@pytest.mark.asyncio
async def test_economic_mutations_write_money_as_decimal_strings():
    from services.x402.commerce_models import PaymentRequirement
    from services.x402.economic_mutations import EconomicGraphMutations

    tenant = "t-mut-str"
    mutations = EconomicGraphMutations(graph_client=None)  # in-memory GraphClient
    resource = _resource(tenant, 0.30)
    req = PaymentRequirement(
        tenant_id=tenant,
        resource_id=resource.resource_id,
        amount_usd=0.30,
        asset_symbol="USDC",
        chain="eip155:8453",
        recipient="aether:t1",
        expires_at="2026-01-01T00:00:00+00:00",
        requester_id="agent-mut",
    )
    await mutations.write_resource(resource)
    await mutations.write_challenge(req, resource)

    money_legs = []
    for w in mutations.get_trace():
        props = w["properties"]
        for key in ("price_usd", "amount_usd"):
            if key in props:
                money_legs.append((w["kind"], key, props[key]))
    assert len(money_legs) == 3  # resource vertex, requirement vertex, edge

    for kind, key, value in money_legs:
        assert isinstance(value, str), f"{kind} {key} is not a decimal string"
        assert Decimal(value) == Decimal("0.30")


# ─── Policies: fractional cap comparisons are exact Decimal ─────────────────

@pytest.mark.asyncio
async def test_policy_fractional_per_transaction_cap_boundary_exact():
    from services.x402.commerce_store import get_commerce_store
    from services.x402.policies import get_policy_engine
    from services.x402.resources import get_resource_registry

    registry = get_resource_registry()
    resource = _resource(TENANT, 0.10)
    await registry.register(resource)

    store = get_commerce_store()
    await store.put_budget_policy(BudgetPolicy(
        tenant_id=TENANT,
        subject_id="agent-cap",
        per_transaction_cap_usd=0.30,
    ))
    engine = get_policy_engine()

    # amount == cap is NOT a denial (0.30 > 0.30 is false in Decimal and float).
    at_cap = await engine.evaluate(
        tenant_id=TENANT,
        challenge_id="chg-at-cap",
        resource=resource,
        requester_id="agent-cap",
        amount_usd=0.30,
        asset_symbol="USDC",
        chain="eip155:8453",
    )
    assert at_cap.outcome != PolicyOutcome.DENY

    # amount one cent over the fractional cap IS denied.
    over = await engine.evaluate(
        tenant_id=TENANT,
        challenge_id="chg-over-cap",
        resource=resource,
        requester_id="agent-cap",
        amount_usd=0.31,
        asset_symbol="USDC",
        chain="eip155:8453",
    )
    assert over.outcome == PolicyOutcome.DENY
    assert over.denial_reason and "exceeds per-transaction cap" in over.denial_reason


# ─── Settlement: a fractional price settles to the exact decimal amount ──────

@pytest.mark.asyncio
async def test_fractional_price_settles_with_exact_amount():
    """A $0.30 resource issues a challenge, verifies, and settles while the
    amount stays the exact decimal 0.30 at every stage — never a float drift,
    and the on-chain atomic gate maps 0.30 to exactly 300_000 units."""
    from services.x402.control_plane import get_control_plane
    from services.x402.facilitators import seed_facilitators_and_assets
    from services.x402.verification import _expected_atomic
    from services.x402.resources import get_resource_registry

    await seed_facilitators_and_assets(TENANT)
    resource = _resource(TENANT, 0.30)
    await get_resource_registry().register(resource)

    plane = get_control_plane()
    challenge = await plane.issue_challenge(
        tenant_id=TENANT,
        resource_id=resource.resource_id,
        requester_id="agent-pay",
        chain="eip155:8453",
        asset_symbol="USDC",
    )
    assert challenge.amount_usd == resource.price_usd
    assert Decimal(str(challenge.amount_usd)) == Decimal("0.30")

    approval, _ = await plane.request_approval(TENANT, challenge.challenge_id)
    await plane.apply_decision(
        TENANT, approval.approval_id, "approve", "ops", "fractional exactness"
    )
    auth = await plane.authorize_payment(TENANT, approval.approval_id, "0xpayer")
    assert Decimal(str(auth.amount_usd)) == Decimal("0.30")

    result = await plane.verify_and_settle(TENANT, auth.authorization_id, "0x" + "a" * 64)
    assert result["verified"] is True

    store = plane._store
    receipt = await store.get_receipt(TENANT, result["receipt_id"])
    settlement = await store.get_settlement(TENANT, result["settlement_id"])
    assert Decimal(str(receipt.amount_usd)) == Decimal("0.30")
    assert Decimal(str(settlement.amount_usd)) == Decimal("0.30")
    # JSON boundary stays exact — no 0.30000000000000004 anywhere.
    assert json.dumps(settlement.amount_usd) == "0.3"

    # On-chain atomic derivation for a fractional amount is exact.
    assert _expected_atomic(0.30, "USDC") == 300_000
    assert _expected_atomic(0.29, "USDC") == 290_000
