"""Typed pydantic models for the raw eBay Fulfillment orders payloads.

Deliberately STRICT (``extra="forbid"``): accidental drift from the canonical
eBay shape fails loudly instead of silently corrupting a parse. Every parser
routes raw payloads through :meth:`EbayOrder.from_api_dict` — the tolerance seam
that selects the known fields and ignores unknown keys.

eBay money travels as ``{"value": "110.95", "currency": "USD"}`` where ``value``
is a decimal string — normalized to an exact string via :func:`money_amount` so
downstream ``Decimal`` conversion is exact (never floats).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _as_str(value: Any, default: str = "") -> str:
    """Coerce a scalar to ``str``; ``None`` becomes ``default``."""
    if value is None:
        return default
    return str(value)


def money_amount(value: Any) -> str:
    """Normalize an eBay amount (dict, ``EbayMoney``, or scalar) to a decimal string."""
    if isinstance(value, dict):
        return _as_str(value.get("value"), "0.0")
    if value is None:
        return "0.0"
    if hasattr(value, "value"):
        return _as_str(value.value, "0.0")
    return str(value)


class EbayMoney(BaseModel):
    """An eBay amount (``value`` is a decimal string)."""

    model_config = ConfigDict(extra="forbid")

    value: str = "0.0"
    currency: str = "USD"


class EbayLineItem(BaseModel):
    """A single eBay fulfillment order line item."""

    model_config = ConfigDict(extra="forbid")

    line_item_id: str = ""
    sku: str = ""
    title: str = ""
    quantity: int = Field(default=0, ge=0)
    line_item_cost: EbayMoney = Field(default_factory=lambda: EbayMoney())


class EbayBuyer(BaseModel):
    """Minimal eBay buyer projection (order payload)."""

    model_config = ConfigDict(extra="forbid")

    username: str = ""
    buyer_registration_address: dict[str, Any] = Field(default_factory=dict)


class EbayOrder(BaseModel):
    """A realistic eBay Fulfillment order projection.

    ``extra="forbid"`` means the real API has MORE fields — use
    :meth:`from_api_dict` (the tolerance seam) to parse raw payloads.
    """

    model_config = ConfigDict(extra="forbid")

    order_id: str = ""
    order_payment_status: str = ""  # FAILED|NOT_APPLICABLE|NOT_PAID|PAID|PENDING|REFUNDED|PARTIALLY_REFUNDED
    order_payment_status_enum: str = ""
    order_fulfillment_status: str = ""  # NOT_STARTED|IN_PROCESS|FULFILLED
    creation_date: str = ""  # ISO-8601
    modified_date: str = ""  # ISO-8601 — the incremental cursor field
    total: EbayMoney = Field(default_factory=lambda: EbayMoney())
    subtotal: EbayMoney = Field(default_factory=lambda: EbayMoney())
    shipping: EbayMoney = Field(default_factory=lambda: EbayMoney())
    tax: EbayMoney = Field(default_factory=lambda: EbayMoney())
    buyer: EbayBuyer = Field(default_factory=EbayBuyer)
    line_items: list[EbayLineItem] = Field(default_factory=list)

    @classmethod
    def from_api_dict(cls, raw: dict) -> "EbayOrder":
        """Tolerant parser: selects known fields, ignores unknown keys, never raises."""

        def _line_items(items: Any) -> list[EbayLineItem]:
            out: list[EbayLineItem] = []
            for item in items or []:
                if not isinstance(item, dict):
                    continue
                cost = item.get("lineItemCost") if isinstance(item.get("lineItemCost"), dict) else {}
                out.append(
                    EbayLineItem(
                        line_item_id=_as_str(item.get("lineItemId")),
                        sku=_as_str(item.get("sku")),
                        title=_as_str(item.get("title")),
                        quantity=int(item.get("quantity") or 0)
                        if str(item.get("quantity") or "").isdigit()
                        else 0,
                        line_item_cost=EbayMoney(
                            value=_as_str(cost.get("value"), "0.0"),
                            currency=_as_str(cost.get("currency"), "USD"),
                        ),
                    )
                )
            return out

        def _money(value: Any, key: str) -> EbayMoney:
            obj = value.get(key) if isinstance(value, dict) else {}
            if not isinstance(obj, dict):
                obj = {}
            return EbayMoney(
                value=_as_str(obj.get("value"), "0.0"),
                currency=_as_str(obj.get("currency"), "USD"),
            )

        def _buyer(value: Any) -> EbayBuyer:
            if not isinstance(value, dict):
                return EbayBuyer()
            return EbayBuyer(
                username=_as_str(value.get("username")),
                buyer_registration_address=value.get("buyerRegistrationAddress") or {},
            )

        return cls(
            order_id=_as_str(raw.get("orderId")),
            order_payment_status=_as_str(raw.get("orderPaymentStatus")),
            order_payment_status_enum=_as_str(raw.get("orderPaymentStatusEnum")),
            order_fulfillment_status=_as_str(raw.get("orderFulfillmentStatus")),
            creation_date=_as_str(raw.get("creationDate")),
            modified_date=_as_str(raw.get("modifiedDate")),
            total=_money(raw, "total"),
            subtotal=_money(raw, "subtotal"),
            shipping=_money(raw, "totalShippingCost") if "totalShippingCost" in raw else EbayMoney(),
            tax=_money(raw, "totalTax") if "totalTax" in raw else EbayMoney(),
            buyer=_buyer(raw.get("buyer")),
            line_items=_line_items(raw.get("lineItems")),
        )


__all__ = ["EbayBuyer", "EbayLineItem", "EbayMoney", "EbayOrder", "money_amount"]
