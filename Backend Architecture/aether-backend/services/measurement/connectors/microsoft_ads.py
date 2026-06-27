"""Microsoft Advertising connector — imports campaign spend via Bing Ads API v13."""

from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from decimal import Decimal

from services.measurement.connectors.base import BaseConnector, ConnectorHealth, SyncResult
from services.measurement.connectors.writer import CampaignMeasurementWriter, ExternalCampaignMetric

logger = logging.getLogger("aether.measurement.connectors.microsoft_ads")

_CONNECTOR_TYPE = "microsoft_ads"
_API_VERSION = "v13"
_BASE_URL = "https://reporting.api.bingads.microsoft.com/Api/Advertiser/Reporting"
_OAUTH_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"


class MicrosoftAdsConnector(BaseConnector):
    """Microsoft Advertising (Bing Ads) spend connector via Bing Ads API v13.

    Required config keys (stored encrypted in measurement_connectors.config):
      - client_id: Azure app registration client ID
      - client_secret: Azure app registration client secret
      - refresh_token: OAuth 2.0 refresh token (bingads.manage scope)
      - customer_id: Microsoft Advertising customer ID
      - account_id: Microsoft Advertising account ID

    Cursor state:
      - last_sync_date: ISO date string of the last successfully synced day

    Rate limits: Bing Ads API enforces per-customer throttling. Reporting API
    uses async submit-and-poll pattern. Incremental sync fetches the last 3 days.
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
        import os
        if os.getenv("AETHER_ENV", "local").lower() == "local":
            return await self._mock_backfill(start, end)
        return await self._live_backfill(start, end)

    async def _mock_backfill(self, start: date, end: date) -> SyncResult:
        """Return a mock SyncResult for local/test environments."""
        account_id = self.config.get("account_id", "")
        metrics_list: list[ExternalCampaignMetric] = []
        current = start
        while current <= end:
            metrics_list.append(ExternalCampaignMetric(
                platform=_CONNECTOR_TYPE,
                external_account_id=account_id,
                external_campaign_id=f"mock-msft-camp-{self.connector_id[:8]}",
                external_campaign_name="Mock Microsoft Ads Campaign",
                period_start=datetime.combine(current, datetime.min.time()).replace(tzinfo=timezone.utc),
                period_end=datetime.combine(current, datetime.max.time()).replace(tzinfo=timezone.utc),
                impressions=6500, clicks=85, spend=Decimal("95.00"), currency="USD",
            ))
            current += timedelta(days=1)

        write_result = await self._writer.write_metrics(self.tenant_id, self.connector_id, metrics_list)
        logger.info("Microsoft Ads mock backfill: connector=%s rows=%d", self.connector_id, write_result.spend_records_written)
        return SyncResult(rows_upserted=write_result.spend_records_written, new_cursor={"last_sync_date": str(end)})

    async def _get_access_token(self) -> str | None:
        """Exchange refresh token for a fresh access token."""
        try:
            import httpx
            resp = await httpx.AsyncClient(timeout=15).post(
                _OAUTH_URL,
                data={
                    "grant_type": "refresh_token",
                    "client_id": self.config.get("client_id", ""),
                    "client_secret": self.config.get("client_secret", ""),
                    "refresh_token": self.config.get("refresh_token", ""),
                    "scope": "https://ads.microsoft.com/msads.manage",
                },
            )
            resp.raise_for_status()
            return resp.json().get("access_token")
        except Exception as exc:
            logger.error("Microsoft Ads token refresh failed: %s", exc)
            return None

    async def _live_backfill(self, start: date, end: date) -> SyncResult:
        try:
            import httpx
        except ImportError:
            logger.error("httpx not installed; Microsoft Ads live sync unavailable")
            return SyncResult(rows_upserted=0, errors=["httpx not installed"], new_cursor={})

        account_id = self.config.get("account_id", "")
        customer_id = self.config.get("customer_id", "")
        if not account_id or not customer_id:
            return SyncResult(rows_upserted=0, errors=["Missing account_id or customer_id"], new_cursor={})

        access_token = await self._get_access_token()
        if not access_token:
            return SyncResult(rows_upserted=0, errors=["Failed to obtain access token"], new_cursor={})

        errors: list[str] = []

        headers = {
            "Authorization": f"Bearer {access_token}",
            "CustomerAccountId": account_id,
            "CustomerId": customer_id,
            "DeveloperToken": self.config.get("developer_token", ""),
        }

        # Bing Ads Reporting API: submit report request, poll for download URL
        report_request = {
            "ReportRequest": {
                "__type": "CampaignPerformanceReportRequest",
                "Format": "Csv",
                "ReportName": "AetherSpendSync",
                "ReturnOnlyCompleteData": False,
                "Aggregation": "Daily",
                "Columns": ["TimePeriod", "CampaignId", "CampaignName", "Impressions", "Clicks", "Spend"],
                "Filter": None,
                "Scope": {
                    "AccountIds": [account_id],
                },
                "Time": {
                    "CustomDateRangeStart": {
                        "Day": start.day,
                        "Month": start.month,
                        "Year": start.year,
                    },
                    "CustomDateRangeEnd": {
                        "Day": end.day,
                        "Month": end.month,
                        "Year": end.year,
                    },
                    "PredefinedTime": None,
                },
            }
        }

        async with httpx.AsyncClient(timeout=60) as client:
            try:
                # Submit report
                submit_resp = await client.post(
                    f"{_BASE_URL}/{_API_VERSION}/Reporting/SubmitGenerateReport",
                    headers={**headers, "Content-Type": "application/json"},
                    json=report_request,
                )
                submit_resp.raise_for_status()
                report_request_id = submit_resp.json().get("ReportRequestId")
                if not report_request_id:
                    raise ValueError("No report request ID returned")

                # Poll for completion (max 10 attempts)
                import asyncio
                download_url = None
                for attempt in range(10):
                    await asyncio.sleep(3 * (attempt + 1))
                    status_resp = await client.get(
                        f"{_BASE_URL}/{_API_VERSION}/Reporting/PollGenerateReport",
                        headers=headers,
                        params={"ReportRequestId": report_request_id},
                    )
                    status_resp.raise_for_status()
                    status_data = status_resp.json()
                    report_status = status_data.get("ReportRequestStatus", {}).get("Status")
                    if report_status == "Success":
                        download_url = status_data.get("ReportRequestStatus", {}).get("ReportDownloadUrl")
                        break
                    if report_status in ("Error", "Expired"):
                        raise ValueError(f"Report generation failed with status: {report_status}")

                if not download_url:
                    raise ValueError("Report did not complete within polling window")

                # Download and parse CSV report
                import io
                import csv
                dl_resp = await client.get(download_url)
                dl_resp.raise_for_status()
                reader = csv.DictReader(io.StringIO(dl_resp.text))
                metrics_list: list[ExternalCampaignMetric] = []
                for row in reader:
                    try:
                        period_str = row.get("TimePeriod", "")
                        period_date = date.fromisoformat(period_str) if period_str else start
                        ext_campaign_id = str(row.get("CampaignId", ""))
                        campaign_name = row.get("CampaignName")
                        spend = Decimal(str(float(row.get("Spend", 0) or 0)))
                        metrics_list.append(ExternalCampaignMetric(
                            platform=_CONNECTOR_TYPE,
                            external_account_id=account_id,
                            external_campaign_id=ext_campaign_id,
                            external_campaign_name=campaign_name,
                            period_start=datetime.combine(period_date, datetime.min.time()).replace(tzinfo=timezone.utc),
                            period_end=datetime.combine(period_date, datetime.max.time()).replace(tzinfo=timezone.utc),
                            impressions=int(row.get("Impressions", 0) or 0),
                            clicks=int(row.get("Clicks", 0) or 0),
                            spend=spend,
                            currency="USD",
                            raw_dimensions={"TimePeriod": period_str, "CampaignId": ext_campaign_id},
                        ))
                    except Exception as row_exc:
                        logger.warning("Microsoft Ads row parse error: %s", row_exc)

            except Exception as exc:
                logger.error("Microsoft Ads API error: %s", exc)
                errors.append(str(exc))
                metrics_list = []

        write_result = await self._writer.write_metrics(self.tenant_id, self.connector_id, metrics_list)
        errors.extend(write_result.errors)
        return SyncResult(rows_upserted=write_result.spend_records_written, errors=errors, new_cursor={"last_sync_date": str(end)})

    async def health_check(self) -> ConnectorHealth:
        import os
        if os.getenv("AETHER_ENV", "local").lower() == "local":
            return ConnectorHealth(status="healthy", message="mock mode")

        try:
            account_id = self.config.get("account_id", "")
            customer_id = self.config.get("customer_id", "")
            if not account_id or not customer_id:
                return ConnectorHealth(status="error", message="Missing account_id or customer_id")

            access_token = await self._get_access_token()
            if not access_token:
                return ConnectorHealth(status="error", message="Failed to refresh access token — check client credentials or refresh_token")

            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://clientcenter.api.bingads.microsoft.com/Api/CustomerManagement/v13/Account",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "CustomerAccountId": account_id,
                        "CustomerId": customer_id,
                        "DeveloperToken": self.config.get("developer_token", ""),
                    },
                    params={"AccountId": account_id},
                )
                if resp.status_code == 401:
                    return ConnectorHealth(status="error", message="Unauthorized — token invalid")
                resp.raise_for_status()
                return ConnectorHealth(status="healthy", message="API credentials valid")
        except Exception as exc:
            return ConnectorHealth(status="error", message=str(exc))

    async def validate_credentials(self) -> bool:
        health = await self.health_check()
        return health.status == "healthy"


def _idempotency_id(connector_id: str, key: str) -> str:
    return hashlib.sha256(f"{connector_id}:{key}".encode()).hexdigest()[:32]
