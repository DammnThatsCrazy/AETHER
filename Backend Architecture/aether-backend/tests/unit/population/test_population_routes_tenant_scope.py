"""Tenant-ownership guards on population routes (IDOR regression).

The population routes resolve groups with ``population_repo.find_by_id``, a
global lookup. A caller who knows another tenant's ``population_id`` must not
be able to read or mutate that group: every route that resolves a group by id
checks the row's ``tenant_id`` equals the request tenant and answers 404
(never 403) so a foreign group id is indistinguishable from a missing one.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from shared.common.common import NotFoundError
from services.consent.authority import ConsentReceiptRepository
from services.population.models import MembershipAdd
from services.population.registry import (
    definition_repo,
    membership_repo,
    population_repo,
)
from services.population.routes import (
    add_members,
    compare_groups,
    entity_memberships,
    explain_membership,
    get_group,
    group_intelligence,
    remove_member,
)


def _mock_graph() -> MagicMock:
    return MagicMock()


class FakeTenant:
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self.user_id = f"user_of_{tenant_id}"

    def require_permission(self, perm: str) -> None:
        return None


def _request(tenant_id: str):
    req = MagicMock()
    req.state.tenant = FakeTenant(tenant_id)
    return req


@pytest.fixture(autouse=True)
def _reset_stores():
    population_repo._store.clear()
    membership_repo._store.clear()
    definition_repo._store.clear()
    ConsentReceiptRepository()._store.clear()
    yield
    population_repo._store.clear()
    membership_repo._store.clear()
    definition_repo._store.clear()
    ConsentReceiptRepository()._store.clear()


async def _group(tenant_id: str) -> dict:
    from services.population.models import PopulationType

    return await population_repo.create_population(
        name="Owned segment",
        population_type=PopulationType.SEGMENT,
        definition={"filters": [{"field": "lifetime_value", "op": "gt", "value": 1}]},
        source_tag="tenant_scope_test",
        tenant_id=tenant_id,
    )


async def _grant(entity_id: str, tenant_id: str) -> None:
    """A governed join is consent-gated (P3.2): seed a server receipt."""
    await ConsentReceiptRepository().record(
        receipt_id=f"rcpt_{tenant_id}_{entity_id}",
        tenant_id=tenant_id,
        purpose="analytics",
        state="granted",
        subject_id=entity_id,
    )


# ── WRITE routes: cross-tenant id must be rejected before any mutation ───────


@pytest.mark.asyncio
async def test_cross_tenant_add_members_rejected():
    group = await _group("tenant_a")

    body = MembershipAdd(entity_ids=["entity_1"], source_tag="attack")
    with pytest.raises(NotFoundError):
        await add_members(
            population_id=group["id"],
            body=body,
            request=_request("tenant_b"),
            graph=MagicMock(),
            producer=MagicMock(),
        )

    # Nothing was written on the owner's group.
    assert await membership_repo.get_members(group["id"]) == []
    owner_row = await population_repo.find_by_id(group["id"])
    assert owner_row["member_count"] == 0


@pytest.mark.asyncio
async def test_cross_tenant_remove_member_rejected():
    group = await _group("tenant_a")

    with pytest.raises(NotFoundError):
        await remove_member(
            population_id=group["id"],
            entity_id="entity_1",
            request=_request("tenant_b"),
            reason="attack",
        )


@pytest.mark.asyncio
async def test_owner_can_add_members():
    """Positive control: the owning tenant's write still lands."""
    group = await _group("tenant_a")
    await _grant("entity_1", "tenant_a")
    await _grant("entity_2", "tenant_a")

    from shared.graph.graph import GraphClient

    graph = GraphClient()
    await graph.connect()
    producer = AsyncMock()
    resp = await add_members(
        population_id=group["id"],
        body=MembershipAdd(entity_ids=["entity_1", "entity_2"], source_tag="ok"),
        request=_request("tenant_a"),
        graph=graph,
        producer=producer,
    )
    assert resp["data"]["members_added"] == 2
    assert await membership_repo.count_active_members(group["id"]) == 2
    assert producer.publish.await_count == 2


# ── READ routes: cross-tenant id must 404, not leak the foreign group ────────


@pytest.mark.asyncio
async def test_cross_tenant_read_routes_reject():
    group = await _group("tenant_a")
    req_b = _request("tenant_b")

    for call in (
        lambda: get_group(group["id"], req_b),
        lambda: group_intelligence(group["id"], req_b),
        lambda: compare_groups(req_b, group_a=group["id"], group_b=group["id"]),
        lambda: explain_membership("entity_x", group["id"], req_b),
    ):
        with pytest.raises(NotFoundError):
            await call()


@pytest.mark.asyncio
async def test_cross_tenant_entity_memberships_do_not_leak():
    """Entity reads are tenant-scoped: B never sees A's membership row."""
    from services.population.models import MembershipBasis

    group_a = await _group("tenant_a")
    await membership_repo.add_member(
        population_id=group_a["id"],
        entity_id="entity_x",
        entity_type="user",
        basis=MembershipBasis.MANUAL,
        tenant_id="tenant_a",
    )

    seen_by_b = await entity_memberships("entity_x", _request("tenant_b"))
    assert seen_by_b["data"]["count"] == 0

    seen_by_a = await entity_memberships("entity_x", _request("tenant_a"))
    assert seen_by_a["data"]["count"] == 1


@pytest.mark.asyncio
async def test_owner_can_read_group():
    group = await _group("tenant_a")
    resp = await get_group(group["id"], _request("tenant_a"))
    assert resp["data"]["id"] == group["id"]
