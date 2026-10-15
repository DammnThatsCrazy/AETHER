"""Order vocabulary: statuses, projections, currency invariants, extra rules."""

from __future__ import annotations

from decimal import Decimal

import pytest

from shared.commerce_contracts.money import Money
from shared.commerce_contracts.order import (
    CommerceOrder,
    OrderCustomer,
    OrderLineItem,
    OrderSnapshot,
    OrderStatus,
    OrderTotals,
    order_to_snapshot,
)


def _money(amount: str, currency: str = "USD") -> Money:
    return Money(amount=Decimal(amount), currency=currency)


def _line(
    *,
    line_id: str = "li_1",
    currency: str = "USD",
    quantity: int = 1,
) -> OrderLineItem:
    return OrderLineItem(
        line_item_id=line_id,
        product_id="prod_1",
        variant_id="var_1",
        sku="SKU-1",
        title="Widget",
        quantity=quantity,
        unit_price=_money("10.00", currency),
        line_total=_money("10.00", currency),
        attributes={"color": "red"},
    )


def _totals(
    *,
    subtotal: str = "10.00",
    shipping: str = "2.00",
    tax: str = "1.00",
    discount: str = "0.00",
    total: str = "13.00",
    currency: str = "USD",
) -> OrderTotals:
    return OrderTotals(
        subtotal=_money(subtotal, currency),
        shipping=_money(shipping, currency),
        tax=_money(tax, currency),
        discount=_money(discount, currency),
        total=_money(total, currency),
    )


def _order(**overrides) -> CommerceOrder:
    kwargs = dict(
        order_id="ord_1",
        external_id="shopify-1001",
        account_id="acct_1",
        status=OrderStatus.paid,
        currency="USD",
        totals=_totals(),
        line_items=[_line()],
        customer=OrderCustomer(
            customer_id="cus_1",
            email="buyer@example.com",
            first_name="Ada",
            last_name="Lovelace",
        ),
        created_at="2026-08-08T12:00:00Z",
        updated_at="2026-08-08T12:30:00Z",
        note="leave at door",
        properties={"channel": "web"},
    )
    kwargs.update(overrides)
    return CommerceOrder(**kwargs)


# ── OrderStatus vocabulary ─────────────────────────────────────────────────


def test_order_status_enum_values() -> None:
    assert {s.value for s in OrderStatus} == {
        "created",
        "updated",
        "paid",
        "fulfilled",
        "cancelled",
        "refunded",
        "partially_refunded",
    }
    assert OrderStatus("paid") is OrderStatus.paid


# ── CommerceOrder construction ─────────────────────────────────────────────


def test_commerce_order_builds_and_round_trips() -> None:
    order = _order()
    assert order.order_id == "ord_1"
    assert order.external_id == "shopify-1001"
    assert order.status is OrderStatus.paid
    assert order.currency == "USD"
    assert order.totals.total.amount == Decimal("13.00")
    assert len(order.line_items) == 1
    assert order.customer is not None
    assert order.customer.email == "buyer@example.com"
    assert order.schema_version == "1"
    assert order.properties == {"channel": "web"}


def test_commerce_order_preserves_unknown_provider_fields() -> None:
    # extra="allow" is deliberate: provider-specific fields survive in-transit.
    order = _order(**{"shopify_admin_graphql_api_id": "gid://shopify/Order/1"})
    assert order.shopify_admin_graphql_api_id == "gid://shopify/Order/1"  # type: ignore[attr-defined]
    assert "shopify_admin_graphql_api_id" in order.model_dump()


# ── extra="forbid" on the closed sub-models ────────────────────────────────


def test_line_item_rejects_unknown_fields() -> None:
    with pytest.raises(ValueError):
        OrderLineItem(
            line_item_id="li_1",
            product_id="prod_1",
            title="Widget",
            quantity=1,
            unit_price=_money("10.00"),
            line_total=_money("10.00"),
            fulfillment_status="shipped",
        )


def test_totals_rejects_unknown_fields() -> None:
    with pytest.raises(ValueError):
        OrderTotals(
            subtotal=_money("10.00"),
            shipping=_money("2.00"),
            tax=_money("1.00"),
            discount=_money("0.00"),
            total=_money("13.00"),
            duties=_money("0.00"),
        )


def test_customer_rejects_unknown_fields() -> None:
    with pytest.raises(ValueError):
        OrderCustomer(customer_id="cus_1", email="a@b.c", tags=["vip"])


def test_snapshot_rejects_unknown_fields() -> None:
    with pytest.raises(ValueError):
        OrderSnapshot(
            order_id="ord_1",
            status=OrderStatus.paid,
            currency="USD",
            total=_money("13.00"),
            created_at="2026-08-08T12:00:00Z",
            account_id="acct_1",
            note="must not pass",
        )


def test_line_item_quantity_must_be_non_negative() -> None:
    with pytest.raises(ValueError):
        _line(quantity=-1)


# ── single-currency invariants ─────────────────────────────────────────────


def test_totals_with_mixed_currencies_are_rejected() -> None:
    with pytest.raises(ValueError):
        OrderTotals(
            subtotal=_money("10.00", "USD"),
            shipping=_money("2.00", "USD"),
            tax=_money("1.00", "USD"),
            discount=_money("0.00", "USD"),
            total=_money("13.00", "EUR"),  # mismatch
        )


def test_order_currency_must_match_totals() -> None:
    with pytest.raises(ValueError):
        _order(currency="EUR")  # totals are USD


def test_order_line_currency_must_match_order() -> None:
    with pytest.raises(ValueError):
        _order(line_items=[_line(currency="GBP")])


def test_order_line_unit_and_line_total_must_match() -> None:
    with pytest.raises(ValueError):
        _order(
            line_items=[
                OrderLineItem(
                    line_item_id="li_1",
                    product_id="prod_1",
                    title="Widget",
                    quantity=1,
                    unit_price=_money("10.00", "USD"),
                    line_total=_money("10.00", "CAD"),
                )
            ]
        )


def test_standalone_line_item_rejects_mixed_currencies() -> None:
    # The line-level self-check fires even when the line is constructed
    # outside an order (e.g. cart contexts), not only inside CommerceOrder.
    with pytest.raises(ValueError):
        OrderLineItem(
            line_item_id="li_1",
            product_id="prod_1",
            title="Widget",
            quantity=1,
            unit_price=_money("10.00", "USD"),
            line_total=_money("10.00", "CAD"),
        )


# ── OrderSnapshot projection ───────────────────────────────────────────────


def test_order_to_snapshot_projection() -> None:
    order = _order()
    snap = order_to_snapshot(order)
    assert isinstance(snap, OrderSnapshot)
    assert snap.order_id == "ord_1"
    assert snap.status is OrderStatus.paid
    assert snap.currency == "USD"
    assert snap.total.amount == Decimal("13.00")
    assert snap.total.currency == "USD"
    assert snap.created_at == "2026-08-08T12:00:00Z"
    assert snap.updated_at == "2026-08-08T12:30:00Z"
    assert snap.account_id == "acct_1"


def test_order_to_snapshot_drops_provider_fields() -> None:
    snap = order_to_snapshot(_order())
    dumped = snap.model_dump()
    # Snapshot is the small, stable contract — no line items, totals, or extras.
    assert set(dumped) == {
        "order_id",
        "status",
        "currency",
        "total",
        "created_at",
        "updated_at",
        "account_id",
    }


def test_order_to_snapshot_with_nullable_fields() -> None:
    order = _order(
        external_id=None,
        customer=None,
        updated_at=None,
    )
    snap = order_to_snapshot(order)
    assert snap.updated_at is None
    assert snap.status is OrderStatus.paid
    assert snap.total.amount == Decimal("13.00")


def test_snapshot_total_is_money_and_json_serializable() -> None:
    snap = order_to_snapshot(_order())
    json_dump = snap.model_dump(mode="json")
    assert json_dump["total"] == {"amount": "13.00", "currency": "USD"}
    assert json_dump["status"] == "paid"
