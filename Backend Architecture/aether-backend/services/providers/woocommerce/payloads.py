"""Typed pydantic models for the raw WooCommerce REST/webhook payloads.

Deliberately STRICT (``extra="forbid"``): accidental drift from the canonical
WooCommerce shape fails loudly instead of silently corrupting a parse. Every
parser routes raw payloads through :meth:`WooCommerceOrder.from_api_dict` — the
tolerance seam that selects the known fields and ignores unknown keys (never
raising on missing optional keys). All money travels as strings like ``"102.98"``
and is converted with :class:`decimal.Decimal` downstream, never binary floats.

Webhook HMAC headers are computed over the RAW request body — never over the
parsed dict (see ``services.providers.woocommerce.webhook``).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _as_int(value: Any, default: int = 0) -> int:
    """Coerce a WooCommerce id (int or digit-string) to ``int``; never raise."""
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


class WooCommerceLineItem(BaseModel):
    """A single WooCommerce order line item."""

    model_config = ConfigDict(extra="forbid")

    id: int
    product_id: int = 0
    variation_id: int | None = None
    sku: str = ""
    name: str = ""
    quantity: int = Field(default=0, ge=0)
    price: str = "0.0"  # unit price (per-unit), string form
    total: str = "0.0"  # line total, string form


class WooCommerceCustomer(BaseModel):
    """Minimal WooCommerce customer projection (order payload)."""

    model_config = ConfigDict(extra="forbid")

    id: int = 0
    email: str | None = None
    phone: str | None = None
    first_name: str | None = None
    last_name: str | None = None


class WooCommerceOrder(BaseModel):
    """A realistic WooCommerce order projection.

    ``extra="forbid"`` means the real API has MORE fields — use
    :meth:`from_api_dict` (the tolerance seam) to parse raw payloads.
    """

    model_config = ConfigDict(extra="forbid")

    id: int
    number: str = ""
    status: str = ""  # pending|processing|on-hold|completed|cancelled|refunded|failed|trash
    currency: str
    date_created: str = ""  # ISO-8601
    date_modified: str = ""  # ISO-8601 — the incremental cursor field
    date_paid: str | None = None
    customer_id: int = 0
    billing: WooCommerceCustomer | None = None
    subtotal: str = "0.0"
    total_tax: str = "0.0"
    discount_total: str = "0.0"
    shipping_total: str = "0.0"
    total: str = "0.0"
    line_items: list[WooCommerceLineItem] = Field(default_factory=list)
    customer_note: str | None = None

    @classmethod
    def from_api_dict(cls, raw: dict) -> "WooCommerceOrder":
        """Tolerant parser: selects known fields, ignores unknown keys, never raises."""

        def _line_items(items: Any) -> list[WooCommerceLineItem]:
            out: list[WooCommerceLineItem] = []
            for item in items or []:
                if not isinstance(item, dict):
                    continue
                out.append(
                    WooCommerceLineItem(
                        id=_as_int(item.get("id")),
                        product_id=_as_int(item.get("product_id")),
                        variation_id=_as_int(item.get("variation_id"))
                        if item.get("variation_id") is not None
                        else None,
                        sku=_as_str(item.get("sku")),
                        name=_as_str(item.get("name")),
                        quantity=_as_int(item.get("quantity")),
                        price=_as_str(item.get("price"), "0.0"),
                        total=_as_str(item.get("total"), "0.0"),
                    )
                )
            return out

        def _customer(value: Any) -> WooCommerceCustomer | None:
            if not isinstance(value, dict):
                return None
            return WooCommerceCustomer(
                id=_as_int(value.get("id")),
                email=value.get("email"),
                phone=value.get("phone"),
                first_name=value.get("first_name"),
                last_name=value.get("last_name"),
            )

        return cls(
            id=_as_int(raw.get("id")),
            number=_as_str(raw.get("number")),
            status=_as_str(raw.get("status")),
            currency=_as_str(raw.get("currency")),
            date_created=_as_str(raw.get("date_created")),
            date_modified=_as_str(raw.get("date_modified")),
            date_paid=raw.get("date_paid"),
            customer_id=_as_int(raw.get("customer_id")),
            billing=_customer(raw.get("billing")),
            subtotal=_as_str(raw.get("subtotal"), "0.0"),
            total_tax=_as_str(raw.get("total_tax"), "0.0"),
            discount_total=_as_str(raw.get("discount_total"), "0.0"),
            shipping_total=_as_str(raw.get("shipping_total"), "0.0"),
            total=_as_str(raw.get("total"), "0.0"),
            line_items=_line_items(raw.get("line_items")),
            customer_note=raw.get("customer_note"),
        )


__all__ = ["WooCommerceCustomer", "WooCommerceLineItem", "WooCommerceOrder"]
