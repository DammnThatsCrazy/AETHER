"""X (Twitter) Ads connector — imports campaign spend via Twitter Ads API v12."""

from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from services.measurement.connectors.base import BaseConnector, ConnectorHealth, SyncResult
from services.measurement.repositories.spend_repo import SpendRepository

logger = logging.getLogger("aether.measurement.connectors.x_ads")

_CONNECTOR_TYPE = "x_ads"
_API_VERSION = "12"
_BASE_URL = f"https://ads-api.twitter.com/{_API_VERSION}"


class XAdsConnector(BaseConnector):
    """X (Twitter) Ads spend connector via Twitter Ads API v12.

    Required config keys (stored encrypted in measurement_connectors.config):
      - access_token: OAuth 1.0a or OAuth 2.0 access token (ads:read scope)
      - access_token_secret: OAuth 1.0a access token secret (if using OAuth 1.0a)
      - consumer_key: OAuth 1.0a consumer key
      - consumer_secret: OAuth 1.0a consumer secret
      - account_id: X Ads account ID

    Cursor state:
      - last_sync_date: ISO date string of the last successfully synced day

    Rate limits: X Ads API enforces per-endpoint rate limits. Incremental sync
    fetches the last 3 days to account for late data delivery.
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
                "platform": "x_ads",
                "ad_account_id": self.config.get("account_id", ""),
                "campaign_id": f"mock-x-camp-{self.connector_id[:8]}",
                "period_start": datetime.combine(current, datetime.min.time()).replace(tzinfo=timezone.utc).isoformat(),
                "period_end": datetime.combine(current, datetime.max.time()).replace(tzinfo=timezone.utc).isoformat(),
                "billing_currency": "USD",
                "impressions": 5000,
                "clicks": 60,
                "media_spend": "90.00",
                "total_cost": "90.00",
                "source_connector_id": self.connector_id,
                "idempotency_key": f"x-{self.connector_id}-{current}",
            }
            await self._spend_repo.upsert(record)
            rows_upserted += 1
            current += timedelta(days=1)

        logger.info("X Ads mock backfill: connector=%s rows=%d", self.connector_id, rows_upserted)
        return SyncResult(rows_upserted=rows_upserted, new_cursor={"last_sync_date": str(end)})

    async def _live_backfill(self, start: date, end: date) -> SyncResult:
        try:
            import httpx
        except ImportError:
            logger.error("httpx not installed; X Ads live sync unavailable")
            return SyncResult(rows_upserted=0, errors=["httpx not installed"], new_cursor={})

        account_id = self.config.get("account_id", "")
        access_token = self.config.get("access_token", "")
        if not account_id or not access_token:
            return SyncResult(rows_upserted=0, errors=["Missing account_id or access_token"], new_cursor={})

        headers = {
            "Authorization": f"Bearer {access_token}",
        }
        rows_upserted = 0
        errors: list[str] = []

        start_str = start.strftime("%Y-%m-%dT00:00:00Z")
        end_str = end.strftime("%Y-%m-%dT23:59:59Z")

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.get(
                    f"{_BASE_URL}/accounts/{account_id}/stats/accounts/{account_id}",
                    headers=headers,
                    params={
                        "metric_groups": "BILLING",
                        "start_time": start_str,
                        "end_time": end_str,
                        "granularity": "DAY",
                        "entity": "ACCOUNT",
                        "placement": "ALL_ON_TWITTER",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                data_items = data.get("data", [])

                for item in data_items:
                    id_data = item.get("id_data", [])
                    for segment in id_data:
                        metrics = segment.get("metrics", {})
                        billed_charge_local_micro = metrics.get("billed_charge_local_micro", [])
                        impressions_list = metrics.get("impressions", [])
                        clicks_list = metrics.get("clicks", [])
                        # Each element corresponds to one day in the requested range
                        current = start
                        for i, spend_micro in enumerate(billed_charge_local_micro):
                            if current > end:
                                break
                            spend = (spend_micro or 0) / 1_000_000
                            record = {
                                "spend_record_id": _idempotency_id(self.connector_id, str(current)),
                                "tenant_id": self.tenant_id,
                                "platform": "x_ads",
                                "ad_account_id": account_id,
                                "campaign_id": account_id,
                                "period_start": datetime.combine(current, datetime.min.time()).replace(tzinfo=timezone.utc).isoformat(),
                                "period_end": datetime.combine(current, datetime.max.time()).replace(tzinfo=timezone.utc).isoformat(),
                                "billing_currency": "USD",
                                "impressions": int(impressions_list[i]) if i < len(impressions_list) else 0,
                                "clicks": int(clicks_list[i]) if i < len(clicks_list) else 0,
                                "media_spend": str(spend),
                                "total_cost": str(spend),
                                "source_connector_id": self.connector_id,
                                "idempotency_key": f"x-{self.connector_id}-{current}",
                            }
                            await self._spend_repo.upsert(record)
                            rows_upserted += 1
                            current += timedelta(days=1)
            except Exception as exc:
                logger.error("X Ads API error: %s", exc)
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
                    headers={"Authorization": f"Bearer {access_token}"},
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
