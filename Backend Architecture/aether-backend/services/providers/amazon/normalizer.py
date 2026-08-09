"""Amazon order normalization (:class:`EventNormalizer`) — deterministic, network-free.

Maps ONE ``RawProviderRecord`` whose ``payload`` is an Amazon SP-API order
dict (from pull, or a ``AmazonOrder`` ``model_dump``) onto a single provider-
neutral ``commerce.order.*`` :class:`AetherEvent <shared.integration_contracts.events.AetherEvent>`.

Status resolution is deterministic and checked in order:

* ``OrderStatus`` SHIPPED -> fulfilled;
* ``OrderStatus`` CANCELED -> cancelled;
* ``OrderStatus`` PENDING / PendingAvailability -> created;
* ``OrderStatus`` UNSHIPPED / INVOICEUNCONFIRMED -> updated (accepted but not
  yet shipped);
* ``OrderStatus`` PARTIALLYSHIPPED -> updated;
* ``OrderStatus`` UNFULFILLABLE -> an honest drop
  (``known_unsupported_behavior``) — never silently skipped.

An explicit order status that is not in the documented map is an honest drop
(``known_unsupported_behavior``) — never silently skipped. Money is normalized
by :func:`services.providers.amazon.payloads.money_amount` (exact ``Decimal``
— never binary floats). The full raw payload is preserved in
``AetherEvent.context["raw_provider_payload"]``.
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

from services.providers.amazon.payloads import AmazonOrder, money_amount

NORMALIZER_VERSION = "1"
SUPPORTED_RECORD_TYPE = "order"

# Amazon SP-API order status -> canonical lifecycle status. Anything outside
# this map is a visible drop (known_unsupported_behavior), never a silent skip.
STATUS_BY_ORDER_STATUS: dict[str, OrderStatus] = {
    "PENDING": OrderStatus.created,
    "PENDINGAVAILABILITY": OrderStatus.created,
    "UNSHIPPED": OrderStatus.updated,
    "INVOICEUNCONFIRMED": OrderStatus.updated,
    "PARTIALLYSHIPPED": OrderStatus.updated,
    "SHIPPED": OrderStatus.fulfilled,
    "CANCELED": OrderStatus.cancelled,
    # UNFULFILLABLE is intentionally absent — an honest drop, not a mis-map.
}

_EVENT_TYPE_BY_STATUS: dict[OrderStatus, str] = {
    OrderStatus.cancelled: "commerce.order.cancelled",
    OrderStatus.created: "commerce.order.created",
    OrderStatus.refunded: "commerce.order.refunded",
    OrderStatus.updated: "commerce.order.updated",
    OrderStatus.paid: "commerce.order.paid",
    OrderStatus.fulfilled: "commerce.order.fulfilled",
    OrderStatus.partially_refunded: "commerce.order.partially_refunded",
}

# Raw SP-API payload keys projected onto ``data["provider"]`` (camelCase —
# the keys as Amazon actually sends them).
_PROVIDER_DATA_FIELDS = ("AmazonOrderId", "OrderStatus", "MarketplaceId", "SellerOrderId")


def _money(value: Any, currency: str) -> Money:
    """Exact ``Decimal`` parse of an Amazon amount string."""
    return Money(amount=Decimal(money_amount(value)), currency=currency)


def _resolve_status(order: AmazonOrder) -> OrderStatus | None:
    """Resolve the canonical status per the documented rule; ``None`` = unmappable."""
    status = (order.order_status or "").strip().upper().replace(" ", "")
    if not status:
        return OrderStatus.created
    return STATUS_BY_ORDER_STATUS.get(status)


def to_commerce_order(order: AmazonOrder, *, account_id: str = "default") -> CommerceOrder:
    """Map a parsed :class:`AmazonOrder` onto a :class:`CommerceOrder`."""
    currency = order.order_total.currency or "USD"
    totals = OrderTotals(
        subtotal=_money(order.order_total, currency),
        shipping=Money(amount=Decimal("0"), currency=currency),
        tax=Money(amount=Decimal("0"), currency=currency),
        discount=Money(amount=Decimal("0"), currency=currency),
        total=_money(order.order_total, currency),
    )
    line_items = [
        OrderLineItem(
            line_item_id=item.order_item_id,
            product_id=item.asin,
            variant_id=None,
            sku=item.seller_sku,
            title=item.title,
            quantity=item.quantity_ordered,
            unit_price=_money(item.item_price, currency),
            line_total=_money(
                Decimal(money_amount(item.item_price)) * Decimal(item.quantity_ordered), currency
            ),
        )
        for item in order.line_items
    ]
    customer: OrderCustomer | None = None
    if order.buyer.buyer_email or order.buyer.buyer_name:
        customer = OrderCustomer(
            customer_id=order.buyer.buyer_email or order.buyer.buyer_name,
            email=order.buyer.buyer_email or None,
            phone=None,
        )
    return CommerceOrder(
        order_id=order.amazon_order_id,
        account_id=account_id,
        status=_resolve_status(order) or OrderStatus.updated,
        currency=currency,
        totals=totals,
        line_items=line_items,
        customer=customer,
        created_at=order.purchase_date,
        updated_at=order.last_update_date,
        note=None,
        properties={
            "marketplace_id": order.marketplace_id,
            "seller_order_id": order.seller_order_id,
            "fulfillment_channel": order.fulfillment_channel,
            "payment_method": order.payment_method,
        },
    )


class AmazonOrderNormalizer:
    """EventNormalizer: deterministic, synchronous Amazon order -> event."""

    normalizer_version = NORMALIZER_VERSION

    def normalize(self, raw: RawProviderRecord) -> NormalizationResult:
        if raw.provider_record_type != SUPPORTED_RECORD_TYPE:
            return NormalizationResult(
                events=[],
                skipped=0,
                dropped=[f"{raw.record_id}:{raw.provider_record_type}"],
                normalizer_version=self.normalizer_version,
            )
        try:
            order = AmazonOrder.from_api_dict(raw.payload)
        except Exception as exc:  # noqa: BLE001 - unparseable payload is a visible drop
            return NormalizationResult(
                events=[],
                skipped=0,
                dropped=[f"{raw.record_id}:unparseable:{type(exc).__name__}"],
                normalizer_version=self.normalizer_version,
            )

        status = _resolve_status(order)
        if status is None:
            return NormalizationResult(
                events=[],
                skipped=0,
                dropped=[
                    f"{raw.record_id}:known_unsupported_behavior:status:"
                    f"{order.order_status}"
                ],
                normalizer_version=self.normalizer_version,
            )

        commerce = to_commerce_order(order, account_id=raw.account_id or "default")
        event_type = _EVENT_TYPE_BY_STATUS[status]
        account_id = raw.account_id or "default"

        data: dict[str, Any] = order_to_snapshot(commerce).model_dump()
        data["provider"] = {
            key: raw.payload.get(key)
            for key in _PROVIDER_DATA_FIELDS
            if raw.payload.get(key) is not None
        }

        context: dict[str, Any] = {
            "acquisition_mode": raw.acquisition_mode,
            "connection_id": raw.connection_id,
            "raw_provider_event_type": f"order.{status.value}",
            "order_status": order.order_status,
            "marketplace_id": order.marketplace_id,
            # Full raw payload — guarantees no silent loss of provider fields.
            "raw_provider_payload": raw.payload,
        }

        event = AetherEvent(
            event_id=f"{raw.record_id}:{event_type}",
            event_type=event_type,
            event_family="commerce",
            tenant_id=raw.tenant_id,
            provider="amazon",
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
    "STATUS_BY_ORDER_STATUS",
    "AmazonOrderNormalizer",
    "to_commerce_order",
]
