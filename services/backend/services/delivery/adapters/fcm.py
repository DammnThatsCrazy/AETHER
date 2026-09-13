"""FCM (Firebase Cloud Messaging) delivery adapter — Android push.

Sends via the FCM HTTP v1 API
(``/v1/projects/{project_id}/messages:send``). The ``credential`` is the ready
OAuth2 bearer access token (minting it from the service-account JSON is a
``credentials-preflight`` concern). Success returns ``{"name":
"projects/{project}/messages/{id}"}``, which becomes the receipt external_id.

Live sends are externally blocked in this session; without a credential the
provider-shaped local fake stands in — and only in local/dev.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Optional

from services.delivery.adapters._notification_base import NotificationProviderAdapter
from services.delivery.adapters.base import AdapterReceipt, ConfigurationError, ProviderError

_FCM_SEND = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"


class FCMAdapter(NotificationProviderAdapter):
    """Delivers Android pushes over the FCM HTTP v1 API."""

    adapter_name = "fcm"
    credential_slot = "fcm"

    def _recipient(self, provider_config: dict[str, Any]) -> str:
        return provider_config.get("registration_token", "")

    def _fake_external_id(self) -> str:
        project = "local"
        return f"projects/{project}/messages/{uuid.uuid4().hex}"

    def _build_request(
        self,
        payload: dict[str, Any],
        provider_config: dict[str, Any],
        token: str,
        idempotency_key: Optional[str],
    ) -> tuple[str, str, dict[str, str], bytes]:
        project_id = provider_config.get("project_id")
        if not project_id:
            raise ConfigurationError("fcm: provider_config missing project_id")
        # M1a (decision-log D11): the push carries ONLY the redacted projection.
        projection = self._push_projection(payload, provider_config)
        title = projection.push_title or "Aether notification"
        body = projection.push_body or projection.push_summary or "You have a new update."
        message: dict[str, Any] = {
            "token": provider_config["registration_token"],
            "notification": {"title": title, "body": body},
        }
        data: dict[str, Any] = {
            # Redacted projection routing fields — the mobile app routes on the
            # continuation-plane deep-link class + category; never raw payload.
            "push_summary": projection.push_summary or "",
            "push_deep_link_class": projection.push_deep_link_class,
            "push_category": projection.push_category,
        }
        if payload.get("deep_link_id"):
            # Only an opaque id travels — never PII / graph.
            data["deep_link_id"] = str(payload["deep_link_id"])
        message["data"] = data
        headers = {
            "authorization": f"Bearer {token}",
            "content-type": "application/json",
        }
        url = _FCM_SEND.format(project_id=project_id)
        return "POST", url, headers, json.dumps({"message": message}).encode("utf-8")

    def _map_success(
        self,
        status: int,
        data: dict[str, Any],
        provider_config: dict[str, Any],
        idempotency_key: Optional[str],
    ) -> AdapterReceipt:
        name = data.get("name")
        if not name:
            raise ProviderError(
                "FCM response missing message name — cannot confirm acceptance",
                http_status=status,
            )
        return AdapterReceipt(
            external_id=name,
            raw_response={k: v for k, v in data.items() if k != "_headers"},
            http_status=status,
        )
