"""Backfill suggestions from legacy sources (recommendations, notifications).

Usage:
    python scripts/backfill_suggestions.py --dry-run --source all
    python scripts/backfill_suggestions.py --tenant-id <tid> --source recommendations --limit 100
    python scripts/backfill_suggestions.py --source notifications --limit 50

Options:
    --dry-run               Print what would be created without persisting
    --tenant-id TID         Restrict to a single tenant
    --source SOURCE         recommendations | notifications | all  (default: all)
    --limit N               Max suggestions to create per source (default: 200)
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).parent.parent / "Backend Architecture" / "aether-backend"))

from shared.logger.logger import get_logger

logger = get_logger("aether.scripts.backfill_suggestions")


async def _backfill_recommendations(tenant_id: str | None, limit: int, dry_run: bool) -> int:
    from repositories.repos import BaseRepository
    from services.suggestions.adapters.recommendation_adapter import find_or_create_from_recommendation
    from services.suggestions.repository import SuggestionRepository
    from shared.auth.auth import TenantContext, Role

    rec_repo = BaseRepository("recommendations")
    sug_repo = SuggestionRepository()
    filters: dict = {}
    if tenant_id:
        filters["tenant_id"] = tenant_id
    recs = await rec_repo.find_many(filters=filters or None, limit=limit)
    created = 0
    for rec in recs:
        tid = rec.get("tenant_id", tenant_id or "")
        if not tid:
            continue
        tenant = TenantContext(tenant_id=tid, role=Role.TENANT, permissions=frozenset({"read"}))
        if dry_run:
            logger.info("[dry-run] Would create suggestion from recommendation %s", rec.get("id"))
            created += 1
        else:
            try:
                result = await find_or_create_from_recommendation(rec, tenant, sug_repo)
                if result:
                    created += 1
                    logger.info("Created suggestion %s from recommendation %s", result.get("id"), rec.get("id"))
            except Exception as exc:
                logger.warning("Failed to backfill recommendation %s: %s", rec.get("id"), exc)
    return created


async def _backfill_notifications(tenant_id: str | None, limit: int, dry_run: bool) -> int:
    from repositories.repos import BaseRepository
    from services.suggestions.adapters.notification_adapter import create_suggestion_from_notification
    from services.suggestions.repository import SuggestionRepository

    notif_repo = BaseRepository("notifications")
    sug_repo = SuggestionRepository()
    filters: dict = {}
    if tenant_id:
        filters["tenant_id"] = tenant_id
    notifs = await notif_repo.find_many(filters=filters or None, limit=limit)
    created = 0
    for notif in notifs:
        tid = notif.get("tenant_id", tenant_id or "")
        if not tid:
            continue
        if dry_run:
            logger.info("[dry-run] Would create suggestion from notification %s", notif.get("id"))
            created += 1
        else:
            try:
                existing = await sug_repo.find_by_source_ref(tid, "notification_intelligence", str(notif.get("id", "")))
                if existing:
                    continue
                create = create_suggestion_from_notification(notif, tid)
                from services.suggestions.models import Suggestion, SuggestionStatus, OodaPhase, SuggestionPriority
                from services.suggestions.scorer import compute_scores
                from services.suggestions.policy import requires_approval, execution_eligible
                from shared.common.common import utc_now
                import uuid

                scores = compute_scores(create)
                now = utc_now().isoformat()
                suggestion = Suggestion(
                    id=str(uuid.uuid4()),
                    tenant_id=tid,
                    subject=create.subject,
                    source=create.source,
                    source_ref=create.source_ref,
                    suggestion_class=create.suggestion_class,
                    title=create.title,
                    summary=create.summary,
                    what=create.what,
                    why=create.why,
                    impact=create.impact,
                    recommended_action=create.recommended_action,
                    confidence_score=create.confidence_score,
                    requires_approval=requires_approval(create.suggestion_class, scores.get("risk_score") or 0.0, create.reversible),
                    execution_eligible=execution_eligible(create.suggestion_class, create.source, scores.get("risk_score") or 0.0),
                    evidence=create.evidence,
                    lineage_event_ids=create.lineage_event_ids,
                    created_at=now,
                    updated_at=now,
                    **{k: v for k, v in scores.items() if k not in ("priority",)},
                    priority=scores.get("priority", SuggestionPriority.P3),
                )
                await sug_repo.create(suggestion)
                created += 1
                logger.info("Created suggestion from notification %s", notif.get("id"))
            except Exception as exc:
                logger.warning("Failed to backfill notification %s: %s", notif.get("id"), exc)
    return created


async def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill suggestions from legacy sources")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, do not persist")
    parser.add_argument("--tenant-id", default=None, help="Restrict to a single tenant ID")
    parser.add_argument("--source", default="all", choices=["recommendations", "notifications", "all"])
    parser.add_argument("--limit", type=int, default=200, help="Max per source")
    args = parser.parse_args()

    total = 0
    prefix = "[DRY RUN] " if args.dry_run else ""

    if args.source in ("recommendations", "all"):
        n = await _backfill_recommendations(args.tenant_id, args.limit, args.dry_run)
        logger.info("%sBackfilled %d suggestions from recommendations", prefix, n)
        total += n

    if args.source in ("notifications", "all"):
        n = await _backfill_notifications(args.tenant_id, args.limit, args.dry_run)
        logger.info("%sBackfilled %d suggestions from notifications", prefix, n)
        total += n

    logger.info("%sTotal: %d suggestions created", prefix, total)
    print(f"{prefix}Backfill complete: {total} suggestions {'would be ' if args.dry_run else ''}created.")


if __name__ == "__main__":
    asyncio.run(main())
