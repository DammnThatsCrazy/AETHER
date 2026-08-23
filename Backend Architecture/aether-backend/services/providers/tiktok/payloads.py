"""Typed pydantic models for the raw TikTok Shop orders payloads.

Deliberately STRICT (``extra="forbid"``): accidental drift from the canonical
TikTok Shop shape fails loudly instead of silently corrupting a parse. Every
parser routes raw payloads through :meth:`TikTokOrder.from_api_dict` — the
tolerance seam that selects the known fields and ignores unknown keys.

TikTok Shop money travels as ``{"currency": "USD", "amount": 66.47}`` where
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
    """Normalize a TikTok amount (dict, ``TikTokMoney``, or scalar) to a decimal string."""
    if isinstance(value, dict):
        return _as_str(value.get("amount"), "0.0")
    if value is None:
        return "0.0"
    if hasattr(value, "amount"):
        return _as_str(value.amount, "0.0")
    return str(value)


class TikTokMoney(BaseModel):
    """A TikTok Shop amount (``amount`` may be a number or string)."""

    model_config = ConfigDict(extra="forbid")

    amount: Any = "0.0"
    currency: str = "USD"


class TikTokOrderLine(BaseModel):
    """A single TikTok Shop order line."""

    model_config = ConfigDict(extra="forbid")

    id: str = ""
    product_name: str = ""
    seller_sku: str = ""
    quantity: int = Field(default=0, ge=0)
    sale_price: TikTokMoney = Field(default_factory=lambda: TikTokMoney())


class TikTokPayment(BaseModel):
    """The TikTok Shop payment block (order totals)."""

    model_config = ConfigDict(extra="forbid")

    sub_total: TikTokMoney = Field(default_factory=lambda: TikTokMoney())
    shipping_fee: TikTokMoney = Field(default_factory=lambda: TikTokMoney())
    tax_amount: TikTokMoney = Field(default_factory=lambda: TikTokMoney())
    total_amount: TikTokMoney = Field(default_factory=lambda: TikTokMoney())


class TikTokOrder(BaseModel):
    """A realistic TikTok Shop order projection.

    ``extra="forbid"`` means the real API has MORE fields — use
    :meth:`from_api_dict` (the tolerance seam) to parse raw payloads.
    """

    model_config = ConfigDict(extra="forbid")

    order_id: str = ""
    order_status: str = ""  # UNPAID|AWAITING_SHIPMENT|... (see the normalizer status map)
    create_time: int = 0  # unix epoch seconds
    update_time: int = 0  # unix epoch seconds — the incremental cursor field
    buyer_uid: str = ""
    currency: str = "USD"
    payment: TikTokPayment = Field(default_factory=TikTokPayment)
    order_line_list: list[TikTokOrderLine] = Field(default_factory=list)

    @classmethod
    def from_api_dict(cls, raw: dict) -> "TikTokOrder":
        """Tolerant parser: selects known fields, ignores unknown keys, never raises."""

        def _money(value: Any) -> TikTokMoney:
            if not isinstance(value, dict):
                value = {}
            return TikTokMoney(
                amount=value.get("amount") if value.get("amount") is not None else "0.0",
                currency=_as_str(value.get("currency"), "USD"),
            )

        def _lines(items: Any) -> list[TikTokOrderLine]:
            out: list[TikTokOrderLine] = []
            for item in items or []:
                if not isinstance(item, dict):
                    continue
                out.append(
                    TikTokOrderLine(
                        id=_as_str(item.get("id")),
                        product_name=_as_str(item.get("product_name")),
                        seller_sku=_as_str(item.get("seller_sku")),
                        quantity=int(item.get("quantity") or 0)
                        if str(item.get("quantity") or "").isdigit()
                        else 0,
                        sale_price=_money(item.get("sale_price")),
                    )
                )
            return out

        payment = raw.get("payment") if isinstance(raw.get("payment"), dict) else {}
        total_amount = (
            raw.get("total_amount")
            if raw.get("total_amount") is not None
            else payment.get("total_amount")
        )
        return cls(
            order_id=_as_str(raw.get("order_id")),
            order_status=_as_str(raw.get("order_status")),
            create_time=int(raw.get("create_time") or 0)
            if str(raw.get("create_time") or "").isdigit()
            else 0,
            update_time=int(raw.get("update_time") or 0)
            if str(raw.get("update_time") or "").isdigit()
            else 0,
            buyer_uid=_as_str(raw.get("buyer_uid")),
            currency=_as_str(raw.get("currency"), "USD"),
            payment=TikTokPayment(
                sub_total=_money(payment.get("sub_total")),
                shipping_fee=_money(payment.get("shipping_fee")),
                tax_amount=_money(payment.get("tax_amount")),
                total_amount=_money(total_amount),
            ),
            order_line_list=_lines(raw.get("order_line_list")),
        )


__all__ = [
    "TikTokMoney",
    "TikTokOrder",
    "TikTokOrderLine",
    "TikTokPayment",
    "money_amount",
]
