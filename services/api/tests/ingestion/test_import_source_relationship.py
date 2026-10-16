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
async def test_personal_account_import_grant_admits():
    grant = _grant(
        source_relationship="personal_account", raw_data_owner="subject",
        subject_ref="person_1", consent_basis="explicit_opt_in",
    )
    evidence = await _admit(grant)
    assert evidence.source_grant_ref == "drg_import"


# olympus_source and internal_system grants are built directly: grant creation
# refuses them outside the Olympus scope, so this covers a store that holds one.
NON_IMPORT_GRANTS = {
    "partner_feed": dict(connector_class="partner_feed", raw_data_owner="partner", contract_id="ctr_1"),
    "olympus_source": dict(connector_class="olympus_provider", raw_data_owner="olympus_labs"),
    "internal_system": dict(connector_class="olympus_provider", raw_data_owner="olympus_labs"),
    "public_reference": dict(connector_class="tenant_byod_data", raw_data_owner="public"),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("relationship", sorted(NON_IMPORT_GRANTS))
async def test_non_tenant_grant_cannot_admit_an_import(relationship):
    grant = _grant(source_relationship=relationship, **NON_IMPORT_GRANTS[relationship])
    with pytest.raises(ImportRightsDenied) as exc:
        await _admit(grant)
    assert "source_relationship_mismatch" in exc.value.evidence.reason_codes


@pytest.mark.asyncio
async def test_grant_lookup_outage_denies_as_authority_unavailable():
    admission = _admission(_grant())

    async def unavailable(*_args, **_kwargs):
        raise ConnectionError("grant store down")

    admission._grant_service.get_grant = unavailable
    with pytest.raises(ImportRightsDenied) as exc:
        await admission.admit(
            tenant_id="tenant-1", import_id="imp_1", commit_id="impc_1",
            source_id="crm-export", actor="admin_1",
        )
    reasons = exc.value.evidence.reason_codes
    assert "rights_authority_unavailable" in reasons
    assert "source_relationship_mismatch" not in reasons
