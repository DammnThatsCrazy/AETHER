"""Shopify inbound webhook verification and payload parsing (:class:`WebhookAdapter`).

Verification is deterministic and constant-time: ``base64(HMAC-SHA256(secret,
raw_body)) == X-Shopify-Hmac-SHA256``, compared via
``actions.delivery.security.constant_time_compare``. The HMAC is computed over
the RAW request body bytes — never over a re-serialized dict. If ``secret`` is
None/empty the adapter returns ``False`` (does NOT auto-verify); the runtime's
endpoint-secret policy handles secret-less providers separately.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from typing import Any, Mapping, Optional

from shared.integration_contracts.events import (
    RawProviderRecord,
    compute_checksum,
    make_raw_record,
)

from connectors.providers.shopify.auth import _validated_shop_domain
from connectors.providers.shopify.payloads import ShopifyWebhookEnvelope

SHOPIFY_ORDER_WEBHOOK_TOPICS = (
    "orders/create",
    "orders/update",
    "orders/cancelled",
)
_SHOPIFY_ORDER_WEBHOOK_TOPIC_SET = frozenset(SHOPIFY_ORDER_WEBHOOK_TOPICS)


class ShopifyWebhookAdapter:
    """WebhookAdapter: constant-time HMAC verify + envelope -> order record."""

    def __init__(self, *, provider_identity: str) -> None:
        self.provider_identity = provider_identity

    def verify(self, raw_body: bytes, headers: Mapping[str, str], secret: Optional[str]) -> bool:
        """Deterministic constant-time HMAC verification over the raw body."""
        if not secret:
            return False
        signature = (
            headers.get("X-Shopify-Hmac-SHA256") or headers.get("x-shopify-hmac-sha256") or ""
        )
        if not signature:
            return False
        expected = base64.b64encode(
            hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
        ).decode("utf-8")
        from actions.delivery.security import constant_time_compare

        return constant_time_compare(expected, signature)

    @staticmethod
    def shop_domain_from_payload(
        payload: dict[str, Any], *, headers: Mapping[str, str] | None = None
    ) -> str:
        """Return the validated shop domain carried by the signed body.

        The body domain is the routing candidate. The optional Shopify domain
        header is only a consistency check and can never select a connection.
        """
        domain = _validated_shop_domain(str(payload.get("domain") or ""))
        if not domain:
            raise ValueError("missing or invalid Shopify shop domain")
        header_domains = {
            value.strip()
            for key, value in (headers or {}).items()
            if key.lower() == "x-shopify-shop-domain" and isinstance(value, str) and value.strip()
        }
        if len(header_domains) > 1:
            raise ValueError("conflicting Shopify shop domain headers")
        if header_domains:
            header_domain = _validated_shop_domain(next(iter(header_domains)))
            if not header_domain or header_domain != domain:
                raise ValueError("Shopify shop domain does not match its signed body")
        return domain

    def parse(
        self, payload: dict[str, Any], *, headers: Mapping[str, str]
    ) -> list[RawProviderRecord]:
        """Extract the order payload and emit ONE webhook-sourced raw record."""
        shop_domain = self.shop_domain_from_payload(payload, headers=headers)
        envelope = ShopifyWebhookEnvelope.from_api_dict(payload)
        delivery_ids = {
            value.strip()
            for key, value in headers.items()
            if key.lower() == "x-shopify-webhook-id" and isinstance(value, str) and value.strip()
        }
        if len(delivery_ids) > 1:
            raise ValueError("conflicting Shopify webhook delivery IDs")
        delivery_id = next(iter(delivery_ids), None)
        if not delivery_id:
            raise ValueError("missing Shopify webhook delivery ID")
        if len(delivery_id) > 255:
            raise ValueError("Shopify webhook delivery ID is too long")
        header_topics = {
            value.strip()
            for key, value in headers.items()
            if key.lower() == "x-shopify-topic" and isinstance(value, str) and value.strip()
        }
        if len(header_topics) > 1:
            raise ValueError("conflicting Shopify webhook topic headers")
        header_topic = next(iter(header_topics), None)
        envelope_topic = envelope.topic.strip() or None
        if header_topic and envelope_topic and header_topic != envelope_topic:
            raise ValueError("Shopify webhook topic does not match its envelope")
        topic = header_topic or envelope_topic
        if topic not in _SHOPIFY_ORDER_WEBHOOK_TOPIC_SET:
            raise ValueError("unsupported Shopify order webhook topic")

        order_dict: dict[str, Any] = dict(envelope.body) if isinstance(envelope.body, dict) else {}
        if not order_dict:
            # No nested body: project the envelope's own fields as the order,
            # keyed by the envelope's order_id (the actual order) when present.
            # Preserve provider fields outside the narrow envelope model too:
            # Shopify's actual webhook body is a bare order object and includes
            # customer evidence not represented by the envelope schema.
            order_dict = {
                key: value
                for key, value in payload.items()
                if key not in {"topic", "domain", "body", "order_id", "id"}
            }
            order_dict["id"] = envelope.order_id if envelope.order_id is not None else envelope.id
        order_id = str(order_dict.get("id") or "").strip()
        if not order_id:
            raise ValueError("missing Shopify order ID")
        payload_digest = compute_checksum(order_dict)
        delivery_record_id = "shopify-webhook-delivery-v1:" + compute_checksum(
            {
                "contract": "shopify-webhook-delivery-v1",
                "shop_domain": shop_domain,
                "order_id": order_id,
                "delivery_id": delivery_id,
                "payload_digest": payload_digest,
            }
        )
        record = make_raw_record(
            provider_identity=self.provider_identity,
            # Raw Bronze deduplicates provider_record_id + envelope version.
            # Include the stable Shopify delivery ID and signed body revision
            # so retries converge while later order updates remain distinct.
            # The native order ID stays in payload and metadata.
            provider_record_id=delivery_record_id,
            provider_record_type="order",
            stream_id="orders_webhook",
            provider_occurred_at=order_dict.get("updated_at") or order_dict.get("created_at"),
            payload=order_dict,
            acquisition_mode="webhook",
            webhook_delivery_id=delivery_id,
            metadata={
                "shopify_webhook_topic": topic,
                "shopify_shop_domain": shop_domain,
                "shopify_order_id": order_id,
                "shopify_delivery_id": delivery_id,
                "shopify_payload_digest": payload_digest,
            },
        )
        return [record]


__all__ = ["SHOPIFY_ORDER_WEBHOOK_TOPICS", "ShopifyWebhookAdapter"]
