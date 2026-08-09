"""Etsy receipt normalization (:class:`EventNormalizer`) — deterministic, network-free.

Maps ONE ``RawProviderRecord`` whose ``payload`` is an Etsy receipt dict (from
pull, or a ``EtsyReceipt`` ``model_dump``) onto a single provider-neutral
``commerce.order.*`` :class:`AetherEvent <shared.integration_contracts.events.AetherEvent>`.

Status resolution is deterministic:

* a present ``status`` is resolved against the documented map
  (:data:`STATUS_BY_ETSY`); a status NOT in the map is an honest drop
  (``known_unsupported_behavior``) — never silently skipped;
* an absent ``status`` is derived from the ``is_paid`` / ``is_shipped``
  booleans (``paid+shipped`` => fulfilled, ``paid`` => paid, else created).

Money is normalized by :func:`services.providers.etsy.payloads.money_amount`
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

from services.providers.etsy.payloads import EtsyReceipt, money_amount

NORMALIZER_VERSION = "1"
SUPPORTED_RECORD_TYPE = "order"

# Etsy receipt status -> canonical lifecycle status. Anything outside this map
# is a visible drop (known_unsupported_behavior), never a silent skip.
STATUS_BY_ETSY: dict[str, OrderStatus] = {
    "open": OrderStatus.created,
    "paid": OrderStatus.paid,
    "shipped": OrderStatus.fulfilled,
    "canceled": OrderStatus.cancelled,
    "cancelled": OrderStatus.cancelled,
    "refunded": OrderStatus.refunded,
}

_EVENT_TYPE_BY_STATUS: dict[OrderStatus, str] = {
    OrderStatus.cancelled: "commerce.order.cancelled",
    OrderStatus.created: "commerce.order.created",
    OrderStatus.refunded: "commerce.order.refunded",
    OrderStatus.updated: "commerce.order.updated",
    OrderStatus.paid: "commerce.order.paid",
    OrderStatus.fulfilled: "commerce.order.fulfilled",
}

_PROVIDER_DATA_FIELDS = ("receipt_id", "create_ts", "update_ts", "is_paid", "is_shipped")


def _money(value: Any, currency: str) -> Money:
    """Exact ``Decimal`` parse of an Etsy amount string/number."""
    return Money(amount=Decimal(money_amount(value)), currency=currency)


def _resolve_status(receipt: EtsyReceipt) -> OrderStatus | None:
    """Resolve the canonical status per the documented rule; ``None`` = unmappable."""
    if receipt.status:
        return STATUS_BY_ETSY.get(receipt.status)
    if receipt.is_paid and receipt.is_shipped:
        return OrderStatus.fulfilled
    if receipt.is_paid:
        return OrderStatus.paid
    return OrderStatus.created


def to_commerce_order(
    receipt: EtsyReceipt, *, account_id: str = "default"
) -> CommerceOrder:
    """Map a parsed :class:`EtsyReceipt` onto a :class:`CommerceOrder`."""
    currency = receipt.currency_code or "USD"
    totals = OrderTotals(
        subtotal=_money(receipt.subtotal, currency),
        shipping=_money(receipt.shipping_cost, currency),
        tax=_money(receipt.total_tax_cost, currency),
        discount=_money(receipt.discount_amt, currency),
        total=_money(receipt.grandtotal, currency),
    )
    line_items = [
        OrderLineItem(
            line_item_id=str(tx.transaction_id),
            product_id="",
            variant_id=None,
            sku=None,
            title=tx.title,
            quantity=tx.quantity,
            unit_price=_money(tx.price, currency),
            line_total=_money(Decimal(money_amount(tx.price)) * Decimal(tx.quantity), currency),
        )
        for tx in receipt.transactions
    ]
    customer: OrderCustomer | None = None
    if receipt.buyer is not None:
        customer = OrderCustomer(
            customer_id=str(receipt.buyer.user_id),
            email=receipt.buyer.email,
            phone=None,
            first_name=receipt.buyer.first_name,
            last_name=receipt.buyer.last_name,
        )
    created_at = _epoch_to_iso(receipt.create_ts)
    updated_at = _epoch_to_iso(receipt.update_ts)
    return CommerceOrder(
        order_id=str(receipt.receipt_id),
        account_id=account_id,
        status=_resolve_status(receipt) or OrderStatus.created,
        currency=currency,
        totals=totals,
        line_items=line_items,
        customer=customer,
        created_at=created_at,
        updated_at=updated_at,
        note=None,
        properties={},
    )


def _epoch_to_iso(epoch: int) -> str:
    """Unix epoch seconds -> ISO-8601 UTC (deterministic, no wall-clock)."""
    from datetime import datetime, timezone

    if not epoch:
        return ""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


class EtsyOrderNormalizer:
    """EventNormalizer: deterministic, synchronous Etsy receipt -> event."""

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
            receipt = EtsyReceipt.from_api_dict(raw.payload)
        except Exception as exc:  # noqa: BLE001 - unparseable payload is a visible drop
            return NormalizationResult(
                events=[],
                skipped=0,
                dropped=[f"{raw.record_id}:unparseable:{type(exc).__name__}"],
                normalizer_version=self.normalizer_version,
            )

        status = _resolve_status(receipt)
        if status is None:
            return NormalizationResult(
                events=[],
                skipped=0,
                dropped=[f"{raw.record_id}:known_unsupported_behavior:status:{receipt.status}"],
                normalizer_version=self.normalizer_version,
            )

        commerce = to_commerce_order(receipt, account_id=raw.account_id or "default")
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
            "raw_provider_event_type": f"receipt.{receipt.status or status.value}",
            "update_ts": receipt.update_ts,
            # Full raw payload — guarantees no silent loss of provider fields.
            "raw_provider_payload": raw.payload,
        }

        event = AetherEvent(
            event_id=f"{raw.record_id}:{event_type}",
            event_type=event_type,
            event_family="commerce",
            tenant_id=raw.tenant_id,
            provider="etsy",
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
    "STATUS_BY_ETSY",
    "EtsyOrderNormalizer",
    "to_commerce_order",
]
