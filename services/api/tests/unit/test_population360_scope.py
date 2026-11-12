from __future__ import annotations

import sys
import types

import pytest

from identity.population360.scope import RepositoryPopulationScopeReader


class _Repository:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = list(rows or [])

    async def find_by_id(self, _record_id):
        return self.row

    async def find_many(self, *, filters, limit):
        assert filters == {"population_id": "population-a"}
        return self.rows[:limit]


def _registry_module(population_repo, membership_repo):
    module = types.ModuleType("identity.population.registry")
    module.population_repo = population_repo
    module.membership_repo = membership_repo
    return module


@pytest.mark.asyncio
async def test_population_scope_returns_only_active_tenant_members_with_evidence(monkeypatch):
    module = _registry_module(
        _Repository(row={"id": "population-a", "tenant_id": "tenant-a"}),
        _Repository(
            rows=[
                {
                    "id": "membership-a",
                    "tenant_id": "tenant-a",
                    "population_id": "population-a",
                    "entity_id": "entity-a",
                    "membership_state": "active",
                },
                {
                    "id": "membership-b",
                    "tenant_id": "tenant-a",
                    "population_id": "population-a",
                    "entity_id": "entity-b",
                    "membership_state": "left",
                },
            ],
        ),
    )
    monkeypatch.setitem(sys.modules, "identity.population.registry", module)

    scope = await RepositoryPopulationScopeReader().resolve("tenant-a", "population-a", limit=10)

    assert scope.state == "available"
    assert scope.entity_ids == ("entity-a",)
    assert {ref.id for ref in scope.evidence_refs} == {"population-a", "membership-a"}
    assert all(
        ref.source in {"identity_populations", "identity_population_memberships"}
        for ref in scope.evidence_refs
    )


@pytest.mark.asyncio
async def test_population_scope_rejects_cross_tenant_membership(monkeypatch):
    module = _registry_module(
        _Repository(row={"id": "population-a", "tenant_id": "tenant-a"}),
        _Repository(
            rows=[
                {
                    "id": "membership-foreign",
                    "tenant_id": "tenant-b",
                    "population_id": "population-a",
                    "entity_id": "foreign-entity",
                    "membership_state": "active",
                }
            ],
        ),
    )
    monkeypatch.setitem(sys.modules, "identity.population.registry", module)

    scope = await RepositoryPopulationScopeReader().resolve("tenant-a", "population-a", limit=10)

    assert scope.state == "conflicted"
    assert scope.entity_ids == ()
    assert scope.reason == "population_membership_scope_mismatch"


@pytest.mark.asyncio
async def test_population_scope_marks_a_capped_member_read_incomplete(monkeypatch):
    module = _registry_module(
        _Repository(row={"id": "population-a", "tenant_id": "tenant-a"}),
        _Repository(
            rows=[
                {
                    "id": f"membership-{index}",
                    "tenant_id": "tenant-a",
                    "population_id": "population-a",
                    "entity_id": f"entity-{index}",
                    "membership_state": "active",
                }
                for index in range(3)
            ],
        ),
    )
    monkeypatch.setitem(sys.modules, "identity.population.registry", module)

    scope = await RepositoryPopulationScopeReader().resolve("tenant-a", "population-a", limit=2)

    assert scope.state == "truncated"
    assert scope.entity_ids == ()
    assert scope.reason == "population_membership_read_capped"
