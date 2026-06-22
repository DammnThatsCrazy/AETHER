"""TikTok Ads connector — imports campaign spend via TikTok Marketing API."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from services.measurement.connectors.base import BaseConnector, ConnectorHealth, SyncResult
from services.measurement.repositories.spend_repo import SpendRepository

logger = logging.getLogger("aether.measurement.connectors.tiktok_ads")

_CONNECTOR_TYPE = "tiktok_ads"
_API_VERSION = "v1.3"


class TikTokAdsConnector(BaseConnector):
    """TikTok Ads spend connector via TikTok Marketing API.

    Required config keys:
      - access_token: TikTok API access token
      - advertiser_id: TikTok advertiser account ID

    Cursor state:
      - last_sync_date: ISO date of last successful sync
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
        return await self.backfill(
            datetime(start.year, start.month, start.day, tzinfo=timezone.utc),
            datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=timezone.utc),
        )

    async def backfill(self, start: datetime, end: datetime) -> SyncResult:
        errors: list[str] = []
        spend_written = 0
        started_at = datetime.now(timezone.utc)

        try:
            rows = await self._fetch_spend(start.date(), end.date())
            for row in rows:
                idem_key = self._make_spend_idem_key(
                    str(row.get("campaign_id")),
                    str(row.get("stat_time_day", row.get("date"))),
                    "daily",
                )
                stat_date_str = str(row.get("stat_time_day", row.get("date", start.date().isoformat())))[:10]
                period_start = datetime.combine(
                    date.fromisoformat(stat_date_str), datetime.min.time()
                ).replace(tzinfo=timezone.utc)
                period_end = period_start + timedelta(days=1)

                await self._spend_repo.upsert({
                    "tenant_id": self.tenant_id,
                    "platform": _CONNECTOR_TYPE,
                    "ad_account_id": self._config.get("advertiser_id"),
                    "campaign_id": str(row.get("campaign_id")),
                    "period_start": period_start.isoformat(),
                    "period_end": period_end.isoformat(),
                    "billing_currency": "USD",
                    "normalized_currency": "USD",
                    "impressions": int(row.get("impression", row.get("impressions", 0))),
                    "clicks": int(row.get("click", row.get("clicks", 0))),
                    "media_spend": str(row.get("spend", "0")),
                    "total_cost": str(row.get("spend", "0")),
                    "source_record_id": idem_key,
                    "source_connector_id": self.connector_id,
                    "idempotency_key": idem_key,
                })
                spend_written += 1

        except Exception as exc:
            errors.append(str(exc))
            logger.exception("TikTok Ads sync failed: connector=%s", self.connector_id)

        return SyncResult(
            connector_id=self.connector_id,
            connector_type=_CONNECTOR_TYPE,
            spend_records_written=spend_written,
            conversion_records_written=0,
            touchpoint_records_written=0,
            errors=errors,
            cursor_state={"last_sync_date": end.date().isoformat()},
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
        )

    async def health_check(self) -> ConnectorHealth:
        valid = await self.validate_credentials()
        return ConnectorHealth(
            connector_id=self.connector_id,
            connector_type=_CONNECTOR_TYPE,
            healthy=valid,
            status_message="Connected" if valid else "Invalid access token",
        )

    async def validate_credentials(self) -> bool:
        import os
        if os.getenv("AETHER_ENV", "local").lower() == "local":
            return True
        return bool(self._config.get("access_token") and self._config.get("advertiser_id"))

    async def _fetch_spend(self, start_date: date, end_date: date) -> list[dict[str, Any]]:
        import os
        if os.getenv("AETHER_ENV", "local").lower() == "local":
            return []

        try:
            import aiohttp  # type: ignore[import]
        except ImportError:
            logger.warning("aiohttp not installed — TikTok connector requires aiohttp")
            return []

        token = self._config.get("access_token")
        advertiser_id = self._config.get("advertiser_id")
        url = f"https://business-api.tiktok.com/open_api/{_API_VERSION}/report/integrated/get/"

        headers = {"Access-Token": token}
        body = {
            "advertiser_id": advertiser_id,
            "report_type": "BASIC",
            "data_level": "AUCTION_CAMPAIGN",
            "dimensions": ["campaign_id", "stat_time_day"],
            "metrics": ["campaign_name", "impressions", "clicks", "spend"],
            "start_date": str(start_date),
            "end_date": str(end_date),
            "page_size": 1000,
        }

        rows = []
        async with aiohttp.ClientSession() as session:
            page = 1
            while True:
                body["page"] = page
                async with session.post(
                    url, json=body, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        raise RuntimeError(f"TikTok API error {resp.status}: {text[:200]}")
                    result = await resp.json()

                if result.get("code") != 0:
                    raise RuntimeError(f"TikTok API error: {result.get('message')}")

                page_data = result.get("data", {}).get("list", [])
                rows.extend(page_data)

                page_info = result.get("data", {}).get("page_info", {})
                total_page = page_info.get("total_page", 1)
                if page >= total_page:
                    break
                page += 1

        return rows
