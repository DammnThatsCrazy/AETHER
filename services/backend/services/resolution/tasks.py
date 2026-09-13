"""
Aether Backend — Identity Resolution Batch Tasks

Scheduled jobs for probabilistic identity matching.  Runs periodically
(e.g. every 15 minutes via a cron trigger or Step Functions schedule)
to evaluate candidate pairs that share graph vertices but did not match
deterministically during real-time ingestion.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from shared.logger.logger import get_logger

from .engine import IdentityResolutionEngine

logger = get_logger("aether.resolution.tasks")


class ResolutionBatchJob:
    """
    Batch probabilistic matching job.

    Wraps the engine's ``batch_resolve()`` and produces a summary report
    suitable for logging, alerting, and dashboard display.
    """

    def __init__(self, engine: IdentityResolutionEngine) -> None:
        self.engine = engine

    async def run(self, tenant_id: str) -> dict[str, Any]:
        """
        Execute a batch resolution run for a single tenant.

        Returns a summary dict with counts of each decision type.
        """
        started_at = datetime.now(timezone.utc)
        logger.info(f"Starting batch resolution for tenant {tenant_id}")

        decisions = await self.engine.batch_resolve(tenant_id)

        auto_merged = sum(1 for d in decisions if d.action == "auto_merge")
        flagged = sum(1 for d in decisions if d.action == "flag_for_review")
        rejected = sum(1 for d in decisions if d.action == "reject")

        elapsed_ms = (
            datetime.now(timezone.utc) - started_at
        ).total_seconds() * 1000

        summary = {
            "tenant_id": tenant_id,
            "total_evaluated": len(decisions),
            "auto_merged": auto_merged,
            "flagged": flagged,
            "rejected": rejected,
            "elapsed_ms": round(elapsed_ms, 2),
            "started_at": started_at.isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }

        logger.info(
            f"Batch resolution complete for tenant {tenant_id}: "
            f"{auto_merged} merged, {flagged} flagged, {rejected} rejected "
            f"({elapsed_ms:.0f}ms)"
        )
        return summary

    async def run_all_tenants(self, tenant_ids: list[str]) -> list[dict[str, Any]]:
        """
        Execute batch resolution across multiple tenants sequentially.

        Returns a list of per-tenant summary dicts.
        """
        results: list[dict[str, Any]] = []
        for tenant_id in tenant_ids:
            try:
                summary = await self.run(tenant_id)
                results.append(summary)
            except Exception as exc:
                logger.error(
                    f"Batch resolution failed for tenant {tenant_id}: {exc}",
                    exc_info=True,
                )
                results.append({
                    "tenant_id": tenant_id,
                    "error": str(exc),
                })
        return results
