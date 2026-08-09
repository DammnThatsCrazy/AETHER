"""WooCommerce order normalization (:class:`EventNormalizer`) — deterministic, network-free.

Maps ONE ``RawProviderRecord`` whose ``payload`` is a WooCommerce order dict
(from pull or webhook, or a ``WooCommerceOrder`` ``model_dump``) onto a single
provider-neutral ``commerce.order.*`` :class:`AetherEvent <shared.integration_contracts.events.AetherEvent>`.

Event-type mapping resolves the WooCommerce ``status`` against the documented
status map (:data:`STATUS_BY_WC`). A status NOT in the map is an honest drop —
the record is surfaced via ``dropped`` with a ``known_unsupported_behavior``
reason, never silently skipped. When ``status`` is absent, the order is derived
deterministically from its timestamps (``date_created == date_modified`` =>
``created``).

Money is parsed via ``decimal.Decimal(str(value))`` — WooCommerce amounts are
strings and are never handled through binary floats. No loss: the full raw
payload is preserved in ``AetherEvent.context["raw_provider_payload"]``.
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

from services.providers.woocommerce.payloads import WooCommerceOrder

NORMALIZER_VERSION = "1"
SUPPORTED_RECORD_TYPE = "order"

# WooCommerce status -> canonical, provider-neutral lifecycle status. Covers the
# full documented status vocabulary; anything outside this map is a visible drop.
STATUS_BY_WC: dict[str, OrderStatus] = {
    "pending": OrderStatus.created,
    "processing": OrderStatus.paid,
    "on-hold": OrderStatus.updated,
    "completed": OrderStatus.fulfilled,
    "cancelled": OrderStatus.cancelled,
    "refunded": OrderStatus.refunded,
    "failed": OrderStatus.updated,
    "trash": OrderStatus.cancelled,
}

# OrderStatus -> provider-neutral event_type.
_EVENT_TYPE_BY_STATUS: dict[OrderStatus, str] = {
    OrderStatus.cancelled: "commerce.order.cancelled",
    OrderStatus.created: "commerce.order.created",
    OrderStatus.refunded: "commerce.order.refunded",
    OrderStatus.updated: "commerce.order.updated",
    OrderStatus.paid: "commerce.order.paid",
    OrderStatus.fulfilled: "commerce.order.fulfilled",
    OrderStatus.partially_refunded: "commerce.order.partially_refunded",
}

# Provider fields surfaced under data["provider"] (the snapshot models do not
# capture them; nothing is lost because the full payload is in context).
_PROVIDER_DATA_FIELDS = ("number", "status", "date_paid", "customer_note")


def _money(value: Any, currency: str) -> Money:
    """Exact ``Decimal`` parse of a WooCommerce amount string (e.g. ``"102.98"``)."""
    return Money(amount=Decimal(str(value)), currency=currency)


def _resolve_status(order: WooCommerceOrder) -> OrderStatus | None:
    """Resolve the canonical status per the documented rule; ``None`` = unmappable.

    A present-but-unmapped ``status`` returns ``None`` so the caller surfaces a
    ``known_unsupported_behavior`` drop (never a silent skip). An absent status
    derives deterministically from the order timestamps.
    """
    if order.status:
        return STATUS_BY_WC.get(order.status)
    if order.date_created and order.date_created == order.date_modified:
        return OrderStatus.created
    return OrderStatus.updated


def to_commerce_order(order: WooCommerceOrder, *, account_id: str = "default") -> CommerceOrder:
    """Map a parsed :class:`WooCommerceOrder` onto a :class:`CommerceOrder`.

    All money comes from ``Decimal(str(value))``; line totals are read directly
    from the provider line ``total`` (never recomputed through floats).
    """
    currency = order.currency or "USD"
    totals = OrderTotals(
        subtotal=_money(order.subtotal, currency),
        shipping=_money(order.shipping_total, currency),
        tax=_money(order.total_tax, currency),
        discount=_money(order.discount_total, currency),
        total=_money(order.total, currency),
    )
    line_items = [
        OrderLineItem(
            line_item_id=str(item.id),
            product_id=str(item.product_id),
            variant_id=str(item.variation_id) if item.variation_id is not None else None,
            sku=item.sku,
            title=item.name,
            quantity=item.quantity,
            unit_price=_money(item.price, currency),
            line_total=_money(item.total, currency),
        )
        for item in order.line_items
    ]
    customer: OrderCustomer | None = None
    if order.billing is not None:
        customer = OrderCustomer(
            customer_id=str(order.billing.id),
            email=order.billing.email,
            phone=order.billing.phone,
            first_name=order.billing.first_name,
            last_name=order.billing.last_name,
        )
    return CommerceOrder(
        order_id=str(order.id),
        account_id=account_id,
        status=_resolve_status(order) or OrderStatus.updated,
        currency=currency,
        totals=totals,
        line_items=line_items,
        customer=customer,
        created_at=order.date_created,
        updated_at=order.date_modified,
        note=order.customer_note,
        properties={},
    )


class WooCommerceOrderNormalizer:
    """EventNormalizer: deterministic, synchronous WooCommerce order -> event."""

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
            order = WooCommerceOrder.from_api_dict(raw.payload)
        except Exception as exc:  # noqa: BLE001 - unparseable payload is a visible drop
            return NormalizationResult(
                events=[],
                skipped=0,
                dropped=[f"{raw.record_id}:unparseable:{type(exc).__name__}"],
                normalizer_version=self.normalizer_version,
            )

        status = _resolve_status(order)
        if status is None:
            # Honest drop: the provider status has no canonical mapping — never
            # silently skip a state we cannot translate.
            return NormalizationResult(
                events=[],
                skipped=0,
                dropped=[f"{raw.record_id}:known_unsupported_behavior:status:{order.status}"],
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
            "raw_provider_event_type": f"order.{order.status or status.value}",
            "status": order.status,
            # Full raw payload — guarantees no silent loss of provider fields.
            "raw_provider_payload": raw.payload,
        }

        event = AetherEvent(
            event_id=f"{raw.record_id}:{event_type}",
            event_type=event_type,
            event_family="commerce",
            tenant_id=raw.tenant_id,
            provider="woocommerce",
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
    "STATUS_BY_WC",
    "WooCommerceOrderNormalizer",
    "to_commerce_order",
]
