"""POST /v1/ingest/feed: first use of a feed source needs a data-rights grant.

* granted: an active grant for feed:<source> allowing the tenant lake; the row
  carries the grant's relationship and ref.
* legacy: a source the tenant already fed keeps working, stamped unclassified
  and tenant-lake-only.
* denied: first use without a grant.
"""

from __future__ import annotations

import pytest

from repositories import repos
from repositories.lake import BronzeRepository
from connectors.integrations.data_rights import service as dr_service_mod
from connectors.integrations.data_rights.models import DataRightsGrantCreate
from ingestion.ingestion.feed_rights import feed_source_id, resolve_feed_rights


@pytest.fixture(autouse=True)
def _memory(monkeypatch: pytest.MonkeyPatch):
    async def no_pool():
        return None

    monkeypatch.setattr(repos, "get_pool", no_pool)
    repos.reset_in_memory_stores()
    service = dr_service_mod.DataRightsService()
    monkeypatch.setattr(dr_service_mod, "data_rights_service", service)
    yield service
    repos.reset_in_memory_stores()


async def _grant(service, tenant_id: str, source: str, *, lake: bool = True):
    return await service.create_grant(DataRightsGrantCreate(
        tenant_id=tenant_id, source_id=feed_source_id(source), connector_id=f"feed.{source}",
        connector_class="tenant_byod_data", data_category="onchain", data_sensitivity="unclassified",
        raw_data_owner="tenant", source_relationship="organization_system", tenant_lake_allowed=lake,
    ), granted_by_user_id="u1")


@pytest.mark.asyncio
async def test_first_use_without_a_grant_is_denied():
    rights = await resolve_feed_rights("t1", "dune")
    assert rights.outcome == "denied" and rights.source_id == "feed:dune"
    assert not rights.allowed


@pytest.mark.asyncio
async def test_a_grant_admits_and_names_relationship_and_ref(_memory):
    grant = await _grant(_memory, "t1", "dune")
    rights = await resolve_feed_rights("t1", "Dune")
    assert rights.outcome == "granted"
    assert rights.stamp() == {
        "source_id": "feed:dune",
        "source_relationship": "organization_system",
        "rights_outcome": "granted",
        "source_grant_refs": [grant.data_rights_grant_id],
    }


@pytest.mark.asyncio
async def test_a_grant_without_tenant_lake_does_not_admit(_memory):
    await _grant(_memory, "t1", "dune", lake=False)
    assert (await resolve_feed_rights("t1", "dune")).outcome == "denied"


@pytest.mark.asyncio
async def test_another_tenants_grant_does_not_count(_memory):
    await _grant(_memory, "t2", "dune")
    assert (await resolve_feed_rights("t1", "dune")).outcome == "denied"


@pytest.mark.asyncio
async def test_a_source_already_fed_stays_legacy_and_tenant_only():
    await BronzeRepository("feeds").ingest(
        source="dune", source_tag="feed:dune", provider_record_id="x1", payload={"a": 1},
        schema_version="1.0", entity_id="x1", entity_type="row", tenant_id="t1",
    )
    rights = await resolve_feed_rights("t1", "dune")
    assert rights.outcome == "legacy"
    assert rights.stamp() == {
        "source_id": "feed:dune", "source_relationship": "unclassified",
        "rights_outcome": "legacy", "lake_scope": "tenant_only",
    }
    # Another tenant's history does not make this tenant legacy.
    assert (await resolve_feed_rights("t2", "dune")).outcome == "denied"


@pytest.mark.asyncio
async def test_the_requirement_can_be_switched_off():
    assert (await resolve_feed_rights("t1", "dune", grant_required=False)).outcome == "legacy"
