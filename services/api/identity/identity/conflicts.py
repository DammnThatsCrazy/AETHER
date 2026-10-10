"""Conflict and candidate queue management for identity resolution.

A conflict arises when two or more candidate entities have strong but
contradictory identity signals (e.g., same email hash but different
user IDs). Conflicts must be resolved by an operator or by the
recompute pipeline before the entities can be merged.
"""

from __future__ import annotations

from typing import Optional

from .repository import IdentityResolutionRepository


class IdentityConflictManager:
    """Creates and resolves identity conflict records."""

    def __init__(self, repo: IdentityResolutionRepository) -> None:
        self._repo = repo

    async def open_conflict(
        self,
        tenant_id: str,
        candidate_entity_ids: list[str],
        candidate_aliases: list[dict],
        conflict_type: str,
        confidence: float,
        reason_codes: list[str],
    ) -> str:
        """Open a new conflict record and return conflict_id."""
        record = await self._repo.create_conflict(
            tenant_id=tenant_id,
            candidate_entity_ids=candidate_entity_ids,
            candidate_aliases=candidate_aliases,
            conflict_type=conflict_type,
            confidence=confidence,
            reason_codes=reason_codes,
        )
        return record["id"]

    async def resolve_conflict(
        self,
        tenant_id: str,
        conflict_id: str,
        resolved_by: str,
    ) -> Optional[dict]:
        return await self._repo.resolve_conflict(conflict_id, resolved_by, tenant_id)

    async def list_open_conflicts(
        self,
        tenant_id: str,
        limit: int = 50,
    ) -> list[dict]:
        return await self._repo.get_conflicts(tenant_id, status="open", limit=limit)

    async def list_all_conflicts(
        self,
        tenant_id: str,
        limit: int = 100,
    ) -> list[dict]:
        return await self._repo.get_conflicts(tenant_id, limit=limit)
