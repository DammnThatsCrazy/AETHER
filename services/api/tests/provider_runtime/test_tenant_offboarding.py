"""Deleting a tenant closes its sources: grants revoked, credentials deleted, connections closed."""

from __future__ import annotations

import pytest

from repositories import repos
from connectors.integrations.data_rights import service as dr_service_mod
from connectors.integrations.data_rights.models import DataRightsGrantCreate, GrantStatus
from connectors.provider_runtime.connection import ConnectionOrchestrator, ProviderConnection
from connectors.provider_runtime.tenant_offboarding import close_tenant_sources


@pytest.fixture(autouse=True)
def _memory(monkeypatch: pytest.MonkeyPatch):
    async def no_pool():
        return None

    monkeypatch.setattr(repos, "get_pool", no_pool)
    repos.reset_in_memory_stores()
    yield
    repos.reset_in_memory_stores()


class _Broker:
    def __init__(self):
        self.deleted: list[tuple[str, str]] = []

    def provider_ref(self, tenant_id, identity):
        return f"{tenant_id}:{identity}"

    async def delete(self, tenant_id, ref):
        self.deleted.append((tenant_id, ref))
        return True


async def _grant(service, tenant_id, source_id):
    return await service.create_grant(DataRightsGrantCreate(
        tenant_id=tenant_id, source_id=source_id, connector_id="shopify.admin.orders_read",
        connector_class="tenant_byod_data", data_category="commerce", data_sensitivity="confidential",
        raw_data_owner="tenant", source_relationship="organization_system", tenant_lake_allowed=True,
    ), granted_by_user_id="u1")


@pytest.mark.asyncio
async def test_tenant_sources_close_and_other_tenants_are_untouched():
    service = dr_service_mod.DataRightsService()
    orchestrator = ConnectionOrchestrator()
    orchestrator.broker = _Broker()
    await _grant(service, "t1", "provider-account:c1:a")
    await _grant(service, "t1", "feed:dune")
    keep = await _grant(service, "t2", "provider-account:c9:a")
    for cid, tenant, ref in (("c1", "t1", "ref-shared"), ("c2", "t1", "ref-shared"), ("c3", "t1", ""), ("c9", "t2", "ref-9")):
        await orchestrator.connections.upsert(ProviderConnection(
            connection_id=cid, tenant_id=tenant, provider_identity="shopify.admin.orders_read",
            credential_ref=ref, state="connected",
        ))

    counts = await close_tenant_sources("t1", actor="tenant_deletion", grant_service=service, orchestrator=orchestrator)

    assert counts["grants_revoked"] == 2
    assert counts["credentials_deleted"] == 1  # the shared secret is deleted once
    assert orchestrator.broker.deleted == [("t1", "ref-shared")]
    assert not [g for g in await service.list_grants(tenant_id="t1", status=GrantStatus.ACTIVE) if g.revoked_at is None]
    for cid in ("c1", "c2", "c3"):
        closed = await orchestrator.connections.find(cid)
        assert closed.state in ("revoked", "disabled") and not closed.credential_ref
    other = await orchestrator.connections.find("c9")
    assert other.state == "connected" and other.credential_ref == "ref-9"
    assert (await service.get_grant(keep.data_rights_grant_id)).revoked_at is None
