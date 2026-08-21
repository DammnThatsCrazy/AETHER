"""Canonical commerce order vocabulary for the provider-neutral runtime.

This package owns the *provider-neutral* shapes of a commerce order. A
provider adapter (e.g. the Shopify plugin) maps its native order onto these
models; downstream consumers (pipelines, analytics, outboxes) read only these
shapes, so provider churn stays behind the adapter seam.

Invariants enforced here:

* :class:`OrderLineItem`, :class:`OrderTotals`, :class:`OrderCustomer`, and
  :class:`OrderSnapshot` are closed (`extra="forbid"`) — unknown fields fail
  loudly so a drift in one provider's payload cannot silently pass through.
* :class:`CommerceOrder` is open (`extra="allow"`) so provider-specific fields
  are preserved in-transit rather than dropped.
* Every :class:`Money` in an order shares one currency; mixed-currency orders
  are rejected at construction time — enforced at the line level
  (:class:`OrderLineItem` unit price vs. line total), the totals level
  (:class:`OrderTotals`), and the order level (:class:`CommerceOrder`
  order currency vs. totals vs. every line).
* :class:`OrderSnapshot` is the canonical projection used as the payload of a
  commerce :mod:`AetherEvent <shared.integration_contracts.events>`; it is
  intentionally small and self-contained so it never depends on the event
  envelope.

This module is fully self-contained (stdlib + pydantic). It does **not**
import from ``shared.integration_contracts`` so it stays importable regardless
of Team A's in-flight event envelope work.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.commerce_contracts.money import Money


class OrderStatus(str, Enum):
    """Canonical, provider-neutral order lifecycle status."""

    created = "created"
    updated = "updated"
    paid = "paid"
    fulfilled = "fulfilled"
    cancelled = "cancelled"
    refunded = "refunded"
    partially_refunded = "partially_refunded"


class OrderLineItem(BaseModel):
    """A single purchased line on an order (extra fields are rejected)."""

    model_config = ConfigDict(extra="forbid")

    line_item_id: str
    product_id: str
    variant_id: Optional[str] = None
    sku: Optional[str] = None
    title: str
    quantity: int = Field(ge=0)
    unit_price: Money
    line_total: Money
    attributes: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_single_currency(self) -> "OrderLineItem":
        if self.unit_price.currency != self.line_total.currency:
            raise ValueError(
                "OrderLineItem mixes currencies between unit_price and "
                f"line_total: {self.unit_price.currency!r} != "
                f"{self.line_total.currency!r}"
            )
        return self


class OrderTotals(BaseModel):
    """Money breakdown for an order (extra fields are rejected).

    All five amounts must share one currency.
    """

    model_config = ConfigDict(extra="forbid")

    subtotal: Money
    shipping: Money
    tax: Money
    discount: Money
    total: Money

    @model_validator(mode="after")
    def _check_single_currency(self) -> "OrderTotals":
        currencies = {
            self.subtotal.currency,
            self.shipping.currency,
            self.tax.currency,
            self.discount.currency,
            self.total.currency,
        }
        if len(currencies) != 1:
            raise ValueError(
                f"OrderTotals mixes currencies: {sorted(currencies)}"
            )
        return self


class OrderCustomer(BaseModel):
    """Minimal customer reference on an order (extra fields are rejected)."""

    model_config = ConfigDict(extra="forbid")

    customer_id: str
    email: Optional[str] = None
    phone: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None


class CommerceOrder(BaseModel):
    """Provider-neutral commerce order.

    ``extra="allow"`` by design: unknown provider fields are preserved
    in-transit so adapters can round-trip their native payload without losing
    data.

    All :class:`Money` fields (totals + every line) must share one currency,
    matching :attr:`currency`.
    """

    model_config = ConfigDict(extra="allow")

    order_id: str
    external_id: Optional[str] = None
    account_id: str
    status: OrderStatus
    currency: str
    totals: OrderTotals
    line_items: list[OrderLineItem]
    customer: Optional[OrderCustomer] = None
    created_at: str  # ISO-8601 UTC, caller-supplied (no datetime.now defaults)
    updated_at: Optional[str] = None
    note: Optional[str] = None
    properties: dict[str, Any] = Field(default_factory=dict)
    schema_version: str = "1"

    @model_validator(mode="after")
    def _check_single_currency(self) -> "CommerceOrder":
        # ``OrderTotals._check_single_currency`` already guarantees all five
        # totals share one currency, so any totals Money field is representative.
        currencies = {self.currency, self.totals.total.currency}
        for line in self.line_items:
            currencies.add(line.unit_price.currency)
            currencies.add(line.line_total.currency)
        if len(currencies) != 1:
            raise ValueError(
                f"CommerceOrder mixes currencies: {sorted(currencies)}"
            )
        return self


class OrderSnapshot(BaseModel):
    """Canonical projection of an order for :attr:`AetherEvent.data`.

    ``extra="forbid"``: the snapshot is the stable, versioned contract
    downstream consumers depend on — unknown fields must not slip through.
    """

    model_config = ConfigDict(extra="forbid")

    order_id: str
    status: OrderStatus
    currency: str
    total: Money
    created_at: str
    updated_at: Optional[str] = None
    account_id: str


def order_to_snapshot(order: CommerceOrder) -> OrderSnapshot:
    """Project a :class:`CommerceOrder` onto its canonical :class:`OrderSnapshot`.

    The snapshot carries the order total in the order's (single) currency and
    drops provider-specific fields; it is the shape emitted as the data
    payload of a commerce order event.
    """
    return OrderSnapshot(
        order_id=order.order_id,
        status=order.status,
        currency=order.currency,
        total=order.totals.total,
        created_at=order.created_at,
        updated_at=order.updated_at,
        account_id=order.account_id,
    )


__all__ = [
    "CommerceOrder",
    "OrderCustomer",
    "OrderLineItem",
    "OrderSnapshot",
    "OrderStatus",
    "OrderTotals",
    "order_to_snapshot",
]
