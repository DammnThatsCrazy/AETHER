"""Read-only targeting state for Noesis intelligence queries.

Exposes summarized targeting facts (intents, latest snapshots, open leakage)
so Noesis can answer questions about targeting posture. Strictly read-only —
no mutation paths.
"""

from __future__ import annotations

from typing import Any, Optional

from services.targeting_intelligence.repository import (
    TargetingRepositories,
    get_targeting_repositories,
)


class TargetingNoesisAdapter:
    """Query surface consumed by Noesis handlers (read-only)."""

    def __init__(self, repositories: Optional[TargetingRepositories] = None) -> None:
        self.repos = repositories or get_targeting_repositories()

    async def targeting_summary(self, tenant_id: str) -> dict[str, Any]:
        intents = await self.repos.intents.list_for_tenant(tenant_id, limit=100)
        findings = await self.repos.leakage.list_for_tenant(tenant_id, limit=100)
        open_severe = [f for f in findings if f.get("severity") in ("high", "critical")]
        return {
            "intentCount": len(intents),
            "campaignsWithIntents": sorted({
                i.get("campaignId") for i in intents if i.get("campaignId")
            }),
            "leakageFindingCount": len(findings),
            "severeLeakageCount": len(open_severe),
            "observationLanguage": "observed",
        }

    async def campaign_targeting(self, tenant_id: str, campaign_id: str) -> dict[str, Any]:
        intents = await self.repos.intents.list_for_tenant(
            tenant_id, campaignId=campaign_id, limit=10
        )
        snapshots: list[dict] = []
        for intent in intents:
            snapshots.extend(await self.repos.snapshots.list_for_tenant(
                tenant_id, targetingIntentId=intent["id"], limit=1
            ))
        findings = await self.repos.leakage.list_for_tenant(
            tenant_id, campaignId=campaign_id, limit=50
        )
        return {
            "campaignId": campaign_id,
            "intents": intents,
            "latestSnapshots": snapshots,
            "leakageFindings": findings,
        }


_adapter: Optional[TargetingNoesisAdapter] = None


def get_targeting_noesis_adapter() -> TargetingNoesisAdapter:
    global _adapter
    if _adapter is None:
        _adapter = TargetingNoesisAdapter()
    return _adapter
