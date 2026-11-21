"""Dune is dual-use: one capability for the Olympus baseline and for tenants.

A global (platform) ingest lands under the reserved olympus scope and needs an
Olympus grant for dune:<source_tag>; a tenant ingest needs that tenant's grant.
Rows record the owner scope, relationship and grant. A source already fed in a
scope stays legacy; first use without a grant is refused.
"""

from __future__ import annotations

import importlib
from datetime import datetime, timezone

import pytest

from tests.unit.test_dune_feeder import backend_module_path


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("DUNE_SOURCE_GRANT_REQUIRED", "true")
    with backend_module_path():
        repos = importlib.import_module("repositories.repos")
        repos.reset_in_memory_stores()
        svc_mod = importlib.import_module("connectors.dune_feeder.service")
        models = importlib.import_module("connectors.dune_feeder.models")
        dr_service = importlib.import_module("connectors.integrations.data_rights.service")
        dr_models = importlib.import_module("connectors.integrations.data_rights.models")
        rel = importlib.import_module("shared.integration_contracts.source_relationship")
        common = importlib.import_module("shared.common.common")
        rights = dr_service.DataRightsService()
        monkeypatch.setattr(dr_service, "data_rights_service", rights)
        yield svc_mod.DuneFeederService(), models, rights, dr_models, rel, common, repos


def _request(models, tenant_scope=None, source_tag="eth_flows"):
    return models.FeederIngestRequest(
        query_result=models.DuneQueryResult(
            query_id="1", execution_id="exec1", query_name="q", rows=[{"a": 1}],
            pulled_at=datetime.now(timezone.utc).isoformat(),
        ),
        source_tag=source_tag, domain="onchain", tenant_scope=tenant_scope,
        quality_threshold=0.0,
    )


async def _olympus_grant(rights, dr_models, rel, source_tag="eth_flows"):
    return await rights.create_grant(dr_models.DataRightsGrantCreate(
        tenant_id=rel.OLYMPUS_SOURCE_TENANT_ID, source_id=f"dune:{source_tag}", connector_id="dune_api",
        connector_class="olympus_provider", data_category="onchain", raw_data_owner="olympus_labs",
        source_relationship="olympus_source",
    ), granted_by_user_id="op")


async def _tenant_grant(rights, dr_models, tenant_id, source_tag="eth_flows"):
    return await rights.create_grant(dr_models.DataRightsGrantCreate(
        tenant_id=tenant_id, source_id=f"dune:{source_tag}", connector_id="dune_api",
        connector_class="tenant_byod_data", data_category="onchain", raw_data_owner="tenant",
        source_relationship="organization_system", tenant_lake_allowed=True,
    ), granted_by_user_id="u1")


def _rows(repos):
    return list(repos._IN_MEMORY_STORES.get("dune_bronze_records", {}).values())


@pytest.mark.asyncio
async def test_global_ingest_is_an_olympus_source_under_an_olympus_grant(env):
    svc, models, rights, dr_models, rel, _common, repos = env
    grant = await _olympus_grant(rights, dr_models, rel)
    await svc.ingest(_request(models))
    [row] = _rows(repos)
    assert row["owner_scope"] == "olympus_system"
    assert row["license_status"] == "olympus_provider_contract"
    assert row["source_rights"]["source_relationship"] == "olympus_source"
    assert row["source_rights"]["source_grant_refs"] == [grant.data_rights_grant_id]


@pytest.mark.asyncio
async def test_tenant_ingest_uses_the_tenants_own_grant(env):
    svc, models, rights, dr_models, rel, common, repos = env
    await _olympus_grant(rights, dr_models, rel)
    # Olympus's grant does not admit a tenant's rows.
    with pytest.raises(common.ForbiddenError):
        await svc.ingest(_request(models, tenant_scope="t1"))
    await _tenant_grant(rights, dr_models, "t1")
    await svc.ingest(_request(models, tenant_scope="t1"))
    [row] = _rows(repos)
    assert row["owner_scope"] == "tenant" and row["tenant_scope"] == "t1"
    assert row["license_status"] == "tenant_rights_granted"
    assert row["source_rights"]["source_relationship"] == "organization_system"


@pytest.mark.asyncio
async def test_a_tenant_grant_does_not_admit_a_global_ingest(env):
    svc, models, rights, dr_models, _rel, common, _repos = env
    await _tenant_grant(rights, dr_models, "t1")
    with pytest.raises(common.ForbiddenError):
        await svc.ingest(_request(models))


@pytest.mark.asyncio
async def test_a_source_already_fed_in_its_scope_stays_legacy(env):
    svc, models, _rights, _dr_models, _rel, common, repos = env
    # A row written before grants were required, in tenant t2's scope.
    await svc._bronze.insert("old", {
        "record_id": "old", "source_tag": "eth_flows", "tenant_scope": "t2", "row_index": 0,
    })
    await svc.ingest(_request(models, tenant_scope="t2"))
    new = [r for r in _rows(repos) if r.get("record_id") != "old"]
    assert new and new[0]["license_status"] == "tenant_legacy"
    assert new[0]["source_rights"] == {
        "source_id": "dune:eth_flows", "source_relationship": "unclassified",
        "rights_outcome": "legacy", "lake_scope": "tenant_only",
    }
    # History in another tenant's scope does not make t3 legacy.
    with pytest.raises(common.ForbiddenError):
        await svc.ingest(_request(models, tenant_scope="t3"))
