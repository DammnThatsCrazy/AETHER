"""File import connector — CSV/JSON spend record batch import."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from services.measurement.connectors.base import BaseConnector, ConnectorHealth, SyncResult
from services.measurement.repositories.spend_repo import SpendRepository

logger = logging.getLogger("aether.measurement.connectors.file_import")

_CONNECTOR_TYPE = "file_import"

_REQUIRED_COLUMNS = {"campaign_id", "period_start", "period_end", "total_cost"}


class FileImportConnector(BaseConnector):
    """Processes uploaded CSV or JSON spend files.

    Expected CSV columns (required):
      campaign_id, period_start, period_end, total_cost

    Optional CSV columns:
      platform, ad_account_id, impressions, clicks, media_spend,
      billing_currency, source_record_id

    sync_incremental() is a no-op — import is triggered via process_file().
    """

    connector_type = _CONNECTOR_TYPE

    def __init__(self, connector_id: str, tenant_id: str, config: dict[str, Any], cursor_state: dict[str, Any]) -> None:
        super().__init__(connector_id, tenant_id, config, cursor_state)
        self._spend_repo = SpendRepository()

    async def process_file(self, content: bytes, filename: str) -> dict[str, Any]:
        """Parse and import a file. Supports .csv and .json extensions."""
        if filename.lower().endswith(".json"):
            rows = _parse_json(content)
        else:
            rows = _parse_csv(content)

        imported = 0
        skipped = 0
        errors: list[str] = []

        for i, row in enumerate(rows):
            missing = _REQUIRED_COLUMNS - set(row.keys())
            if missing:
                errors.append(f"Row {i+1}: missing columns {missing}")
                skipped += 1
                continue

            idem_key = row.get("idempotency_key") or hashlib.sha256(
                f"{self.tenant_id}:{row.get('campaign_id')}:{row.get('period_start')}:{row.get('source_record_id', i)}".encode()
            ).hexdigest()

            try:
                await self._spend_repo.upsert({
                    "tenant_id": self.tenant_id,
                    "platform": row.get("platform", "import"),
                    "ad_account_id": row.get("ad_account_id"),
                    "campaign_id": row.get("campaign_id"),
                    "period_start": row.get("period_start"),
                    "period_end": row.get("period_end"),
                    "billing_currency": row.get("billing_currency", "USD"),
                    "normalized_currency": "USD",
                    "impressions": int(row.get("impressions", 0)),
                    "clicks": int(row.get("clicks", 0)),
                    "media_spend": _safe_decimal(row.get("media_spend", "0")),
                    "total_cost": _safe_decimal(row.get("total_cost", "0")),
                    "source_record_id": row.get("source_record_id"),
                    "source_connector_id": self.connector_id,
                    "idempotency_key": idem_key,
                })
                imported += 1
            except Exception as exc:
                errors.append(f"Row {i+1}: {str(exc)[:150]}")
                skipped += 1

        return {
            "filename": filename,
            "total_rows": len(rows),
            "imported": imported,
            "skipped": skipped,
            "errors": errors[:50],
        }

    async def sync_incremental(self, cursor: dict[str, Any]) -> SyncResult:
        return SyncResult(
            connector_id=self.connector_id,
            connector_type=_CONNECTOR_TYPE,
            spend_records_written=0,
            conversion_records_written=0,
            touchpoint_records_written=0,
            cursor_state=cursor,
        )

    async def backfill(self, start: datetime, end: datetime) -> SyncResult:
        return SyncResult(
            connector_id=self.connector_id,
            connector_type=_CONNECTOR_TYPE,
            spend_records_written=0,
            conversion_records_written=0,
            touchpoint_records_written=0,
            cursor_state={},
        )

    async def health_check(self) -> ConnectorHealth:
        return ConnectorHealth(
            connector_id=self.connector_id,
            connector_type=_CONNECTOR_TYPE,
            healthy=True,
            status_message="File import endpoint active",
        )

    async def validate_credentials(self) -> bool:
        return True


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_csv(content: bytes) -> list[dict[str, Any]]:
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    return [dict(row) for row in reader]


def _parse_json(content: bytes) -> list[dict[str, Any]]:
    data = json.loads(content.decode("utf-8"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "records" in data:
        return data["records"]
    return [data]


def _safe_decimal(value: Any) -> str:
    try:
        return str(Decimal(str(value)))
    except (InvalidOperation, TypeError):
        return "0"
