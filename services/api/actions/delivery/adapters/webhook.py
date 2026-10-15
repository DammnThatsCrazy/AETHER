"""Outbound webhook adapter — SSRF-protected with HMAC signing.

Only reaches public internet addresses: the URL is resolved and checked
before connecting, and the connection is pinned to the validated address.
Signs payloads with HMAC-SHA256 via the `X-Aether-Signature` header.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from typing import Any, Optional

from shared.logger.logger import get_logger
from shared.security.ssrf import UnsafeDestinationError, resolve_public_addresses, send_public_request

from actions.delivery.adapters.base import (
    AdapterReceipt,
    ConfigurationError,
    ProviderAdapter,
    ProviderError,
    RetryableProviderError,
    SSRFBlockedError,
)

logger = get_logger("aether.delivery.adapters.webhook")


def _check_ssrf(url: str) -> None:
    """Raise SSRFBlockedError unless every address the URL resolves to is public."""
    try:
        resolve_public_addresses(url)
    except UnsafeDestinationError as exc:
        raise SSRFBlockedError(str(exc)) from exc


def _sign_payload(secret: str, body: bytes, timestamp: str) -> str:
    """Compute HMAC-SHA256 signature for outbound webhook."""
    base = f"{timestamp}.{body.decode('utf-8', errors='replace')}"
    return hmac.new(secret.encode(), base.encode(), hashlib.sha256).hexdigest()


class WebhookAdapter(ProviderAdapter):
    """Delivers a JSON payload to an arbitrary HTTPS endpoint."""

    adapter_name = "webhook"

    async def dispatch(
        self,
        payload: dict[str, Any],
        provider_config: dict[str, Any],
        *,
        credential: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> AdapterReceipt:
        # URL may be in provider_config OR in credential (vault-backed channels)
        url = provider_config.get("url") or provider_config.get("webhook_url") or credential
        if not url:
            raise ConfigurationError("WebhookAdapter requires provider_config.url or a vault-backed URL credential")
        if not url.startswith("https://"):
            raise ConfigurationError(
                f"WebhookAdapter only supports HTTPS URLs, got: {url!r}"
            )

        body_bytes = json.dumps(payload).encode("utf-8")
        from datetime import datetime, timezone
        timestamp = datetime.now(timezone.utc).isoformat()
        delivery_id = idempotency_key or str(uuid.uuid4())

        headers: dict[str, str] = {
            "Content-Type": "application/json; charset=utf-8",
            "X-Aether-Delivery-Id": delivery_id,
            "X-Aether-Timestamp": timestamp,
        }
        if credential:
            sig = _sign_payload(credential, body_bytes, timestamp)
            headers["X-Aether-Signature"] = f"sha256={sig}"

        # Allow caller to inject extra headers
        extra_headers = provider_config.get("headers") or {}
        headers.update(extra_headers)

        try:
            resp = await send_public_request(
                "POST", url, headers=headers, content=body_bytes, timeout=20.0, max_redirects=0
            )
        except UnsafeDestinationError as exc:
            raise SSRFBlockedError(str(exc)) from exc

        status = resp.status_code
        resp_body = resp.text

        raw_response: dict[str, Any] = {
            "http_status": status,
            "body": resp_body[:2000],
            "delivery_id": delivery_id,
        }

        if status == 429:
            retry_after = int(resp.headers.get("Retry-After", "60"))
            raise RetryableProviderError(
                f"Webhook rate-limited: HTTP 429",
                http_status=429,
                retry_after_seconds=retry_after,
            )
        if status >= 500:
            raise RetryableProviderError(
                f"Webhook server error: HTTP {status}",
                http_status=status,
            )
        if status >= 400:
            raise ProviderError(
                f"Webhook client error: HTTP {status} — {resp_body[:500]}",
                http_status=status,
            )

        logger.info(f"Webhook delivered: url={url!r} status={status} delivery_id={delivery_id!r}")
        return AdapterReceipt(
            external_id=delivery_id,
            raw_response=raw_response,
            http_status=status,
        )
