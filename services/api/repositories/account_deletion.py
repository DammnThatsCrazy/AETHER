"""Durable repositories for account deletion and detached legal retention."""

from __future__ import annotations

from typing import Any, Optional

from repositories.repos import BaseRepository
from repositories.typed_repo import TypedTableRepository


class AccountDeletionWorkflowRepository(TypedTableRepository):
    """PostgreSQL-backed workflow state with an idempotent tenant key."""

    table_name = "account_deletion_workflows"
    columns = (
        "id", "tenant_id", "requested_at", "recovery_until", "status",
        "actor_id", "actor_type", "reauth_evidence", "idempotency_key",
        "storage_results", "retry_count", "completed_at", "failed_at",
        "cancelled_at", "erasure_manifest", "created_at", "updated_at",
    )
    jsonb_columns = frozenset({"reauth_evidence", "storage_results", "erasure_manifest"})
    conflict_key = ("tenant_id", "idempotency_key")

    async def find_by_request_id(self, request_id: str) -> Optional[dict]:
        return await self.find_one({"id": request_id})

    async def find_by_tenant(self, tenant_id: str) -> list[dict]:
        return await self.find_many({"tenant_id": tenant_id}, limit=100)

    async def find_by_idempotency(self, tenant_id: str, idempotency_key: str) -> Optional[dict]:
        return await self.find_one({"tenant_id": tenant_id, "idempotency_key": idempotency_key})

    async def update_request(self, request_id: str, changes: dict[str, Any]) -> bool:
        return await self.update_by_key({"id": request_id}, changes)


class DetachedRetentionStubRepository(BaseRepository):
    """Minimal non-operational stubs for legally retained billing/audit facts."""

    def __init__(self) -> None:
        super().__init__("account_retention_stubs")
