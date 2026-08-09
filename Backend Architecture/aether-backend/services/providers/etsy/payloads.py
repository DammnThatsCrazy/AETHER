"""Typed pydantic models for the raw Etsy receipts payloads.

Deliberately STRICT (``extra="forbid"``): accidental drift from the canonical
Etsy shape fails loudly instead of silently corrupting a parse. Every parser
routes raw payloads through :meth:`EtsyReceipt.from_api_dict` — the tolerance
seam that selects the known fields and ignores unknown keys.

Etsy API v3 money can arrive as a plain decimal number (``"12.50"`` / ``12.50``)
or as a ``Money`` object ``{"amount": 1250, "divisor": 100, "currency_code":
"USD"}``. :func:`_money_amount` normalizes BOTH forms to an exact decimal
string so downstream ``Decimal`` conversion is always exact (never floats).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _as_int(value: Any, default: int = 0) -> int:
    """Coerce an Etsy id/ts (int or digit-string) to ``int``; never raise."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_str(value: Any, default: str = "") -> str:
    """Coerce a scalar to ``str``; ``None`` becomes ``default``."""
    if value is None:
        return default
    return str(value)


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}


def money_amount(value: Any) -> str:
    """Normalize an Etsy amount (number or Money dict) to an exact decimal string."""
    if isinstance(value, dict):
        try:
            amount = value.get("amount")
            divisor = value.get("divisor") or 1
            return str(Decimal(str(amount)) / Decimal(str(divisor)))
        except (TypeError, ValueError, ArithmeticError):
            return "0.0"
    if value is None:
        return "0.0"
    return str(value)


class EtsyMoney(BaseModel):
    """An Etsy API v3 Money object (minor units + divisor)."""

    model_config = ConfigDict(extra="forbid")

    amount: int = 0
    divisor: int = 100
    currency_code: str = "USD"

    def to_decimal(self) -> Decimal:
        """Exact ``amount / divisor`` as a :class:`decimal.Decimal`."""
        try:
            return Decimal(self.amount) / Decimal(self.divisor)
        except (TypeError, ValueError):
            return Decimal("0.0")


class EtsyTransaction(BaseModel):
    """A single Etsy receipt transaction (line item)."""

    model_config = ConfigDict(extra="forbid")

    transaction_id: int
    title: str = ""
    quantity: int = Field(default=0, ge=0)
    price: Any = "0.0"  # number or Money dict — normalized by money_amount()


class EtsyBuyer(BaseModel):
    """Minimal Etsy buyer projection (receipt payload)."""

    model_config = ConfigDict(extra="forbid")

    user_id: int = 0
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None


class EtsyReceipt(BaseModel):
    """A realistic Etsy shop receipt (the orders payload).

    ``extra="forbid"`` means the real API has MORE fields — use
    :meth:`from_api_dict` (the tolerance seam) to parse raw payloads.
    """

    model_config = ConfigDict(extra="forbid")

    receipt_id: int
    create_ts: int = 0  # unix epoch seconds
    update_ts: int = 0  # unix epoch seconds — the incremental cursor field
    is_paid: bool = False
    is_shipped: bool = False
    status: str | None = None  # optional provider state override
    currency_code: str = "USD"
    grandtotal: Any = "0.0"
    subtotal: Any = "0.0"
    total_tax_cost: Any = "0.0"
    shipping_cost: Any = "0.0"
    discount_amt: Any = "0.0"
    buyer: EtsyBuyer | None = None
    transactions: list[EtsyTransaction] = Field(default_factory=list)

    @classmethod
    def from_api_dict(cls, raw: dict) -> "EtsyReceipt":
        """Tolerant parser: selects known fields, ignores unknown keys, never raises."""

        def _transactions(items: Any) -> list[EtsyTransaction]:
            out: list[EtsyTransaction] = []
            for item in items or []:
                if not isinstance(item, dict):
                    continue
                out.append(
                    EtsyTransaction(
                        transaction_id=_as_int(item.get("transaction_id")),
                        title=_as_str(item.get("title")),
                        quantity=_as_int(item.get("quantity")),
                        price=item.get("price"),
                    )
                )
            return out

        def _buyer(value: Any) -> EtsyBuyer | None:
            if not isinstance(value, dict):
                return None
            return EtsyBuyer(
                user_id=_as_int(value.get("user_id")),
                email=value.get("email"),
                first_name=value.get("first_name"),
                last_name=value.get("last_name"),
            )

        return cls(
            receipt_id=_as_int(raw.get("receipt_id")),
            create_ts=_as_int(raw.get("create_ts")),
            update_ts=_as_int(raw.get("update_ts")),
            is_paid=_as_bool(raw.get("is_paid")),
            is_shipped=_as_bool(raw.get("is_shipped")),
            status=raw.get("status"),
            currency_code=_as_str(raw.get("currency_code"), "USD"),
            grandtotal=raw.get("grandtotal") if raw.get("grandtotal") is not None else "0.0",
            subtotal=raw.get("subtotal") if raw.get("subtotal") is not None else "0.0",
            total_tax_cost=raw.get("total_tax_cost") if raw.get("total_tax_cost") is not None else "0.0",
            shipping_cost=raw.get("shipping_cost") if raw.get("shipping_cost") is not None else "0.0",
            discount_amt=raw.get("discount_amt") if raw.get("discount_amt") is not None else "0.0",
            buyer=_buyer(raw.get("buyer")),
            transactions=_transactions(raw.get("transactions")),
        )


__all__ = [
    "EtsyBuyer",
    "EtsyMoney",
    "EtsyReceipt",
    "EtsyTransaction",
    "money_amount",
]
