"""Typed pydantic models for the raw Amazon SP-API Orders payloads.

Deliberately STRICT (``extra="forbid"``): accidental drift from the canonical
Amazon Orders shape fails loudly instead of silently corrupting a parse. Every
parser routes raw payloads through :meth:`AmazonOrder.from_api_dict` — the
tolerance seam that selects the known fields and ignores unknown keys.

Amazon money travels as ``{"CurrencyCode": "USD", "Amount": "50.00"}`` where
``Amount`` is a decimal string — normalized to an exact string via
:func:`money_amount` so downstream ``Decimal`` conversion is exact (never
floats).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _as_str(value: Any, default: str = "") -> str:
    """Coerce a scalar to ``str``; ``None`` becomes ``default``."""
    if value is None:
        return default
    return str(value)


def _as_int(value: Any, default: int = 0) -> int:
    """Coerce a scalar to ``int``; non-numeric becomes ``default`` (never raises)."""
    raw = str(value or "").strip()
    return int(raw) if raw.isdigit() else default


def money_amount(value: Any) -> str:
    """Normalize an Amazon amount (dict, ``AmazonMoney``, or scalar) to a decimal string."""
    if isinstance(value, dict):
        return _as_str(value.get("Amount"), "0.0")
    if value is None:
        return "0.0"
    if hasattr(value, "amount"):
        return _as_str(value.amount, "0.0")
    return str(value)


class AmazonMoney(BaseModel):
    """An Amazon SP-API amount (``Amount`` is a decimal string)."""

    model_config = ConfigDict(extra="forbid")

    amount: str = "0.0"
    currency: str = "USD"


class AmazonLineItem(BaseModel):
    """A single Amazon SP-API order item."""

    model_config = ConfigDict(extra="forbid")

    order_item_id: str = ""
    asin: str = ""
    seller_sku: str = ""
    title: str = ""
    quantity_ordered: int = Field(default=0, ge=0)
    quantity_shipped: int = Field(default=0, ge=0)
    item_price: AmazonMoney = Field(default_factory=lambda: AmazonMoney())


class AmazonBuyer(BaseModel):
    """Minimal Amazon buyer projection (order payload)."""

    model_config = ConfigDict(extra="forbid")

    buyer_email: str = ""
    buyer_name: str = ""
    purchase_order_number: str = ""


class AmazonOrder(BaseModel):
    """A realistic Amazon SP-API order projection.

    ``extra="forbid"`` means the real API has MORE fields — use
    :meth:`from_api_dict` (the tolerance seam) to parse raw payloads.
    """

    model_config = ConfigDict(extra="forbid")

    amazon_order_id: str = ""
    order_status: str = ""  # Pending|Unshipped|PartiallyShipped|Shipped|Canceled|Unfulfillable|InvoiceUnconfirmed|PendingAvailability
    purchase_date: str = ""  # ISO-8601 — the incremental cursor field (CreatedAfter)
    last_update_date: str = ""  # ISO-8601
    order_total: AmazonMoney = Field(default_factory=lambda: AmazonMoney())
    number_of_items_shipped: int = 0
    number_of_items_unshipped: int = 0
    seller_order_id: str = ""
    fulfillment_channel: str = ""  # MFN|AFN
    payment_method: str = ""
    marketplace_id: str = ""
    buyer: AmazonBuyer = Field(default_factory=AmazonBuyer)
    line_items: list[AmazonLineItem] = Field(default_factory=list)

    @classmethod
    def from_api_dict(cls, raw: dict) -> "AmazonOrder":
        """Tolerant parser: selects known fields, ignores unknown keys, never raises."""

        def _line_items(items: Any) -> list[AmazonLineItem]:
            out: list[AmazonLineItem] = []
            for item in items or []:
                if not isinstance(item, dict):
                    continue
                price = item.get("ItemPrice") if isinstance(item.get("ItemPrice"), dict) else {}
                out.append(
                    AmazonLineItem(
                        order_item_id=_as_str(item.get("OrderItemId")),
                        asin=_as_str(item.get("ASIN")),
                        seller_sku=_as_str(item.get("SellerSKU")),
                        title=_as_str(item.get("Title")),
                        quantity_ordered=_as_int(item.get("QuantityOrdered")),
                        quantity_shipped=_as_int(item.get("QuantityShipped")),
                        item_price=AmazonMoney(
                            amount=_as_str(price.get("Amount"), "0.0"),
                            currency=_as_str(price.get("CurrencyCode"), "USD"),
                        ),
                    )
                )
            return out

        def _money(value: Any) -> AmazonMoney:
            obj = value if isinstance(value, dict) else {}
            return AmazonMoney(
                amount=_as_str(obj.get("Amount"), "0.0"),
                currency=_as_str(obj.get("CurrencyCode"), "USD"),
            )

        def _buyer(value: Any) -> AmazonBuyer:
            if not isinstance(value, dict):
                return AmazonBuyer()
            return AmazonBuyer(
                buyer_email=_as_str(value.get("BuyerEmail")),
                buyer_name=_as_str(value.get("BuyerName")),
                purchase_order_number=_as_str(value.get("PurchaseOrderNumber")),
            )

        return cls(
            amazon_order_id=_as_str(raw.get("AmazonOrderId")),
            order_status=_as_str(raw.get("OrderStatus")),
            purchase_date=_as_str(raw.get("PurchaseDate")),
            last_update_date=_as_str(raw.get("LastUpdateDate")),
            order_total=_money(raw.get("OrderTotal")),
            number_of_items_shipped=_as_int(raw.get("NumberOfItemsShipped")),
            number_of_items_unshipped=_as_int(raw.get("NumberOfItemsUnshipped")),
            seller_order_id=_as_str(raw.get("SellerOrderId")),
            fulfillment_channel=_as_str(raw.get("FulfillmentChannel")),
            payment_method=_as_str(raw.get("PaymentMethod")),
            marketplace_id=_as_str(raw.get("MarketplaceId")),
            buyer=_buyer(raw.get("BuyerInfo")),
            line_items=_line_items(raw.get("OrderItems")),
        )


__all__ = ["AmazonBuyer", "AmazonLineItem", "AmazonMoney", "AmazonOrder", "money_amount"]
