"""Per-tenant LLM token budget tracking for Noesis.

Uses CacheClient (Redis in production, in-memory in dev) to enforce
daily and monthly provider token limits without requiring a database write.

Usage pattern:
  reserved = await budget.check_and_reserve(tenant_id, estimated_tokens)
  if not reserved:
      raise token_budget_error
  try:
      result = await provider.call(...)
      actual = result.tokens_used
      if actual != estimated_tokens:
          await budget.release(tenant_id, estimated_tokens - actual)
  except Exception:
      await budget.release(tenant_id, estimated_tokens)
      raise
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
        """Atomically reserve estimated_tokens across all budget scopes.

        Returns True if reservation succeeded (all scopes had room).
        Returns False if any scope was exhausted.
        On cache failure allows through and logs a warning.
        """
        daily_key = self._daily_key(tenant_id)
        monthly_key = self._monthly_key(tenant_id)
        global_key = self._global_daily_key()
        try:
            daily_val, daily_ok = await self._cache.incr_by_if_under(
                daily_key, estimated_tokens, self._per_tenant_daily_limit, _DAILY_TTL
            )
            if not daily_ok:
                logger.warning(
                    "Noesis tenant daily token limit exceeded",
                    extra={"tenant_id": tenant_id, "current": daily_val, "limit": self._per_tenant_daily_limit},
                )
                metrics.increment("noesis_token_limit_exceeded", labels={"scope": "tenant_daily"})
                return False

            monthly_val, monthly_ok = await self._cache.incr_by_if_under(
                monthly_key, estimated_tokens, self._per_tenant_monthly_limit, _MONTHLY_TTL
            )
            if not monthly_ok:
                # Roll back daily reservation
                await self._cache.incr_by(daily_key, -estimated_tokens)
                logger.warning(
                    "Noesis tenant monthly token limit exceeded",
                    extra={"tenant_id": tenant_id, "current": monthly_val, "limit": self._per_tenant_monthly_limit},
                )
                metrics.increment("noesis_token_limit_exceeded", labels={"scope": "tenant_monthly"})
                return False

            global_val, global_ok = await self._cache.incr_by_if_under(
                global_key, estimated_tokens, self._global_daily_limit, _DAILY_TTL
            )
            if not global_ok:
                # Roll back daily and monthly reservations
                await self._cache.incr_by(daily_key, -estimated_tokens)
                await self._cache.incr_by(monthly_key, -estimated_tokens)
                logger.warning(
                    "Noesis global daily token limit exceeded",
                    extra={"current": global_val, "limit": self._global_daily_limit},
                )
                metrics.increment("noesis_token_limit_exceeded", labels={"scope": "global_daily"})
                return False

            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Noesis token budget check failed, allowing: {exc}")
            return True

    async def charge(self, tenant_id: str, tokens: int) -> None:
        """Record additional token spend beyond the initial reservation.

        Called when actual usage exceeds the upfront estimate so counters
        accurately reflect total spend even without a budget gate.
        """
        if tokens <= 0:
            return
        try:
            await self._cache.incr_by(self._daily_key(tenant_id), tokens)
            await self._cache.incr_by(self._monthly_key(tenant_id), tokens)
            await self._cache.incr_by(self._global_daily_key(), tokens)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Noesis token budget charge failed: {exc}")

    async def release(self, tenant_id: str, tokens: int) -> None:
        """Release previously reserved tokens (on failure or over-estimate).

        Decrements all three scopes by `tokens`. Used when a provider call
        fails or completes with fewer tokens than estimated.
        """
        if tokens <= 0:
            return
        try:
            await self._cache.incr_by(self._daily_key(tenant_id), -tokens)
            await self._cache.incr_by(self._monthly_key(tenant_id), -tokens)
            await self._cache.incr_by(self._global_daily_key(), -tokens)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Noesis token budget release failed: {exc}")
