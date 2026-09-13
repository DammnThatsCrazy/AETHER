"""eBay order normalization (:class:`EventNormalizer`) — deterministic, network-free.

Maps ONE ``RawProviderRecord`` whose ``payload`` is an eBay Fulfillment order
dict (from pull, or a ``EbayOrder`` ``model_dump``) onto a single provider-
neutral ``commerce.order.*`` :class:`AetherEvent <shared.integration_contracts.events.AetherEvent>`.

Status resolution is deterministic and checked in order:

* ``order_payment_status`` REFUNDED / PARTIALLY_REFUNDED -> refunded /
  partially_refunded;
* ``order_fulfillment_status`` FULFILLED -> fulfilled;
* ``order_payment_status`` PAID -> paid;
* ``creation_date == modified_date`` -> created;
* otherwise -> updated.

An explicit payment status that is not in the documented map is an honest drop
(``known_unsupported_behavior``) — never silently skipped. Money is normalized
by :func:`services.providers.ebay.payloads.money_amount` (exact ``Decimal`` —
never binary floats). The full raw payload is preserved in
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

from services.providers.ebay.payloads import EbayOrder, money_amount

NORMALIZER_VERSION = "1"
SUPPORTED_RECORD_TYPE = "order"

# eBay payment status -> canonical lifecycle status. Anything outside this map
# is a visible drop (known_unsupported_behavior), never a silent skip.
STATUS_BY_PAYMENT: dict[str, OrderStatus] = {
    "PAID": OrderStatus.paid,
    "REFUNDED": OrderStatus.refunded,
    "PARTIALLY_REFUNDED": OrderStatus.partially_refunded,
    "PENDING": OrderStatus.updated,
    "NOT_PAID": OrderStatus.created,
    "FAILED": OrderStatus.updated,
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

_PROVIDER_DATA_FIELDS = ("order_id", "order_payment_status", "order_fulfillment_status")


def _money(value: Any, currency: str) -> Money:
    """Exact ``Decimal`` parse of an eBay amount string."""
    return Money(amount=Decimal(money_amount(value)), currency=currency)


def _resolve_status(order: EbayOrder) -> OrderStatus | None:
    """Resolve the canonical status per the documented rule; ``None`` = unmappable."""
    payment = (order.order_payment_status or order.order_payment_status_enum).upper()
    if payment in STATUS_BY_PAYMENT:
        return STATUS_BY_PAYMENT[payment]
    if payment:
        # An explicit payment status with no canonical mapping is a visible drop.
        return None
    if order.order_fulfillment_status == "FULFILLED":
        return OrderStatus.fulfilled
    if order.creation_date and order.creation_date == order.modified_date:
        return OrderStatus.created
    return OrderStatus.updated


def to_commerce_order(order: EbayOrder, *, account_id: str = "default") -> CommerceOrder:
    """Map a parsed :class:`EbayOrder` onto a :class:`CommerceOrder`."""
    currency = order.total.currency or "USD"
    totals = OrderTotals(
        subtotal=_money(order.subtotal, currency),
        shipping=_money(order.shipping, currency),
        tax=_money(order.tax, currency),
        discount=Money(amount=Decimal("0"), currency=currency),
        total=_money(order.total, currency),
    )
    line_items = [
        OrderLineItem(
            line_item_id=item.line_item_id,
            product_id="",
            variant_id=None,
            sku=item.sku,
            title=item.title,
            quantity=item.quantity,
            unit_price=_money(item.line_item_cost, currency),
            line_total=_money(
                Decimal(money_amount(item.line_item_cost)) * Decimal(item.quantity), currency
            ),
        )
        for item in order.line_items
    ]
    customer: OrderCustomer | None = None
    if order.buyer.username:
        customer = OrderCustomer(customer_id=order.buyer.username, email=None, phone=None)
    return CommerceOrder(
        order_id=order.order_id,
        account_id=account_id,
        status=_resolve_status(order) or OrderStatus.updated,
        currency=currency,
        totals=totals,
        line_items=line_items,
        customer=customer,
        created_at=order.creation_date,
        updated_at=order.modified_date,
        note=None,
        properties={},
    )


class EbayOrderNormalizer:
    """EventNormalizer: deterministic, synchronous eBay order -> event."""

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
            order = EbayOrder.from_api_dict(raw.payload)
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
                    f"{order.order_payment_status or order.order_payment_status_enum}"
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
            "order_payment_status": order.order_payment_status or order.order_payment_status_enum,
            "order_fulfillment_status": order.order_fulfillment_status,
            # Full raw payload — guarantees no silent loss of provider fields.
            "raw_provider_payload": raw.payload,
        }

        event = AetherEvent(
            event_id=f"{raw.record_id}:{event_type}",
            event_type=event_type,
            event_family="commerce",
            tenant_id=raw.tenant_id,
            provider="ebay",
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
    "STATUS_BY_PAYMENT",
    "EbayOrderNormalizer",
    "to_commerce_order",
]
