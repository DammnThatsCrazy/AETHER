"""Typed pydantic models for the raw Shopify REST payloads.

These models are deliberately STRICT (``extra="forbid"``): accidental drift
from the canonical Shopify shape fails loudly instead of silently corrupting a
parse. Because the real Shopify API sends many fields we do not model, every
parser in this plugin routes raw payloads through :meth:`ShopifyOrder.from_api_dict`
— the tolerance seam that selects the known fields and ignores unknown keys
(never raising on missing optional keys).

Webhook HMAC headers are computed over the RAW request body — never over the
parsed dict (see ``services.providers.shopify.webhook``).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _as_int(value: Any, default: int = 0) -> int:
    """Coerce a Shopify id (int or digit-string) to ``int``; never raise."""
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


class ShopifyMoney(BaseModel):
    """A Shopify money payload (amounts travel as strings like ``"12.50"``)."""

    model_config = ConfigDict(extra="forbid")

    amount: str
    currency_code: str


class ShopifyCustomer(BaseModel):
    """Minimal Shopify customer projection (orders payload)."""

    model_config = ConfigDict(extra="forbid")

    id: int
    email: str | None = None
    phone: str | None = None
    first_name: str | None = None
    last_name: str | None = None


class ShopifyLineItem(BaseModel):
    """A single Shopify order line item."""

    model_config = ConfigDict(extra="forbid")

    id: int
    product_id: int | None = None
    variant_id: int | None = None
    sku: str | None = None
    title: str = ""
    quantity: int = Field(default=0, ge=0)
    price: str = "0.0"
    total_discount: str = "0.0"


class ShopifyOrder(BaseModel):
    """A realistic Shopify order projection.

    ``extra="forbid"`` means the real API has MORE fields — use
    :meth:`from_api_dict` (the tolerance seam) to parse raw payloads.
    """

    model_config = ConfigDict(extra="forbid")

    id: int
    name: str = ""
    email: str | None = None
    created_at: str  # ISO-8601
    updated_at: str  # ISO-8601
    cancelled_at: str | None = None
    closed_at: str | None = None
    financial_status: str | None = None  # paid|pending|refunded|voided|...
    currency: str
    subtotal_price: str = "0.0"
    shipping_lines: list[dict] = Field(default_factory=list)
    total_shipping: str = "0.0"
    total_tax: str = "0.0"
    total_discounts: str = "0.0"
    total_price: str = "0.0"
    line_items: list[ShopifyLineItem] = Field(default_factory=list)
    customer: ShopifyCustomer | None = None
    note: str | None = None
    properties: list[dict] = Field(default_factory=list)

    @classmethod
    def from_api_dict(cls, raw: dict) -> "ShopifyOrder":
        """Select the fields this model knows (ignore unknown keys).

        Tolerant parser: uses ``.get()`` with defaults so real payloads parse,
        and never raises on missing optional keys. Nested ``line_items`` and
        ``customer`` are parsed through the same tolerance (real payloads carry
        extra fields on those too).
        """

        def _line_items(items: Any) -> list[ShopifyLineItem]:
            out: list[ShopifyLineItem] = []
            for item in items or []:
                if not isinstance(item, dict):
                    continue
                out.append(
                    ShopifyLineItem(
                        id=_as_int(item.get("id")),
                        product_id=_as_int(item.get("product_id"))
                        if item.get("product_id") is not None
                        else None,
                        variant_id=_as_int(item.get("variant_id"))
                        if item.get("variant_id") is not None
                        else None,
                        sku=_as_str(item.get("sku")),
                        title=_as_str(item.get("title")),
                        quantity=_as_int(item.get("quantity")),
                        price=_as_str(item.get("price"), "0.0"),
                        total_discount=_as_str(item.get("total_discount"), "0.0"),
                    )
                )
            return out

        def _customer(value: Any) -> ShopifyCustomer | None:
            if not isinstance(value, dict):
                return None
            return ShopifyCustomer(
                id=_as_int(value.get("id")),
                email=value.get("email"),
                phone=value.get("phone"),
                first_name=value.get("first_name"),
                last_name=value.get("last_name"),
            )

        return cls(
            id=_as_int(raw.get("id")),
            name=_as_str(raw.get("name")),
            email=raw.get("email"),
            created_at=_as_str(raw.get("created_at")),
            updated_at=_as_str(raw.get("updated_at")),
            cancelled_at=raw.get("cancelled_at"),
            closed_at=raw.get("closed_at"),
            financial_status=raw.get("financial_status"),
            currency=_as_str(raw.get("currency")),
            subtotal_price=_as_str(raw.get("subtotal_price"), "0.0"),
            shipping_lines=list(raw.get("shipping_lines") or []),
            total_shipping=_as_str(raw.get("total_shipping"), "0.0"),
            total_tax=_as_str(raw.get("total_tax"), "0.0"),
            total_discounts=_as_str(raw.get("total_discounts"), "0.0"),
            total_price=_as_str(raw.get("total_price"), "0.0"),
            line_items=_line_items(raw.get("line_items")),
            customer=_customer(raw.get("customer")),
            note=raw.get("note"),
            properties=list(raw.get("properties") or []),
        )


class ShopifyWebhookEnvelope(BaseModel):
    """Shopify webhook delivery envelope (topic + nested order payload)."""

    model_config = ConfigDict(extra="forbid")

    id: int
    domain: str = ""
    topic: str = ""  # "orders/create" | "orders/update" | "orders/cancelled"
    created_at: str = ""
    order_id: int | None = None
    body: dict | None = None  # nested order payload for webhook deliveries

    @classmethod
    def from_api_dict(cls, raw: dict) -> "ShopifyWebhookEnvelope":
        """Tolerance seam for webhook delivery envelopes (unknown keys ignored)."""
        body = raw.get("body")
        if isinstance(body, dict) and body.get("id") is not None:
            order_id = _as_int(body.get("id"))
        else:
            order_id = _as_int(raw.get("order_id")) if raw.get("order_id") is not None else None
        return cls(
            id=_as_int(raw.get("id")),
            domain=_as_str(raw.get("domain")),
            topic=_as_str(raw.get("topic")),
            created_at=_as_str(raw.get("created_at")),
            order_id=order_id,
            body=body if isinstance(body, dict) else None,
        )


__all__ = [
    "ShopifyCustomer",
    "ShopifyLineItem",
    "ShopifyMoney",
    "ShopifyOrder",
    "ShopifyWebhookEnvelope",
]
