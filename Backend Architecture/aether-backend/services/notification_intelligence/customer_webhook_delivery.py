"""Hardened customer webhook delivery primitives.

This module is intentionally independent of the route layer.  It owns the
security policy for customer-controlled destinations and records every
attempt in the existing durable delivery-attempt store.  Secret material is
resolved by the caller from the provider vault and is never part of a
webhook configuration response or an attempt record.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import socket
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import urlparse

from shared.logger.logger import get_logger
from repositories.delivery_repos import DeliveryAttemptRepository
from repositories.repos import BaseRepository

logger = get_logger("aether.notification.customer_webhook_delivery")

REPLAY_WINDOW_SECONDS = 300
CONNECT_TIMEOUT_SECONDS = 3.0
TOTAL_TIMEOUT_SECONDS = 15.0
MAX_REDIRECTS = 0
MAX_RESPONSE_BYTES = 64 * 1024
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (0.0, 1.0, 2.0)
IN_FLIGHT_RECOVERY_SECONDS = TOTAL_TIMEOUT_SECONDS + 60.0
_WEBHOOK_CLAIM_LOCK = asyncio.Lock()

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
    # An absent environment is not local. Provider capabilities must fail
    # closed until deployment explicitly opts into local development.
    return os.getenv("AETHER_ENV", "").lower() == "local"


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
    """Return an allowlisted customer DTO with all secret material removed."""
    allowed = {
        "id", "tenant_id", "url", "events", "active", "status",
        "display_name", "verification_status", "last_test",
        "last_delivery_failure", "created_at", "updated_at",
    }
    redacted = {key: record[key] for key in allowed if key in record}
    redacted["secret_configured"] = bool(
        record.get("secret_ref")
        or record.get("credentials_ref")
        or record.get("secret")
        or record.get("encrypted_api_key")
    )
    return redacted


def secret_fingerprint(secret: str) -> str:
    """Create a non-reversible diagnostic fingerprint for a write-only secret."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


class _WebhookDeliveryClaimRepository(BaseRepository):
    """PostgreSQL-backed atomic claims for one tenant webhook event."""

    def __init__(self) -> None:
        super().__init__("customer_webhook_delivery_claims")
        self._local_lock = _WEBHOOK_CLAIM_LOCK

    @staticmethod
    def _claim_id(tenant_id: str, webhook_id: str, key: str) -> str:
        return hashlib.sha256(
            f"{tenant_id}:{webhook_id}:{key}".encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _record(row: Any) -> dict[str, Any]:
        result = dict(row)
        for field in ("claimed_at", "updated_at"):
            value = result.get(field)
            if isinstance(value, datetime):
                result[field] = value.isoformat()
        return result

    async def _ensure_claim_table(self) -> Optional[Any]:
        pool = await self._ensure_pool()
        if pool is None:
            self._table_ensured = True
            return None
        if not self._table_ensured:
            await pool.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.table_name} (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    webhook_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    status TEXT NOT NULL,
                    claimed_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    attempts INTEGER NOT NULL DEFAULT 1,
                    status_code INTEGER,
                    latency_ms DOUBLE PRECISION,
                    failure_reason TEXT,
                    attempt_id TEXT,
                    claim_token TEXT,
                    CONSTRAINT customer_webhook_delivery_claims_key
                        UNIQUE (tenant_id, webhook_id, idempotency_key)
                )
                """
            )
            await pool.execute(
                f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS claim_token TEXT"
            )
            await pool.execute(
                f"CREATE INDEX IF NOT EXISTS ix_{self.table_name}_lookup "
                f"ON {self.table_name} (tenant_id, webhook_id, updated_at)"
            )
            await pool.execute(
                f"CREATE INDEX IF NOT EXISTS ix_{self.table_name}_recovery "
                f"ON {self.table_name} (status, claimed_at)"
            )
            self._table_ensured = True
        return pool

    async def _find(self, claim_id: str, pool: Optional[Any]) -> Optional[dict[str, Any]]:
        if pool is None:
            return self._store.get(claim_id)
        row = await pool.fetchrow(
            f"SELECT * FROM {self.table_name} WHERE id = $1", claim_id
        )
        return self._record(row) if row else None

    async def claim(
        self,
        tenant_id: str,
        webhook_id: str,
        key: str,
        *,
        now: Optional[datetime] = None,
        owner_token: Optional[str] = None,
    ) -> tuple[dict[str, Any], bool]:
        """Atomically claim one delivery key, recovering stale claims."""
        current = now or datetime.now(timezone.utc)
        owner_token = owner_token or secrets.token_urlsafe(24)
        claim_id = self._claim_id(tenant_id, webhook_id, key)
        pool = await self._ensure_claim_table()
        lock = self._local_lock if pool is None else _NullAsyncLock()
        async with lock:
            existing = await self._find(claim_id, pool)
            if existing:
                status = str(existing.get("status", "in_flight"))
                claimed_at = existing.get("claimed_at")
                stale = False
                if claimed_at:
                    try:
                        parsed = datetime.fromisoformat(str(claimed_at).replace("Z", "+00:00"))
                        if parsed.tzinfo is None:
                            parsed = parsed.replace(tzinfo=timezone.utc)
                        stale = (current - parsed.astimezone(timezone.utc)).total_seconds() > IN_FLIGHT_RECOVERY_SECONDS
                    except (TypeError, ValueError):
                        stale = True
                if status == "in_flight" and stale:
                    if pool is None:
                        refreshed = dict(existing)
                        refreshed.update({
                            "status": "in_flight",
                            "claimed_at": current.isoformat(),
                            "updated_at": current.isoformat(),
                            "attempts": int(existing.get("attempts", 0)) + 1,
                            "claim_token": owner_token,
                        })
                        self._store[claim_id] = refreshed
                        return refreshed, True
                    row = await pool.fetchrow(
                        f"""
                        UPDATE {self.table_name}
                        SET status = 'in_flight', claimed_at = $1, updated_at = $1,
                            attempts = attempts + 1, claim_token = $4
                        WHERE id = $2 AND status = 'in_flight' AND claimed_at < $3
                        RETURNING *
                        """,
                        current,
                        claim_id,
                        current - timedelta(seconds=IN_FLIGHT_RECOVERY_SECONDS),
                        owner_token,
                    )
                    if row:
                        return self._record(row), True
                    refreshed = await self._find(claim_id, pool)
                    if refreshed:
                        return refreshed, False
                return existing, False

            values = (
                claim_id,
                tenant_id,
                webhook_id,
                key,
                "in_flight",
                current,
                current,
                1,
            )
            if pool is None:
                record = {
                    "id": claim_id,
                    "tenant_id": tenant_id,
                    "webhook_id": webhook_id,
                    "idempotency_key": key,
                    "status": "in_flight",
                    "claimed_at": current.isoformat(),
                    "updated_at": current.isoformat(),
                    "attempts": 1,
                    "status_code": None,
                    "latency_ms": None,
                    "failure_reason": None,
                    "attempt_id": None,
                    "claim_token": owner_token,
                }
                self._store[claim_id] = record
                return record, True
            row = await pool.fetchrow(
                f"""
                INSERT INTO {self.table_name}
                    (id, tenant_id, webhook_id, idempotency_key, status,
                     claimed_at, updated_at, attempts, claim_token)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (tenant_id, webhook_id, idempotency_key) DO NOTHING
                RETURNING *
                """,
                *values, owner_token,
            )
            if row:
                return self._record(row), True
            winner = await self._find(claim_id, pool)
            if winner:
                return winner, False
            raise RuntimeError("webhook delivery claim disappeared after conflict")

    async def complete(
        self,
        tenant_id: str,
        webhook_id: str,
        key: str,
        outcome: WebhookDeliveryOutcome,
        owner_token: Optional[str],
    ) -> None:
        if not owner_token:
            return
        claim_id = self._claim_id(tenant_id, webhook_id, key)
        pool = await self._ensure_claim_table()
        values = {
            "status": outcome.status,
            "updated_at": datetime.now(timezone.utc),
            "attempts": outcome.attempts,
            "status_code": outcome.status_code,
            "latency_ms": outcome.latency_ms,
            "failure_reason": outcome.error,
            "attempt_id": outcome.attempt_id,
        }
        if pool is None:
            existing = self._store.get(claim_id)
            if existing and existing.get("status") == "in_flight" and existing.get("claim_token") == owner_token:
                existing.update({**values, "updated_at": values["updated_at"].isoformat()})
            return
        await pool.execute(
            f"""
            UPDATE {self.table_name}
            SET status = $1, updated_at = $2, attempts = $3, status_code = $4,
                latency_ms = $5, failure_reason = $6, attempt_id = $7
            WHERE id = $8 AND status = 'in_flight' AND claim_token = $9
            """,
            values["status"], values["updated_at"], values["attempts"],
            values["status_code"], values["latency_ms"], values["failure_reason"],
            values["attempt_id"], claim_id, owner_token,
        )

    async def delete_by_tenant(self, tenant_id: str) -> int:
        pool = await self._ensure_claim_table()
        if pool is None:
            keys = [key for key, value in self._store.items() if value.get("tenant_id") == tenant_id]
            for key in keys:
                del self._store[key]
            return len(keys)
        result = await pool.execute(
            f"DELETE FROM {self.table_name} WHERE tenant_id = $1", tenant_id
        )
        try:
            return int(str(result).split()[-1])
        except (TypeError, ValueError, IndexError):
            return 0


class _NullAsyncLock:
    async def __aenter__(self) -> "_NullAsyncLock":
        return self

    async def __aexit__(self, *_args: Any) -> None:
        return None


class CustomerWebhookDeliveryRepository(DeliveryAttemptRepository):
    """Durable tenant-scoped records for customer webhook attempts."""

    def __init__(self) -> None:
        super().__init__()
        self.claims = _WebhookDeliveryClaimRepository()

    async def claim(
        self,
        tenant_id: str,
        webhook_id: str,
        key: str,
        *,
        now: Optional[datetime] = None,
        owner_token: Optional[str] = None,
    ) -> tuple[dict[str, Any], bool]:
        return await self.claims.claim(
            tenant_id, webhook_id, key, now=now, owner_token=owner_token
        )

    async def complete_claim(
        self,
        tenant_id: str,
        webhook_id: str,
        key: str,
        outcome: WebhookDeliveryOutcome,
        owner_token: Optional[str],
    ) -> None:
        await self.claims.complete(tenant_id, webhook_id, key, outcome, owner_token)

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


class _WebhookSecretCipher:
    """Encrypt webhook secrets before they enter the durable provider row."""

    def __init__(self) -> None:
        self._fernet = None
        self._previous = None
        try:
            from cryptography.fernet import Fernet
        except ImportError:
            Fernet = None
        key = os.getenv("BYOK_ENCRYPTION_KEY", "")
        previous = os.getenv("BYOK_ENCRYPTION_KEY_PREVIOUS", "")
        if Fernet and key:
            try:
                self._fernet = Fernet(key.encode("utf-8"))
                if previous:
                    self._previous = Fernet(previous.encode("utf-8"))
            except Exception as exc:
                if not _is_local_development():
                    raise ProviderUnavailableError("webhook credential encryption is misconfigured") from exc
        elif not _is_local_development():
            raise ProviderUnavailableError("webhook credential encryption is not configured")

    def encrypt(self, value: str) -> str:
        if self._fernet:
            return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")
        return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str) -> str:
        if self._fernet:
            from cryptography.fernet import InvalidToken
            try:
                return self._fernet.decrypt(value.encode("ascii")).decode("utf-8")
            except InvalidToken:
                if self._previous:
                    return self._previous.decrypt(value.encode("ascii")).decode("utf-8")
                raise ProviderUnavailableError("webhook signing secret cannot be decrypted")
        return base64.urlsafe_b64decode(value.encode("ascii")).decode("utf-8")


class CustomerWebhookSecretStore:
    """Write-only customer secret facade over the durable encrypted vault."""

    def __init__(self, provider_repository: Any, cipher: Any = None) -> None:
        self._provider_repository = provider_repository
        self._cipher = cipher

    def _get_cipher(self) -> _WebhookSecretCipher:
        if self._cipher is None:
            self._cipher = _WebhookSecretCipher()
        return self._cipher

    async def store(self, tenant_id: str, webhook_id: str, secret: Optional[str] = None) -> dict[str, Any]:
        value = secret or secrets.token_urlsafe(32)
        secret_ref = f"customer_webhook:{tenant_id}:{webhook_id}"
        encrypted = self._get_cipher().encrypt(value)
        await self._provider_repository.upsert(secret_ref, {
            "encrypted_api_key": encrypted,
            "credential_version": 1,
            "provider": "customer_webhook",
            "tenant_id": tenant_id,
            # ProvidersRepository updates JSONB rows by merge. Explicitly
            # clear legacy plaintext fields during the encrypted migration so
            # an old row cannot retain raw credentials beside the ciphertext.
            "api_key": None,
            "token": None,
            "access_token": None,
            "client_secret": None,
            "secret": None,
            "signing_secret": None,
            "raw_secret": None,
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
        encrypted = record.get("encrypted_api_key")
        if encrypted:
            value = self._get_cipher().decrypt(str(encrypted))
        else:
            # Legacy raw provider rows may only be read in explicit local
            # development. Production must be backfilled with an encrypted
            # record before delivery is allowed.
            if not _is_local_development():
                raise ProviderUnavailableError(
                    "legacy webhook signing secret requires encrypted migration"
                )
            value = str(record.get("api_key", ""))
            if value:
                await self.store(tenant_id, secret_ref.rsplit(":", 1)[-1], value)
        if not value:
            raise ProviderUnavailableError("webhook signing secret unavailable")
        return value


class _PinnedNetworkBackend:
    """httpcore backend that connects only to the already-validated IPs."""

    def __init__(self, hostname: str, addresses: tuple[str, ...]) -> None:
        from httpcore._backends.auto import AutoBackend

        self._hostname = hostname
        self._addresses = addresses
        self._backend = AutoBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> Any:
        if host.rstrip(".").lower() != self._hostname:
            raise WebhookPolicyError("webhook connection hostname changed after validation")
        last_error: Exception | None = None
        for address in self._addresses:
            try:
                return await self._backend.connect_tcp(
                    address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except Exception as exc:  # try the next validated address
                last_error = exc
        raise ProviderUnavailableError("webhook destination could not be reached") from last_error

    async def connect_unix_socket(self, *args: Any, **kwargs: Any) -> Any:
        return await self._backend.connect_unix_socket(*args, **kwargs)

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


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
        claim_token = secrets.token_urlsafe(24)
        claim, acquired = await self.attempts.claim(
            tenant_id,
            webhook_id,
            idempotency_key,
            now=datetime.now(timezone.utc),
            owner_token=claim_token,
        )
        if not acquired:
            return self._outcome_from_record(claim, idempotency_key)

        try:
            destination = resolve_safe_destination(url)
        except WebhookPolicyError as exc:
            return await self._record_terminal(
                tenant_id, webhook_id, idempotency_key,
                status="blocked", error=str(exc), claim_token=claim_token,
            )
        if not secret:
            return await self._record_terminal(
                tenant_id, webhook_id, idempotency_key,
                status="provider_unavailable", error="webhook signing secret unavailable",
                claim_token=claim_token,
            )

        try:
            import httpx
        except ImportError:
            return await self._record_terminal(
                tenant_id, webhook_id, idempotency_key,
                status="provider_unavailable", error="webhook HTTP provider unavailable",
                claim_token=claim_token,
            )
        client_factory = self._http_client_factory or httpx.AsyncClient
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        last: Optional[WebhookDeliveryOutcome] = None
        for attempt_number in range(1, MAX_ATTEMPTS + 1):
            try:
                # Resolve immediately before each connect and pin the
                # validated addresses so a DNS rebinding cannot redirect the
                # HTTP client to a private or metadata network.
                destination = resolve_safe_destination(url)
            except WebhookPolicyError as exc:
                return await self._record_terminal(
                    tenant_id, webhook_id, idempotency_key,
                    status="blocked", error=str(exc), claim_token=claim_token,
                )
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
                transport = httpx.AsyncHTTPTransport(
                    retries=0,
                    limits=httpx.Limits(max_connections=1, max_keepalive_connections=0),
                )
                pool = getattr(transport, "_pool", None)
                if pool is None or not hasattr(pool, "_network_backend"):
                    raise ProviderUnavailableError(
                        "webhook HTTP transport cannot enforce destination pinning"
                    )
                # HTTPX exposes no public IP-pinning hook. Fail closed if the
                # supported transport internals ever change instead of
                # silently falling back to a second DNS resolution.
                pool._network_backend = _PinnedNetworkBackend(
                    destination.hostname, destination.addresses
                )
                async with client_factory(
                    timeout=httpx.Timeout(TOTAL_TIMEOUT_SECONDS, connect=CONNECT_TIMEOUT_SECONDS),
                    follow_redirects=False,
                    max_redirects=MAX_REDIRECTS,
                    transport=transport,
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
                        claim_token=claim_token,
                    )
                reason = f"webhook provider returned HTTP {status_code}"
                await self.attempts.update(attempt_id, {
                    "status": "failed", "status_code": status_code, "completed_at": datetime.now(timezone.utc).isoformat(),
                    "latency_ms": elapsed, "retryable": retryable, "failure_reason": reason,
                })
                if not retryable:
                    outcome = WebhookDeliveryOutcome("failed", False, webhook_id, tenant_id, idempotency_key, attempt_number, status_code, elapsed, reason, attempt_id)
                    await self.attempts.complete_claim(
                        tenant_id, webhook_id, idempotency_key, outcome, claim_token
                    )
                    return outcome
                last = WebhookDeliveryOutcome("failed", False, webhook_id, tenant_id, idempotency_key, attempt_number, status_code, elapsed, reason, attempt_id)
            except WebhookPolicyError as exc:
                reason = str(exc)
                await self.attempts.update(attempt_id, {
                    "status": "blocked", "completed_at": datetime.now(timezone.utc).isoformat(),
                    "status_code": status_code, "failure_reason": reason,
                })
                outcome = WebhookDeliveryOutcome("blocked", False, webhook_id, tenant_id, idempotency_key, attempt_number, status_code, (time.monotonic() - started) * 1000, reason, attempt_id)
                await self.attempts.complete_claim(
                    tenant_id, webhook_id, idempotency_key, outcome, claim_token
                )
                return outcome
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
        await self.attempts.complete_claim(
            tenant_id, webhook_id, idempotency_key, last, claim_token
        )
        return last

    async def _record_terminal(
        self,
        tenant_id: str,
        webhook_id: str,
        key: str,
        *,
        status: str,
        error: str,
        claim_token: str,
    ) -> WebhookDeliveryOutcome:
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
        outcome = WebhookDeliveryOutcome(status, False, webhook_id, tenant_id, key, 0, error=error, attempt_id=attempt_id)
        await self.attempts.complete_claim(tenant_id, webhook_id, key, outcome, claim_token)
        return outcome

    async def _finish_attempt(
        self,
        attempt_id: str,
        tenant_id: str,
        webhook_id: str,
        key: str,
        *,
        status: str,
        status_code: int,
        latency_ms: float,
        attempts: int,
        claim_token: str,
    ) -> WebhookDeliveryOutcome:
        await self.attempts.update(attempt_id, {
            "status": status,
            "status_code": status_code,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "latency_ms": latency_ms,
            "failure_reason": None,
        })
        outcome = WebhookDeliveryOutcome(status, True, webhook_id, tenant_id, key, attempts, status_code, latency_ms, attempt_id=attempt_id)
        await self.attempts.complete_claim(tenant_id, webhook_id, key, outcome, claim_token)
        return outcome

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
