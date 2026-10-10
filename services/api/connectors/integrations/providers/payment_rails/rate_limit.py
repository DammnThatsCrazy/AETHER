"""Per-endpoint rate limiting for public payment-rail webhooks.

A high-entropy endpoint id (``whe_<hex>``) is a capability, but a leaked or
guessed one must not let a flood of bodies burn CPU on signature verification.
This enforces a fixed per-UTC-minute budget keyed on the endpoint id (falling
back to ``tenant:provider`` when a webhook arrives without an endpoint id),
using the same atomic ``incr_if_under`` counter the Noesis limiter uses
(Redis in production, in-memory in dev). It fails **open**: any cache error
allows the request through and is logged, so the limiter can never itself take
webhook ingestion down.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from shared.cache.cache import CacheClient, CacheKey
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.payment_rails.rate_limit")

_WINDOW_TTL = 60  # seconds; matches the per-minute key granularity


class PaymentWebhookRateLimiter:
    """Fixed per-minute-window webhook admission limiter."""

    def __init__(self, cache: Optional[CacheClient] = None) -> None:
        self._cache = cache or CacheClient()

    @staticmethod
    def _key(scope: str) -> str:
        minute = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M")
        return CacheKey.custom(f"payrail:whrl:{scope}:{minute}")

    async def allow(
        self,
        *,
        provider: str,
        limit: int,
        endpoint_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> bool:
        """Atomically account one webhook against the window; True if under limit.

        Prefer the endpoint id as the scope (each provider endpoint gets its own
        budget); fall back to ``tenant:provider`` for the header-resolved legacy
        path. Fails open on any cache error.
        """
        if limit <= 0:
            return True
        scope = endpoint_id or f"{tenant_id or 'unknown'}:{provider}"
        try:
            count, allowed = await self._cache.incr_if_under(
                self._key(scope), limit=limit, ttl=_WINDOW_TTL
            )
        except Exception as exc:  # noqa: BLE001 — never let the limiter fail closed
            logger.warning(f"payment webhook rate limiter unavailable, allowing: {exc}")
            return True
        if not allowed:
            metrics.increment(
                "payment_rail_webhook_rate_limited_total",
                labels={"provider": provider},
            )
            logger.warning(
                "payment webhook rate limit exceeded",
                extra={"provider": provider, "scope": scope, "count": count, "limit": limit},
            )
        return allowed


payment_webhook_rate_limiter = PaymentWebhookRateLimiter()


class PaymentTenantActionRateLimiter:
    """Fixed per-minute-window limiter for tenant-initiated write actions.

    Guards the manual provider-sync and canonical-repair endpoints so an
    authorized tenant cannot hammer provider polling / repair with no cooldown.
    Keyed on ``action:tenant`` per UTC minute using the same atomic counter as
    the webhook limiter. Fails **open** (a cache error never blocks a legitimate
    admin action) — the endpoints remain permission-gated and audited regardless.
    """

    def __init__(self, cache: Optional[CacheClient] = None) -> None:
        self._cache = cache or CacheClient()

    @staticmethod
    def _key(action: str, tenant_id: str) -> str:
        minute = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M")
        return CacheKey.custom(f"payrail:actrl:{action}:{tenant_id}:{minute}")

    async def allow(self, *, action: str, tenant_id: str, limit: int) -> bool:
        if limit <= 0:
            return True
        try:
            count, allowed = await self._cache.incr_if_under(
                self._key(action, tenant_id), limit=limit, ttl=_WINDOW_TTL
            )
        except Exception as exc:  # noqa: BLE001 — never let the limiter fail closed
            logger.warning(f"payment tenant-action rate limiter unavailable, allowing: {exc}")
            return True
        if not allowed:
            metrics.increment(
                "payment_rail_tenant_action_rate_limited_total",
                labels={"action": action},
            )
            logger.warning(
                "payment tenant-action rate limit exceeded",
                extra={"action": action, "tenant_id": tenant_id, "count": count, "limit": limit},
            )
        return allowed


payment_tenant_action_rate_limiter = PaymentTenantActionRateLimiter()
