"""Aether Billing — Quota Notifications

Fires webhook notifications when tenants cross usage thresholds. Each event
is deduplicated within a billing period so we never spam the customer.

Triggers:
  quota.threshold.80   — first time usage >= 80%
  quota.threshold.90   — first time usage >= 90%
  quota.exhausted      — first time usage >= 100% (entering overage)
  quota.overage.daily_summary — daily 00:00 UTC tick while in overage
  burst.repeated_limit — when burst rejections cross a threshold
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from shared.auth.auth import PlanTier
from shared.logger.logger import get_logger
from shared.plans.catalog import PLAN_CATALOG

logger = get_logger("aether.billing.notifications")


_REDIS_TTL_SECONDS = 35 * 86400


def _current_period() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


class QuotaNotifier:
    """Threshold notifier with per-period deduplication.

    Notifications are dispatched via the existing notification service.
    The hook here is best-effort — failures never block the request path.
    """

    def __init__(
        self,
        redis_client: Optional[Any] = None,
        notification_service: Optional[Any] = None,
    ) -> None:
        self._redis = redis_client
        self._notifier = notification_service
        # In-memory dedup cache for environments without Redis.
        self._memory_dedup: set[str] = set()

    def set_redis(self, client: Any) -> None:
        self._redis = client

    def set_notification_service(self, service: Any) -> None:
        self._notifier = service

    @staticmethod
    def _dedup_key(tenant_id: str, period: str) -> str:
        return f"rl:notified:{tenant_id}:{period}"

    async def _is_already_sent(
        self, tenant_id: str, period: str, event_type: str,
    ) -> bool:
        key = self._dedup_key(tenant_id, period)
        if self._redis is not None:
            try:
                return bool(await self._redis.sismember(key, event_type))
            except Exception as e:  # pragma: no cover — defensive
                logger.debug(f"dedup sismember failed: {e}")
        return f"{key}:{event_type}" in self._memory_dedup

    async def _mark_sent(
        self, tenant_id: str, period: str, event_type: str,
    ) -> None:
        key = self._dedup_key(tenant_id, period)
        if self._redis is not None:
            try:
                await self._redis.sadd(key, event_type)
                ttl = await self._redis.ttl(key)
                if ttl is None or ttl == -1:
                    await self._redis.expire(key, _REDIS_TTL_SECONDS)
                return
            except Exception as e:  # pragma: no cover — defensive
                logger.debug(f"dedup sadd failed: {e}")
        self._memory_dedup.add(f"{key}:{event_type}")

    async def _send(self, event_type: str, payload: dict) -> None:
        if self._notifier is None:
            logger.info(
                f"[quota-notification] {event_type} payload={payload}"
            )
            return
        try:
            await self._notifier.dispatch(event_type, payload)
        except Exception as e:  # pragma: no cover — defensive
            logger.warning(f"Notification dispatch failed: {e}")

    async def check_and_notify(
        self,
        tenant_id: str,
        plan_tier: PlanTier,
        quota_result: Any,
    ) -> None:
        """Inspect a QuotaResult and fire any threshold notifications."""
        period = _current_period()
        if quota_result.quota_limit <= 0:
            return
        ratio = quota_result.quota_used / quota_result.quota_limit
        plan = PLAN_CATALOG[plan_tier]

        thresholds = (
            (1.00, "quota.exhausted"),
            (0.90, "quota.threshold.90"),
            (0.80, "quota.threshold.80"),
        )
        for threshold, event in thresholds:
            if ratio < threshold:
                continue
            if await self._is_already_sent(tenant_id, period, event):
                continue
            await self._mark_sent(tenant_id, period, event)
            payload = {
                "tenant_id": tenant_id,
                "plan_tier": plan.plan_id,
                "billing_period": period,
                "used": quota_result.quota_used,
                "limit": quota_result.quota_limit,
                "remaining": quota_result.remaining,
                "utilization_ratio": round(ratio, 4),
            }
            if event == "quota.exhausted":
                payload["overage_start_time"] = (
                    datetime.now(timezone.utc).isoformat()
                )
            await self._send(event, payload)

    async def notify_burst_repeated(
        self,
        tenant_id: str,
        plan_tier: PlanTier,
        rejection_count: int,
    ) -> None:
        period = _current_period()
        event = "burst.repeated_limit"
        # Dedup once per hour bucket
        bucket_key = f"{event}:{datetime.now(timezone.utc).strftime('%H')}"
        if await self._is_already_sent(tenant_id, period, bucket_key):
            return
        await self._mark_sent(tenant_id, period, bucket_key)
        plan = PLAN_CATALOG[plan_tier]
        await self._send(event, {
            "tenant_id": tenant_id,
            "plan_tier": plan.plan_id,
            "rejection_count": rejection_count,
            "current_rpm_limit": plan.burst_rpm,
        })

    async def send_daily_summary(
        self,
        tenant_id: str,
        plan_tier: PlanTier,
        overage_today: int,
        overage_cost_today: str,
        overage_cost_mtd: str,
    ) -> None:
        plan = PLAN_CATALOG[plan_tier]
        await self._send("quota.overage.daily_summary", {
            "tenant_id": tenant_id,
            "plan_tier": plan.plan_id,
            "overage_requests_today": overage_today,
            "overage_cost_today": overage_cost_today,
            "overage_cost_mtd": overage_cost_mtd,
        })
