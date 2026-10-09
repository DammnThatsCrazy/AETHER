"""Shopify order normalization (:class:`EventNormalizer`) — deterministic, network-free.

Maps ONE ``RawProviderRecord`` whose ``payload`` is a Shopify order dict (from
pull or webhook, or a ``ShopifyOrder`` ``model_dump``) onto a single provider-
neutral ``commerce.order.*`` :class:`AetherEvent <shared.integration_contracts.events.AetherEvent>`.

REST v1 event-type mapping (status rule, in order):

* ``cancelled_at`` set          -> ``OrderStatus.cancelled``  -> ``commerce.order.cancelled``
* ``created_at == updated_at``  -> ``OrderStatus.created``    -> ``commerce.order.created``
* ``financial_status == refunded`` -> ``OrderStatus.refunded`` -> ``commerce.order.refunded``
* otherwise                     -> ``OrderStatus.updated``    -> ``commerce.order.updated``

GraphQL v2 polls are snapshots. They emit ``commerce.order.updated`` or
``commerce.order.cancelled`` from store order lifecycle. A Shopify display
financial status alone is not processor refund or settlement evidence.

Money is parsed via ``decimal.Decimal(str(value))`` — Shopify amounts are
strings and are never handled through binary floats. REST v1 retains its
historical full raw context. GraphQL v2 keeps the full provider payload only
in protected raw Bronze and emits opaque lineage in the canonical event, so
contact fields and notes do not spread through graph/outbox consumers.
Unknown record types are reported via ``dropped`` — never silent.
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
from shared.integration_contracts.events import AetherEvent, RawProviderRecord, compute_checksum
from shared.integration_contracts.normalization import EventNormalizer, NormalizationResult
from shared.integration_contracts.source_objects import (
    event_revision_id_for_parts,
    logical_event_id_for_source_parts,
)

from services.providers.shopify.payloads import ShopifyOrder
from services.providers.shopify.graphql_pull import (
    PAYLOAD_SCHEMA_VERSION,
    _SHOP_GID_RE,
    _economic_revision_key,
    _money_amount as _graphql_money_amount,
    _source_revision_key,
    _validate_order as _validate_graphql_order,
)

# Identity continuity: source identity creation for Shopify customers (via SourceIdentityRegistry)
from services.identity.integration import IdentityIngestionWire
from services.identity.repository import IdentityResolutionRepository
from services.identity.source_identity_registry import SourceIdentityRegistry
from shared.logger.logger import get_logger as _get_logger

_logger = _get_logger("aether.providers.shopify.identity")


async def register_shopify_customer_identity(
    tenant_id: str,
    source_system_id: str,
    customer_data: dict,
) -> object | None:
    """Register a source identity from a Shopify customer record.

    Wires SourceIdentityRegistry via IdentityIngestionWire (identity continuity runtime).
    Called by pull/webhook sync when customer data is ingested.
    """
    try:
        repo = IdentityResolutionRepository()
        registry = SourceIdentityRegistry(repo)
        wire = IdentityIngestionWire(registry)
        rec = await wire.extract_and_register_from_provider_customer(
            tenant_id=tenant_id,
            source_system_id=source_system_id,
            provider="shopify",
            customer_data=customer_data,
        )
        if rec:
            from services.identity.observability import IdentityTrace, identity_metrics

            trace = IdentityTrace(tenant_id=tenant_id, source_system_id=source_system_id)
            trace.source_identity_register(rec.id)
            identity_metrics.record_source_identity_created()
            # Also upsert email/phone claims when present
            if customer_data.get("email"):
                await registry.upsert_identity_claim(
                    tenant_id=tenant_id,
                    source_identity_id=rec.id,
                    claim_type="email",
                    raw_value=customer_data["email"],
                    verification_status="observed",
                    pii_classification="sensitive",
                )
            if customer_data.get("phone"):
                await registry.upsert_identity_claim(
                    tenant_id=tenant_id,
                    source_identity_id=rec.id,
                    claim_type="phone",
                    raw_value=customer_data["phone"],
                    verification_status="observed",
                    pii_classification="sensitive",
                )
        return rec
    except Exception as e:
        _logger.warning("shopify source identity registration failed: %s", e)
        return None


NORMALIZER_VERSION = "1"
EVENT_SCHEMA_VERSION = "2"
GRAPHQL_MAPPING_VERSION = "shopify.order.snapshot.v1"
SUPPORTED_RECORD_TYPE = "order"

# OrderStatus -> provider-neutral event_type.
_EVENT_TYPE_BY_STATUS: dict[OrderStatus, str] = {
    OrderStatus.cancelled: "commerce.order.cancelled",
    OrderStatus.created: "commerce.order.created",
    OrderStatus.refunded: "commerce.order.refunded",
    OrderStatus.updated: "commerce.order.updated",
}

# Provider fields surfaced under data["provider"] (the order/snapshot models do
# not capture them; nothing is lost because the full payload is in context).
_PROVIDER_DATA_FIELDS = (
    "name",
    "financial_status",
    "fulfillment_status",
    "closed_at",
    "cancelled_at",
    "tags",
)

# Shopify webhook topic derived from the resolved status.
_TOPIC_BY_STATUS: dict[OrderStatus, str] = {
    OrderStatus.cancelled: "orders/cancelled",
    OrderStatus.created: "orders/create",
    OrderStatus.refunded: "orders/cancelled",
    OrderStatus.updated: "orders/update",
}


def _money(value: Any, currency: str) -> Money:
    """Exact ``Decimal`` parse of a Shopify amount string (e.g. ``"12.50"``)."""
    return Money(amount=Decimal(str(value)), currency=currency)


def _legacy_id_from_gid(value: Any, resource: str) -> int | None:
    """Recover the numeric REST ID only from a Shopify GID of the right type."""
    if value is None:
        return None
    prefix = f"gid://shopify/{resource}/"
    if not isinstance(value, str) or not value.startswith(prefix):
        raise ValueError("invalid Shopify GID")
    numeric = value[len(prefix) :]
    if not numeric.isdigit() or not numeric or int(numeric) <= 0:
        raise ValueError("invalid Shopify GID")
    return int(numeric)


def _graphql_order_to_rest_shape(node: dict[str, Any]) -> dict[str, Any]:
    """Project a complete native GraphQL node for the existing commerce mapper.

    The returned dict is an in-memory projection only. Protected raw Bronze
    retains the original GraphQL payload and exact money strings.
    GraphQL current totals reflect the state after returns and order edits.
    """
    _validate_graphql_order(node)
    if node["lineItems"]["pageInfo"]["hasNextPage"]:
        raise ValueError("incomplete GraphQL line items")
    currency = node["currencyCode"]
    customer = node.get("customer")
    if customer is not None:
        if not isinstance(customer, dict) or customer.get("legacyResourceId") is None:
            raise ValueError("customer identity missing")
        # Protected Bronze retains the exact provider payload. The canonical
        # commerce projection only needs the opaque customer reference; never
        # carry contact details or freeform customer text into normalizer
        # intermediates that may later be reused by graph or outbox code.
        customer = {"id": customer["legacyResourceId"]}
    line_items = []
    for line in node["lineItems"]["nodes"]:
        product = line.get("product")
        variant = line.get("variant")
        line_items.append(
            {
                "id": _legacy_id_from_gid(line["id"], "LineItem"),
                "product_id": _legacy_id_from_gid(product.get("id"), "Product")
                if isinstance(product, dict)
                else None,
                "variant_id": _legacy_id_from_gid(variant.get("id"), "ProductVariant")
                if isinstance(variant, dict)
                else None,
                "sku": line.get("sku"),
                "title": line["title"],
                "quantity": line["quantity"],
                "price": _graphql_money_amount(line["originalUnitPriceSet"], currency),
                "total_discount": _graphql_money_amount(line["totalDiscountSet"], currency),
            }
        )
    return {
        "id": int(node["legacyResourceId"]),
        "name": node.get("name") or "",
        "created_at": node["createdAt"],
        "updated_at": node["updatedAt"],
        "cancelled_at": node.get("cancelledAt"),
        "closed_at": node.get("closedAt"),
        "financial_status": (node.get("displayFinancialStatus") or "").lower(),
        "fulfillment_status": (node.get("displayFulfillmentStatus") or "").lower(),
        "currency": currency,
        "subtotal_price": _graphql_money_amount(node["currentSubtotalPriceSet"], currency),
        "total_shipping": _graphql_money_amount(node["currentShippingPriceSet"], currency),
        "total_tax": _graphql_money_amount(node["currentTotalTaxSet"], currency),
        "total_discounts": _graphql_money_amount(node["currentTotalDiscountsSet"], currency),
        "total_price": _graphql_money_amount(node["currentTotalPriceSet"], currency),
        "line_items": line_items,
        "customer": customer,
    }


def _order_status(order: ShopifyOrder) -> OrderStatus:
    """Resolve the canonical status per the documented rule (checked in order)."""
    if order.cancelled_at:
        return OrderStatus.cancelled
    if order.created_at == order.updated_at:
        return OrderStatus.created
    if order.financial_status == "refunded":
        return OrderStatus.refunded
    return OrderStatus.updated


def _logical_event_id(raw: RawProviderRecord, revision_key: str) -> str:
    """Stable logical identity for one Shopify order economic/lifecycle fact.

    Raw acquisition revisions include contact material and updatedAt. This
    identity deliberately includes only the PII-free economic revision and
    immutable tenant, shop, realm, order and semantic event scope.
    """
    return logical_event_id_for_source_parts(
        tenant_id=raw.tenant_id,
        provider_family="shopify",
        source_account_realm=raw.source_account_realm,
        source_account_key=raw.source_account_key,
        source_object_type=raw.source_object_type,
        source_object_id=raw.source_object_id,
        source_revision_key=revision_key,
        semantic_slot="order.snapshot",
    )


def _event_revision_id(
    *,
    logical_event_id: str,
    mapping_version: str,
    normalizer_version: str,
    canonical_payload_digest: str,
) -> str:
    """Identify one immutable Shopify interpretation of a logical order fact."""
    return event_revision_id_for_parts(
        logical_event_id=logical_event_id,
        event_schema_version=EVENT_SCHEMA_VERSION,
        mapping_version=mapping_version,
        normalizer_version=normalizer_version,
        canonical_payload_digest=canonical_payload_digest,
    )


def to_commerce_order(
    order: ShopifyOrder, *, account_id: str = "default", snapshot_mode: bool = False
) -> CommerceOrder:
    """Map a parsed :class:`ShopifyOrder` onto a :class:`CommerceOrder`.

    All money comes from ``Decimal(str(value))``; line totals are computed from
    decimals (``unit_price * quantity``), never floats. A GraphQL poll is a
    snapshot, with no creation event topic or processor settlement proof, so
    ``snapshot_mode`` emits updated/cancelled order lifecycle only.
    """
    currency = order.currency
    totals = OrderTotals(
        subtotal=_money(order.subtotal_price, currency),
        shipping=_money(order.total_shipping, currency),
        tax=_money(order.total_tax, currency),
        discount=_money(order.total_discounts, currency),
        total=_money(order.total_price, currency),
    )
    line_items = [
        OrderLineItem(
            line_item_id=str(item.id),
            product_id=str(item.product_id) if item.product_id is not None else "",
            variant_id=str(item.variant_id) if item.variant_id is not None else None,
            sku=item.sku,
            title=item.title,
            quantity=item.quantity,
            unit_price=_money(item.price, currency),
            line_total=_money(Decimal(str(item.price)) * Decimal(item.quantity), currency),
        )
        for item in order.line_items
    ]
    customer: OrderCustomer | None = None
    if order.customer is not None:
        customer = OrderCustomer(
            customer_id=str(order.customer.id),
            email=order.customer.email,
            phone=order.customer.phone,
            first_name=order.customer.first_name,
            last_name=order.customer.last_name,
        )
    properties: dict[str, Any] = {}
    for index, prop in enumerate(order.properties):
        if isinstance(prop, dict):
            properties[str(index)] = prop
    return CommerceOrder(
        order_id=str(order.id),
        account_id=account_id,
        status=(OrderStatus.cancelled if order.cancelled_at else OrderStatus.updated)
        if snapshot_mode
        else _order_status(order),
        currency=currency,
        totals=totals,
        line_items=line_items,
        customer=customer,
        created_at=order.created_at,
        updated_at=order.updated_at,
        note=order.note,
        properties=properties,
    )


class ShopifyOrderNormalizer:
    """EventNormalizer: deterministic, synchronous Shopify order -> event."""

    normalizer_version = NORMALIZER_VERSION

    def normalize(self, raw: RawProviderRecord) -> NormalizationResult:
        if raw.provider_record_type != SUPPORTED_RECORD_TYPE:
            return NormalizationResult(
                events=[],
                skipped=0,
                dropped=[f"{raw.record_id}:{raw.provider_record_type}"],
                normalizer_version=self.normalizer_version,
            )
        # Any parse OR money-conversion failure (e.g. a pathological empty
        # amount string) must surface as a visible drop — the normalizer never
        # raises and never silently zeroes a bad amount.
        try:
            if raw.schema_version == "2" and raw.payload_schema_version != PAYLOAD_SCHEMA_VERSION:
                raise ValueError("unrecognized v2 Shopify payload schema")
            if raw.payload_schema_version == PAYLOAD_SCHEMA_VERSION:
                source_payload = _graphql_order_to_rest_shape(raw.payload)
            elif str(raw.payload.get("id", "")).startswith("gid://shopify/"):
                raise ValueError("unrecognized GraphQL payload schema")
            else:
                source_payload = raw.payload
            if raw.schema_version == "2":
                if (
                    raw.source_account_realm not in ("live", "test")
                    or raw.metadata.get("source_account_realm") != raw.source_account_realm
                    or not isinstance(raw.source_account_key, str)
                    or not _SHOP_GID_RE.fullmatch(raw.source_account_key)
                    or raw.metadata.get("shopify_shop_gid") != raw.source_account_key
                    or raw.source_object_type != "order"
                    or raw.source_object_id != raw.payload.get("id")
                    or raw.provider_record_id != str(raw.payload.get("legacyResourceId"))
                    or raw.source_revision_key != _source_revision_key(raw.payload)
                    or raw.checksum != compute_checksum(raw.payload)
                ):
                    raise ValueError("GraphQL source identity mismatch")
                economic_revision_key = _economic_revision_key(raw.payload)
            order = ShopifyOrder.from_api_dict(source_payload)
            commerce = to_commerce_order(
                order,
                account_id=raw.account_id or "default",
                snapshot_mode=raw.schema_version == "2",
            )
        except Exception as exc:  # noqa: BLE001 - unparseable payload is a visible drop
            return NormalizationResult(
                events=[],
                skipped=0,
                dropped=[f"{raw.record_id}:unparseable:{type(exc).__name__}"],
                normalizer_version=self.normalizer_version,
            )

        status = commerce.status
        event_type = _EVENT_TYPE_BY_STATUS[status]
        account_id = raw.account_id or "default"

        # V2 canonical event data is JSON-safe before it is hashed. In
        # particular, Pydantic's Python dump leaves Money.amount as Decimal,
        # which the shared checksum's canonical JSON encoder rejects. Keep the
        # existing v1 in-memory data shape unchanged for REST consumers.
        data: dict[str, Any] = order_to_snapshot(commerce).model_dump(
            mode="json" if raw.schema_version == "2" else "python"
        )
        if raw.schema_version == "2":
            # Shopify's display financial status is an order observation. It
            # is not evidence that a payment processor settled funds.
            data["provider"] = {
                "shopify_display_financial_status": order.financial_status,
                "shopify_display_fulfillment_status": source_payload.get("fulfillment_status"),
            }
            context: dict[str, Any] = {
                "acquisition_mode": raw.acquisition_mode,
                "connection_id": raw.connection_id,
                "raw_record_id": raw.record_id,
                "raw_provider_checksum": raw.checksum,
                "bronze_provider_record_id": raw.bronze_provider_record_id,
                "payload_schema_version": raw.payload_schema_version,
                "source_account_key": raw.source_account_key,
                "source_object_id": raw.source_object_id,
                "source_revision_key": raw.source_revision_key,
                "economic_revision_key": economic_revision_key,
                "source_account_realm": raw.source_account_realm,
                "stream_id": raw.stream_id,
            }
        else:
            data["provider"] = {
                key: source_payload.get(key)
                for key in _PROVIDER_DATA_FIELDS
                if key in source_payload and source_payload.get(key) is not None
            }
            context = {
                "acquisition_mode": raw.acquisition_mode,
                "connection_id": raw.connection_id,
                "raw_provider_event_type": _TOPIC_BY_STATUS[status],
                "financial_status": order.financial_status,
                "fulfillment_status": source_payload.get("fulfillment_status"),
                # Historical REST v1 context retained until its cutover.
                "raw_provider_payload": raw.payload,
            }

        event_revision_fields: dict[str, str] = {}
        if raw.schema_version == "2":
            logical_event_id = _logical_event_id(raw, economic_revision_key)
            canonical_payload_digest = compute_checksum(
                {"event_type": event_type, "event_family": "commerce", "data": data}
            )
            event_revision_id = _event_revision_id(
                logical_event_id=logical_event_id,
                mapping_version=GRAPHQL_MAPPING_VERSION,
                normalizer_version=self.normalizer_version,
                canonical_payload_digest=canonical_payload_digest,
            )
            event_revision_fields = {
                "logical_event_id": logical_event_id,
                "event_revision_id": event_revision_id,
                "mapping_version": GRAPHQL_MAPPING_VERSION,
                "normalizer_version": self.normalizer_version,
                "source_revision_key": raw.source_revision_key or "",
                "canonical_payload_digest": canonical_payload_digest,
            }

        event = AetherEvent(
            event_id=event_revision_fields.get(
                "event_revision_id", f"{raw.record_id}:{event_type}"
            ),
            **event_revision_fields,
            event_type=event_type,
            event_family="commerce",
            tenant_id=raw.tenant_id,
            provider="shopify",
            provider_identity=raw.provider_identity,
            source_record_id=raw.record_id,
            occurred_at=raw.provider_occurred_at or raw.observed_at,
            observed_at=raw.observed_at,
            account_id=account_id,
            data=data,
            context=context,
            schema_version=EVENT_SCHEMA_VERSION if raw.schema_version == "2" else "1",
        )
        return NormalizationResult(
            events=[event],
            skipped=0,
            dropped=[],
            normalizer_version=self.normalizer_version,
        )


__all__ = [
    "NORMALIZER_VERSION",
    "ShopifyOrderNormalizer",
    "to_commerce_order",
]
