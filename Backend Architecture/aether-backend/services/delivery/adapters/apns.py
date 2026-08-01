"""APNs (Apple Push Notification service) delivery adapter — iOS push.

Sends to ``/3/device/{device_token}`` on the production or sandbox APNs host. The
``credential`` is the ready provider bearer JWT (deriving it from the ``.p8`` key is
a ``credentials-preflight`` concern, not a per-send one). Success is signalled by a
200 with an ``apns-id`` header, which becomes the receipt external_id.

Live sends are externally blocked in this session (no APNs credential/reachability);
without a credential the provider-shaped local fake stands in — and only in
local/dev (see ``_notification_base``).
"""
from __future__ import annotations

import json
from typing import Any, Optional

from services.delivery.adapters._notification_base import NotificationProviderAdapter
from services.delivery.adapters.base import AdapterReceipt, ProviderError

_PROD_HOST = "https://api.push.apple.com"
_SANDBOX_HOST = "https://api.sandbox.push.apple.com"


class APNsAdapter(NotificationProviderAdapter):
    """Delivers iOS pushes over the APNs HTTP/2 provider API."""

    adapter_name = "apns"
    credential_slot = "apns"

    def _recipient(self, provider_config: dict[str, Any]) -> str:
        return provider_config.get("device_token", "")

    def _fake_external_id(self) -> str:
        # APNs identifies a push by a UUID (the ``apns-id``).
        import uuid

        return str(uuid.uuid4())

    def _build_request(
        self,
        payload: dict[str, Any],
        provider_config: dict[str, Any],
        token: str,
        idempotency_key: Optional[str],
    ) -> tuple[str, str, dict[str, str], bytes]:
        device_token = provider_config["device_token"]
        host = _SANDBOX_HOST if provider_config.get("environment") == "sandbox" else _PROD_HOST
        topic = provider_config.get("topic") or provider_config.get("bundle_id", "")
        title, body = self._push_alert(payload, provider_config)
        aps: dict[str, Any] = {"alert": {"title": title, "body": body}}
        if provider_config.get("sound") is not False:
            aps["sound"] = "default"
        message = {"aps": aps}
        if payload.get("deep_link_id"):
            # Only an opaque id travels — never PII / graph.
            message["deep_link_id"] = payload["deep_link_id"]
        headers = {
            "authorization": f"bearer {token}",
            "apns-topic": topic,
            "apns-push-type": provider_config.get("push_type", "alert"),
            "apns-priority": str(provider_config.get("priority", 10)),
            "content-type": "application/json",
        }
        if idempotency_key:
            headers["apns-collapse-id"] = idempotency_key[:64]
        url = f"{host}/3/device/{device_token}"
        return "POST", url, headers, json.dumps(message).encode("utf-8")

    def _map_success(
        self,
        status: int,
        data: dict[str, Any],
        provider_config: dict[str, Any],
        idempotency_key: Optional[str],
    ) -> AdapterReceipt:
        apns_id = data.get("_headers", {}).get("apns-id")
        if not apns_id:
            raise ProviderError(
                "APNs response missing apns-id — cannot confirm acceptance",
                http_status=status,
            )
        return AdapterReceipt(
            external_id=f"apns:{apns_id}",
            raw_response={k: v for k, v in data.items() if k != "_headers"},
            http_status=status,
        )
