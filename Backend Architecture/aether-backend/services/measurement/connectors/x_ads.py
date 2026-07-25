"""X (Twitter) Ads connector — imports campaign spend via Twitter Ads API v12."""

from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from decimal import Decimal

from services.measurement.connectors.base import BaseConnector, ConnectorHealth, SyncResult
from services.measurement.connectors.writer import CampaignMeasurementWriter, ExternalCampaignMetric

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
            logger.error("httpx not installed; X Ads live sync unavailable")
            return self._sync_result(errors=["httpx not installed"])

        account_id = self._config.get("account_id", "")
        access_token = self._config.get("access_token", "")
        if not account_id or not access_token:
            return self._sync_result(errors=["Missing account_id or access_token"])

        headers = {"Authorization": f"Bearer {access_token}"}
        errors: list[str] = []
        metrics_list: list[ExternalCampaignMetric] = []

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
                        seg_metrics = segment.get("metrics", {})
                        billed_charge_local_micro = seg_metrics.get("billed_charge_local_micro", [])
                        impressions_list = seg_metrics.get("impressions", [])
                        clicks_list = seg_metrics.get("clicks", [])
                        # Each element in the arrays corresponds to one day in the requested range
                        current = start
                        for i, spend_micro in enumerate(billed_charge_local_micro):
                            if current > end:
                                break
                            spend = Decimal(str((spend_micro or 0) / 1_000_000))
                            metrics_list.append(ExternalCampaignMetric(
                                platform=_CONNECTOR_TYPE,
                                external_account_id=account_id,
                                external_campaign_id=account_id,  # X Ads account-level stats endpoint; no campaign granularity
                                period_start=datetime.combine(current, datetime.min.time()).replace(tzinfo=timezone.utc),
                                period_end=datetime.combine(current, datetime.max.time()).replace(tzinfo=timezone.utc),
                                impressions=int(impressions_list[i]) if i < len(impressions_list) else 0,
                                clicks=int(clicks_list[i]) if i < len(clicks_list) else 0,
                                spend=spend,
                                currency="USD",
                                raw_dimensions={"date": str(current)},
                            ))
                            current += timedelta(days=1)
            except Exception as exc:
                logger.error("X Ads API error: %s", exc)
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
                    headers={"Authorization": f"Bearer {access_token}"},
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
