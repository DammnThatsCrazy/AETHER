"""TikTok Shop inbound webhook verification and payload parsing (:class:`WebhookAdapter`).

The declared scheme is ``tiktok_hmac``: the request is verified as
``hex(HMAC-SHA256(app_secret, raw_body))`` against the ``X-Tiktok-Shop-Sign``
header. Verification is deterministic and constant-time
(:func:`services.delivery.security.constant_time_compare`), and the HMAC is
computed over the RAW request body bytes — never over a re-serialized dict. If
``secret`` is None/empty the adapter returns ``False`` (does NOT auto-verify);
the runtime's endpoint-secret policy handles secret-less providers separately.

TikTok Shop delivers webhook payloads as an order object (possibly nested under
a ``data`` envelope), so :meth:`parse` unwraps the order and emits ONE
webhook-sourced raw record. The normalizer carries a full status map, so any
unmappable order status surfaces as a visible drop — never silent.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any, Mapping, Optional

from shared.integration_contracts.events import RawProviderRecord, make_raw_record

from services.providers.tiktok.payloads import TikTokOrder


def _unwrap_order(payload: dict[str, Any]) -> dict[str, Any]:
    """Unwrap a TikTok webhook order payload (nested ``data`` envelope support)."""
    if "order" in payload and isinstance(payload["order"], dict):
        return payload["order"]
    if "data" in payload and isinstance(payload["data"], dict):
        data = payload["data"]
        if "order" in data and isinstance(data["order"], dict):
            return data["order"]
        if "order_id" in data or "order_status" in data:
            return data
    return payload


class TikTokWebhookAdapter:
    """WebhookAdapter: constant-time HMAC verify + order payload -> one record."""

    def __init__(self, *, provider_identity: str) -> None:
        self.provider_identity = provider_identity

    def verify(
        self, raw_body: bytes, headers: Mapping[str, str], secret: Optional[str]
    ) -> bool:
        """Deterministic constant-time ``tiktok_hmac`` verification over the raw body."""
        if not secret:
            return False
        signature = (
            headers.get("X-Tiktok-Shop-Sign")
            or headers.get("x-tiktok-shop-sign")
            or ""
        )
        if not signature:
            return False
        expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        from services.delivery.security import constant_time_compare

        return constant_time_compare(expected, signature.lower())

    def parse(
        self, payload: dict[str, Any], *, headers: Mapping[str, str]
    ) -> list[RawProviderRecord]:
        """Emit ONE webhook-sourced order record from the unwrapped order payload."""
        order_dict = _unwrap_order(payload)
        order = TikTokOrder.from_api_dict(order_dict)
        record = make_raw_record(
            provider_identity=self.provider_identity,
            provider_record_id=str(order.order_id),
            provider_record_type="order",
            provider_occurred_at=str(order.update_time or order.create_time or ""),
            payload=dict(order_dict),
            acquisition_mode="webhook",
        )
        return [record]


__all__ = ["TikTokWebhookAdapter", "_unwrap_order"]
