"""Durable communications synchronization ledger (§12.4).

Every connector sync/backfill opens a :class:`SyncRun` *before* provider work
begins and closes it with the observed counts, cursor movement, and a safe
error classification when it fails. The ledger is the customer-visible progress
surface (connection wizard) and the operator surface (Kyber), and it is the
truthful record of what a sync actually did — never a synthetic estimate.

Storage is the generic JSONB row shape via :class:`BaseRepository`, so the
ledger inherits the in-memory local-mode fallback (no Postgres required for
local dev or the golden fixture), exactly like ``connector_cursors`` and
``webhook_inbox``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field

from repositories.repos import BaseRepository

SyncMode = str  # "initial" | "backfill" | "incremental"
SyncRunStatus = str  # "queued" | "running" | "completed" | "failed" | "partial"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SyncRun(BaseModel):
    """One durable synchronization run (§12.4 field set)."""

    sync_run_id: str = Field(default_factory=lambda: f"syncrun_{uuid.uuid4().hex}")
    tenant_id: str
    connector_instance_id: str
    provider: str
    provider_product: Optional[str] = None
    provider_account_id: Optional[str] = None
    mode: SyncMode = "incremental"
    requested_window: Optional[str] = None
    effective_window: Optional[str] = None
    status: SyncRunStatus = "running"
    started_at: str = Field(default_factory=_now_iso)
    completed_at: Optional[str] = None
    cursor_before: Optional[str] = None
    cursor_after: Optional[str] = None
    pages_requested: int = 0
    records_received: int = 0
    records_deduplicated: int = 0
    records_rejected: int = 0
    facts_written: int = 0
    campaigns_created: int = 0
    messages_created: int = 0
    profiles_resolved: int = 0
    profiles_unresolved: int = 0
    replies_correlated: int = 0
    suppressions_updated: int = 0
    rate_limit_events: int = 0
    retry_count: int = 0
    safe_error_code: Optional[str] = None
    safe_error_detail: Optional[str] = None
    reconciliation_status: str = "not_run"  # not_run | pending | reconciled | drift
    triggered_by: str = "system"


class SyncRunRepository(BaseRepository):
    """Durable store for sync runs (JSONB table, in-memory local fallback)."""

    def __init__(self) -> None:
        super().__init__("comms_sync_runs")

    async def upsert(self, run: SyncRun) -> dict[str, Any]:
        payload = run.model_dump()
        payload["updated_at"] = _now_iso()
        return await self.insert(run.sync_run_id, payload)

    async def get(self, run_id: str) -> Optional[dict[str, Any]]:
        return await self.find_by_id(run_id)

    async def list_for_connector(
        self, tenant_id: str, connector_instance_id: str, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        rows = await self.find_many(
            {"tenant_id": tenant_id, "connector_instance_id": connector_instance_id},
            sort_by="created_at",
            sort_order="desc",
            limit=limit,
        )
        return rows

    async def list_for_tenant(
        self, tenant_id: str, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        return await self.find_many(
            {"tenant_id": tenant_id},
            sort_by="created_at",
            sort_order="desc",
            limit=limit,
        )


class SyncRunService:
    """Facade owning sync-run lifecycle transitions."""

    def __init__(self, repo: Optional[SyncRunRepository] = None) -> None:
        self.repo = repo or SyncRunRepository()

    async def open_run(
        self,
        *,
        tenant_id: str,
        connector_instance_id: str,
        provider: str,
        provider_account_id: Optional[str] = None,
        mode: SyncMode = "incremental",
        requested_window: Optional[str] = None,
        effective_window: Optional[str] = None,
        cursor_before: Optional[str] = None,
        triggered_by: str = "system",
    ) -> SyncRun:
        run = SyncRun(
            tenant_id=tenant_id,
            connector_instance_id=connector_instance_id,
            provider=provider,
            provider_product=provider,
            provider_account_id=provider_account_id,
            mode=mode,
            requested_window=requested_window,
            effective_window=effective_window or requested_window,
            cursor_before=cursor_before,
            status="running",
            triggered_by=triggered_by,
        )
        await self.repo.upsert(run)
        return run

    async def complete_run(
        self,
        run: SyncRun,
        *,
        status: SyncRunStatus,
        cursor_after: Optional[str] = None,
        counts: Optional[dict[str, int]] = None,
        safe_error_code: Optional[str] = None,
        safe_error_detail: Optional[str] = None,
        reconciliation_status: Optional[str] = None,
    ) -> SyncRun:
        run.status = status
        run.completed_at = _now_iso()
        if cursor_after is not None:
            run.cursor_after = cursor_after
        if reconciliation_status is not None:
            run.reconciliation_status = reconciliation_status
        run.safe_error_code = safe_error_code
        run.safe_error_detail = (safe_error_detail or "")[:500] or None
        for key, value in (counts or {}).items():
            if hasattr(run, key) and isinstance(value, int):
                setattr(run, key, value)
        await self.repo.upsert(run)
        return run

    async def list_for_connector(
        self, tenant_id: str, connector_instance_id: str, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        return await self.repo.list_for_connector(
            tenant_id, connector_instance_id, limit=limit
        )

    async def list_for_tenant(
        self, tenant_id: str, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        return await self.repo.list_for_tenant(tenant_id, limit=limit)


def derive_sync_counts(
    events: list[Any], ingest_counts: dict[str, int], *, ingested: int
) -> dict[str, int]:
    """Derive honest §12.4 counts from a sync's normalized events.

    Only counts that are deterministically observable from the event stream are
    populated; downstream stages (identity bridge, reconciliation) refine the
    rest. ``ingest_counts`` is the ``ingest_normalized_events`` return.
    """
    received = len(events)

    def _etype(ev: Any) -> str:
        return getattr(ev, "event_type", "") or ""

    campaigns = sum(1 for ev in events if _etype(ev).endswith(".campaign"))
    flows = sum(1 for ev in events if _etype(ev).endswith(".flow"))
    profiles = sum(1 for ev in events if _etype(ev).endswith(".profile"))
    replies = sum(1 for ev in events if _etype(ev) == "email_replied")
    suppression_events = sum(
        1
        for ev in events
        if _etype(ev) in ("unsubscribe_observed", "email_spam_complaint")
    )
    return {
        "records_received": received,
        "records_deduplicated": max(0, received - ingested),
        "facts_written": int(ingest_counts.get("communications", 0)),
        "campaigns_created": campaigns + flows,
        "messages_created": int(ingest_counts.get("catalog", 0)),
        "profiles_unresolved": profiles,
        "replies_correlated": replies,
        "suppressions_updated": suppression_events,
    }


__all__ = [
    "SyncRun",
    "SyncRunRepository",
    "SyncRunService",
    "derive_sync_counts",
]
