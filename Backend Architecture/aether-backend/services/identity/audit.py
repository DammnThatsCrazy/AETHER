"""Durable audit record creation for all identity resolution decisions.

Every merge, link, split, create, block, or conflict creates an audit
record. Records are append-only and must never be deleted.
"""

from __future__ import annotations

from typing import Optional

from .models import ConfidenceTier, MergeDecision
from .repository import IdentityResolutionRepository


class IdentityAuditWriter:
    """Creates durable audit records for identity decisions."""

    def __init__(self, repo: IdentityResolutionRepository) -> None:
        self._repo = repo

    async def record_resolution(
        self,
        tenant_id: str,
        decision: MergeDecision,
        canonical_entity_id: str,
        candidate_entity_ids: list[str],
        confidence: float,
        confidence_tier: ConfidenceTier,
        reason_codes: list[str],
        source_event_ids: list[str],
        policy_result: str,
        consent_snapshot: Optional[dict] = None,
    ) -> str:
        """Create an audit record and return the audit_id."""
        record = await self._repo.create_audit_record(
            tenant_id=tenant_id,
            decision=decision.value,
            canonical_entity_id=canonical_entity_id,
            candidate_entity_ids=candidate_entity_ids,
            confidence=confidence,
            confidence_tier=confidence_tier,
            reason_codes=reason_codes,
            source_event_ids=source_event_ids,
            policy_result=policy_result,
            consent_snapshot=consent_snapshot,
        )
        return record["id"]

    async def record_merge(
        self,
        tenant_id: str,
        from_entity_id: str,
        into_entity_id: str,
        resulting_entity_id: str,
        confidence: float,
        confidence_tier: ConfidenceTier,
        reason_codes: list[str],
        source_event_ids: list[str],
        actor_type: str = "system",
        actor_id: str = "",
    ) -> str:
        record = await self._repo.create_merge_event(
            tenant_id=tenant_id,
            from_entity_id=from_entity_id,
            into_entity_id=into_entity_id,
            resulting_entity_id=resulting_entity_id,
            confidence=confidence,
            confidence_tier=confidence_tier,
            reason_codes=reason_codes,
            source_event_ids=source_event_ids,
            actor_type=actor_type,
            actor_id=actor_id,
        )
        return record["id"]

    async def record_split(
        self,
        tenant_id: str,
        original_entity_id: str,
        resulting_entity_ids: list[str],
        reason: str,
        actor_type: str,
        actor_id: str,
        source_merge_event_id: Optional[str] = None,
    ) -> str:
        record = await self._repo.create_split_event(
            tenant_id=tenant_id,
            original_entity_id=original_entity_id,
            resulting_entity_ids=resulting_entity_ids,
            reason=reason,
            actor_type=actor_type,
            actor_id=actor_id,
            source_merge_event_id=source_merge_event_id,
        )
        return record["id"]
