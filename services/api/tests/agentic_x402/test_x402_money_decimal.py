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

from value.x402.commerce_models import (
    ProtectedResource,
    ResourceClass,
)

TENANT = "t-money"


@pytest.fixture(autouse=True)
def _reset():
    """Reset in-memory stores and the remaining x402 singletons between tests."""
    from value.x402 import (
        commerce_store as cs,
        facilitators as fac,
        idempotency as idem,
        verification as ver,
    )

    cs.reset_commerce_store()
    idem.reset_idempotency_store()
    fac._facilitator_registry = None
    fac._asset_registry = None
    ver._engine = None
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


@pytest.mark.asyncio
async def test_interceptor_fee_elimination_fractional_is_exact():
    """$0.05 * 2.9% == $0.00145 -> half-even round at 4dp == $0.0014.

    The legacy float path computes round(0.05 * 0.029, 4) where the binary
    product is 0.0014500000000000001 and wrongly rounds UP to $0.0015.
    """
    from value.x402.interceptor import X402Interceptor
    from value.x402.models import PaymentTerms

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


@pytest.mark.asyncio
async def test_economic_graph_node_totals_have_no_float_drift():
    """Three $0.10 payments must total exactly $0.30 — not 0.30000000000000004."""
    from value.x402.economic_graph import X402EconomicGraph
    from value.x402.models import CapturedX402Transaction, PaymentTerms

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
    from value.x402.economic_graph import X402EconomicGraph
    from value.x402.models import CapturedX402Transaction, PaymentTerms

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


@pytest.mark.asyncio
async def test_economic_mutations_write_money_as_decimal_strings():
    from value.x402.commerce_models import PaymentRequirement
    from value.x402.economic_mutations import EconomicGraphMutations

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
