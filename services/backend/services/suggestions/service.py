"""SuggestionService — orchestrates OODA lifecycle, scoring, policy, and events."""

from __future__ import annotations

import uuid
from typing import Any, Optional

from shared.auth.auth import TenantContext
from shared.cache.cache import CacheClient
from shared.common.common import BadRequestError, ForbiddenError, NotFoundError, utc_now
from shared.events.events import EventProducer
from shared.graph.graph import GraphClient
from shared.logger.logger import get_logger

from .events import emit_suggestion_event
from .lifecycle import apply_transition, build_audit_event
from .models import (
    OodaPhase,
    Suggestion,
    SuggestionActionRequest,
    SuggestionCreate,
    SuggestionFeedbackRequest,
    SuggestionOutcomeRequest,
    SuggestionQuery,
    SuggestionRejectRequest,
    SuggestionStatus,
    SuggestionSuppressRequest,
    SuggestionSummary,
)
from .policy import evaluate_suggestion_policy, redact_for_tenant, requires_approval
from .repository import SuggestionRepository
from .scorer import compute_scores

logger = get_logger("aether.suggestions.service")


class SuggestionService:
    def __init__(
        self,
        repo: SuggestionRepository,
        producer: EventProducer,
        cache: CacheClient,
        graph: GraphClient,
    ) -> None:
        self._repo = repo
        self._producer = producer
        self._cache = cache
        self._graph = graph

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create_suggestion(
        self,
        create: SuggestionCreate,
        tenant_context: TenantContext,
        *,
        request_id: str = "",
    ) -> dict:
        if create.tenant_id != tenant_context.tenant_id:
            raise ForbiddenError("tenant_id does not match authenticated tenant")

        scores = compute_scores(create)
        policy_decision = await evaluate_suggestion_policy(create, tenant_context)

        _requires_approval = requires_approval(
            create.suggestion_class,
            create.risk_score,
            create.reversible,
        )
        from .policy import execution_eligible as _exec_eligible
        _exec_eligible_flag = _exec_eligible(
            create.suggestion_class,
            create.source,
            create.risk_score,
        )

        now = utc_now().isoformat()
        suggestion_id = str(uuid.uuid4())

        audit_event = build_audit_event(
            action="created",
            from_status=None,
            to_status=SuggestionStatus.DETECTED.value,
            actor_id=tenant_context.user_id,
            actor_kind="system",
        )

        suggestion = Suggestion(
            id=suggestion_id,
            tenant_id=create.tenant_id,
            org_id=create.org_id,
            subject=create.subject,
            source=create.source,
            source_ref=create.source_ref,
            ooda_phase=OodaPhase.OBSERVE,
            suggestion_class=create.suggestion_class,
            priority=scores["priority"],
            status=SuggestionStatus.DETECTED,
            title=create.title,
            summary=create.summary,
            what=create.what,
            why=create.why,
            impact=create.impact,
            recommended_action=create.recommended_action,
            expected_outcome=create.expected_outcome,
            confidence_score=create.confidence_score,
            impact_score=scores["impact_score"],
            urgency_score=scores["urgency_score"],
            risk_score=create.risk_score,
            evidence_quality_score=scores["evidence_quality_score"],
            tenant_value_score=scores["tenant_value_score"],
            reversibility_score=scores["reversibility_score"],
            priority_score=scores["priority_score"],
            reversible=create.reversible,
            requires_approval=_requires_approval,
            execution_eligible=_exec_eligible_flag,
            delivery_eligible=True,
            evidence=create.evidence,
            lineage_event_ids=create.lineage_event_ids,
            policy_decision=policy_decision,
            audit_trail=[audit_event],
            expires_at=create.expires_at,
            created_at=now,
            updated_at=now,
        )

        record = await self._repo.create(suggestion)
        await emit_suggestion_event(self._producer, "suggestion.created", record)
        logger.info(f"Created suggestion {suggestion_id!r} class={create.suggestion_class.value!r} priority={scores['priority'].value!r}")
        return record

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_suggestion(
        self, suggestion_id: str, tenant_context: TenantContext
    ) -> dict:
        record = await self._repo.get(suggestion_id, tenant_context.tenant_id)
        if record is None:
            raise NotFoundError(f"Suggestion {suggestion_id!r}")
        return record

    async def query_suggestions(
        self,
        query: SuggestionQuery,
        tenant_context: TenantContext,
    ) -> tuple[list[dict], int]:
        if query.tenant_id != tenant_context.tenant_id:
            raise ForbiddenError("tenant_id does not match authenticated tenant")
        rows = await self._repo.list(query)
        return rows, len(rows)

    async def review_queue(
        self,
        tenant_context: TenantContext,
        limit: int = 50,
    ) -> list[dict]:
        return await self._repo.list_review_queue(tenant_context.tenant_id, limit=limit)

    async def summarize(
        self,
        tenant_context: TenantContext,
        filters: Optional[dict] = None,
    ) -> SuggestionSummary:
        return await self._repo.summary(tenant_context.tenant_id, filters=filters)

    # ------------------------------------------------------------------
    # Lifecycle actions
    # ------------------------------------------------------------------

    async def approve_suggestion(
        self,
        suggestion_id: str,
        body: SuggestionActionRequest,
        tenant_context: TenantContext,
    ) -> dict:
        record = await self._repo.get_or_fail(suggestion_id, tenant_context.tenant_id)
        current = SuggestionStatus(record["status"])
        if current not in (SuggestionStatus.REVIEW_REQUIRED, SuggestionStatus.SUGGESTED):
            raise BadRequestError(
                f"Cannot approve a suggestion with status {current.value!r}. "
                "Only review_required or suggested suggestions can be approved."
            )
        updated = await apply_transition(
            repo=self._repo,
            suggestion_id=suggestion_id,
            tenant_id=tenant_context.tenant_id,
            to_status=SuggestionStatus.APPROVED,
            actor_id=body.actor_id or tenant_context.user_id,
            actor_kind="tenant_user" if tenant_context.user_id else "operator",
            notes=body.notes,
        )
        await emit_suggestion_event(self._producer, "suggestion.approved", updated)
        return updated

    async def reject_suggestion(
        self,
        suggestion_id: str,
        body: SuggestionRejectRequest,
        tenant_context: TenantContext,
    ) -> dict:
        await self._repo.get_or_fail(suggestion_id, tenant_context.tenant_id)
        updated = await apply_transition(
            repo=self._repo,
            suggestion_id=suggestion_id,
            tenant_id=tenant_context.tenant_id,
            to_status=SuggestionStatus.REJECTED,
            actor_id=body.actor_id or tenant_context.user_id,
            actor_kind="tenant_user" if tenant_context.user_id else "operator",
            notes=body.reason,
        )
        await emit_suggestion_event(self._producer, "suggestion.rejected", updated)
        return updated

    async def suppress_suggestion(
        self,
        suggestion_id: str,
        body: SuggestionSuppressRequest,
        tenant_context: TenantContext,
    ) -> dict:
        await self._repo.get_or_fail(suggestion_id, tenant_context.tenant_id)
        updated = await apply_transition(
            repo=self._repo,
            suggestion_id=suggestion_id,
            tenant_id=tenant_context.tenant_id,
            to_status=SuggestionStatus.SUPPRESSED,
            actor_id=body.actor_id or tenant_context.user_id,
            actor_kind="tenant_user" if tenant_context.user_id else "operator",
            notes=body.reason,
        )
        await emit_suggestion_event(self._producer, "suggestion.suppressed", updated)
        return updated

    async def execute_suggestion(
        self,
        suggestion_id: str,
        body: SuggestionActionRequest,
        tenant_context: TenantContext,
        *,
        execution_enabled: bool = False,
    ) -> dict:
        record = await self._repo.get_or_fail(suggestion_id, tenant_context.tenant_id)
        if record.get("status") != SuggestionStatus.APPROVED.value:
            raise BadRequestError("Only approved suggestions can be executed.")
        if not record.get("execution_eligible", False):
            raise BadRequestError("This suggestion is not eligible for automated execution.")
        if not execution_enabled:
            raise BadRequestError(
                "Automated execution is disabled. "
                "Enable AETHER_SUGGESTIONS_EXECUTION_ENABLED to allow it."
            )

        updated = await apply_transition(
            repo=self._repo,
            suggestion_id=suggestion_id,
            tenant_id=tenant_context.tenant_id,
            to_status=SuggestionStatus.EXECUTING,
            actor_id=body.actor_id or tenant_context.user_id,
            actor_kind="operator",
            notes=body.notes,
        )
        await emit_suggestion_event(self._producer, "suggestion.executing", updated)
        return updated

    async def deliver_suggestion(
        self,
        suggestion_id: str,
        tenant_context: TenantContext,
    ) -> dict:
        record = await self._repo.get_or_fail(suggestion_id, tenant_context.tenant_id)
        if not record.get("delivery_eligible", True):
            raise BadRequestError("This suggestion is not eligible for delivery.")

        updated = await apply_transition(
            repo=self._repo,
            suggestion_id=suggestion_id,
            tenant_id=tenant_context.tenant_id,
            to_status=SuggestionStatus.DELIVERED,
            actor_kind="system",
        )
        await emit_suggestion_event(self._producer, "suggestion.delivered", updated)
        return updated

    async def record_outcome(
        self,
        suggestion_id: str,
        body: SuggestionOutcomeRequest,
        tenant_context: TenantContext,
    ) -> dict:
        await self._repo.get_or_fail(suggestion_id, tenant_context.tenant_id)
        now = utc_now().isoformat()
        outcome = {
            "status": body.status,
            "measured_impact": body.measured_impact,
            "operator_notes": body.operator_notes,
            "tenant_feedback": body.tenant_feedback,
            "created_at": now,
            "created_by": body.created_by or tenant_context.user_id,
        }
        updated = await self._repo.record_outcome(suggestion_id, tenant_context.tenant_id, outcome)

        # Advance lifecycle if possible
        current_status = SuggestionStatus(updated.get("status", "delivered"))
        if current_status in (SuggestionStatus.EXECUTED, SuggestionStatus.DELIVERED):
            try:
                updated = await apply_transition(
                    repo=self._repo,
                    suggestion_id=suggestion_id,
                    tenant_id=tenant_context.tenant_id,
                    to_status=SuggestionStatus.MEASURED,
                    actor_kind="system",
                    notes="Outcome recorded",
                )
            except Exception:
                pass

        await emit_suggestion_event(self._producer, "suggestion.outcome_recorded", updated)
        return updated

    async def submit_feedback(
        self,
        suggestion_id: str,
        body: SuggestionFeedbackRequest,
        tenant_context: TenantContext,
    ) -> dict:
        await self._repo.get_or_fail(suggestion_id, tenant_context.tenant_id)
        now = utc_now().isoformat()
        outcome = {
            "status": body.status,
            "tenant_feedback": body.tenant_feedback,
            "created_at": now,
            "created_by": tenant_context.user_id,
        }
        updated = await self._repo.record_outcome(suggestion_id, tenant_context.tenant_id, outcome)
        await emit_suggestion_event(self._producer, "suggestion.outcome_recorded", updated)
        return redact_for_tenant(updated)

    async def close_suggestion(
        self,
        suggestion_id: str,
        tenant_context: TenantContext,
    ) -> dict:
        await self._repo.get_or_fail(suggestion_id, tenant_context.tenant_id)
        updated = await apply_transition(
            repo=self._repo,
            suggestion_id=suggestion_id,
            tenant_id=tenant_context.tenant_id,
            to_status=SuggestionStatus.CLOSED,
            actor_id=tenant_context.user_id,
            actor_kind="operator",
        )
        await emit_suggestion_event(self._producer, "suggestion.closed", updated)
        return updated

    async def get_audit_trail(
        self, suggestion_id: str, tenant_context: TenantContext
    ) -> list[dict]:
        record = await self.get_suggestion(suggestion_id, tenant_context)
        return record.get("audit_trail", [])
