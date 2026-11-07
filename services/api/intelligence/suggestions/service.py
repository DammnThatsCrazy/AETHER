"""SuggestionService — orchestrates OODA lifecycle, scoring, policy, and events."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Optional

from shared.auth.auth import TenantContext
from shared.cache.cache import CacheClient
from shared.common.common import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    utc_now,
)
from shared.events.events import EventProducer
from shared.graph.graph import GraphClient
from shared.logger.logger import get_logger

from .dispatcher import dispatch, resolve_dispatch_mode
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
    parse_timestamp,
)
from .outcome import record_and_close
from .policy import evaluate_suggestion_policy, redact_for_tenant, requires_approval
from .repository import SuggestionRepository
from .scorer import compute_scores

logger = get_logger("aether.suggestions.service")


_IDEMPOTENCY_NAMESPACE = uuid.UUID("5d0f4c2e-6a1b-4c57-9a43-2e8f1b7c9d10")

# Content that defines "the same request" for a replayed create.
_FINGERPRINT_FIELDS = (
    "org_id", "subject", "source", "source_ref", "suggestion_class", "title",
    "summary", "what", "why", "impact", "recommended_action", "expected_outcome",
    "confidence_score", "risk_score", "reversible", "expires_at",
)


def _request_fingerprint(create: SuggestionCreate, tenant_id: str, principal: Optional[str]) -> str:
    body = json.loads(create.model_dump_json(include=set(_FINGERPRINT_FIELDS)))
    canonical = json.dumps(
        {"tenant": tenant_id, "principal": principal, "body": body},
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _is_expired(record: dict) -> bool:
    expires_at = parse_timestamp(record.get("expires_at"))
    return expires_at is not None and expires_at <= parse_timestamp(utc_now().isoformat())


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
        principal = tenant_context.user_id
        fingerprint = _request_fingerprint(create, create.tenant_id, principal)
        if create.idempotency_key:
            # Deterministic id per tenant, principal, and key, so concurrent and
            # retried creates collide on the same row instead of duplicating.
            suggestion_id = str(uuid.uuid5(
                _IDEMPOTENCY_NAMESPACE,
                f"{create.tenant_id}\x1f{principal or ''}\x1f{create.idempotency_key}",
            ))
        else:
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
            idempotency_key=create.idempotency_key,
            request_fingerprint=fingerprint,
            created_by=principal,
            created_at=now,
            updated_at=now,
        )

        if create.idempotency_key:
            if not await self._repo.create_if_absent(suggestion):
                existing = await self._repo.get(suggestion_id, create.tenant_id)
                if existing is not None and existing.get("request_fingerprint") == fingerprint:
                    return existing  # replay: same key, same content, no new event
                raise ConflictError("idempotency_key was already used with different content")
            record = await self._repo.get_or_fail(suggestion_id, create.tenant_id)
        else:
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

    async def _expire_if_due(self, record: dict, tenant_context: TenantContext) -> None:
        """Move a past-due suggestion to EXPIRED and refuse the action.

        The reviewer and executor are always the authenticated principal; a
        client-supplied ``actor_id`` is never trusted.
        """
        if not _is_expired(record):
            return
        status = SuggestionStatus(record["status"])
        if status in (SuggestionStatus.SUGGESTED, SuggestionStatus.REVIEW_REQUIRED,
                      SuggestionStatus.APPROVED, SuggestionStatus.DETECTED,
                      SuggestionStatus.ORIENTED):
            expired = await apply_transition(
                repo=self._repo,
                suggestion_id=record["id"],
                tenant_id=tenant_context.tenant_id,
                to_status=SuggestionStatus.EXPIRED,
                actor_kind="system",
                notes="expires_at passed before the action",
            )
            await emit_suggestion_event(self._producer, "suggestion.expired", expired)
        raise BadRequestError("This suggestion has expired.")

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
        await self._expire_if_due(record, tenant_context)
        updated = await apply_transition(
            repo=self._repo,
            suggestion_id=suggestion_id,
            tenant_id=tenant_context.tenant_id,
            to_status=SuggestionStatus.APPROVED,
            actor_id=tenant_context.user_id,
            actor_kind="tenant_user" if tenant_context.user_id else "operator",
            notes=body.notes,
        )
        await emit_suggestion_event(self._producer, "suggestion.approved", updated)
        if resolve_dispatch_mode(updated) == "notify_only":
            # Approval hands a delivery-eligible suggestion to the delivery pipeline
            # (a DeliveryIntent + DeliveryJob per active channel). The suggestion
            # stays APPROVED until the delivery worker confirms a provider receipt.
            # A delivery problem never undoes the approval.
            try:
                updated = await dispatch(updated, tenant_context, self, execution_enabled=False)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Delivery hand-off failed for suggestion {suggestion_id!r}: {exc}")
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
            actor_id=tenant_context.user_id,
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
            actor_id=tenant_context.user_id,
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
        await self._expire_if_due(record, tenant_context)

        if resolve_dispatch_mode(record) == "legacy_recommendation_execute":
            # The dispatcher runs the recommendation path and moves the
            # suggestion on to EXECUTED (or FAILED), so it is never left in EXECUTING.
            return await dispatch(record, tenant_context, self, execution_enabled=True)

        updated = await apply_transition(
            repo=self._repo,
            suggestion_id=suggestion_id,
            tenant_id=tenant_context.tenant_id,
            to_status=SuggestionStatus.EXECUTING,
            actor_id=tenant_context.user_id,
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
        await self._expire_if_due(record, tenant_context)

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
        """Record an outcome and run the outcome loop (MEASURED → LEARNED → CLOSED)."""
        return await record_and_close(
            suggestion_id, body, self._repo, self._producer, tenant_context,
        )

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
