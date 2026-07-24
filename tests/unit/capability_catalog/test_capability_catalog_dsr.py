"""DSR / erasure propagation for the capability catalog (PR 2, Phase A).

Proves the tables are part of the standard deletion plan and that a tenant-scoped erasure
(entity_id = tenant id, entity_field = "tenant_id") physically removes that tenant's rows via
``delete_by_entity`` while leaving other tenants intact — the same wiring
``DSARRequest.process_erasure`` drives in production.
"""

from __future__ import annotations

import pytest

from repositories.repos import reset_in_memory_stores
from shared.privacy.retention import DeletionPlan

from services.agent_access_intelligence.catalog_service import capability_catalog_service
from services.agent_access_intelligence.repositories import (
    CapabilityCatalogRepository,
    CapabilityInstallationRepository,
)


@pytest.fixture(autouse=True)
def _clean_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


def _fact(tenant_id: str, source_event_id: str):
    return {
        "tenant_id": tenant_id,
        "source_event_id": source_event_id,
        "event_name": "agent_tool_invocation_observed",
        "occurred_at": "2026-07-24T00:00:00Z",
        "agent_id": "agentA",
        "tool_name": "search",
        "server_name": "srvX",
        "provider": "acme",
    }


async def test_standard_plan_includes_capability_tables_as_hard_delete():
    plan = DeletionPlan(entity_id="t1", tenant_id="t1")
    plan.build_standard_plan()
    steps = {s["table"]: s for s in plan.steps if s["table"].startswith("capability_")}
    assert set(steps) == {"capability_catalog", "capability_installations"}
    for step in steps.values():
        assert step["behavior"] == "hard_delete"
        assert step["entity_field"] == "tenant_id"


async def test_tenant_erasure_removes_only_that_tenant():
    await capability_catalog_service.record_from_fact(_fact("t1", "a"))
    await capability_catalog_service.record_from_fact(_fact("t2", "b"))
    assert len(await capability_catalog_service.list_capabilities("t1")) == 1
    assert len(await capability_catalog_service.list_installations("t1")) == 1

    plan = DeletionPlan(entity_id="t1", tenant_id="t1")
    plan.build_standard_plan()
    await plan.execute(
        {
            "postgresql:capability_catalog": CapabilityCatalogRepository(),
            "postgresql:capability_installations": CapabilityInstallationRepository(),
        }
    )

    # t1 fully erased ...
    assert await capability_catalog_service.list_capabilities("t1") == []
    assert await capability_catalog_service.list_installations("t1") == []
    # ... t2 untouched.
    assert len(await capability_catalog_service.list_capabilities("t2")) == 1
