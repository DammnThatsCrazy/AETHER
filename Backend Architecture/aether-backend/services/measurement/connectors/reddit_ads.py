"""Reddit Ads connector — imports campaign spend via Reddit Advertising API v3."""

from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from services.measurement.connectors.base import BaseConnector, ConnectorHealth, SyncResult
from services.measurement.repositories.spend_repo import SpendRepository

logger = logging.getLogger("aether.measurement.connectors.reddit_ads")

_CONNECTOR_TYPE = "reddit_ads"
_BASE_URL = "https://ads-api.reddit.com/api/v3"


class RedditAdsConnector(BaseConnector):
    """Reddit Ads spend connector via Reddit Advertising API v3.

    Required config keys (stored encrypted in measurement_connectors.config):
      - access_token: OAuth 2.0 access token (ads:read scope)
      - account_id: Reddit Ads account ID (t2_<base36id>)

    Cursor state:
      - last_sync_date: ISO date string of the last successfully synced day

    Rate limits: Reddit Ads API enforces 60 requests/minute per token.
    Incremental sync fetches the last 3 days to account for late data delivery.
    """

    connector_type = _CONNECTOR_TYPE

    def __init__(self, connector_id: str, tenant_id: str, config: dict[str, Any], cursor_state: dict[str, Any]) -> None:
        super().__init__(connector_id, tenant_id, config, cursor_state)
        self._spend_repo = SpendRepository()

    async def sync_incremental(self, cursor: dict[str, Any]) -> SyncResult:
        last_date_str = cursor.get("last_sync_date")
        if last_date_str:
            try:
                start = date.fromisoformat(last_date_str) - timedelta(days=3)
            except ValueError:
                start = date.today() - timedelta(days=3)
        else:
            start = date.today() - timedelta(days=3)

        end = date.today()
        return await self.backfill(start, end)

    async def backfill(self, start: date, end: date) -> SyncResult:
        import os
        if os.getenv("AETHER_ENV", "local").lower() == "local":
            return await self._mock_backfill(start, end)
        return await self._live_backfill(start, end)

    async def _mock_backfill(self, start: date, end: date) -> SyncResult:
        """Return a mock SyncResult for local/test environments."""
        rows_upserted = 0
        current = start
        while current <= end:
            record = {
                "spend_record_id": _idempotency_id(self.connector_id, str(current)),
                "tenant_id": self.tenant_id,
                "platform": "reddit_ads",
                "ad_account_id": self.config.get("account_id", ""),
                "campaign_id": f"mock-reddit-camp-{self.connector_id[:8]}",
                "period_start": datetime.combine(current, datetime.min.time()).replace(tzinfo=timezone.utc).isoformat(),
                "period_end": datetime.combine(current, datetime.max.time()).replace(tzinfo=timezone.utc).isoformat(),
                "billing_currency": "USD",
                "impressions": 8000,
                "clicks": 120,
                "media_spend": "110.00",
                "total_cost": "110.00",
                "source_connector_id": self.connector_id,
                "idempotency_key": f"reddit-{self.connector_id}-{current}",
            }
            await self._spend_repo.upsert(record)
            rows_upserted += 1
            current += timedelta(days=1)

        logger.info("Reddit Ads mock backfill: connector=%s rows=%d", self.connector_id, rows_upserted)
        return SyncResult(rows_upserted=rows_upserted, new_cursor={"last_sync_date": str(end)})

    async def _live_backfill(self, start: date, end: date) -> SyncResult:
        try:
            import httpx
        except ImportError:
            logger.error("httpx not installed; Reddit Ads live sync unavailable")
            return SyncResult(rows_upserted=0, errors=["httpx not installed"], new_cursor={})

        account_id = self.config.get("account_id", "")
        access_token = self.config.get("access_token", "")
        if not account_id or not access_token:
            return SyncResult(rows_upserted=0, errors=["Missing account_id or access_token"], new_cursor={})

        headers = {
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "Aether/1.0",
        }
        rows_upserted = 0
        errors: list[str] = []

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                # Fetch campaigns first
                camps_resp = await client.get(
                    f"{_BASE_URL}/accounts/{account_id}/campaigns",
                    headers=headers,
                    params={"limit": 100},
                )
                camps_resp.raise_for_status()
                campaigns = camps_resp.json().get("data", {}).get("campaigns", [])

                for campaign in campaigns:
                    campaign_id = campaign.get("id", "")
                    if not campaign_id:
                        continue

                    current = start
                    while current <= end:
                        stats_resp = await client.get(
                            f"{_BASE_URL}/accounts/{account_id}/campaigns/{campaign_id}/report",
                            headers=headers,
                            params={
                                "date_start": str(current),
                                "date_stop": str(current),
                                "fields": "date,spend,impressions,clicks",
                                "breakdown": "date",
                            },
                        )
                        stats_resp.raise_for_status()
                        report_data = stats_resp.json().get("data", {})
                        rows = report_data.get("rows", [])

                        for row in rows:
                            spend = float(row.get("spend", 0)) / 100  # cents to dollars
                            record = {
                                "spend_record_id": _idempotency_id(self.connector_id, str(current) + campaign_id),
                                "tenant_id": self.tenant_id,
                                "platform": "reddit_ads",
                                "ad_account_id": account_id,
                                "campaign_id": campaign_id,
                                "period_start": datetime.combine(current, datetime.min.time()).replace(tzinfo=timezone.utc).isoformat(),
                                "period_end": datetime.combine(current, datetime.max.time()).replace(tzinfo=timezone.utc).isoformat(),
                                "billing_currency": "USD",
                                "impressions": int(row.get("impressions", 0)),
                                "clicks": int(row.get("clicks", 0)),
                                "media_spend": str(spend),
                                "total_cost": str(spend),
                                "source_connector_id": self.connector_id,
                                "idempotency_key": f"reddit-{self.connector_id}-{current}-{campaign_id}",
                            }
                            await self._spend_repo.upsert(record)
                            rows_upserted += 1
                        current += timedelta(days=1)

            except Exception as exc:
                logger.error("Reddit Ads API error: %s", exc)
                errors.append(str(exc))

        return SyncResult(rows_upserted=rows_upserted, errors=errors, new_cursor={"last_sync_date": str(end)})

    async def health_check(self) -> ConnectorHealth:
        import os
        if os.getenv("AETHER_ENV", "local").lower() == "local":
            return ConnectorHealth(status="healthy", message="mock mode")

        try:
            import httpx
            account_id = self.config.get("account_id", "")
            access_token = self.config.get("access_token", "")
            if not account_id or not access_token:
                return ConnectorHealth(status="error", message="Missing account_id or access_token")
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{_BASE_URL}/accounts/{account_id}",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "User-Agent": "Aether/1.0",
                    },
                )
                if resp.status_code == 401:
                    return ConnectorHealth(status="error", message="Unauthorized — token expired or invalid")
                if resp.status_code == 403:
                    return ConnectorHealth(status="error", message="Forbidden — insufficient scope")
                resp.raise_for_status()
                return ConnectorHealth(status="healthy", message="API credentials valid")
        except Exception as exc:
            return ConnectorHealth(status="error", message=str(exc))

    async def validate_credentials(self) -> bool:
        health = await self.health_check()
        return health.status == "healthy"


def _idempotency_id(connector_id: str, key: str) -> str:
    return hashlib.sha256(f"{connector_id}:{key}".encode()).hexdigest()[:32]
