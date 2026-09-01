"""Revocation/impact facade over the durable IRRL ledger."""

from __future__ import annotations

from shared.rights_authority.contracts import RevokeRightsAuthority, RightsImpactGraph
from shared.rights_authority.service import RightsAuthority, rights_authority


class RightsImpactService:
    def __init__(self, authority: RightsAuthority | None = None) -> None:
        self._authority = authority or rights_authority

    async def revoke(self, command: RevokeRightsAuthority) -> RightsImpactGraph:
        return await self._authority.revoke(command)

    async def impact(self, root_refs: list[str], tenant_id: str | None = None) -> RightsImpactGraph:
        return await self._authority.impact(root_refs, tenant_id)


rights_impact_service = RightsImpactService()

__all__ = ["RightsImpactService", "rights_impact_service"]
