"""TikTok Shop order normalization (:class:`EventNormalizer`) — deterministic, network-free.

Maps ONE ``RawProviderRecord`` whose ``payload`` is a TikTok Shop order dict
(from pull or webhook, or a ``TikTokOrder`` ``model_dump``) onto a single
provider-neutral ``commerce.order.*`` :class:`AetherEvent <shared.integration_contracts.events.AetherEvent>`.

Status resolution: the TikTok ``order_status`` is resolved against the documented
map (:data:`STATUS_BY_TIKTOK`). A status NOT in the map is an honest drop
(``known_unsupported_behavior``) — never silently skipped — which satisfies the
honesty invariant for the claimed ``tiktok_hmac`` webhook (the normalizer carries
a full status map). An absent status derives deterministically to ``created``.

Money is normalized by :func:`services.providers.tiktok.payloads.money_amount`
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

from services.providers.tiktok.payloads import TikTokOrder, money_amount

NORMALIZER_VERSION = "1"
SUPPORTED_RECORD_TYPE = "order"

# TikTok Shop order status -> canonical lifecycle status. Covers the full
# documented status vocabulary; anything outside this map is a visible drop.
STATUS_BY_TIKTOK: dict[str, OrderStatus] = {
    "UNPAID": OrderStatus.created,
    "AWAITING_SHIPMENT": OrderStatus.paid,
    "AWAITING_COLLECTION": OrderStatus.paid,
    "IN_TRANSIT": OrderStatus.fulfilled,
    "DELIVERED": OrderStatus.fulfilled,
    "COMPLETED": OrderStatus.fulfilled,
    "CANCELLED": OrderStatus.cancelled,
    "CANCEL_REQUESTED": OrderStatus.cancelled,
    "REFUNDED": OrderStatus.refunded,
    "PARTIALLY_REFUNDED": OrderStatus.partially_refunded,
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

_PROVIDER_DATA_FIELDS = ("order_id", "order_status", "create_time", "update_time", "buyer_uid")


def _money(value: Any, currency: str) -> Money:
    """Exact ``Decimal`` parse of a TikTok amount (number or string)."""
    return Money(amount=Decimal(money_amount(value)), currency=currency)


def _resolve_status(order: TikTokOrder) -> OrderStatus | None:
    """Resolve the canonical status per the documented rule; ``None`` = unmappable."""
    status = order.order_status.strip().upper()
    if status:
        return STATUS_BY_TIKTOK.get(status)
    return OrderStatus.created


def to_commerce_order(order: TikTokOrder, *, account_id: str = "default") -> CommerceOrder:
    """Map a parsed :class:`TikTokOrder` onto a :class:`CommerceOrder`."""
    currency = order.currency or "USD"
    totals = OrderTotals(
        subtotal=_money(order.payment.sub_total, currency),
        shipping=_money(order.payment.shipping_fee, currency),
        tax=_money(order.payment.tax_amount, currency),
        discount=Money(amount=Decimal("0"), currency=currency),
        total=_money(order.payment.total_amount, currency),
    )
    line_items = [
        OrderLineItem(
            line_item_id=item.id,
            product_id="",
            variant_id=None,
            sku=item.seller_sku,
            title=item.product_name,
            quantity=item.quantity,
            unit_price=_money(item.sale_price, currency),
            line_total=_money(
                Decimal(money_amount(item.sale_price)) * Decimal(item.quantity), currency
            ),
        )
        for item in order.order_line_list
    ]
    customer: OrderCustomer | None = None
    if order.buyer_uid:
        customer = OrderCustomer(customer_id=order.buyer_uid, email=None, phone=None)
    return CommerceOrder(
        order_id=order.order_id,
        account_id=account_id,
        status=_resolve_status(order) or OrderStatus.created,
        currency=currency,
        totals=totals,
        line_items=line_items,
        customer=customer,
        created_at=_epoch_to_iso(order.create_time),
        updated_at=_epoch_to_iso(order.update_time),
        note=None,
        properties={},
    )


def _epoch_to_iso(epoch: int) -> str:
    """Unix epoch seconds -> ISO-8601 UTC (deterministic, no wall-clock)."""
    from datetime import datetime, timezone

    if not epoch:
        return ""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


class TikTokOrderNormalizer:
    """EventNormalizer: deterministic, synchronous TikTok order -> event."""

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
            order = TikTokOrder.from_api_dict(raw.payload)
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
            "update_time": order.update_time,
            # Full raw payload — guarantees no silent loss of provider fields.
            "raw_provider_payload": raw.payload,
        }

        event = AetherEvent(
            event_id=f"{raw.record_id}:{event_type}",
            event_type=event_type,
            event_family="commerce",
            tenant_id=raw.tenant_id,
            provider="tiktok",
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
    "STATUS_BY_TIKTOK",
    "TikTokOrderNormalizer",
    "to_commerce_order",
]
