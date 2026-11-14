"""Read-only trace from a governed write's rights decision to its source authority.

Resolves rights_decision_ref → RightsDecision → DataRightsGrant → relationship,
source scope, provider identity and rights-source class, so graph state never
needs to carry source-governance metadata itself.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class SourceAuthorityTrace(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str
    rights_decision_ref: str
    source_grant_ref: str
    source_id: str
    source_relationship: str
    provider_identity: str
    rights_source_class: str


async def trace_source_authority(
    rights_decision_ref: str,
    *,
    tenant_id: str,
    decision_repository: Any = None,
    grant_lookup: Any = None,
) -> Optional[SourceAuthorityTrace]:
    """Return the governing source for a decision, or None when it is not source-governed.

    Revoked or expired grants still trace: lineage is historical, not an authorization.
    """
    if decision_repository is None:
        from tenancy.rights_authority.repositories import rights_decision_repository as decision_repository
    if grant_lookup is None:
        from connectors.integrations.data_rights.service import data_rights_service

        grant_lookup = data_rights_service.get_grant

    row = await decision_repository.get_for_tenant(rights_decision_ref, tenant_id=tenant_id)
    if not isinstance(row, dict):
        return None
    grant_refs = list(row.get("source_grant_refs") or [])
    if len(grant_refs) != 1:
        return None
    grant = await grant_lookup(grant_refs[0], tenant_id=tenant_id)
    if grant is None or grant.tenant_id != tenant_id:
        return None
    return SourceAuthorityTrace(
        tenant_id=tenant_id,
        rights_decision_ref=rights_decision_ref,
        source_grant_ref=grant.data_rights_grant_id,
        source_id=grant.source_id,
        source_relationship=grant.source_relationship,
        provider_identity=grant.connector_id,
        rights_source_class=grant.connector_class,
    )
