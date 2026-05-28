"""
Aether — Recommendation Executor
Executes approved retargeting recommendations against ad platform APIs.

Flow:
  1. Analyst approves via POST /v1/recommendations/{id}/approve
  2. executor.execute(recommendation) is called
  3. Ad platform's Custom Audience API receives the entity's identifiers
  4. status updated to 'executed'; attribution touchpoint stamped
  5. All actions written to consent_audit_log

Ad platform APIs used:
  - Twitter Ads: Promoted Tweets audience endpoint
  - Meta Ads: POST /act_{ad_account_id}/customaudiences
  - Google Ads: POST /v15/customers/{id}/userLists
  - LinkedIn Ads: Campaign Manager API
  - TikTok Ads: Custom Audience API v1.3
"""

from __future__ import annotations

from datetime import datetime, timezone

from shared.logger.logger import get_logger

logger = get_logger("aether.recommendations.executor")

_PLATFORM_AUDIENCE_METHODS: dict[str, str] = {
    "twitter_ads": "create_custom_audience",
    "meta_ads": "create_custom_audience",
    "google_ads": "create_user_list",
    "linkedin_ads": "create_audience_segment",
    "tiktok_ads": "create_custom_audience",
}


class RecommendationExecutor:
    """
    Executes approved recommendations against ad platform APIs.
    Never called unless status = 'approved'.
    """

    def __init__(self, provider_registry, recommendation_repo, audit_log_repo):
        self.registry = provider_registry
        self.repo = recommendation_repo
        self.audit_log = audit_log_repo

    async def execute(
        self,
        recommendation_id: str,
        tenant_id: str,
        reviewed_by: str,
        review_notes: str | None = None,
    ) -> dict:
        """
        Execute an approved recommendation against the target ad platform.

        Args:
            recommendation_id: UUID of the recommendation to execute.
            tenant_id: Tenant scope for provider key lookup.
            reviewed_by: Analyst user ID who approved.
            review_notes: Optional analyst notes.

        Returns:
            Updated recommendation dict with execution status.
        """
        rec = await self.repo.get(recommendation_id, tenant_id)
        if not rec:
            raise ValueError(f"Recommendation {recommendation_id} not found")

        if rec["status"] != "approved":
            raise ValueError(
                f"Recommendation {recommendation_id} is not in 'approved' state (current: {rec['status']})"
            )

        platform = rec["recommended_platform"]
        method = _PLATFORM_AUDIENCE_METHODS.get(platform)
        if not method:
            raise ValueError(f"No audience method configured for platform: {platform}")

        try:
            provider = await self.registry.get(platform, tenant_id)
            ad_platform_response = await provider.execute(method, {
                "entity_id": rec["entity_id"],
                "audience_segment": rec["recommended_audience_segment"],
                "bid_usd": rec["recommended_bid_usd"],
                "creative_theme": rec["recommended_creative_theme"],
            })
        except Exception as exc:
            logger.error(
                f"Ad platform execution failed for recommendation {recommendation_id}: {exc}"
            )
            await self._update_status(rec, "pending_review", tenant_id, error=str(exc))
            raise

        executed_at = datetime.now(timezone.utc).isoformat()
        updated = {
            **rec,
            "status": "executed",
            "reviewed_by": reviewed_by,
            "review_notes": review_notes,
            "executed_at": executed_at,
            "ad_platform_response": ad_platform_response,
        }

        await self.repo.update(updated, tenant_id)

        # Write to audit log
        await self.audit_log.record({
            "action": "retarget_recommendation_executed",
            "recommendation_id": recommendation_id,
            "entity_id": rec["entity_id"],
            "platform": platform,
            "executed_by": reviewed_by,
            "executed_at": executed_at,
            "tenant_id": tenant_id,
        })

        logger.info(
            f"Recommendation {recommendation_id} executed on {platform} "
            f"for entity {rec['entity_id']} by {reviewed_by}"
        )

        return updated

    async def _update_status(
        self,
        rec: dict,
        status: str,
        tenant_id: str,
        error: str | None = None,
    ) -> None:
        updated = {**rec, "status": status}
        if error:
            updated["review_notes"] = (rec.get("review_notes") or "") + f" [execution_error: {error}]"
        await self.repo.update(updated, tenant_id)
