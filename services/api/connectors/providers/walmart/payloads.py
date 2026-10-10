"""Typed pydantic models for the raw Walmart Marketplace orders payloads.

Deliberately STRICT (``extra="forbid"``): accidental drift from the canonical
Walmart shape fails loudly instead of silently corrupting a parse. Every parser
routes raw payloads through :meth:`WalmartOrder.from_api_dict` — the tolerance
seam that selects the known fields and ignores unknown keys.

Walmart money travels as ``{"currency": "USD", "amount": 49.98}`` where
``amount`` may be a number or a string — normalized to an exact decimal string
via :func:`money_amount` so downstream ``Decimal`` conversion is exact (never
binary floats).
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
    """Normalize a Walmart amount (dict, ``WalmartMoney``, or scalar) to a decimal string."""
    if isinstance(value, dict):
        return _as_str(value.get("amount"), "0.0")
    if value is None:
        return "0.0"
    if hasattr(value, "amount"):
        return _as_str(value.amount, "0.0")
    return str(value)


class WalmartMoney(BaseModel):
    """A Walmart amount (``amount`` may be a number or string)."""

    model_config = ConfigDict(extra="forbid")

    amount: Any = "0.0"
    currency: str = "USD"


class WalmartLineItem(BaseModel):
    """A single Walmart order line item."""

    model_config = ConfigDict(extra="forbid")

    line_number: str = ""
    item_status: str = ""
    sku: str = ""
    product_name: str = ""
    quantity: int = Field(default=0, ge=0)
    unit_price: WalmartMoney = Field(default_factory=lambda: WalmartMoney())
    line_total: WalmartMoney = Field(default_factory=lambda: WalmartMoney())


class WalmartOrderSummary(BaseModel):
    """The Walmart order totals breakdown."""

    model_config = ConfigDict(extra="forbid")

    total_amount: WalmartMoney = Field(default_factory=lambda: WalmartMoney())
    subtotal: WalmartMoney = Field(default_factory=lambda: WalmartMoney())
    tax_total: WalmartMoney = Field(default_factory=lambda: WalmartMoney())
    shipping_handling: WalmartMoney = Field(default_factory=lambda: WalmartMoney())


class WalmartOrder(BaseModel):
    """A realistic Walmart Marketplace order projection.

    ``extra="forbid"`` means the real API has MORE fields — use
    :meth:`from_api_dict` (the tolerance seam) to parse raw payloads.
    """

    model_config = ConfigDict(extra="forbid")

    order_id: str = ""
    customer_email_id: str | None = None
    order_date: str = ""  # ISO-8601 — the incremental cursor basis
    order_status: str = ""  # CREATED|ACKNOWLEDGED|SHIPPED|CANCELLED|REFUNDED
    order_type: str = ""
    order_lines: list[WalmartLineItem] = Field(default_factory=list)
    order_summary: WalmartOrderSummary = Field(default_factory=WalmartOrderSummary)

    @classmethod
    def from_api_dict(cls, raw: dict) -> "WalmartOrder":
        """Tolerant parser: selects known fields, ignores unknown keys, never raises."""

        def _money(value: Any) -> WalmartMoney:
            if not isinstance(value, dict):
                value = {}
            return WalmartMoney(
                amount=value.get("amount") if value.get("amount") is not None else "0.0",
                currency=_as_str(value.get("currency"), "USD"),
            )

        def _line_items(items: Any) -> list[WalmartLineItem]:
            out: list[WalmartLineItem] = []
            for item in items or []:
                if not isinstance(item, dict):
                    continue
                item_obj = item.get("item") if isinstance(item.get("item"), dict) else {}
                qty = item.get("orderLineQuantity") if isinstance(item.get("orderLineQuantity"), dict) else {}
                charges = item.get("charges") if isinstance(item.get("charges"), list) else []
                unit_price: WalmartMoney = WalmartMoney()
                line_total: WalmartMoney = WalmartMoney()
                for charge in charges:
                    if not isinstance(charge, dict):
                        continue
                    if str(charge.get("chargeType") or "").upper() == "PRODUCT":
                        unit_price = _money(charge.get("chargeAmount"))
                out.append(
                    WalmartLineItem(
                        line_number=_as_str(item.get("lineNumber")),
                        item_status=_as_str(item.get("itemStatus")),
                        sku=_as_str(item_obj.get("sku")),
                        product_name=_as_str(item_obj.get("productName")),
                        quantity=int(qty.get("amount") or 0)
                        if str(qty.get("amount") or "").isdigit()
                        else 0,
                        unit_price=unit_price,
                        line_total=line_total,
                    )
                )
            return out

        summary = raw.get("orderSummary") if isinstance(raw.get("orderSummary"), dict) else {}
        return cls(
            order_id=_as_str(raw.get("orderId")),
            customer_email_id=raw.get("customerEmailId"),
            order_date=_as_str(raw.get("orderDate")),
            order_status=_as_str(raw.get("orderStatus")),
            order_type=_as_str(raw.get("orderType")),
            order_lines=_line_items(raw.get("orderLines")),
            order_summary=WalmartOrderSummary(
                total_amount=_money(summary.get("totalAmount")),
                subtotal=_money(summary.get("subtotal")),
                tax_total=_money(summary.get("taxTotal")),
                shipping_handling=_money(summary.get("shippingHandling")),
            ),
        )


__all__ = [
    "WalmartLineItem",
    "WalmartMoney",
    "WalmartOrder",
    "WalmartOrderSummary",
    "money_amount",
]
