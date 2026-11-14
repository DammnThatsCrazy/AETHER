from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from value.commerce import order_payment_reconciliation as ledger_module  # noqa: E402
from value.commerce.order_payment_reconciliation import (  # noqa: E402
    CommerceOrderPaymentLedger,
)
from value.economic.operation_linkage import commerce_ledger_operation_link  # noqa: E402


class MemoryStore:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    async def get(self, key: str):
        value = self.rows.get(key)
        return dict(value) if value is not None else None

    async def set(self, key: str, value: dict):
        self.rows[key] = dict(value)

    async def find(self, **filters):
        return [row for row in self.rows.values() if all(row.get(k) == v for k, v in filters.items())]


def _instant(day: int) -> datetime:
    return datetime(2026, 10, day, 12, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_as_of_reconstructs_order_and_payment_knowledge(monkeypatch):
    current = [_instant(1)]
    monkeypatch.setattr(ledger_module, "utc_now", lambda: current[0])
    ledger = CommerceOrderPaymentLedger(MemoryStore())

    await ledger.record_order(
        "tenant-a", commerce_order_ref="shop:1", provider="shopify",
        provider_order_id="1", amount="10.00", currency="USD",
        revision_id="r1", source_revision_at="2026-10-01T10:00:00Z",
        occurred_at="2026-10-01T10:00:00Z",
    )
    current[0] = _instant(2)
    await ledger.record_payment(
        "tenant-a", commerce_order_ref="shop:1", provider="stripe",
        provider_payment_id="pi_1", amount="10.00", currency="USD",
        status="completed", occurred_at="2026-10-02T10:00:00Z",
    )
    current[0] = _instant(3)
    await ledger.record_order(
        "tenant-a", commerce_order_ref="shop:1", provider="shopify",
        provider_order_id="1", amount="12.00", currency="USD",
        revision_id="r2", source_revision_at="2026-10-03T10:00:00Z",
        occurred_at="2026-10-03T10:00:00Z",
    )

    before_payment = await ledger.get_as_of(
        "tenant-a", "shop:1", "2026-10-01T18:00:00Z"
    )
    after_payment = await ledger.get_as_of(
        "tenant-a", "shop:1", "2026-10-02T18:00:00Z"
    )
    after_revision = await ledger.get_as_of(
        "tenant-a", "shop:1", "2026-10-03T18:00:00Z"
    )

    assert before_payment is not None
    assert before_payment["state"] == "order_only"
    assert before_payment["payments"] == {}
    assert after_payment is not None
    assert after_payment["state"] == "matched"
    assert after_payment["order"]["revisionId"] == "r1"
    assert after_revision is not None
    assert after_revision["state"] == "amount_conflict"
    assert after_revision["order"]["revisionId"] == "r2"


@pytest.mark.asyncio
async def test_as_of_does_not_leak_another_tenants_operation(monkeypatch):
    monkeypatch.setattr(ledger_module, "utc_now", lambda: _instant(1))
    ledger = CommerceOrderPaymentLedger(MemoryStore())
    await ledger.record_order(
        "tenant-b", commerce_order_ref="shop:1", provider="shopify",
        provider_order_id="1", amount="10", currency="USD",
        revision_id="r1", source_revision_at="2026-10-01T10:00:00Z",
        occurred_at="2026-10-01T10:00:00Z",
    )

    assert await ledger.get_as_of("tenant-a", "shop:1", "2026-10-02T00:00:00Z") is None


@pytest.mark.asyncio
async def test_payment_source_details_are_as_of_and_conflicts_remain_visible(monkeypatch):
    current = [_instant(1)]
    monkeypatch.setattr(ledger_module, "utc_now", lambda: current[0])
    ledger = CommerceOrderPaymentLedger(MemoryStore())
    base = {
        "commerce_order_ref": "shop:crypto-1",
        "provider": "coinbase",
        "provider_payment_id": "tx-1",
        "amount": "100.00",
        "currency": "USD",
        "status": "completed",
        "occurred_at": "2026-10-01T10:00:00Z",
    }
    await ledger.record_payment("tenant-a", **base)
    current[0] = _instant(2)
    await ledger.record_payment(
        "tenant-a",
        **base,
        payment_rail="coinbase",
        flow_type="crypto_onramp",
        source_amount="100.00",
        source_asset="USD",
        destination_amount="0.05",
        destination_asset="ETH",
        destination_chain="ethereum",
        tx_hash="0xabc123",
    )

    before_enrichment = await ledger.get_as_of(
        "tenant-a", "shop:crypto-1", "2026-10-01T18:00:00Z"
    )
    after_enrichment = await ledger.get_as_of(
        "tenant-a", "shop:crypto-1", "2026-10-02T18:00:00Z"
    )
    assert before_enrichment is not None
    assert "paymentRail" not in before_enrichment["payments"]["coinbase:tx-1"]
    assert after_enrichment is not None
    enriched = after_enrichment["payments"]["coinbase:tx-1"]
    assert enriched["paymentRail"] == "coinbase"
    assert enriched["flowType"] == "crypto_onramp"
    assert enriched["destinationAmount"] == "0.05"
    assert enriched["destinationAsset"] == "ETH"
    assert enriched["destinationChain"] == "ethereum"
    assert enriched["txHash"] == "0xabc123"

    current[0] = _instant(3)
    await ledger.record_payment(
        "tenant-a",
        **base,
        payment_rail="coinbase",
        flow_type="crypto_onramp",
        source_amount="100.00",
        source_asset="USD",
        destination_amount="0.05",
        destination_asset="ETH",
        destination_chain="ethereum",
        tx_hash="0xdivergent",
    )
    conflicted = await ledger.get_as_of(
        "tenant-a", "shop:crypto-1", "2026-10-03T18:00:00Z"
    )
    assert conflicted is not None
    assert conflicted["state"] == "conflict"
    assert conflicted["conflictReason"] == (
        "provider_payment_id_reused_with_divergent_evidence"
    )


@pytest.mark.asyncio
async def test_explicit_refund_is_separate_and_reverses_only_its_payment(monkeypatch):
    current = [_instant(1)]
    monkeypatch.setattr(ledger_module, "utc_now", lambda: current[0])
    ledger = CommerceOrderPaymentLedger(MemoryStore())
    await ledger.record_order(
        "tenant-a", commerce_order_ref="shop:1", provider="shopify",
        provider_order_id="1", amount="10.00", currency="USD",
        revision_id="r1", source_revision_at="2026-10-01T10:00:00Z",
        occurred_at="2026-10-01T10:00:00Z",
    )
    await ledger.record_payment(
        "tenant-a", commerce_order_ref="shop:1", provider="stripe",
        provider_payment_id="pi_1", amount="10.00", currency="USD",
        status="completed", occurred_at="2026-10-01T10:30:00Z",
    )
    current[0] = _instant(2)
    await ledger.record_adjustment(
        "tenant-a", commerce_order_ref="shop:1", provider="stripe",
        adjustment_id="re_1", reverses_payment_id="pi_1", amount="10.00",
        currency="USD", occurred_at="2026-10-02T10:00:00Z",
    )

    before_refund = await ledger.get_as_of("tenant-a", "shop:1", "2026-10-01T18:00:00Z")
    after_refund = await ledger.get("tenant-a", "shop:1")
    assert before_refund is not None
    assert not before_refund.get("adjustments")
    assert after_refund is not None
    link = commerce_ledger_operation_link(after_refund)
    assert {row.role for row in link.records} == {"order", "payment", "refund"}
    assert [(row.relation, row.from_link_ref_id, row.to_link_ref_id) for row in link.relations] == [
        ("fulfills", "payment-0", "order"),
        ("reverses", "refund-0", "payment-0"),
    ]


@pytest.mark.asyncio
async def test_explicit_settlement_links_only_named_payments_and_is_temporal(monkeypatch):
    current = [_instant(1)]
    monkeypatch.setattr(ledger_module, "utc_now", lambda: current[0])
    ledger = CommerceOrderPaymentLedger(MemoryStore())
    await ledger.record_order(
        "tenant-a", commerce_order_ref="shop:1", provider="shopify",
        provider_order_id="1", amount="10.00", currency="USD",
        revision_id="r1", source_revision_at="2026-10-01T10:00:00Z",
        occurred_at="2026-10-01T10:00:00Z",
    )
    await ledger.record_payment(
        "tenant-a", commerce_order_ref="shop:1", provider="stripe",
        provider_payment_id="pi_1", amount="10.00", currency="USD",
        status="completed", occurred_at="2026-10-01T10:30:00Z",
    )

    current[0] = _instant(2)
    await ledger.record_settlement(
        "tenant-a", commerce_order_ref="shop:1", provider="stripe",
        settlement_id="po_1", amount="9.70", currency="USD",
        settled_payment_refs=[
            {"provider": "stripe", "provider_payment_id": "pi_1"},
            {"provider": "stripe", "provider_payment_id": "pi_1"},
        ],
        occurred_at="2026-10-02T10:00:00Z",
    )

    before_settlement = await ledger.get_as_of(
        "tenant-a", "shop:1", "2026-10-01T18:00:00Z"
    )
    after_settlement = await ledger.get_as_of(
        "tenant-a", "shop:1", "2026-10-02T18:00:00Z"
    )
    assert before_settlement is not None
    assert before_settlement["settlements"] == {}
    assert before_settlement["state"] == "matched"
    assert after_settlement is not None
    assert after_settlement["settlements"]["stripe:po_1"]["amount"] == "9.70"
    assert after_settlement["settlements"]["stripe:po_1"]["settlesPaymentRefs"] == [
        {"provider": "stripe", "providerPaymentId": "pi_1"}
    ]

    link = commerce_ledger_operation_link(after_settlement)
    assert link.state == "linked"
    assert {row.role for row in link.records} == {"order", "payment", "settlement"}
    assert [(row.relation, row.from_link_ref_id, row.to_link_ref_id) for row in link.relations] == [
        ("fulfills", "payment-0", "order"),
        ("settled_by", "payment-0", "settlement-0"),
    ]
    assert not any(hasattr(row, "amount") for row in link.records)


@pytest.mark.asyncio
async def test_unmatched_settlement_reference_stays_partial_and_reused_id_conflicts(monkeypatch):
    current = [_instant(1)]
    monkeypatch.setattr(ledger_module, "utc_now", lambda: current[0])
    ledger = CommerceOrderPaymentLedger(MemoryStore())
    await ledger.record_order(
        "tenant-a", commerce_order_ref="shop:1", provider="shopify",
        provider_order_id="1", amount="10.00", currency="USD",
        revision_id="r1", source_revision_at="2026-10-01T10:00:00Z",
        occurred_at="2026-10-01T10:00:00Z",
    )
    await ledger.record_payment(
        "tenant-a", commerce_order_ref="shop:1", provider="stripe",
        provider_payment_id="pi_1", amount="10.00", currency="USD",
        status="completed", occurred_at="2026-10-01T10:30:00Z",
    )
    await ledger.record_settlement(
        "tenant-a", commerce_order_ref="shop:1", provider="stripe",
        settlement_id="po_1", amount="9.70", currency="USD",
        settled_payment_refs=[{"provider": "stripe", "provider_payment_id": "pi_missing"}],
        occurred_at="2026-10-01T11:00:00Z",
    )
    record = await ledger.get("tenant-a", "shop:1")
    assert record is not None
    assert commerce_ledger_operation_link(record).state == "partial"

    current[0] = _instant(2)
    await ledger.record_settlement(
        "tenant-a", commerce_order_ref="shop:1", provider="stripe",
        settlement_id="po_1", amount="8.70", currency="USD",
        settled_payment_refs=[{"provider": "stripe", "provider_payment_id": "pi_1"}],
        occurred_at="2026-10-01T11:00:00Z",
    )
    conflicted = await ledger.get("tenant-a", "shop:1")
    assert conflicted is not None
    assert conflicted["state"] == "conflict"
    assert conflicted["conflictReason"] == "provider_settlement_id_reused_with_divergent_evidence"


def test_stripe_refund_extractor_requires_explicit_order_and_payment_refs():
    from connectors.integrations.providers.payment_rails.base import ParsedProviderEvent
    from connectors.integrations.providers.payment_rails.stripe_onramp import StripeOnrampAdapter

    event = ParsedProviderEvent(
        provider="stripe",
        provider_event_id="evt_refund",
        event_type="charge.refunded",
        occurred_at="2026-10-02T10:00:00Z",
        raw_hash="hash",
        payload={"data": {"object": {
            "payment_intent": "pi_1",
            "currency": "usd",
            "metadata": {"aether_order_ref": "shop:1"},
            "refunds": {"data": [{"id": "re_1", "status": "succeeded", "amount": 1000}]},
        }}},
    )
    assert StripeOnrampAdapter.extract_commerce_adjustments(event) == [{
        "commerce_order_ref": "shop:1",
        "provider": "stripe",
        "adjustment_id": "re_1",
        "reverses_payment_id": "pi_1",
        "amount": "10.00",
        "currency": "USD",
        "occurred_at": "2026-10-02T10:00:00Z",
    }]
    missing_ref = event.model_copy(deep=True)
    missing_ref.payload["data"]["object"]["metadata"] = {}
    assert StripeOnrampAdapter.extract_commerce_adjustments(missing_ref) == []


def test_stripe_payment_rail_and_crypto_order_link_require_explicit_source_fields():
    from connectors.integrations.providers.payment_rails.base import ParsedProviderEvent
    from connectors.integrations.providers.payment_rails.stripe_onramp import StripeOnrampAdapter

    adapter = StripeOnrampAdapter()
    payment_event = ParsedProviderEvent(
        provider="stripe",
        provider_event_id="evt_payment",
        event_type="payment_intent.succeeded",
        occurred_at="2026-10-01T10:00:00Z",
        raw_hash="hash",
        payload={"data": {"object": {
            "id": "pi_card",
            "currency": "usd",
            "amount_received": 1000,
            "payment_method_types": ["card"],
            "metadata": {"aether_order_ref": "shop:1"},
        }}},
    )
    card = adapter.normalize_to_funding_session("tenant-a", payment_event)
    assert card is not None
    assert card.rail == "card"
    assert card.metadata["commerce_order_ref"] == "shop:1"

    ambiguous = payment_event.model_copy(deep=True)
    ambiguous.payload["data"]["object"]["payment_method_types"] = ["card", "us_bank_account"]
    normalized_ambiguous = adapter.normalize_to_funding_session("tenant-a", ambiguous)
    assert normalized_ambiguous is not None
    assert normalized_ambiguous.rail == "stripe"

    onramp_event = ParsedProviderEvent(
        provider="stripe",
        provider_event_id="evt_crypto",
        event_type="crypto.onramp_session_updated",
        occurred_at="2026-10-01T10:00:00Z",
        raw_hash="hash",
        payload={"data": {"object": {
            "id": "cos_1",
            "status": "fulfillment_complete",
            "metadata": {"commerce_order_ref": "shop:crypto-1"},
            "transaction_details": {
                "source_amount": "100.00",
                "source_currency": "usd",
                "destination_amount": "0.05",
                "destination_currency": "eth",
                "destination_network": "ethereum",
                "transaction_hash": "0xabc123",
            },
        }}},
    )
    normalized_onramp = adapter.normalize_to_funding_session("tenant-a", onramp_event)
    assert normalized_onramp is not None
    assert normalized_onramp.metadata["commerce_order_ref"] == "shop:crypto-1"
    assert normalized_onramp.metadata["commerce_payment_amount"] == "100.00"
    assert normalized_onramp.metadata["commerce_payment_currency"] == "USD"
    assert normalized_onramp.tx_hash == "0xabc123"


@pytest.mark.asyncio
async def test_newer_revision_wins_by_instant_not_by_string():
    ledger = CommerceOrderPaymentLedger(MemoryStore())
    common = dict(
        commerce_order_ref="shop:tz", provider="shopify", provider_order_id="1",
        amount="10.00", currency="USD", occurred_at="2026-10-01T09:00:00Z",
    )
    # 09:00Z is later than 10:00+02:00 (08:00Z) although it sorts earlier as text.
    await ledger.record_order(
        "tenant-a", revision_id="r-newer", source_revision_at="2026-10-01T09:00:00Z", **common
    )
    record = await ledger.record_order(
        "tenant-a", revision_id="r-older", source_revision_at="2026-10-01T10:00:00+02:00", **common
    )

    assert record["order"]["revisionId"] == "r-newer"


@pytest.mark.asyncio
async def test_concurrent_order_and_payment_writes_are_both_retained():
    import asyncio

    class SlowStore(MemoryStore):
        async def get(self, key: str):
            value = await super().get(key)
            await asyncio.sleep(0)  # let a concurrent writer read the same row
            return value

    ledger = CommerceOrderPaymentLedger(SlowStore())
    await asyncio.gather(
        ledger.record_order(
            "tenant-a", commerce_order_ref="shop:race", provider="shopify",
            provider_order_id="1", amount="10.00", currency="USD", revision_id="r1",
            source_revision_at="2026-10-01T10:00:00Z", occurred_at="2026-10-01T10:00:00Z",
        ),
        ledger.record_payment(
            "tenant-a", commerce_order_ref="shop:race", provider="stripe",
            provider_payment_id="pay_1", amount="10.00", currency="USD",
            status="succeeded", occurred_at="2026-10-01T10:01:00Z",
        ),
    )

    record = await ledger.get("tenant-a", "shop:race")
    assert record["order"]["providerOrderId"] == "1"
    assert "stripe:pay_1" in record["payments"]


@pytest.mark.asyncio
async def test_all_four_ledger_writers_survive_concurrent_updates_to_one_reference():
    """Order, payment, adjustment and settlement writers race on the same record.

    A conditional-write store (the in-memory, Redis and DynamoDB stores) must keep
    every fact; the previous read-then-set path kept only the last writer's.
    """
    import asyncio

    from shared.store import InMemoryStore

    class _Yielding(InMemoryStore):
        async def get_versioned(self, key):
            result = await super().get_versioned(key)
            await asyncio.sleep(0)
            return result

    ledger = CommerceOrderPaymentLedger(_Yielding("ledger_race"))
    ref = "shop:race-all"
    await asyncio.gather(
        ledger.record_order(
            "tenant-a", commerce_order_ref=ref, provider="shopify", provider_order_id="1",
            amount="10.00", currency="USD", revision_id="r1",
            source_revision_at="2026-10-01T10:00:00Z", occurred_at="2026-10-01T10:00:00Z",
        ),
        ledger.record_payment(
            "tenant-a", commerce_order_ref=ref, provider="stripe", provider_payment_id="pay_1",
            amount="10.00", currency="USD", status="completed", occurred_at="2026-10-01T10:01:00Z",
        ),
        ledger.record_adjustment(
            "tenant-a", commerce_order_ref=ref, provider="stripe", adjustment_id="re_1",
            reverses_payment_id="pay_1", amount="2.00", currency="USD",
            occurred_at="2026-10-01T10:02:00Z",
        ),
        ledger.record_settlement(
            "tenant-a", commerce_order_ref=ref, provider="stripe", settlement_id="po_1",
            amount="10.00", currency="USD",
            settled_payment_refs=[{"provider": "stripe", "provider_payment_id": "pay_1"}],
            occurred_at="2026-10-01T10:03:00Z",
        ),
    )

    record = await ledger.get("tenant-a", ref)
    assert record["order"]["providerOrderId"] == "1"
    assert "stripe:pay_1" in record["payments"]
    assert record["adjustments"], "refund was dropped"
    assert record["settlements"], "settlement was dropped"
