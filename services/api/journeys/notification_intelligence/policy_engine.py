"""Notification Intelligence — Policy Engine

Evaluates whether an incoming notification should be delivered:
1. Deduplication check (Redis, TTL-based)
2. Tenant config lookup (Redis cache → DB fallback)
3. Severity routing: which channels, requires_operator_review, expires_at
4. Rate limit check per tenant
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.notification.policy")

DEDUPE_TTL_S = 300       # 5 minutes
CONFIG_CACHE_TTL_S = 60  # 1 minute
RATE_LIMIT_WINDOW_S = 60


@dataclass
class PolicyResult:
    allowed: bool
    channels: list[str] = field(default_factory=list)
    requires_operator_review: bool = False
    expires_at: Optional[str] = None
    reject_reason: Optional[str] = None


class PolicyEngine:
    def __init__(self, cache=None):
        self._cache = cache

    async def evaluate(
        self,
        dedup_key: str,
        tenant_id: str,
        severity: str,
        config,
    ) -> PolicyResult:
        """Run policy checks and return routing decision."""
        # 1. Deduplication
        if self._cache:
            redis_dedup_key = f"aether:notif:dedupe:{dedup_key}"
            existing = await self._cache.get_json(redis_dedup_key)
            if existing:
                metrics.increment("aether_notifications_dedupe_hits_total",
                                  labels={"tenant_id": tenant_id})
                logger.info("notification_dedupe_hit dedup_key=%s tenant=%s", dedup_key, tenant_id)
                return PolicyResult(allowed=False, reject_reason="duplicate")
            # Mark as seen
            await self._cache.set_json(redis_dedup_key, {"seen": True}, ttl=DEDUPE_TTL_S)

        # 2. Rate limit (simple counter per tenant per minute)
        if self._cache:
            rl_key = f"aether:notif:ratelimit:{tenant_id}"
            count_raw = await self._cache.get_json(rl_key)
            count = (count_raw or {}).get("count", 0)
            limit = getattr(config, "rate_limit_per_minute", 10)
            if count >= limit:
                metrics.increment("aether_notifications_rate_limited_total",
                                  labels={"tenant_id": tenant_id})
                return PolicyResult(allowed=False, reject_reason="rate_limited")
            await self._cache.set_json(rl_key, {"count": count + 1}, ttl=RATE_LIMIT_WINDOW_S)

        # 3. Channel routing from severity
        channels = self._channels_for_severity(severity, config)

        # 4. Operator review requirement
        requires_review = severity in getattr(config, "operator_review_required", ["P0", "P1"])

        # 5. SLA deadline
        sla_minutes = config.sla_for(severity) if hasattr(config, "sla_for") else 60
        expires_at = (
            datetime.now(timezone.utc) + timedelta(minutes=sla_minutes)
        ).isoformat()

        return PolicyResult(
            allowed=True,
            channels=channels,
            requires_operator_review=requires_review,
            expires_at=expires_at,
        )

    @staticmethod
    def _channels_for_severity(severity: str, config) -> list[str]:
        channel_map = {
            "P0": ["slack", "discord", "telegram", "webhook"],
            "P1": ["slack", "discord", "telegram", "webhook"],
            "P2": ["slack", "discord"],
            "P3": ["slack"],
            "info": ["slack"],
        }
        return channel_map.get(severity, ["slack"])
