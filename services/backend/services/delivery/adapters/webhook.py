"""Outbound webhook adapter — SSRF-protected with HMAC signing.

Blocks requests to private/loopback IP ranges before connecting.
Signs payloads with HMAC-SHA256 via the `X-Aether-Signature` header.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import socket
import uuid
from typing import Any, Optional
from urllib.parse import urlparse

from shared.logger.logger import get_logger

from services.delivery.adapters.base import (
    AdapterReceipt,
    ConfigurationError,
    ProviderAdapter,
    ProviderError,
    RetryableProviderError,
    SSRFBlockedError,
)

logger = get_logger("aether.delivery.adapters.webhook")

# Private / loopback / link-local ranges that must never be reachable
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),     # loopback
    ipaddress.ip_network("10.0.0.0/8"),       # RFC 1918
    ipaddress.ip_network("172.16.0.0/12"),    # RFC 1918
    ipaddress.ip_network("192.168.0.0/16"),   # RFC 1918
    ipaddress.ip_network("169.254.0.0/16"),   # link-local
    ipaddress.ip_network("::1/128"),           # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),          # IPv6 ULA
    ipaddress.ip_network("fe80::/10"),         # IPv6 link-local
    ipaddress.ip_network("0.0.0.0/8"),         # unspecified
]


def _check_ssrf(url: str) -> None:
    """Resolve the URL's hostname and raise SSRFBlockedError if it maps to a private range."""
    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        raise SSRFBlockedError(f"Cannot parse hostname from URL: {url!r}")
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise SSRFBlockedError(f"DNS resolution failed for {hostname!r}: {exc}")

    for info in infos:
        addr_str = info[4][0]
        try:
            addr = ipaddress.ip_address(addr_str)
        except ValueError:
            continue
        for network in _BLOCKED_NETWORKS:
            if addr in network:
                raise SSRFBlockedError(
                    f"Webhook URL {url!r} resolves to blocked address {addr_str!r} "
                    f"(matches {network}). SSRF protection active."
                )


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

        # SSRF protection — blocks private/loopback destinations
        _check_ssrf(url)

        try:
            import aiohttp
        except ImportError:
            raise ConfigurationError("aiohttp is required for WebhookAdapter: pip install aiohttp")

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

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                headers=headers,
                data=body_bytes,
                timeout=aiohttp.ClientTimeout(total=20),
                ssl=True,
                allow_redirects=False,
            ) as resp:
                status = resp.status
                try:
                    resp_body = await resp.text()
                except Exception:
                    resp_body = ""

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
