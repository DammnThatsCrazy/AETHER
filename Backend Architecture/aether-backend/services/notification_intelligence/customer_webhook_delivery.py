"""Hardened customer webhook delivery primitives.

This module is intentionally independent of the route layer.  It owns the
security policy for customer-controlled destinations and records every
attempt in the existing durable delivery-attempt store.  Secret material is
resolved by the caller from the provider vault and is never part of a
webhook configuration response or an attempt record.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import os
import secrets
import socket
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import urlparse

from shared.logger.logger import get_logger
from repositories.delivery_repos import DeliveryAttemptRepository

logger = get_logger("aether.notification.customer_webhook_delivery")

REPLAY_WINDOW_SECONDS = 300
CONNECT_TIMEOUT_SECONDS = 3.0
TOTAL_TIMEOUT_SECONDS = 15.0
MAX_REDIRECTS = 0
MAX_RESPONSE_BYTES = 64 * 1024
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (0.0, 1.0, 2.0)

_LOCAL_HOSTS = frozenset({"localhost", "localhost.localdomain", "127.0.0.1", "::1"})
_BLOCKED_NETWORKS = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)


class WebhookPolicyError(ValueError):
    """A destination or delivery policy rejected the request."""


class ProviderUnavailableError(RuntimeError):
    """The configured HTTP or credential provider cannot service delivery."""


@dataclass(frozen=True)
class ResolvedDestination:
    url: str
    hostname: str
    port: int
    addresses: tuple[str, ...]


@dataclass(frozen=True)
class WebhookDeliveryOutcome:
    status: str
    success: bool
    webhook_id: str
    tenant_id: str
    idempotency_key: str
    attempts: int
    status_code: Optional[int] = None
    latency_ms: Optional[float] = None
    error: Optional[str] = None
    attempt_id: Optional[str] = None


def _is_local_development() -> bool:
    return os.getenv("AETHER_ENV", "local").lower() == "local"


def _is_blocked(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return any(ip in network for network in _BLOCKED_NETWORKS) or ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified


def resolve_safe_destination(url: str) -> ResolvedDestination:
    """Validate scheme and resolve every address before an outbound connect."""
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not hostname or parsed.username or parsed.password or parsed.fragment:
        raise WebhookPolicyError("webhook destination is malformed")

    local_dev = _is_local_development() and hostname in _LOCAL_HOSTS
    if parsed.scheme != "https" and not local_dev:
        raise WebhookPolicyError("webhook destination must use HTTPS")
    if parsed.scheme not in {"https", "http"}:
        raise WebhookPolicyError("webhook destination scheme is unsupported")

    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise WebhookPolicyError("webhook destination port is invalid") from exc

    try:
        infos = socket.getaddrinfo(
            hostname,
            port,
            type=socket.SOCK_STREAM,
        )
    except (OSError, socket.gaierror) as exc:
        raise WebhookPolicyError("webhook destination DNS resolution failed") from exc
    addresses = tuple(dict.fromkeys(info[4][0] for info in infos if info[4]))
    if not addresses:
        raise WebhookPolicyError("webhook destination has no resolved address")
    if not local_dev and any(_is_blocked(address) for address in addresses):
        raise WebhookPolicyError("webhook destination resolves to a blocked network")
    if local_dev and any(not _is_blocked(address) for address in addresses):
        raise WebhookPolicyError("local webhook destination resolved outside the local host")
    return ResolvedDestination(url=url, hostname=hostname, port=port, addresses=addresses)


def make_idempotency_key(tenant_id: str, webhook_id: str, event_id: str, kind: str = "production") -> str:
    """Return a stable tenant- and endpoint-scoped delivery key."""
    raw = f"{tenant_id}:{webhook_id}:{kind}:{event_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def sign_payload(secret: str, body: bytes, timestamp: str) -> str:
    """Sign ``timestamp.body`` using the customer webhook secret."""
    digest = hmac.new(secret.encode("utf-8"), timestamp.encode("ascii") + b"." + body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify_signature(
    secret: str,
    body: bytes,
    timestamp: str,
    signature: str,
    *,
    now: Optional[float] = None,
    replay_window_seconds: int = REPLAY_WINDOW_SECONDS,
) -> bool:
    """Verify timestamp freshness and the signed body in constant time."""
    try:
        timestamp_value = int(timestamp)
    except (TypeError, ValueError):
        return False
    current = time.time() if now is None else now
    if abs(current - timestamp_value) > replay_window_seconds:
        return False
    expected = sign_payload(secret, body, timestamp)
    return hmac.compare_digest(expected, signature)


def redact_webhook_record(record: dict[str, Any]) -> dict[str, Any]:
    """Return a response-safe copy with all secret material removed."""
    redacted = dict(record)
    for key in (
        "secret",
        "signing_secret",
        "token",
        "api_key",
        "credentials_ref",
        "secret_ref",
        "secret_hash",
    ):
        redacted.pop(key, None)
    if "secret_configured" not in redacted:
        redacted["secret_configured"] = bool(
            record.get("secret_ref") or record.get("credentials_ref") or record.get("secret")
        )
    return redacted


def secret_fingerprint(secret: str) -> str:
    """Create a non-reversible diagnostic fingerprint for a write-only secret."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


class CustomerWebhookDeliveryRepository(DeliveryAttemptRepository):
    """Durable tenant-scoped records for customer webhook attempts."""

    async def find_for_webhook(self, tenant_id: str, webhook_id: str, limit: int = 100) -> list[dict[str, Any]]:
        return await self.find_many(
            filters={"tenant_id": tenant_id, "webhook_id": webhook_id},
            limit=limit,
            sort_by="created_at",
            sort_order="desc",
        )

    async def find_by_idempotency_key(self, tenant_id: str, webhook_id: str, key: str) -> Optional[dict[str, Any]]:
        rows = await self.find_many(
            filters={"tenant_id": tenant_id, "webhook_id": webhook_id, "idempotency_key": key},
            limit=20,
            sort_by="created_at",
            sort_order="desc",
        )
        return rows[0] if rows else None


class CustomerWebhookSecretStore:
    """Write-only customer secret facade over the existing provider vault."""

    def __init__(self, provider_repository: Any) -> None:
        self._provider_repository = provider_repository

    async def store(self, tenant_id: str, webhook_id: str, secret: Optional[str] = None) -> dict[str, Any]:
        value = secret or secrets.token_urlsafe(32)
        secret_ref = f"customer_webhook:{tenant_id}:{webhook_id}"
        await self._provider_repository.upsert(secret_ref, {
            "api_key": value,
            "provider": "customer_webhook",
            "tenant_id": tenant_id,
        })
        return {
            "secret_ref": secret_ref,
            "secret_hash": secret_fingerprint(value),
            "secret_configured": True,
            # The caller may return this only in the create response. It is
            # never persisted in the webhook record or included in reads.
            "secret": value,
        }

    async def resolve(self, tenant_id: str, secret_ref: str) -> str:
        record = await self._provider_repository.find_by_id(secret_ref)
        if not record or record.get("tenant_id") != tenant_id:
            raise ProviderUnavailableError("webhook signing secret unavailable")
        value = str(record.get("api_key", ""))
        if not value:
            raise ProviderUnavailableError("webhook signing secret unavailable")
        return value


class CustomerWebhookDeliveryService:
    """Deterministic, bounded, durable customer webhook dispatcher."""

    def __init__(
        self,
        *,
        attempts: Optional[CustomerWebhookDeliveryRepository] = None,
        http_client_factory: Optional[Callable[..., Any]] = None,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
        now: Callable[[], float] = time.time,
    ) -> None:
        self.attempts = attempts or CustomerWebhookDeliveryRepository()
        self._http_client_factory = http_client_factory
        self._sleeper = sleeper
        self._now = now

    async def deliver(
        self,
        *,
        tenant_id: str,
        webhook_id: str,
        url: str,
        payload: dict[str, Any],
        secret: str,
        event_id: str,
        kind: str = "production",
    ) -> WebhookDeliveryOutcome:
        return await self._dispatch(
            tenant_id=tenant_id,
            webhook_id=webhook_id,
            url=url,
            payload=payload,
            secret=secret,
            idempotency_key=make_idempotency_key(tenant_id, webhook_id, event_id, kind),
        )

    async def test(
        self,
        *,
        tenant_id: str,
        webhook_id: str,
        url: str,
        secret: str,
    ) -> WebhookDeliveryOutcome:
        return await self.deliver(
            tenant_id=tenant_id,
            webhook_id=webhook_id,
            url=url,
            payload={"schema_version": "1.0", "type": "test", "message": "Aether notification channel test"},
            secret=secret,
            event_id="test",
            kind="test",
        )

    async def _dispatch(
        self,
        *,
        tenant_id: str,
        webhook_id: str,
        url: str,
        payload: dict[str, Any],
        secret: str,
        idempotency_key: str,
    ) -> WebhookDeliveryOutcome:
        existing = await self.attempts.find_by_idempotency_key(tenant_id, webhook_id, idempotency_key)
        if existing and existing.get("status") in {"delivered", "blocked", "provider_unavailable", "failed"}:
            return self._outcome_from_record(existing, idempotency_key)
        if existing and existing.get("status") == "in_flight":
            return self._outcome_from_record(existing, idempotency_key)

        try:
            destination = resolve_safe_destination(url)
        except WebhookPolicyError as exc:
            return await self._record_terminal(
                tenant_id, webhook_id, idempotency_key, status="blocked", error=str(exc)
            )
        if not secret:
            return await self._record_terminal(
                tenant_id, webhook_id, idempotency_key, status="provider_unavailable", error="webhook signing secret unavailable"
            )

        try:
            import httpx
        except ImportError:
            return await self._record_terminal(
                tenant_id, webhook_id, idempotency_key, status="provider_unavailable", error="webhook HTTP provider unavailable"
            )
        client_factory = self._http_client_factory or httpx.AsyncClient
        body = __import__("json").dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        last: Optional[WebhookDeliveryOutcome] = None
        for attempt_number in range(1, MAX_ATTEMPTS + 1):
            attempt_id = str(uuid.uuid4())
            started_at = datetime.now(timezone.utc).isoformat()
            await self.attempts.insert(attempt_id, {
                "id": attempt_id,
                "tenant_id": tenant_id,
                "webhook_id": webhook_id,
                "idempotency_key": idempotency_key,
                "status": "in_flight",
                "attempt_number": attempt_number,
                "retries": attempt_number - 1,
                "started_at": started_at,
            })
            timestamp = str(int(self._now()))
            headers = {
                "Content-Type": "application/json",
                "X-Aether-Delivery-Id": idempotency_key,
                "X-Aether-Idempotency-Key": idempotency_key,
                "X-Aether-Timestamp": timestamp,
                "X-Aether-Signature": sign_payload(secret, body, timestamp),
            }
            started = time.monotonic()
            status_code: Optional[int] = None
            try:
                async with client_factory(
                    timeout=httpx.Timeout(TOTAL_TIMEOUT_SECONDS, connect=CONNECT_TIMEOUT_SECONDS),
                    follow_redirects=False,
                    max_redirects=MAX_REDIRECTS,
                ) as client:
                    async with client.stream("POST", destination.url, content=body, headers=headers) as response:
                        status_code = int(response.status_code)
                        if 300 <= status_code < 400:
                            raise WebhookPolicyError("webhook redirect refused")
                        content_length = response.headers.get("content-length")
                        if content_length and int(content_length) > MAX_RESPONSE_BYTES:
                            raise WebhookPolicyError("webhook response exceeded size limit")
                        read = 0
                        async for chunk in response.aiter_bytes():
                            read += len(chunk)
                            if read > MAX_RESPONSE_BYTES:
                                raise WebhookPolicyError("webhook response exceeded size limit")
                elapsed = (time.monotonic() - started) * 1000
                success = 200 <= (status_code or 0) < 300
                retryable = status_code in {408, 425, 429} or (status_code is not None and status_code >= 500)
                if success:
                    return await self._finish_attempt(
                        attempt_id, tenant_id, webhook_id, idempotency_key,
                        status="delivered", status_code=status_code, latency_ms=elapsed,
                        attempts=attempt_number,
                    )
                reason = f"webhook provider returned HTTP {status_code}"
                await self.attempts.update(attempt_id, {
                    "status": "failed", "status_code": status_code, "completed_at": datetime.now(timezone.utc).isoformat(),
                    "latency_ms": elapsed, "retryable": retryable, "failure_reason": reason,
                })
                if not retryable:
                    return WebhookDeliveryOutcome("failed", False, webhook_id, tenant_id, idempotency_key, attempt_number, status_code, elapsed, reason, attempt_id)
                last = WebhookDeliveryOutcome("failed", False, webhook_id, tenant_id, idempotency_key, attempt_number, status_code, elapsed, reason, attempt_id)
            except WebhookPolicyError as exc:
                reason = str(exc)
                await self.attempts.update(attempt_id, {
                    "status": "blocked", "completed_at": datetime.now(timezone.utc).isoformat(),
                    "status_code": status_code, "failure_reason": reason,
                })
                return WebhookDeliveryOutcome("blocked", False, webhook_id, tenant_id, idempotency_key, attempt_number, status_code, (time.monotonic() - started) * 1000, reason, attempt_id)
            except (httpx.TimeoutException, TimeoutError) as exc:
                reason = "webhook provider timed out"
                await self.attempts.update(attempt_id, {
                    "status": "failed", "completed_at": datetime.now(timezone.utc).isoformat(),
                    "failure_reason": reason, "retryable": True,
                })
                last = WebhookDeliveryOutcome("failed", False, webhook_id, tenant_id, idempotency_key, attempt_number, status_code, (time.monotonic() - started) * 1000, reason, attempt_id)
            except Exception as exc:
                logger.warning("customer_webhook_delivery_failed webhook=%s reason=%s", webhook_id, type(exc).__name__)
                reason = "webhook provider unavailable"
                await self.attempts.update(attempt_id, {
                    "status": "failed", "completed_at": datetime.now(timezone.utc).isoformat(),
                    "failure_reason": reason, "retryable": True,
                })
                last = WebhookDeliveryOutcome("failed", False, webhook_id, tenant_id, idempotency_key, attempt_number, status_code, (time.monotonic() - started) * 1000, reason, attempt_id)
            if attempt_number < MAX_ATTEMPTS:
                await self._sleeper(BACKOFF_SECONDS[attempt_number - 1])
        assert last is not None
        return last

    async def _record_terminal(self, tenant_id: str, webhook_id: str, key: str, *, status: str, error: str) -> WebhookDeliveryOutcome:
        attempt_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        await self.attempts.insert(attempt_id, {
            "id": attempt_id,
            "tenant_id": tenant_id,
            "webhook_id": webhook_id,
            "idempotency_key": key,
            "status": status,
            "attempt_number": 0,
            "retries": 0,
            "started_at": now,
            "completed_at": now,
            "failure_reason": error,
        })
        return WebhookDeliveryOutcome(status, False, webhook_id, tenant_id, key, 0, error=error, attempt_id=attempt_id)

    async def _finish_attempt(self, attempt_id: str, tenant_id: str, webhook_id: str, key: str, *, status: str, status_code: int, latency_ms: float, attempts: int) -> WebhookDeliveryOutcome:
        await self.attempts.update(attempt_id, {
            "status": status,
            "status_code": status_code,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "latency_ms": latency_ms,
            "failure_reason": None,
        })
        return WebhookDeliveryOutcome(status, True, webhook_id, tenant_id, key, attempts, status_code, latency_ms, attempt_id=attempt_id)

    @staticmethod
    def _outcome_from_record(record: dict[str, Any], key: str) -> WebhookDeliveryOutcome:
        status = str(record.get("status", "failed"))
        return WebhookDeliveryOutcome(
            status=status,
            success=status == "delivered",
            webhook_id=str(record.get("webhook_id", "")),
            tenant_id=str(record.get("tenant_id", "")),
            idempotency_key=key,
            attempts=int(record.get("attempt_number", 0)),
            status_code=record.get("status_code"),
            latency_ms=record.get("latency_ms"),
            error=record.get("failure_reason"),
            attempt_id=record.get("id"),
        )
