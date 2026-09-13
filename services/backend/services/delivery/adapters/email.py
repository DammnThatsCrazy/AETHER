"""Email delivery adapter — transactional email via AWS SES (SMTP fallback).

Maps to ``DeliveryChannel.EMAIL``. Uses the SES ``SendEmail`` action over HTTPS; a
verified sender domain and IAM/SMTP secret are ``credentials-preflight`` concerns.
SES returns a ``MessageId`` which becomes the receipt external_id. Unlike the push
adapters, email may carry full content (it is the channel for it).

Live sends are externally blocked in this session; without a credential the
provider-shaped local fake stands in — and only in local/dev.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional
from urllib.parse import urlencode

from services.delivery.adapters._notification_base import NotificationProviderAdapter
from services.delivery.adapters.base import AdapterReceipt, ConfigurationError, ProviderError

_SES_ENDPOINT = "https://email.{region}.amazonaws.com/"


class EmailAdapter(NotificationProviderAdapter):
    """Delivers transactional email over AWS SES."""

    adapter_name = "email"
    credential_slot = "email"

    def _recipient(self, provider_config: dict[str, Any]) -> str:
        return provider_config.get("to", "")

    def _fake_external_id(self) -> str:
        return f"email-local-{uuid.uuid4().hex}@fake.local"

    def _build_request(
        self,
        payload: dict[str, Any],
        provider_config: dict[str, Any],
        token: str,
        idempotency_key: Optional[str],
    ) -> tuple[str, str, dict[str, str], bytes]:
        sender = provider_config.get("sender")
        if not sender:
            raise ConfigurationError("email: provider_config missing verified sender")
        region = provider_config.get("region", "us-east-1")
        subject = payload.get("title", "Aether Notification")
        body = payload.get("body") or payload.get("summary", "")
        form = {
            "Action": "SendEmail",
            "Source": sender,
            "Destination.ToAddresses.member.1": provider_config["to"],
            "Message.Subject.Data": subject,
            "Message.Body.Text.Data": body,
        }
        headers = {
            # SES SigV4 signing is applied by the transport from the resolved IAM
            # credential; the ready authorization travels in the credential.
            "authorization": token,
            "content-type": "application/x-www-form-urlencoded",
        }
        url = _SES_ENDPOINT.format(region=region)
        return "POST", url, headers, urlencode(form).encode("utf-8")

    def _map_success(
        self,
        status: int,
        data: dict[str, Any],
        provider_config: dict[str, Any],
        idempotency_key: Optional[str],
    ) -> AdapterReceipt:
        # SES XML → the transport is expected to surface MessageId in the dict.
        message_id = data.get("MessageId") or data.get("message_id")
        if not message_id:
            raise ProviderError(
                "SES response missing MessageId — cannot confirm acceptance",
                http_status=status,
            )
        return AdapterReceipt(
            external_id=f"ses:{message_id}",
            raw_response={k: v for k, v in data.items() if k != "_headers"},
            http_status=status,
        )
