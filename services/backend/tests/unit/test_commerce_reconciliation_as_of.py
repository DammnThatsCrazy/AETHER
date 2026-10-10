from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.commerce import order_payment_reconciliation as ledger_module  # noqa: E402
from services.commerce.order_payment_reconciliation import (  # noqa: E402
    CommerceOrderPaymentLedger,
)
from services.economic.operation_linkage import commerce_ledger_operation_link  # noqa: E402


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


def test_stripe_refund_extractor_requires_explicit_order_and_payment_refs():
    from services.integrations.providers.payment_rails.base import ParsedProviderEvent
    from services.integrations.providers.payment_rails.stripe_onramp import StripeOnrampAdapter

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
