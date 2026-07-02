"""Notification Intelligence — Delivery Router

Routes a notification to all active channels configured for a tenant.
Each channel type has an independent circuit breaker — one failure doesn't
block the others.
"""

from __future__ import annotations

import asyncio
from typing import Any

from shared.logger.logger import get_logger, metrics
from services.notification_intelligence.channel_gateway import get_gateway, DeliveryResult

logger = get_logger("aether.notification.delivery_router")


class DeliveryRouter:
    def __init__(self, channel_repo=None, providers_repo=None):
        self._channel_repo = channel_repo
        self._providers_repo = providers_repo

    async def route(self, notification: Any) -> list[DeliveryResult]:
        """Deliver notification to all eligible active channels for the tenant."""
        tenant_id = getattr(notification, "tenant_id", "")
        severity = getattr(notification, "severity", "info")
        sev_val = severity.value if hasattr(severity, "value") else str(severity)
        source_topic = getattr(notification, "source_topic", "")

        channels = await self._load_channels(tenant_id)
        eligible = self._filter_channels(channels, sev_val, source_topic)

        if not eligible:
            logger.info("no_eligible_channels tenant=%s severity=%s", tenant_id, sev_val)
            return []

        tasks = [self._deliver_one(notification, ch) for ch in eligible]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        final: list[DeliveryResult] = []
        for ch, result in zip(eligible, results):
            if isinstance(result, Exception):
                logger.error("delivery_exception channel=%s error=%s", ch.get("channel_type"), result)
                final.append(DeliveryResult(
                    success=False,
                    channel_type=ch.get("channel_type", "unknown"),
                    error=str(result),
                ))
            else:
                final.append(result)

        metrics.increment("aether_notifications_emitted_total",
                          labels={"tenant_id": tenant_id, "severity": sev_val,
                                  "source_topic": source_topic})
        return final

    async def _load_channels(self, tenant_id: str) -> list[dict]:
        if self._channel_repo is None:
            return []
        try:
            return await self._channel_repo.find_many(filters={"tenant_id": tenant_id, "active": True})
        except Exception as exc:
            logger.error("load_channels_failed tenant=%s error=%s", tenant_id, exc)
            return []

    @staticmethod
    def _filter_channels(channels: list[dict], severity: str, source_topic: str) -> list[dict]:
        eligible = []
        for ch in channels:
            sev_filter = ch.get("severity_filter") or ["P0", "P1", "P2", "P3", "info"]
            if severity not in sev_filter:
                continue
            type_filter = ch.get("event_type_filter")
            if type_filter and source_topic not in type_filter:
                continue
            eligible.append(ch)
        return eligible

    async def _deliver_one(self, notification: Any, channel: dict) -> DeliveryResult:
        channel_type = channel.get("channel_type", "webhook")
        gateway = get_gateway(channel_type)
        if gateway is None:
            return DeliveryResult(
                success=False,
                channel_type=channel_type,
                error=f"unsupported channel type: {channel_type}",
            )

        credentials = await self._resolve_credentials(channel)
        config = channel.get("channel_config", {})

        try:
            result = await gateway.deliver(notification, config, credentials)
            logger.info("delivered channel_type=%s channel_id=%s success=%s",
                        channel_type, channel.get("id"), result.success)
            return result
        except Exception as exc:
            logger.error("delivery_failed channel_type=%s error=%s", channel_type, exc)
            return DeliveryResult(success=False, channel_type=channel_type, error=str(exc))

    async def _resolve_credentials(self, channel: dict) -> str:
        """Retrieve decrypted credentials from vault via ProvidersRepository."""
        credentials_ref = channel.get("credentials_ref", "")
        if not credentials_ref:
            return ""
        if self._providers_repo is None:
            raise RuntimeError(
                f"DeliveryRouter requires providers_repo for credential resolution — "
                f"credentials_ref literal fallback removed to prevent vault keys being "
                f"treated as plaintext tokens. Pass providers_repo=ProvidersRepository() "
                f"when constructing DeliveryRouter. credentials_ref={credentials_ref!r}"
            )
        try:
            record = await self._providers_repo.find_by_id(credentials_ref)
            if record:
                return record.get("api_key", "")
        except Exception as exc:
            logger.error("credentials_resolve_failed ref=%s error=%s", credentials_ref, exc)
            raise RuntimeError(
                f"Credential resolution failed for ref={credentials_ref!r}. "
                f"Cannot proceed without valid credentials: {exc}"
            ) from exc
        raise RuntimeError(
            f"Credential record not found for ref={credentials_ref!r}. "
            f"The vault reference does not exist in the providers repository."
        )
