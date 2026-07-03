"""Backfill fraud decisions for existing canonical_activity records.

Iterates over canonical_activity rows that have no associated fraud decision
and runs FraudEvaluationService.evaluate_subject() for each unique entity.

Usage:
    python scripts/backfill_fraud_decisions.py --dry-run
    python scripts/backfill_fraud_decisions.py --tenant-id <tid> --batch-size 50
    python scripts/backfill_fraud_decisions.py --cursor <cursor> --limit 500

Options:
    --dry-run               Print what would be evaluated without persisting
    --tenant-id TID         Restrict to a single tenant (default: all tenants)
    --batch-size N          Activities processed per batch (default: 100)
    --limit N               Max activities to process in total (default: unlimited)
    --cursor CURSOR         Resume from a prior run (activity_id offset)
    --model-version V       Risk model version tag written on decisions (default: backfill-v1)
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "Backend Architecture" / "aether-backend"))

from shared.logger.logger import get_logger

logger = get_logger("aether.scripts.backfill_fraud_decisions")

_UNLIMITED = 2 ** 63


async def _iter_unscored_activities(
    tenant_id: str | None,
    batch_size: int,
    total_limit: int,
    cursor: str | None,
) -> list[dict]:
    """Yield batches of canonical_activity rows with no fraud decision."""
    from repositories.repos import BaseRepository, FraudDecisionRepository

    activity_repo = BaseRepository("canonical_activity")
    decision_repo = FraudDecisionRepository()

    filters: dict = {}
    if tenant_id:
        filters["tenant_id"] = tenant_id

    fetched = 0
    current_cursor = cursor
    while fetched < total_limit:
        batch = await activity_repo.find_many(
            filters=filters or None,
            limit=min(batch_size, total_limit - fetched),
        )
        if not batch:
            break

        for row in batch:
            # Skip rows that already have a decision.
            if row.get("fraud_decision_id"):
                current_cursor = row.get("activity_id") or row.get("id")
                continue
            existing = await decision_repo.get_current_for_activity(
                tenant_id=row.get("tenant_id", ""),
                activity_id=str(row.get("activity_id") or row.get("id") or ""),
            )
            if existing:
                current_cursor = row.get("activity_id") or row.get("id")
                continue
            yield row
            fetched += 1
            current_cursor = row.get("activity_id") or row.get("id")
            if fetched >= total_limit:
                break

        if len(batch) < batch_size:
            break  # No more rows

    logger.info("Iteration complete. Last cursor: %s", current_cursor)


async def _run(
    tenant_id: str | None,
    batch_size: int,
    total_limit: int,
    cursor: str | None,
    dry_run: bool,
    model_version: str,
) -> None:
    from services.fraud.evaluation import FraudEvaluationService

    service = FraudEvaluationService(model_version=model_version)
    evaluated = 0
    skipped = 0
    errors = 0

    async for row in _iter_unscored_activities(tenant_id, batch_size, total_limit, cursor):
        tid = row.get("tenant_id") or ""
        entity_id = (
            row.get("entity_id")
            or row.get("user_id")
            or row.get("wallet_id")
            or row.get("agent_id")
        )
        activity_id = str(row.get("activity_id") or row.get("id") or "")

        if not entity_id or not tid:
            logger.warning("Skipping activity %s — no entity_id or tenant_id", activity_id)
            skipped += 1
            continue

        if dry_run:
            logger.info(
                "[dry-run] Would evaluate entity=%s activity=%s tenant=%s",
                entity_id, activity_id, tid,
            )
            evaluated += 1
            continue

        try:
            await service.evaluate_subject(
                tenant_id=tid,
                subject_type="entity",
                subject_id=str(entity_id),
                trigger_activity_id=activity_id,
            )
            evaluated += 1
            if evaluated % 50 == 0:
                logger.info("Progress: %d evaluated, %d skipped, %d errors", evaluated, skipped, errors)
        except Exception as exc:
            logger.error(
                "Evaluation failed for entity=%s activity=%s: %s",
                entity_id, activity_id, exc,
            )
            errors += 1

    logger.info(
        "Backfill complete%s: %d evaluated, %d skipped, %d errors",
        " (dry-run)" if dry_run else "",
        evaluated,
        skipped,
        errors,
    )


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry-run", action="store_true", help="Print what would be done without persisting")
    p.add_argument("--tenant-id", metavar="TID", help="Restrict to a single tenant")
    p.add_argument("--batch-size", type=int, default=100, metavar="N", help="Activities per batch (default: 100)")
    p.add_argument("--limit", type=int, default=None, metavar="N", help="Max activities to process")
    p.add_argument("--cursor", default=None, metavar="CURSOR", help="Resume from activity_id offset")
    p.add_argument("--model-version", default="backfill-v1", metavar="V", help="Risk model version tag")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    total_limit = args.limit if args.limit is not None else _UNLIMITED
    asyncio.run(
        _run(
            tenant_id=args.tenant_id,
            batch_size=args.batch_size,
            total_limit=total_limit,
            cursor=args.cursor,
            dry_run=args.dry_run,
            model_version=args.model_version,
        )
    )


if __name__ == "__main__":
    main()
