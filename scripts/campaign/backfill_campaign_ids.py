"""
backfill_campaign_ids.py — Canonical campaign ID backfill for spend_records.

Scans spend_records rows where campaign_id looks like a provider text ID
(not a UUID), resolves the canonical Aether campaign_id via the registry,
and updates the row in place.

Usage:
    python scripts/campaign/backfill_campaign_ids.py [options]

Options:
    --dry-run               Print actions without writing to the database
    --batch-size INT        Rows per batch (default: 500)
    --tenant-id TEXT        Restrict to a single tenant
    --cursor TEXT           Resume from a spend_record_id cursor
    --log-file PATH         Write JSON audit log to file (default: stdout summary only)

Exit codes:
    0  Completed successfully (all rows resolved or intentionally skipped)
    1  Fatal error (DB connection failure, unrecoverable exception)
    2  Partial success (some rows failed or remain unresolved — see log)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("aether.scripts.backfill_campaign_ids")

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

REPORT_FIELDS = [
    "scanned",
    "already_canonical",
    "mapped",
    "newly_registered",
    "ambiguous",
    "unresolved",
    "failed",
    "skipped",
]


def _is_uuid(value: str) -> bool:
    return bool(_UUID_RE.match(value))


class BackfillReport:
    def __init__(self) -> None:
        self.scanned = 0
        self.already_canonical = 0
        self.mapped = 0
        self.newly_registered = 0
        self.ambiguous = 0
        self.unresolved = 0
        self.failed = 0
        self.skipped = 0
        self.errors: list[str] = []
        self.started_at = datetime.now(timezone.utc)
        self.completed_at: Optional[datetime] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            **{f: getattr(self, f) for f in REPORT_FIELDS},
            "errors": self.errors[:50],  # cap to avoid enormous logs
        }

    def summary(self) -> str:
        return (
            f"scanned={self.scanned} "
            f"already_canonical={self.already_canonical} "
            f"mapped={self.mapped} "
            f"newly_registered={self.newly_registered} "
            f"ambiguous={self.ambiguous} "
            f"unresolved={self.unresolved} "
            f"failed={self.failed} "
            f"skipped={self.skipped}"
        )


async def _get_pool():
    """Return DB pool or None (local mode)."""
    if os.getenv("AETHER_ENV", "local").lower() == "local":
        return None
    try:
        from repositories.repos import get_pool  # type: ignore[import]
        return await get_pool()
    except Exception as exc:
        logger.error("Failed to get DB pool: %s", exc)
        return None


async def _fetch_batch(
    pool,
    batch_size: int,
    cursor: Optional[str],
    tenant_id: Optional[str],
) -> list[dict[str, Any]]:
    """Fetch a batch of spend_records where campaign_id is not a UUID."""
    if pool is None:
        return []

    filters = ["(campaign_resolution_status = 'not_applicable' OR campaign_resolution_status IS NULL)"]
    params: list[Any] = []
    param_idx = 1

    if cursor:
        filters.append(f"spend_record_id > ${param_idx}")
        params.append(cursor)
        param_idx += 1

    if tenant_id:
        filters.append(f"tenant_id = ${param_idx}")
        params.append(tenant_id)
        param_idx += 1

    where = " AND ".join(filters)
    params.extend([batch_size])
    query = f"""
        SELECT spend_record_id, tenant_id, platform, ad_account_id,
               campaign_id, external_campaign_id, source_connector_id
        FROM spend_records
        WHERE {where}
        ORDER BY spend_record_id
        LIMIT ${param_idx}
    """
    rows = await pool.fetch(query, *params)
    return [dict(r) for r in rows]


async def _resolve_row(
    row: dict[str, Any],
    registry,
    report: BackfillReport,
    dry_run: bool,
    pool,
) -> None:
    """Attempt to resolve a single spend_record row to a canonical campaign_id."""
    spend_record_id = row["spend_record_id"]
    tenant_id = row["tenant_id"]
    current_campaign_id = str(row.get("campaign_id") or "")
    external_campaign_id = row.get("external_campaign_id")
    platform = row.get("platform", "")
    ad_account_id = str(row.get("ad_account_id") or "")
    connector_id = row.get("source_connector_id")

    # Already canonical — nothing to do.
    if _is_uuid(current_campaign_id):
        report.already_canonical += 1
        return

    # Determine provider ID: prefer explicit external_campaign_id if set,
    # otherwise the current campaign_id value (which is the provider ID
    # for pre-registry rows).
    provider_id = external_campaign_id or current_campaign_id
    if not provider_id:
        report.skipped += 1
        return

    try:
        # Attempt exact external ref resolution first.
        canonical_id = await registry.upsert_external_campaign(
            tenant_id=tenant_id,
            platform=platform,
            external_account_id=ad_account_id,
            external_campaign_id=provider_id,
            external_campaign_name=None,
            source_connector_id=connector_id,
            raw_metadata={},
        )
        if canonical_id is None:
            report.unresolved += 1
            _mark_unresolved(pool, spend_record_id, dry_run)
            return

        if dry_run:
            logger.info(
                "[dry-run] Would update spend_record_id=%s: campaign_id=%s → %s",
                spend_record_id, current_campaign_id, canonical_id,
            )
            report.mapped += 1
            return

        await _update_row(pool, spend_record_id, str(canonical_id), provider_id)
        report.mapped += 1

    except Exception as exc:
        logger.warning("Row %s failed: %s", spend_record_id, exc)
        report.failed += 1
        report.errors.append(f"{spend_record_id}: {exc}")


async def _update_row(pool, spend_record_id: str, canonical_id: str, provider_id: str) -> None:
    if pool is None:
        return
    await pool.execute(
        """
        UPDATE spend_records
        SET campaign_id = $1,
            external_campaign_id = $2,
            campaign_resolution_status = 'resolved',
            campaign_resolution_method = 'backfill_exact_external_ref',
            campaign_resolution_version = '1.0'
        WHERE spend_record_id = $3
        """,
        canonical_id,
        provider_id,
        spend_record_id,
    )


def _mark_unresolved(pool, spend_record_id: str, dry_run: bool) -> None:
    if dry_run or pool is None:
        return
    asyncio.ensure_future(pool.execute(
        """
        UPDATE spend_records
        SET campaign_resolution_status = 'unresolved',
            campaign_resolution_version = '1.0'
        WHERE spend_record_id = $1
        """,
        spend_record_id,
    ))


async def run_backfill(
    dry_run: bool,
    batch_size: int,
    tenant_id: Optional[str],
    cursor: Optional[str],
    log_file: Optional[str],
) -> int:
    pool = await _get_pool()

    if pool is None and os.getenv("AETHER_ENV", "local").lower() != "local":
        logger.error("No DB pool available in non-local mode — aborting")
        return 1

    try:
        from services.campaign.registry import CampaignRegistryService  # type: ignore[import]
        from services.campaign.repository import (  # type: ignore[import]
            CampaignRegistryRepository,
            ExternalRefRepository,
            AliasRepository,
            MappingReviewRepository,
        )
        registry = CampaignRegistryService(
            campaign_repo=CampaignRegistryRepository(pool),
            external_ref_repo=ExternalRefRepository(pool),
            alias_repo=AliasRepository(pool),
            review_repo=MappingReviewRepository(pool),
        )
    except ImportError as exc:
        logger.error("Cannot import registry service: %s", exc)
        return 1

    report = BackfillReport()
    current_cursor = cursor

    logger.info(
        "Starting backfill: dry_run=%s batch_size=%d tenant_id=%s cursor=%s",
        dry_run, batch_size, tenant_id or "ALL", current_cursor or "START",
    )

    while True:
        batch = await _fetch_batch(pool, batch_size, current_cursor, tenant_id)
        if not batch:
            break

        for row in batch:
            report.scanned += 1
            await _resolve_row(row, registry, report, dry_run, pool)
            current_cursor = row["spend_record_id"]

        logger.info("Batch processed. %s", report.summary())

        if len(batch) < batch_size:
            break

    report.completed_at = datetime.now(timezone.utc)

    audit = report.to_dict()
    audit["options"] = {
        "dry_run": dry_run,
        "batch_size": batch_size,
        "tenant_id": tenant_id,
        "initial_cursor": cursor,
    }

    if log_file:
        Path(log_file).write_text(json.dumps(audit, indent=2))
        logger.info("Audit log written to %s", log_file)

    print(json.dumps({"summary": report.to_dict()}))

    if report.failed > 0:
        return 2
    return 0


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Backfill canonical campaign IDs in spend_records")
    p.add_argument("--dry-run", action="store_true", help="Print actions without writing")
    p.add_argument("--batch-size", type=int, default=500, metavar="INT")
    p.add_argument("--tenant-id", default=None, metavar="TEXT")
    p.add_argument("--cursor", default=None, metavar="TEXT", help="Resume from this spend_record_id")
    p.add_argument("--log-file", default=None, metavar="PATH", help="Write JSON audit log")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    exit_code = asyncio.run(run_backfill(
        dry_run=args.dry_run,
        batch_size=args.batch_size,
        tenant_id=args.tenant_id,
        cursor=args.cursor,
        log_file=args.log_file,
    ))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
