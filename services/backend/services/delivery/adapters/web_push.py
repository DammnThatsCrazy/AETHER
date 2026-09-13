"""Web Push (VAPID) delivery adapter — browser / PWA push.

POSTs the (pre-encrypted) payload to the subscription ``endpoint`` with a VAPID
``Authorization`` header. The ``credential`` is the ready VAPID auth token
(``vapid t=<jwt>, k=<pubkey>``); building it from the P-256 keypair is a
``credentials-preflight`` concern. A push service returns 201 with a ``location``
header identifying the message, which becomes the receipt external_id.

Live sends are externally blocked in this session; without a credential the
provider-shaped local fake stands in — and only in local/dev.
"""
from __future__ import annotations

from typing import Any, Optional

from services.delivery.adapters._notification_base import NotificationProviderAdapter
from services.delivery.adapters.base import AdapterReceipt


class WebPushAdapter(NotificationProviderAdapter):
    """Delivers browser pushes to a Web Push subscription endpoint (RFC 8030)."""

    adapter_name = "web_push"
    credential_slot = "web_push_vapid"

    def _recipient(self, provider_config: dict[str, Any]) -> str:
        return provider_config.get("endpoint", "")

    def _build_request(
        self,
        payload: dict[str, Any],
        provider_config: dict[str, Any],
        token: str,
        idempotency_key: Optional[str],
    ) -> tuple[str, str, dict[str, str], bytes]:
        endpoint = provider_config["endpoint"]
        # The body is the caller-supplied aes128gcm ciphertext (encryption happens
        # upstream with the client keys) — never plaintext PII.
        body = provider_config.get("encrypted_body", b"")
        if isinstance(body, str):
            body = body.encode("utf-8")
        headers = {
            "authorization": token,
            "ttl": str(provider_config.get("ttl", 2419200)),
            "content-encoding": "aes128gcm",
            "content-type": "application/octet-stream",
        }
        urgency = provider_config.get("urgency")
        if urgency:
            headers["urgency"] = urgency
        return "POST", endpoint, headers, body

    def _map_success(
        self,
        status: int,
        data: dict[str, Any],
        provider_config: dict[str, Any],
        idempotency_key: Optional[str],
    ) -> AdapterReceipt:
        location = data.get("_headers", {}).get("location")
        # RFC 8030 push message id lives in Location; fall back to a stable digest of
        # the endpoint so a 201 without Location is still a real, non-simulated id.
        if location:
            external_id = f"webpush:{location}"
        else:
            import hashlib

            digest = hashlib.sha256(provider_config["endpoint"].encode()).hexdigest()[:16]
            external_id = f"webpush:accepted:{digest}"
        return AdapterReceipt(
            external_id=external_id,
            raw_response={k: v for k, v in data.items() if k != "_headers"},
            http_status=status,
        )
