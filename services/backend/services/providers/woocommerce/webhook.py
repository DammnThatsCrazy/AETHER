"""WooCommerce inbound webhook verification and payload parsing (:class:`WebhookAdapter`).

The declared scheme is ``wc_hmac``: the ``X-WC-Webhook-Signature`` header carries
``sha256=<hex>`` where ``<hex>`` is the hex-encoded HMAC-SHA256 of the RAW
request body keyed by the webhook secret. Verification is deterministic and
constant-time (:func:`services.delivery.security.constant_time_compare`), and
the HMAC is computed over the RAW request body bytes — never over a
re-serialized dict. If ``secret`` is None/empty the adapter returns ``False``
(does NOT auto-verify); the runtime's endpoint-secret policy handles secret-less
providers separately.

WooCommerce delivers webhook payloads as the bare order JSON, so :meth:`parse`
treats the payload dict as the order itself (one webhook-sourced raw record).
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any, Mapping, Optional

from shared.integration_contracts.events import RawProviderRecord, make_raw_record

from services.providers.woocommerce.payloads import WooCommerceOrder


class WooCommerceWebhookAdapter:
    """WebhookAdapter: constant-time HMAC verify + order payload -> one record."""

    def __init__(self, *, provider_identity: str) -> None:
        self.provider_identity = provider_identity

    def verify(
        self, raw_body: bytes, headers: Mapping[str, str], secret: Optional[str]
    ) -> bool:
        """Deterministic constant-time ``wc_hmac`` verification over the raw body.

        Only the canonical ``sha256=<hex>`` form (WooCommerce's signature header
        format) is accepted; any other form — including a bare hex digest — fails
        closed.
        """
        if not secret:
            return False
        signature = (
            headers.get("X-WC-Webhook-Signature")
            or headers.get("x-wc-webhook-signature")
            or ""
        )
        if not signature:
            return False
        prefix, sep, hex_digest = signature.partition("=")
        if not sep or not hex_digest or prefix.lower() != "sha256":
            return False
        expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        from services.delivery.security import constant_time_compare

        return constant_time_compare(expected, hex_digest.lower())

    def parse(
        self, payload: dict[str, Any], *, headers: Mapping[str, str]
    ) -> list[RawProviderRecord]:
        """Emit ONE webhook-sourced order record from the bare order payload."""
        order = WooCommerceOrder.from_api_dict(payload)
        record = make_raw_record(
            provider_identity=self.provider_identity,
            provider_record_id=str(order.id),
            provider_record_type="order",
            provider_occurred_at=order.date_modified or order.date_created,
            payload=dict(payload),
            acquisition_mode="webhook",
        )
        return [record]


__all__ = ["WooCommerceWebhookAdapter"]
