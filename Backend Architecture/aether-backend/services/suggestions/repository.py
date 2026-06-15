"""SuggestionRepository — JSONB-backed, tenant-isolated, in-memory fallback."""

from __future__ import annotations

import json
from typing import Any, Optional

from repositories.repos import BaseRepository
from shared.common.common import NotFoundError, utc_now
from shared.logger.logger import get_logger

from .models import (
    Suggestion,
    SuggestionQuery,
    SuggestionStatus,
    SuggestionSummary,
)

logger = get_logger("aether.suggestions.repository")


class SuggestionRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("suggestions")

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create(self, suggestion: Suggestion) -> dict:
        data = json.loads(suggestion.model_dump_json())
        return await self.insert(suggestion.id, data)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get(self, suggestion_id: str, tenant_id: str) -> Optional[dict]:
        record = await self.find_by_id(suggestion_id)
        if record is None:
            return None
        if record.get("tenant_id") != tenant_id:
            return None
        return record

    async def get_or_fail(self, suggestion_id: str, tenant_id: str) -> dict:
        record = await self.get(suggestion_id, tenant_id)
        if record is None:
            raise NotFoundError(f"Suggestion {suggestion_id!r} not found")
        return record

    async def list(self, query: SuggestionQuery) -> list[dict]:
        filters: dict[str, Any] = {"tenant_id": query.tenant_id}
        if query.org_id:
            filters["org_id"] = query.org_id

        rows = await self.find_many(
            filters=filters,
            limit=query.limit,
            offset=query.offset,
            sort_by="created_at",
            sort_order="desc",
        )

        # In-memory post-filter (DB path uses filters above for tenant scoping;
        # enum filters applied here for both paths since BaseRepository only
        # supports equality string matching, not IN-set).
        if query.statuses:
            status_vals = {s.value for s in query.statuses}
            rows = [r for r in rows if r.get("status") in status_vals]
        if query.classes:
            class_vals = {c.value for c in query.classes}
            rows = [r for r in rows if r.get("suggestion_class") in class_vals]
        if query.priorities:
            priority_vals = {p.value for p in query.priorities}
            rows = [r for r in rows if r.get("priority") in priority_vals]
        if query.sources:
            source_vals = {s.value for s in query.sources}
            rows = [r for r in rows if r.get("source") in source_vals]
        if query.min_priority_score is not None:
            rows = [r for r in rows if (r.get("priority_score") or 0.0) >= query.min_priority_score]
        if not query.include_closed:
            terminal = {
                SuggestionStatus.CLOSED.value,
                SuggestionStatus.REJECTED.value,
                SuggestionStatus.SUPPRESSED.value,
                SuggestionStatus.EXPIRED.value,
            }
            rows = [r for r in rows if r.get("status") not in terminal]

        return rows

    async def list_review_queue(self, tenant_id: str, limit: int = 50) -> list[dict]:
        return await self.find_many(
            filters={"tenant_id": tenant_id, "status": SuggestionStatus.REVIEW_REQUIRED.value},
            limit=limit,
            sort_by="created_at",
            sort_order="asc",
        )

    async def list_by_subject(
        self, tenant_id: str, subject_kind: str, subject_id: str
    ) -> list[dict]:
        rows = await self.find_many(
            filters={"tenant_id": tenant_id},
            limit=200,
        )
        return [
            r for r in rows
            if r.get("subject", {}).get("kind") == subject_kind
            and r.get("subject", {}).get("id") == subject_id
        ]

    async def find_by_source_ref(
        self, tenant_id: str, source: str, source_id: str
    ) -> Optional[dict]:
        rows = await self.find_many(
            filters={"tenant_id": tenant_id, "source": source},
            limit=200,
        )
        for r in rows:
            ref = r.get("source_ref") or {}
            if ref.get("id") == source_id:
                return r
        return None

    # ------------------------------------------------------------------
    # Update / transition
    # ------------------------------------------------------------------

    async def patch(self, suggestion_id: str, tenant_id: str, patch: dict) -> dict:
        record = await self.get_or_fail(suggestion_id, tenant_id)
        record.update(patch)
        record["updated_at"] = utc_now().isoformat()
        return await self.update(suggestion_id, record)

    async def transition(
        self,
        suggestion_id: str,
        tenant_id: str,
        from_status: str,
        to_status: str,
        audit_event: dict,
    ) -> dict:
        record = await self.get_or_fail(suggestion_id, tenant_id)
        if record["status"] != from_status:
            from shared.common.common import BadRequestError
            raise BadRequestError(
                f"Expected status {from_status!r} but found {record['status']!r}"
            )
        record["status"] = to_status
        record["updated_at"] = utc_now().isoformat()
        record.setdefault("audit_trail", []).append(audit_event)
        return await self.update(suggestion_id, record)

    async def append_audit(
        self, suggestion_id: str, tenant_id: str, audit_event: dict
    ) -> dict:
        record = await self.get_or_fail(suggestion_id, tenant_id)
        record.setdefault("audit_trail", []).append(audit_event)
        record["updated_at"] = utc_now().isoformat()
        return await self.update(suggestion_id, record)

    async def record_outcome(
        self, suggestion_id: str, tenant_id: str, outcome: dict
    ) -> dict:
        return await self.patch(suggestion_id, tenant_id, {"outcome": outcome})

    # ------------------------------------------------------------------
    # Aggregates
    # ------------------------------------------------------------------

    async def summary(
        self, tenant_id: str, filters: Optional[dict] = None
    ) -> SuggestionSummary:
        base_filters: dict[str, Any] = {"tenant_id": tenant_id}
        if filters:
            base_filters.update(filters)

        rows = await self.find_many(filters=base_filters, limit=5000)

        open_statuses = {
            SuggestionStatus.DETECTED.value,
            SuggestionStatus.ORIENTED.value,
            SuggestionStatus.SUGGESTED.value,
            SuggestionStatus.APPROVED.value,
            SuggestionStatus.EXECUTING.value,
            SuggestionStatus.DELIVERED.value,
        }

        by_class: dict[str, int] = {}
        by_priority: dict[str, int] = {}
        by_status: dict[str, int] = {}
        open_count = review_count = approved_count = 0
        executed_count = failed_count = closed_count = 0

        for r in rows:
            st = r.get("status", "unknown")
            cl = r.get("suggestion_class", "unknown")
            pr = r.get("priority", "unknown")
            by_status[st] = by_status.get(st, 0) + 1
            by_class[cl] = by_class.get(cl, 0) + 1
            by_priority[pr] = by_priority.get(pr, 0) + 1
            if st in open_statuses:
                open_count += 1
            if st == SuggestionStatus.REVIEW_REQUIRED.value:
                review_count += 1
            if st == SuggestionStatus.APPROVED.value:
                approved_count += 1
            if st in (SuggestionStatus.EXECUTED.value, SuggestionStatus.MEASURED.value, SuggestionStatus.LEARNED.value):
                executed_count += 1
            if st == SuggestionStatus.FAILED.value:
                failed_count += 1
            if st == SuggestionStatus.CLOSED.value:
                closed_count += 1

        return SuggestionSummary(
            total=len(rows),
            open=open_count,
            review_required=review_count,
            approved=approved_count,
            executed=executed_count,
            failed=failed_count,
            closed=closed_count,
            by_class=by_class,
            by_priority=by_priority,
            by_status=by_status,
        )
