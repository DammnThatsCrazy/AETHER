"""Shopify order normalization (:class:`EventNormalizer`) — deterministic, network-free.

Maps ONE ``RawProviderRecord`` whose ``payload`` is a Shopify order dict (from
pull or webhook, or a ``ShopifyOrder`` ``model_dump``) onto a single provider-
neutral ``commerce.order.*`` :class:`AetherEvent <shared.integration_contracts.events.AetherEvent>`.

Event-type mapping (status rule, in order):

* ``cancelled_at`` set          -> ``OrderStatus.cancelled``  -> ``commerce.order.cancelled``
* ``created_at == updated_at``  -> ``OrderStatus.created``    -> ``commerce.order.created``
* ``financial_status == refunded`` -> ``OrderStatus.refunded`` -> ``commerce.order.refunded``
* otherwise                     -> ``OrderStatus.updated``    -> ``commerce.order.updated``

Money is parsed via ``decimal.Decimal(str(value))`` — Shopify amounts are
strings and are never handled through binary floats. No loss: the full raw
payload is preserved in ``AetherEvent.context["raw_provider_payload"]`` and
provider-specific fields the order model does not capture are surfaced under
``data["provider"]``. Unknown record types are reported via ``dropped`` — never
silent.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from shared.commerce_contracts.money import Money
from shared.commerce_contracts.order import (
    CommerceOrder,
    OrderCustomer,
    OrderLineItem,
    OrderStatus,
    OrderTotals,
    order_to_snapshot,
)
from shared.integration_contracts.events import AetherEvent, RawProviderRecord
from shared.integration_contracts.normalization import EventNormalizer, NormalizationResult

from services.providers.shopify.payloads import ShopifyOrder

NORMALIZER_VERSION = "1"
SUPPORTED_RECORD_TYPE = "order"

# OrderStatus -> provider-neutral event_type.
_EVENT_TYPE_BY_STATUS: dict[OrderStatus, str] = {
    OrderStatus.cancelled: "commerce.order.cancelled",
    OrderStatus.created: "commerce.order.created",
    OrderStatus.refunded: "commerce.order.refunded",
    OrderStatus.updated: "commerce.order.updated",
}

# Provider fields surfaced under data["provider"] (the order/snapshot models do
# not capture them; nothing is lost because the full payload is in context).
_PROVIDER_DATA_FIELDS = (
    "name",
    "financial_status",
    "fulfillment_status",
    "closed_at",
    "cancelled_at",
    "tags",
)

# Shopify webhook topic derived from the resolved status.
_TOPIC_BY_STATUS: dict[OrderStatus, str] = {
    OrderStatus.cancelled: "orders/cancelled",
    OrderStatus.created: "orders/create",
    OrderStatus.refunded: "orders/cancelled",
    OrderStatus.updated: "orders/update",
}


def _money(value: Any, currency: str) -> Money:
    """Exact ``Decimal`` parse of a Shopify amount string (e.g. ``"12.50"``)."""
    return Money(amount=Decimal(str(value)), currency=currency)


def _order_status(order: ShopifyOrder) -> OrderStatus:
    """Resolve the canonical status per the documented rule (checked in order)."""
    if order.cancelled_at:
        return OrderStatus.cancelled
    if order.created_at == order.updated_at:
        return OrderStatus.created
    if order.financial_status == "refunded":
        return OrderStatus.refunded
    return OrderStatus.updated


def to_commerce_order(order: ShopifyOrder, *, account_id: str = "default") -> CommerceOrder:
    """Map a parsed :class:`ShopifyOrder` onto a :class:`CommerceOrder`.

    All money comes from ``Decimal(str(value))``; line totals are computed from
    decimals (``unit_price * quantity``), never floats.
    """
    currency = order.currency
    totals = OrderTotals(
        subtotal=_money(order.subtotal_price, currency),
        shipping=_money(order.total_shipping, currency),
        tax=_money(order.total_tax, currency),
        discount=_money(order.total_discounts, currency),
        total=_money(order.total_price, currency),
    )
    line_items = [
        OrderLineItem(
            line_item_id=str(item.id),
            product_id=str(item.product_id) if item.product_id is not None else "",
            variant_id=str(item.variant_id) if item.variant_id is not None else None,
            sku=item.sku,
            title=item.title,
            quantity=item.quantity,
            unit_price=_money(item.price, currency),
            line_total=_money(Decimal(str(item.price)) * Decimal(item.quantity), currency),
        )
        for item in order.line_items
    ]
    customer: OrderCustomer | None = None
    if order.customer is not None:
        customer = OrderCustomer(
            customer_id=str(order.customer.id),
            email=order.customer.email,
            phone=order.customer.phone,
            first_name=order.customer.first_name,
            last_name=order.customer.last_name,
        )
    properties: dict[str, Any] = {}
    for index, prop in enumerate(order.properties):
        if isinstance(prop, dict):
            properties[str(index)] = prop
    return CommerceOrder(
        order_id=str(order.id),
        account_id=account_id,
        status=_order_status(order),
        currency=currency,
        totals=totals,
        line_items=line_items,
        customer=customer,
        created_at=order.created_at,
        updated_at=order.updated_at,
        note=order.note,
        properties=properties,
    )


class ShopifyOrderNormalizer:
    """EventNormalizer: deterministic, synchronous Shopify order -> event."""

    normalizer_version = NORMALIZER_VERSION

    def normalize(self, raw: RawProviderRecord) -> NormalizationResult:
        if raw.provider_record_type != SUPPORTED_RECORD_TYPE:
            return NormalizationResult(
                events=[],
                skipped=0,
                dropped=[f"{raw.record_id}:{raw.provider_record_type}"],
                normalizer_version=self.normalizer_version,
            )
        # Any parse OR money-conversion failure (e.g. a pathological empty
        # amount string) must surface as a visible drop — the normalizer never
        # raises and never silently zeroes a bad amount.
        try:
            order = ShopifyOrder.from_api_dict(raw.payload)
            commerce = to_commerce_order(order, account_id=raw.account_id or "default")
        except Exception as exc:  # noqa: BLE001 - unparseable payload is a visible drop
            return NormalizationResult(
                events=[],
                skipped=0,
                dropped=[f"{raw.record_id}:unparseable:{type(exc).__name__}"],
                normalizer_version=self.normalizer_version,
            )

        status = commerce.status
        event_type = _EVENT_TYPE_BY_STATUS[status]
        account_id = raw.account_id or "default"

        data: dict[str, Any] = order_to_snapshot(commerce).model_dump()
        data["provider"] = {
            key: raw.payload.get(key)
            for key in _PROVIDER_DATA_FIELDS
            if key in raw.payload and raw.payload.get(key) is not None
        }

        context: dict[str, Any] = {
            "acquisition_mode": raw.acquisition_mode,
            "connection_id": raw.connection_id,
            "raw_provider_event_type": _TOPIC_BY_STATUS[status],
            "financial_status": order.financial_status,
            "fulfillment_status": raw.payload.get("fulfillment_status"),
            # Full raw payload — guarantees no silent loss of provider fields.
            "raw_provider_payload": raw.payload,
        }

        event = AetherEvent(
            event_id=f"{raw.record_id}:{event_type}",
            event_type=event_type,
            event_family="commerce",
            tenant_id=raw.tenant_id,
            provider="shopify",
            provider_identity=raw.provider_identity,
            source_record_id=raw.record_id,
            occurred_at=raw.provider_occurred_at or raw.observed_at,
            observed_at=raw.observed_at,
            account_id=account_id,
            data=data,
            context=context,
            schema_version="1",
        )
        return NormalizationResult(
            events=[event],
            skipped=0,
            dropped=[],
            normalizer_version=self.normalizer_version,
        )


__all__ = [
    "NORMALIZER_VERSION",
    "ShopifyOrderNormalizer",
    "to_commerce_order",
]
