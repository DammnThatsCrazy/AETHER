"""Noesis adapter for attribution run data.

Wraps AttributionRunRepository to expose campaign performance metrics
(ROAS, conversion counts) for the campaign_reward_lookup intent.
"""

from __future__ import annotations

from typing import Any, Optional

from shared.logger.logger import get_logger

logger = get_logger("aether.service.noesis.adapters.attribution")


class NoesisAttributionAdapter:
    """Read-only adapter over AttributionRunRepository for Noesis queries."""

    def __init__(self, repo: Any | None = None) -> None:
        self._repo = repo

    async def campaign_performance(
        self,
        tenant_id: str,
        time_range: Optional[str] = None,
        campaign_id: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict]:
        """Return campaigns sorted by ROAS/conversion_count from attribution runs."""
        if self._repo is None:
            try:
                from services.measurement.repositories.attribution_run_repo import AttributionRunRepository
                self._repo = AttributionRunRepository()
            except Exception as exc:
                logger.warning(f"Attribution adapter: cannot load repo: {exc}")
                return []

        try:
            runs = await self._repo.list_runs(
                tenant_id,
                campaign_id=campaign_id,
                status="completed",
                limit=limit * 5,
            )
        except Exception as exc:
            logger.warning(f"Attribution adapter list_runs failed: {exc}")
            return []

        # Aggregate per campaign_id
        by_campaign: dict[str, dict] = {}
        for run in runs:
            cid = run.get("campaign_id") or run.get("attribution_run_id", "unknown")
            if cid not in by_campaign:
                by_campaign[cid] = {
                    "campaign_id": cid,
                    "conversion_count": 0,
                    "total_revenue": 0.0,
                    "total_cost": 0.0,
                    "run_count": 0,
                }
            entry = by_campaign[cid]
            entry["conversion_count"] += int(run.get("conversion_count") or 0)
            entry["total_revenue"] += float(run.get("revenue") or 0)
            entry["total_cost"] += float(run.get("cost") or 0)
            entry["run_count"] += 1

        results = list(by_campaign.values())
        for r in results:
            cost = r["total_cost"]
            r["roas"] = round(r["total_revenue"] / cost, 4) if cost > 0 else None

        results.sort(key=lambda x: (x["roas"] or 0, x["conversion_count"]), reverse=True)
        return results[:limit]
