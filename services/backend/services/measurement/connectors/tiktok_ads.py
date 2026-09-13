"""TikTok Ads connector — imports campaign spend via TikTok Marketing API."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from decimal import Decimal

from services.measurement.connectors.base import BaseConnector, ConnectorHealth, SyncResult
from services.measurement.connectors.writer import CampaignMeasurementWriter, ExternalCampaignMetric

logger = logging.getLogger("aether.measurement.connectors.tiktok_ads")

_CONNECTOR_TYPE = "tiktok_ads"
_API_VERSION = "v1.3"
_DEFAULT_CURRENCY = "USD"


def _resolve_billing_currency(config: dict[str, Any], row_currency: Any = None) -> tuple[str, bool]:
    """Resolve the billing currency for a spend row.

    TikTok reports spend in the advertiser account's currency; the integrated
    report row does not always echo a currency code, so it is sourced from
    account settings (connector config) unless the row provides one.

    Preference order:
      1. Currency reported on the provider row (``row_currency``), if present.
      2. Account-level currency from connector config (account settings).
      3. Documented ``USD`` default, flagged as a fallback.

    Returns ``(currency_code, is_default_fallback)``.
    """
    for candidate in (
        row_currency,
        config.get("currency"),
        config.get("account_currency"),
        config.get("billing_currency"),
    ):
        if candidate:
            code = str(candidate).strip().upper()
            if code:
                return code, False
    return _DEFAULT_CURRENCY, True


def _resolve_source_timezone(config: dict[str, Any], row_timezone: Any = None) -> str:
    """Resolve the account/report timezone, preserving provider metadata when present."""
    for candidate in (
        row_timezone,
        config.get("time_zone"),
        config.get("timezone"),
        config.get("account_timezone"),
    ):
        if candidate:
            tz = str(candidate).strip()
            if tz:
                return tz
    return "UTC"


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
        self._writer = CampaignMeasurementWriter()

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
        started_at = datetime.now(timezone.utc)
        account_id = str(self._config.get("advertiser_id", ""))

        try:
            if not await self.validate_credentials():
                raise RuntimeError("TikTok Ads credentials unavailable")
            rows = await self._fetch_spend(start.date(), end.date())
            metrics_list: list[ExternalCampaignMetric] = []
            for row in rows:
                stat_date_str = str(row.get("stat_time_day", row.get("date", start.date().isoformat())))[:10]
                period_start = datetime.combine(date.fromisoformat(stat_date_str), datetime.min.time()).replace(tzinfo=timezone.utc)
                period_end = period_start + timedelta(days=1)
                currency, currency_is_default = _resolve_billing_currency(
                    self._config, row_currency=row.get("currency")
                )
                source_tz = _resolve_source_timezone(self._config, row_timezone=row.get("timezone"))
                raw_dimensions: dict[str, Any] = {
                    "stat_time_day": stat_date_str,
                    "currency_source": "default_fallback" if currency_is_default else "provider",
                    "source_timezone": source_tz,
                }
                exchange_rate = row.get("exchange_rate") or self._config.get("exchange_rate")
                if exchange_rate is not None:
                    raw_dimensions["exchange_rate"] = str(exchange_rate)
                metrics_list.append(ExternalCampaignMetric(
                    platform=_CONNECTOR_TYPE,
                    external_account_id=account_id,
                    external_campaign_id=str(row.get("campaign_id", "")),
                    external_campaign_name=row.get("campaign_name"),
                    period_start=period_start,
                    period_end=period_end,
                    impressions=int(row.get("impression", row.get("impressions", 0))),
                    clicks=int(row.get("click", row.get("clicks", 0))),
                    spend=Decimal(str(row.get("spend", "0"))),
                    currency=currency,
                    source_timezone=source_tz,
                    raw_dimensions=raw_dimensions,
                ))
            write_result = await self._writer.write_metrics(self.tenant_id, self.connector_id, metrics_list)
            errors.extend(write_result.errors)
            spend_written = write_result.spend_records_written
        except Exception as exc:
            errors.append(str(exc))
            logger.exception("TikTok Ads sync failed: connector=%s", self.connector_id)
            spend_written = 0

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
        return bool(self._config.get("access_token") and self._config.get("advertiser_id"))

    async def _fetch_spend(self, start_date: date, end_date: date) -> list[dict[str, Any]]:
        try:
            import aiohttp  # type: ignore[import]
        except ImportError:
            raise RuntimeError("aiohttp not installed — TikTok connector unavailable")

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
