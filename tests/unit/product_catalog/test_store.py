"""Store CRUD + tenant isolation on the in-memory BaseRepository backend."""
from __future__ import annotations

import pytest

from repositories.repos import reset_in_memory_stores
from services.product_catalog.models import CatalogNode, MappingProposal, MappingRule
from services.product_catalog.store import (
    ProductCatalogNodeRepository,
    ProductMappingProposalRepository,
    ProductMappingRuleRepository,
)


@pytest.fixture(autouse=True)
def _clean_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


def _node(stable_id: str = "feat-1", **kwargs) -> CatalogNode:
    return CatalogNode(
        kind=kwargs.pop("kind", "feature"),
        stable_id=stable_id,
        display_name=kwargs.pop("display_name", "Feature One"),
        **kwargs,
    )


class TestNodeCrud:
    async def test_upsert_get_roundtrip(self):
        repo = ProductCatalogNodeRepository()
        stored = await repo.upsert_node("t1", _node())
        assert stored.tenant_id == "t1"
        fetched = await repo.get_node("t1", "feat-1")
        assert fetched is not None
        assert fetched.model_dump() == stored.model_dump()

    async def test_upsert_overwrites_same_stable_id(self):
        repo = ProductCatalogNodeRepository()
        await repo.upsert_node("t1", _node())
        await repo.upsert_node("t1", _node(display_name="Renamed"))
        fetched = await repo.get_node("t1", "feat-1")
        assert fetched is not None and fetched.display_name == "Renamed"
        assert len(await repo.list_nodes("t1")) == 1

    async def test_list_filters_by_kind_and_status(self):
        repo = ProductCatalogNodeRepository()
        await repo.upsert_node("t1", _node("p-1", kind="product", display_name="P"))
        await repo.upsert_node("t1", _node("f-1"))
        await repo.upsert_node("t1", _node("f-2", status="retired", display_name="Old"))
        assert {n.stable_id for n in await repo.list_nodes("t1", kind="feature")} == {"f-1", "f-2"}
        assert {n.stable_id for n in await repo.list_nodes("t1", kind="feature", status="retired")} == {"f-2"}

    async def test_missing_node_is_none(self):
        repo = ProductCatalogNodeRepository()
        assert await repo.get_node("t1", "ghost") is None


class TestTenantIsolation:
    async def test_same_stable_id_is_isolated_per_tenant(self):
        repo = ProductCatalogNodeRepository()
        await repo.upsert_node("t1", _node(display_name="Tenant One"))
        await repo.upsert_node("t2", _node(display_name="Tenant Two"))
        one = await repo.get_node("t1", "feat-1")
        two = await repo.get_node("t2", "feat-1")
        assert one is not None and one.display_name == "Tenant One"
        assert two is not None and two.display_name == "Tenant Two"

    async def test_list_never_crosses_tenants(self):
        repo = ProductCatalogNodeRepository()
        await repo.upsert_node("t1", _node("only-t1"))
        assert await repo.list_nodes("t2") == []

    async def test_get_and_delete_never_cross_tenants(self):
        repo = ProductCatalogNodeRepository()
        await repo.upsert_node("t1", _node())
        assert await repo.get_node("t2", "feat-1") is None
        assert await repo.delete_scoped("t2", "feat-1") is False
        assert await repo.get_node("t1", "feat-1") is not None
        assert await repo.delete_scoped("t1", "feat-1") is True
        assert await repo.get_node("t1", "feat-1") is None


class TestRuleAndProposalCrud:
    async def test_rule_roundtrip_and_match_kind_filter(self):
        repo = ProductMappingRuleRepository()
        await repo.upsert_rule("t1", MappingRule(
            rule_id="r-1", match_kind="route", match_value="/checkout",
            precedence_class="tenant_catalog",
        ))
        await repo.upsert_rule("t1", MappingRule(
            rule_id="r-2", match_kind="event_name", match_value="order_completed",
            precedence_class="inferred", confidence=0.6,
        ))
        assert {r.rule_id for r in await repo.list_rules("t1")} == {"r-1", "r-2"}
        routes_only = await repo.list_rules("t1", match_kind="route")
        assert [r.rule_id for r in routes_only] == ["r-1"]
        assert routes_only[0].tenant_id == "t1"
        assert await repo.list_rules("t2") == []

    async def test_proposal_roundtrip_and_status_filter(self):
        repo = ProductMappingProposalRepository()
        await repo.upsert_proposal("t1", MappingProposal(
            rule_id="p-1", match_kind="selector", match_value="#buy",
            precedence_class="reviewed_discovery", evidence_count=4,
        ))
        await repo.upsert_proposal("t1", MappingProposal(
            rule_id="p-2", match_kind="agent_tool", match_value="create_order",
            precedence_class="inferred", status="approved",
        ))
        pending = await repo.list_proposals("t1", status="pending")
        assert [p.rule_id for p in pending] == ["p-1"]
        assert pending[0].evidence_count == 4
        assert {p.rule_id for p in await repo.list_proposals("t1")} == {"p-1", "p-2"}
        assert await repo.list_proposals("t2") == []
