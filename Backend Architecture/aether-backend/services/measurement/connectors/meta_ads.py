"""Meta Ads connector — imports campaign spend via Meta Marketing API."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from services.measurement.connectors.base import BaseConnector, ConnectorHealth, SyncResult
from services.measurement.repositories.spend_repo import SpendRepository

logger = logging.getLogger("aether.measurement.connectors.meta_ads")

_CONNECTOR_TYPE = "meta_ads"
_API_VERSION = "v19.0"


class MetaAdsConnector(BaseConnector):
    """Meta Ads (Facebook/Instagram) spend connector via Meta Marketing API.

    Required config keys (stored encrypted in measurement_connectors.config):
      - access_token: Long-lived Meta user access token or system user token
      - ad_account_id: Meta ad account ID (format: act_<id>)

    Cursor state:
      - last_sync_date: ISO date string of the last successfully synced day

    Rate limits: Meta throttles per-ad-account; uses cursor-based pagination
    (after parameter) to fetch without offset drift.
    Incremental sync fetches the last 3 days to handle late data delivery.
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
                    str(row.get("date_start")),
                    "daily",
                )
                period_start = datetime.combine(
                    date.fromisoformat(str(row["date_start"])), datetime.min.time()
                ).replace(tzinfo=timezone.utc)
                period_end = period_start + timedelta(days=1)

                await self._spend_repo.upsert({
                    "tenant_id": self.tenant_id,
                    "platform": _CONNECTOR_TYPE,
                    "ad_account_id": self._config.get("ad_account_id"),
                    "campaign_id": str(row.get("campaign_id")),
                    "period_start": period_start.isoformat(),
                    "period_end": period_end.isoformat(),
                    "billing_currency": row.get("currency", "USD"),
                    "normalized_currency": "USD",
                    "impressions": int(row.get("impressions", 0)),
                    "clicks": int(row.get("clicks", 0)),
                    "media_spend": str(row.get("spend", "0")),
                    "total_cost": str(row.get("spend", "0")),
                    "source_record_id": idem_key,
                    "source_connector_id": self.connector_id,
                    "idempotency_key": idem_key,
                })
                spend_written += 1

        except Exception as exc:
            errors.append(str(exc))
            logger.exception("Meta Ads sync failed: connector=%s", self.connector_id)

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
            valid = await self.validate_credentials()
            if not valid:
                return ConnectorHealth(
                    connector_id=self.connector_id,
                    connector_type=_CONNECTOR_TYPE,
                    healthy=False,
                    status_message="Invalid or expired access token",
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
        import os
        if os.getenv("AETHER_ENV", "local").lower() == "local":
            return True
        token = self._config.get("access_token")
        return bool(token and len(token) > 10)

    async def _fetch_spend(self, start_date: date, end_date: date) -> list[dict[str, Any]]:
        import os
        if os.getenv("AETHER_ENV", "local").lower() == "local":
            return []

        try:
            import aiohttp  # type: ignore[import]
        except ImportError:
            logger.warning("aiohttp not installed — Meta Ads connector requires aiohttp")
            return []

        token = self._config.get("access_token")
        ad_account_id = self._config.get("ad_account_id")
        url = f"https://graph.facebook.com/{_API_VERSION}/{ad_account_id}/insights"
        params = {
            "access_token": token,
            "fields": "campaign_id,campaign_name,impressions,clicks,spend,date_start,date_stop",
            "level": "campaign",
            "time_range": f'{{"since":"{start_date}","until":"{end_date}"}}',
            "time_increment": 1,
            "limit": 500,
        }

        rows = []
        async with aiohttp.ClientSession() as session:
            after: Optional[str] = None
            while True:
                if after:
                    params["after"] = after
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        raise RuntimeError(f"Meta API error {resp.status}: {text[:200]}")
                    body = await resp.json()

                data = body.get("data", [])
                rows.extend(data)

                paging = body.get("paging", {})
                cursors = paging.get("cursors", {})
                after = cursors.get("after")
                if not after or not data:
                    break

        return rows
