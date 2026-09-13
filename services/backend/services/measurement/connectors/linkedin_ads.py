"""LinkedIn Ads connector — imports campaign spend via LinkedIn Marketing API."""

from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from decimal import Decimal

from services.measurement.connectors.base import BaseConnector, ConnectorHealth, SyncResult
from services.measurement.connectors.writer import CampaignMeasurementWriter, ExternalCampaignMetric

logger = logging.getLogger("aether.measurement.connectors.linkedin_ads")

_CONNECTOR_TYPE = "linkedin_ads"
_API_VERSION = "202401"
_BASE_URL = "https://api.linkedin.com/rest"
_DEFAULT_CURRENCY = "USD"


def _resolve_billing_currency(config: dict[str, Any], row_currency: Any = None) -> tuple[str, bool]:
    """Resolve the billing currency for a spend row.

    LinkedIn reports spend as ``costInLocalCurrency`` — the ad account's local
    currency — but the ``adAnalytics`` element does not echo a currency code, so
    the code is sourced from account settings (connector config).

    Preference order:
      1. Currency reported on the provider element (``row_currency``), if present.
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


class LinkedInAdsConnector(BaseConnector):
    """LinkedIn Ads spend connector via LinkedIn Marketing API.

    Required config keys (stored encrypted in measurement_connectors.config):
      - access_token: OAuth 2.0 access token (r_ads_reporting scope required)
      - ad_account_id: LinkedIn ad account ID (urn:li:sponsoredAccount:<id>)

    Cursor state:
      - last_sync_date: ISO date string of the last successfully synced day

    Rate limits: LinkedIn enforces 100 requests/day per app for campaign analytics.
    Incremental sync fetches the last 3 days to account for late data delivery.
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
        return await self.backfill(start, end)

    async def backfill(self, start: date, end: date) -> SyncResult:
        return await self._live_backfill(start, end)

    async def _live_backfill(self, start: date, end: date) -> SyncResult:
        try:
            import httpx
        except ImportError:
            logger.error("httpx not installed; LinkedIn live sync unavailable")
            return self._sync_result(errors=["httpx not installed"])

        access_token = self._config.get("access_token", "")
        ad_account_id = self._config.get("ad_account_id", "")
        if not access_token or not ad_account_id:
            return self._sync_result(errors=["Missing access_token or ad_account_id"])

        headers = {
            "Authorization": f"Bearer {access_token}",
            "LinkedIn-Version": _API_VERSION,
            "X-Restli-Protocol-Version": "2.0.0",
        }
        rows_upserted = 0
        errors: list[str] = []

        start_ms = int(datetime.combine(start, datetime.min.time()).replace(tzinfo=timezone.utc).timestamp() * 1000)
        end_ms = int(datetime.combine(end, datetime.max.time()).replace(tzinfo=timezone.utc).timestamp() * 1000)

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.get(
                    f"{_BASE_URL}/adAnalytics",
                    headers=headers,
                    params={
                        "q": "analytics",
                        "pivot": "CAMPAIGN",
                        "dateRange.start.year": start.year,
                        "dateRange.start.month": start.month,
                        "dateRange.start.day": start.day,
                        "dateRange.end.year": end.year,
                        "dateRange.end.month": end.month,
                        "dateRange.end.day": end.day,
                        "timeGranularity": "DAILY",
                        "accounts": f"urn:li:sponsoredAccount:{ad_account_id}",
                        "fields": "dateRange,impressions,clicks,costInLocalCurrency,pivot,pivotValue",
                        "count": 100,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                elements = data.get("elements", [])

                metrics_list: list[ExternalCampaignMetric] = []
                for el in elements:
                    date_range = el.get("dateRange", {})
                    dr_start = date_range.get("start", {})
                    period_date = date(dr_start.get("year", start.year), dr_start.get("month", start.month), dr_start.get("day", start.day))
                    campaign_urn = el.get("pivotValue", "")
                    spend = el.get("costInLocalCurrency", 0)
                    currency, currency_is_default = _resolve_billing_currency(
                        self._config, row_currency=el.get("currency")
                    )
                    source_tz = _resolve_source_timezone(self._config)
                    raw_dimensions: dict[str, Any] = {
                        "pivotValue": campaign_urn,
                        "date": str(period_date),
                        "currency_source": "default_fallback" if currency_is_default else "provider",
                        "source_timezone": source_tz,
                    }
                    exchange_rate = el.get("exchangeRate") or self._config.get("exchange_rate")
                    if exchange_rate is not None:
                        raw_dimensions["exchange_rate"] = str(exchange_rate)
                    metrics_list.append(ExternalCampaignMetric(
                        platform=_CONNECTOR_TYPE,
                        external_account_id=ad_account_id,
                        external_campaign_id=campaign_urn,
                        period_start=datetime.combine(period_date, datetime.min.time()).replace(tzinfo=timezone.utc),
                        period_end=datetime.combine(period_date, datetime.max.time()).replace(tzinfo=timezone.utc),
                        impressions=int(el.get("impressions", 0)),
                        clicks=int(el.get("clicks", 0)),
                        spend=Decimal(str(spend)),
                        currency=currency,
                        source_timezone=source_tz,
                        raw_dimensions=raw_dimensions,
                    ))
                write_result = await self._writer.write_metrics(self.tenant_id, self.connector_id, metrics_list)
                rows_upserted = write_result.spend_records_written
                errors.extend(write_result.errors)
            except Exception as exc:
                logger.error("LinkedIn API error: %s", exc)
                errors.append(str(exc))

        return self._sync_result(
            spend_records_written=rows_upserted,
            errors=errors,
            cursor_state={"last_sync_date": str(end)},
        )

    async def health_check(self) -> ConnectorHealth:
        try:
            import httpx
            access_token = self._config.get("access_token", "")
            if not access_token:
                return self._health(False, "Missing access_token")
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{_BASE_URL}/adAccounts",
                    headers={"Authorization": f"Bearer {access_token}", "LinkedIn-Version": _API_VERSION},
                    params={"q": "search"},
                )
                if resp.status_code == 401:
                    return self._health(False, "Unauthorized — token expired or invalid")
                resp.raise_for_status()
                return self._health(True, "API credentials valid")
        except Exception as exc:
            return self._health(False, str(exc))

    async def validate_credentials(self) -> bool:
        health = await self.health_check()
        return health.healthy


def _idempotency_id(connector_id: str, key: str) -> str:
    return hashlib.sha256(f"{connector_id}:{key}".encode()).hexdigest()[:32]
