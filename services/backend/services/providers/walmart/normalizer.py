"""Walmart order normalization (:class:`EventNormalizer`) — deterministic, network-free.

Maps ONE ``RawProviderRecord`` whose ``payload`` is a Walmart Marketplace order
dict (from pull, or a ``WalmartOrder`` ``model_dump``) onto a single provider-
neutral ``commerce.order.*`` :class:`AetherEvent <shared.integration_contracts.events.AetherEvent>`.

Status resolution: the Walmart ``orderStatus`` (compared case-insensitively) is
resolved against the documented map (:data:`STATUS_BY_WALMART`). A status NOT in
the map is an honest drop (``known_unsupported_behavior``) — never silently
skipped; an absent status derives deterministically to ``created``.

Money is normalized by :func:`services.providers.walmart.payloads.money_amount`
(exact ``Decimal`` — never binary floats). The full raw payload is preserved in
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

from services.providers.walmart.payloads import WalmartOrder, money_amount

NORMALIZER_VERSION = "1"
SUPPORTED_RECORD_TYPE = "order"

# Walmart order status (case-insensitive) -> canonical lifecycle status.
STATUS_BY_WALMART: dict[str, OrderStatus] = {
    "CREATED": OrderStatus.created,
    "ACKNOWLEDGED": OrderStatus.updated,
    "PROCESSING": OrderStatus.updated,
    "SHIPPED": OrderStatus.fulfilled,
    "DELIVERED": OrderStatus.fulfilled,
    "CANCELLED": OrderStatus.cancelled,
    "REFUNDED": OrderStatus.refunded,
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

_PROVIDER_DATA_FIELDS = ("order_id", "order_status", "order_type", "customer_email_id")


def _money(value: Any, currency: str) -> Money:
    """Exact ``Decimal`` parse of a Walmart amount (number or string)."""
    return Money(amount=Decimal(money_amount(value)), currency=currency)


def _resolve_status(order: WalmartOrder) -> OrderStatus | None:
    """Resolve the canonical status per the documented rule; ``None`` = unmappable."""
    status = order.order_status.strip().upper()
    if status:
        return STATUS_BY_WALMART.get(status)
    return OrderStatus.created


def to_commerce_order(order: WalmartOrder, *, account_id: str = "default") -> CommerceOrder:
    """Map a parsed :class:`WalmartOrder` onto a :class:`CommerceOrder`."""
    currency = order.order_summary.total_amount.currency or "USD"
    totals = OrderTotals(
        subtotal=_money(order.order_summary.subtotal, currency),
        shipping=_money(order.order_summary.shipping_handling, currency),
        tax=_money(order.order_summary.tax_total, currency),
        discount=Money(amount=Decimal("0"), currency=currency),
        total=_money(order.order_summary.total_amount, currency),
    )
    line_items = [
        OrderLineItem(
            line_item_id=item.line_number,
            product_id="",
            variant_id=None,
            sku=item.sku,
            title=item.product_name,
            quantity=item.quantity,
            unit_price=_money(item.unit_price, currency),
            line_total=_money(
                Decimal(money_amount(item.unit_price)) * Decimal(item.quantity), currency
            ),
        )
        for item in order.order_lines
    ]
    customer: OrderCustomer | None = None
    if order.customer_email_id:
        customer = OrderCustomer(
            customer_id="", email=order.customer_email_id, phone=None
        )
    return CommerceOrder(
        order_id=order.order_id,
        account_id=account_id,
        status=_resolve_status(order) or OrderStatus.created,
        currency=currency,
        totals=totals,
        line_items=line_items,
        customer=customer,
        created_at=order.order_date,
        updated_at=order.order_date,
        note=None,
        properties={},
    )


class WalmartOrderNormalizer:
    """EventNormalizer: deterministic, synchronous Walmart order -> event."""

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
            order = WalmartOrder.from_api_dict(raw.payload)
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
                dropped=[f"{raw.record_id}:known_unsupported_behavior:status:{order.order_status}"],
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
            # Full raw payload — guarantees no silent loss of provider fields.
            "raw_provider_payload": raw.payload,
        }

        event = AetherEvent(
            event_id=f"{raw.record_id}:{event_type}",
            event_type=event_type,
            event_family="commerce",
            tenant_id=raw.tenant_id,
            provider="walmart",
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
    "STATUS_BY_WALMART",
    "WalmartOrderNormalizer",
    "to_commerce_order",
]
