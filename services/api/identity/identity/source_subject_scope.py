"""Exact source-to-canonical subject resolution shared by 360 projections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Protocol

from graph.operational_intelligence.models import EvidenceRef


SourceSubjectScopeState = Literal["available", "unknown", "degraded"]


@dataclass(frozen=True)
class SourceSubjectScopeRead:
    """Verified source identity binding to one tenant-owned canonical entity."""

    tenant_id: str
    source_identity_id: str
    state: SourceSubjectScopeState
    canonical_entity_id: Optional[str] = None
    evidence_refs: tuple[EvidenceRef, ...] = ()
    reason: Optional[str] = None


class SourceSubjectScopeReader(Protocol):
    """Resolve an exact source identity through the canonical Identity360 authority."""

    async def resolve(
        self, tenant_id: str, source_identity_id: str
    ) -> SourceSubjectScopeRead: ...


class RepositorySourceSubjectScopeReader:
    """Adapter over Identity360's exact tenant-bound source identity read."""

    def __init__(self, identity_provider=None) -> None:
        self._identity_provider = identity_provider

    async def resolve(self, tenant_id: str, source_identity_id: str) -> SourceSubjectScopeRead:
        if self._identity_provider is None:
            from identity.identity.identity360_provider import Identity360Provider

            self._identity_provider = Identity360Provider()
        try:
            result = await self._identity_provider.read(
                tenant_id,
                "source",
                source_identity_id,
                requested_slot_ids={"resolved_subject_identity"},
            )
        except Exception:  # noqa: BLE001 - identity authority is fail-closed
            return SourceSubjectScopeRead(
                tenant_id,
                source_identity_id,
                "degraded",
                reason="source_identity_authority_unavailable",
            )

        slot = result.slot("resolved_subject_identity")
        if slot.state != "available":
            return SourceSubjectScopeRead(
                tenant_id,
                source_identity_id,
                "unknown" if slot.state == "unknown" else "degraded",
                reason=slot.reason or "source_identity_binding_unresolved",
            )
        canonical_entity = slot.content.get("canonicalEntity")
        resolution = slot.content.get("resolution")
        canonical_entity_id = (
            canonical_entity.get("id") if isinstance(canonical_entity, dict) else None
        )
        if (
            result.tenant_id != tenant_id
            or result.subject_kind != "source"
            or result.subject_id != source_identity_id
            or not isinstance(canonical_entity_id, str)
            or not canonical_entity_id
            or not isinstance(resolution, dict)
            or resolution.get("state") != "resolved"
            or resolution.get("exactIdMatch") is not True
        ):
            return SourceSubjectScopeRead(
                tenant_id,
                source_identity_id,
                "unknown",
                reason="source_identity_canonical_join_unverified",
            )
        return SourceSubjectScopeRead(
            tenant_id,
            source_identity_id,
            "available",
            canonical_entity_id=canonical_entity_id,
            evidence_refs=slot.evidence_refs,
        )


__all__ = [
    "RepositorySourceSubjectScopeReader",
    "SourceSubjectScopeRead",
    "SourceSubjectScopeReader",
    "SourceSubjectScopeState",
]
