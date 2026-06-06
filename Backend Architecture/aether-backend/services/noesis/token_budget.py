"""Per-tenant LLM token budget tracking for Noesis.

Uses CacheClient (Redis in production, in-memory in dev) to enforce
daily and monthly provider token limits without requiring a database write.
"""

from __future__ import annotations

import os

from shared.cache.cache import CacheClient, CacheKey
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.service.noesis.token_budget")

_DAILY_TTL = 86400       # 24 h
_MONTHLY_TTL = 2592000   # 30 days


class NoesisTokenBudget:
    """Track and enforce per-tenant provider token spend."""

    def __init__(self, cache: CacheClient | None = None) -> None:
        self._cache = cache or CacheClient()
        self._global_daily_limit = int(os.getenv("NOESIS_PROVIDER_TOKEN_BUDGET", "100000"))
        self._per_tenant_daily_limit = int(os.getenv("NOESIS_TENANT_TOKEN_DAILY_LIMIT", "5000"))
        self._per_tenant_monthly_limit = int(os.getenv("NOESIS_TENANT_TOKEN_MONTHLY_LIMIT", "50000"))

    def _daily_key(self, tenant_id: str) -> str:
        from datetime import date
        day = date.today().isoformat()
        return CacheKey.custom(f"noesis:tokens:daily:{tenant_id}:{day}")

    def _monthly_key(self, tenant_id: str) -> str:
        from datetime import date
        month = date.today().strftime("%Y-%m")
        return CacheKey.custom(f"noesis:tokens:monthly:{tenant_id}:{month}")

    def _global_daily_key(self) -> str:
        from datetime import date
        day = date.today().isoformat()
        return CacheKey.custom(f"noesis:tokens:global:daily:{day}")

    async def check_and_reserve(self, tenant_id: str, estimated_tokens: int) -> bool:
        """Return True if under budget. Does NOT deduct yet — call record() after."""
        try:
            daily_used = int(await self._cache.get(self._daily_key(tenant_id)) or 0)
            monthly_used = int(await self._cache.get(self._monthly_key(tenant_id)) or 0)
            global_used = int(await self._cache.get(self._global_daily_key()) or 0)

            if daily_used + estimated_tokens > self._per_tenant_daily_limit:
                logger.warning("Noesis tenant daily token limit exceeded", extra={"tenant_id": tenant_id, "used": daily_used, "limit": self._per_tenant_daily_limit})
                metrics.increment("noesis_token_limit_exceeded", labels={"scope": "tenant_daily"})
                return False
            if monthly_used + estimated_tokens > self._per_tenant_monthly_limit:
                logger.warning("Noesis tenant monthly token limit exceeded", extra={"tenant_id": tenant_id, "used": monthly_used, "limit": self._per_tenant_monthly_limit})
                metrics.increment("noesis_token_limit_exceeded", labels={"scope": "tenant_monthly"})
                return False
            if global_used + estimated_tokens > self._global_daily_limit:
                logger.warning("Noesis global daily token limit exceeded", extra={"used": global_used, "limit": self._global_daily_limit})
                metrics.increment("noesis_token_limit_exceeded", labels={"scope": "global_daily"})
                return False
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Noesis token budget check failed, allowing: {exc}")
        return True

    async def record(self, tenant_id: str, tokens_used: int) -> None:
        """Record actual token usage after a successful provider call."""
        try:
            await self._cache.incr(self._daily_key(tenant_id), amount=tokens_used, ttl=_DAILY_TTL)
            await self._cache.incr(self._monthly_key(tenant_id), amount=tokens_used, ttl=_MONTHLY_TTL)
            await self._cache.incr(self._global_daily_key(), amount=tokens_used, ttl=_DAILY_TTL)
            metrics.observe("noesis_tokens_used", tokens_used, labels={"tenant_id": tenant_id})
            logger.info("Noesis token usage recorded", extra={"tenant_id": tenant_id, "tokens": tokens_used})
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Noesis token budget record failed: {exc}")
