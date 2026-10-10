"""Repositories for the Security & Governance control plane.

Each repository subclasses BaseRepository (JSONB-backed in production, in-memory
for local dev). All records carry a tenant_id (nullable for Olympus/system-scope
records) so tenant-scoped reads stay isolated.
"""
from __future__ import annotations

from typing import Any, Optional

from repositories.repos import BaseRepository


class _ScopedRepo(BaseRepository):
    """Shared helpers for tenant-scoped governance repositories."""

    async def list_for_tenant(
        self, tenant_id: str, limit: int = 100, offset: int = 0,
        extra: Optional[dict[str, Any]] = None,
    ) -> list[dict]:
        filters: dict[str, Any] = {"tenant_id": tenant_id}
        if extra:
            filters.update(extra)
        return await self.find_many(filters=filters, limit=limit, offset=offset)

    async def list_all(
        self, limit: int = 200, offset: int = 0,
        extra: Optional[dict[str, Any]] = None,
    ) -> list[dict]:
        return await self.find_many(filters=extra or None, limit=limit, offset=offset)


class SecurityAuditEventRepository(_ScopedRepo):
    def __init__(self) -> None:
        super().__init__("security_audit_events")

    async def latest_for_tenant(self, tenant_id: str, limit: int = 50) -> list[dict]:
        return await self.list_for_tenant(tenant_id, limit=limit)


class PolicyDecisionRepository(_ScopedRepo):
    def __init__(self) -> None:
        super().__init__("security_policy_decisions")


class BreakGlassRepository(_ScopedRepo):
    def __init__(self) -> None:
        super().__init__("security_break_glass_requests")


class DataRetentionPolicyRepository(_ScopedRepo):
    def __init__(self) -> None:
        super().__init__("security_data_retention_policies")


class DataRequestRepository(_ScopedRepo):
    def __init__(self) -> None:
        super().__init__("security_data_requests")


class EvidencePackRepository(_ScopedRepo):
    def __init__(self) -> None:
        super().__init__("security_evidence_packs")


class IsolationResultRepository(_ScopedRepo):
    def __init__(self) -> None:
        super().__init__("security_isolation_results")
