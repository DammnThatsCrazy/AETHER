"""Population360 P3.2 — population definitions are immutable, versioned contracts.

A population's definition can never be silently redefined: ``create_population``
seeds an immutable v1 contract in the append-only ``population_definition_versions``
ledger, and the only way a definition changes is ``revise_definition`` — which
refuses a no-op bump and otherwise appends a NEW immutable version (old versions
stay reconstructable) with a documented transition. Membership computed against a
definition keeps that definition's version.

Suites pin: (1) create seeds v1; (2) a no-op revision is refused; (3) a revision
appends the next version + advances the projection, leaving v1 intact; (4) further
revisions chain supersedes; (5) a version row is immutable (second publish of the
same (population, version) is refused); (6) the revision/history routes are
tenant-owned.
"""

from __future__ import annotations

import pytest

from shared.common.common import BadRequestError, ConflictError, NotFoundError
from services.population.models import DefinitionRevision, PopulationType
from services.population.registry import (
    definition_repo,
    membership_repo,
    population_repo,
)
from services.population.routes import (
    group_definition_history,
    revise_group_definition,
)

_DEF_V1 = {"filters": [{"field": "lifetime_value", "op": "gt", "value": 1000}]}
_DEF_V2 = {"filters": [{"field": "lifetime_value", "op": "gt", "value": 5000}]}


class FakeTenant:
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self.user_id = f"user_of_{tenant_id}"

    def require_permission(self, perm: str) -> None:
        return None


def _request(tenant_id: str):
    from unittest.mock import MagicMock

    req = MagicMock()
    req.state.tenant = FakeTenant(tenant_id)
    return req


@pytest.fixture(autouse=True)
def _reset_stores():
    population_repo._store.clear()
    membership_repo._store.clear()
    definition_repo._store.clear()
    yield
    population_repo._store.clear()
    membership_repo._store.clear()
    definition_repo._store.clear()


async def _group(tenant_id: str = "tenant_a") -> dict:
    return await population_repo.create_population(
        name="Versioned segment",
        population_type=PopulationType.SEGMENT,
        definition=dict(_DEF_V1),
        source_tag="p3_2_test",
        tenant_id=tenant_id,
    )


# ── 1. Create seeds the immutable v1 contract ────────────────────────────────


@pytest.mark.asyncio
async def test_create_seeds_v1_definition_version():
    group = await _group("tenant_a")

    assert group["definition_version"] == "1"
    history = await definition_repo.history(group["id"])
    assert [v["definition_version"] for v in history] == ["1"]
    v1 = history[0]
    assert v1["definition"] == _DEF_V1
    assert v1["reason"] == "initial definition"
    assert v1["definition_hash"]
    assert v1["population_id"] == group["id"]
    # Record id is a deterministic digest prefix over (population, version).
    assert len(v1["id"]) == 24
    assert v1["id"].isalnum()


# ── 2. No-op revision is refused ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_noop_revision_is_refused():
    group = await _group("tenant_a")

    with pytest.raises(BadRequestError):
        await population_repo.revise_definition(
            group, dict(_DEF_V1), reason="identical no-op"
        )

    history = await definition_repo.history(group["id"])
    assert len(history) == 1  # nothing was appended
    fresh = await population_repo.find_by_id(group["id"])
    assert fresh["definition_version"] == "1"


# ── 3. Revision appends + advances, leaving v1 intact ────────────────────────


@pytest.mark.asyncio
async def test_revision_appends_version_and_advances_projection():
    group = await _group("tenant_a")

    updated, version = await population_repo.revise_definition(
        group, dict(_DEF_V2), reason="raise threshold after model retrain"
    )

    assert version["definition_version"] == "2"
    assert version["supersedes_version"] == "1"
    assert version["definition"] == _DEF_V2
    assert version["reason"] == "raise threshold after model retrain"

    # Projection advanced; v1 is still reconstructable verbatim.
    assert updated["definition"] == _DEF_V2
    assert updated["definition_version"] == "2"
    history = await definition_repo.history(group["id"])
    assert [v["definition_version"] for v in history] == ["1", "2"]
    assert history[0]["definition"] == _DEF_V1  # immutable: old cohort contract


# ── 4. Further revisions chain ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_further_revisions_chain_supersedes():
    group = await _group("tenant_a")
    v2_group = (await population_repo.revise_definition(
        group, dict(_DEF_V2), reason="first retrain"))[0]
    v3_group, v3 = await population_repo.revise_definition(
        v2_group, {"filters": [{"field": "lifetime_value", "op": "gt", "value": 9000}]},
        reason="second retrain",
    )

    assert v3["definition_version"] == "3"
    assert v3["supersedes_version"] == "2"
    assert [v["definition_version"] for v in await definition_repo.history(group["id"])] == ["1", "2", "3"]


# ── 5. A version row is immutable ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_version_cannot_be_republished():
    group = await _group("tenant_a")

    with pytest.raises(ConflictError):
        await definition_repo.record(group["id"], "1", dict(_DEF_V2),
                                     reason="attempted silent overwrite")


# ── 6. Routes are tenant-owned ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_revision_route_owner_and_foreign_tenant():
    group = await _group("tenant_a")
    body = DefinitionRevision(definition=dict(_DEF_V2), reason="retrain")

    # Owner: revision lands and history is readable.
    resp = await revise_group_definition(group["id"], body, _request("tenant_a"))
    assert resp["data"]["definition_version"] == "2"
    hist = await group_definition_history(group["id"], _request("tenant_a"))
    assert hist["data"]["count"] == 2

    # Foreign tenant: 404 on both the write and the read.
    with pytest.raises(NotFoundError):
        await revise_group_definition(group["id"], body, _request("tenant_b"))
    with pytest.raises(NotFoundError):
        await group_definition_history(group["id"], _request("tenant_b"))
