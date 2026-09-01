"""Derivation registry facade kept separate from policy evaluation."""

from __future__ import annotations

from shared.rights_authority.contracts import ArtifactRef, DerivationEdge, TransformEvidence
from shared.rights_authority.service import RightsAuthority, rights_authority


class DerivationRegistry:
    def __init__(self, authority: RightsAuthority | None = None) -> None:
        self._authority = authority or rights_authority

    async def record(self, edge: DerivationEdge) -> None:
        await self._authority.record_derivation(edge)

    async def descendants(self, root_refs: list[str]) -> list[ArtifactRef]:
        return await self._authority.descendants(root_refs)

    async def prove_transform(
        self, transform_ref: str, inputs: list[ArtifactRef], evidence: dict | None = None,
    ) -> TransformEvidence:
        return await self._authority.prove_transform(transform_ref, inputs, evidence)


derivation_registry = DerivationRegistry()

__all__ = ["DerivationRegistry", "derivation_registry"]
