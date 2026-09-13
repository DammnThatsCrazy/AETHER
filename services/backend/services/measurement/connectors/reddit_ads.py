"""Reddit Ads connector — imports campaign spend via Reddit Advertising API v3."""

from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from decimal import Decimal

from services.measurement.connectors.base import BaseConnector, ConnectorHealth, SyncResult
from services.measurement.connectors.writer import CampaignMeasurementWriter, ExternalCampaignMetric

logger = logging.getLogger("aether.measurement.connectors.reddit_ads")

_CONNECTOR_TYPE = "reddit_ads"
_BASE_URL = "https://ads-api.reddit.com/api/v3"
_DEFAULT_CURRENCY = "USD"


def _resolve_billing_currency(config: dict[str, Any], row_currency: Any = None) -> tuple[str, bool]:
    """Resolve the billing currency for a spend row.

    Reddit's report rows carry spend in the account's currency but omit a
    currency code, so the code is sourced from account settings (connector
    config) unless a row/report variant provides one.

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
            logger.error("httpx not installed; Reddit Ads live sync unavailable")
            return self._sync_result(errors=["httpx not installed"])

        account_id = self._config.get("account_id", "")
        access_token = self._config.get("access_token", "")
        if not account_id or not access_token:
            return self._sync_result(errors=["Missing account_id or access_token"])

        headers = {
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "Aether/1.0",
        }
        errors: list[str] = []
        metrics_list: list[ExternalCampaignMetric] = []

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                camps_resp = await client.get(
                    f"{_BASE_URL}/accounts/{account_id}/campaigns",
                    headers=headers,
                    params={"limit": 100},
                )
                camps_resp.raise_for_status()
                campaigns = camps_resp.json().get("data", {}).get("campaigns", [])

                for campaign in campaigns:
                    ext_campaign_id = campaign.get("id", "")
                    campaign_name = campaign.get("name")
                    if not ext_campaign_id:
                        continue

                    current = start
                    while current <= end:
                        stats_resp = await client.get(
                            f"{_BASE_URL}/accounts/{account_id}/campaigns/{ext_campaign_id}/report",
                            headers=headers,
                            params={
                                "date_start": str(current),
                                "date_stop": str(current),
                                "fields": "date,spend,impressions,clicks",
                                "breakdown": "date",
                            },
                        )
                        stats_resp.raise_for_status()
                        rows = stats_resp.json().get("data", {}).get("rows", [])

                        for row in rows:
                            spend = Decimal(str(float(row.get("spend", 0)) / 100))  # cents to dollars
                            currency, currency_is_default = _resolve_billing_currency(
                                self._config, row_currency=row.get("currency")
                            )
                            source_tz = _resolve_source_timezone(
                                self._config, row_timezone=row.get("timezone")
                            )
                            raw_dimensions: dict[str, Any] = {
                                "date": str(current),
                                "campaign_id": ext_campaign_id,
                                "currency_source": "default_fallback" if currency_is_default else "provider",
                                "source_timezone": source_tz,
                            }
                            exchange_rate = row.get("exchange_rate") or self._config.get("exchange_rate")
                            if exchange_rate is not None:
                                raw_dimensions["exchange_rate"] = str(exchange_rate)
                            metrics_list.append(ExternalCampaignMetric(
                                platform=_CONNECTOR_TYPE,
                                external_account_id=account_id,
                                external_campaign_id=ext_campaign_id,
                                external_campaign_name=campaign_name,
                                period_start=datetime.combine(current, datetime.min.time()).replace(tzinfo=timezone.utc),
                                period_end=datetime.combine(current, datetime.max.time()).replace(tzinfo=timezone.utc),
                                impressions=int(row.get("impressions", 0)),
                                clicks=int(row.get("clicks", 0)),
                                spend=spend,
                                currency=currency,
                                source_timezone=source_tz,
                                raw_dimensions=raw_dimensions,
                            ))
                        current += timedelta(days=1)

            except Exception as exc:
                logger.error("Reddit Ads API error: %s", exc)
                errors.append(str(exc))

        write_result = await self._writer.write_metrics(self.tenant_id, self.connector_id, metrics_list)
        errors.extend(write_result.errors)
        return self._sync_result(
            spend_records_written=write_result.spend_records_written,
            errors=errors,
            cursor_state={"last_sync_date": str(end)},
        )

    async def health_check(self) -> ConnectorHealth:
        try:
            import httpx
            account_id = self._config.get("account_id", "")
            access_token = self._config.get("access_token", "")
            if not account_id or not access_token:
                return self._health(False, "Missing account_id or access_token")
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{_BASE_URL}/accounts/{account_id}",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "User-Agent": "Aether/1.0",
                    },
                )
                if resp.status_code == 401:
                    return self._health(False, "Unauthorized — token expired or invalid")
                if resp.status_code == 403:
                    return self._health(False, "Forbidden — insufficient scope")
                resp.raise_for_status()
                return self._health(True, "API credentials valid")
        except Exception as exc:
            return self._health(False, str(exc))

    async def validate_credentials(self) -> bool:
        health = await self.health_check()
        return health.healthy


def _idempotency_id(connector_id: str, key: str) -> str:
    return hashlib.sha256(f"{connector_id}:{key}".encode()).hexdigest()[:32]
