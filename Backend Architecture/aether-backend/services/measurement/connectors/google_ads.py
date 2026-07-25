"""Google Ads connector — imports campaign spend via Google Ads API."""

from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional

from services.measurement.connectors.base import BaseConnector, ConnectorHealth, SyncResult
from services.measurement.connectors.writer import CampaignMeasurementWriter, ExternalCampaignMetric

logger = logging.getLogger("aether.measurement.connectors.google_ads")

_CONNECTOR_TYPE = "google_ads"


class GoogleAdsConnector(BaseConnector):
    """Google Ads spend connector using the Google Ads API v18.

    Required config keys (stored encrypted in measurement_connectors.config):
      - customer_id: Google Ads customer/account ID (without hyphens)
      - developer_token: Google Ads API developer token
      - client_id: OAuth2 client ID
      - client_secret: OAuth2 client secret
      - refresh_token: OAuth2 refresh token

    Cursor state:
      - last_sync_date: ISO date string of the last successfully synced day

    Rate limits: Google Ads API allows 1000 operations/day (standard access).
    Incremental sync fetches the last 7 days to handle late-arriving data.
    """

    connector_type = _CONNECTOR_TYPE

    def __init__(self, connector_id: str, tenant_id: str, config: dict[str, Any], cursor_state: dict[str, Any]) -> None:
        super().__init__(connector_id, tenant_id, config, cursor_state)
        self._writer = CampaignMeasurementWriter()

    async def sync_incremental(self, cursor: dict[str, Any]) -> SyncResult:
        last_date_str = cursor.get("last_sync_date")
        if last_date_str:
            try:
                start = date.fromisoformat(last_date_str) - timedelta(days=7)
            except ValueError:
                start = date.today() - timedelta(days=7)
        else:
            start = date.today() - timedelta(days=7)

        end = date.today()
        return await self.backfill(
            datetime(start.year, start.month, start.day, tzinfo=timezone.utc),
            datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=timezone.utc),
        )

    async def backfill(self, start: datetime, end: datetime) -> SyncResult:
        errors: list[str] = []
        started_at = datetime.now(timezone.utc)
        account_id = str(self._config.get("customer_id", ""))

        try:
            client = await self._get_client()
            if client is None:
                raise RuntimeError("Google Ads credentials or SDK unavailable")
            rows = await self._fetch_campaign_spend(client, start.date(), end.date())

            metrics_list: list[ExternalCampaignMetric] = []
            for row in rows:
                period_start = datetime.combine(
                    date.fromisoformat(str(row["date"])), datetime.min.time()
                ).replace(tzinfo=timezone.utc)
                period_end = period_start + timedelta(days=1)
                metrics_list.append(ExternalCampaignMetric(
                    platform=_CONNECTOR_TYPE,
                    external_account_id=account_id,
                    external_campaign_id=str(row.get("campaign_id", "")),
                    external_campaign_name=row.get("campaign_name"),
                    period_start=period_start,
                    period_end=period_end,
                    impressions=int(row.get("impressions", 0)),
                    clicks=int(row.get("clicks", 0)),
                    spend=Decimal(str(row.get("cost_micros", 0) / 1_000_000)),
                    currency=row.get("currency", "USD"),
                    raw_dimensions={"date": str(row.get("date"))},
                ))

            write_result = await self._writer.write_metrics(
                self.tenant_id, self.connector_id, metrics_list
            )
            errors.extend(write_result.errors)
            spend_written = write_result.spend_records_written

        except Exception as exc:
            errors.append(str(exc))
            logger.exception("Google Ads sync failed: connector=%s", self.connector_id)
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
        try:
            client = await self._get_client()
            if client is None:
                return ConnectorHealth(
                    connector_id=self.connector_id,
                    connector_type=_CONNECTOR_TYPE,
                    healthy=False,
                    status_message="Client initialization failed — check credentials",
                )
            return ConnectorHealth(
                connector_id=self.connector_id,
                connector_type=_CONNECTOR_TYPE,
                healthy=True,
                status_message="Connected",
            )
        except Exception as exc:
            return ConnectorHealth(
                connector_id=self.connector_id,
                connector_type=_CONNECTOR_TYPE,
                healthy=False,
                status_message=str(exc)[:200],
            )

    async def validate_credentials(self) -> bool:
        try:
            client = await self._get_client()
            return client is not None
        except Exception:
            return False

    async def _get_client(self) -> Optional[Any]:
        """Return an authenticated Google Ads API client.

        Missing credentials or SDK support are unavailable states in every
        environment; local development must not silently simulate a provider.
        """
        required = ("developer_token", "client_id", "client_secret", "refresh_token")
        if any(not self._config.get(key) for key in required):
            return None
        try:
            from google.ads.googleads.client import GoogleAdsClient as _GAC  # type: ignore[import]
            credentials = {
                "developer_token": self._config.get("developer_token"),
                "client_id": self._config.get("client_id"),
                "client_secret": self._config.get("client_secret"),
                "refresh_token": self._config.get("refresh_token"),
                "use_proto_plus": True,
            }
            return _GAC.load_from_dict(credentials)
        except ImportError:
            logger.warning("google-ads package not installed")
            return None

    async def _fetch_campaign_spend(
        self,
        client: Any,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        customer_id = self._config.get("customer_id", "")
        ga_service = client.get_service("GoogleAdsService")
        query = f"""
            SELECT
                campaign.id,
                campaign.name,
                metrics.impressions,
                metrics.clicks,
                metrics.cost_micros,
                segments.date
            FROM campaign
            WHERE segments.date BETWEEN '{start_date}' AND '{end_date}'
              AND campaign.status = 'ENABLED'
        """
        response = ga_service.search(customer_id=customer_id, query=query)
        rows = []
        for row in response:
            rows.append({
                "campaign_id": row.campaign.id,
                "campaign_name": row.campaign.name,
                "date": row.segments.date,
                "impressions": row.metrics.impressions,
                "clicks": row.metrics.clicks,
                "cost_micros": row.metrics.cost_micros,
                "currency": "USD",
            })
        return rows
