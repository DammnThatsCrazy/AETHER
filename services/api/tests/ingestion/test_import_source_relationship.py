"""Imports are tenant/subject sources; a partner or Olympus grant cannot admit one."""

from __future__ import annotations

import pytest

from connectors.integrations.data_rights.models import DataRightsGrant, GrantStatus
from connectors.integrations.data_rights.service import DataRightsService
from ingestion.imports.rights_admission import ImportRightsAdmission, ImportRightsDenied
from tenancy.rights_authority.resolver import EffectiveRightsResolver


class _Decisions:
    def __init__(self):
        self.rows = {}

    async def record(self, decision, *, identity_key=None):
        body = decision.model_dump(mode="json")
        self.rows[body["decision_id"]] = body
        return body

    async def find_by_identity(self, tenant_id, identity_key, limit=1):
        return None


def _grant(**changes):
    values = dict(
        data_rights_grant_id="drg_import", tenant_id="tenant-1", source_id="crm-export",
        connector_id="csv_import", connector_class="tenant_import", data_category="customer",
        data_sensitivity="internal", raw_data_owner="tenant", source_relationship="organization_system",
        tenant_lake_allowed=True, tenant_graph_allowed=True, tenant_insights_allowed=True,
        legal_basis="contract", granted_by_user_id="admin", granted_at="2026-01-01T00:00:00+00:00",
        audit_event_id="audit_import", status=GrantStatus.ACTIVE,
    )
    values.update(changes)
    return DataRightsGrant(**values)


def _admission(grant):
    service = DataRightsService()
    service._repository._local_grants[grant.data_rights_grant_id] = grant
    resolver = EffectiveRightsResolver(
        grant_loader=service.get_effective_grant, decision_repository=_Decisions(),
    )
    return ImportRightsAdmission(resolver=resolver, grant_service=service)


async def _admit(grant):
    return await _admission(grant).admit(
        tenant_id="tenant-1", import_id="imp_1", commit_id="impc_1",
        source_id="crm-export", actor="admin_1",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("relationship", ["organization_system", "unclassified"])
async def test_tenant_and_legacy_import_grants_admit(relationship):
    evidence = await _admit(_grant(source_relationship=relationship))
    assert evidence.source_grant_ref == "drg_import"


@pytest.mark.asyncio
async def test_partner_grant_cannot_admit_an_import():
    grant = _grant(
        connector_class="partner_feed", raw_data_owner="partner",
        source_relationship="partner_feed", contract_id="ctr_1",
    )
    with pytest.raises(ImportRightsDenied) as exc:
        await _admit(grant)
    assert "source_relationship_mismatch" in exc.value.evidence.reason_codes
