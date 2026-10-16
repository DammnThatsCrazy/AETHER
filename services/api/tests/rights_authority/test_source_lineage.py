"""A mutation's rights decision resolves to the source grant and relationship behind it."""

from __future__ import annotations

import pytest

from connectors.integrations.data_rights.models import DataRightsGrant, GrantStatus
from tenancy.rights_authority.source_lineage import trace_source_authority

GRANT = DataRightsGrant(
    data_rights_grant_id="drg_1", tenant_id="tenant-1", source_id="provider-account:conn_1:shop-1",
    connector_id="shopify.admin.orders_read", connector_class="tenant_byod_data",
    data_category="commerce", data_sensitivity="internal", raw_data_owner="tenant",
    source_relationship="organization_system", tenant_graph_allowed=True,
    granted_by_user_id="admin", granted_at="2026-01-01T00:00:00+00:00",
    audit_event_id="audit_1", status=GrantStatus.ACTIVE,
)


class _Decisions:
    def __init__(self, rows):
        self.rows = rows

    async def get_for_tenant(self, decision_id, *, tenant_id):
        row = self.rows.get(decision_id)
        return row if row and row["tenant_id"] == tenant_id else None


async def _lookup(grant_id, *, tenant_id):
    return GRANT if grant_id == GRANT.data_rights_grant_id and tenant_id == GRANT.tenant_id else None


def _repo(**row):
    base = {"decision_id": "rdec_graph", "tenant_id": "tenant-1", "source_grant_refs": ["drg_1"]}
    base.update(row)
    return _Decisions({base["decision_id"]: base})


@pytest.mark.asyncio
async def test_graph_decision_traces_to_relationship_and_grant():
    trace = await trace_source_authority(
        "rdec_graph", tenant_id="tenant-1", decision_repository=_repo(), grant_lookup=_lookup,
    )
    assert trace.source_relationship == "organization_system"
    assert trace.source_id == "provider-account:conn_1:shop-1"
    assert trace.provider_identity == "shopify.admin.orders_read"
    assert trace.rights_source_class == "tenant_byod_data"
    assert trace.source_grant_ref == "drg_1"


@pytest.mark.asyncio
@pytest.mark.parametrize("tenant,row", [
    ("tenant-2", {}),                                     # another tenant's decision
    ("tenant-1", {"source_grant_refs": []}),              # consent-only decision
    ("tenant-1", {"source_grant_refs": ["drg_1", "drg_2"]}),
    ("tenant-1", {"source_grant_refs": ["drg_missing"]}),
])
async def test_untraceable_decisions_return_none(tenant, row):
    assert await trace_source_authority(
        "rdec_graph", tenant_id=tenant, decision_repository=_repo(**row), grant_lookup=_lookup,
    ) is None
