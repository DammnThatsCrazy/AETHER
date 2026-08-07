"""Computation repository behavior (in-memory backend): immutable insert,
supersession, restatement chain, tenant scoping."""

from __future__ import annotations

import pytest

from services.computation.repositories import (
    ComputationConflictError,
    ComputedResultsRepository,
)
from shared.computation.context import ComputationContext
from shared.computation.registry import get_definition
from shared.computation.runtime import money_result, new_run_id


@pytest.fixture()
def repo():
    return ComputedResultsRepository()


@pytest.fixture()
def ctx():
    return ComputationContext(tenant_id="t1", grain="campaign_day",
                             event_time_start="2026-01-01T00:00:00+00:00")


def _result(ctx, amount="100.00"):
    d = get_definition("campaign.media_spend")
    r = money_result(d, ctx, amount=amount, currency="USD", run_id=new_run_id())
    return r.model_dump(mode="json")


async def test_insert_and_get(repo, ctx):
    rec = await repo.insert_result(_result(ctx))
    got = await repo.get("t1", rec["result_id"])
    assert got is not None
    assert got["value"] == 100.0
    # tenant scoping
    assert await repo.get("other", rec["result_id"]) is None


async def test_active_duplicate_rejected(repo, ctx):
    await repo.insert_result(_result(ctx))
    with pytest.raises(ComputationConflictError):
        await repo.insert_result(_result(ctx, amount="200.00"))


async def test_supersede_preserves_prior_and_chains(repo, ctx):
    prior = await repo.insert_result(_result(ctx, amount="100.00"))
    new = await repo.supersede(
        "t1", prior["result_id"], _result(ctx, amount="150.00"),
        reason="provider correction",
    )
    # prior is retained, stamped superseded_by; new is active.
    prior_now = await repo.get("t1", prior["result_id"])
    assert prior_now["superseded_by"] == new["result_id"]
    active = await repo.get_active(
        "t1", "campaign.media_spend", "1", ctx.context_hash()
    )
    assert active["result_id"] == new["result_id"]
    assert active["value"] == 150.0
    # a fresh active insert is now allowed (the old one is superseded).
    chain = await repo.restatement_chain("t1", new["result_id"])
    assert any(c["reason"] == "provider correction" for c in chain)


async def test_list_excludes_superseded_by_default(repo, ctx):
    prior = await repo.insert_result(_result(ctx, amount="100.00"))
    await repo.supersede("t1", prior["result_id"], _result(ctx, amount="150.00"),
                         reason="fix")
    active = await repo.list_for_tenant("t1", definition_id="campaign.media_spend")
    assert len(active) == 1
    allrows = await repo.list_for_tenant(
        "t1", definition_id="campaign.media_spend", include_superseded=True
    )
    assert len(allrows) == 2


async def test_run_roundtrip(repo):
    run = await repo.insert_run(
        {"tenant_id": "t1", "definition_id": "campaign.ctr", "definition_version": "1",
         "status": "completed"}
    )
    got = await repo.get_run("t1", run["run_id"])
    assert got["status"] == "completed"
    assert await repo.get_run("other", run["run_id"]) is None
