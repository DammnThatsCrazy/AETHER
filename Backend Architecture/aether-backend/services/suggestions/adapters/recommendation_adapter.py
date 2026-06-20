"""Recommendation Engine ↔ Suggestion adapter.

Maps retarget recommendation records into SuggestionCreate inputs and
executes approved execution-eligible Suggestions via the existing engine.
Idempotent via source_ref deduplication.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from shared.common.common import utc_now
from shared.logger.logger import get_logger

from services.suggestions.models import (
    SuggestionClass,
    SuggestionCreate,
    SuggestionSource,
    SuggestionStatus,
    SuggestionSubject,
)

if TYPE_CHECKING:
    from services.suggestions.service import SuggestionService

logger = get_logger("aether.suggestions.adapters.recommendation")


def create_suggestion_from_recommendation(
    rec: dict,
    tenant_id: str,
) -> SuggestionCreate:
    """Map a retarget recommendation dict to a SuggestionCreate."""
    entity_id = rec.get("entity_id") or rec.get("user_id") or "unknown"
    confidence = float(rec.get("retarget_score", 0.5))
    platform = rec.get("platform") or rec.get("channel") or "unknown"
    campaign = rec.get("campaign_id") or ""

    return SuggestionCreate(
        tenant_id=tenant_id,
        subject=SuggestionSubject(
            kind="entity",
            id=entity_id,
            display_name=rec.get("display_name"),
        ),
        source=SuggestionSource.RECOMMENDATION_ENGINE,
        source_ref={"service": "recommendation_engine", "id": rec.get("recommendation_id", "")},
        suggestion_class=SuggestionClass.RETARGETING,
        title=f"Retarget {entity_id[:16]!r} via {platform}",
        summary=(
            f"Retargeting opportunity detected for entity {entity_id[:16]!r} "
            f"with confidence {confidence:.0%}."
        ),
        what=f"Retarget via {platform}" + (f" for campaign {campaign}" if campaign else ""),
        why=f"Retarget score {confidence:.2f} indicates high re-engagement probability.",
        impact="Re-engage a high-value entity and recover potential revenue.",
        recommended_action=f"Send re-engagement via {platform}",
        confidence_score=confidence,
        impact_score=confidence,
        urgency_score=rec.get("urgency_score", 0.5),
        risk_score=0.1,
        reversible=True,
        evidence=[
            {
                "id": rec.get("recommendation_id", ""),
                "type": "model_output",
                "source": "recommendation_engine",
                "observedAt": rec.get("created_at") or utc_now().isoformat(),
                "confidence": confidence,
            }
        ],
        lineage_event_ids=[rec.get("recommendation_id")] if rec.get("recommendation_id") else [],
    )


async def find_or_create_from_recommendation(
    rec: dict,
    tenant_id: str,
    service: "SuggestionService",
) -> dict:
    """Idempotent: return existing suggestion for this rec_id or create a new one."""
    rec_id = rec.get("recommendation_id", "")
    if rec_id:
        existing = await service._repo.find_by_source_ref(
            tenant_id=tenant_id,
            source="recommendation_engine",
            source_id=rec_id,
        )
        if existing:
            logger.debug(f"Dedup: suggestion already exists for rec {rec_id!r}")
            return existing

    create = create_suggestion_from_recommendation(rec, tenant_id)

    from shared.auth.auth import TenantContext, Role
    ctx = TenantContext(
        tenant_id=tenant_id,
        role=Role.ADMIN,
        permissions=["read", "write", "admin"],
    )
    return await service.create_suggestion(create, ctx)


async def execute_recommendation_via_suggestion(
    suggestion: dict,
    service: "SuggestionService",
) -> dict:
    """Execute an approved, execution-eligible recommendation suggestion.

    Only called by the dispatcher. The suggestion must already be APPROVED
    and execution_eligible must be True.
    """
    if suggestion.get("status") != SuggestionStatus.APPROVED.value:
        logger.warning(f"Cannot execute suggestion {suggestion.get('id')!r}: not APPROVED")
        return suggestion

    if not suggestion.get("execution_eligible", False):
        logger.warning(f"Suggestion {suggestion.get('id')!r} not execution_eligible — skipping")
        return suggestion

    source_ref = suggestion.get("source_ref") or {}
    rec_id = source_ref.get("id")

    if rec_id:
        try:
            from repositories.repos import RecommendationRepository
            rec_repo = RecommendationRepository()
            await rec_repo.update_status(
                recommendation_id=rec_id,
                tenant_id=suggestion["tenant_id"],
                status="approved_via_suggestion",
                approved_by_suggestion_id=suggestion["id"],
            )
            logger.info(f"Synced approval back to rec {rec_id!r}")
        except Exception as exc:
            logger.warning(f"Rec status sync failed for {rec_id!r}: {exc}")

    # Transition to EXECUTED
    from shared.auth.auth import TenantContext, Role
    from services.suggestions.lifecycle import apply_transition
    from services.suggestions.events import emit_suggestion_event
    from services.suggestions.models import SuggestionStatus as _SS
    updated = await apply_transition(
        repo=service._repo,
        suggestion_id=suggestion["id"],
        tenant_id=suggestion["tenant_id"],
        to_status=_SS.EXECUTED,
        actor_kind="system",
        notes="Executed via recommendation engine",
    )
    await emit_suggestion_event(service._producer, "suggestion.executed", updated)
    return updated
