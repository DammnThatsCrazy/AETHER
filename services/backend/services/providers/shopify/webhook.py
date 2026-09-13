"""Shopify inbound webhook verification and payload parsing (:class:`WebhookAdapter`).

Verification is deterministic and constant-time: ``base64(HMAC-SHA256(secret,
raw_body)) == X-Shopify-Hmac-SHA256``, compared via
``services.delivery.security.constant_time_compare``. The HMAC is computed over
the RAW request body bytes — never over a re-serialized dict. If ``secret`` is
None/empty the adapter returns ``False`` (does NOT auto-verify); the runtime's
endpoint-secret policy handles secret-less providers separately.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from typing import Any, Mapping, Optional

from shared.integration_contracts.events import RawProviderRecord, make_raw_record

from services.providers.shopify.payloads import ShopifyWebhookEnvelope


class ShopifyWebhookAdapter:
    """WebhookAdapter: constant-time HMAC verify + envelope -> order record."""

    def __init__(self, *, provider_identity: str) -> None:
        self.provider_identity = provider_identity

    def verify(
        self, raw_body: bytes, headers: Mapping[str, str], secret: Optional[str]
    ) -> bool:
        """Deterministic constant-time HMAC verification over the raw body."""
        if not secret:
            return False
        signature = (
            headers.get("X-Shopify-Hmac-SHA256")
            or headers.get("x-shopify-hmac-sha256")
            or ""
        )
        if not signature:
            return False
        expected = base64.b64encode(
            hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
        ).decode("utf-8")
        from services.delivery.security import constant_time_compare

        return constant_time_compare(expected, signature)

    def parse(
        self, payload: dict[str, Any], *, headers: Mapping[str, str]
    ) -> list[RawProviderRecord]:
        """Extract the order payload and emit ONE webhook-sourced raw record."""
        envelope = ShopifyWebhookEnvelope.from_api_dict(payload)
        order_dict: dict[str, Any] = (
            dict(envelope.body) if isinstance(envelope.body, dict) else {}
        )
        if not order_dict:
            # No nested body: project the envelope's own fields as the order,
            # keyed by the envelope's order_id (the actual order) when present.
            order_dict = {
                key: value
                for key, value in envelope.model_dump().items()
                if key not in {"topic", "domain", "body", "order_id", "id"}
            }
            order_dict["id"] = envelope.order_id if envelope.order_id is not None else envelope.id
        record = make_raw_record(
            provider_identity=self.provider_identity,
            provider_record_id=str(order_dict.get("id", envelope.id)),
            provider_record_type="order",
            provider_occurred_at=order_dict.get("updated_at") or order_dict.get("created_at"),
            payload=order_dict,
            acquisition_mode="webhook",
            webhook_delivery_id=str(envelope.id),
        )
        return [record]


__all__ = ["ShopifyWebhookAdapter"]
